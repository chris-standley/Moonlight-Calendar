"""Read-only calendars from Home Assistant calendar entities ("Add from Home Assistant").

Typical entities: bin collection days (Waste Collection Schedule), the Workday integration, energy saving
sessions, school holidays. An account of kind "ha" holds one calendar; its `username` and `server_url` are the
entity id. Events come from HA's REST API (`GET /api/calendars/{entity}?start=&end=`, already expanded into
single occurrences), are turned into an ICS document and stored through the same path as a calendar link
(ics_feed.store), so a poll only rewrites the events that changed. Polled every MOONLIGHT_FEED_SECONDS.

Moonlight's own calendar entities (calendar.moonlight_*, from the Moonlight integration) are not offered:
they would show every event twice.
"""
from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote

import httpx
import icalendar

from . import caldav_sync, db, ha_client, ics_feed

OWN_PREFIX = "calendar.moonlight_"
TIMEOUT = 30.0

# Tests swap in an httpx.MockTransport.
transport: httpx.BaseTransport | None = None


class NotConnected(Exception):
    """No Home Assistant API token (not running as an add-on and MOONLIGHT_HA_TOKEN unset)."""


def _client() -> httpx.Client:
    conn = ha_client.connection()
    if not conn:
        raise NotConnected("Moonlight isn't connected to Home Assistant")
    base, token = conn
    return httpx.Client(base_url=base.rstrip("/"), transport=transport, timeout=TIMEOUT,
                        headers={"Authorization": f"Bearer {token}"})


def _get(path: str, params: dict | None = None):
    try:
        with _client() as client:
            r = client.get(path, params=params)
    except httpx.HTTPError as e:
        raise caldav_sync.SyncError(f"Couldn't reach Home Assistant: {e.__class__.__name__}")
    if r.status_code == 404:
        raise caldav_sync.SyncError("Home Assistant doesn't have that calendar any more")
    if r.status_code >= 400:
        raise caldav_sync.SyncError(f"Home Assistant replied HTTP {r.status_code}")
    try:
        return r.json()
    except ValueError:
        raise caldav_sync.SyncError("Home Assistant sent something that isn't JSON")


def list_calendars() -> list[dict]:
    """[{entity_id, name, added}] for HA's calendar entities, Moonlight's own left out."""
    found = _get("/calendars")
    with db.connect() as c:
        added = {r["username"] for r in db.rows(c, "SELECT username FROM accounts WHERE kind = 'ha'")}
    out = []
    for e in found if isinstance(found, list) else []:
        eid = str(e.get("entity_id") or "")
        if not eid.startswith("calendar.") or eid.startswith(OWN_PREFIX):
            continue
        out.append({"entity_id": eid, "name": str(e.get("name") or eid), "added": eid in added})
    return sorted(out, key=lambda x: x["name"].lower())


def _when(raw) -> date | datetime | None:
    if not isinstance(raw, dict):
        return None
    if raw.get("date"):
        return date.fromisoformat(str(raw["date"]))
    if raw.get("dateTime"):
        dt = datetime.fromisoformat(str(raw["dateTime"]).replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc) if dt.tzinfo else dt
    return None


def to_ics(entity_id: str, events: list[dict]) -> str:
    """HA's expanded occurrences -> one VCALENDAR (each occurrence its own UID, no RRULE)."""
    cal = icalendar.Calendar()
    cal.add("prodid", "-//Moonlight//Home Assistant calendar//EN")
    cal.add("version", "2.0")
    for ev in events:
        try:
            start, end = _when(ev.get("start")), _when(ev.get("end"))
        except ValueError:
            continue
        if start is None:
            continue
        if end is None or end <= start:
            end = start + timedelta(days=1) if not isinstance(start, datetime) else start
        base = str(ev.get("uid") or "") or f"{ev.get('summary', '')}|{start.isoformat()}"
        rid = str(ev.get("recurrence_id") or "") or (start.isoformat() if ev.get("rrule") else "")
        uid = f"ha-{hashlib.sha1(f'{entity_id}|{base}|{rid}'.encode()).hexdigest()[:20]}"
        v = icalendar.Event()
        v.add("uid", uid)
        v.add("summary", str(ev.get("summary") or "(no title)"))
        v.add("dtstart", start)
        v.add("dtend", end)
        if ev.get("description"):
            v.add("description", str(ev["description"]))
        if ev.get("location"):
            v.add("location", str(ev["location"]))
        cal.add_component(v)
    return cal.to_ical().decode("utf-8")


def fetch(entity_id: str) -> ics_feed.Fetched:
    """Blocking: the entity's events inside the kept window, as a fetched ICS document."""
    tz = caldav_sync.household_tz()
    on = ics_feed.today(tz)
    lo = datetime.combine(on - timedelta(days=ics_feed.PAST_DAYS), datetime.min.time(), tz)
    hi = datetime.combine(on + timedelta(days=ics_feed.FUTURE_DAYS), datetime.min.time(), tz)
    events = _get(f"/calendars/{quote(entity_id)}", {"start": lo.isoformat(), "end": hi.isoformat()})
    if not isinstance(events, list):
        raise caldav_sync.SyncError("Home Assistant sent an unexpected calendar reply")
    return ics_feed.Fetched(False, to_ics(entity_id, events))


def sync(acct: dict) -> bool:
    """Blocking poll of one HA calendar account (called from caldav_sync.sync_account under its lock)."""
    with db.connect() as c:
        cal = ics_feed.feed_calendar(c, acct["id"])
    if not cal:
        return False
    try:
        fetched = fetch(acct["username"])
    except NotConnected as e:
        raise caldav_sync.SyncError(str(e))
    return ics_feed.store(cal["id"], fetched)
