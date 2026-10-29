"""Reading a photo of a party invitation or an event flier into a draft event, with Claude (the Anthropic API key
saved in Settings › Recipes). One request per photo. The iPhone app reads the words on the phone instead unless
asked to use Claude.

Returns draft fields for the event editor; nothing is saved until the family taps Add."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from .recipe_import import ImportError_, _ask, _images

SCHEMA = {
    "type": "object",
    "properties": {
        "found": {"type": "boolean"},
        "title": {"type": "string"},
        "date": {"type": ["string", "null"], "description": "YYYY-MM-DD"},
        "start_time": {"type": ["string", "null"], "description": "HH:MM, 24-hour"},
        "end_date": {"type": ["string", "null"], "description": "YYYY-MM-DD"},
        "end_time": {"type": ["string", "null"], "description": "HH:MM, 24-hour"},
        "location": {"type": "string"},
        "notes": {"type": "string"},
        "for_people": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["found", "title", "date", "start_time", "end_date", "end_time", "location", "notes", "for_people"],
    "additionalProperties": False,
}

PROMPT = """This photo is an invitation, a flier or a poster for an event. Read it for a family calendar and \
return JSON.

Today is {today}.
- title: short, as the family would write it in their calendar, e.g. "Mia's 7th birthday party", "Christmas \
fair", "Swimming gala". At most 60 characters.
- date: the day it happens. When the year isn't printed, pick the first such date on or after today (a weekday \
printed next to it must match). null if there is no date.
- start_time and end_time: 24-hour HH:MM, null when not printed. "2-4pm" is 14:00 and 16:00.
- end_date: only when it runs over several days, else null.
- location: the venue's name and address as printed, on one line. Empty if none.
- notes: anything else worth keeping, one short line each: RSVP (to whom, how, by when), what to bring or wear, \
the host, a theme, a price. Empty if nothing.
- for_people: who it is addressed to, only from this family: {names}. Empty when it doesn't say.
If this is not about an event at all, set found to false."""

DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIME = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


async def read_invite(api_key: str, model: str, image: tuple[str, bytes], today: date, names: list[str]) -> dict:
    content = _images([image]) + [{"type": "text", "text": PROMPT.format(
        today=f"{today:%A} {today.day} {today:%B %Y}", names=", ".join(names) or "(no names given)")}]
    data = await _ask(api_key, model, content, SCHEMA)
    if not data.get("found"):
        raise ImportError_("Claude couldn't find an event in that photo. Try a clearer photo with the details in view.")
    return draft(data, today)


def _time(v) -> str | None:
    m = TIME.match(str(v or "").strip())
    return f"{int(m[1]):02d}:{m[2]}" if m else None


def _day(v) -> date | None:
    s = str(v or "").strip()
    if not DATE.match(s):
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def draft(data: dict, today: date) -> dict:
    """Claude's answer as event fields. A missing date is today (the family picks it); a missing time is all day;
    a missing end is two hours on (the length of most parties)."""
    day = _day(data.get("date"))
    start_t, end_t = _time(data.get("start_time")), _time(data.get("end_time"))
    last = _day(data.get("end_date"))
    if last and day and last < day:
        last = None
    d = day or today
    if start_t is None:
        all_day = True
        start = f"{d.isoformat()}T00:00"
        end = f"{((last or d) + timedelta(days=1)).isoformat()}T00:00"
    else:
        all_day = False
        s = datetime.fromisoformat(f"{d.isoformat()}T{start_t}")
        e = datetime.fromisoformat(f"{(last or d).isoformat()}T{end_t}") if end_t else None
        if e is None or e <= s:
            e = s + timedelta(hours=2)
        start, end = s.strftime("%Y-%m-%dT%H:%M"), e.strftime("%Y-%m-%dT%H:%M")
    return {
        "title": str(data.get("title") or "").strip()[:120],
        "start": start, "end": end, "all_day": all_day,
        "location": str(data.get("location") or "").strip()[:500],
        "notes": str(data.get("notes") or "").strip()[:4000],
        "for_people": [str(n) for n in data.get("for_people") or [] if isinstance(n, str)],
        "found_date": day is not None,
    }
