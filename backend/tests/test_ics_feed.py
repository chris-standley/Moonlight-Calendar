"""Read-only calendar subscriptions from published ICS links (ics_feed.py), against httpx.MockTransport.

No real calendar server is contacted: every URL below is answered by `FakeFeeds`.
"""
from __future__ import annotations

import asyncio
import sqlite3
import sys
from datetime import date
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from moonlight import caldav_sync, ics_feed  # noqa: E402
from moonlight.main import create_app  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
PIN = "4321"
# Shaped like an Outlook "Publish a calendar" ICS link; the long path segments are the secret.
WORK_URL = ("https://outlook.example.test/owa/calendar/0a1b2c3d4e5f60718293a4b5c6d7e8f9@contoso.test/"
            "f0e1d2c3b4a5968778695a4b3c2d1e0f1234567890/calendar.ics")
SECRET = "f0e1d2c3b4a5968778695a4b3c2d1e0f1234567890"
SCHOOL_URL = "https://school.example.test/terms.ics"
TITLES_URL = "https://outlook.example.test/owa/calendar/abc/titles-9f8e7d6c5b4a/calendar.ics"
TODAY = date(2026, 10, 10)


def fixture(name: str) -> str:
    with open(FIXTURES / name, newline="") as f:  # keep the CRLF line endings real feeds use
        return f.read()


class FakeFeeds:
    """URL -> (status, body, etag). Honours If-None-Match with a 304 and records every request."""

    def __init__(self):
        self.feeds: dict[str, tuple[int, str, str | None]] = {}
        self.requests: list[httpx.Request] = []

    def set(self, url: str, body: str, etag: str | None = '"v1"', status: int = 200):
        self.feeds[url] = (status, body, etag)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url = str(request.url)
        if url not in self.feeds:
            return httpx.Response(404, text="Not found")
        status, body, etag = self.feeds[url]
        headers = {"Content-Type": "text/calendar; charset=utf-8"}
        if etag:
            headers["ETag"] = etag
            if request.headers.get("If-None-Match") == etag:
                return httpx.Response(304, headers=headers)
        headers["Last-Modified"] = "Fri, 09 Oct 2026 12:00:00 GMT"
        return httpx.Response(status, text=body, headers=headers)


@pytest.fixture
def feeds(monkeypatch):
    f = FakeFeeds()
    monkeypatch.setattr(ics_feed, "transport", httpx.MockTransport(f))
    monkeypatch.setattr(ics_feed, "today", lambda tz: TODAY)
    monkeypatch.delenv("MOONLIGHT_TIMEZONE", raising=False)
    return f


class RecordingClient(TestClient):
    bodies: list[str]

    def request(self, *args, **kwargs):
        r = super().request(*args, **kwargs)
        self.bodies.append(r.text)
        return r


@pytest.fixture
def db_file(tmp_path):
    return str(tmp_path / "test.db")


@pytest.fixture
def client(db_file, tmp_path, feeds):
    app = create_app(db_path=db_file, demo=False, static_dir=tmp_path / "no-dist", sync=False)
    with RecordingClient(app) as c:
        c.bodies = []
        assert c.patch("/api/settings", json={"pin": PIN}).status_code == 200
        c.people = {n: c.post("/api/people", json={"name": n, "color": col, "role": role}).json()["id"]
                    for n, col, role in [("Chris", "#4F7CEC", "adult"), ("Sam", "#9B6BE0", "adult"),
                                         ("Mia", "#F0679A", "child")]}
        yield c
        for b in c.bodies:  # the link is a secret: never sent back in full
            assert SECRET not in b and "titles-9f8e7d6c5b4a" not in b


def add_feed(client, url, label="Work", who=("Chris",), **kw):
    r = client.post("/api/accounts", json={"kind": "ics", "url": url, "label": label, "pin": PIN,
                                           "person_ids": [client.people[n] for n in who], **kw})
    assert r.status_code == 200, r.text
    return r.json()


def events(client, start="2026-10-01", end="2026-11-15"):
    r = client.get(f"/api/events?start={start}&end={end}")
    assert r.status_code == 200, r.text
    return r.json()


def feed_events(client, acct, **kw):
    cal = next(c for c in client.get("/api/calendars").json() if c["account_id"] == acct["id"])
    return [e for e in events(client, **kw) if e["calendar_id"] == cal["id"]]


def when(evs):
    return {(e["start"], e["end"], e["busy"]) for e in evs}


# ---------------------------------------------------------------- unit level

def test_url_normalising_and_masking():
    assert ics_feed.normalize_url(" webcal://outlook.office365.com/owa/calendar/x/y/calendar.ics ") == \
        "https://outlook.office365.com/owa/calendar/x/y/calendar.ics"
    assert ics_feed.normalize_url("WEBCALS://example.org/a.ics") == "https://example.org/a.ics"
    for bad_url in ("", "ftp://example.org/a.ics", "outlook.office365.com/calendar.ics", "https://"):
        with pytest.raises(ValueError):
            ics_feed.normalize_url(bad_url)
    masked = ics_feed.mask_url(WORK_URL)
    assert masked == "outlook.example.test/…/calendar.ics" and SECRET not in masked
    assert ics_feed.mask_url("https://example.org/terms.ics") == "example.org/terms.ics"
    assert "abc" not in ics_feed.mask_url("https://example.org/feed?token=abc")
    assert "0123456789abcdef" not in ics_feed.mask_url("https://h.test/private-0123456789abcdef0123")


def test_windows_timezones_are_understood_by_the_libraries():
    """icalendar resolves Outlook's Windows TZIDs: via the feed's VTIMEZONE, or its built-in table."""
    import icalendar
    cal = icalendar.Calendar.from_ical(fixture("outlook_freebusy.ics"))
    starts = {str(e["UID"])[-4:]: e.decoded("DTSTART") for e in cal.walk("VEVENT") if "RECURRENCE-ID" not in e}
    assert starts["1001"].utcoffset().total_seconds() == 3600            # GMT Standard Time in October = BST
    assert starts["1002"].utcoffset().total_seconds() == -7 * 3600       # Pacific (no VTIMEZONE) = PDT
    titles = icalendar.Calendar.from_ical(fixture("outlook_titles.ics"))
    first = next(iter(titles.walk("VEVENT"))).decoded("DTSTART")
    assert first.utcoffset().total_seconds() == 2 * 3600                 # W. Europe Standard Time = CEST


def test_busy_status_from_cdo_summary_and_transp():
    import icalendar
    def ev(**props):
        e = icalendar.Event()
        for k, v in props.items():
            e.add(k.replace("_", "-"), v)
        return e
    from moonlight.freebusy import busy_status
    assert busy_status(ev(summary="Team sync", X_MICROSOFT_CDO_BUSYSTATUS="OOF")) == "away"
    assert busy_status(ev(summary="Tentative")) == "tentative"
    assert busy_status(ev(summary="Out of Office")) == "away"
    assert busy_status(ev(summary="Lunch", transp="TRANSPARENT")) == "free"
    assert busy_status(ev(summary="Planning")) == "busy"


# ---------------------------------------------------------------- API

def test_preview_counts_events_in_the_window(client, feeds):
    feeds.set(WORK_URL, fixture("outlook_freebusy.ics"))
    r = client.post("/api/accounts/feed-preview", json={"url": WORK_URL.replace("https://", "webcal://")})
    assert r.status_code == 200, r.text
    # 9 UIDs in the file; 4 are free, too old, too far ahead or a finished series... the free one still counts.
    assert r.json() == {"event_count": 5, "name": "Calendar", "busy_only": True,
                        "masked_url": "outlook.example.test/…/calendar.ics"}
    assert feeds.requests[-1].url.scheme == "https"
    assert client.get("/api/accounts").json() == []  # nothing saved


def test_outlook_free_busy_feed(client, feeds, db_file):
    feeds.set(WORK_URL, fixture("outlook_freebusy.ics"))
    acct = add_feed(client, WORK_URL)
    assert acct["kind"] == "ics" and acct["status"] == "ok" and acct["calendar_count"] == 1
    assert acct["server_url"] == "outlook.example.test/…/calendar.ics" and acct["username"] == ""
    assert "password" not in acct and "url" not in acct
    [cal] = client.get("/api/calendars").json()
    assert cal["read_only"] and cal["busy_blocks"] and cal["busy_blocks_auto"] and not cal["busy_blocks_set"]
    assert cal["name"] == "Work" and cal["person_ids"] == [client.people["Chris"]]
    assert cal["color"] == "#4F7CEC"  # defaults to the person's colour

    evs = feed_events(client, acct)
    assert all(e["source"] == "ics" and e["read_only"] for e in evs)
    assert all(e["person_ids"] == [client.people["Chris"]] for e in evs)
    got = when(evs)
    # Weekly Tuesday block at 09:00 UK time both sides of the 25 Oct clock change; 20 Oct is excluded
    # and 27 Oct was moved to 11:00 and is only tentative.
    assert ("2026-10-06T09:00", "2026-10-06T10:00", "busy") in got
    assert ("2026-10-13T09:00", "2026-10-13T10:00", "busy") in got
    assert not any(s.startswith("2026-10-20") for s, _, _ in got)
    assert ("2026-10-27T11:00", "2026-10-27T12:00", "tentative") in got
    assert not any(s == "2026-10-27T09:00" for s, _, _ in got)
    assert ("2026-11-03T09:00", "2026-11-03T10:00", "busy") in got
    # Pacific Standard Time (no VTIMEZONE in the feed): 09:00 PDT = 17:00 BST.
    assert ("2026-10-13T17:00", "2026-10-13T18:00", "busy") in got
    # Weekly 08:00 Pacific: the UK falls back on 25 Oct, the US on 1 Nov, so one week is an hour earlier.
    assert {s for s, _, _ in got if s[11:] in ("15:00", "16:00") and s[5:7] in ("10", "11")} >= {
        "2026-10-15T16:00", "2026-10-22T16:00", "2026-10-29T15:00", "2026-11-05T16:00"}
    # All-day out of office.
    away = [e for e in evs if e["all_day"]]
    assert [(e["start"], e["end"], e["busy"]) for e in away] == [("2026-10-16T00:00", "2026-10-17T00:00", "away")]
    # Free time is not shown at all.
    assert not any(e["start"].startswith("2026-10-14") for e in evs)
    # Outside the kept window: never stored.
    with sqlite3.connect(db_file) as c:
        uids = {r[0][-4:] for r in c.execute("SELECT uid FROM events WHERE calendar_id = ?", (cal["id"],))}
    assert uids == {"1001", "1002", "1003", "1004", "1005"}

    # Read-only: can't be edited or deleted from Moonlight.
    eid = evs[0]["id"]
    assert client.patch(f"/api/events/{eid}", json={"title": "Mine now"}).status_code == 403
    assert client.delete(f"/api/events/{eid}").status_code == 403
    assert client.post("/api/events", json={"title": "x", "person_ids": [], "start": "2026-10-12T10:00",
                                            "end": "2026-10-12T11:00", "calendar_id": cal["id"]}).status_code == 400

    # Busy blocks can be switched off (titles then show as published) and back to automatic.
    r = client.patch(f"/api/calendars/{cal['id']}", json={"busy_blocks": False})
    assert r.status_code == 200 and not r.json()["busy_blocks"] and r.json()["busy_blocks_set"]
    evs = feed_events(client, acct)
    assert all(e["busy"] is None for e in evs) and any(e["title"] == "Free" for e in evs)
    r = client.patch(f"/api/calendars/{cal['id']}", json={"busy_blocks": None})
    assert r.json()["busy_blocks"] and not r.json()["busy_blocks_set"]
    assert client.patch(f"/api/calendars/{cal['id']}", json={"busy_blocks": "yes"}).status_code == 400


def test_unchanged_feed_uses_conditional_get(client, feeds, db_file):
    feeds.set(WORK_URL, fixture("outlook_freebusy.ics"))
    acct = add_feed(client, WORK_URL)
    before = feed_events(client, acct)
    n = len(feeds.requests)
    r = client.post(f"/api/accounts/{acct['id']}/sync")
    assert r.status_code == 200 and r.json()["status"] == "ok" and r.json()["last_sync"]
    req = feeds.requests[n]
    assert req.headers["If-None-Match"] == '"v1"'
    assert req.headers["If-Modified-Since"] == "Fri, 09 Oct 2026 12:00:00 GMT"
    assert feed_events(client, acct) == before

    # A server without validators that sends the same body: also no change.
    feeds.set(WORK_URL, fixture("outlook_freebusy.ics"), etag=None)
    assert client.post(f"/api/accounts/{acct['id']}/sync").json()["status"] == "ok"
    assert feed_events(client, acct) == before
    assert "If-None-Match" in feeds.requests[-1].headers  # still sent the last ETag it had


def test_changed_feed_replaces_only_changed_events(client, feeds, db_file):
    text = fixture("outlook_freebusy.ics")
    feeds.set(WORK_URL, text)
    acct = add_feed(client, WORK_URL)
    with sqlite3.connect(db_file) as c:
        ids = dict(c.execute("SELECT substr(uid, -4), id FROM events"))
    # The one-off Pacific call moves an hour later; the all-day away day is cancelled (removed from the feed).
    changed = text.replace("20261013T090000", "20261013T100000").replace("20261013T100000\r\nCLASS", "20261013T110000\r\nCLASS")
    start = changed.index("BEGIN:VEVENT\r\nDESCRIPTION:\\n\r\nUID:040000008200E00074C5B7101A82E00800000001005")
    changed = changed[:start] + changed[changed.index("END:VEVENT\r\n", start) + len("END:VEVENT\r\n"):]
    feeds.set(WORK_URL, changed, etag='"v2"')
    assert client.post(f"/api/accounts/{acct['id']}/sync").json()["status"] == "ok"
    got = when(feed_events(client, acct))
    assert ("2026-10-13T18:00", "2026-10-13T19:00", "busy") in got
    assert ("2026-10-13T17:00", "2026-10-13T18:00", "busy") not in got
    assert not any(e[2] == "away" for e in got)
    with sqlite3.connect(db_file) as c:
        after = dict(c.execute("SELECT substr(uid, -4), id FROM events"))
    assert "1005" not in after
    assert after["1001"] == ids["1001"] and after["1002"] == ids["1002"]  # updated in place, same ids


def test_titles_feed_and_school_feed(client, feeds):
    feeds.set(TITLES_URL, fixture("outlook_titles.ics"))
    feeds.set(SCHOOL_URL, fixture("school_terms.ics"))
    work = add_feed(client, TITLES_URL, label="Sam work", who=("Sam",))
    school = add_feed(client, SCHOOL_URL, label="", who=("Mia",), color="#63da38")
    assert school["label"] == "Hillside School"  # from X-WR-CALNAME
    cals = {c["account_id"]: c for c in client.get("/api/calendars").json()}
    assert not cals[work["id"]]["busy_blocks"] and not cals[school["id"]]["busy_blocks"]
    assert cals[school["id"]]["color"] == "#63DA38"

    w = feed_events(client, work)
    assert [(e["title"], e["location"], e["start"], e["busy"]) for e in w] == [
        ("Quarterly review", "Room 4.12", "2026-10-14T14:00", None),   # 15:00 CEST = 14:00 BST
        ("Dentist (personal)", "", "2026-10-15T08:30", None)]
    # Forcing busy blocks on a titles feed keeps the statuses from X-MICROSOFT-CDO-BUSYSTATUS.
    client.patch(f"/api/calendars/{cals[work['id']]['id']}", json={"busy_blocks": True})
    assert [e["busy"] for e in feed_events(client, work)] == ["busy", "away"]

    s = {(e["title"], e["start"], e["end"], e["all_day"]) for e in feed_events(client, school)}
    assert ("Half term", "2026-10-26T00:00", "2026-10-31T00:00", True) in s
    assert ("INSET day", "2026-11-02T00:00", "2026-11-03T00:00", True) in s
    assert ("Open evening", "2026-10-21T18:00", "2026-10-21T19:30", False) in s
    bins = sorted(e[1][:10] for e in s if e[0] == "Recycling bins")
    assert bins == ["2026-10-08", "2026-10-22", "2026-11-05"]
    assert all(e["person_ids"] == [client.people["Mia"]] for e in feed_events(client, school))


def test_bad_links_and_errors(client, feeds):
    assert client.post("/api/accounts", json={"kind": "ics", "url": "ftp://x/y.ics", "pin": PIN}).status_code == 400
    assert client.post("/api/accounts", json={"kind": "ics", "url": WORK_URL, "pin": "0000"}).status_code == 403
    r = client.post("/api/accounts/feed-preview", json={"url": WORK_URL})
    assert r.status_code == 502 and "no longer works" in r.json()["detail"] and SECRET not in r.text
    feeds.set(WORK_URL, "<html>Sign in</html>")
    r = client.post("/api/accounts/feed-preview", json={"url": WORK_URL})
    assert r.status_code == 502 and "didn't return a calendar" in r.json()["detail"]
    feeds.set(WORK_URL, fixture("outlook_freebusy.ics"))
    acct = add_feed(client, WORK_URL)
    r = client.post("/api/accounts", json={"kind": "ics", "url": WORK_URL, "pin": PIN})
    assert r.status_code == 400 and "already" in r.json()["detail"]

    # The link is unpublished: status error with a message, cached events stay until it works again.
    before = feed_events(client, acct)
    feeds.set(WORK_URL, "gone", status=404, etag=None)
    a = client.post(f"/api/accounts/{acct['id']}/sync").json()
    assert a["status"] == "error" and "unpublished" in a["last_error"]
    assert feed_events(client, acct) == before
    st = client.get("/api/sync/status").json()
    assert st["accounts"][0]["status"] == "error" and not st["needs_reconnect"]

    # Paste a new link: verified, replaces the events, status back to ok.
    feeds.set(SCHOOL_URL, fixture("school_terms.ics"))
    r = client.patch(f"/api/accounts/{acct['id']}", json={"pin": PIN, "url": SCHOOL_URL, "label": "Terms"})
    assert r.status_code == 200 and r.json()["status"] == "ok" and r.json()["server_url"] == "school.example.test/terms.ics"
    titles = {e["title"] for e in feed_events(client, acct)}
    assert "Half term" in titles and "Busy" not in titles
    assert client.get("/api/calendars").json()[0]["name"] == "Terms"

    assert client.request("DELETE", f"/api/accounts/{acct['id']}", json={"pin": PIN}).status_code == 200
    assert events(client) == []


def test_background_loop_polls_feeds_with_backoff(db_file, tmp_path, feeds, monkeypatch):
    monkeypatch.setenv("MOONLIGHT_FEED_SECONDS", "900")
    app = create_app(db_path=db_file, demo=False, static_dir=tmp_path / "no-dist", sync=False)
    with TestClient(app) as c:
        assert c.patch("/api/settings", json={"pin": PIN}).status_code == 200
        feeds.set(WORK_URL, fixture("outlook_freebusy.ics"))
        acct = c.post("/api/accounts", json={"kind": "ics", "url": WORK_URL, "pin": PIN}).json()
        assert acct["label"] == "Calendar"

    async def run():
        m = caldav_sync.SyncManager(interval=120)
        assert m.feed_interval == 900 and m.interval_for(acct["id"]) == 900
        caldav_sync.manager = m
        try:
            import time
            feeds.set(WORK_URL, "down", status=500, etag=None)
            await m.sync_one(acct["id"])
            st = m.state[acct["id"]]
            assert st["fails"] == 1 and 590 < st["next"] - time.monotonic() <= 600   # 5 min * 2
            await m.sync_one(acct["id"])
            assert 1190 < m.state[acct["id"]]["next"] - time.monotonic() <= 1200
            feeds.set(WORK_URL, fixture("outlook_freebusy.ics"))
            await m.sync_one(acct["id"])
            st = m.state[acct["id"]]
            assert st["fails"] == 0 and 890 < st["next"] - time.monotonic() <= 900
        finally:
            caldav_sync.manager = None

    asyncio.run(run())
