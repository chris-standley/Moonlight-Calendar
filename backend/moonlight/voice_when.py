"""Amounts of time, days and times of day as people say them to Assist.

    duration_of("an hour and a half") -> 5400
    when_of("dentist tomorrow at half past 3", now) -> When(day=<tomorrow>, start=(15, 30), rest="dentist")

Times without am/pm read the way a family calendar means them: 1 to 6 o'clock is the afternoon, 7 to 11 the
morning (the evening after "tonight" or "in the evening").
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

# ---------------------------------------------------------------- amounts of time ("1 hour and 15 minutes")

UNITS = {"hour": 3600, "hr": 3600, "minute": 60, "min": 60, "second": 1, "sec": 1}
WORDS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "ninety": 90, "couple of": 2, "few": 3,
}
NUM = r"(\d+(?:\.\d+)?|" + "|".join(sorted((re.escape(w) for w in WORDS), key=len, reverse=True)) + r")"
# "twenty five", "twenty-five"
COMPOUND = r"((?:twenty|thirty|forty|fifty)[ -](?:one|two|three|four|five|six|seven|eight|nine))"
AMOUNT = re.compile(rf"\b(?:{COMPOUND}|{NUM})(?:\s+and\s+a\s+half)?\s*[- ]?\s*(hours?|hrs?|minutes?|mins?|seconds?|secs?)\b"
                    r"(\s+and\s+a\s+half)?", re.I)
HALF_HOUR = re.compile(r"(?<!and a )\bhalf\s+(?:an?\s+)?hour\b", re.I)


def number(word: str) -> float:
    word = word.lower().replace("-", " ")
    if word in WORDS:
        return WORDS[word]
    if " " in word:
        tens, ones = word.split(" ", 1)
        return WORDS.get(tens, 0) + WORDS.get(ones, 0)
    return float(word)


def duration_of(text: str) -> int:
    """Seconds said in `text` ("1 hour and 15 minutes", "an hour and a half", "half an hour"), 0 if none."""
    total = 1800.0 * len(HALF_HOUR.findall(text))
    for m in AMOUNT.finditer(HALF_HOUR.sub(" ", text)):
        n = number(m.group(1) or m.group(2))
        unit = UNITS[re.sub(r"s$", "", m.group(3).lower())]
        half = bool(m.group(4)) or "and a half" in m.group(0).lower()
        total += (n + (0.5 if half else 0)) * unit
    return int(round(total))


# ---------------------------------------------------------------- days and times ("on Friday at half past 5")

DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
MONTHS = {m: i + 1 for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                          "september", "october", "november", "december"])}
MONTHS.update({m[:3]: n for m, n in list(MONTHS.items())}, sept=9)
ORDINALS = {w: i + 1 for i, w in enumerate(
    "first second third fourth fifth sixth seventh eighth ninth tenth eleventh twelfth thirteenth fourteenth "
    "fifteenth sixteenth seventeenth eighteenth nineteenth twentieth".split())}
ORDINALS.update({f"twenty {w}": 20 + n for w, n in list(ORDINALS.items()) if n < 10})
ORDINALS.update(thirtieth=30, **{"thirty first": 31})
HOURS = {w: i + 1 for i, w in enumerate("one two three four five six seven eight nine ten eleven twelve".split())}
PAST = {"five": 5, "ten": 10, "quarter": 15, "twenty": 20, "twenty five": 25, "half": 30}
MINUTE_WORDS = {"o'clock": 0, "oh five": 5, "ten": 10, "fifteen": 15, "twenty": 20, "twenty five": 25, "thirty": 30,
                "thirty five": 35, "forty": 40, "forty five": 45, "fifty": 50, "fifty five": 55}


def _alt(words) -> str:
    return "|".join(sorted((re.escape(w).replace(r"\ ", r"[ -]") for w in words), key=len, reverse=True))


H = rf"(?:\d{{1,2}}|{_alt(HOURS)})"
AMPM = r"(?:a\.?\s?m\.?|p\.?\s?m\.?)(?![a-z])"
TIME = (rf"(?:(?:{_alt(PAST)})\s+(?:past|to)\s+{H}|noon|midday|midnight|"
        rf"{H}(?:[:.]\d{{2}}|\s+(?:{_alt(MINUTE_WORDS)}))?)(?:\s*{AMPM})?")
ORD = rf"(?:\d{{1,2}}(?:st|nd|rd|th)?|{_alt(ORDINALS)})"
ORD_SAID = rf"(?:\d{{1,2}}(?:st|nd|rd|th)|{_alt(ORDINALS)})"  # "the 5th", not "the 5"
MONTH = rf"(?:{_alt(MONTHS)})"

PATTERNS = [  # (kind, regex): each found part is taken out of the text, so what's left is the event's name
    ("range", re.compile(rf"\b(?:from|between)\s+({TIME})\s*(?:to|till|until|and|-)\s*({TIME})", re.I)),
    ("at", re.compile(rf"\bat\s+({TIME})(?!\s*(?:hours?|minutes?|mins?|days?|weeks?))", re.I)),
    ("bare", re.compile(rf"\b({H}(?:[:.]\d{{2}})?\s*{AMPM}|{H}\s+o'clock|noon|midday)", re.I)),
    ("for", re.compile(r"\bfor\s+((?:an?|half\s+an|\d+|one|two|three|four|five|six|ninety|forty[ -]five|thirty)"
                       r"(?:\s+and\s+a\s+half)?\s+(?:hours?|minutes?|mins?|hrs?)(?:\s+and\s+a\s+half)?"
                       r"(?:\s+and\s+\d+\s+minutes?)?)", re.I)),
    ("after_tomorrow", re.compile(r"\b(?:the\s+)?day\s+after\s+tomorrow\b", re.I)),
    ("tomorrow", re.compile(r"\btomorrow(?:\s+(morning|afternoon|evening|night))?\b", re.I)),
    ("tonight", re.compile(r"\btonight\b", re.I)),
    ("today", re.compile(r"\b(?:today|this\s+(morning|afternoon|evening))\b", re.I)),
    ("part", re.compile(r"\bin\s+the\s+(morning|afternoon|evening)\b", re.I)),
    ("in_days", re.compile(r"\bin\s+(\d+|an?|one|two|three|four|five|six|seven|ten)\s+(days?|weeks?)\b", re.I)),
    ("next_week", re.compile(r"\bnext\s+week\b", re.I)),
    ("weekday", re.compile(rf"\b(?:on\s+)?(?:(this|next|coming)\s+)?({_alt(DAYS)})s?\b", re.I)),
    ("day_month", re.compile(rf"\b(?:on\s+)?(?:the\s+)?({ORD})(?:\s+of)?\s+({MONTH})\b", re.I)),
    ("month_day", re.compile(rf"\b(?:on\s+)?({MONTH})\s+(?:the\s+)?({ORD})\b", re.I)),
    ("the_day", re.compile(rf"\b(?:on\s+)?the\s+({ORD_SAID})\b", re.I)),
]


@dataclass
class When:
    day: date | None = None
    start: tuple[int, int] | None = None  # hour, minute
    end: tuple[int, int] | None = None
    minutes: int | None = None  # how long, when said ("for an hour")
    rest: str = ""  # the text with the day and time taken out


def _ordinal(s: str) -> int:
    s = s.lower().replace("-", " ")
    if s in ORDINALS:
        return ORDINALS[s]
    return int(re.sub(r"\D", "", s))


def _hour(s: str) -> int:
    s = s.lower()
    return HOURS[s] if s in HOURS else int(s)


def time_of(said: str, part: str | None = None, after: tuple[int, int] | None = None) -> tuple[int, int] | None:
    """(hour, minute) of "3", "3pm", "half past 3", "15:30", "quarter to 7", "noon"; None if it isn't a time.
    `part` is the part of the day said with it; `after` a start time this one ends after ("from 3 to 4")."""
    s = re.sub(r"\s+", " ", said.lower().strip())
    m = re.search(AMPM + r"$", s)
    ampm = m.group(0).replace(".", "").replace(" ", "")[0] if m else None
    s = re.sub(AMPM + r"$", "", s).strip()
    if s in ("noon", "midday"):
        return 12, 0
    if s == "midnight":
        return 0, 0
    if m := re.fullmatch(rf"({_alt(PAST)}) (past|to) ({H})", s):
        mins = PAST[m.group(1).replace("-", " ")]
        h = _hour(m.group(3))
        h, minute = (h, mins) if m.group(2) == "past" else (h - 1, 60 - mins)
    elif m := re.fullmatch(rf"({H})(?:[:.](\d{{2}})| ({_alt(MINUTE_WORDS)}))?(?: o'clock)?", s):
        h = _hour(m.group(1))
        minute = int(m.group(2)) if m.group(2) else MINUTE_WORDS[(m.group(3) or "o'clock").replace("-", " ")]
    else:
        return None
    if not (0 <= h <= 23 and 0 <= minute <= 59):
        return None
    if ampm == "p" and h < 12:
        h += 12
    elif ampm == "a" and h == 12:
        h = 0
    elif ampm is None and h <= 12:
        if part in ("afternoon", "evening", "night"):
            h = h + 12 if h < 12 else h
        elif part == "morning":
            h = 0 if h == 12 else h
        elif after is not None:
            if (h, minute) <= after and h < 12:
                h += 12
        elif 1 <= h <= 6:
            h += 12  # "at 3": the afternoon
    return h % 24, minute


def _next_weekday(today: date, wd: int) -> date:
    ahead = (wd - today.weekday()) % 7
    return today + timedelta(days=ahead or 7)


def when_of(text: str, now: datetime) -> When:
    """The day and time said in `text`; `rest` keeps the other words (the event's name, say)."""
    today = now.date()
    out = When()
    part: str | None = None
    found: dict[str, re.Match] = {}
    rest = " " + text + " "
    for kind, rx in PATTERNS:
        m = rx.search(rest)
        if not m:
            continue
        found[kind] = m
        rest = rest[:m.start()] + " " + rest[m.end():]
    for kind in ("tomorrow", "today", "part"):
        if kind in found and found[kind].group(1):
            part = found[kind].group(1).lower()
    if "tonight" in found:
        part = "evening"
    if part == "night":
        part = "evening"
    # The day
    if "after_tomorrow" in found:
        out.day = today + timedelta(days=2)
    elif "tomorrow" in found:
        out.day = today + timedelta(days=1)
    elif "today" in found or "tonight" in found:
        out.day = today
    elif "in_days" in found:
        m = found["in_days"]
        n = int(number(m.group(1)))
        out.day = today + timedelta(days=n * (7 if m.group(2).lower().startswith("week") else 1))
    elif "weekday" in found:
        m = found["weekday"]
        out.day = _next_weekday(today, DAYS.index(m.group(2).lower()))
        if (m.group(1) or "").lower() == "this" and m.group(2).lower() == DAYS[today.weekday()]:
            out.day = today
    elif "next_week" in found:
        out.day = today + timedelta(days=7)
    elif "day_month" in found or "month_day" in found:
        m = found.get("day_month") or found["month_day"]
        d, mon = (m.group(1), m.group(2)) if "day_month" in found else (m.group(2), m.group(1))
        out.day = _in_year(today, MONTHS[mon.lower()], _ordinal(d))
    elif "the_day" in found:
        out.day = _in_month(today, _ordinal(found["the_day"].group(1)))
    # The time
    if "range" in found:
        out.start = time_of(found["range"].group(1), part)
        out.end = time_of(found["range"].group(2), part, out.start) if out.start else None
    elif "at" in found:
        out.start = time_of(found["at"].group(1), part)
    elif "bare" in found:
        out.start = time_of(found["bare"].group(1), part)
    elif part and out.day is not None:
        out.start = {"morning": (9, 0), "afternoon": (14, 0), "evening": (19, 0)}[part]
    if "for" in found:
        out.minutes = duration_of(found["for"].group(1)) // 60 or None
    out.rest = re.sub(r"\s+", " ", rest).strip(" ,.?!")
    return out


def _in_year(today: date, month: int, day: int) -> date | None:
    """That day this year, else next year ("the 3rd of March" said in November)."""
    for year in (today.year, today.year + 1):
        try:
            d = date(year, month, day)
        except ValueError:
            return None
        if d >= today:
            return d
    return None


def _in_month(today: date, day: int) -> date | None:
    """That day this month, else in the next month that has it ("the 31st")."""
    for i in range(3):
        year, month = today.year + (today.month - 1 + i) // 12, (today.month - 1 + i) % 12 + 1
        try:
            d = date(year, month, day)
        except ValueError:
            continue
        if d >= today:
            return d
    return None


def spoken_day(d: date, today: date) -> str:
    if d == today:
        return "today"
    if d == today + timedelta(days=1):
        return "tomorrow"
    if 0 < (d - today).days < 7:
        return "on " + DAYS[d.weekday()].capitalize()
    return f"on {DAYS[d.weekday()].capitalize()} {d.day} {list(MONTHS)[d.month - 1].capitalize()}"


def spoken_time(h: int, m: int) -> str:
    if (h, m) == (12, 0):
        return "midday"
    suffix = "am" if h < 12 else "pm"
    h12 = h % 12 or 12
    return f"{h12}{suffix}" if m == 0 else f"{h12}:{m:02d}{suffix}"
