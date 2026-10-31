"""Countdowns (see countdowns.py): list, add, change, remove, and the well-known days to pick from."""
from __future__ import annotations

import json
from datetime import date

from fastapi import APIRouter, Body

from .. import countdowns, db, public_holidays
from ..common import as_date, bad, body_dict, hub, not_found, opt_str
from .calendar import list_people, next_occurrence

router = APIRouter(prefix="/api")

TITLE_MAX = 60
EMOJI_MAX = 16


def _today(value: str | None) -> date:
    return date.fromisoformat(as_date(value, "today")) if value else date.today()


def list_countdowns(today: date) -> list[dict]:
    people = list_people()
    with db.connect() as c:
        rows = db.rows(c, "SELECT * FROM countdowns ORDER BY date, created_at")
        region = public_holidays.region(c)
        cache: dict[str, date | None] = {}

        def next_of_event(event_id: str) -> date | None:
            if event_id not in cache:
                cache[event_id] = next_occurrence(c, event_id, today)
            return cache[event_id]

        return countdowns.resolve(rows, people, today, region, next_of_event)


@router.get("/countdowns")
def get_countdowns(today: str | None = None):
    """Every countdown with its next date and days to go, soonest first. `today` (default the add-on's date) is the
    screen's own day, so a screen just after midnight counts from the new day."""
    return list_countdowns(_today(today))


@router.get("/countdowns/suggestions")
def get_suggestions(today: str | None = None):
    """Well-known days (Christmas, Easter, Halloween, Mother's Day, ...) and the household's public holidays in the
    next year, soonest first, each with `taken` if it's already counted down to."""
    with db.connect() as c:
        region = public_holidays.region(c)
        taken = {r["special"] for r in db.rows(c, "SELECT special FROM countdowns WHERE special IS NOT NULL")}
    return countdowns.suggestions(_today(today), region, taken)


def _person_ids(c, value) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(p, str) for p in value):
        raise bad("person_ids must be a list of person ids")
    known = {r["id"] for r in db.rows(c, "SELECT id FROM people")}
    return [p for p in dict.fromkeys(value) if p in known]


def _apply(c, row: dict, body: dict, creating: bool) -> dict:
    if "special" in body and body["special"] not in (None, ""):
        key = body["special"]
        if not isinstance(key, str) or not countdowns.valid_special(key):
            raise bad("special must be one of the well-known days, or holiday:<public holiday name>")
        row["special"], row["event_id"] = key, None
        title, emoji = countdowns.special_title(key)
        if creating:
            row["title"], row["emoji"] = title, emoji
        d = countdowns.next_special(key, date.today(), public_holidays.region(c))
        if d is None:
            raise bad("That day isn't coming up in the next two years")
        row["date"], row["yearly"] = d.isoformat(), 1
    elif "special" in body:
        row["special"] = None
    if "event_id" in body and body["event_id"] not in (None, ""):
        ev = db.row(c, "SELECT id, title, start FROM events WHERE id = ?", (str(body["event_id"]),))
        if not ev:
            raise bad("event_id must be an existing event")
        row["event_id"], row["special"] = ev["id"], None
        if creating:
            row["title"] = ev["title"]
        row["date"] = ev["start"][:10]
    elif "event_id" in body:
        row["event_id"] = None
    if "title" in body:
        title = opt_str(body, "title").strip()
        if not title:
            raise bad("title is required")
        if len(title) > TITLE_MAX:
            raise bad(f"title must be at most {TITLE_MAX} characters")
        row["title"] = title
    if "emoji" in body:
        emoji = opt_str(body, "emoji").strip()
        if len(emoji) > EMOJI_MAX:
            raise bad("emoji must be one emoji")
        row["emoji"] = emoji
    if "date" in body and not row.get("special"):
        row["date"] = as_date(body["date"], "date")
    if "yearly" in body and not row.get("special"):
        if not isinstance(body["yearly"], bool):
            raise bad("yearly must be a boolean")
        row["yearly"] = int(body["yearly"])
    if "person_ids" in body:
        row["person_ids"] = json.dumps(_person_ids(c, body["person_ids"]))
    if creating:
        if not row.get("title"):
            raise bad("title is required")
        if not row.get("date"):
            raise bad("date is required")
    return row


@router.post("/countdowns")
async def create_countdown(body: dict = Body(...)):
    """{title, emoji, date, yearly, person_ids}, or {special} for a well-known day or public holiday (title and emoji
    default to its own), or {event_id} to follow a calendar event (title defaults to the event's)."""
    body = body_dict(body)
    with db.connect() as c:
        row = _apply(c, {"id": db.new_id("cd"), "emoji": "", "yearly": 0, "special": None, "event_id": None,
                         "person_ids": "[]"}, body, creating=True)
        c.execute("INSERT INTO countdowns(id, title, emoji, date, yearly, special, event_id, person_ids, created_at) "
                  "VALUES(?,?,?,?,?,?,?,?,?)",
                  (row["id"], row["title"], row["emoji"], row["date"], row["yearly"], row["special"],
                   row["event_id"], row["person_ids"], db.now_iso()))
    await hub.broadcast("countdowns")
    return _one(row["id"])


def _one(cid: str) -> dict:
    found = next((o for o in list_countdowns(date.today()) if o["id"] == cid), None)
    if found:
        return found
    with db.connect() as c:  # a one-off day that's already gone
        r = db.row(c, "SELECT * FROM countdowns WHERE id = ?", (cid,))
    if not r:
        raise not_found("Countdown not found")
    return countdowns.resolve([r], list_people(), date.fromisoformat(r["date"]), {}, lambda _e: None)[0] | {
        "days": (date.fromisoformat(r["date"]) - date.today()).days}


@router.patch("/countdowns/{countdown_id}")
async def update_countdown(countdown_id: str, body: dict = Body(...)):
    body = body_dict(body)
    with db.connect() as c:
        row = db.row(c, "SELECT * FROM countdowns WHERE id = ?", (countdown_id,))
        if not row:
            raise not_found("Countdown not found")
        row = _apply(c, row, body, creating=False)
        c.execute("UPDATE countdowns SET title=?, emoji=?, date=?, yearly=?, special=?, event_id=?, person_ids=? "
                  "WHERE id=?", (row["title"], row["emoji"], row["date"], row["yearly"], row["special"],
                                 row["event_id"], row["person_ids"], countdown_id))
    await hub.broadcast("countdowns")
    return _one(countdown_id)


@router.delete("/countdowns/{countdown_id}")
async def delete_countdown(countdown_id: str):
    with db.connect() as c:
        if not c.execute("DELETE FROM countdowns WHERE id = ?", (countdown_id,)).rowcount:
            raise not_found("Countdown not found")
    await hub.broadcast("countdowns")
    return {"ok": True}
