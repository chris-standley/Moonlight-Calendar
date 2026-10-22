"""Notifications and timers that Home Assistant (or anything else on the API) puts on the screens.

A notification is a message shown full screen or as a toast in the corner. A timer counts down to a moment (from a
duration, or to a date and time for a countdown) and says "Time's up" when it gets there, or counts up from a moment
(`since`, e.g. how long ago the kettle boiled). Each goes to every screen or to chosen ones, and stays for a set time or until someone taps it away on a screen or Home Assistant clears it.

They are kept in the database (table `alerts`) so a restart doesn't lose one that waits to be cleared, and in memory
for the screens. Times are epoch milliseconds; the API sends its own clock as `server_time` so a screen with a wrong
clock still counts down right. Screens hear about changes as topic `alerts`; a timer reaching zero and a screen
dismissing one are also sent on the WebSocket as `{"type": "alert", "event": "finished"|"dismissed", ...}` for the
Home Assistant integration, which fires them as `moonlight_alert` events.
"""
from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from . import db
from .common import LAYOUTS, as_int, bad, hub, log

SCHEMA = """
CREATE TABLE IF NOT EXISTS alerts (
    id   TEXT PRIMARY KEY,
    data TEXT NOT NULL
);
"""

KINDS = ("notification", "timer")
STYLES = ("fullscreen", "toast")
TOAST_SECONDS = 10           # a toast with no duration given
MAX_SECONDS = 366 * 86400     # durations and countdowns up to a year
MAX_ALERTS = 50
ALL = "all"
APP = "app"                   # the iPhone and iPad apps (screens are large, compact or phone)
SERVICE = "service"           # the Home Assistant integration: never shown anything

_alerts: dict[str, dict] = {}
_task: asyncio.Task | None = None


def now_ms() -> int:
    return int(time.time() * 1000)


def load() -> None:
    """Read the saved ones (called when the app starts, for each database)."""
    _alerts.clear()
    with db.connect() as c:
        c.executescript(SCHEMA)
        for r in c.execute("SELECT data FROM alerts").fetchall():
            try:
                a = json.loads(r[0])
            except ValueError:
                continue
            if isinstance(a, dict) and a.get("id"):
                _alerts[a["id"]] = a
    _expire(now_ms())


def _save(a: dict) -> None:
    with db.connect() as c:
        c.execute("INSERT OR REPLACE INTO alerts(id, data) VALUES(?, ?)", (a["id"], json.dumps(a)))


def _drop(ids: list[str]) -> None:
    for i in ids:
        _alerts.pop(i, None)
    if ids:
        with db.connect() as c:
            c.executemany("DELETE FROM alerts WHERE id = ?", [(i,) for i in ids])


def _expire(now: int) -> list[str]:
    gone = [i for i, a in _alerts.items() if a["expires_at"] is not None and a["expires_at"] <= now]
    _drop(gone)
    return gone


# ---------------------------------------------------------------- targets

def _screens(c) -> list[dict]:
    return db.rows(c, "SELECT id, name, layout FROM displays WHERE revoked = 0 AND layout != ?", (SERVICE,))


def resolve_targets(c, value: Any) -> tuple[list[str] | None, list[str]]:
    """`screens` -> (display ids, or None for every device; the names as given, for showing).

    Each entry is "all", a screen's name or id (any case), or a style: large, compact, phone, or app (the iPhone and
    iPad apps). A style means every device of that style paired at the time."""
    if value is None or value == "":
        return None, [ALL]
    if isinstance(value, str):
        value = [x for x in (s.strip() for s in value.split(",")) if x]
    if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
        raise bad("screens must be a list of screen names, styles or \"all\"")
    value = [x.strip() for x in value if x.strip()]
    if not value or any(x.lower() == ALL for x in value):
        return None, [ALL]
    screens = _screens(c)
    ids: list[str] = []
    for ref in value:
        low = ref.lower()
        low = db.OLD_LAYOUTS.get(low, low)
        if low in (*LAYOUTS, APP, "apps"):
            style = APP if low == "apps" else low
            ids += [d["id"] for d in screens if d["layout"] == style]
            continue
        hits = [d for d in screens if d["id"] == ref or d["name"].strip().lower() == low]
        if not hits:
            names = ", ".join(sorted({d["name"] for d in screens})) or "none paired yet"
            raise bad(f"No screen called {ref!r}. Screens: {names}; or use all, large, compact, phone or app")
        ids += [d["id"] for d in hits]
    return list(dict.fromkeys(ids)), value


def shown_on(a: dict, display: dict | None) -> bool:
    """Whether this device shows it. Without a paired screen (the Home Assistant panel, auth off) only "all" ones."""
    if display is not None and display["layout"] == SERVICE:
        return False
    if a["display_ids"] is None:
        return True
    return display is not None and display["id"] in a["display_ids"]


# ---------------------------------------------------------------- making them

def _seconds(value: Any, key: str, allow_zero: bool = True) -> int:
    if isinstance(value, str):
        try:
            value = float(value)
        except ValueError:
            raise bad(f"{key} must be a number of seconds")
    if isinstance(value, float):
        value = round(value)
    v = as_int(value, key)
    if v < 0 or v > MAX_SECONDS or (v == 0 and not allow_zero):
        raise bad(f"{key} must be {'0' if allow_zero else '1'} to {MAX_SECONDS} seconds")
    return v


def _text(body: dict, key: str, limit: int, required: bool = False) -> str:
    v = body.get(key)
    if v is None:
        v = ""
    if not isinstance(v, str):
        raise bad(f"{key} must be text")
    v = v.strip()[:limit]
    if required and not v:
        raise bad(f"{key} is required")
    return v


def _bool(body: dict, key: str, default: bool) -> bool:
    v = body.get(key, default)
    if v is None:
        return default
    if not isinstance(v, bool):
        raise bad(f"{key} must be true or false")
    return v


def _until_ms(c, value: Any, key: str = "until") -> int:
    """An ISO date-time; without a zone it is the household's local time."""
    try:
        dt = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except ValueError:
        raise bad(f"{key} must be an ISO date and time, like 2026-12-25T07:00")
    if dt.tzinfo is None:
        tz = db.get_setting(c, "timezone", db.default_timezone())
        try:
            dt = dt.replace(tzinfo=ZoneInfo(tz))
        except Exception:
            dt = dt.replace(tzinfo=ZoneInfo(db.FALLBACK_TIMEZONE))
    return int(dt.timestamp() * 1000)


def build(c, body: dict, now: int | None = None) -> dict:
    """Check a POST /api/alerts body and make the stored alert."""
    now = now_ms() if now is None else now
    kind = body.get("kind") or "notification"
    if kind not in KINDS:
        raise bad("kind must be notification or timer")
    style = body.get("style") or ("fullscreen" if kind == "notification" else "toast")
    if style not in STYLES:
        raise bad("style must be fullscreen or toast")
    aid = _text(body, "id", 80) or db.new_id("al")
    display_ids, screens = resolve_targets(c, body.get("screens"))
    a: dict[str, Any] = {
        "id": aid, "kind": kind, "style": style, "screens": screens, "display_ids": display_ids,
        "icon": _text(body, "icon", 16), "dismissible": _bool(body, "dismissible", True),
        "created_at": now,
    }
    if kind == "notification":
        a["title"] = _text(body, "title", 120)
        a["message"] = _text(body, "message", 1000)
        if not a["title"] and not a["message"]:
            raise bad("A notification needs a title or a message")
        image = _text(body, "image", 2000)
        if image and not image.startswith(("http://", "https://", "/")):
            raise bad("image must be a web address (http or https)")
        a["image"] = image or None
        a["chime"] = _bool(body, "chime", False)
        if body.get("duration") is None:
            secs = TOAST_SECONDS if style == "toast" else 0
        else:
            secs = _seconds(body["duration"], "duration")
        a["expires_at"] = now + secs * 1000 if secs else None  # 0 = until dismissed or cleared
    else:
        a["label"] = _text(body, "label", 80, required=True)
        a["description"] = _text(body, "description", 300)
        has_duration, has_until = body.get("duration") is not None, body.get("until") not in (None, "")
        if body.get("since") not in (None, ""):
            return _count_up(c, body, a, now, has_duration, has_until)
        a["chime"] = _bool(body, "chime", True)
        if has_duration == has_until:
            raise bad("A timer needs either duration (seconds) or until (a date and time)")
        if has_duration:
            ends = now + _seconds(body["duration"], "duration", allow_zero=False) * 1000
        else:
            ends = _until_ms(c, body["until"])
            if ends <= now:
                raise bad("until is in the past")
            if ends - now > MAX_SECONDS * 1000:
                raise bad("until is more than a year away")
        a["count_up"] = False
        a["started_at"] = now
        a["ends_at"] = ends
        a["finished"] = False
        # How long "Time's up" stays once it gets there; null = until dismissed or cleared.
        after = body.get("finished_for")
        secs = 0 if after in (None, "") else _seconds(after, "finished_for")
        a["finished_for"] = secs or None
        a["expires_at"] = ends + secs * 1000 if secs else None
    return a


def _count_up(c, body: dict, a: dict, now: int, has_duration: bool, has_until: bool) -> dict:
    """A timer that counts up from `since` ("now" or an ISO date-time); `duration` is how long after `since` it goes
    (left out: until dismissed or cleared)."""
    if has_until:
        raise bad("A timer counts down to until or up from since, not both")
    since = body["since"]
    started = now if isinstance(since, str) and since.strip().lower() == "now" else _until_ms(c, since, "since")
    if started > now + 5000:
        raise bad("since is in the future")
    if now - started > MAX_SECONDS * 1000:
        raise bad("since is more than a year ago")
    started = min(started, now)
    secs = _seconds(body["duration"], "duration", allow_zero=False) if has_duration else 0
    expires = started + secs * 1000 if secs else None
    if expires is not None and expires <= now:
        raise bad("since plus duration is already over")
    a["chime"] = _bool(body, "chime", False)  # nothing to get to: a chime is played when it appears
    a.update(count_up=True, started_at=started, ends_at=None, finished=False, finished_for=None, expires_at=expires)
    return a


def out(a: dict) -> dict:
    return {k: v for k, v in a.items() if k != "display_ids"}


def for_device(display: dict | None) -> list[dict]:
    """What this device shows. The Home Assistant integration (a service, which shows nothing) sees every one."""
    _expire(now_ms())
    service = display is not None and display["layout"] == SERVICE
    shown = [out(a) for a in _alerts.values() if service or shown_on(a, display)]
    return sorted(shown, key=lambda a: a["created_at"])


async def add(c, body: dict) -> dict:
    a = build(c, body)
    if a["id"] not in _alerts and len(_alerts) >= MAX_ALERTS:
        raise bad(f"There are already {MAX_ALERTS} notifications and timers showing; clear some first")
    _alerts[a["id"]] = a  # the same id again replaces it (e.g. restarting a timer)
    _save(a)
    await hub.broadcast("alerts")
    return out(a)


def get(aid: str) -> dict | None:
    return _alerts.get(aid)


async def remove(ids: list[str], event: str | None = None, screen: str | None = None) -> list[str]:
    gone = [i for i in ids if i in _alerts]
    removed = [_alerts[i] for i in gone]
    _drop(gone)
    if gone:
        await hub.broadcast("alerts")
    if event:
        for a in removed:
            await announce(event, a, screen)
    return gone


def matching(screens: Any, c) -> list[str]:
    """Ids of the ones shown on any of these screens (all of them when `screens` is empty)."""
    ids, _ = resolve_targets(c, screens)
    if ids is None:
        return list(_alerts)
    wanted = set(ids)
    return [i for i, a in _alerts.items() if a["display_ids"] is None or wanted & set(a["display_ids"])]


async def announce(event: str, a: dict, screen: str | None = None) -> None:
    msg = {"type": "alert", "event": event, "id": a["id"], "kind": a["kind"],
           "title": a.get("title") or a.get("label") or "", "screen": screen}
    await hub.send(msg)


# ---------------------------------------------------------------- the clock

async def tick(now: int | None = None) -> None:
    """Timers that reached zero say so; the ones whose time is up go."""
    now = now_ms() if now is None else now
    for a in list(_alerts.values()):
        if a["kind"] == "timer" and not a["finished"] and a["ends_at"] is not None and a["ends_at"] <= now:
            a["finished"] = True
            _save(a)
            await announce("finished", a)
    if _expire(now):
        await hub.broadcast("alerts")


async def _run() -> None:
    while True:
        try:
            await tick()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Notifications and timers clock")
        await asyncio.sleep(1)


async def start() -> None:
    global _task
    _task = asyncio.get_running_loop().create_task(_run())


async def stop() -> None:
    global _task
    if _task:
        _task.cancel()
        _task = None
