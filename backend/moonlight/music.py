"""The Music tab: the queue, the library, playing things now / next / at the end, and grouping rooms, for the speaker
set for a screen (see media.py for now playing and the speaker itself).

Everything goes through Home Assistant except one optional extra:
- Library: HA's `media_player/browse_media` on the speaker (Music Assistant's artists, albums, playlists, podcasts,
  radio...; a Sonos speaker's favourites), and `music_assistant.search`. Thumbnails are fetched by the backend and
  served at /api/media/thumb, keyed by a hash, so screens never see HA or Music Assistant addresses or tokens.
- Play: `music_assistant.play_media` for a Music Assistant speaker, else `media_player.play_media`, with enqueue
  replace (play now), next, or add (end of the queue).
- Queue: a Sonos speaker's whole queue from `sonos.get_queue` (jump to / remove a track with `sonos.play_queue` /
  `sonos.remove_from_queue`). For a Music Assistant speaker HA only gives the current and next track
  (`music_assistant.get_queue`); with a Music Assistant token in Settings (key `music_assistant`), Moonlight asks
  Music Assistant itself for the whole queue (and can jump, remove, and move a track up to play next).
- Rooms: the speaker's `group_members`; `media_player.join` / `media_player.unjoin`, and each room's own volume.
  Only players of the same kind (Music Assistant or not) that support grouping are offered.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import re
import time
import uuid
from collections import OrderedDict
from typing import Any, Callable
from urllib.parse import urlsplit

import httpx

from . import db
from .media import ACTIVE, ENTITY_RE, FEATURES, MediaError, MediaService, _describe, _num, is_music_assistant

log = logging.getLogger("moonlight.music")

THUMBS_KEPT = 4000           # thumbnail keys remembered (key -> source URL)
THUMB_CACHE = 300            # thumbnails kept in memory
THUMB_MAX_BYTES = 3 * 1024 * 1024
QUEUE_AHEAD = 80             # tracks after the current one sent to screens
BROWSE_MAX = 500
SONOS_TTL = 600
ENQUEUE = ("replace", "next", "add", "play")
MA_TYPES = ("artist", "album", "audiobook", "folder", "playlist", "podcast", "track", "radio")
SEARCH_TYPES = ["album", "artist", "playlist", "podcast", "audiobook", "radio", "track"]
SETTINGS_KEY = "music_assistant"


# ---------------------------------------------------------------- thumbnails

class Thumbs:
    """Picture URLs handed out as /api/media/thumb?k=<hash>; only URLs Moonlight has handed out can be fetched."""

    def __init__(self) -> None:
        self.urls: OrderedDict[str, str] = OrderedDict()
        self.cache: OrderedDict[str, tuple[bytes, str]] = OrderedDict()

    def url(self, src: Any) -> str | None:
        if not isinstance(src, str) or not src or not (src.startswith("/") or src.startswith(("http://", "https://"))):
            return None
        src = _smaller(src)
        key = hashlib.sha256(src.encode()).hexdigest()[:24]
        self.urls[key] = src
        self.urls.move_to_end(key)
        while len(self.urls) > THUMBS_KEPT:
            self.urls.popitem(last=False)
        return f"/api/media/thumb?k={key}"


def _smaller(src: str) -> str:
    # Music Assistant's image proxy sends the full-size picture for size=0; a list only needs a thumbnail.
    return re.sub(r"([?&]size=)0(?=&|$)", r"\g<1>300", src) if "/imageproxy" in src else src


# ---------------------------------------------------------------- Music Assistant (direct, optional)

def ma_settings(c) -> dict:
    saved = db.get_setting(c, SETTINGS_KEY, {}) or {}
    return {"url": str(saved.get("url") or ""), "token": str(saved.get("token") or "")}


def ma_url_ok(url: str) -> bool:
    parts = urlsplit(url)
    return parts.scheme in ("http", "https") and bool(parts.hostname)


def ws_url(url: str) -> str:
    base = url.rstrip("/")
    base = re.sub(r"^http", "ws", base)
    return base if base.endswith("/ws") else base + "/ws"


class MAError(MediaError):
    pass


class MAClient:
    """Music Assistant's own WebSocket API: server info, `auth` with a long-lived token, then commands. One short
    connection per request (screens ask for the queue now and then; nothing is kept open)."""

    def __init__(self, url: str, token: str, ws_connect: Callable[[str], Any] | None = None) -> None:
        self.url = url.rstrip("/")
        self.token = token
        self.ws_connect = ws_connect or _default_connect
        self.base_url = self.url

    async def run(self, *commands: tuple[str, dict]) -> list[Any]:
        try:
            async with self.ws_connect(ws_url(self.url)) as ws:
                info = json.loads(await ws.recv())
                if not isinstance(info, dict) or "server_version" not in info:
                    raise MAError("That doesn't look like a Music Assistant server")
                self.base_url = (info.get("internal_url") or info.get("base_url") or self.url).rstrip("/")
                if int(info.get("schema_version") or 0) >= 28:
                    ok = await self._send(ws, "auth", {"token": self.token})
                    if not ok:
                        raise MAError("Music Assistant didn't accept the token", 400)
                return [await self._send(ws, cmd, args) for cmd, args in commands]
        except MAError:
            raise
        except Exception as e:  # network, closed socket, bad JSON
            raise MAError(f"Couldn't reach Music Assistant ({_describe(e)})")

    async def _send(self, ws, command: str, args: dict) -> Any:
        mid = uuid.uuid4().hex
        await ws.send(json.dumps({"message_id": mid, "command": command, "args": args}))
        partial: list | None = None
        while True:
            msg = json.loads(await ws.recv())
            if not isinstance(msg, dict) or msg.get("message_id") != mid:
                continue  # events
            if "error_code" in msg:
                detail = msg.get("details") or msg.get("error_code")
                if command == "auth":
                    raise MAError("Music Assistant didn't accept the token", 400)
                raise MAError(f"Music Assistant said no to {command}: {detail}", 400)
            if msg.get("partial"):
                partial = (partial or []) + list(msg.get("result") or [])
                continue
            result = msg.get("result")
            return partial + list(result or []) if partial is not None else result

    def image_url(self, image: Any) -> str | None:
        if not isinstance(image, dict) or not image.get("path"):
            return None
        if image.get("remotely_accessible"):
            return str(image["path"])
        if image.get("proxy_id"):
            return f"{self.base_url}/imageproxy/{image['proxy_id']}?size=300"
        from urllib.parse import quote

        return (f"{self.base_url}/imageproxy?path={quote(quote(str(image['path'])))}"
                f"&provider={quote(str(image.get('provider') or ''))}&size=300")


def _default_connect(url: str):
    from websockets.asyncio.client import connect

    return connect(url, open_timeout=8, max_size=16 * 1024 * 1024)


_ma_connect: Callable[[str], Any] | None = None  # tests


def set_ma_connect(fn: Callable[[str], Any] | None) -> None:
    global _ma_connect
    _ma_connect = fn


def ma_client() -> MAClient | None:
    with db.connect() as c:
        s = ma_settings(c)
    if not s["token"]:
        return None
    return MAClient(s["url"] or _detected.get("url") or "", s["token"], _ma_connect)


_detected: dict[str, str] = {}


def note_ma_url(src: Any) -> None:
    """Music Assistant's own address, learnt from the image URLs it hands Home Assistant (its imageproxy)."""
    if isinstance(src, str) and "/imageproxy" in src and src.startswith(("http://", "https://")):
        p = urlsplit(src)
        _detected["url"] = f"{p.scheme}://{p.netloc}"


# ---------------------------------------------------------------- helpers

class Music:
    """Per-service state: thumbnails, which entities are Sonos ones."""

    def __init__(self, svc: MediaService, clock: Callable[[], float] = time.monotonic) -> None:
        self.svc = svc
        self.clock = clock
        self.thumbs = Thumbs()
        self._sonos: tuple[float, set[str]] | None = None
        self._entry: str | None = None

    # ---- what kind of player
    async def sonos_entities(self) -> set[str]:
        if self._sonos and self.clock() - self._sonos[0] < SONOS_TTL:
            return self._sonos[1]
        found: set[str] = set()
        try:
            async with self.svc._client() as client:
                r = await client.post("/template", json={"template": "{{ integration_entities('sonos') | list | tojson }}"})
            if r.status_code == 200:
                val = json.loads(r.text)
                found = {e for e in val if isinstance(e, str) and ENTITY_RE.match(e)}
        except Exception as e:
            log.info("Couldn't list Sonos players: %s", _describe(e))
            return self._sonos[1] if self._sonos else set()
        self._sonos = (self.clock(), found)
        return found

    async def ma_entry(self) -> str | None:
        if self._entry:
            return self._entry
        try:
            async with self.svc._client() as client:
                r = await client.get("/config/config_entries/entry", params={"domain": "music_assistant"})
            r.raise_for_status()
            entries = [e for e in r.json() if isinstance(e, dict) and e.get("state") in (None, "loaded")]
        except Exception as e:
            log.info("Couldn't find the Music Assistant integration: %s", _describe(e))
            return None
        self._entry = entries[0]["entry_id"] if entries else None
        return self._entry

    async def _refresh(self, *entities: str) -> None:
        changed = False
        for e in entities:
            with contextlib.suppress(Exception):
                changed |= await self.svc.refresh(e)
        if changed:
            self.svc.notify()

    async def browse_any_ma(self) -> None:
        """Ask Music Assistant (through HA) for a few library items, to learn its address from their images."""
        entry = await self.ma_entry()
        if not entry:
            return
        for mtype in ("playlist", "album", "radio"):
            resp = await self.svc.call_service("music_assistant", "get_library", {
                "config_entry_id": entry, "media_type": mtype, "limit": 3}, return_response=True)
            for it in ((resp or {}).get("service_response", resp) or {}).get("items") or []:
                if isinstance(it, dict):
                    note_ma_url(it.get("image"))
            if _detected.get("url"):
                return

    # ---- library
    def item(self, child: dict) -> dict:
        thumb = child.get("thumbnail")
        note_ma_url(thumb)
        return {
            "id": str(child.get("media_content_id") or ""),
            "type": str(child.get("media_content_type") or ""),
            "title": str(child.get("title") or ""),
            "subtitle": None,
            "kind": str(child.get("media_class") or ""),
            "can_play": bool(child.get("can_play")),
            "can_expand": bool(child.get("can_expand")),
            "thumb": self.thumbs.url(thumb),
        }

    async def browse(self, entity: str, media_id: str | None, media_type: str | None) -> dict:
        cmd: dict = {"type": "media_player/browse_media", "entity_id": entity}
        if media_id is not None or media_type:
            cmd["media_content_id"] = media_id or ""
            cmd["media_content_type"] = media_type or ""
        errors: list[str] = []
        try:
            got, = await self.svc._ws_commands(cmd, errors=errors)
        except MediaError:
            raise
        except Exception as e:
            raise MediaError(f"Home Assistant is unreachable ({_describe(e)})")
        if not isinstance(got, dict):
            raise MediaError("Couldn't open that" + (f": {errors[0]}" if errors else ""), 400 if errors else 502)
        children = [c for c in got.get("children") or [] if isinstance(c, dict)
                    and not str(c.get("media_content_id") or "").startswith("media-source://")
                    and c.get("media_class") != "app"]
        here = self.item(got)
        return {**here, "items": [self.item(c) for c in children[:BROWSE_MAX]], "more": max(0, len(children) - BROWSE_MAX)}

    async def search(self, entity_state: dict | None, query: str) -> list[dict]:
        if not is_music_assistant((entity_state or {}).get("attributes") or {}):
            raise MediaError("Search needs a Music Assistant speaker", 409)
        entry = await self.ma_entry()
        if not entry:
            raise MediaError("Music Assistant isn't set up in Home Assistant", 409)
        resp = await self.svc.call_service("music_assistant", "search", {
            "config_entry_id": entry, "name": query, "media_type": SEARCH_TYPES, "limit": 12,
        }, return_response=True)
        got = (resp or {}).get("service_response", resp) or {}
        out = []
        for group in ("albums", "artists", "playlists", "podcasts", "audiobooks", "radio", "tracks"):
            for it in got.get(group) or []:
                if isinstance(it, dict) and it.get("uri") and it.get("name"):
                    out.append(self.ma_item(it))
        return out

    def ma_item(self, it: dict) -> dict:
        mtype = str(it.get("media_type") or "")
        artists = [a.get("name") for a in it.get("artists") or [] if isinstance(a, dict) and a.get("name")]
        note_ma_url(it.get("image"))
        return {
            "id": str(it["uri"]), "type": mtype, "title": str(it["name"]),
            "subtitle": ", ".join(artists) or None, "kind": mtype, "can_play": True,
            "can_expand": mtype in ("artist", "album", "playlist", "podcast", "audiobook"),
            "thumb": self.thumbs.url(it.get("image")),
        }

    async def play(self, entity: str, state: dict | None, media_id: str, media_type: str, enqueue: str) -> None:
        if enqueue not in ENQUEUE:
            raise MediaError("enqueue must be one of: " + ", ".join(ENQUEUE), 400)
        attrs = (state or {}).get("attributes") or {}
        if is_music_assistant(attrs):
            data: dict = {"entity_id": entity, "media_id": media_id, "enqueue": enqueue}
            if media_type in MA_TYPES:
                data["media_type"] = media_type
            await self.svc.call_service("music_assistant", "play_media", data)
        else:
            data = {"entity_id": entity, "media_content_id": media_id, "media_content_type": media_type or "music"}
            if int(_num(attrs.get("supported_features")) or 0) & FEATURES["media_enqueue"]:
                data["enqueue"] = enqueue
            await self.svc.call_service("media_player", "play_media", data)
        await self._refresh(entity)

    # ---- queue
    async def queue(self, entity: str, state: dict | None, art_url: str | None) -> dict:
        attrs = (state or {}).get("attributes") or {}
        out = {"source": "none", "full": False, "total": 0, "current": None, "items": [],
               "can_jump": False, "can_remove": False, "can_move": False}
        if state is None:
            return out
        if is_music_assistant(attrs):
            queue_id = attrs.get("active_queue") if isinstance(attrs.get("active_queue"), str) else entity
            ma = ma_client()
            if ma is not None and ma.url:
                try:
                    return await self._ma_queue(ma, queue_id, art_url)
                except MAError as e:
                    log.info("Music Assistant queue: %s; using Home Assistant's", e)
            return await self._ha_ma_queue(entity, art_url)
        if entity in await self.sonos_entities():
            return await self._sonos_queue(entity, attrs, art_url)
        return out

    async def _ha_ma_queue(self, entity: str, art_url: str | None) -> dict:
        resp = await self.svc.call_service("music_assistant", "get_queue", {"entity_id": entity}, return_response=True)
        got = (resp or {}).get("service_response", resp) or {}
        q = got.get(entity) or next(iter(got.values()), {}) if isinstance(got, dict) else {}
        q = q if isinstance(q, dict) else {}
        items = []
        cur = q.get("current_index")
        for i, key in enumerate(("current_item", "next_item")):
            it = q.get(key)
            if isinstance(it, dict):
                items.append(self._ma_queue_item(it, None if cur is None else cur + i, i == 0 and key == "current_item",
                                                 art_url if key == "current_item" else None))
        return {"source": "music_assistant", "full": False, "total": int(_num(q.get("items")) or 0),
                "current": cur if isinstance(cur, int) else None, "items": items,
                "can_jump": False, "can_remove": False, "can_move": False}

    def _ma_queue_item(self, it: dict, index: int | None, current: bool, art_url: str | None,
                       ma: MAClient | None = None) -> dict:
        mi = it.get("media_item") if isinstance(it.get("media_item"), dict) else {}
        artists = [a.get("name") for a in mi.get("artists") or [] if isinstance(a, dict) and a.get("name")]
        album = mi.get("album") if isinstance(mi.get("album"), dict) else {}
        pic = None
        if ma is not None:
            pic = ma.image_url(it.get("image")) or ma.image_url(mi.get("image"))
        else:
            pic = mi.get("image") if isinstance(mi.get("image"), str) else it.get("image") if isinstance(it.get("image"), str) else None
        note_ma_url(pic)
        return {
            "key": str(it.get("queue_item_id") or index or ""), "index": index,
            "title": str(mi.get("name") or it.get("name") or ""), "artist": ", ".join(artists) or None,
            "album": album.get("name") or None, "duration": _num(it.get("duration") or mi.get("duration")),
            "thumb": art_url if (current and art_url) else self.thumbs.url(pic), "current": current,
        }

    async def _ma_queue(self, ma: MAClient, queue_id: str, art_url: str | None) -> dict:
        q, = await ma.run(("player_queues/get", {"queue_id": queue_id}))
        q = q if isinstance(q, dict) else {}
        cur = q.get("current_index") if isinstance(q.get("current_index"), int) else None
        start = cur or 0
        items, = await ma.run(("player_queues/items", {"queue_id": queue_id, "limit": QUEUE_AHEAD + 1, "offset": start}))
        out = [self._ma_queue_item(it, start + i, cur is not None and start + i == cur, art_url, ma)
               for i, it in enumerate(items or []) if isinstance(it, dict)]
        return {"source": "music_assistant", "full": True, "total": int(_num(q.get("items")) or len(out)),
                "current": cur, "items": out, "can_jump": True, "can_remove": True, "can_move": True}

    async def _sonos_queue(self, entity: str, attrs: dict, art_url: str | None) -> dict:
        resp = await self.svc.call_service("sonos", "get_queue", {"entity_id": entity}, return_response=True)
        got = (resp or {}).get("service_response", resp) or {}
        tracks = got.get(entity) if isinstance(got, dict) else None
        tracks = tracks if isinstance(tracks, list) else []
        pos = _num(attrs.get("queue_position"))
        # HA's queue_position counts from 1; sonos.play_queue / remove_from_queue count from 0.
        cur = int(pos) - 1 if pos is not None and 0 < pos <= len(tracks) else None
        playing_from_queue = cur is not None and tracks[cur].get("media_title") == attrs.get("media_title")
        if not playing_from_queue:
            cur = None
        start = cur or 0
        items = []
        for i, t in enumerate(tracks[start:start + QUEUE_AHEAD + 1]):
            if not isinstance(t, dict):
                continue
            idx = start + i
            items.append({"key": str(idx), "index": idx, "title": str(t.get("media_title") or ""),
                          "artist": t.get("media_artist") or None, "album": t.get("media_album_name") or None,
                          "duration": None, "thumb": art_url if idx == cur else None, "current": idx == cur})
        return {"source": "sonos", "full": True, "total": len(tracks), "current": cur, "items": items,
                "can_jump": True, "can_remove": True, "can_move": False}

    async def queue_action(self, entity: str, state: dict | None, action: str, key: str) -> None:
        attrs = (state or {}).get("attributes") or {}
        if action not in ("play", "remove", "next"):
            raise MediaError("action must be play, remove or next", 400)
        if is_music_assistant(attrs):
            ma = ma_client()
            if ma is None or not ma.url:
                raise MediaError("Changing the queue needs Music Assistant connected in Settings > Music", 409)
            queue_id = attrs.get("active_queue") if isinstance(attrs.get("active_queue"), str) else entity
            cmd = {"play": ("player_queues/play_index", {"queue_id": queue_id, "index": key}),
                   "remove": ("player_queues/delete_item", {"queue_id": queue_id, "item_id_or_index": key}),
                   "next": ("player_queues/move_item", {"queue_id": queue_id, "queue_item_id": key, "pos_shift": 0})}
            await ma.run(cmd[action])
        elif entity in await self.sonos_entities():
            if action == "next" or not key.isdigit():
                raise MediaError("Sonos can only play or remove a track in its queue", 400)
            service = "play_queue" if action == "play" else "remove_from_queue"
            await self.svc.call_service("sonos", service, {"entity_id": entity, "queue_position": int(key)})
        else:
            raise MediaError("This speaker's queue can't be changed from Moonlight", 409)
        await self._refresh(entity)

    # ---- rooms
    async def rooms(self, entity: str, state: dict | None) -> dict:
        try:
            states = await _all_states(self.svc)
        except Exception as e:
            raise MediaError(f"Couldn't read Home Assistant's speakers ({_describe(e)})")
        sattrs = (state or {}).get("attributes") or {}
        ma = is_music_assistant(sattrs)
        sonos = set() if ma else await self.sonos_entities()
        members = [m for m in sattrs.get("group_members") or [] if isinstance(m, str)]
        out = []
        for s in states:
            eid = s.get("entity_id", "") if isinstance(s, dict) else ""
            if not ENTITY_RE.match(eid):
                continue
            a = s.get("attributes") or {}
            feats = int(_num(a.get("supported_features")) or 0)
            if eid != entity:
                if not feats & FEATURES["grouping"] or s.get("state") in ("unavailable", "unknown"):
                    continue
                if is_music_assistant(a) != ma or (not ma and sonos and eid not in sonos):
                    continue
            vol = _num(a.get("volume_level"))
            out.append({
                "entity_id": eid, "name": a.get("friendly_name") or eid, "state": s.get("state"),
                "this": eid == entity, "grouped": eid == entity or eid in members,
                "volume": None if vol is None else max(0.0, min(1.0, vol)),
                "muted": a.get("is_volume_muted") if isinstance(a.get("is_volume_muted"), bool) else None,
                "playing": a.get("media_title") if s.get("state") in ACTIVE else None,
                "can_volume": bool(feats & FEATURES["volume_set"]),
            })
        out.sort(key=lambda r: (not r["this"], not r["grouped"], str(r["name"]).lower()))
        return {"entity": entity, "can_group": bool(int(_num(sattrs.get("supported_features")) or 0) & FEATURES["grouping"]),
                "rooms": out}

    async def room_action(self, entity: str, state: dict | None, room: str, action: str, value: Any) -> None:
        listed = {r["entity_id"]: r for r in (await self.rooms(entity, state))["rooms"]}
        if room not in listed:
            raise MediaError("That speaker can't be grouped with this one", 404)
        if action == "join":
            if room == entity:
                raise MediaError("A speaker is always in its own group", 400)
            await self.svc.call_service("media_player", "join", {"entity_id": entity, "group_members": [room]})
        elif action == "unjoin":
            await self.svc.call_service("media_player", "unjoin", {"entity_id": room})
        elif action == "volume":
            v = _num(value)
            if v is None or not 0 <= v <= 1:
                raise MediaError("value must be a volume between 0 and 1", 400)
            await self.svc.call_service("media_player", "volume_set", {"entity_id": room, "volume_level": round(v, 3)})
        elif action == "mute":
            if not isinstance(value, bool):
                raise MediaError("value must be true or false", 400)
            await self.svc.call_service("media_player", "volume_mute", {"entity_id": room, "is_volume_muted": value})
        else:
            raise MediaError("action must be join, unjoin, volume or mute", 400)
        await self._refresh(entity, room)

    # ---- thumbnails
    async def thumb(self, key: str) -> tuple[bytes, str] | None:
        if key in self.thumbs.cache:
            self.thumbs.cache.move_to_end(key)
            return self.thumbs.cache[key]
        src = self.thumbs.urls.get(key)
        if not src:
            return None
        if src.startswith("/"):
            url, headers = self.svc.origin + src, {"Authorization": f"Bearer {self.svc.token}"}
        else:
            url, headers = src, {}
        try:
            async with httpx.AsyncClient(timeout=10, transport=self.svc.transport, follow_redirects=not headers,
                                         max_redirects=3) as client:
                r = await client.get(url, headers=headers)
                if r.status_code in (401, 403) and not headers and "/imageproxy" in url:
                    ma = ma_client()  # Music Assistant may want its token for images too
                    if ma is not None and urlsplit(ma.url).netloc == urlsplit(url).netloc:
                        r = await client.get(url, headers={"Authorization": f"Bearer {ma.token}"})
        except httpx.HTTPError as e:
            log.info("Couldn't fetch a thumbnail: %s", _describe(e))
            return None
        ctype = r.headers.get("content-type", "").split(";")[0].strip().lower()
        if r.status_code != 200 or not ctype.startswith("image/") or len(r.content) > THUMB_MAX_BYTES:
            return None
        self.thumbs.cache[key] = (r.content, ctype)
        while len(self.thumbs.cache) > THUMB_CACHE:
            self.thumbs.cache.popitem(last=False)
        return self.thumbs.cache[key]


async def _all_states(svc: MediaService) -> list[dict]:
    async with svc._client() as client:
        r = await client.get("/states")
    r.raise_for_status()
    data = r.json()
    return data if isinstance(data, list) else []


_music: dict[int, Music] = {}


def for_service(svc: MediaService) -> Music:
    m = _music.get(id(svc))
    if m is None or m.svc is not svc:
        _music.clear()
        m = _music[id(svc)] = Music(svc)
    return m
