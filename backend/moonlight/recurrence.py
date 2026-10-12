"""Server-side expansion of repeating events and chore schedules.

repeat = None | {freq: daily|weekly|monthly, interval: int>=1, byday: [MO..SU] (weekly only), until: date|None}

* daily:   every `interval` days from the start date.
* weekly:  on the `byday` weekdays (default: the start's weekday) in weeks that are a
           multiple of `interval` weeks from the start week (weeks begin Monday).
* monthly: same day-of-month every `interval` months; months without that day are skipped.
* until:   inclusive last date an occurrence may *start* on.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Callable, Iterator

WEEKDAYS = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]
FREQS = ("daily", "weekly", "monthly")


def parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def fmt_dt(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M")


def normalize_repeat(rep: dict | None) -> dict | None:
    """Validate and normalise a repeat rule. Raises ValueError on bad input."""
    if rep is None:
        return None
    if not isinstance(rep, dict):
        raise ValueError("repeat must be an object or null")
    freq = rep.get("freq")
    if freq not in FREQS:
        raise ValueError("repeat.freq must be daily, weekly or monthly")
    interval = rep.get("interval", 1)
    if interval is None:
        interval = 1
    if isinstance(interval, bool) or not isinstance(interval, int) or interval < 1:
        raise ValueError("repeat.interval must be an integer >= 1")
    until = rep.get("until")
    if until is not None:
        date.fromisoformat(until)  # raises ValueError
    out: dict = {"freq": freq, "interval": interval, "until": until}
    if rep.get("skip_holidays"):
        if not isinstance(rep["skip_holidays"], bool):
            raise ValueError("repeat.skip_holidays must be true or false")
        out["skip_holidays"] = True
    byday = rep.get("byday")
    if freq == "weekly" and byday:
        if not isinstance(byday, list) or any(d not in WEEKDAYS for d in byday):
            raise ValueError("repeat.byday must be a list of MO..SU")
        out["byday"] = sorted(set(byday), key=WEEKDAYS.index)
    return out


def occurrence_dates(start: date, rep: dict, lo: date, hi: date) -> Iterator[date]:
    """Dates (inclusive window lo..hi) on which a repeating series has an occurrence start."""
    interval = max(1, int(rep.get("interval") or 1))
    if rep.get("until"):
        hi = min(hi, date.fromisoformat(rep["until"]))
    lo = max(lo, start)
    if lo > hi:
        return
    freq = rep["freq"]
    if freq == "daily":
        offset = (lo - start).days
        k = -(-offset // interval)  # ceil
        d = start + timedelta(days=k * interval)
        while d <= hi:
            yield d
            d += timedelta(days=interval)
    elif freq == "weekly":
        days = {WEEKDAYS.index(x) for x in (rep.get("byday") or [])} or {start.weekday()}
        start_week = start - timedelta(days=start.weekday())
        d = lo
        while d <= hi:
            week = d - timedelta(days=d.weekday())
            if d.weekday() in days and ((week - start_week).days // 7) % interval == 0:
                yield d
            d += timedelta(days=1)
    elif freq == "monthly":
        m0 = start.year * 12 + start.month - 1
        m = lo.year * 12 + lo.month - 1
        m_end = hi.year * 12 + hi.month - 1
        while m <= m_end:
            if (m - m0) % interval == 0:
                try:
                    d = date(m // 12, m % 12 + 1, start.day)
                except ValueError:
                    d = None
                if d is not None and lo <= d <= hi:
                    yield d
            m += 1


def expand_event(ev: dict, range_start: datetime, range_end: datetime,
                 is_holiday: Callable[[date], bool] | None = None) -> list[dict]:
    """Occurrences of `ev` overlapping [range_start, range_end). A series with `skip_holidays` leaves out the
    days `is_holiday` names."""
    start = parse_dt(ev["start"])
    end = parse_dt(ev["end"])
    duration = end - start
    if duration < timedelta(0):
        duration = timedelta(0)

    def overlaps(s: datetime, e: datetime) -> bool:
        if s >= range_end:
            return False
        return e > range_start or (s == e and s >= range_start)

    def make(s: datetime, recurring: bool) -> dict:
        occ = dict(ev)
        occ["start"] = fmt_dt(s)
        occ["end"] = fmt_dt(s + duration)
        occ["occurrence_id"] = f"{ev['id']}@{s.date().isoformat()}"
        occ["recurring"] = recurring
        return occ

    rep = ev.get("repeat")
    if not rep:
        return [make(start, False)] if overlaps(start, start + duration) else []

    lo = range_start.date() - timedelta(days=duration.days + 1)
    hi = range_end.date()
    out = []
    skip = is_holiday if (is_holiday and rep.get("skip_holidays")) else None
    for d in occurrence_dates(start.date(), rep, lo, hi):
        if skip and skip(d):
            continue
        s = datetime.combine(d, start.time())
        if overlaps(s, s + duration):
            out.append(make(s, True))
    return out


# ---------------------------------------------------------------- chores

def chore_due(schedule: dict, day: date, is_holiday: Callable[[date], bool] | None = None) -> bool:
    if schedule.get("skip_holidays") and is_holiday and is_holiday(day):
        return False
    t = schedule.get("type")
    if t == "daily":
        return True
    if t == "weekly":
        return WEEKDAYS[day.weekday()] in (schedule.get("days") or [])
    if t == "once":
        return schedule.get("date") == day.isoformat()
    return False


def normalize_schedule(sch: dict) -> dict:
    if not isinstance(sch, dict):
        raise ValueError("schedule must be an object")
    t = sch.get("type")
    skip = sch.get("skip_holidays", False)
    if not isinstance(skip, bool):
        raise ValueError("schedule.skip_holidays must be true or false")
    extra = {"skip_holidays": True} if skip and t in ("daily", "weekly") else {}
    if t == "daily":
        return {"type": "daily", **extra}
    if t == "weekly":
        days = sch.get("days") or []
        if not isinstance(days, list) or not days or any(d not in WEEKDAYS for d in days):
            raise ValueError("schedule.days must be a non-empty list of MO..SU")
        return {"type": "weekly", "days": sorted(set(days), key=WEEKDAYS.index), **extra}
    if t == "once":
        d = sch.get("date")
        if not isinstance(d, str):
            raise ValueError("schedule.date required for once")
        date.fromisoformat(d)
        return {"type": "once", "date": d}
    raise ValueError("schedule.type must be daily, weekly or once")


def streak(schedule: dict, day: date, completed: set[str], lookback: int = 60,
           is_holiday: Callable[[date], bool] | None = None) -> int:
    """Consecutive completed due dates walking back from `day`.

    `day` counts only if completed; if it isn't, start from the previous due date.
    Dates that aren't due are skipped. Looks back at most `lookback` days.
    """
    count = 0
    for i in range(lookback + 1):
        d = day - timedelta(days=i)
        if not chore_due(schedule, d, is_holiday):
            continue
        if d.isoformat() in completed:
            count += 1
        elif i == 0:
            continue
        else:
            break
    return count
