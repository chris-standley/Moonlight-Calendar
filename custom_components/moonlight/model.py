"""Pure parsing and mapping helpers for the Moonlight integration.

Nothing in this module imports Home Assistant or aiohttp (and it uses no relative imports), so it can be
unit-tested on its own: see tests/test_moonlight_model.py at the repo root.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, tzinfo
from typing import Any

NOTHING_PLANNED = "Nothing planned"


# ---------------------------------------------------------------- data

@dataclass(frozen=True)
class Event:
    id: str
    occurrence_id: str
    title: str
    person_ids: tuple[str, ...]
    start: datetime          # household-local, naive
    end: datetime            # exclusive
    all_day: bool
    location: str = ""
    notes: str = ""
    recurring: bool = False


@dataclass(frozen=True)
class Chore:
    id: str
    title: str
    emoji: str
    points: int
    time_of_day: str
    completed: bool


@dataclass(frozen=True)
class Person:
    id: str
    name: str
    role: str
    color: str
    balance: int
    chores: tuple[Chore, ...]
    event: Event | None

    @property
    def is_child(self) -> bool:
        return self.role == "child"

    @property
    def chores_done(self) -> int:
        return sum(1 for c in self.chores if c.completed)

    @property
    def chores_left(self) -> int:
        return len(self.chores) - self.chores_done

    @property
    def all_done(self) -> bool:
        return self.chores_left == 0

    @property
    def remaining(self) -> list[str]:
        return [c.title for c in self.chores if not c.completed]


@dataclass(frozen=True)
class Item:
    id: str
    title: str
    done: bool
    due: date | None
    person_id: str | None


@dataclass(frozen=True)
class TodoList:
    id: str
    name: str
    emoji: str
    kind: str
    items: tuple[Item, ...]

    @property
    def open_count(self) -> int:
        return sum(1 for i in self.items if not i.done)


@dataclass(frozen=True)
class Meal:
    id: str
    date: date
    title: str
    notes: str


@dataclass(frozen=True)
class Summary:
    version: str
    family_name: str
    date: date
    people: tuple[Person, ...]
    dinner: Meal | None
    next_event: Event | None
    lists: tuple[TodoList, ...]
    by_id: dict[str, Person] = field(default_factory=dict, compare=False, repr=False)

    def person(self, person_id: str) -> Person | None:
        return self.by_id.get(person_id)

    def todo_list(self, list_id: str) -> TodoList | None:
        return next((lst for lst in self.lists if lst.id == list_id), None)

    def names(self, person_ids: tuple[str, ...] | list[str]) -> list[str]:
        return [self.by_id[p].name for p in person_ids if p in self.by_id]


# ---------------------------------------------------------------- parsing

def _dt(value: Any) -> datetime:
    return datetime.fromisoformat(str(value))


def _date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    return date.fromisoformat(str(value)[:10])


def parse_event(raw: dict) -> Event:
    return Event(
        id=str(raw["id"]),
        occurrence_id=str(raw.get("occurrence_id") or raw["id"]),
        title=str(raw.get("title") or ""),
        person_ids=tuple(raw.get("person_ids") or ()),
        start=_dt(raw["start"]),
        end=_dt(raw["end"]),
        all_day=bool(raw.get("all_day")),
        location=str(raw.get("location") or ""),
        notes=str(raw.get("notes") or ""),
        recurring=bool(raw.get("recurring")),
    )


def parse_chore(raw: dict) -> Chore:
    return Chore(id=str(raw["id"]), title=str(raw.get("title") or ""), emoji=str(raw.get("emoji") or ""),
                 points=int(raw.get("points") or 0), time_of_day=str(raw.get("time_of_day") or "anytime"),
                 completed=bool(raw.get("completed")))


def parse_item(raw: dict) -> Item:
    return Item(id=str(raw["id"]), title=str(raw.get("title") or ""), done=bool(raw.get("done")),
                due=_date(raw.get("due")), person_id=raw.get("person_id"))


def parse_summary(raw: Any) -> Summary:
    """Parse GET /api/summary. Raises ValueError on anything that doesn't look like Moonlight."""
    if not isinstance(raw, dict) or not isinstance(raw.get("people"), list):
        raise ValueError("not a Moonlight summary")
    try:
        people = tuple(
            Person(id=str(p["id"]), name=str(p["name"]), role=str(p.get("role") or "adult"),
                   color=str(p.get("color") or ""), balance=int(p.get("balance") or 0),
                   chores=tuple(parse_chore(c) for c in p.get("chores") or ()),
                   event=parse_event(p["event"]) if p.get("event") else None)
            for p in raw["people"]
        )
        dinner = raw.get("dinner")
        lists = tuple(
            TodoList(id=str(lst["id"]), name=str(lst["name"]), emoji=str(lst.get("emoji") or ""),
                     kind=str(lst.get("kind") or "todo"),
                     items=tuple(parse_item(i) for i in lst.get("items") or ()))
            for lst in raw.get("lists") or ()
        )
        return Summary(
            version=str(raw.get("version") or ""),
            family_name=str(raw.get("family_name") or ""),
            date=date.fromisoformat(str(raw["date"])),
            people=people,
            dinner=Meal(id=str(dinner["id"]), date=date.fromisoformat(str(dinner["date"])),
                        title=str(dinner["title"]), notes=str(dinner.get("notes") or "")) if dinner else None,
            next_event=parse_event(raw["next_event"]) if raw.get("next_event") else None,
            lists=lists,
            by_id={p.id: p for p in people},
        )
    except (KeyError, TypeError, ValueError) as err:
        raise ValueError(f"bad Moonlight summary: {err}") from err


def health_version(raw: Any) -> str:
    """Validate GET /api/health; returns the Moonlight version."""
    if not isinstance(raw, dict) or raw.get("ok") is not True:
        raise ValueError("not a Moonlight health response")
    return str(raw.get("version") or "")


def base_url(host: str, port: int) -> str:
    """`host` may be a bare host/IP, an IPv6 address, or a URL with a scheme (port then taken from it if given)."""
    host = host.strip().rstrip("/")
    if host.startswith(("http://", "https://")):
        scheme, rest = host.split("://", 1)
        if ":" in rest.rsplit("]", 1)[-1]:
            return f"{scheme}://{rest}"
        return f"{scheme}://{rest}:{port}"
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"  # IPv6 literal
    return f"http://{host}:{port}"


def ws_url(http_base: str) -> str:
    return "ws" + http_base[4:] + "/api/ws" if http_base.startswith("http") else http_base + "/api/ws"


def is_change_message(text: str) -> bool:
    """True for Moonlight's {"type":"changed","topic":...} WebSocket messages."""
    try:
        msg = json.loads(text)
    except (TypeError, ValueError):
        return False
    return isinstance(msg, dict) and msg.get("type") == "changed"


ALERT_EVENTS = ("finished", "dismissed")


def parse_alert_event(text: str) -> dict | None:
    """Moonlight's {"type":"alert","event":"finished"|"dismissed",...} message as event data, else None."""
    try:
        msg = json.loads(text)
    except (TypeError, ValueError):
        return None
    if not isinstance(msg, dict) or msg.get("type") != "alert" or msg.get("event") not in ALERT_EVENTS:
        return None
    return {"event": msg["event"], "id": str(msg.get("id") or ""), "kind": msg.get("kind"),
            "title": msg.get("title") or "", "screen": msg.get("screen")}


def backoff(attempt: int, base: float = 1.0, cap: float = 300.0) -> float:
    """Reconnect delay: 1, 2, 4, ... seconds, capped at 5 minutes."""
    return min(cap, base * 2 ** max(0, min(attempt, 20)))


# ---------------------------------------------------------------- pairing

PAIR_NAME = "Home Assistant"
PAIR_LAYOUT = "service"  # Moonlight lists it with the screens (to revoke it) but not as a screen


def auth_headers(token: str | None) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"} if token else {}


def needs_pairing(status: Any) -> bool:
    """From GET /api/auth/status: True when Moonlight requires pairing and this client isn't authorised.

    `None` (a Moonlight without /api/auth/status, i.e. from before pairing existed) means no pairing.
    """
    if not isinstance(status, dict):
        return False
    return bool(status.get("required")) and not status.get("authorised")


def parse_pair_start(raw: Any) -> tuple[str, str]:
    """POST /api/pair/start -> (pair_id, code)."""
    if not isinstance(raw, dict) or not raw.get("pair_id") or not raw.get("code"):
        raise ValueError("Unexpected reply to /api/pair/start")
    return str(raw["pair_id"]), str(raw["code"])


def parse_pair_poll(raw: Any) -> tuple[str, str | None]:
    """GET /api/pair/{id} -> ("approved", token) | ("pending", None) | ("expired", None)."""
    if not isinstance(raw, dict):
        raise ValueError("Unexpected reply to /api/pair/{id}")
    status = raw.get("status")
    if status == "approved":
        token = raw.get("token")
        if not isinstance(token, str) or not token:
            raise ValueError("Pairing approved but no token was returned")
        return "approved", token
    if status == "pending":
        return "pending", None
    return "expired", None


def format_code(code: str) -> str:
    """"123456" -> "123 456", easier to read off the dialog."""
    return f"{code[:3]} {code[3:]}" if len(code) == 6 else code


# ---------------------------------------------------------------- lookups (services)

def _norm(s: str) -> str:
    return " ".join(s.casefold().split())


def _strip_emoji(s: str) -> str:
    return "".join(ch for ch in s if ch.isalnum() or ch.isspace() or ch in "'&-").strip()


def resolve_person(people: list[dict] | tuple[Person, ...], ref: str) -> Any:
    """Find a person by id or (case-insensitive) name. Raises LookupError."""
    ref_n = _norm(str(ref))
    get = (lambda p, k: p[k]) if people and isinstance(people[0], dict) else getattr
    for p in people:
        if get(p, "id") == ref:
            return p
    matches = [p for p in people if _norm(get(p, "name")) == ref_n]
    if not matches:
        matches = [p for p in people if _norm((get(p, "name").split() or [""])[0]) == ref_n] if ref_n else []
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise LookupError(f"More than one person called {ref!r}; use the person id")
    raise LookupError(f"No person called {ref!r}")


def resolve_chore(chores: list[dict], person_id: str, ref: str) -> dict:
    """Find a chore (from GET /api/chores?date=) for a person by id or title (emoji and case ignored)."""
    mine = [c for c in chores if c.get("person_id") == person_id]
    for c in chores:
        if c.get("id") == ref:
            if c.get("person_id") != person_id:
                raise LookupError("That chore belongs to someone else")
            return c
    ref_n = _norm(_strip_emoji(str(ref)))
    matches = [c for c in mine if _norm(_strip_emoji(c.get("title", ""))) == ref_n]
    if not matches:
        matches = [c for c in mine if ref_n and ref_n in _norm(c.get("title", ""))]
    if not matches:
        raise LookupError(f"No chore {ref!r} due for that person on that day")
    # Same title twice (e.g. "Brush teeth" morning and evening): tick off the next one not yet done.
    return next((c for c in matches if not c.get("completed")), matches[0])


def open_once_chore(chores: list[dict], person_id: str, title: str) -> dict | None:
    """An unfinished one-off chore with this title (emoji and case ignored) for the person, from
    GET /api/chores?date=. moonlight.add_chore reuses it, so an automation that fires twice adds one chore."""
    t = _norm(_strip_emoji(title))
    return next((c for c in chores if c.get("person_id") == person_id and not c.get("completed")
                 and (c.get("schedule") or {}).get("type") == "once"
                 and _norm(_strip_emoji(c.get("title", ""))) == t), None)


def resolve_list(lists: list[dict] | tuple[TodoList, ...], ref: str) -> Any:
    """Find a list by id or name; emoji and case are ignored ("groceries" matches "🛒 Groceries")."""
    get = (lambda x, k: x[k]) if lists and isinstance(lists[0], dict) else getattr
    for lst in lists:
        if get(lst, "id") == ref:
            return lst
    ref_n = _norm(_strip_emoji(str(ref)))
    matches = [lst for lst in lists if _norm(_strip_emoji(get(lst, "name"))) == ref_n]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise LookupError(f"More than one list called {ref!r}")
    raise LookupError(f"No list called {ref!r}")


# ---------------------------------------------------------------- sensors

def dinner_state(summary: Summary) -> str:
    return summary.dinner.title if summary.dinner else NOTHING_PLANNED


def event_attributes(summary: Summary, ev: Event | None) -> dict[str, Any]:
    if ev is None:
        return {}
    return {
        "start": ev.start.isoformat(timespec="minutes"),
        "end": ev.end.isoformat(timespec="minutes"),
        "all_day": ev.all_day,
        "people": summary.names(ev.person_ids),
        "location": ev.location,
    }


def chores_attributes(p: Person) -> dict[str, Any]:
    return {"remaining": p.remaining, "total": len(p.chores), "done": p.chores_done}


# ---------------------------------------------------------------- calendar

def event_times(ev: Event, tz: tzinfo) -> tuple[date, date] | tuple[datetime, datetime]:
    """HA wants dates (end exclusive) for all-day events and aware datetimes otherwise."""
    if ev.all_day:
        start = ev.start.date()
        end = ev.end.date() if ev.end.time() == time(0) else ev.end.date() + timedelta(days=1)
        return start, max(end, start + timedelta(days=1))
    return ev.start.replace(tzinfo=tz), ev.end.replace(tzinfo=tz)


def query_range(start: datetime, end: datetime, tz: tzinfo) -> tuple[str, str]:
    """Moonlight's /api/events takes local dates [start, end) — widen an aware datetime window to cover it."""
    s = start.astimezone(tz).date()
    e_local = end.astimezone(tz)
    e = e_local.date() if e_local.time() == time(0) else e_local.date() + timedelta(days=1)
    return s.isoformat(), max(e, s + timedelta(days=1)).isoformat()


def events_for_person(raw: list[dict], person_id: str | None, start: datetime, end: datetime,
                      tz: tzinfo) -> list[Event]:
    """Occurrences overlapping the aware window [start, end), optionally only one person's."""
    out = []
    for r in raw:
        ev = parse_event(r)
        if person_id is not None and person_id not in ev.person_ids:
            continue
        s, e = ev.start.replace(tzinfo=tz), ev.end.replace(tzinfo=tz)
        if s < end and e > start:
            out.append(ev)
    return out


# ---------------------------------------------------------------- todo

def item_patch(current: Item, title: str | None, completed: bool, due: date | datetime | None,
               supports_due: bool = True) -> dict[str, Any]:
    """The PATCH /api/items body that turns `current` into the item HA asked for (only changed fields)."""
    patch: dict[str, Any] = {}
    if title is not None and title.strip() and title != current.title:
        patch["title"] = title.strip()
    if completed != current.done:
        patch["done"] = completed
    if supports_due:
        new_due = due.date() if isinstance(due, datetime) else due
        if new_due != current.due:
            patch["due"] = new_due.isoformat() if new_due else None
    return patch


def due_param(due: date | datetime | None) -> str | None:
    if due is None:
        return None
    return (due.date() if isinstance(due, datetime) else due).isoformat()
