"""Settings, PIN, people and events."""
from __future__ import annotations

import asyncio
import json
import re
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Body, HTTPException

from .. import caldav_sync, db
from ..common import (
    as_datetime, as_int, bad, body_dict, choice, hub, next_sort, not_found, opt_str,
    person_exists, req_str, require_pin,
)
from ..recurrence import expand_event, normalize_repeat
from . import photos

router = APIRouter(prefix="/api")

# ---------------------------------------------------------------- settings


def settings_out(c) -> dict:
    out = {k: db.get_setting(c, k, v) for k, v in db.default_settings().items()}
    out["pin_set"] = bool(db.get_setting(c, "pin_hash"))
    return out


@router.get("/settings")
def get_settings():
    with db.connect() as c:
        return settings_out(c)


@router.patch("/settings")
async def patch_settings(body: dict = Body(...)):
    body = body_dict(body)
    pin = body.get("pin")
    if pin is None or str(pin) == "":
        raise bad("pin is required")
    with db.connect() as c:
        if db.get_setting(c, "pin_hash"):
            require_pin(c, pin)
        else:
            db.set_pin(c, str(pin))  # first PIN supplied becomes the household PIN
        if "family_name" in body:
            db.set_setting(c, "family_name", req_str(body, "family_name"))
        if "week_start" in body:
            db.set_setting(c, "week_start", choice(body["week_start"], "week_start", ("monday", "sunday")))
        if "temp_unit" in body:
            db.set_setting(c, "temp_unit", choice(body["temp_unit"], "temp_unit", ("C", "F")))
        if "chore_approval" in body:
            if not isinstance(body["chore_approval"], bool):
                raise bad("chore_approval must be a boolean")
            db.set_setting(c, "chore_approval", body["chore_approval"])
        photos.apply_settings(c, body)  # screensaver_album, screensaver_seconds, idle_minutes
        tz_changed = False
        if "timezone" in body:
            try:
                ZoneInfo(str(body["timezone"]))
            except Exception:
                raise bad("timezone must be an IANA zone name like Europe/London")
            tz_changed = db.get_setting(c, "timezone", db.default_timezone()) != body["timezone"]
            db.set_setting(c, "timezone", str(body["timezone"]))
        if body.get("new_pin") not in (None, ""):
            db.set_pin(c, str(body["new_pin"]))
        out = settings_out(c)
    if tz_changed:
        await asyncio.to_thread(caldav_sync.reparse_all)
        await hub.broadcast("events")
    await hub.broadcast("settings")
    return out


@router.post("/pin/verify")
def verify_pin(body: dict = Body(...)):
    body = body_dict(body)
    with db.connect() as c:
        return {"ok": db.verify_pin(c, body.get("pin"))}


# ---------------------------------------------------------------- people

ROLES = ("adult", "child")
NAME_MAX = 40
HEX_COLOR = re.compile(r"^#(?:[0-9A-Fa-f]{3}|[0-9A-Fa-f]{6})$")


def person_name(body: dict) -> str:
    name = req_str(body, "name")
    if len(name) > NAME_MAX:
        raise bad(f"name must be at most {NAME_MAX} characters")
    return name


def person_color(body: dict) -> str:
    color = req_str(body, "color")
    if not HEX_COLOR.match(color):
        raise bad("color must look like #RRGGBB")
    if len(color) == 4:  # #RGB -> #RRGGBB (screens tint the colour, which needs six digits)
        color = "#" + "".join(ch * 2 for ch in color[1:])
    return color.upper()


def initials(name: str) -> str:
    parts = [p for p in name.split() if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][0].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def person_out(r: dict) -> dict:
    return {
        "id": r["id"], "name": r["name"], "initials": initials(r["name"]),
        "color": r["color"], "role": r["role"], "sort": r["sort"],
    }


@router.get("/people")
def list_people():
    with db.connect() as c:
        return [person_out(r) for r in db.rows(c, "SELECT * FROM people ORDER BY sort, name")]


@router.post("/people")
async def create_person(body: dict = Body(...)):
    body = body_dict(body)
    name = person_name(body)
    color = person_color(body)
    role = choice(body.get("role", "child"), "role", ROLES)
    with db.connect() as c:
        pid = db.new_id("p")
        sort = as_int(body["sort"], "sort") if "sort" in body else next_sort(c, "people")
        c.execute("INSERT INTO people(id, name, color, role, sort) VALUES(?,?,?,?,?)",
                  (pid, name, color, role, sort))
        out = person_out(db.row(c, "SELECT * FROM people WHERE id = ?", (pid,)))
    await hub.broadcast("people", "points")
    return out


@router.patch("/people/{person_id}")
async def update_person(person_id: str, body: dict = Body(...)):
    body = body_dict(body)
    with db.connect() as c:
        r = db.row(c, "SELECT * FROM people WHERE id = ?", (person_id,))
        if not r:
            raise not_found("Person not found")
        if "name" in body:
            r["name"] = person_name(body)
        if "color" in body:
            r["color"] = person_color(body)
        if "role" in body:
            r["role"] = choice(body["role"], "role", ROLES)
        if "sort" in body:
            r["sort"] = as_int(body["sort"], "sort")
        c.execute("UPDATE people SET name=?, color=?, role=?, sort=? WHERE id=?",
                  (r["name"], r["color"], r["role"], r["sort"], person_id))
        out = person_out(r)
    await hub.broadcast("people")
    return out


@router.delete("/people/{person_id}")
async def delete_person(person_id: str, body: dict | None = Body(None)):
    body = body_dict(body)
    with db.connect() as c:
        require_pin(c, body.get("pin"))
        if not person_exists(c, person_id):
            raise not_found("Person not found")
        c.execute("DELETE FROM people WHERE id = ?", (person_id,))
        # Detach from events; drop their chores, completions, ledger and personal rewards.
        for ev in db.rows(c, "SELECT id, person_ids FROM events"):
            ids = json.loads(ev["person_ids"])
            if person_id in ids:
                ids.remove(person_id)
                c.execute("UPDATE events SET person_ids = ? WHERE id = ?", (json.dumps(ids), ev["id"]))
        c.execute("DELETE FROM completions WHERE chore_id IN (SELECT id FROM chores WHERE person_id = ?)",
                  (person_id,))
        c.execute("DELETE FROM chores WHERE person_id = ?", (person_id,))
        c.execute("DELETE FROM ledger WHERE person_id = ?", (person_id,))
        c.execute("DELETE FROM rewards WHERE person_id = ?", (person_id,))
        c.execute("UPDATE items SET person_id = NULL WHERE person_id = ?", (person_id,))
        for cal in db.rows(c, "SELECT id, person_ids FROM calendars"):
            ids = json.loads(cal["person_ids"])
            if person_id in ids:
                ids.remove(person_id)
                c.execute("UPDATE calendars SET person_ids = ? WHERE id = ?", (json.dumps(ids), cal["id"]))
    # "accounts": calendars' person mappings changed too (Settings > Calendars refetches on it).
    await hub.broadcast("people", "events", "chores", "points", "rewards", "lists", "accounts")
    return {"ok": True}


# ---------------------------------------------------------------- events


# Synced events (calendar_id set) take their people from the calendar mapping unless the event
# names its own (X-MOONLIGHT-PEOPLE), and their colour from the calendar.
EVENT_SELECT = ("SELECT e.*, cal.person_ids AS cal_person_ids, cal.color AS cal_color, a.kind AS source "
                "FROM events e LEFT JOIN calendars cal ON cal.id = e.calendar_id "
                "LEFT JOIN accounts a ON a.id = cal.account_id")


def event_out(r: dict) -> dict:
    out = {
        "id": r["id"], "title": r["title"], "person_ids": json.loads(r["person_ids"]),
        "start": r["start"], "end": r["end"], "all_day": bool(r["all_day"]),
        "location": r["location"], "notes": r["notes"],
        "repeat": json.loads(r["repeat"]) if r["repeat"] else None,
        "calendar_id": r.get("calendar_id"), "source": r.get("source"),
        "custom_repeat": bool(r.get("custom_repeat")), "color": r.get("cal_color"),
    }
    if out["calendar_id"] and not out["person_ids"]:
        out["person_ids"] = json.loads(r.get("cal_person_ids") or "[]")
    return out


def _load_event(c, event_id: str) -> dict | None:
    return db.row(c, EVENT_SELECT + " WHERE e.id = ?", (event_id,))


def _sync_error(e: Exception) -> HTTPException:
    if isinstance(e, ValueError):
        return bad(str(e))
    return HTTPException(status_code=getattr(e, "status", 502), detail=str(e))


def _apply_event_fields(c, ev: dict, body: dict, creating: bool) -> dict:
    if creating or "title" in body:
        ev["title"] = req_str(body, "title")
    if creating or "person_ids" in body:
        ids = body.get("person_ids") or []
        if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
            raise bad("person_ids must be a list of ids")
        for i in ids:
            if not person_exists(c, i):
                raise bad(f"Unknown person {i}")
        ev["person_ids"] = list(dict.fromkeys(ids))
    if "all_day" in body or creating:
        ev["all_day"] = bool(body.get("all_day", False))
    if creating or "start" in body:
        ev["start"] = as_datetime(body.get("start"), "start")
    if creating or "end" in body:
        ev["end"] = as_datetime(body.get("end"), "end") if body.get("end") is not None else None
    if ev.get("end") is None:
        ev["end"] = ev["start"]
    if ev["all_day"]:
        # Snap to midnight; end is exclusive, so at least the next day.
        s = datetime.fromisoformat(ev["start"]).date()
        e = datetime.fromisoformat(ev["end"])
        e_day = e.date() if e.time() == time(0) else date.fromordinal(e.date().toordinal() + 1)
        if e_day <= s:
            e_day = date.fromordinal(s.toordinal() + 1)
        ev["start"] = f"{s.isoformat()}T00:00"
        ev["end"] = f"{e_day.isoformat()}T00:00"
    if ev["end"] < ev["start"]:
        raise bad("end must not be before start")
    if creating or "location" in body:
        ev["location"] = opt_str(body, "location")
    if creating or "notes" in body:
        ev["notes"] = opt_str(body, "notes")
    if creating or "repeat" in body:
        try:
            ev["repeat"] = normalize_repeat(body.get("repeat"))
        except ValueError as e:
            raise bad(str(e))
    return ev


def _save_event(c, ev: dict, insert: bool) -> None:
    args = (ev["title"], json.dumps(ev["person_ids"]), ev["start"], ev["end"], int(ev["all_day"]),
            ev["location"], ev["notes"], json.dumps(ev["repeat"]) if ev["repeat"] else None, ev["id"])
    if insert:
        c.execute('INSERT INTO events(title, person_ids, start, "end", all_day, location, notes, repeat, id) '
                  "VALUES(?,?,?,?,?,?,?,?,?)", args)
    else:
        c.execute('UPDATE events SET title=?, person_ids=?, start=?, "end"=?, all_day=?, location=?, notes=?, '
                  "repeat=? WHERE id=?", args)


@router.get("/events")
def list_events(start: str, end: str):
    try:
        rs = datetime.combine(date.fromisoformat(start), time(0))
        re_ = datetime.combine(date.fromisoformat(end), time(0))
    except ValueError:
        raise bad("start and end must be YYYY-MM-DD")
    if re_ <= rs:
        return []
    rs_s, re_s = rs.strftime("%Y-%m-%dT%H:%M"), re_.strftime("%Y-%m-%dT%H:%M")
    with db.connect() as c:
        # Repeating series are expanded in Python; one-offs are pre-filtered in SQL.
        candidates = db.rows(
            c,
            EVENT_SELECT + ' WHERE (e.calendar_id IS NULL OR cal.visible = 1) AND (e.repeat IS NOT NULL '
            'OR e.custom_repeat = 1 OR (e.start < ? AND (e."end" > ? OR e.start >= ?)))',
            (re_s, rs_s, rs_s),
        )
    out = []
    for r in candidates:
        if r.get("custom_repeat") and r.get("raw_ics"):
            out.extend(caldav_sync.expand_custom(event_out(r), r["raw_ics"], f"{r['id']}:{r['etag']}", rs, re_))
        else:
            out.extend(expand_event(event_out(r), rs, re_))
    out.sort(key=lambda o: (o["start"], not o["all_day"], o["end"], o["title"]))
    return out


@router.get("/events/{event_id}")
def get_event(event_id: str):
    with db.connect() as c:
        r = _load_event(c, event_id)
    if not r:
        raise not_found("Event not found")
    return event_out(r)


@router.post("/events")
async def create_event(body: dict = Body(...)):
    body = body_dict(body)
    with db.connect() as c:
        ev = _apply_event_fields(c, {"id": db.new_id("e")}, body, creating=True)
        try:
            target = caldav_sync.target_calendar(c, body, ev["person_ids"])
        except ValueError as e:
            raise bad(str(e))
        if target is None:
            _save_event(c, ev, insert=True)
    if target is not None:  # written to iCloud first; stored once the server accepts it
        try:
            await asyncio.to_thread(caldav_sync.save_event, None, ev, target, True)
        except (caldav_sync.SyncError, ValueError) as e:
            await hub.broadcast("accounts")
            raise _sync_error(e)
    with db.connect() as c:
        out = event_out(_load_event(c, ev["id"]))
    await hub.broadcast("events")
    return out


@router.patch("/events/{event_id}")
async def update_event(event_id: str, body: dict = Body(...)):
    body = body_dict(body)
    with db.connect() as c:
        r = _load_event(c, event_id)
        if not r:
            raise not_found("Event not found")
        ev = _apply_event_fields(c, event_out(r), body, creating=False)
        try:
            target = caldav_sync.target_calendar(c, body, ev["person_ids"], current=r["calendar_id"])
        except ValueError as e:
            raise bad(str(e))
        if target is None and r["calendar_id"] is None:
            _save_event(c, ev, insert=False)
    if target is not None or r["calendar_id"] is not None:
        try:
            await asyncio.to_thread(caldav_sync.save_event, r, ev, target, "repeat" in body)
        except (caldav_sync.SyncError, ValueError) as e:
            await hub.broadcast("events", "accounts")
            raise _sync_error(e)
        if target is None:  # moved from a synced calendar to local-only
            with db.connect() as c:
                _save_event(c, ev, insert=False)
    with db.connect() as c:
        out = event_out(_load_event(c, event_id))
    await hub.broadcast("events")
    return out


@router.delete("/events/{event_id}")
async def delete_event(event_id: str):
    with db.connect() as c:
        r = db.row(c, "SELECT * FROM events WHERE id = ?", (event_id,))
        if not r:
            raise not_found("Event not found")
        if r["calendar_id"] is None:
            c.execute("DELETE FROM events WHERE id = ?", (event_id,))
    if r["calendar_id"] is not None:
        try:
            await asyncio.to_thread(caldav_sync.delete_event, r)
        except caldav_sync.SyncError as e:
            await hub.broadcast("events", "accounts")
            raise _sync_error(e)
    await hub.broadcast("events")
    return {"ok": True}
