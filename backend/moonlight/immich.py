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

Only images are used (videos skipped). The asset list is cached and refreshed every few minutes; if Immich can't be
reached the last good list is kept, and with none the screensaver falls back to its painted scenes.
"""
from __future__ import annotations

import asyncio
import json
import os
import socket
import time
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from . import db
from .common import log

TIMEOUT = httpx.Timeout(15.0, connect=5.0)
PAGE_SIZE = 1000
MAX_ASSETS = 5000  # per refresh, across every source: plenty for a slideshow, bounded memory
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
    r["favorites"] = bool(r["favorites"])
    r["memories"] = bool(r["memories"])
    return r


def save_config(c, cfg: dict) -> None:
    c.execute(
        "INSERT INTO immich(id, server_url, api_key, album_ids, favorites, memories, updated_at) "
        "VALUES(1, ?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET server_url=excluded.server_url, "
        "api_key=excluded.api_key, album_ids=excluded.album_ids, favorites=excluded.favorites, "
        "memories=excluded.memories, updated_at=excluded.updated_at",
        (cfg["server_url"], cfg["api_key"], json.dumps(cfg["album_ids"]), int(cfg["favorites"]),
         int(cfg["memories"]), db.now_iso()))


def delete_config(c) -> None:
    c.execute("DELETE FROM immich")


# ---------------------------------------------------------------- client

class Client:
    def __init__(self, server_url: str, api_key: str) -> None:
        self.server_url = normalize_url(server_url)
        self.base = self.server_url + "/api"
        self._key = api_key

    def http(self, timeout: httpx.Timeout = TIMEOUT) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self.base, timeout=timeout, transport=transport, follow_redirects=False,
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
                seen[a["id"]] = {"id": a["id"], "name": str(a.get("albumName") or "Untitled"),
                                 "asset_count": int(a.get("assetCount") or 0), "shared": bool(a.get("shared"))}
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
                body = {"filter": new, "size": PAGE_SIZE, **({"cursor": cursor} if cursor else {})}
            else:
                body = {**flat, "type": "IMAGE", "size": PAGE_SIZE, "page": page}
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


def photo_out(a: dict) -> dict:
    w, h = a.get("width"), a.get("height")
    exif = a.get("exifInfo") or {}
    if not (isinstance(w, int) and isinstance(h, int)):
        w, h = exif.get("exifImageWidth"), exif.get("exifImageHeight")
    return {
        "id": a["id"],
        "width": w if isinstance(w, int) and w > 0 else None,
        "height": h if isinstance(h, int) and h > 0 else None,
        "taken_at": (a.get("localDateTime") or a.get("fileCreatedAt") or None),
        "url": f"/api/immich/assets/{a['id']}/preview",
    }


# ---------------------------------------------------------------- cache

class Cache:
    """The chosen photos, refreshed at most every REFRESH_SECONDS. Also the proxy's allow-list."""

    def __init__(self) -> None:
        self.photos: list[dict] = []
        self.ids: set[str] = set()
        self.key: str | None = None  # which config the list belongs to
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
                           cfg["memories"]])

    def _due(self, key: str | None) -> bool:
        now = time.monotonic()
        if key != self.key:
            return True
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
        if not force and not self._due(key):
            return self
        async with self._get_lock():
            if not force and not self._due(key):
                return self
            if cfg is None:
                self.reset()
                return self
            if key != self.key:  # new server, key or albums: never serve the old list
                self.photos, self.ids, self.version = [], set(), None
                self.key = key
            self.tried_at = time.monotonic()
            try:
                photos, version = await self._fetch(cfg, tz)
            except ImmichError as e:
                self.status = "auth_failed" if isinstance(e, AuthFailed) else "error"
                self.error = str(e)
                log.warning("Immich refresh failed: %s", e)
                return self
            self.photos, self.ids = photos, {p["id"] for p in photos}
            self.version = version or self.version
            self.status, self.error = "ok", None
            self.fetched_at = time.monotonic()
            self.last_refresh = db.now_iso()
            return self

    async def _fetch(self, cfg: dict, tz: str) -> tuple[list[dict], str | None]:
        client = Client(cfg["server_url"], cfg["api_key"])
        found: dict[str, dict] = {}

        def add(assets: list[dict]) -> None:
            for a in assets:
                if len(found) >= MAX_ASSETS:
                    return
                if is_image(a) and a["id"] not in found:
                    found[a["id"]] = photo_out(a)

        async with client.http() as http:
            version = await client.version(http)
            for album_id in cfg["album_ids"]:
                add(await client.album_assets(http, album_id, MAX_ASSETS - len(found)))
            if cfg["favorites"] and len(found) < MAX_ASSETS:
                add(await client.favorite_assets(http, MAX_ASSETS - len(found)))
            if cfg["memories"] and len(found) < MAX_ASSETS:
                try:
                    today = datetime.now(ZoneInfo(tz)).date()
                except Exception:
                    today = date.today()
                try:
                    add(await client.memory_assets(http, today))
                except AuthFailed:
                    raise
                except ImmichError as e:  # optional extra: an older server or a key without memory.read
                    log.info("Immich memories skipped: %s", e)
        return list(found.values()), version


cache = Cache()
