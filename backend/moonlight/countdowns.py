"""Countdowns: "55 days to Christmas" on the screens' top bar and screensaver.

Three kinds, all listed by GET /api/countdowns soonest first:
- the family's own (table `countdowns`): a date, once or every year ("Holiday in Spain", "Wedding anniversary");
  or one of the well-known days below ("christmas", "easter", ...) whose date is worked out for each year; or one of
  the household's public holidays by name ("holiday:Early May Bank Holiday"); or a calendar event, following the
  event if it moves (its next occurrence when it repeats);
- everyone's birthday, for people with one set (people.birthday, "2018-11-23", or "11-23" without the year).
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Callable

from dateutil.easter import easter

from . import db, public_holidays

SCHEMA = """
CREATE TABLE IF NOT EXISTS countdowns (
    id         TEXT PRIMARY KEY,
    title      TEXT NOT NULL,
    emoji      TEXT NOT NULL DEFAULT '',
    date       TEXT NOT NULL,              -- YYYY-MM-DD: the day (once), the first one (yearly), or the last known
                                           -- date of a special day or event
    yearly     INTEGER NOT NULL DEFAULT 0,
    special    TEXT,                       -- a key of SPECIAL_DAYS, or "holiday:<public holiday name>"
    event_id   TEXT,                       -- follows this event's next occurrence while it exists
    person_ids TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);
"""

HOLIDAY_PREFIX = "holiday:"
LOOKAHEAD_YEARS = 2  # a special day or event further away than this isn't shown


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """The nth (1-based; -1 = last) weekday (Mon=0) of a month."""
    if n > 0:
        d = date(year, month, 1)
        d += timedelta(days=(weekday - d.weekday()) % 7)
        return d + timedelta(weeks=n - 1)
    d = date(year + month // 12, month % 12 + 1, 1) - timedelta(days=1)
    return d - timedelta(days=(d.weekday() - weekday) % 7)


def _mothers_day(year: int, country: str) -> date:
    if country in ("GB", "IE"):  # Mothering Sunday: three weeks before Easter
        return easter(year) - timedelta(days=21)
    return _nth_weekday(year, 5, 6, 2)


# key: (title, emoji, date for a year and country, countries it's offered in (None = everywhere))
SPECIAL_DAYS: dict[str, tuple[str, str, Callable[[int, str], date], tuple[str, ...] | None]] = {
    "christmas": ("Christmas", "🎄", lambda y, c: date(y, 12, 25), None),
    "christmas_eve": ("Christmas Eve", "🎅", lambda y, c: date(y, 12, 24), None),
    "new_years_eve": ("New Year's Eve", "🎆", lambda y, c: date(y, 12, 31), None),
    "halloween": ("Halloween", "🎃", lambda y, c: date(y, 10, 31), None),
    "bonfire_night": ("Bonfire Night", "🎇", lambda y, c: date(y, 11, 5), ("GB",)),
    "valentines": ("Valentine's Day", "❤️", lambda y, c: date(y, 2, 14), None),
    "pancake_day": ("Pancake Day", "🥞", lambda y, c: easter(y) - timedelta(days=47), ("GB", "IE")),
    "st_patricks": ("St Patrick's Day", "☘️", lambda y, c: date(y, 3, 17), ("IE", "GB", "US")),
    "easter": ("Easter", "🐣", lambda y, c: easter(y), None),
    "mothers_day": ("Mother's Day", "💐", _mothers_day, None),
    "fathers_day": ("Father's Day", "👔", lambda y, c: _nth_weekday(y, 6, 6, 3), None),
    "thanksgiving": ("Thanksgiving", "🦃", lambda y, c: _nth_weekday(y, 11, 3, 4), ("US",)),
}


def special_date(key: str, year: int, region: dict) -> date | None:
    if key.startswith(HOLIDAY_PREFIX):
        name = key[len(HOLIDAY_PREFIX):]
        found = [h for h in public_holidays.between(region, date(year, 1, 1), date(year, 12, 31)) if h["name"] == name]
        return date.fromisoformat(found[0]["date"]) if found else None
    sd = SPECIAL_DAYS.get(key)
    return sd[2](year, region.get("country") or "") if sd else None


def next_special(key: str, today: date, region: dict) -> date | None:
    for y in range(today.year, today.year + LOOKAHEAD_YEARS + 1):
        d = special_date(key, y, region)
        if d and d >= today:
            return d
    return None


def valid_special(key: str) -> bool:
    return key in SPECIAL_DAYS or (key.startswith(HOLIDAY_PREFIX) and len(key) > len(HOLIDAY_PREFIX))


def _on_year(month: int, day: int, year: int) -> date:
    try:
        return date(year, month, day)
    except ValueError:  # 29 February outside a leap year
        return date(year, month, 28)


def next_yearly(first: date, today: date) -> date:
    d = _on_year(first.month, first.day, today.year)
    return d if d >= today else _on_year(first.month, first.day, today.year + 1)


def parse_birthday(value: str | None) -> tuple[int | None, int, int] | None:
    """(year or None, month, day) from "2018-11-23" or "11-23"."""
    if not value:
        return None
    parts = value.split("-")
    try:
        if len(parts) == 3:
            d = date.fromisoformat(value)
            return d.year, d.month, d.day
        if len(parts) == 2:
            m, dd = int(parts[0]), int(parts[1])
            date(2024, m, dd)  # a leap year, so 02-29 is fine
            return None, m, dd
    except ValueError:
        pass
    return None


def normalize_birthday(value) -> str | None:
    """Stored form, or ValueError. Empty clears it."""
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise ValueError
    value = value.strip()
    if value.startswith("--"):  # vCard style, --11-23
        value = value[2:]
    b = parse_birthday(value)
    if not b:
        raise ValueError
    y, m, d = b
    return f"{y:04d}-{m:02d}-{d:02d}" if y else f"{m:02d}-{d:02d}"


def _out(kind: str, cid: str, title: str, emoji: str, day: date, today: date, **extra) -> dict:
    return {"id": cid, "kind": kind, "title": title, "emoji": emoji, "date": day.isoformat(),
            "days": (day - today).days, "person_ids": [], "yearly": False, "special": None, "event_id": None,
            "turns": None, **extra}


def birthdays(people: list[dict], today: date) -> list[dict]:
    out = []
    for p in people:
        b = parse_birthday(p.get("birthday"))
        if not b:
            continue
        y, m, d = b
        day = next_yearly(date(2024, m, d), today)
        turns = day.year - y if y and day.year > y else None
        out.append(_out("birthday", f"birthday:{p['id']}", f"{p['name']}'s birthday", "🎂", day, today,
                        person_ids=[p["id"]], yearly=True, turns=turns))
    return out


def resolve(rows: list[dict], people: list[dict], today: date, region: dict,
            next_of_event: Callable[[str], date | None]) -> list[dict]:
    """Every countdown with its next date, soonest first. Past one-off days are left out (they stay on "today" for
    the day itself)."""
    known = {p["id"] for p in people}
    out = []
    for r in rows:
        stored = date.fromisoformat(r["date"])
        kind, day = "custom", stored
        if r.get("event_id"):
            kind = "event"
            day = next_of_event(r["event_id"]) or stored
        elif r.get("special"):
            kind = "special"
            day = next_special(r["special"], today, region) or stored
        elif r["yearly"]:
            day = next_yearly(stored, today)
        if day < today:
            continue
        out.append(_out(kind, r["id"], r["title"], r["emoji"], day, today,
                        person_ids=[p for p in json.loads(r["person_ids"] or "[]") if p in known],
                        yearly=bool(r["yearly"]), special=r.get("special"), event_id=r.get("event_id"),
                        stored_date=r["date"]))
    out.extend(birthdays(people, today))
    out.sort(key=lambda o: (o["date"], o["kind"] == "birthday", o["title"]))
    for o in out:
        o.pop("stored_date", None)
    return out


def suggestions(today: date, region: dict, taken: set[str]) -> list[dict]:
    """Well-known days and the household's public holidays in the next year, soonest first, for "Add countdown".
    `taken`: special keys already counted down to."""
    country = region.get("country") or ""
    out, dates = [], set()
    for key, (title, emoji, _fn, where) in SPECIAL_DAYS.items():
        if where is not None and country not in where:
            continue
        d = next_special(key, today, region)
        if d:
            dates.add(d)
            out.append({"special": key, "title": title, "emoji": emoji, "date": d.isoformat(),
                        "days": (d - today).days, "taken": key in taken})
    seen = set()
    for h in public_holidays.between(region, today, today + timedelta(days=366)):
        d = date.fromisoformat(h["date"])
        key = HOLIDAY_PREFIX + h["name"]
        if d in dates or key in seen or "(observed)" in h["name"]:  # Christmas Day is already "Christmas"
            continue
        seen.add(key)
        out.append({"special": key, "title": h["name"], "emoji": "🗓️", "date": h["date"],
                    "days": (d - today).days, "taken": key in taken})
    out.sort(key=lambda s: s["date"])
    return out


def special_title(key: str) -> tuple[str, str]:
    if key in SPECIAL_DAYS:
        return SPECIAL_DAYS[key][0], SPECIAL_DAYS[key][1]
    return key[len(HOLIDAY_PREFIX):], "🗓️"
