"""Now playing and playback control for a Home Assistant media_player (e.g. a Sonos speaker exposed by
Music Assistant's Home Assistant integration), through the same Supervisor proxy as the weather.

Which player a screen controls: Settings `media_players` ({hallway, kitchen, phone} -> entity id, "" = none);
the kitchen defaults to MOONLIGHT_MEDIA_ENTITY when set (development; the add-on no longer has an option for it). Screens only ever name
their layout, never an entity, so a screen can't read or drive any other Home Assistant entity.

Live updates: one WebSocket to Home Assistant (ws://supervisor/core/websocket, authenticated with the Supervisor
token) with a `subscribe_trigger` on the configured players. Each change broadcasts the `media` topic to screens.
When the WebSocket is down (HA restarting, proxy hiccup) the states are polled over REST every few seconds, and the
WebSocket is retried with a growing back-off.

Album art is fetched by the backend (HA's `entity_picture_local` / `entity_picture`, a /api/media_player_proxy
path that needs the HA token, or a public image URL) and served at /api/media/art, keyed by a hash of the picture
URL, so no HA token or proxy token ever reaches a screen.
"""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import os
import re
import time
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

import httpx

from . import db

log = logging.getLogger("moonlight.media")

LAYOUTS = ("hallway", "kitchen", "phone")
ENTITY_RE = re.compile(r"^media_player\.[a-z0-9_]+$")
SUPERVISOR_API = "http://supervisor/core/api"
SUPERVISOR_WS = "ws://supervisor/core/websocket"

POLL_SECONDS = 5.0
STATE_TTL = 2.0           # REST answers reused for this long when the WebSocket isn't feeding us
STALE_SECONDS = 90.0      # keep showing the last known state this long while HA is unreachable
BACKOFF = (5, 10, 20, 30, 60)
ART_CACHE = 12
ART_MAX_BYTES = 8 * 1024 * 1024
FAVOURITES_TTL = 15 * 60

# MediaPlayerEntityFeature bits (homeassistant/components/media_player/const.py)
FEATURES = {
    "pause": 1, "seek": 2, "volume_set": 4, "volume_mute": 8, "previous": 16, "next": 32,
    "volume_step": 1024, "stop": 4096, "play": 16384, "shuffle_set": 32768, "repeat_set": 262144,
}
ACTIVE = ("playing", "paused", "buffering")
REPEAT = ("off", "all", "one")
ACTIONS = ("play_pause", "play", "pause", "next", "previous", "volume_set", "volume_mute", "shuffle_set", "repeat_set")


class MediaError(Exception):
    """A failure to report to the screen (status is the HTTP status for the API)."""

    def __init__(self, message: str, status: int = 502) -> None:
        super().__init__(message)
        self.status = status


class AuthFailed(Exception):
    pass


# ---------------------------------------------------------------- configuration

def default_entity() -> str:
    """MOONLIGHT_MEDIA_ENTITY, used by the kitchen screen unless Settings say otherwise."""
    raw = os.environ.get("MOONLIGHT_MEDIA_ENTITY", "").strip()
    if raw and not ENTITY_RE.match(raw):
        log.warning("MOONLIGHT_MEDIA_ENTITY %r isn't a media_player entity id; ignoring it", raw)
        return ""
    return raw


def players_setting(c) -> dict[str, str]:
    saved = db.get_setting(c, "media_players", {}) or {}
    out = {"hallway": "", "kitchen": default_entity(), "phone": ""}
    for k, v in saved.items():
        if k in out and isinstance(v, str) and (v == "" or ENTITY_RE.match(v)):
            out[k] = v
    return out


def apply_settings(c, body: dict) -> bool:
    """PATCH /api/settings `media_players`: {layout: entity_id | "" | null}. Returns True if it was present."""
    if "media_players" not in body:
        return False
    from .common import bad  # local import: common imports db, keep this module importable on its own

    val = body["media_players"]
    if not isinstance(val, dict):
        raise bad("media_players must be an object like {\"kitchen\": \"media_player.kitchen\"}")
    saved = dict(db.get_setting(c, "media_players", {}) or {})
    for k, v in val.items():
        if k not in LAYOUTS:
            raise bad("media_players keys are hallway, kitchen, phone")
        v = "" if v is None else v
        if not isinstance(v, str) or (v and not ENTITY_RE.match(v.strip())):
            raise bad(f"media_players.{k} must be a media_player entity id or empty")
        saved[k] = v.strip()
    db.set_setting(c, "media_players", saved)
    return True


def entity_for(layout: str) -> str:
    if layout not in LAYOUTS:
        from .common import bad

        raise bad("layout must be one of: " + ", ".join(LAYOUTS))
    with db.connect() as c:
        return players_setting(c)[layout]


def watched_entities() -> set[str]:
    with db.connect() as c:
        return {e for e in players_setting(c).values() if e}


# ---------------------------------------------------------------- mapping

def _num(v: Any) -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def picture_of(attrs: dict) -> str | None:
    """HA's local proxy path is preferred: entity_picture is the raw remote URL when the image is public."""
    for key in ("entity_picture_local", "entity_picture"):
        v = attrs.get(key)
        if isinstance(v, str) and v:
            return v
    return None


def art_key(picture: str) -> str:
    # The picture URL carries HA's proxy token, so only a hash of it is ever sent to screens.
    return hashlib.sha256(picture.encode()).hexdigest()[:20]


def is_music_assistant(attrs: dict) -> bool:
    return "mass_player_type" in attrs or attrs.get("app_id") == "music_assistant"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def empty(layout: str, entity: str | None, configured: bool, state: str = "off", error: str | None = None) -> dict:
    return {
        "layout": layout, "configured": configured, "entity": entity or None, "name": None, "state": state,
        "show": False, "title": None, "artist": None, "album": None, "duration": None, "position": None,
        "position_updated_at": None, "volume": None, "muted": None, "shuffle": None, "repeat": None,
        "source": None, "app": None, "music_assistant": False, "has_art": False, "art_url": None,
        "supports": {k: False for k in ("play_pause", "previous", "next", "volume", "mute", "shuffle", "repeat", "seek")},
        "reachable": error is None, "error": error, "server_time": utc_now_iso(),
    }


def now_playing(layout: str, entity: str, state: dict | None, error: str | None = None) -> dict:
    """Map a HA media_player state object to the /api/media/now-playing shape."""
    if not entity:
        return empty(layout, None, False)
    if state is None:
        return empty(layout, entity, True, "unavailable", error)
    attrs = state.get("attributes") or {}
    st = str(state.get("state") or "unknown")
    title = attrs.get("media_title") or None
    artist = attrs.get("media_artist") or attrs.get("media_album_artist") or None
    picture = picture_of(attrs)
    feats = int(_num(attrs.get("supported_features")) or 0)
    has = lambda name: bool(feats & FEATURES[name])  # noqa: E731
    shuffle = attrs.get("shuffle")
    repeat = attrs.get("repeat")
    vol = _num(attrs.get("volume_level"))
    muted = attrs.get("is_volume_muted")
    show = st in ACTIVE or (st in ("idle", "on") and bool(title))
    out = empty(layout, entity, True, st, error)
    out.update({
        "name": attrs.get("friendly_name") or entity,
        "show": show,
        "title": title,
        "artist": artist,
        "album": attrs.get("media_album_name") or None,
        "duration": _num(attrs.get("media_duration")),
        "position": _num(attrs.get("media_position")),
        "position_updated_at": attrs.get("media_position_updated_at") or None,
        "volume": None if vol is None else max(0.0, min(1.0, vol)),
        "muted": muted if isinstance(muted, bool) else None,
        "shuffle": shuffle if isinstance(shuffle, bool) else None,
        "repeat": repeat if repeat in REPEAT else None,
        "source": attrs.get("source") or attrs.get("app_name") or None,
        "app": attrs.get("app_id") or None,
        "music_assistant": is_music_assistant(attrs),
        "has_art": picture is not None,
        "art_url": f"/api/media/art?layout={layout}&v={art_key(picture)}" if picture else None,
        "supports": {
            "play_pause": has("pause") or has("play"),
            "previous": has("previous"),
            "next": has("next"),
            "volume": has("volume_set"),
            "mute": has("volume_mute"),
            "shuffle": has("shuffle_set"),
            "repeat": has("repeat_set"),
            "seek": has("seek"),
        },
    })
    return out


def service_call(action: str, value: Any) -> tuple[str, dict]:
    """(media_player service, extra data) for a /api/media/command action. Raises MediaError(400) on bad input."""
    if action not in ACTIONS:
        raise MediaError("action must be one of: " + ", ".join(ACTIONS), 400)
    if action == "play_pause":
        return "media_play_pause", {}
    if action == "play":
        return "media_play", {}
    if action == "pause":
        return "media_pause", {}
    if action == "next":
        return "media_next_track", {}
    if action == "previous":
        return "media_previous_track", {}
    if action == "volume_set":
        v = _num(value)
        if v is None or not 0 <= v <= 1:
            raise MediaError("value must be a volume between 0 and 1", 400)
        return "volume_set", {"volume_level": round(v, 3)}
    if action == "volume_mute":
        if not isinstance(value, bool):
            raise MediaError("value must be true or false", 400)
        return "volume_mute", {"is_volume_muted": value}
    if action == "shuffle_set":
        if not isinstance(value, bool):
            raise MediaError("value must be true or false", 400)
        return "shuffle_set", {"shuffle": value}
    if value not in REPEAT:  # repeat_set
        raise MediaError("value must be one of: off, all, one", 400)
    return "repeat_set", {"repeat": value}


# ---------------------------------------------------------------- Home Assistant connection

WsConnect = Callable[[str], Any]  # returns an async context manager yielding a websocket (send/recv/close)


def _default_ws_connect(url: str):
    from websockets.asyncio.client import connect

    return connect(url, open_timeout=10, ping_interval=20, ping_timeout=20, max_size=8 * 1024 * 1024)


class MediaService:
    def __init__(self, base_url: str, token: str, *, ws_url: str | None = None,
                 transport: httpx.AsyncBaseTransport | None = None,
                 ws_connect: WsConnect | None = None,
                 on_change: Callable[[], Awaitable[None]] | None = None,
                 poll_seconds: float = POLL_SECONDS, backoff: tuple[float, ...] = BACKOFF,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.base_url = base_url.rstrip("/")
        self.origin = self.base_url[:-4] if self.base_url.endswith("/api") else self.base_url
        self.token = token
        self.ws_url = ws_url or ws_url_for(self.base_url)
        self.transport = transport
        self.ws_connect = ws_connect or _default_ws_connect
        self.on_change = on_change
        self.poll_seconds = poll_seconds
        self.backoff = backoff
        self.clock = clock
        self.states: dict[str, dict | None] = {}
        self.fetched_at: dict[str, float] = {}
        self.last_error: str | None = None
        self.watched: set[str] = set()
        self.ws_connected = False
        self.ws_sessions = 0
        self._art: OrderedDict[str, tuple[bytes, str]] = OrderedDict()
        self._favs: dict[str, tuple[float, list[dict]]] = {}
        self._wake = asyncio.Event()
        self._ws = None
        self._task: asyncio.Task | None = None
        self._notify_task: asyncio.Task | None = None
        self._logged_down = False

    # ---- REST
    def _client(self) -> httpx.AsyncClient:
        headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
        return httpx.AsyncClient(base_url=self.base_url, headers=headers, timeout=10, transport=self.transport)

    async def fetch_state(self, entity: str) -> dict | None:
        async with self._client() as client:
            r = await client.get(f"/states/{entity}")
        if r.status_code == 404:
            return None
        if r.status_code in (401, 403):
            raise MediaError("Home Assistant refused Moonlight's token")
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, dict):
            raise MediaError("unexpected response from Home Assistant")
        return data

    def _store(self, entity: str, state: dict | None) -> bool:
        """Remember a state; True if it differs from what we had."""
        old = self.states.get(entity, "missing")
        self.states[entity] = state
        self.fetched_at[entity] = self.clock()
        if old == "missing":
            return True
        strip = lambda s: None if s is None else (s.get("state"), s.get("attributes"))  # noqa: E731
        return strip(old) != strip(state)

    async def refresh(self, entity: str) -> bool:
        """Fetch one entity over REST and store it. True if it changed. Raises on HA errors."""
        state = await self.fetch_state(entity)
        self.last_error = None
        return self._store(entity, state)

    async def get_state(self, entity: str) -> tuple[dict | None, str | None]:
        """(state, error) for now-playing: from the live WebSocket feed when we have one, else a short REST cache."""
        now = self.clock()
        live = self.ws_connected and entity in self.watched and entity in self.states
        if live or (entity in self.states and now - self.fetched_at[entity] < STATE_TTL):
            return self.states[entity], None
        try:
            if await self.refresh(entity):
                self.notify()
            st = self.states[entity]
            return st, None if st is not None else f"{entity} was not found in Home Assistant"
        except Exception as e:  # network, HTTP status, bad JSON
            self.last_error = _describe(e)
            self._log_down(e)
            if entity in self.states and now - self.fetched_at[entity] < STALE_SECONDS:
                return self.states[entity], None
            return None, "Home Assistant is unreachable"

    async def call_service(self, domain: str, service: str, data: dict, return_response: bool = False) -> Any:
        path = f"/services/{domain}/{service}" + ("?return_response" if return_response else "")
        try:
            async with self._client() as client:
                r = await client.post(path, json=data)
        except httpx.HTTPError as e:
            raise MediaError(f"Home Assistant is unreachable ({_describe(e)})")
        if r.status_code >= 400:
            detail = ""
            with contextlib.suppress(Exception):
                detail = r.json().get("message", "")
            raise MediaError(f"Home Assistant rejected {domain}.{service}" + (f": {detail}" if detail else ""),
                             400 if r.status_code == 400 else 502)
        with contextlib.suppress(Exception):
            return r.json()
        return None

    async def command(self, entity: str, action: str, value: Any = None) -> None:
        service, extra = service_call(action, value)
        await self.call_service("media_player", service, {"entity_id": entity, **extra})
        with contextlib.suppress(Exception):
            if await self.refresh(entity):
                self.notify()

    async def players(self) -> list[dict]:
        try:
            async with self._client() as client:
                r = await client.get("/states")
            r.raise_for_status()
            states = r.json()
        except Exception as e:
            raise MediaError(f"Couldn't list Home Assistant's media players ({_describe(e)})")
        out = []
        for s in states if isinstance(states, list) else []:
            eid = s.get("entity_id", "") if isinstance(s, dict) else ""
            if not ENTITY_RE.match(eid):
                continue
            attrs = s.get("attributes") or {}
            out.append({"entity_id": eid, "name": attrs.get("friendly_name") or eid, "state": s.get("state"),
                        "music_assistant": "mass_player_type" in attrs or attrs.get("app_id") == "music_assistant"})
        out.sort(key=lambda p: (not p["music_assistant"], str(p["name"]).lower()))
        return out

    # ---- album art
    async def art(self, entity: str, key: str) -> tuple[bytes, str] | None:
        if key in self._art:
            self._art.move_to_end(key)
            return self._art[key]
        state, _ = await self.get_state(entity)
        picture = picture_of((state or {}).get("attributes") or {})
        if not picture or art_key(picture) != key:
            return None  # only the configured player's current picture can be fetched
        if picture.startswith("/"):
            url, headers = self.origin + picture, {"Authorization": f"Bearer {self.token}"}
        elif picture.startswith(("http://", "https://")):
            url, headers = picture, {}  # a public image URL: never send HA's token elsewhere
        else:
            return None
        try:
            async with httpx.AsyncClient(timeout=10, transport=self.transport, follow_redirects=not headers,
                                         max_redirects=3) as client:
                r = await client.get(url, headers=headers)
        except httpx.HTTPError as e:
            log.info("Couldn't fetch album art for %s: %s", entity, _describe(e))
            return None
        ctype = r.headers.get("content-type", "").split(";")[0].strip().lower()
        if r.status_code != 200 or not ctype.startswith("image/") or len(r.content) > ART_MAX_BYTES:
            log.info("Album art for %s: HTTP %s %s (%d bytes)", entity, r.status_code, ctype, len(r.content))
            return None
        self._art[key] = (r.content, ctype)
        while len(self._art) > ART_CACHE:
            self._art.popitem(last=False)
        return self._art[key]

    # ---- Music Assistant favourites (optional quick-play)
    async def favourites(self, entity: str) -> list[dict]:
        state, _ = await self.get_state(entity)
        if not state or "mass_player_type" not in (state.get("attributes") or {}):
            return []
        hit = self._favs.get(entity)
        if hit and self.clock() - hit[0] < FAVOURITES_TTL:
            return hit[1]
        items: list[dict] = []
        try:
            async with self._client() as client:
                r = await client.get("/config/config_entries/entry", params={"domain": "music_assistant"})
            r.raise_for_status()
            entries = [e for e in r.json() if isinstance(e, dict) and e.get("state") in (None, "loaded")]
            if not entries:
                return []
            entry_id = entries[0]["entry_id"]
            for media_type, limit in (("playlist", 10), ("radio", 6)):
                resp = await self.call_service("music_assistant", "get_library", {
                    "config_entry_id": entry_id, "media_type": media_type, "favorite": True, "limit": limit,
                }, return_response=True)
                got = (resp or {}).get("service_response", resp) or {}
                for it in got.get("items") or []:
                    if isinstance(it, dict) and it.get("uri") and it.get("name"):
                        items.append({"uri": str(it["uri"]), "name": str(it["name"]),
                                      "media_type": str(it.get("media_type") or media_type)})
        except Exception as e:
            log.info("Couldn't read Music Assistant favourites: %s", _describe(e))
            return hit[1] if hit else []
        self._favs[entity] = (self.clock(), items[:12])
        return self._favs[entity][1]

    async def play_favourite(self, entity: str, uri: str) -> None:
        favs = await self.favourites(entity)
        fav = next((f for f in favs if f["uri"] == uri), None)
        if fav is None:
            raise MediaError("That isn't one of the Music Assistant favourites", 404)
        await self.call_service("music_assistant", "play_media", {
            "entity_id": entity, "media_id": fav["uri"], "media_type": fav["media_type"], "enqueue": "replace",
        })
        with contextlib.suppress(Exception):
            if await self.refresh(entity):
                self.notify()

    # ---- change notification (coalesced: a volume drag fires many state changes)
    def notify(self) -> None:
        if self.on_change is None or (self._notify_task and not self._notify_task.done()):
            return
        try:
            self._notify_task = asyncio.get_running_loop().create_task(self._notify_soon())
        except RuntimeError:
            pass

    async def _notify_soon(self) -> None:
        await asyncio.sleep(0.15)
        with contextlib.suppress(Exception):
            await self.on_change()

    # ---- watcher: WebSocket subscription with REST polling fallback
    def set_watched(self, entities: set[str]) -> None:
        entities = {e for e in entities if ENTITY_RE.match(e)}
        if entities == self.watched:
            return
        self.watched = entities
        self._wake.set()
        if self._ws is not None:  # resubscribe with the new set
            with contextlib.suppress(Exception):
                asyncio.get_running_loop().create_task(self._ws.close())

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.get_running_loop().create_task(self.run())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(BaseException):
                await self._task
            self._task = None

    async def run(self) -> None:
        attempt = 0
        while True:
            if not self.watched:
                self._wake.clear()
                await self._wake.wait()
                continue
            self._wake.clear()
            started = self.clock()
            try:
                await self._ws_session()
            except asyncio.CancelledError:
                raise
            except AuthFailed as e:
                log.warning("Home Assistant WebSocket: %s; polling instead", e)
                attempt = len(self.backoff) - 1
            except Exception as e:
                if attempt == 0:
                    log.info("Home Assistant WebSocket unavailable (%s); polling every %ss", _describe(e),
                             self.poll_seconds)
            finally:
                self.ws_connected = False
                self._ws = None
            if self._wake.is_set():  # players changed: resubscribe straight away
                continue
            if self.clock() - started > 60:
                attempt = 0  # it was a healthy session (e.g. HA restarted): start the back-off again
            delay = self.backoff[min(attempt, len(self.backoff) - 1)]
            attempt += 1
            await self._poll_for(delay)

    async def _poll_once(self) -> None:
        changed = False
        for entity in sorted(self.watched):
            try:
                changed |= await self.refresh(entity)
                self._logged_down = False
            except Exception as e:
                self.last_error = _describe(e)
                self._log_down(e)
        if changed:
            self.notify()

    async def _poll_for(self, seconds: float) -> None:
        end = self.clock() + seconds
        while True:
            await self._poll_once()
            left = end - self.clock()
            if left <= 0 or self._wake.is_set():
                return
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._wake.wait(), timeout=min(self.poll_seconds, left))

    async def _ws_session(self) -> None:
        async with self.ws_connect(self.ws_url) as ws:
            self._ws = ws
            msg = json.loads(await ws.recv())
            if msg.get("type") != "auth_required":
                raise MediaError(f"unexpected greeting {msg.get('type')!r}")
            await ws.send(json.dumps({"type": "auth", "access_token": self.token}))
            msg = json.loads(await ws.recv())
            if msg.get("type") != "auth_ok":
                raise AuthFailed(msg.get("message") or "authentication failed")
            entities = sorted(self.watched)
            await ws.send(json.dumps({"id": 1, "type": "subscribe_trigger",
                                      "trigger": {"platform": "state", "entity_id": entities}}))
            while True:
                msg = json.loads(await ws.recv())
                if msg.get("id") == 1 and msg.get("type") == "result":
                    if not msg.get("success"):
                        raise MediaError(f"subscribe_trigger failed: {(msg.get('error') or {}).get('message')}")
                    break
            self.ws_connected = True
            self.ws_sessions += 1
            if self._logged_down or self.ws_sessions > 1:
                log.info("Following %s live over Home Assistant's WebSocket", ", ".join(entities))
            self._logged_down = False
            # Catch up on anything that changed while we weren't subscribed.
            changed = False
            for entity in entities:
                with contextlib.suppress(Exception):
                    changed |= await self.refresh(entity)
            if changed:
                self.notify()
            while True:
                msg = json.loads(await ws.recv())  # raises ConnectionClosed when HA goes away
                if msg.get("type") != "event" or msg.get("id") != 1:
                    continue
                trig = ((msg.get("event") or {}).get("variables") or {}).get("trigger") or {}
                entity = trig.get("entity_id")
                if entity in self.watched:
                    if self._store(entity, trig.get("to_state")):
                        self.notify()

    def _log_down(self, e: Exception) -> None:
        if not self._logged_down:
            log.warning("Couldn't read the media player from Home Assistant: %s", _describe(e))
            self._logged_down = True


def _describe(e: Exception) -> str:
    return str(e) or type(e).__name__


def ws_url_for(base_url: str) -> str:
    env = os.environ.get("MOONLIGHT_HA_WS_URL", "").strip()
    if env:
        return env
    base = base_url.rstrip("/")
    if base == SUPERVISOR_API:
        return SUPERVISOR_WS
    if base.endswith("/api"):
        base = base[:-4]
    return re.sub(r"^http", "ws", base) + "/api/websocket"


# ---------------------------------------------------------------- module-level service

_service: MediaService | None = None
_configured = False


def from_env() -> MediaService | None:
    token = os.environ.get("MOONLIGHT_HA_TOKEN") or os.environ.get("SUPERVISOR_TOKEN") or ""
    if not token:
        return None
    url = os.environ.get("MOONLIGHT_HA_URL") or SUPERVISOR_API
    return MediaService(url, token, on_change=_broadcast)


async def _broadcast() -> None:
    from .common import hub

    await hub.broadcast("media")


def set_service(svc: MediaService | None) -> None:
    """Override the HA connection (tests); None means no Home Assistant."""
    global _service, _configured
    _service, _configured = svc, True


def reset() -> None:
    global _service, _configured
    _service, _configured = None, False


def service() -> MediaService | None:
    global _service, _configured
    if not _configured:
        _service, _configured = from_env(), True
    return _service


def settings_changed() -> None:
    svc = service()
    if svc is not None:
        svc.set_watched(watched_entities())
