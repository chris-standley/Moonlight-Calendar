"""GET /api/summary: everything the Home Assistant integration needs in one call."""
from __future__ import annotations

from datetime import date as date_cls, datetime, timedelta

from fastapi import APIRouter

from .. import __version__, db
from ..common import as_date, as_datetime
from .calendar import list_events, list_people
from .chores import chores_for_day, points
from .lists import get_items, get_lists
from .meals import list_meals

router = APIRouter(prefix="/api")

LOOKAHEAD_DAYS = 31


def _event_out(o: dict) -> dict:
    return {k: o[k] for k in ("id", "occurrence_id", "title", "person_ids", "start", "end", "all_day", "location")}


@router.get("/summary")
def summary(date: str | None = None, now: str | None = None):  # noqa: A002 - query param name is part of the API
    """`date` (default today) picks the chores/dinner day; `now` (default now) picks the next event."""
    now_dt = datetime.fromisoformat(as_datetime(now, "now")) if now else datetime.now().replace(second=0, microsecond=0)
    day = as_date(date, "date") if date else now_dt.date().isoformat()
    now_s = now_dt.strftime("%Y-%m-%dT%H:%M")

    people = list_people()
    balances = {b["person_id"]: b["balance"] for b in points()}
    chores = chores_for_day(day)
    d = date_cls.fromisoformat(day)
    dinners = [m for m in list_meals(day, (d + timedelta(days=1)).isoformat()) if m["slot"] == "dinner"]
    upcoming = list_events(now_dt.date().isoformat(), (now_dt.date() + timedelta(days=LOOKAHEAD_DAYS)).isoformat())
    # Not yet ended, in start order; all-day events count as "current" for the whole day.
    live = [o for o in upcoming if o["end"] > now_s]

    out_people = []
    for p in people:
        mine = [c for c in chores if c["person_id"] == p["id"]]
        done = sum(1 for c in mine if c["completed"])
        mine_events = [o for o in live if p["id"] in o["person_ids"]]
        out_people.append({
            **p,
            "balance": balances.get(p["id"], 0),
            "chores": [{k: c[k] for k in ("id", "title", "emoji", "points", "time_of_day", "completed", "streak")}
                       for c in mine],
            "chores_total": len(mine),
            "chores_done": done,
            "chores_left": len(mine) - done,
            "all_done": done == len(mine),
            "event": _event_out(mine_events[0]) if mine_events else None,
        })

    nxt = next((o for o in live if o["start"] >= now_s), None)
    lists = [{**lst, "items": get_items(lst["id"])} for lst in get_lists()]
    with db.connect() as c:
        family = db.get_setting(c, "family_name", db.DEFAULT_SETTINGS["family_name"])
    return {
        "version": __version__,
        "family_name": family,
        "date": day,
        "now": now_s,
        "people": out_people,
        "dinner": dinners[0] if dinners else None,
        "next_event": _event_out(nxt) if nxt else None,
        "lists": lists,
    }
