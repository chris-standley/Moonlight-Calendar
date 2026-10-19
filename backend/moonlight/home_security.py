"""Security: the alarm, its sensors and the cameras, read from Home Assistant through the same Supervisor proxy as
the weather and the speakers (security.py is about Moonlight's own logins; this is the house).

- Alarm: an `alarm_control_panel` entity. By default the Alarmo one (its state carries `arm_mode` and
  `open_sensors`), else the first panel Home Assistant has; Settings > Security can pick another or none.
- Sensors: the ones set up in Alarmo, read over Home Assistant's WebSocket with Alarmo's own `alarmo/sensors`
  command (enabled sensors only, with Alarmo's type and the arm modes each one guards). Without Alarmo there is
  no sensor list: guessing from device classes would also show car doors and radiator valves.
- Cameras: every `camera` entity. UniFi Protect cameras are shown by default (one per camera: the highest
  resolution channel); others start hidden. Each camera's "Person detected" binary sensor is found through the
  entity registry (same device), else by name; Settings can change it or turn it off.

Live: the panel, sensors and person sensors are followed over the WebSocket (MediaService's watcher). Any change
broadcasts `security`; a change in who is at which camera also broadcasts `security_alert`, which the screens
use to pop up that camera in a corner.

Video: Home Assistant serves a camera as (low-latency) HLS once asked over the WebSocket (`camera/stream`, which
also starts the stream). Moonlight keeps the stream's token and passes the playlists and segments through at
/api/security/cameras/<camera>/hls/..., so the screens play real video (hls.js) without seeing any token. A
Protect camera's medium channel is used when it's enabled in HA. The stream is asked for as soon as someone is
seen, so it's warm when the pop-up opens.

Pictures: the Supervisor proxy reads a whole answer before passing it on, so HA's endless MJPEG stream can't be
proxied. For cameras without HLS (and as the fallback) a live feed is made here from HA's camera snapshots
(/api/camera_proxy, resized by HA) about twice a second, served as MJPEG, which an <img> plays. Screens only ever name a camera that is shown, never any
other entity, and never see Home Assistant's token.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
import time
from typing import Any, AsyncIterator

from . import db, media

log = logging.getLogger("moonlight.security")

KEY = "security"
PANEL_RE = re.compile(r"^alarm_control_panel\.[a-z0-9_]+$")
CAMERA_RE = re.compile(r"^camera\.[a-z0-9_]+$")
BINARY_RE = re.compile(r"^binary_sensor\.[a-z0-9_]+$")
WATCH_RE = re.compile(r"^(alarm_control_panel|binary_sensor|sensor)\.[a-z0-9_]+$")
# Where a camera that sees a person pops up: each screen style, and the Apple TV app on its own (off by default, as a
# TV may already show cameras from HomeKit).
DEFAULT_POPUP = {"large": True, "compact": True, "phone": False, "tv": False}

DISCOVERY_TTL = 300.0
STATES_TTL = 2.0
FRAME_SECONDS = 0.5           # live feed: a new snapshot this often (HA's own MJPEG fallback runs at the same rate)
FRAME_TTL = 0.4               # screens watching the same camera share snapshots this fresh
STREAM_MAX_SECONDS = 15 * 60  # a live feed ends after this; the screen opens a new one if it's still showing
MAX_STREAMS = 8
TEST_ALERT_SECONDS = 20
SNAPSHOT_MAX_BYTES = 5 * 1024 * 1024
STREAM_FEATURE = 2            # CameraEntityFeature.STREAM: Home Assistant can serve the camera as HLS video
HLS_PATH_RE = re.compile(r"^[A-Za-z0-9_\-][A-Za-z0-9_.\-]*(/[A-Za-z0-9_.\-]+)*$")
HLS_TIMEOUT = 20.0            # low-latency HLS holds a playlist request until the next part is ready

# Protect names each camera entity after its channel; the camera's own name is the device's.
CHANNEL_SUFFIX = re.compile(r"\s+(high|medium|low) resolution channel(\s+\(insecure\))?$", re.I)
CHANNEL_RANK = {"high": 0, "medium": 1, "low": 2}

ALARM_LABEL = {
    "disarmed": "Disarmed", "armed_home": "Armed home", "armed_away": "Armed away", "armed_night": "Armed night",
    "armed_vacation": "Armed vacation", "armed_custom_bypass": "Armed custom", "arming": "Arming",
    "pending": "Entry delay", "triggered": "Triggered", "disarming": "Disarming",
    "unavailable": "Unavailable", "unknown": "Unknown",
}
# Alarmo's sensor types -> the group the screen shows them under.
GROUPS = {"door": "doors", "window": "windows", "motion": "motion", "tamper": "other", "environmental": "environment",
          "other": "other"}
GROUP_FROM_CLASS = {"door": "doors", "garage_door": "doors", "opening": "doors", "window": "windows",
                    "motion": "motion", "occupancy": "motion", "presence": "motion", "moving": "motion",
                    "smoke": "environment", "gas": "environment", "moisture": "environment",
                    "carbon_monoxide": "environment", "heat": "environment", "cold": "environment"}
ACTIVE_WORDS = {"doors": ("Open", "Closed"), "windows": ("Open", "Closed"), "motion": ("Motion", "Clear"),
                "environment": ("Detected", "Clear"), "other": ("On", "Off")}


# ---------------------------------------------------------------- settings

def saved(c) -> dict:
    val = db.get_setting(c, KEY, {}) or {}
    return val if isinstance(val, dict) else {}


def popup_setting(c) -> dict[str, bool]:
    out = dict(DEFAULT_POPUP)
    for k, v in (saved(c).get("popup") or {}).items():
        if k in out and isinstance(v, bool):
            out[k] = v
    return out


def apply_settings(c, body: dict) -> bool:
    """PATCH /api/settings `security`: {alarm_entity?, cameras?: {entity: {show?, person?}}, popup?: {layout: bool}}.

    alarm_entity: an alarm_control_panel id, "" for none, null for automatic. A camera's person: a binary_sensor
    id, "" for none, null for automatic. Returns True if `security` was present."""
    if KEY not in body:
        return False
    from .common import bad  # local import: keep this module importable on its own

    val = body[KEY]
    if not isinstance(val, dict):
        raise bad("security must be an object")
    out = saved(c)
    if "alarm_entity" in val:
        a = val["alarm_entity"]
        if a is not None and (not isinstance(a, str) or (a and not PANEL_RE.match(a))):
            raise bad("security.alarm_entity must be an alarm_control_panel entity id, \"\" for none, or null")
        if a is None:
            out.pop("alarm_entity", None)
        else:
            out["alarm_entity"] = a
    if "cameras" in val:
        cams = val["cameras"]
        if not isinstance(cams, dict):
            raise bad("security.cameras must be an object like {\"camera.driveway\": {\"show\": true}}")
        merged = dict(out.get("cameras") or {})
        for eid, conf in cams.items():
            if not CAMERA_RE.match(str(eid)):
                raise bad(f"security.cameras: {eid} isn't a camera entity id")
            if conf is None:
                merged.pop(eid, None)
                continue
            if not isinstance(conf, dict):
                raise bad(f"security.cameras.{eid} must be an object")
            cur = dict(merged.get(eid) or {})
            if "show" in conf:
                if not isinstance(conf["show"], bool):
                    raise bad(f"security.cameras.{eid}.show must be true or false")
                cur["show"] = conf["show"]
            if "person" in conf:
                p = conf["person"]
                if p is not None and (not isinstance(p, str) or (p and not BINARY_RE.match(p))):
                    raise bad(f"security.cameras.{eid}.person must be a binary_sensor entity id, \"\" or null")
                if p is None:
                    cur.pop("person", None)
                else:
                    cur["person"] = p
            merged[eid] = cur
        out["cameras"] = merged
    if "popup" in val:
        pop = val["popup"]
        if not isinstance(pop, dict) or any(k not in DEFAULT_POPUP or not isinstance(v, bool) for k, v in pop.items()):
            raise bad("security.popup must map large/compact/phone/tv to true or false")
        out["popup"] = {**popup_setting(c), **pop}
    db.set_setting(c, KEY, out)
    return True


# ---------------------------------------------------------------- mapping (pure, tested on their own)

def _attrs(state: dict | None) -> dict:
    return (state or {}).get("attributes") or {}


def _name(state: dict | None, entity: str) -> str:
    return str(_attrs(state).get("friendly_name") or entity.split(".", 1)[1].replace("_", " ").capitalize())


def is_alarmo(state: dict) -> bool:
    a = _attrs(state)
    return "arm_mode" in a and "open_sensors" in a


def camera_name(state: dict | None, entity: str) -> str:
    return CHANNEL_SUFFIX.sub("", _name(state, entity)).strip() or entity


def _channel_rank(state: dict | None) -> int:
    m = CHANNEL_SUFFIX.search(_name(state, ""))
    if not m:
        return 0
    return CHANNEL_RANK.get(m.group(1).lower(), 0) + (5 if m.group(2) else 0)


def tidy_names(names: dict[str, str]) -> dict[str, str]:
    """"Alarm Panel front_door" -> "Front door": drop a first word or two that most sensors share (the panel's
    device name) and turn snake_case into words."""
    out = dict(names)
    for words in (2, 1):
        prefixes: dict[str, int] = {}
        for n in out.values():
            parts = n.split()
            if len(parts) > words:
                p = " ".join(parts[:words])
                prefixes[p] = prefixes.get(p, 0) + 1
        common = [p for p, k in prefixes.items() if k >= 3 and k * 2 >= len(out)]
        if common:
            p = common[0] + " "
            out = {e: (n[len(p):] if n.startswith(p) else n) for e, n in out.items()}
            break
    return {e: (n.replace("_", " ")[:1].upper() + n.replace("_", " ")[1:]) if "_" in n else n for e, n in out.items()}


def discover(states: list[dict], registry: list[dict] | None, alarmo: dict | None) -> dict:
    """What Home Assistant offers: {panels, cameras (with suggested person sensor and default show), person_sensors,
    alarmo_sensors: {entity: {group, modes, always_on}} | None}."""
    by_id = {s.get("entity_id"): s for s in states if isinstance(s, dict) and isinstance(s.get("entity_id"), str)}
    reg = {r.get("ei"): r for r in (registry or []) if isinstance(r, dict) and r.get("ei")}

    panels = []
    for eid, st in by_id.items():
        if PANEL_RE.match(eid):
            panels.append({"entity_id": eid, "name": _name(st, eid), "alarmo": is_alarmo(st),
                           "state": st.get("state")})
    panels.sort(key=lambda p: (not p["alarmo"], p["name"].lower()))

    person_sensors = []
    for eid, st in by_id.items():
        if not BINARY_RE.match(eid):
            continue
        n = _name(st, eid).lower()
        if eid.endswith("_person_detected") or n.endswith("person detected") or (
                reg.get(eid, {}).get("tk") or "").endswith("person"):
            person_sensors.append({"entity_id": eid, "name": _name(st, eid), "device": reg.get(eid, {}).get("di")})
    person_sensors.sort(key=lambda p: p["name"].lower())

    cams = []
    for eid, st in by_id.items():
        if not CAMERA_RE.match(eid):
            continue
        r = reg.get(eid, {})
        protect = r.get("pl") == "unifiprotect" or "unifi protect" in str(_attrs(st).get("attribution") or "").lower()
        feats = _attrs(st).get("supported_features")
        cams.append({"entity_id": eid, "name": camera_name(st, eid), "device": r.get("di"), "protect": protect,
                     "rank": _channel_rank(st), "available": st.get("state") not in ("unavailable", "unknown", None),
                     "stream": isinstance(feats, int) and bool(feats & STREAM_FEATURE)})
    # One per Protect camera: its best channel (the others are usually disabled anyway).
    same = lambda c: c["device"] or "name:" + _norm(c["name"])  # noqa: E731  (no registry: same name)
    best: dict[str, str] = {}
    for cam in sorted(cams, key=lambda c: c["rank"]):
        best.setdefault(same(cam), cam["entity_id"])
    used: set[str] = set()
    for cam in cams:
        # Video comes from the camera's medium channel when Home Assistant has it (easier for a Pi to play than
        # 2.7K), else from the camera itself.
        lighter = [c for c in cams if c is not cam and c["device"] and same(c) == same(cam) and c["available"]
                   and c["stream"] and c["rank"] == CHANNEL_RANK["medium"]]
        cam["stream_entity"] = lighter[0]["entity_id"] if lighter and cam["rank"] == 0 else cam["entity_id"]
        cam["default_show"] = bool(cam["protect"] and cam["available"] and best[same(cam)] == cam["entity_id"])
        same_device = [p for p in person_sensors if cam["device"] and p["device"] == cam["device"]]
        by_name = [p for p in person_sensors if p["entity_id"] not in used
                   and _norm(p["name"]).startswith(_norm(cam["name"]) + " ")]
        pick = (same_device or by_name or [None])[0]
        cam["default_person"] = pick["entity_id"] if pick else ""
        if pick and cam["default_show"]:
            used.add(pick["entity_id"])
    cams.sort(key=lambda c: (not c["default_show"], c["name"].lower()))

    sensors = None
    if isinstance(alarmo, dict):
        sensors = {}
        for eid, conf in alarmo.items():
            if not isinstance(conf, dict) or conf.get("enabled") is False or not WATCH_RE.match(str(eid)):
                continue
            kind = str(conf.get("type") or "other")
            dc = str(_attrs(by_id.get(eid)).get("device_class") or "")
            group = GROUPS.get(kind) if kind != "other" else GROUP_FROM_CLASS.get(dc, "other")
            sensors[eid] = {"group": group or "other", "modes": [m for m in conf.get("modes") or [] if isinstance(m, str)],
                            "always_on": bool(conf.get("always_on"))}
    return {"panels": panels, "cameras": cams, "person_sensors": person_sensors, "alarmo_sensors": sensors}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def effective(found: dict, conf: dict) -> dict:
    """The household's choices over what was found: {alarm_entity, sensors: {entity: meta}, cameras: [...]}."""
    panels = [p["entity_id"] for p in found["panels"]]
    alarm = conf.get("alarm_entity")
    if not isinstance(alarm, str):
        alarm = panels[0] if panels else ""
    saved_cams = conf.get("cameras") or {}
    cams = []
    for cam in found["cameras"]:
        mine = saved_cams.get(cam["entity_id"]) or {}
        show = mine.get("show", cam["default_show"])
        person = mine.get("person", cam["default_person"])
        cams.append({"entity_id": cam["entity_id"], "name": cam["name"], "show": bool(show), "person": person or "",
                     "auto_person": "person" not in mine, "default_person": cam["default_person"],
                     "available": cam["available"], "stream_entity": cam.get("stream_entity", cam["entity_id"]),
                     "stream": cam.get("stream", False)})
    sensors = found["alarmo_sensors"] or {}
    return {"alarm_entity": alarm, "sensors": sensors, "cameras": cams}


def alarm_out(entity: str, state: dict | None, names: dict[str, str]) -> dict | None:
    if not entity:
        return None
    a = _attrs(state)
    st = str((state or {}).get("state") or "unavailable")
    open_sensors = a.get("open_sensors")
    blocking = [names.get(e, e) for e in (open_sensors or {})] if isinstance(open_sensors, dict) else []
    return {"entity_id": entity, "name": _name(state, entity), "state": st, "label": ALARM_LABEL.get(st, st.replace("_", " ").capitalize()),
            "armed": st.startswith("armed_"), "alarmo": state is not None and is_alarmo(state),
            "changed_by": a.get("changed_by") or None, "last_changed": (state or {}).get("last_changed"),
            "next_state": a.get("next_state") or None, "delay": a.get("delay") if isinstance(a.get("delay"), (int, float)) else None,
            "open_sensors": blocking, "available": state is not None and st not in ("unavailable", "unknown")}


def sensor_out(entity: str, meta: dict, state: dict | None, name: str, panel_state: str) -> dict:
    st = str((state or {}).get("state") or "unavailable")
    group = meta.get("group") or "other"
    on, off = ACTIVE_WORDS.get(group, ACTIVE_WORDS["other"])
    available = st not in ("unavailable", "unknown")
    active = st in ("on", "open", "detected")
    guards = panel_state.startswith("armed_") and (meta.get("always_on") or panel_state in (meta.get("modes") or []))
    return {"entity_id": entity, "name": name, "group": group, "state": st,
            "label": (on if active else off) if available else ("Unavailable" if st == "unavailable" else "Unknown"),
            "active": active, "available": available, "armed": bool(guards),
            "last_changed": (state or {}).get("last_changed")}


# ---------------------------------------------------------------- service

class SecurityService(media.MediaService):
    """MediaService's REST + WebSocket watcher pointed at the alarm, its sensors and the person sensors."""
    watch_re = WATCH_RE
    subject = "the alarm and cameras"

    def __init__(self, *args, **kw) -> None:
        super().__init__(*args, **kw)
        self.found: dict | None = None
        self.found_at = -1e9
        self.found_error: str | None = None
        self.sensors_source: str = "none"   # "alarmo" | "none"
        self._discover_lock = asyncio.Lock()
        self._all_at = -1e9
        self.tests: dict[str, float] = {}     # camera -> test alert ends (monotonic)
        self.last_alerts: tuple = ()
        self._frames: dict[tuple, tuple[float, bytes, str]] = {}
        self._frame_locks: dict[tuple, asyncio.Lock] = {}
        self.streams = 0
        self._hls: dict[str, str] = {}        # stream entity -> HLS token (HA keeps it for the stream's life)
        self._hls_locks: dict[str, asyncio.Lock] = {}

    # ---- discovery
    async def _ws_commands(self, *commands: dict) -> list[Any]:
        """Run WebSocket commands once ([result or None per command]); raises if HA can't be reached at all."""
        results: list[Any] = [None] * len(commands)
        async with self.ws_connect(self.ws_url) as ws:
            msg = json.loads(await ws.recv())
            if msg.get("type") != "auth_required":
                raise media.MediaError(f"unexpected greeting {msg.get('type')!r}")
            await ws.send(json.dumps({"type": "auth", "access_token": self.token}))
            msg = json.loads(await ws.recv())
            if msg.get("type") != "auth_ok":
                raise media.AuthFailed(msg.get("message") or "authentication failed")
            for i, cmd in enumerate(commands, start=1):
                await ws.send(json.dumps({"id": i, **cmd}))
            pending = set(range(1, len(commands) + 1))
            while pending:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
                if msg.get("type") == "result" and msg.get("id") in pending:
                    pending.discard(msg["id"])
                    if msg.get("success"):
                        results[msg["id"] - 1] = msg.get("result")
                    else:
                        log.info("Home Assistant said no to %s: %s", commands[msg["id"] - 1]["type"],
                                 (msg.get("error") or {}).get("message"))
        return results

    async def all_states(self) -> list[dict]:
        async with self._client() as client:
            r = await client.get("/states")
        if r.status_code in (401, 403):
            raise media.MediaError("Home Assistant refused Moonlight's token")
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, list):
            raise media.MediaError("unexpected response from Home Assistant")
        return data

    async def discover(self, force: bool = False) -> dict:
        async with self._discover_lock:
            if self.found is not None and not force and self.clock() - self.found_at < DISCOVERY_TTL:
                return self.found
            try:
                states = await self.all_states()
            except Exception as e:
                self.found_error = "Home Assistant is unreachable"
                self.last_error = media._describe(e)
                if self.found is not None:
                    return self.found
                raise media.MediaError(self.found_error)
            registry = alarmo = None
            try:
                reg, alarmo = await self._ws_commands({"type": "config/entity_registry/list_for_display"},
                                                      {"type": "alarmo/sensors"})
                registry = (reg or {}).get("entities") if isinstance(reg, dict) else None
            except Exception as e:  # WebSocket down: cameras still work, matched by name
                log.info("Couldn't read the entity registry or Alarmo's sensors: %s", media._describe(e))
            self.found = discover(states, registry, alarmo if isinstance(alarmo, dict) else None)
            self.found_at = self.clock()
            self.found_error = None
            self.sensors_source = "alarmo" if self.found["alarmo_sensors"] is not None else "none"
            for s in states:
                if isinstance(s, dict) and s.get("entity_id") in self.watched | set(self.states):
                    self._store(s["entity_id"], s)
            self._all_at = self.clock()
            return self.found

    async def config(self, force: bool = False) -> dict:
        found = await self.discover(force)
        with db.connect() as c:
            conf = saved(c)
        eff = effective(found, conf)
        self.set_watched(watch_list(eff))
        return eff

    async def states_for(self, entities: list[str]) -> dict[str, dict | None]:
        """Current states: live from the WebSocket when following them, else one /states read (shared briefly)."""
        live = self.ws_connected and all(e in self.watched and e in self.states for e in entities)
        stale = self.clock() - self._all_at >= STATES_TTL or any(e not in self.states for e in entities)
        if not live and stale:
            try:
                got = {s.get("entity_id"): s for s in await self.all_states() if isinstance(s, dict)}
                for e in entities:
                    self._store(e, got.get(e))
                self._all_at = self.clock()
                self.last_error = None
            except Exception as e:
                self.last_error = media._describe(e)
                self._log_down(e)
        return {e: self.states.get(e) for e in entities}

    # ---- alerts
    def alerts_from(self, eff: dict, states: dict[str, dict | None]) -> list[dict]:
        now = self.clock()
        out = []
        for cam in eff["cameras"]:
            if not cam["show"]:
                continue
            st = states.get(cam["person"]) if cam["person"] else None
            test = self.tests.get(cam["entity_id"], 0) > now
            if (st and st.get("state") == "on") or test:
                out.append({"camera": cam["entity_id"], "name": cam["name"], "test": test and not (st and st.get("state") == "on"),
                            "since": (st or {}).get("last_changed") if not test else media.utc_now_iso()})
        return out

    def test_alert(self, camera: str, eff: dict) -> None:
        self.tests[camera] = self.clock() + TEST_ALERT_SECONDS
        self.warm(eff, [camera])
        loop = asyncio.get_running_loop()
        loop.create_task(_broadcast_alerts())
        loop.call_later(TEST_ALERT_SECONDS + 0.2, lambda: loop.create_task(_broadcast_alerts()))

    # ---- video
    async def hls_token(self, entity: str, force: bool = False) -> str | None:
        """The token of Home Assistant's HLS stream for `entity`, starting the stream if needed."""
        lock = self._hls_locks.setdefault(entity, asyncio.Lock())
        async with lock:
            if entity in self._hls and not force:
                return self._hls[entity]
            try:
                got, = await self._ws_commands({"type": "camera/stream", "entity_id": entity, "format": "hls"})
            except Exception as e:
                log.info("Couldn't start video for %s: %s", entity, media._describe(e))
                return None
            m = re.match(r"^/api/hls/([^/]+)/", str((got or {}).get("url") or ""))
            if not m:
                self._hls.pop(entity, None)
                return None
            self._hls[entity] = m.group(1)
            return self._hls[entity]

    async def hls(self, entity: str, path: str, query: str) -> tuple[int, bytes, str]:
        """One HLS file (playlist, init or segment) of `entity`'s stream: (status, body, content type)."""
        for attempt in (0, 1):
            token = await self.hls_token(entity, force=attempt == 1)
            if token is None:
                return 404, b"", "text/plain"
            url = f"/hls/{token}/{path}" + (f"?{query}" if query else "")
            try:
                async with self._client() as client:
                    r = await client.get(url, timeout=HLS_TIMEOUT)
            except Exception as e:
                log.info("Video from %s: %s", entity, media._describe(e))
                return 502, b"", "text/plain"
            if r.status_code == 404 and attempt == 0:
                continue  # the stream was restarted with a new token
            return r.status_code, r.content, r.headers.get("content-type", "application/octet-stream")
        return 404, b"", "text/plain"

    def warm(self, eff: dict, cameras: list[str]) -> None:
        """Start the video of cameras that just saw someone, so the pop-up plays straight away."""
        by_id = {c["entity_id"]: c for c in eff["cameras"]}
        for cam in cameras:
            c = by_id.get(cam)
            if c and c.get("stream"):
                # Both channels: the compact screens play the lighter one, large screens and the TV the full one.
                for entity in {c["stream_entity"], c["entity_id"]}:
                    asyncio.get_running_loop().create_task(self.hls_token(entity))

    # ---- pictures
    async def snapshot(self, entity: str, width: int | None = None) -> tuple[bytes, str] | None:
        params = {}
        if width:
            st = self.states.get(entity) or {}
            a = _attrs(st)
            w, h = a.get("width"), a.get("height")
            ratio = (h / w) if isinstance(w, (int, float)) and isinstance(h, (int, float)) and w > 0 else 9 / 16
            # HA only resizes when it gets both
            params = {"width": str(width), "height": str(max(1, round(width * ratio)))}
        try:
            async with self._client() as client:
                r = await client.get(f"/camera_proxy/{entity}", params=params)
        except Exception as e:
            log.info("Couldn't get a picture from %s: %s", entity, media._describe(e))
            return None
        ctype = r.headers.get("content-type", "").split(";")[0].strip().lower()
        if r.status_code != 200 or not ctype.startswith("image/") or len(r.content) > SNAPSHOT_MAX_BYTES:
            log.info("Picture from %s: HTTP %s %s", entity, r.status_code, ctype)
            return None
        return r.content, ctype

    async def frame(self, entity: str, width: int | None) -> tuple[bytes, str] | None:
        """A snapshot no older than FRAME_TTL, shared by every screen watching this camera at this size."""
        key = (entity, width)
        lock = self._frame_locks.setdefault(key, asyncio.Lock())
        async with lock:
            hit = self._frames.get(key)
            if hit and self.clock() - hit[0] < FRAME_TTL:
                return hit[1], hit[2]
            got = await self.snapshot(entity, width)
            if got is not None:
                self._frames[key] = (self.clock(), *got)
            return got

    async def mjpeg(self, entity: str, width: int | None, max_seconds: float | None = None,
                    frame_seconds: float = FRAME_SECONDS) -> AsyncIterator[bytes]:
        max_seconds = STREAM_MAX_SECONDS if max_seconds is None else max_seconds
        self.streams += 1
        start = time.monotonic()
        misses = 0
        try:
            while time.monotonic() - start < max_seconds:
                t0 = time.monotonic()
                got = await self.frame(entity, width)
                if got is None:
                    misses += 1
                    if misses >= 10:
                        return
                else:
                    misses = 0
                    data, ctype = got
                    yield (b"--frame\r\nContent-Type: " + ctype.encode() + b"\r\nContent-Length: "
                           + str(len(data)).encode() + b"\r\n\r\n" + data + b"\r\n")
                await asyncio.sleep(max(0.05, frame_seconds - (time.monotonic() - t0)))
        finally:
            self.streams -= 1


def watch_list(eff: dict) -> set[str]:
    out = set(eff["sensors"])
    if eff["alarm_entity"]:
        out.add(eff["alarm_entity"])
    out |= {c["person"] for c in eff["cameras"] if c["show"] and c["person"]}
    return out


async def overview(svc: SecurityService) -> dict:
    """GET /api/security."""
    eff = await svc.config()
    entities = sorted(watch_list(eff))
    states = await svc.states_for(entities)
    raw_names = {e: _name(states.get(e), e) for e in eff["sensors"]}
    names = tidy_names(raw_names)
    alarm = alarm_out(eff["alarm_entity"], states.get(eff["alarm_entity"]), names) if eff["alarm_entity"] else None
    panel_state = alarm["state"] if alarm else ""
    order = {"doors": 0, "windows": 1, "motion": 2, "environment": 3, "other": 4}
    sensors = [sensor_out(e, meta, states.get(e), names[e], panel_state) for e, meta in eff["sensors"].items()]
    sensors.sort(key=lambda s: (order.get(s["group"], 9), not s["active"], s["name"].lower()))
    cams = [{"entity_id": c["entity_id"], "name": c["name"], "available": c["available"], "person": bool(c["person"]),
             **_urls(c)}
            for c in eff["cameras"] if c["show"]]
    return {"configured": True, "reachable": svc.last_error is None, "error": svc.found_error,
            "sensors_source": svc.sensors_source, "alarm": alarm, "sensors": sensors, "cameras": cams,
            "alerts": [_alert_out(a, eff) for a in svc.alerts_from(eff, states)]}


def _urls(cam: dict) -> dict:
    """Picture and video URLs of a camera. `video_url` is the lighter medium channel when there is one;
    `video_hd_url` is always the camera's own (full resolution) stream, for big screens."""
    base = f"/api/security/cameras/{cam['entity_id']}"
    stream = cam.get("stream", False)
    video = f"{base}/hls/master_playlist.m3u8" if stream else None
    hd = f"{base}/hd/hls/master_playlist.m3u8" if stream and cam.get("stream_entity", cam["entity_id"]) != cam["entity_id"] else video
    return {"snapshot_url": f"{base}/snapshot", "live_url": f"{base}/live", "video_url": video, "video_hd_url": hd}


def _alert_out(a: dict, eff: dict) -> dict:
    cam = next((c for c in eff["cameras"] if c["entity_id"] == a["camera"]), {"entity_id": a["camera"]})
    return {**a, **_urls(cam)}


async def alerts(svc: SecurityService) -> list[dict]:
    eff = await svc.config()
    people = [c["person"] for c in eff["cameras"] if c["show"] and c["person"]]
    states = await svc.states_for(people)
    return [_alert_out(a, eff) for a in svc.alerts_from(eff, states)]


# ---------------------------------------------------------------- module-level service

_service: SecurityService | None = None
_configured = False


def from_env() -> SecurityService | None:
    import os

    token = os.environ.get("MOONLIGHT_HA_TOKEN") or os.environ.get("SUPERVISOR_TOKEN") or ""
    if not token:
        return None
    url = os.environ.get("MOONLIGHT_HA_URL") or media.SUPERVISOR_API
    return SecurityService(url, token, on_change=_changed)


async def _changed() -> None:
    from .common import hub

    await hub.broadcast("security")
    svc = service()
    if svc is not None:
        with contextlib.suppress(Exception):
            now = tuple(a["camera"] for a in await alerts(svc))
            if now != svc.last_alerts:
                svc.warm(await svc.config(), [c for c in now if c not in svc.last_alerts])
                svc.last_alerts = now
                await hub.broadcast("security_alert")


async def _broadcast_alerts() -> None:
    from .common import hub

    svc = service()
    if svc is not None:
        with contextlib.suppress(Exception):
            svc.last_alerts = tuple(a["camera"] for a in await alerts(svc))
    await hub.broadcast("security_alert")


def set_service(svc: SecurityService | None) -> None:
    """Override the HA connection (tests); None means no Home Assistant."""
    global _service, _configured
    _service, _configured = svc, True


def reset() -> None:
    global _service, _configured
    _service, _configured = None, False


def service() -> SecurityService | None:
    global _service, _configured
    if not _configured:
        _service, _configured = from_env(), True
    return _service


async def settings_changed() -> None:
    """The household changed Settings > Security: follow the new entities and refresh the screens."""
    from .common import hub

    svc = service()
    if svc is not None:
        with contextlib.suppress(Exception):
            await svc.config()
    await hub.broadcast("security")
    await _broadcast_alerts()


async def start() -> None:
    svc = service()
    if svc is None:
        return
    with contextlib.suppress(Exception):
        await svc.config()  # finds the entities and sets what to follow
    svc.start()


async def stop() -> None:
    svc = service()
    if svc is not None:
        await svc.stop()
