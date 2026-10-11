"""iCloud / CalDAV calendar sync.

iCloud (or any CalDAV server) is the master copy. Moonlight keeps a local cache of every VEVENT
resource (raw ICS + ETag) in the `events` table, with `calendar_id` set.

* Polling: one PROPFIND (depth 1) on the account's calendar home returns every calendar and its
  ctag (or sync-token). Only calendars whose ctag changed are listed (href + ETag), and only new or
  changed resources are downloaded (calendar-multiget). Missing hrefs are deleted locally.
* Writes from the touchscreen go to the server first (If-Match / If-None-Match) and are stored
  locally only once the server accepts them. A 412 means a phone changed the event in the meantime:
  we re-fetch it and report a conflict (HTTP 409).
* Recurrence: simple RRULEs map onto Moonlight's `repeat` model; anything else (COUNT, EXDATE,
  RECURRENCE-ID overrides, BYSETPOS, other timezones...) sets `custom_repeat` and is expanded from
  raw ICS with recurring-ical-events at query time. Times are stored as naive household-local times.
* Credentials live only in the database; the API never returns the password.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import threading
import time as _time
import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from urllib.parse import urljoin, urlparse
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

import caldav
import icalendar
import recurring_ical_events
from caldav.lib import error as dav_error
from lxml import etree

from . import db
from .common import hub
from .freebusy import busy_status
from .recurrence import WEEKDAYS, fmt_dt, normalize_repeat

log = logging.getLogger("moonlight.sync")

ICLOUD_URL = "https://caldav.icloud.com/"
NS = {"d": "DAV:", "c": "urn:ietf:params:xml:ns:caldav", "cs": "http://calendarserver.org/ns/",
      "ic": "http://apple.com/ns/ical/"}
PEOPLE_PROP = "X-MOONLIGHT-PEOPLE"
FAMILY_NAMES = {"family", "home", "household", "everyone", "shared"}
MULTIGET_BATCH = 50


# ---------------------------------------------------------------- errors

class SyncError(Exception):
    """Server unreachable or replied with something unexpected (HTTP 502 to our clients)."""
    status = 502


class AuthFailed(SyncError):
    status = 502


class Forbidden(SyncError):
    status = 403


class Conflict(SyncError):
    status = 409


def auth_message(kind: str) -> str:
    if kind == "icloud":
        return "iCloud did not accept the Apple ID or app-specific password. Reconnect it in Settings > Calendars."
    return "The calendar server did not accept the username or password. Reconnect it in Settings > Calendars."


# ---------------------------------------------------------------- timezone helpers

def tz_or_default(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or db.default_timezone())
    except Exception:
        return ZoneInfo(db.default_timezone())


def household_tz() -> ZoneInfo:
    with db.connect() as c:
        return tz_or_default(db.get_setting(c, "timezone", db.default_timezone()))


def to_local(v: date | datetime, tz: ZoneInfo) -> datetime:
    """date -> midnight; aware datetime -> household-local naive; floating stays as is."""
    if isinstance(v, datetime):
        if v.tzinfo is None:
            return v.replace(second=0, microsecond=0)
        return v.astimezone(tz).replace(tzinfo=None, second=0, microsecond=0)
    return datetime.combine(v, time(0))


def _zone_key(dt: datetime) -> str | None:
    tzinfo = dt.tzinfo
    return getattr(tzinfo, "key", None) or getattr(tzinfo, "zone", None)


# ---------------------------------------------------------------- CalDAV protocol

PROPFIND_CALENDARS = """<?xml version="1.0" encoding="utf-8"?>
<d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav" xmlns:cs="http://calendarserver.org/ns/" xmlns:ic="http://apple.com/ns/ical/">
  <d:prop><d:displayname/><d:resourcetype/><ic:calendar-color/><c:supported-calendar-component-set/>
  <d:current-user-privilege-set/><cs:getctag/><d:sync-token/></d:prop>
</d:propfind>"""

REPORT_ETAGS = """<?xml version="1.0" encoding="utf-8"?>
<c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">
  <d:prop><d:getetag/></d:prop>
  <c:filter><c:comp-filter name="VCALENDAR"><c:comp-filter name="VEVENT"/></c:comp-filter></c:filter>
</c:calendar-query>"""

REPORT_MULTIGET = """<?xml version="1.0" encoding="utf-8"?>
<c:calendar-multiget xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">
  <d:prop><d:getetag/><c:calendar-data/></d:prop>
  {hrefs}
</c:calendar-multiget>"""


def _norm_color(value: str | None) -> str | None:
    if not value:
        return None
    m = re.match(r"^\s*#?([0-9a-fA-F]{6})", value)
    return f"#{m.group(1).upper()}" if m else None


class Remote:
    """Thin blocking CalDAV client (caldav.DAVClient handles auth negotiation and redirects)."""

    def __init__(self, server_url: str, username: str, password: str, timeout: int = 30):
        self.server_url = server_url
        self.client = caldav.DAVClient(url=server_url, username=username, password=password,
                                       timeout=timeout, enable_rfc6764=False)

    def _call(self, fn, *args):
        try:
            return fn(*args)
        except dav_error.AuthorizationError as e:
            if "forbidden" in str(getattr(e, "reason", "")).lower():
                raise Forbidden("The calendar server refused this change (no permission).")
            raise AuthFailed("login rejected")
        except dav_error.DAVError as e:
            raise SyncError(f"Calendar server error: {e}")
        except SyncError:
            raise
        except Exception as e:  # network errors, DNS, TLS...
            host = urlparse(self.server_url).hostname or self.server_url
            raise SyncError(f"Couldn't reach {host}: {e.__class__.__name__}")

    def request(self, url: str, method: str, body: str = "", headers: dict | None = None):
        r = self._call(self.client.request, url, method, body, headers or {})
        if r.status in (401,):
            raise AuthFailed("login rejected")
        return r

    def _multistatus(self, url: str, method: str, body: str, depth: str) -> list[tuple[str, dict]]:
        r = self.request(url, method, body, {"Depth": depth, "Content-Type": "application/xml; charset=utf-8"})
        if r.status != 207:
            raise SyncError(f"Calendar server replied {r.status} to {method}")
        root = r.tree if r.tree is not None else etree.fromstring(r.raw.encode())
        out = []
        for resp in root.findall("d:response", NS):
            href = resp.findtext("d:href", namespaces=NS)
            if not href:
                continue
            props: dict[str, Any] = {}
            for ps in resp.findall("d:propstat", NS):
                status = ps.findtext("d:status", default="", namespaces=NS)
                if " 200" not in status:
                    continue
                prop = ps.find("d:prop", NS)
                if prop is not None:
                    for el in prop:
                        props[etree.QName(el).localname] = el
            out.append((urljoin(url, href.strip()), props))
        return out

    # discovery
    def home_url(self) -> str:
        principal = self._call(self.client.principal)
        home = self._call(lambda: principal.calendar_home_set)
        return str(home.url)

    def list_calendars(self, home: str) -> list[dict]:
        found = []
        for url, p in self._multistatus(home, "PROPFIND", PROPFIND_CALENDARS, "1"):
            rt = p.get("resourcetype")
            if rt is None or rt.find("c:calendar", NS) is None:
                continue
            comps = p.get("supported-calendar-component-set")
            names = [x.get("name") for x in comps.findall("c:comp", NS)] if comps is not None else []
            if names and "VEVENT" not in names:
                continue  # reminders / task lists
            privs = p.get("current-user-privilege-set")
            read_only = False
            if privs is not None:
                granted = {etree.QName(x).localname for pr in privs.findall("d:privilege", NS) for x in pr}
                read_only = not (granted & {"write", "write-content", "all", "bind"})
            name_el = p.get("displayname")
            ctag_el = p.get("getctag")
            tok_el = p.get("sync-token")
            col_el = p.get("calendar-color")
            found.append({
                "url": url,
                "name": (name_el.text or "").strip() if name_el is not None else "",
                "color": _norm_color(col_el.text if col_el is not None else None),
                "read_only": read_only,
                "ctag": (ctag_el.text if ctag_el is not None else None) or (tok_el.text if tok_el is not None else None),
            })
        for f in found:
            if not f["name"]:
                f["name"] = urlparse(f["url"]).path.rstrip("/").rsplit("/", 1)[-1] or "Calendar"
        return found

    # objects
    def list_etags(self, cal_url: str) -> dict[str, str]:
        out = {}
        for url, p in self._multistatus(cal_url, "REPORT", REPORT_ETAGS, "1"):
            if url.rstrip("/") == cal_url.rstrip("/"):
                continue
            et = p.get("getetag")
            out[url] = et.text if et is not None else ""
        return out

    def multiget(self, cal_url: str, urls: list[str]) -> dict[str, tuple[str | None, str]]:
        out: dict[str, tuple[str | None, str]] = {}
        for i in range(0, len(urls), MULTIGET_BATCH):
            hrefs = "".join(f"<d:href>{escape(urlparse(u).path)}</d:href>" for u in urls[i:i + MULTIGET_BATCH])
            for url, p in self._multistatus(cal_url, "REPORT", REPORT_MULTIGET.format(hrefs=hrefs), "1"):
                data = p.get("calendar-data")
                if data is None or not data.text:
                    continue
                et = p.get("getetag")
                out[url] = (et.text if et is not None else None, data.text)
        return out

    def get(self, url: str) -> tuple[str | None, str] | None:
        r = self.request(url, "GET")
        if r.status == 404 or r.status == 410:
            return None
        if r.status >= 300:
            raise SyncError(f"Calendar server replied {r.status} to GET")
        return r.headers.get("ETag"), r.raw

    def put(self, url: str, ics: str, etag: str | None = None, create: bool = False) -> str | None:
        headers = {"Content-Type": "text/calendar; charset=utf-8"}
        if create:
            headers["If-None-Match"] = "*"
        elif etag:
            headers["If-Match"] = etag
        r = self.request(url, "PUT", ics, headers)
        if r.status == 412:
            raise Conflict("precondition failed")
        if r.status == 403:
            raise Forbidden("The calendar server refused this change (no permission).")
        if r.status >= 300:
            raise SyncError(f"Calendar server replied {r.status} to the change")
        return r.headers.get("ETag")

    def delete(self, url: str, etag: str | None) -> None:
        r = self.request(url, "DELETE", "", {"If-Match": etag} if etag else {})
        if r.status == 412:
            raise Conflict("precondition failed")
        if r.status == 403:
            raise Forbidden("The calendar server refused this change (no permission).")
        if r.status >= 300 and r.status not in (404, 410):
            raise SyncError(f"Calendar server replied {r.status} to the delete")


def remote_for(acct: dict) -> Remote:
    return Remote(acct["server_url"], acct["username"], acct["password"])


def discover(server_url: str, username: str, password: str) -> tuple[str, list[dict]]:
    """Log in, find the calendar home and its event calendars. Raises AuthFailed / SyncError."""
    r = Remote(server_url, username, password)
    home = r.home_url()
    return home, r.list_calendars(home)


# ---------------------------------------------------------------- ICS <-> Moonlight event

def _text(comp, key: str) -> str:
    v = comp.get(key)
    return str(v).strip() if v is not None else ""


def _map_rrule(master, has_overrides: bool, dtstart, start_local: datetime, tz: ZoneInfo) -> tuple[dict | None, bool]:
    """(repeat, custom) for the master VEVENT. custom=True means expand from raw ICS."""
    rr = master.get("RRULE")
    if rr is None:
        return None, bool(has_overrides or "RDATE" in master)
    if isinstance(rr, list) or has_overrides or "EXDATE" in master or "RDATE" in master:
        return None, True
    if set(rr.keys()) - {"FREQ", "INTERVAL", "BYDAY", "UNTIL", "WKST", "BYMONTHDAY"}:
        return None, True
    freq = str(rr.get("FREQ", [""])[0]).lower()
    if freq not in ("daily", "weekly", "monthly"):
        return None, True
    if isinstance(dtstart, datetime) and dtstart.tzinfo is not None and _zone_key(dtstart) != tz.key:
        return None, True  # DST rules of another zone (or UTC) can't be expressed as local wall time
    try:
        interval = int(rr.get("INTERVAL", [1])[0])
    except (TypeError, ValueError):
        return None, True
    byday = [str(d).upper() for d in rr.get("BYDAY", [])]
    bymd = rr.get("BYMONTHDAY", [])
    start_d = start_local.date()
    out: dict = {"freq": freq, "interval": interval, "until": None}
    if freq == "daily" and (byday or bymd):
        return None, True
    if freq == "weekly":
        if bymd or any(d not in WEEKDAYS for d in byday):
            return None, True
        if byday and WEEKDAYS[start_d.weekday()] not in byday:
            return None, True
        wkst = rr.get("WKST")
        if interval > 1 and wkst and str(wkst[0]).upper() != "MO":
            return None, True
        if byday:
            out["byday"] = byday
    if freq == "monthly":
        if byday or (bymd and [int(x) for x in bymd] != [start_d.day]):
            return None, True
    if rr.get("UNTIL"):
        u = rr["UNTIL"][0]
        if isinstance(u, datetime):
            ul = to_local(u, tz)
            ud = ul.date()
            if ul.time() < start_local.time():
                ud -= timedelta(days=1)
        else:
            ud = u
        out["until"] = ud.isoformat()
    try:
        return normalize_repeat(out), False
    except ValueError:
        return None, True


def parse_resource(ics: str, tz: ZoneInfo) -> dict | None:
    """Moonlight fields for one CalDAV resource, or None if it holds no VEVENT."""
    cal = icalendar.Calendar.from_ical(ics)
    vevents = list(cal.walk("VEVENT"))
    if not vevents:
        return None
    masters = [e for e in vevents if e.get("RECURRENCE-ID") is None]
    master = masters[0] if masters else vevents[0]
    has_overrides = len(vevents) > 1 or not masters
    dtstart = master.decoded("DTSTART")
    all_day = not isinstance(dtstart, datetime)
    if "DTEND" in master:
        dtend = master.decoded("DTEND")
    elif "DURATION" in master:
        dtend = dtstart + master.decoded("DURATION")
    else:
        dtend = dtstart + timedelta(days=1) if all_day else dtstart
    start, end = to_local(dtstart, tz), to_local(dtend, tz)
    if all_day:
        end = datetime.combine(end.date(), time(0))
        if end <= start:
            end = start + timedelta(days=1)
    if end < start:
        end = start
    repeat, custom = _map_rrule(master, has_overrides, dtstart, start, tz)
    people = [p.strip() for p in _text(master, PEOPLE_PROP).split(",") if p.strip()]
    return {
        "uid": _text(master, "UID"), "title": _text(master, "SUMMARY") or "(No title)",
        "start": fmt_dt(start), "end": fmt_dt(end), "all_day": all_day,
        "location": _text(master, "LOCATION"), "notes": _text(master, "DESCRIPTION"),
        "repeat": repeat, "custom_repeat": custom, "person_ids": people, "busy": busy_status(master),
    }


def build_ics(raw: str | None, ev: dict, tz: ZoneInfo, explicit_people: list[str] | None,
              set_repeat: bool, uid: str | None = None) -> str:
    """New ICS for `ev`, editing the master VEVENT of `raw` in place (keeping unknown properties)."""
    if raw:
        cal = icalendar.Calendar.from_ical(raw)
        vevents = list(cal.walk("VEVENT"))
        master = next((e for e in vevents if e.get("RECURRENCE-ID") is None), vevents[0])
    else:
        cal = icalendar.Calendar()
        cal.add("prodid", "-//Moonlight//Family Calendar//EN")
        cal.add("version", "2.0")
        master = icalendar.Event()
        master.add("uid", uid or f"{uuid.uuid4()}")
        cal.add_component(master)
        set_repeat = True

    def setp(name: str, value: Any) -> None:
        master.pop(name, None)
        if value not in (None, ""):
            master.add(name, value)

    start = datetime.fromisoformat(ev["start"])
    end = datetime.fromisoformat(ev["end"])
    setp("SUMMARY", ev["title"])
    if ev["all_day"]:
        setp("DTSTART", start.date())
        setp("DTEND", end.date())
    else:
        setp("DTSTART", start.replace(tzinfo=tz))
        setp("DTEND", end.replace(tzinfo=tz))
    master.pop("DURATION", None)
    setp("LOCATION", ev.get("location") or None)
    setp("DESCRIPTION", ev.get("notes") or None)
    setp(PEOPLE_PROP, ",".join(explicit_people) if explicit_people else None)
    if set_repeat or ev.get("repeat"):
        # A simple rule is fully described by `repeat`, so it is always rewritten (keeps UNTIL in step
        # with a moved start time). Custom rules are only replaced when the client sends a new repeat.
        for k in ("RRULE", "RDATE", "EXDATE"):
            master.pop(k, None)
        cal.subcomponents = [s for s in cal.subcomponents if s.name != "VEVENT" or s is master]
        rep = ev.get("repeat")
        if rep:
            rr: dict[str, Any] = {"FREQ": rep["freq"].upper(), "INTERVAL": rep.get("interval") or 1}
            if rep.get("byday"):
                rr["BYDAY"] = rep["byday"]
            if rep.get("until"):
                ud = date.fromisoformat(rep["until"])
                rr["UNTIL"] = ud if ev["all_day"] else \
                    datetime.combine(ud, time(23, 59, 59)).replace(tzinfo=tz).astimezone(timezone.utc)
            master.add("RRULE", rr)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    setp("DTSTAMP", now)
    setp("LAST-MODIFIED", now)
    if raw:
        try:
            seq = int(master.get("SEQUENCE", 0))
        except (TypeError, ValueError):
            seq = 0
        setp("SEQUENCE", seq + 1)
    if not ev["all_day"]:
        cal.add_missing_timezones()
    return cal.to_ical().decode("utf-8")


# ---------------------------------------------------------------- query-time expansion

_ics_cache: dict[str, Any] = {}


def expand_custom(base: dict, raw: str, cache_key: str, rs: datetime, re_: datetime) -> list[dict]:
    """Occurrences of a custom-repeat synced event overlapping [rs, re_), in household-local time."""
    tz = household_tz()
    cal = _ics_cache.get(cache_key)
    if cal is None:
        try:
            cal = icalendar.Calendar.from_ical(raw)
        except Exception:
            log.exception("Unparseable ICS for %s", base["id"])
            return []
        if len(_ics_cache) > 2000:
            _ics_cache.clear()
        _ics_cache[cache_key] = cal
    lo = (rs - timedelta(days=1)).replace(tzinfo=tz)
    hi = (re_ + timedelta(days=1)).replace(tzinfo=tz)
    try:
        comps = recurring_ical_events.of(cal, components=["VEVENT"]).between(lo, hi)
    except Exception:
        log.exception("Couldn't expand %s", base["id"])
        return []
    out = []
    for comp in comps:
        ds = comp.decoded("DTSTART")
        all_day = not isinstance(ds, datetime)
        if "DTEND" in comp:
            de = comp.decoded("DTEND")
        elif "DURATION" in comp:
            de = ds + comp.decoded("DURATION")
        else:
            de = ds + timedelta(days=1) if all_day else ds
        s, e = to_local(ds, tz), to_local(de, tz)
        if e < s:
            e = s
        if s >= re_ or not (e > rs or (s == e and s >= rs)):
            continue
        occ = dict(base)
        occ.update({
            "title": _text(comp, "SUMMARY") or base["title"], "location": _text(comp, "LOCATION"),
            "notes": _text(comp, "DESCRIPTION"), "start": fmt_dt(s), "end": fmt_dt(e), "all_day": all_day,
            "occurrence_id": f"{base['id']}@{s.date().isoformat()}", "recurring": True,
        })
        if base.get("busy") is not None:  # free/busy calendar: a moved occurrence may be tentative
            occ["busy"] = busy_status(comp)
        out.append(occ)
    return out


# ---------------------------------------------------------------- local cache

def _lock(account_id: str, _locks: dict = {}, _guard=threading.Lock()) -> threading.Lock:  # noqa: B006
    with _guard:
        return _locks.setdefault(account_id, threading.Lock())


def default_people(c, cal_name: str) -> list[str]:
    people = db.rows(c, "SELECT id, name FROM people ORDER BY sort, name")
    words = set(re.findall(r"[^\W\d_]+", cal_name.casefold()))
    if words & FAMILY_NAMES:
        return [p["id"] for p in people]
    return [p["id"] for p in people if p["name"].casefold() in words]


def store_calendars(c, account_id: str, found: list[dict]) -> bool:
    """Upsert discovered calendars; drop ones that disappeared (and their events). True if any removed."""
    existing = {r["url"]: r for r in db.rows(c, "SELECT * FROM calendars WHERE account_id = ?", (account_id,))}
    for f in found:
        r = existing.get(f["url"])
        if r:
            c.execute("UPDATE calendars SET name = ?, read_only = ? WHERE id = ?",
                      (f["name"], int(f["read_only"]), r["id"]))
        else:
            c.execute("INSERT INTO calendars(id, account_id, url, name, color, person_ids, visible, read_only) "
                      "VALUES(?,?,?,?,?,?,1,?)",
                      (db.new_id("cal"), account_id, f["url"], f["name"], f["color"] or "#8A94A6",
                       json.dumps(default_people(c, f["name"])), int(f["read_only"])))
    gone = [r["id"] for u, r in existing.items() if u not in {f["url"] for f in found}]
    for cid in gone:
        c.execute("DELETE FROM events WHERE calendar_id = ?", (cid,))
        c.execute("DELETE FROM calendars WHERE id = ?", (cid,))
    return bool(gone)


def apply_resource(c, calendar_id: str, href: str, etag: str | None, ics: str, tz: ZoneInfo,
                   event_id: str | None = None) -> str | None:
    """Insert/update the cached copy of one resource. Returns the event id (None if it has no VEVENT)."""
    existing = db.row(c, "SELECT id FROM events WHERE calendar_id = ? AND href = ?", (calendar_id, href))
    try:
        p = parse_resource(ics, tz)
    except Exception:
        log.exception("Skipping unparseable event %s", href)
        return existing["id"] if existing else None
    if p is None:
        if existing:
            c.execute("DELETE FROM events WHERE id = ?", (existing["id"],))
        return None
    eid = existing["id"] if existing else (event_id or db.new_id("e"))
    args = (p["title"], json.dumps(p["person_ids"]), p["start"], p["end"], int(p["all_day"]), p["location"],
            p["notes"], json.dumps(p["repeat"]) if p["repeat"] else None, calendar_id, p["uid"], href, etag,
            ics, int(p["custom_repeat"]), p["busy"], eid)
    if existing or db.row(c, "SELECT 1 AS x FROM events WHERE id = ?", (eid,)):
        c.execute('UPDATE events SET title=?, person_ids=?, start=?, "end"=?, all_day=?, location=?, notes=?, '
                  "repeat=?, calendar_id=?, uid=?, href=?, etag=?, raw_ics=?, custom_repeat=?, busy=? WHERE id=?",
                  args)
    else:
        c.execute('INSERT INTO events(title, person_ids, start, "end", all_day, location, notes, repeat, '
                  "calendar_id, uid, href, etag, raw_ics, custom_repeat, busy, id) "
                  "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", args)
    return eid


def reparse_all() -> None:
    """Re-derive local times of every synced event (after the household timezone changes)."""
    tz = household_tz()
    with db.connect() as c:
        for r in db.rows(c, "SELECT calendar_id, href, etag, raw_ics FROM events WHERE calendar_id IS NOT NULL"):
            apply_resource(c, r["calendar_id"], r["href"], r["etag"], r["raw_ics"], tz)
    _ics_cache.clear()


def _set_status(account_id: str, status: str, error: str | None, synced: bool = False) -> None:
    with db.connect() as c:
        if synced:
            c.execute("UPDATE accounts SET status=?, last_error=?, last_sync=? WHERE id=?",
                      (status, error, db.now_iso(), account_id))
        else:
            c.execute("UPDATE accounts SET status=?, last_error=? WHERE id=?", (status, error, account_id))


def _pull_calendar(remote: Remote, cal: dict, tz: ZoneInfo) -> bool:
    remote_etags = remote.list_etags(cal["url"])
    with db.connect() as c:
        local = {r["href"]: r["etag"] for r in db.rows(
            c, "SELECT href, etag FROM events WHERE calendar_id = ?", (cal["id"],))}
    want = [h for h, et in remote_etags.items() if h not in local or not et or local[h] != et]
    gone = [h for h in local if h not in remote_etags]
    fetched = remote.multiget(cal["url"], want) if want else {}
    with db.connect() as c:
        for h in gone:
            c.execute("DELETE FROM events WHERE calendar_id = ? AND href = ?", (cal["id"], h))
        for h, (etag, data) in fetched.items():
            apply_resource(c, cal["id"], h, etag or remote_etags.get(h), data, tz)
    return bool(gone or fetched)


def sync_account(account_id: str, force: bool = False) -> bool:
    """Blocking: pull changes for one account. Returns True if events changed. Raises SyncError."""
    with _lock(account_id):
        with db.connect() as c:
            acct = db.row(c, "SELECT * FROM accounts WHERE id = ?", (account_id,))
        if not acct:
            return False
        if acct["kind"] in ("ics", "ha"):
            return _sync_feed(acct, force)
        remote = remote_for(acct)
        try:
            home = acct["home_url"] or remote.home_url()
            found = remote.list_calendars(home)
            tz = household_tz()
            with db.connect() as c:
                c.execute("UPDATE accounts SET home_url = ? WHERE id = ?", (home, account_id))
                changed = store_calendars(c, account_id, found)
                cals = db.rows(c, "SELECT * FROM calendars WHERE account_id = ?", (account_id,))
            ctags = {f["url"]: f["ctag"] for f in found}
            for cal in cals:
                ctag = ctags.get(cal["url"])
                if not force and ctag and ctag == cal["ctag"]:
                    continue
                changed |= _pull_calendar(remote, cal, tz)
                with db.connect() as c:
                    c.execute("UPDATE calendars SET ctag = ? WHERE id = ?", (ctag, cal["id"]))
        except AuthFailed:
            _set_status(account_id, "auth_failed", auth_message(acct["kind"]))
            raise
        except SyncError as e:
            _set_status(account_id, "error", str(e))
            raise
        except Exception as e:
            log.exception("Sync of %s failed", account_id)
            _set_status(account_id, "error", f"Sync failed: {e.__class__.__name__}")
            raise SyncError(str(e))
        _set_status(account_id, "ok", None, synced=True)
        return changed


def _sync_feed(acct: dict, force: bool) -> bool:
    from . import ha_calendar, ics_feed  # import this module
    try:
        changed = ha_calendar.sync(acct) if acct["kind"] == "ha" else ics_feed.sync_feed(acct, force)
    except SyncError as e:
        _set_status(acct["id"], "error", str(e))
        raise
    except Exception as e:
        log.exception("Feed %s failed", acct["id"])
        _set_status(acct["id"], "error", f"Couldn't read the calendar: {e.__class__.__name__}")
        raise SyncError(str(e))
    _set_status(acct["id"], "ok", None, synced=True)
    return changed


# ---------------------------------------------------------------- writes (blocking, run in a thread)

def _calendar_ctx(c, calendar_id: str) -> tuple[dict, dict]:
    cal = db.row(c, "SELECT * FROM calendars WHERE id = ?", (calendar_id,))
    if not cal:
        raise ValueError("Unknown calendar")
    acct = db.row(c, "SELECT * FROM accounts WHERE id = ?", (cal["account_id"],))
    return cal, acct


def target_calendar(c, body: dict, person_ids: list[str], current: str | None = None) -> str | None:
    """Which synced calendar an event should live in. None = local-only. Raises ValueError."""
    if "calendar_id" in body:
        cid = body.get("calendar_id")
        if cid in (None, "", "local"):
            return None
        cal = db.row(c, "SELECT * FROM calendars WHERE id = ?", (cid,))
        if not cal:
            raise ValueError("Unknown calendar")
        if cal["read_only"] and cid != current:
            raise ValueError(f"The calendar “{cal['name']}” is read-only")
        return cid
    if current is not None:
        return current
    cals = db.rows(c, "SELECT c.* FROM calendars c JOIN accounts a ON a.id = c.account_id "
                      "WHERE c.read_only = 0 AND c.visible = 1 ORDER BY a.created_at, a.id, c.name")
    for pid in person_ids[:1]:
        mine = [cal for cal in cals if pid in json.loads(cal["person_ids"])]
        if mine:  # prefer the person's own calendar over shared ones (e.g. "Jordan" before "Family")
            return min(mine, key=lambda cal: len(json.loads(cal["person_ids"])))["id"]
    return None


def _explicit_people(cal: dict, person_ids: list[str]) -> list[str] | None:
    return None if set(person_ids) == set(json.loads(cal["person_ids"])) else list(person_ids)


def _guard(acct: dict, fn, *args):
    try:
        return fn(*args)
    except AuthFailed:
        _set_status(acct["id"], "auth_failed", auth_message(acct["kind"]))
        raise AuthFailed(auth_message(acct["kind"]))


def _refetch_and_conflict(remote: Remote, acct: dict, row: dict, tz: ZoneInfo) -> None:
    fresh = _guard(acct, remote.get, row["href"])
    with db.connect() as c:
        if fresh is None:
            c.execute("DELETE FROM events WHERE id = ?", (row["id"],))
        else:
            apply_resource(c, row["calendar_id"], row["href"], fresh[0], fresh[1], tz)
    if fresh is None:
        raise Conflict(f"“{row['title']}” was deleted on another device. Your change was not saved.")
    raise Conflict(f"“{row['title']}” was changed on another device (iCloud) since this screen loaded it. "
                   "The latest version is shown now; please make your change again.")


def _create(cal: dict, acct: dict, ev: dict, tz: ZoneInfo, event_id: str) -> None:
    remote = remote_for(acct)
    uid = f"{uuid.uuid4()}"
    href = urljoin(cal["url"].rstrip("/") + "/", f"{uid}.ics")
    ics = build_ics(None, ev, tz, _explicit_people(cal, ev["person_ids"]), True, uid)
    etag = _guard(acct, remote.put, href, ics, None, True)
    with db.connect() as c:
        apply_resource(c, cal["id"], href, etag, ics, tz, event_id=event_id)


def _remove(row: dict, acct: dict, tz: ZoneInfo) -> None:
    remote = remote_for(acct)
    try:
        _guard(acct, remote.delete, row["href"], row["etag"])
    except Conflict:
        _refetch_and_conflict(remote, acct, row, tz)


def save_event(existing: dict | None, ev: dict, target: str | None, set_repeat: bool) -> str:
    """Write a create/update through to CalDAV (if synced) and store it. Returns the event id."""
    tz = household_tz()
    with db.connect() as c:
        tgt = _calendar_ctx(c, target) if target else None
        src = _calendar_ctx(c, existing["calendar_id"]) if existing and existing.get("calendar_id") else None
    if tgt and tgt[0]["read_only"] and (not src or src[0]["id"] != tgt[0]["id"]):
        raise ValueError(f"The calendar “{tgt[0]['name']}” is read-only")
    if src and src[0]["read_only"]:
        raise Forbidden(f"“{existing['title']}” is in a read-only calendar and can't be changed here.")
    event_id = existing["id"] if existing else ev["id"]

    if src and tgt and src[0]["id"] == tgt[0]["id"]:  # plain update
        cal, acct = src
        with _lock(acct["id"]):
            remote = remote_for(acct)
            row = existing
            if not row.get("etag"):
                fresh = _guard(acct, remote.get, row["href"])
                if fresh is None:
                    with db.connect() as c:
                        c.execute("DELETE FROM events WHERE id = ?", (row["id"],))
                    raise Conflict(f"“{row['title']}” was deleted on another device. Your change was not saved.")
                row = {**row, "etag": fresh[0], "raw_ics": fresh[1]}
            ics = build_ics(row["raw_ics"], ev, tz, _explicit_people(cal, ev["person_ids"]), set_repeat)
            try:
                etag = _guard(acct, remote.put, row["href"], ics, row["etag"])
            except Conflict:
                _refetch_and_conflict(remote, acct, row, tz)
            with db.connect() as c:
                apply_resource(c, cal["id"], row["href"], etag, ics, tz)
        return event_id

    if src:  # moving out of a synced calendar: delete there first (If-Match), then re-create
        with _lock(src[1]["id"]):
            _remove(existing, src[1], tz)
        try:
            if tgt:
                with _lock(tgt[1]["id"]):
                    _create(tgt[0], tgt[1], ev, tz, event_id)
        except Exception:
            # put the original back so nothing is lost
            try:
                remote_for(src[1]).put(existing["href"], existing["raw_ics"], None, True)
            except Exception:
                log.exception("Couldn't restore %s after a failed move", existing["href"])
            raise
        if not tgt:
            with db.connect() as c:
                c.execute("UPDATE events SET calendar_id=NULL, uid=NULL, href=NULL, etag=NULL, raw_ics=NULL, "
                          "custom_repeat=0 WHERE id=?", (event_id,))
            return event_id  # caller saves the local fields
        return event_id

    if tgt:  # new event, or local event moving into a synced calendar
        with _lock(tgt[1]["id"]):
            _create(tgt[0], tgt[1], ev, tz, event_id)
        return event_id
    return event_id


def delete_event(existing: dict) -> None:
    tz = household_tz()
    with db.connect() as c:
        cal, acct = _calendar_ctx(c, existing["calendar_id"])
    if cal["read_only"]:
        raise Forbidden(f"“{existing['title']}” is in a read-only calendar and can't be deleted here.")
    with _lock(acct["id"]):
        _remove(existing, acct, tz)
        with db.connect() as c:
            c.execute("DELETE FROM events WHERE id = ?", (existing["id"],))


# ---------------------------------------------------------------- background loop

class SyncManager:
    """Polls every CalDAV account every `interval` seconds and every ICS feed and Home Assistant calendar
    every `feed_interval` seconds (default 15 min), with exponential backoff on errors.

    An account whose login fails is marked auth_failed and skipped until its credentials change.
    """

    def __init__(self, interval: float | None = None):
        self.interval = float(interval or os.environ.get("MOONLIGHT_SYNC_SECONDS", "120"))
        from .ics_feed import feed_interval
        self.feed_interval = feed_interval()
        self.task: asyncio.Task | None = None
        self.wake: asyncio.Event | None = None
        self.state: dict[str, dict] = {}

    @property
    def running(self) -> bool:
        return self.task is not None and not self.task.done()

    def start(self) -> None:
        self.wake = asyncio.Event()
        self.task = asyncio.get_running_loop().create_task(self._run())
        log.info("Calendar sync every %ss", int(self.interval))

    async def stop(self) -> None:
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except (asyncio.CancelledError, Exception):
                pass
            self.task = None

    def poke(self, account_id: str | None = None) -> None:
        if account_id:
            self.state[account_id] = {"fails": 0, "next": 0.0}
        if self.wake:
            self.wake.set()

    def interval_for(self, account_id: str) -> float:
        with db.connect() as c:
            r = db.row(c, "SELECT kind FROM accounts WHERE id = ?", (account_id,))
        return self.feed_interval if r and r["kind"] in ("ics", "ha") else self.interval

    def synced(self, account_id: str) -> None:
        """An account was just synced outside the loop (e.g. a feed added): next poll one interval later."""
        self.state[account_id] = {"fails": 0, "next": _time.monotonic() + self.interval_for(account_id)}

    async def sync_one(self, account_id: str, force: bool = False) -> None:
        st = self.state.setdefault(account_id, {"fails": 0, "next": 0.0})
        changed = False
        interval = self.interval_for(account_id)
        try:
            changed = await asyncio.to_thread(sync_account, account_id, force)
            st.update(fails=0, next=_time.monotonic() + interval)
        except AuthFailed:
            st.update(fails=0, next=_time.monotonic() + interval)
            log.warning("Calendar account %s: login rejected; waiting for new credentials", account_id)
        except Exception as e:
            st["fails"] += 1
            # Retry sooner than a long feed interval, then back off to at most an hour.
            st["next"] = _time.monotonic() + min(min(interval, 300) * 2 ** st["fails"], max(3600, interval))
            log.warning("Calendar account %s sync failed (%s); retry in %ds", account_id, e,
                        st["next"] - _time.monotonic())
        await hub.broadcast(*(("accounts", "events") if changed else ("accounts",)))

    async def _run(self) -> None:
        while True:
            try:
                with db.connect() as c:
                    accts = db.rows(c, "SELECT id, status FROM accounts ORDER BY created_at")
                for a in accts:
                    if a["status"] == "auth_failed":
                        continue
                    st = self.state.setdefault(a["id"], {"fails": 0, "next": 0.0})
                    if st["next"] <= _time.monotonic():
                        await self.sync_one(a["id"])
                nexts = [self.state[a["id"]]["next"] for a in accts if a["status"] != "auth_failed"
                         and a["id"] in self.state]
                wait = min([n - _time.monotonic() for n in nexts] + [self.interval, self.feed_interval])
                wait = max(1.0, wait)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Sync loop error")
                wait = self.interval
            try:
                await asyncio.wait_for(self.wake.wait(), wait)
            except asyncio.TimeoutError:
                pass
            self.wake.clear()


manager: SyncManager | None = None


async def sync_now(account_id: str, force: bool = False) -> None:
    """Sync one account right away (used by POST /api/accounts/{id}/sync)."""
    if manager is not None:
        await manager.sync_one(account_id, force)
        return
    changed = False
    try:
        changed = await asyncio.to_thread(sync_account, account_id, force)
    except SyncError:
        pass  # status recorded on the account
    await hub.broadcast(*(("accounts", "events") if changed else ("accounts",)))


def poke(account_id: str | None = None) -> None:
    if manager is not None:
        manager.poke(account_id)


def mark_synced(account_id: str) -> None:
    if manager is not None:
        manager.synced(account_id)
