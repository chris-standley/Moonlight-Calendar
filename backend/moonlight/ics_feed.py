"""Read-only calendar subscriptions from a published ICS link ("Add calendar link").

Typical feeds: an Office 365 / Outlook calendar published with "Can view when I'm busy" (every event
is just "Busy" / "Tentative" / "Away" / "Free"), school term dates, bin days, public holidays.

* An account of kind "ics" holds one read-only calendar. The full URL is a secret (anyone with it can
  read the calendar): it is stored in the account's `password` column, never returned by the API and
  never logged; `server_url` holds a masked form for display.
* Polling (default every 15 min, MOONLIGHT_FEED_SECONDS) uses a conditional GET (If-None-Match /
  If-Modified-Since); a 304, or a body identical to the last one, changes nothing. Errors back off
  exponentially (SyncManager) and are shown on the account like CalDAV errors.
* The feed is split into one cached "resource" per UID (master + RECURRENCE-ID overrides, plus the
  VTIMEZONEs they use), so a change replaces exactly the events that changed and timezone conversion
  and recurrence go through the same path as CalDAV events (caldav_sync.apply_resource /
  expand_custom). Outlook's Windows TZIDs ("GMT Standard Time") are resolved by icalendar, from the
  feed's VTIMEZONE or its built-in Windows -> IANA table.
* Only events touching [today - 60 days, today + 1 year] are kept, to bound the database.
* Free/busy: each event gets a busy status (busy / tentative / away / elsewhere / free) from
  X-MICROSOFT-CDO-BUSYSTATUS, a placeholder summary, STATUS or TRANSP. A calendar whose every summary
  is such a placeholder shows its events as busy blocks automatically (calendars.busy_auto); the
  household can force it on or off (calendars.busy_blocks).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import httpx
import icalendar
import recurring_ical_events

from . import caldav_sync, db
from .freebusy import is_placeholder

log = logging.getLogger("moonlight.feeds")
logging.getLogger("httpx").setLevel(logging.WARNING)  # httpx logs full request URLs at INFO

FEED_CALENDAR_URL = "feed"  # calendars.url of a feed's single calendar
PAST_DAYS = 60
FUTURE_DAYS = 366
MAX_BYTES = 25 * 1024 * 1024
TIMEOUT = 30.0
USER_AGENT = "Moonlight family calendar (ICS subscription)"

# Tests swap in an httpx.MockTransport.
transport: httpx.BaseTransport | None = None


def today(tz: ZoneInfo) -> date:
    """The household's today (tests pin it)."""
    return datetime.now(tz).date()


def feed_interval() -> float:
    try:
        return max(30.0, float(os.environ.get("MOONLIGHT_FEED_SECONDS", "900")))
    except ValueError:
        return 900.0


class FeedError(caldav_sync.SyncError):
    """The link couldn't be fetched or isn't a calendar (HTTP 502 to clients when testing a link)."""


# ---------------------------------------------------------------- URL handling

def normalize_url(raw: str) -> str:
    """webcal:// -> https://; anything that isn't http(s) with a host is rejected (ValueError)."""
    url = (raw or "").strip()
    low = url.lower()
    for prefix in ("webcals://", "webcal://"):
        if low.startswith(prefix):
            url = "https://" + url[len(prefix):]
            break
    p = urlparse(url)
    if p.scheme.lower() not in ("http", "https") or not p.hostname:
        raise ValueError("Paste a calendar link starting with https:// or webcal://")
    return url


def mask_url(url: str) -> str:
    """Host plus the last path segment, e.g. "outlook.office365.com/…/calendar.ics" (no tokens)."""
    p = urlparse(url)
    host = p.hostname or ""
    last = p.path.rstrip("/").rsplit("/", 1)[-1] if p.path.strip("/") else ""
    if len(last) > 24 or re.search(r"[0-9a-fA-F]{16,}", last):
        last = last[:4] + "…" if last else ""
    if not last:
        return f"{host}/…" if (p.path.strip("/") or p.query) else host
    middle = "/…/" if p.path.strip("/").count("/") else "/"
    return f"{host}{middle}{last}" + ("?…" if p.query else "")


# ---------------------------------------------------------------- fetching

@dataclass
class Fetched:
    not_modified: bool
    text: str = ""
    etag: str | None = None
    last_modified: str | None = None


def fetch(url: str, etag: str | None = None, last_modified: str | None = None) -> Fetched:
    """Blocking conditional GET. Raises FeedError with a message that never includes the URL."""
    host = urlparse(url).hostname or "the server"
    headers = {"User-Agent": USER_AGENT, "Accept": "text/calendar, text/plain;q=0.9, */*;q=0.5"}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified
    try:
        with httpx.Client(transport=transport, timeout=TIMEOUT, follow_redirects=True, max_redirects=5) as client:
            with client.stream("GET", url, headers=headers) as r:
                if r.status_code == 304:
                    return Fetched(True, etag=etag, last_modified=last_modified)
                if r.status_code in (401, 403):
                    raise FeedError(f"{host} refused the calendar link (HTTP {r.status_code}). It may have been "
                                    "unpublished or your workplace may block it; publish it again and paste the new link.")
                if r.status_code in (404, 410):
                    raise FeedError(f"The calendar link no longer works (HTTP {r.status_code} from {host}). "
                                    "It may have been unpublished; paste a new link.")
                if r.status_code >= 400:
                    raise FeedError(f"{host} replied HTTP {r.status_code} to the calendar link.")
                chunks, size = [], 0
                for chunk in r.iter_bytes():
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise FeedError("That calendar is too large (over 25 MB).")
                    chunks.append(chunk)
                body = b"".join(chunks)
                new_etag, new_lm = r.headers.get("ETag"), r.headers.get("Last-Modified")
                encoding = r.encoding or "utf-8"
    except FeedError:
        raise
    except httpx.TooManyRedirects:
        raise FeedError(f"{host} redirected too many times.")
    except httpx.HTTPError as e:
        raise FeedError(f"Couldn't reach {host}: {e.__class__.__name__}")
    try:
        text = body.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = body.decode(encoding if encoding.lower() not in ("utf-8", "utf8") else "latin-1", errors="replace")
    if "BEGIN:VCALENDAR" not in text[:4096].upper():
        raise FeedError("That link didn't return a calendar (.ics) file. Check you copied the ICS link, "
                        "not the HTML one.")
    return Fetched(False, text, new_etag, new_lm)


# ---------------------------------------------------------------- parsing

def _parse_calendars(text: str) -> list:
    try:
        return [icalendar.Calendar.from_ical(text)]
    except ValueError:
        return list(icalendar.Calendar.from_ical(text, multiple=True))


def _to_standard(cal):
    """Google-style feeds: floating times + X-WR-TIMEZONE -> real TZIDs (as recurring-ical-events does)."""
    if cal.get("X-WR-TIMEZONE") is None:
        return cal
    try:
        import x_wr_timezone
        return x_wr_timezone.to_standard(cal)
    except Exception:
        log.warning("Couldn't apply X-WR-TIMEZONE; using times as given")
        return cal


_TZID_RE = re.compile(r";TZID=(?:\"([^\"]+)\"|([^;:]+))")


def _bounds(comp) -> tuple[date | datetime, date | datetime]:
    ds = comp.decoded("DTSTART")
    if "DTEND" in comp:
        de = comp.decoded("DTEND")
    elif "DURATION" in comp:
        de = ds + comp.decoded("DURATION")
    else:
        de = ds + timedelta(days=1) if not isinstance(ds, datetime) else ds
    return ds, de


def _as_local(v: date | datetime, tz: ZoneInfo) -> datetime:
    return caldav_sync.to_local(v, tz)


@dataclass
class Parsed:
    name: str
    resources: dict[str, tuple[str, str]]  # href -> (etag, ics)
    event_count: int                       # in-window resources (series count once)
    busy_only: bool                        # every in-window summary is a free/busy placeholder


def _in_window(group_cal, events: list, lo: datetime, hi: datetime, tz: ZoneInfo) -> bool:
    master = next((e for e in events if e.get("RECURRENCE-ID") is None), None)
    recurring = master is not None and ("RRULE" in master or "RDATE" in master)
    if not recurring:
        for e in events:
            try:
                ds, de = _bounds(e)
            except Exception:
                continue
            s, en = _as_local(ds, tz), _as_local(de, tz)
            if s < hi and en >= lo:
                return True
        return False
    try:
        for occ in recurring_ical_events.of(group_cal, components=["VEVENT"]).after(lo.replace(tzinfo=tz)):
            ds, _ = _bounds(occ)
            return _as_local(ds, tz) < hi
    except Exception:
        return True  # can't tell: keep it, expansion at query time copes or skips
    return False


def parse_feed(text: str, tz: ZoneInfo, on: date | None = None) -> Parsed:
    """Split a feed into per-UID resources inside the window. Raises FeedError if unreadable."""
    try:
        cals = [_to_standard(c) for c in _parse_calendars(text)]
    except Exception as e:
        raise FeedError(f"Couldn't read that calendar file ({e.__class__.__name__}).")
    on = on or today(tz)
    lo = datetime.combine(on - timedelta(days=PAST_DAYS), time(0))
    hi = datetime.combine(on + timedelta(days=FUTURE_DAYS), time(0))
    name = ""
    zones: dict[str, object] = {}
    groups: dict[str, list] = {}
    for cal in cals:
        name = name or str(cal.get("X-WR-CALNAME", "")).strip()
        for tzc in cal.walk("VTIMEZONE"):
            zones.setdefault(str(tzc.get("TZID", "")), tzc)
        for ev in cal.walk("VEVENT"):
            if "DTSTART" not in ev:
                continue
            uid = str(ev.get("UID", "")).strip()
            if not uid:
                seed = f"{ev.get('SUMMARY', '')}|{ev.get('DTSTART').to_ical().decode()}"
                uid = "nouid-" + hashlib.sha1(seed.encode()).hexdigest()[:16]
                ev["UID"] = uid
            groups.setdefault(uid, []).append(ev)

    resources: dict[str, tuple[str, str]] = {}
    placeholders = total = 0
    for uid, evs in groups.items():
        masters = [e for e in evs if e.get("RECURRENCE-ID") is None]
        overrides = [e for e in evs if e.get("RECURRENCE-ID") is not None]
        # Some feeds reuse a UID for unrelated one-off events: keep each master as its own resource.
        sets = [[m] + (overrides if i == 0 else []) for i, m in enumerate(masters)] or [overrides]
        for i, members in enumerate(sets):
            members = [m for m in members if str(m.get("STATUS", "")).strip().upper() != "CANCELLED"]
            if not members:
                continue
            out = icalendar.Calendar()
            out.add("prodid", "-//Moonlight//ICS subscription//EN")
            out.add("version", "2.0")
            body = "".join(m.to_ical().decode("utf-8", "replace") for m in members).replace("\r\n ", "")
            for tzid in dict.fromkeys(m.group(1) or m.group(2) for m in _TZID_RE.finditer(body)):
                if tzid in zones:
                    out.add_component(zones[tzid])
            for m in members:
                out.add_component(m)
            try:
                if not _in_window(out, members, lo, hi, tz):
                    continue
            except Exception:
                log.debug("Window check failed for %s; keeping it", uid)
            ics = out.to_ical().decode("utf-8", "replace")
            stable = "\n".join(ln for ln in ics.splitlines() if not ln.startswith("DTSTAMP"))
            href = f"uid:{uid}" + (f"#{i}" if i else "")
            resources[href] = (hashlib.sha1(stable.encode()).hexdigest(), ics)
            total += 1
            placeholders += all(is_placeholder(m) for m in members)
    return Parsed(name, resources, total, total > 0 and placeholders == total)


# ---------------------------------------------------------------- storing

def _validators(cal_row: dict) -> dict:
    try:
        v = json.loads(cal_row.get("ctag") or "{}")
        return v if isinstance(v, dict) else {}
    except ValueError:
        return {}


def store(calendar_id: str, fetched: Fetched, tz: ZoneInfo | None = None) -> bool:
    """Apply a fetched feed to its calendar. Returns True if events changed."""
    tz = tz or caldav_sync.household_tz()
    with db.connect() as c:
        cal = db.row(c, "SELECT * FROM calendars WHERE id = ?", (calendar_id,))
    if not cal:
        return False
    old = _validators(cal)
    if fetched.not_modified:
        return False
    sha = hashlib.sha1(fetched.text.encode()).hexdigest()
    validators = {"etag": fetched.etag, "last_modified": fetched.last_modified, "sha": sha}
    if sha == old.get("sha"):
        with db.connect() as c:
            c.execute("UPDATE calendars SET ctag = ? WHERE id = ?", (json.dumps(validators), calendar_id))
        return False
    parsed = parse_feed(fetched.text, tz)
    changed = False
    with db.connect() as c:
        local = {r["href"]: r["etag"] for r in db.rows(
            c, "SELECT href, etag FROM events WHERE calendar_id = ?", (calendar_id,))}
        for href in local:
            if href not in parsed.resources:
                c.execute("DELETE FROM events WHERE calendar_id = ? AND href = ?", (calendar_id, href))
                changed = True
        for href, (etag, ics) in parsed.resources.items():
            if local.get(href) != etag:
                caldav_sync.apply_resource(c, calendar_id, href, etag, ics, tz)
                changed = True
        c.execute("UPDATE calendars SET ctag = ?, busy_auto = ? WHERE id = ?",
                  (json.dumps(validators), int(parsed.busy_only), calendar_id))
    return changed


def feed_calendar(c, account_id: str) -> dict | None:
    return db.row(c, "SELECT * FROM calendars WHERE account_id = ?", (account_id,))


def sync_feed(acct: dict, force: bool = False) -> bool:
    """Blocking poll of one feed account (called by caldav_sync.sync_account under its lock)."""
    with db.connect() as c:
        cal = feed_calendar(c, acct["id"])
    if not cal:
        return False
    v = {} if force else _validators(cal)
    fetched = fetch(acct["password"], v.get("etag"), v.get("last_modified"))
    if force and not fetched.not_modified:
        with db.connect() as c:  # forget the body hash so the feed is re-applied
            c.execute("UPDATE calendars SET ctag = NULL WHERE id = ?", (cal["id"],))
    return store(cal["id"], fetched)


def preview(url: str) -> dict:
    """Test a link: fetch and count what would be shown. Raises ValueError / FeedError."""
    url = normalize_url(url)
    fetched = fetch(url)
    parsed = parse_feed(fetched.text, caldav_sync.household_tz())
    return {"event_count": parsed.event_count, "name": parsed.name, "busy_only": parsed.busy_only,
            "masked_url": mask_url(url), "fetched": fetched, "url": url}
