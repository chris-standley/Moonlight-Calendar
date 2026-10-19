"""Shared bits for routes: WebSocket hub, error helpers, input validation."""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

from fastapi import HTTPException, WebSocket

from . import db

log = logging.getLogger("moonlight")

TOPICS = {"people", "events", "chores", "points", "rewards", "lists", "meals", "recipes", "settings", "photos", "displays", "accounts", "media", "security", "security_alert"}


class Hub:
    """Connected WebSocket clients; every mutation broadcasts {"type":"changed","topic":...}."""

    def __init__(self) -> None:
        self.sockets: set[WebSocket] = set()

    async def broadcast(self, *topics: str) -> None:
        for topic in topics:
            msg = {"type": "changed", "topic": topic}
            for ws in list(self.sockets):
                try:
                    await ws.send_json(msg)
                except Exception:  # client went away mid-send
                    self.sockets.discard(ws)


hub = Hub()


def bad(detail: str) -> HTTPException:
    return HTTPException(status_code=400, detail=detail)


def not_found(what: str = "Not found") -> HTTPException:
    return HTTPException(status_code=404, detail=what)


def forbidden(detail: str = "Wrong PIN") -> HTTPException:
    return HTTPException(status_code=403, detail=detail)


def require_pin(c, pin: Any) -> None:
    from . import security  # local import: security imports db lazily too

    if not security.check_pin(c, pin):
        raise forbidden()


def body_dict(body: Any) -> dict:
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise bad("Body must be a JSON object")
    return body


def req_str(body: dict, key: str, allow_empty: bool = False) -> str:
    v = body.get(key)
    if not isinstance(v, str) or (not allow_empty and not v.strip()):
        raise bad(f"{key} is required")
    return v.strip() if not allow_empty else v


def opt_str(body: dict, key: str, default: str = "") -> str:
    v = body.get(key, default)
    if v is None:
        return default
    if not isinstance(v, str):
        raise bad(f"{key} must be a string")
    return v


def as_int(value: Any, key: str) -> int:
    if isinstance(value, bool):
        raise bad(f"{key} must be an integer")
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if not isinstance(value, int):
        raise bad(f"{key} must be an integer")
    return value


def as_date(value: Any, key: str) -> str:
    try:
        return date.fromisoformat(str(value)).isoformat()
    except (TypeError, ValueError):
        raise bad(f"{key} must be a YYYY-MM-DD date")


def opt_date(value: Any, key: str) -> str | None:
    return None if value in (None, "") else as_date(value, key)


def as_datetime(value: Any, key: str) -> str:
    try:
        return datetime.fromisoformat(str(value)).strftime("%Y-%m-%dT%H:%M")
    except (TypeError, ValueError):
        raise bad(f"{key} must be an ISO datetime (YYYY-MM-DDTHH:MM)")


# Screen styles: a big wall screen, a small touch screen, a phone. "hallway" and "kitchen" are their old names.
LAYOUTS = ("large", "compact", "phone")


def layout_name(value: Any, key: str = "layout") -> str:
    return choice(db.OLD_LAYOUTS.get(value, value) if isinstance(value, str) else value, key, LAYOUTS)


def choice(value: Any, key: str, options: tuple[str, ...]) -> str:
    if value not in options:
        raise bad(f"{key} must be one of: {', '.join(options)}")
    return value


def person_exists(c, person_id: str) -> bool:
    return c.execute("SELECT 1 FROM people WHERE id = ?", (person_id,)).fetchone() is not None


def next_sort(c, table: str, where: str = "", args: tuple = ()) -> int:
    sql = f"SELECT COALESCE(MAX(sort), -1) + 1 FROM {table}"
    if where:
        sql += f" WHERE {where}"
    return c.execute(sql, args).fetchone()[0]
