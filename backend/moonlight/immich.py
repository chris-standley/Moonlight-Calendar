"""Immich client for the photo screensaver.

Moonlight talks to the family's Immich server with an API key (`x-api-key`) and proxies preview images to the
screens, so screens never see the key or talk to Immich. Written against the Immich API as of v3.3 (OpenAPI spec
3.3.1) and compatible with v1.1xx-v2.x:

- `GET  /api/server/version`  -> {major, minor, patch}         (no auth: used to report the version)
- `GET  /api/albums`          -> [{id, albumName, assetCount, ...}]           (permission album.read)
- `POST /api/search/metadata` -> {assets: {items: [Asset], nextPage}}         (asset.read)
  Album contents: since v3 `GET /api/albums/{id}` no longer lists assets, so they come from a metadata search with
  `albumIds`. The flat search fields (`albumIds`, `isFavorite`, `type`, `page`) are deprecated since v3.2 in favour
  of `filter` + `cursor`; they still work and are the only form before v3.2. If a server rejects them (400), the
  `filter` form is used instead.
- `GET  /api/memories?for=YYYY-MM-DD&type=on_this_day` -> [{assets: [Asset]}]  (memory.read, optional)
- `GET  /api/assets/{id}/thumbnail?size=preview` -> JPEG/WebP, EXIF orientation already applied (asset.view)

What is shown: the chosen albums (plus favourites and memories), or with mode "all" every album except the excluded
ones. With `festive` on, albums named for Christmas are hidden outside December, and in December only they and
winter albums are shown. The list is grouped by album (oldest photo first) so the screens can play one album
at a time; an album's photos are only fetched again when Immich says it changed. Only images are used (videos skipped). The asset list is cached and refreshed every few minutes; if Immich can't be
reached the last good list is kept, and with none the screensaver falls back to its painted scenes.
"""
from __future__ import annotations

import asyncio
import json
import math
import os
import re
import socket
import ssl
import time
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from . import db, ha_client
from .common import log

TIMEOUT = httpx.Timeout(15.0, connect=5.0)
PAGE_SIZE = 1000
MAX_ASSETS = 5000  # per refresh, across every source: plenty for a slideshow, bounded memory
HIDE_LIMIT = 20000  # photos read from each excluded or out-of-season album
# Album names (whole words, any case; digits may touch them, as in "Christmas2024").
FESTIVE = re.compile(r"(?<![a-z])(christmas|xmas|x-mas|festive|yule|yuletide|advent|santa|nativity|carols?|boxing day)(?![a-z])", re.I)
WINTER = re.compile(r"(?<![a-z])(winter|wintry|snow|snowy|snowman|snowmen|snowball|frost|frosty|blizzard|sledging|sledge|sled|"
                    r"skiing|ski|ice skating|icicles?)(?![a-z])", re.I)
MODES = ("albums", "all")
REFRESH_SECONDS = float(os.environ.get("MOONLIGHT_IMMICH_REFRESH", "300"))
RETRY_SECONDS = 60.0  # after a failed refresh, how soon to try again
HIDDEN_VISIBILITY = {"hidden", "locked"}

# Tests swap in an httpx.MockTransport; None = real network.
transport: httpx.AsyncBaseTransport | None = None

class ImmichError(Exception):
    """Immich couldn't be reached or answered with an error. The message is safe to show (never has the key)."""


class AuthFailed(ImmichError):
    pass


# ---------------------------------------------------------------- config

def normalize_url(raw: str) -> str:
    url = raw.strip().rstrip("/")
    if url.endswith("/api"):
        url = url[:-4]
    return url


def load_config(c) -> dict | None:
    r = db.row(c, "SELECT * FROM immich WHERE id = 1")
    if not r:
        return None
    r["album_ids"] = json.loads(r["album_ids"])
    r["mode"] = r.get("mode") if r.get("mode") in MODES else "albums"
    r["excluded_album_ids"] = json.loads(r.get("excluded_album_ids") or "[]")
    r["festive"] = bool(r.get("festive", 1))
    r["favorites"] = bool(r["favorites"])
    r["memories"] = bool(r["memories"])
    r["skip_cert_check"] = bool(r.get("skip_cert_check"))
    return r


def save_config(c, cfg: dict) -> None:
    c.execute(
        "INSERT INTO immich(id, server_url, api_key, album_ids, favorites, memories, skip_cert_check, mode, "
        "excluded_album_ids, festive, updated_at) VALUES(1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET "
        "server_url=excluded.server_url, api_key=excluded.api_key, album_ids=excluded.album_ids, "
        "favorites=excluded.favorites, memories=excluded.memories, skip_cert_check=excluded.skip_cert_check, "
        "mode=excluded.mode, excluded_album_ids=excluded.excluded_album_ids, festive=excluded.festive, "
        "updated_at=excluded.updated_at",
        (cfg["server_url"], cfg["api_key"], json.dumps(cfg["album_ids"]), int(cfg["favorites"]),
         int(cfg["memories"]), int(cfg.get("skip_cert_check", False)), cfg.get("mode", "albums"),
         json.dumps(cfg.get("excluded_album_ids", [])), int(cfg.get("festive", True)), db.now_iso()))


def delete_config(c) -> None:
    c.execute("DELETE FROM immich")


def household_today(tz: str) -> date:
    try:
        return datetime.now(ZoneInfo(tz)).date()
    except Exception:
        return date.today()


def is_festive(name: str) -> bool:
    return bool(FESTIVE.search(name))


def is_winter(name: str) -> bool:
    return bool(WINTER.search(name))


def december(cfg: dict | None, day: date) -> bool:
    """With the festive filter on, December shows only festive and winter albums (when there are any festive ones)."""
    return bool(cfg and cfg.get("festive", True) and day.month == 12)


# ---------------------------------------------------------------- client

class Client:
    def __init__(self, server_url: str, api_key: str, skip_cert_check: bool = False) -> None:
        self.server_url = normalize_url(server_url)
        self.base = self.server_url + "/api"
        self._key = api_key
        # Immich on the home network often has a self-signed certificate, or one for a domain name while Moonlight
        # reaches it by IP address; the household can choose to skip the check rather than give up HTTPS.
        self.verify = not skip_cert_check

    def http(self, timeout: httpx.Timeout = TIMEOUT) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self.base, timeout=timeout, transport=transport, follow_redirects=False, verify=self.verify,
                                 headers={"x-api-key": self._key, "Accept": "application/json"})

    def _fail(self, r: httpx.Response, what: str) -> ImmichError:
        if r.status_code == 401:
            return AuthFailed("Immich didn't accept the API key")
        if r.status_code == 403:
            return ImmichError(f"The API key isn't allowed to {what} (give it album.read, asset.read and asset.view)")
        if r.is_redirect:
            to = r.headers.get("location", "")
            return ImmichError(f"{self.server_url} redirects to {to or 'another address'}. "
                               "Enter Immich's own address instead, e.g. http://192.168.1.10:2283")
        if r.status_code in (502, 503, 504):
            return ImmichError(f"{self.server_url} answered {r.status_code} ({r.reason_phrase or 'gateway error'}): "
                               "Immich is starting, stopped, or behind a proxy that can't reach it. "
                               "Check Immich is running, or enter its own address and port (2283 by default)")
        if r.status_code == 400 and "https" in r.text.lower() and self.server_url.startswith("http://"):
            return ImmichError(f"{self.server_url} only speaks HTTPS: start the address with https://")
        if r.status_code == 404:
            return ImmichError(f"{self.server_url} has no Immich API (404). Enter the address you open Immich at, "
                               "without /photos or other paths")
        return ImmichError(f"Immich answered {r.status_code} when asked to {what}")

    def _unreachable(self, e: httpx.HTTPError) -> ImmichError:
        """A message that says what to try, for a request that never got an answer."""
        host = httpx.URL(self.server_url).host
        cause = e.__cause__ or e.__context__
        if isinstance(e, httpx.ConnectError) and isinstance(cause, socket.gaierror):
            tip = (" Addresses ending in .local often don't work from inside an add-on: use the IP address instead, "
                   "e.g. http://192.168.1.10:2283" if host.endswith(".local") else " Check the spelling, or use the IP address")
            return ImmichError(f"Couldn't find {host} on the network.{tip}")
        if isinstance(cause, ssl.SSLCertVerificationError) or "CERTIFICATE_VERIFY_FAILED" in str(e):
            return ImmichError(f"{self.server_url} has a certificate Moonlight can't check (self-signed, or made for a "
                               "domain name rather than this address). Turn on \"Skip certificate check\", or use "
                               "the name the certificate was made for")
        if isinstance(cause, ssl.SSLError) or "WRONG_VERSION_NUMBER" in str(e):
            return ImmichError(f"{self.server_url} doesn't speak HTTPS: start the address with http://")
        if isinstance(e, httpx.TimeoutException):
            return ImmichError(f"{self.server_url} didn't answer in time. Check the address and that Immich is running")
        if isinstance(e, httpx.ConnectError):
            return ImmichError(f"Nothing answered at {self.server_url}. Check Immich is running and the port "
                               "(2283 by default)")
        return ImmichError(f"Couldn't reach Immich at {self.server_url} ({type(e).__name__})")

    async def _call(self, http: httpx.AsyncClient, method: str, path: str, what: str, **kw) -> Any:
        try:
            r = await http.request(method, path, **kw)
        except httpx.HTTPError as e:
            raise self._unreachable(e) from None
        if r.status_code != 200:
            raise self._fail(r, what)
        try:
            return r.json()
        except ValueError:
            raise ImmichError(f"{self.server_url} doesn't look like an Immich server") from None

    async def version(self, http: httpx.AsyncClient) -> str | None:
        try:
            v = await self._call(http, "GET", "/server/version", "report its version")
            return f"{v['major']}.{v['minor']}.{v['patch']}"
        except (ImmichError, KeyError, TypeError):
            return None

    async def albums(self, http: httpx.AsyncClient | None = None) -> list[dict]:
        """Every album the key's user owns or has been shared, by name."""
        if http is None:
            async with self.http() as h:
                return await self.albums(h)
        raw = await self._call(http, "GET", "/albums", "list albums")
        if not isinstance(raw, list):
            raise ImmichError(f"{self.server_url} doesn't look like an Immich server")
        seen: dict[str, dict] = {}
        for a in raw:
            if isinstance(a, dict) and isinstance(a.get("id"), str) and a["id"] not in seen:
                stamps = [a.get(k) for k in ("lastModifiedAssetTimestamp", "updatedAt") if isinstance(a.get(k), str)]
                seen[a["id"]] = {"id": a["id"], "name": str(a.get("albumName") or "Untitled"),
                                 "asset_count": int(a.get("assetCount") or 0), "shared": bool(a.get("shared")),
                                 "updated_at": max(stamps) if stamps else None}
        return sorted(seen.values(), key=lambda a: a["name"].lower())

    async def test(self) -> dict:
        async with self.http() as http:
            albums = await self.albums(http)
            version = await self.version(http)
        return {"ok": True, "version": version, "albums": albums}

    async def _search(self, http: httpx.AsyncClient, flat: dict, new: dict, limit: int) -> list[dict]:
        """POST /search/metadata, all pages, images only. `flat` = pre-3.2 fields, `new` = 3.2+ `filter`."""
        out: list[dict] = []
        page: Any = 1
        cursor: str | None = None
        use_filter = False
        while len(out) < limit:
            if use_filter:
                body = {"filter": new, "size": PAGE_SIZE, "withExif": True, **({"cursor": cursor} if cursor else {})}
            else:
                body = {**flat, "type": "IMAGE", "size": PAGE_SIZE, "page": page, "withExif": True}
            try:
                res = await self._call(http, "POST", "/search/metadata", "search photos", json=body)
            except ImmichError as e:
                if not use_filter and page == 1 and "answered 400" in str(e):
                    use_filter = True  # a server that dropped the deprecated fields
                    continue
                raise
            assets = (res or {}).get("assets") or {}
            out.extend(a for a in assets.get("items") or [] if isinstance(a, dict))
            if use_filter:
                cursor = assets.get("nextCursor")
                if not cursor:
                    break
            else:
                nxt = assets.get("nextPage")
                if not nxt:
                    break
                page = int(nxt) if str(nxt).isdigit() else page + 1
        return out

    async def album_assets(self, http: httpx.AsyncClient, album_id: str, limit: int) -> list[dict]:
        return await self._search(http, {"albumIds": [album_id]},
                                  {"albumIds": {"any": [album_id]}, "type": {"eq": "IMAGE"}}, limit)

    async def favorite_assets(self, http: httpx.AsyncClient, limit: int) -> list[dict]:
        return await self._search(http, {"isFavorite": True},
                                  {"isFavorite": {"eq": True}, "type": {"eq": "IMAGE"}}, limit)

    async def memory_assets(self, http: httpx.AsyncClient, day: date) -> list[dict]:
        raw = await self._call(http, "GET", "/memories", "read memories",
                               params={"for": day.isoformat(), "type": "on_this_day"})
        return [a for m in raw if isinstance(m, dict) for a in (m.get("assets") or []) if isinstance(a, dict)]

    async def preview(self, asset_id: str) -> tuple[httpx.AsyncClient, httpx.Response]:
        """Open a streaming request for an asset's preview. The caller closes both."""
        http = self.http(httpx.Timeout(30.0, connect=5.0))
        try:
            r = await http.send(http.build_request("GET", f"/assets/{asset_id}/thumbnail", params={"size": "preview"},
                                                  headers={"Accept": "image/*"}),
                                stream=True)
        except httpx.HTTPError as e:
            await http.aclose()
            raise self._unreachable(e) from None
        if r.status_code != 200:
            await r.aclose()
            await http.aclose()
            raise self._fail(r, "show photos")
        return http, r


def is_image(a: dict) -> bool:
    return (a.get("type") == "IMAGE" and not a.get("isTrashed") and a.get("visibility") not in HIDDEN_VISIBILITY
            and isinstance(a.get("id"), str))


def _distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6_371_000 * math.asin(min(1.0, math.sqrt(h)))


def place_name(exif: dict, zones: list[dict]) -> str | None:
    """Where a photo was taken: the Home Assistant zone it falls in (the smallest, if zones overlap), else the
    town Immich found from its GPS (else the region or country). None without location data."""
    lat, lon = exif.get("latitude"), exif.get("longitude")
    if isinstance(lat, (int, float)) and isinstance(lon, (int, float)) and not isinstance(lat, bool):
        inside = [z for z in zones if _distance_m(lat, lon, z["latitude"], z["longitude"]) <= z["radius"]]
        if inside:
            return min(inside, key=lambda z: z["radius"])["name"]
    for key in ("city", "state", "country"):
        v = exif.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def slim(a: dict) -> dict:
    """What photo_out needs of an asset, kept between refreshes for albums that haven't changed."""
    exif = a.get("exifInfo") if isinstance(a.get("exifInfo"), dict) else {}
    keep = ("id", "type", "isTrashed", "visibility", "width", "height", "localDateTime", "fileCreatedAt")
    return {**{k: a.get(k) for k in keep}, "exifInfo": {k: exif.get(k) for k in (
        "latitude", "longitude", "city", "state", "country", "exifImageWidth", "exifImageHeight")}}


def photo_out(a: dict, zones: list[dict] | None = None) -> dict:
    w, h = a.get("width"), a.get("height")
    exif = a.get("exifInfo") or {}
    if not (isinstance(w, int) and isinstance(h, int)):
        w, h = exif.get("exifImageWidth"), exif.get("exifImageHeight")
    return {
        "id": a["id"],
        "width": w if isinstance(w, int) and w > 0 else None,
        "height": h if isinstance(h, int) and h > 0 else None,
        "taken_at": (a.get("localDateTime") or a.get("fileCreatedAt") or None),
        "place": place_name(exif if isinstance(exif, dict) else {}, zones or []),
        "url": f"/api/immich/assets/{a['id']}/preview",
    }


# ---------------------------------------------------------------- cache

class Cache:
    """The chosen photos, refreshed at most every REFRESH_SECONDS. Also the proxy's allow-list."""

    def __init__(self) -> None:
        self.photos: list[dict] = []
        self.albums: list[dict] = []  # [{id, name, updated_at, photos: [id]}]: what the screens play, album by album
        self._album_assets: dict[str, tuple[Any, list[dict]]] = {}  # album id -> (what Immich said of it, its assets)
        self.ids: set[str] = set()
        self.key: str | None = None  # which config the list belongs to
        self.december = False  # the festive filter's December rule applied when the list was made
        self.festive_now = False  # the list is only festive and winter albums
        self.day: str | None = None  # with "on this day" memories, the day they are for
        self.fetched_at = 0.0
        self.tried_at = 0.0
        self.status = "unconfigured"  # unconfigured | ok | auth_failed | error
        self.error: str | None = None
        self.last_refresh: str | None = None
        self.version: str | None = None
        self._lock: asyncio.Lock | None = None
        self._lock_loop: asyncio.AbstractEventLoop | None = None

    def _get_lock(self) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        if self._lock is None or self._lock_loop is not loop:  # tests run each request on a fresh loop
            self._lock, self._lock_loop = asyncio.Lock(), loop
        return self._lock

    def reset(self) -> None:
        self.__init__()  # type: ignore[misc]

    @staticmethod
    def config_key(cfg: dict | None) -> str | None:
        if not cfg:
            return None
        return json.dumps([cfg["server_url"], cfg["api_key"], sorted(cfg["album_ids"]), cfg["favorites"],
                           cfg["memories"], cfg.get("skip_cert_check", False), cfg.get("mode", "albums"),
                           sorted(cfg.get("excluded_album_ids", [])), cfg.get("festive", True)])

    def _due(self, key: str | None, season: bool = False, day: str | None = None) -> bool:
        now = time.monotonic()
        if key != self.key:
            return True
        if key is not None and (season != self.december or day != self.day):
            return True  # December started or ended, or a new day's memories
        if self.status in ("ok",):
            return now - self.fetched_at >= REFRESH_SECONDS
        return now - self.tried_at >= RETRY_SECONDS

    def mark_failed(self, e: ImmichError) -> None:
        """A proxied preview failed: report it, and re-check Immich on the next request after RETRY_SECONDS."""
        self.status = "auth_failed" if isinstance(e, AuthFailed) else "error"
        self.error = str(e)
        self.tried_at = time.monotonic()

    async def get(self, force: bool = False) -> "Cache":
        with db.connect() as c:
            cfg = load_config(c)
            tz = db.get_setting(c, "timezone", db.default_timezone())
        key = self.config_key(cfg)
        today = household_today(tz)
        season = december(cfg, today)
        day = today.isoformat() if cfg and cfg.get("memories") else None
        if not force and not self._due(key, season, day):
            return self
        async with self._get_lock():
            if not force and not self._due(key, season, day):
                return self
            if cfg is None:
                self.reset()
                return self
            if key != self.key:  # new server, key or albums: never serve the old list
                self.photos, self.albums, self.ids, self.version = [], [], set(), None
                self._album_assets = {}
                self.key = key
            self.tried_at = time.monotonic()
            try:
                photos, albums, version, festive_now = await self._fetch(cfg, today)
            except ImmichError as e:
                self.status = "auth_failed" if isinstance(e, AuthFailed) else "error"
                self.error = str(e)
                log.warning("Immich refresh failed: %s", e)
                return self
            self.photos, self.albums, self.ids = photos, albums, {p["id"] for p in photos}
            self.december, self.festive_now, self.day = season, festive_now, day
            self.version = version or self.version
            self.status, self.error = "ok", None
            self.fetched_at = time.monotonic()
            self.last_refresh = db.now_iso()
            return self

    async def _album(self, client: Client, http: httpx.AsyncClient, album: dict, limit: int) -> list[dict]:
        """An album's assets, from the last refresh if Immich reports the same change time and size."""
        stamp = (album["updated_at"], album["asset_count"])
        had = self._album_assets.get(album["id"])
        if had and had[0] == stamp and stamp[0] is not None and len(had[1]) <= limit:
            return had[1]
        assets = [slim(a) for a in await client.album_assets(http, album["id"], limit) if is_image(a)]
        self._album_assets[album["id"]] = (stamp, assets)
        return assets

    async def _fetch(self, cfg: dict, today: date) -> tuple[list[dict], list[dict], str | None, bool]:
        client = Client(cfg["server_url"], cfg["api_key"], cfg.get("skip_cert_check", False))
        found: dict[str, dict] = {}
        groups: list[dict] = []
        zones = await ha_client.zones()  # friendly place names ("Home") for photos taken inside a zone

        def add(group: dict, assets: list[dict], hide: set[str]) -> None:
            ids = []
            for a in sorted((a for a in assets if is_image(a) and a["id"] not in hide),
                            key=lambda a: str(a.get("localDateTime") or a.get("fileCreatedAt") or "")):
                if a["id"] not in found:
                    if len(found) >= MAX_ASSETS:
                        continue
                    found[a["id"]] = photo_out(a, zones)
                if a["id"] not in ids:
                    ids.append(a["id"])
            if ids:
                groups.append({**group, "photos": ids})

        async with client.http() as http:
            version = await client.version(http)
            albums = {a["id"]: a for a in await client.albums(http)}
            excluded = set(cfg.get("excluded_album_ids", [])) if cfg.get("mode") == "all" else set()
            festive = {i for i, a in albums.items() if is_festive(a["name"])} if cfg.get("festive", True) else set()
            # December: the festive and winter albums and nothing else (unless there are no festive albums at all).
            season = december(cfg, today) and bool(festive - excluded)
            if season:
                hidden = excluded
                shown = [i for i, a in albums.items() if (i in festive or is_winter(a["name"])) and i not in excluded]
            else:
                hidden = festive | excluded  # the rest of the year festive albums are hidden, even if chosen
                pick = albums if cfg.get("mode") == "all" else cfg["album_ids"]
                shown = [i for i in pick if i in albums and i not in hidden]
            # Most recently changed first, so if the cap is reached it's old albums that miss out.
            shown.sort(key=lambda i: albums[i]["updated_at"] or "", reverse=True)
            hide: set[str] = set()
            for album_id in sorted(i for i in hidden if i in albums):  # a hidden album's photos stay hidden elsewhere
                hide.update(a["id"] for a in await self._album(client, http, albums[album_id], HIDE_LIMIT))
            for album_id in shown:
                if len(found) >= MAX_ASSETS:
                    break
                a = albums[album_id]
                add({"id": a["id"], "name": a["name"], "updated_at": a["updated_at"]},
                    await self._album(client, http, a, MAX_ASSETS), hide)
            if not season and cfg["favorites"] and len(found) < MAX_ASSETS:
                add({"id": "favorites", "name": "Favourites", "updated_at": None},
                    await client.favorite_assets(http, MAX_ASSETS - len(found)), hide)
            if not season and cfg["memories"] and len(found) < MAX_ASSETS:
                try:
                    add({"id": "on-this-day", "name": "On this day", "updated_at": today.isoformat()},
                        await client.memory_assets(http, today), hide)
                except AuthFailed:
                    raise
                except ImmichError as e:  # optional extra: an older server or a key without memory.read
                    log.info("Immich memories skipped: %s", e)
        self._album_assets = {k: v for k, v in self._album_assets.items() if k in albums}
        return list(found.values()), groups, version, season


cache = Cache()
