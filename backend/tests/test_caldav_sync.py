"""Calendar sync against a real CalDAV server (Radicale, in-thread on a random port)."""
from __future__ import annotations

import os
import socketserver
import sqlite3
import sys
import threading
import time
from pathlib import Path
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

import caldav
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from moonlight import caldav_sync  # noqa: E402
from moonlight.main import create_app  # noqa: E402

radicale = pytest.importorskip("radicale")
from radicale import config as radicale_config  # noqa: E402

PIN = "4321"
USER, PASSWORD = "alice", "app-pass-Zq81x"


class _Server(socketserver.ThreadingMixIn, WSGIServer):
    daemon_threads = True


class _Quiet(WSGIRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture
def server(tmp_path):
    users = tmp_path / "users"
    users.write_text(f"{USER}:{PASSWORD}\n")
    conf = radicale_config.load()
    conf.update({
        "storage": {"filesystem_folder": str(tmp_path / "collections")},
        "auth": {"type": "htpasswd", "htpasswd_filename": str(users), "htpasswd_encryption": "plain", "delay": "0"},
        "rights": {"type": "owner_only"},
        "logging": {"level": "error"},
    }, "test", privileged=True)
    srv = make_server("127.0.0.1", 0, radicale.Application(conf), server_class=_Server, handler_class=_Quiet)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    url = f"http://127.0.0.1:{srv.server_port}/"
    yield url
    srv.shutdown()
    srv.server_close()


@pytest.fixture
def dav(server):
    """Direct caldav-library access, standing in for 'a phone editing iCloud'."""
    principal = caldav.DAVClient(url=server, username=USER, password=PASSWORD, enable_rfc6764=False).principal()
    return principal


class RecordingClient(TestClient):
    """Remembers every response body so we can prove the password never leaks."""
    bodies: list[str]

    def request(self, *args, **kwargs):
        r = super().request(*args, **kwargs)
        self.bodies.append(r.text)
        return r


@pytest.fixture
def db_file(tmp_path):
    return str(tmp_path / "test.db")


def make_client(db_file, tmp_path, **kw):
    app = create_app(db_path=db_file, demo=False, static_dir=tmp_path / "no-dist", **kw)
    c = RecordingClient(app)
    c.bodies = []
    return c


@pytest.fixture
def client(db_file, tmp_path):
    with make_client(db_file, tmp_path) as c:
        assert c.patch("/api/settings", json={"pin": PIN}).status_code == 200
        c.people = {n: c.post("/api/people", json={"name": n, "color": col, "role": role}).json()["id"]
                    for n, col, role in [("Alex", "#4F7CEC", "adult"), ("Jordan", "#9B6BE0", "adult"),
                                         ("Mia", "#F0679A", "child")]}
        yield c
        for b in c.bodies:
            assert PASSWORD not in b


def ics(uid, summary, start, end, extra="", tzid="Europe/London"):
    def dt(name, v):
        if len(v) == 8:
            return f"{name};VALUE=DATE:{v}"
        if v.endswith("Z") or not tzid:
            return f"{name}:{v}"
        return f"{name};TZID={tzid}:{v}"
    return "\r\n".join([
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Test//EN", "BEGIN:VEVENT", f"UID:{uid}",
        "DTSTAMP:20261001T000000Z", dt("DTSTART", start), dt("DTEND", end), f"SUMMARY:{summary}",
        *([extra] if extra else []), "END:VEVENT", "END:VCALENDAR", ""])


def connect(client, server):
    r = client.post("/api/accounts", json={"kind": "caldav", "server_url": server, "username": USER,
                                           "password": PASSWORD, "pin": PIN})
    assert r.status_code == 200, r.text
    acct = r.json()
    assert "password" not in acct
    return acct


def sync(client, acct):
    r = client.post(f"/api/accounts/{acct['id']}/sync")
    assert r.status_code == 200, r.text
    return r.json()


def events(client, start="2026-10-01", end="2026-11-01"):
    r = client.get(f"/api/events?start={start}&end={end}")
    assert r.status_code == 200, r.text
    return r.json()


def by_title(evs, title):
    return [e for e in evs if e["title"] == title]


# ---------------------------------------------------------------- tests

def test_connect_discover_and_initial_sync(client, server, dav):
    fam = dav.make_calendar(name="Family", cal_id="family")
    alex = dav.make_calendar(name="Alex", cal_id="alex")
    fam.save_event(ics("f1", "Dinner at Gran's", "20261012T180000", "20261012T200000", "LOCATION:Gran's"))
    fam.save_event(ics("f2", "Half term", "20261026", "20261031"))
    alex.save_event(ics("a1", "NY call", "20261013T090000", "20261013T100000", tzid="America/New_York"))
    alex.save_event(ics("a2", "UTC thing", "20261014T120000Z", "20261014T130000Z"))

    # Wrong password is refused and nothing is stored.
    bad = client.post("/api/accounts", json={"kind": "caldav", "server_url": server, "username": USER,
                                             "password": "nope", "pin": PIN})
    assert bad.status_code == 400
    assert client.post("/api/accounts", json={"kind": "caldav", "server_url": server, "username": USER,
                                              "password": PASSWORD, "pin": "0000"}).status_code == 403
    assert client.get("/api/accounts").json() == []

    acct = connect(client, server)
    assert acct["status"] == "ok" and acct["calendar_count"] == 2 and acct["kind"] == "caldav"
    cals = {c["name"]: c for c in client.get("/api/calendars").json()}
    p = client.people
    assert set(cals["Family"]["person_ids"]) == set(p.values())          # "Family" -> everyone
    assert cals["Alex"]["person_ids"] == [p["Alex"]]                    # name match
    assert cals["Alex"]["visible"] and not cals["Alex"]["read_only"]

    assert events(client) == []  # nothing until the first sync
    acct = sync(client, acct)
    assert acct["status"] == "ok" and acct["last_sync"]
    evs = events(client)
    dinner = by_title(evs, "Dinner at Gran's")[0]
    assert (dinner["start"], dinner["end"], dinner["location"]) == ("2026-10-12T18:00", "2026-10-12T20:00", "Gran's")
    assert set(dinner["person_ids"]) == set(p.values())
    assert dinner["source"] == "caldav" and dinner["calendar_id"] == cals["Family"]["id"]
    ht = by_title(evs, "Half term")[0]
    assert (ht["all_day"], ht["start"], ht["end"]) == (True, "2026-10-26T00:00", "2026-10-31T00:00")
    ny = by_title(evs, "NY call")[0]
    assert (ny["start"], ny["end"], ny["person_ids"]) == ("2026-10-13T14:00", "2026-10-13T15:00", [p["Alex"]])
    assert by_title(evs, "UTC thing")[0]["start"] == "2026-10-14T13:00"  # BST

    # Mapping and visibility changes apply immediately.
    r = client.patch(f"/api/calendars/{cals['Alex']['id']}", json={"person_ids": [p["Jordan"]], "color": "#112233"})
    assert r.status_code == 200 and r.json()["color"] == "#112233"
    assert by_title(events(client), "NY call")[0]["person_ids"] == [p["Jordan"]]
    client.patch(f"/api/calendars/{cals['Alex']['id']}", json={"visible": False})
    assert by_title(events(client), "NY call") == []
    assert by_title(events(client), "Dinner at Gran's")

    # Household timezone change re-derives local times.
    assert client.patch("/api/settings", json={"pin": PIN, "timezone": "America/New_York"}).status_code == 200
    assert by_title(events(client), "Dinner at Gran's")[0]["start"] == "2026-10-12T13:00"
    assert client.patch("/api/settings", json={"pin": PIN, "timezone": "Mars/Base"}).status_code == 400

    status = client.get("/api/sync/status").json()
    assert status["needs_reconnect"] is False and status["accounts"][0]["status"] == "ok"

    assert client.request("DELETE", f"/api/accounts/{acct['id']}", json={"pin": "0000"}).status_code == 403
    assert client.request("DELETE", f"/api/accounts/{acct['id']}", json={"pin": PIN}).json() == {"ok": True}
    assert events(client) == [] and client.get("/api/calendars").json() == []


def test_incremental_sync(client, server, dav, monkeypatch):
    fam = dav.make_calendar(name="Family", cal_id="family")
    other = dav.make_calendar(name="Work", cal_id="work")
    fam.save_event(ics("e1", "Swim", "20261010T090000", "20261010T100000"))
    fam.save_event(ics("e2", "Dentist", "20261011T090000", "20261011T100000"))
    other.save_event(ics("w1", "Offsite", "20261015T090000", "20261015T170000"))
    acct = connect(client, server)
    sync(client, acct)
    assert {e["title"] for e in events(client)} == {"Swim", "Dentist", "Offsite"}
    swim_id = by_title(events(client), "Swim")[0]["id"]

    calls = {"etags": [], "multiget": []}
    real_etags, real_multiget = caldav_sync.Remote.list_etags, caldav_sync.Remote.multiget

    def spy_etags(self, url):
        calls["etags"].append(url)
        return real_etags(self, url)

    def spy_multiget(self, url, urls):
        calls["multiget"].append(list(urls))
        return real_multiget(self, url, urls)

    monkeypatch.setattr(caldav_sync.Remote, "list_etags", spy_etags)
    monkeypatch.setattr(caldav_sync.Remote, "multiget", spy_multiget)

    sync(client, acct)  # nothing changed: ctags match, no listing, no downloads
    assert calls == {"etags": [], "multiget": []}

    # A phone edits one event, deletes another and adds a third, all in Family.
    swim = fam.event_by_uid("e1")
    swim.data = ics("e1", "Swim lesson", "20261010T093000", "20261010T103000")
    swim.save()
    fam.event_by_uid("e2").delete()
    fam.save_event(ics("e3", "Party", "20261017T140000", "20261017T160000"))
    sync(client, acct)
    assert len(calls["etags"]) == 1 and "family" in calls["etags"][0]   # Work untouched
    assert len(calls["multiget"]) == 1 and len(calls["multiget"][0]) == 2  # only changed + new
    evs = events(client)
    assert {e["title"] for e in evs} == {"Swim lesson", "Party", "Offsite"}
    swim = by_title(evs, "Swim lesson")[0]
    assert swim["id"] == swim_id and swim["start"] == "2026-10-10T09:30"

    # A calendar deleted on the server disappears with its events.
    other.delete()
    sync(client, acct)
    assert {e["title"] for e in events(client)} == {"Swim lesson", "Party"}
    assert [c["name"] for c in client.get("/api/calendars").json()] == ["Family"]


def test_recurrence_simple_and_custom(client, server, dav):
    fam = dav.make_calendar(name="Family", cal_id="family")
    # Simple: maps onto Moonlight's repeat model.
    fam.save_event(ics("s1", "Football", "20261005T170000", "20261005T180000",
                       "RRULE:FREQ=WEEKLY;BYDAY=MO,WE;UNTIL=20261014T225959Z"))
    # Custom: COUNT + EXDATE + a moved, renamed occurrence (RECURRENCE-ID override).
    master = ics("c1", "Piano", "20261006T160000", "20261006T163000",
                 "RRULE:FREQ=WEEKLY;COUNT=4\r\nEXDATE;TZID=Europe/London:20261013T160000")
    override = "\r\n".join([
        "BEGIN:VEVENT", "UID:c1", "DTSTAMP:20261001T000000Z",
        "RECURRENCE-ID;TZID=Europe/London:20261020T160000",
        "DTSTART;TZID=Europe/London:20261021T170000", "DTEND;TZID=Europe/London:20261021T173000",
        "SUMMARY:Piano (moved)", "END:VEVENT"])
    fam.save_event(master.replace("END:VCALENDAR", override + "\r\nEND:VCALENDAR"))
    # Monthly on the 2nd Tuesday (BYDAY with a number) is custom too.
    fam.save_event(ics("m1", "Book club", "20261013T200000", "20261013T210000", "RRULE:FREQ=MONTHLY;BYDAY=2TU"))
    acct = connect(client, server)
    sync(client, acct)

    fb = client.get(f"/api/events/{by_title(events(client), 'Football')[0]['id']}").json()
    assert fb["repeat"] == {"freq": "weekly", "interval": 1, "byday": ["MO", "WE"], "until": "2026-10-14"}
    assert fb["custom_repeat"] is False
    assert [o["start"] for o in by_title(events(client), "Football")] == [
        "2026-10-05T17:00", "2026-10-07T17:00", "2026-10-12T17:00", "2026-10-14T17:00"]

    piano = [o for o in events(client, "2026-10-01", "2026-12-01") if o["title"].startswith("Piano")]
    assert [(o["title"], o["start"], o["end"]) for o in piano] == [
        ("Piano", "2026-10-06T16:00", "2026-10-06T16:30"),
        ("Piano (moved)", "2026-10-21T17:00", "2026-10-21T17:30"),
        ("Piano", "2026-10-27T16:00", "2026-10-27T16:30"),
    ]
    assert all(o["recurring"] and o["custom_repeat"] and o["repeat"] is None for o in piano)
    assert piano[1]["occurrence_id"].endswith("@2026-10-21")
    # Windowed queries only return what overlaps.
    assert [o["start"] for o in events(client, "2026-10-21", "2026-10-22") if o["title"].startswith("Piano")] == [
        "2026-10-21T17:00"]
    assert [o["start"] for o in events(client, "2026-10-01", "2027-01-01") if o["title"] == "Book club"] == [
        "2026-10-13T20:00", "2026-11-10T20:00", "2026-12-08T20:00"]

    # Editing the title of a custom series keeps its EXDATE/override on the server.
    pid = piano[0]["id"]
    r = client.patch(f"/api/events/{pid}", json={"title": "Piano lesson"})
    assert r.status_code == 200, r.text
    data = fam.event_by_uid("c1").data
    assert "EXDATE" in data and "RECURRENCE-ID" in data and "SUMMARY:Piano lesson" in data
    assert [o["title"] for o in events(client, "2026-10-01", "2026-12-01") if o["id"] == pid] == [
        "Piano lesson", "Piano (moved)", "Piano lesson"]


def test_write_back_create_update_delete(client, server, dav, db_file):
    fam = dav.make_calendar(name="Family", cal_id="family")
    alex_cal = dav.make_calendar(name="Alex", cal_id="alex")
    dav.make_calendar(name="Leo", cal_id="leo")  # nobody called Leo -> unmapped
    mia_cal = dav.make_calendar(name="Mia", cal_id="mia")
    acct = connect(client, server)
    sync(client, acct)
    p = client.people
    cals = {c["name"]: c for c in client.get("/api/calendars").json()}

    # Default target: first writable calendar mapped to the first selected person (Alex -> "Alex").
    r = client.post("/api/events", json={"title": "Gym", "person_ids": [p["Alex"]], "start": "2026-10-12T07:00",
                                         "end": "2026-10-12T08:00", "location": "Leisure centre",
                                         "repeat": {"freq": "weekly", "interval": 1, "byday": ["MO"],
                                                    "until": "2026-10-26"}})
    assert r.status_code == 200, r.text
    gym = r.json()
    assert gym["calendar_id"] == cals["Alex"]["id"] and gym["source"] == "caldav"
    assert gym["repeat"]["until"] == "2026-10-26"
    remote = alex_cal.events()
    assert len(remote) == 1
    data = remote[0].data
    assert "SUMMARY:Gym" in data and "TZID=Europe/London" in data and "RRULE:FREQ=WEEKLY" in data
    assert "X-MOONLIGHT-PEOPLE" not in data  # people == calendar mapping
    assert len(by_title(events(client), "Gym")) == 3

    # The person's own calendar wins over shared ones ("Mia" sorts after "Family").
    r = client.post("/api/events", json={"title": "Ballet", "person_ids": [p["Mia"]], "start": "2026-10-13T17:00",
                                         "end": "2026-10-13T18:00"})
    assert r.json()["calendar_id"] == cals["Mia"]["id"] and len(mia_cal.events()) == 1

    # Explicit calendar; people differing from the mapping are kept in the event.
    r = client.post("/api/events", json={"title": "Parents' evening", "person_ids": [p["Mia"]],
                                         "calendar_id": cals["Family"]["id"], "all_day": True,
                                         "start": "2026-10-15T00:00", "end": "2026-10-16T00:00"})
    assert r.status_code == 200, r.text
    pe = r.json()
    assert pe["person_ids"] == [p["Mia"]] and pe["all_day"]
    assert "X-MOONLIGHT-PEOPLE:" + p["Mia"] in fam.event_by_uid(fam.events()[0].icalendar_component["UID"]).data
    assert "DTSTART;VALUE=DATE:20261015" in fam.events()[0].data

    # calendar_id null -> local-only (Mia would otherwise default to Family, mapped to everyone).
    local = client.post("/api/events", json={"title": "Local", "person_ids": [p["Mia"]], "calendar_id": None,
                                             "start": "2026-10-12T10:00", "end": "2026-10-12T11:00"}).json()
    assert local["calendar_id"] is None and local["source"] is None

    # Update goes to the server; the next sync is a no-op for it.
    r = client.patch(f"/api/events/{gym['id']}", json={"title": "Gym class", "start": "2026-10-12T07:30",
                                                       "end": "2026-10-12T08:30"})
    assert r.status_code == 200, r.text
    assert "SUMMARY:Gym class" in alex_cal.events()[0].data
    sync(client, acct)
    assert [o["start"] for o in by_title(events(client), "Gym class")] == [
        "2026-10-12T07:30", "2026-10-19T07:30", "2026-10-26T07:30"]

    # Move to another calendar, and a local event into a synced one.
    r = client.patch(f"/api/events/{gym['id']}", json={"calendar_id": cals["Family"]["id"]})
    assert r.status_code == 200, r.text
    assert r.json()["calendar_id"] == cals["Family"]["id"] and r.json()["id"] == gym["id"]
    assert alex_cal.events() == [] and len(fam.events()) == 2
    r = client.patch(f"/api/events/{local['id']}", json={"calendar_id": cals["Leo"]["id"]})
    assert r.status_code == 200 and r.json()["source"] == "caldav"

    # Delete.
    assert client.delete(f"/api/events/{gym['id']}").json() == {"ok": True}
    assert len(fam.events()) == 1
    assert by_title(events(client), "Gym class") == []
    sync(client, acct)
    assert {e["title"] for e in events(client)} == {"Parents' evening", "Local", "Ballet"}

    # Read-only calendars can't be targeted.
    with sqlite3.connect(db_file) as conn:
        conn.execute("UPDATE calendars SET read_only = 1 WHERE name = 'Leo'")
    r = client.post("/api/events", json={"title": "X", "person_ids": [], "calendar_id": cals["Leo"]["id"],
                                         "start": "2026-10-12T10:00", "end": "2026-10-12T11:00"})
    assert r.status_code == 400 and "read-only" in r.json()["detail"]


def test_etag_conflict_returns_409(client, server, dav):
    fam = dav.make_calendar(name="Family", cal_id="family")
    fam.save_event(ics("e1", "Swim", "20261010T090000", "20261010T100000"))
    fam.save_event(ics("e2", "Dentist", "20261011T090000", "20261011T100000"))
    acct = connect(client, server)
    sync(client, acct)
    swim = by_title(events(client), "Swim")[0]
    dentist = by_title(events(client), "Dentist")[0]

    # A phone edits both before Moonlight's next poll.
    ev = fam.event_by_uid("e1")
    ev.data = ics("e1", "Swim (phone)", "20261010T090000", "20261010T100000")
    ev.save()
    ev = fam.event_by_uid("e2")
    ev.data = ics("e2", "Dentist (phone)", "20261011T090000", "20261011T100000")
    ev.save()

    r = client.patch(f"/api/events/{swim['id']}", json={"title": "Swim (wall)"})
    assert r.status_code == 409
    assert "changed on another device" in r.json()["detail"]
    assert "Swim (phone)" in fam.event_by_uid("e1").data  # phone edit not clobbered
    assert client.get(f"/api/events/{swim['id']}").json()["title"] == "Swim (phone)"  # re-fetched
    # Retrying now works (fresh ETag).
    assert client.patch(f"/api/events/{swim['id']}", json={"title": "Swim (wall)"}).status_code == 200
    assert "Swim (wall)" in fam.event_by_uid("e1").data

    r = client.delete(f"/api/events/{dentist['id']}")
    assert r.status_code == 409
    assert "Dentist (phone)" in fam.event_by_uid("e2").data

    # Deleted on the phone, then edited on the wall.
    fam.event_by_uid("e2").delete()
    r = client.patch(f"/api/events/{dentist['id']}", json={"title": "Dentist (wall)"})
    assert r.status_code == 409 and "deleted on another device" in r.json()["detail"]
    assert client.get(f"/api/events/{dentist['id']}").status_code == 404


def test_auth_failure_marks_account_and_reconnect(client, server, dav, db_file):
    dav.make_calendar(name="Family", cal_id="family").save_event(
        ics("e1", "Swim", "20261010T090000", "20261010T100000"))
    acct = connect(client, server)
    sync(client, acct)
    # The app-specific password gets revoked.
    with sqlite3.connect(db_file) as conn:
        conn.execute("UPDATE accounts SET password = 'revoked'")
    acct = sync(client, acct)
    assert acct["status"] == "auth_failed" and "Reconnect" in acct["last_error"]
    assert client.get("/api/sync/status").json()["needs_reconnect"] is True
    assert by_title(events(client), "Swim")  # cached events stay on screen

    # Writes fail clearly too.
    swim = by_title(events(client), "Swim")[0]
    r = client.patch(f"/api/events/{swim['id']}", json={"title": "Nope"})
    assert r.status_code == 502 and "Reconnect" in r.json()["detail"]

    # Reconnect: wrong password refused, right one restores ok.
    assert client.patch(f"/api/accounts/{acct['id']}", json={"pin": PIN, "password": "still-wrong"}).status_code == 400
    r = client.patch(f"/api/accounts/{acct['id']}", json={"pin": PIN, "password": PASSWORD})
    assert r.status_code == 200 and r.json()["status"] == "ok"
    assert sync(client, acct)["status"] == "ok"
    assert all(PASSWORD not in b for b in client.bodies)


def test_background_loop_syncs(db_file, tmp_path, server, dav, monkeypatch):
    monkeypatch.setenv("MOONLIGHT_SYNC_SECONDS", "1")
    dav.make_calendar(name="Family", cal_id="family").save_event(
        ics("e1", "Swim", "20261010T090000", "20261010T100000"))
    with make_client(db_file, tmp_path, sync=True) as c:
        assert c.get("/api/sync/status").json()["running"] is True
        c.patch("/api/settings", json={"pin": PIN})
        connect(c, server)
        deadline = time.time() + 10
        while time.time() < deadline and not events(c):
            time.sleep(0.2)
        assert [e["title"] for e in events(c)] == ["Swim"]
        # A later phone edit arrives on the next poll.
        dav.calendar(cal_id="family").save_event(ics("e2", "Dentist", "20261011T090000", "20261011T100000"))
        deadline = time.time() + 10
        while time.time() < deadline and len(events(c)) < 2:
            time.sleep(0.2)
        assert {e["title"] for e in events(c)} == {"Swim", "Dentist"}
        for b in c.bodies:
            assert PASSWORD not in b
    assert caldav_sync.manager is None


def test_network_blips_are_retried_before_showing_an_error(client, server, dav, monkeypatch, no_retry_waits):
    dav.make_calendar(name="Family", cal_id="family").save_event(
        ics("e1", "Swim", "20261010T090000", "20261010T100000"))
    acct = connect(client, server)
    real = caldav_sync.Remote.list_calendars
    blips = {"left": 2}

    def flaky(self, home):
        if blips["left"]:
            blips["left"] -= 1
            return self._call(lambda: (_ for _ in ()).throw(ConnectionError("reset by peer")))
        return real(self, home)

    monkeypatch.setattr(caldav_sync.Remote, "list_calendars", flaky)
    # Two blips in a row: retried quietly, and the sync still succeeds.
    assert sync(client, acct)["status"] == "ok"
    assert no_retry_waits == list(caldav_sync.RETRY_WAITS)

    # Still unreachable after every retry: now it's shown.
    blips["left"] = len(caldav_sync.RETRY_WAITS) + 1
    r = client.post(f"/api/accounts/{acct['id']}/sync").json()
    assert r["status"] == "error" and "Couldn't reach" in r["last_error"] and "ConnectionError" in r["last_error"]
    assert sync(client, acct)["status"] == "ok"


def test_a_save_whose_reply_was_lost_is_not_a_conflict(client, server, dav, monkeypatch):
    alex_cal = dav.make_calendar(name="Alex", cal_id="alex")
    acct = connect(client, server)
    sync(client, acct)
    p = client.people
    ev = client.post("/api/events", json={"title": "Gym", "person_ids": [p["Alex"]], "start": "2026-10-12T07:00",
                                          "end": "2026-10-12T08:00"}).json()
    real_put = caldav_sync.Remote.put
    lose = {"n": 1}

    def put_then_drop(self, url, ics, etag=None, create=False):
        out = real_put(self, url, ics, etag, create)
        if lose["n"]:
            lose["n"] -= 1
            raise caldav_sync.Unreachable("Couldn't reach the server: ConnectionError")
        return out

    monkeypatch.setattr(caldav_sync.Remote, "put", put_then_drop)
    # The change reached the server but its reply was lost: still a success.
    r = client.patch(f"/api/events/{ev['id']}", json={"title": "Gym class"})
    assert r.status_code == 200, r.text
    assert r.json()["title"] == "Gym class" and "SUMMARY:Gym class" in alex_cal.events()[0].data

    # A retry of a save that already landed (stale etag) isn't "changed on another device" either.
    with sqlite3.connect(caldav_sync.db.db_path()) as c:
        c.execute("UPDATE events SET etag = '\"stale\"' WHERE id = ?", (ev["id"],))
    r = client.patch(f"/api/events/{ev['id']}", json={"title": "Gym class"})
    assert r.status_code == 200, r.text
    # A real change made elsewhere still is.
    with sqlite3.connect(caldav_sync.db.db_path()) as c:
        c.execute("UPDATE events SET etag = '\"stale\"' WHERE id = ?", (ev["id"],))
    r = client.patch(f"/api/events/{ev['id']}", json={"title": "Swimming"})
    assert r.status_code == 409

    # A new event whose reply was lost isn't created twice when it did land.
    lose["n"] = 1
    r = client.post("/api/events", json={"title": "Dentist", "person_ids": [p["Alex"]], "start": "2026-10-14T09:00",
                                         "end": "2026-10-14T10:00"})
    assert r.status_code == 200, r.text
    assert sum("SUMMARY:Dentist" in e.data for e in alex_cal.events()) == 1


def test_skip_public_holidays_round_trips_through_caldav(client, server, dav):
    alex_cal = dav.make_calendar(name="Alex", cal_id="alex")
    acct = connect(client, server)
    sync(client, acct)
    client.patch("/api/settings", json={"pin": PIN, "holidays": {"country": "GB", "subdiv": "ENG"}})
    r = client.post("/api/events", json={
        "title": "School run", "person_ids": [client.people["Alex"]], "start": "2026-12-21T08:30",
        "end": "2026-12-21T09:00", "repeat": {"freq": "weekly", "byday": ["MO", "TU", "WE", "TH", "FR"],
                                               "skip_holidays": True}})
    assert r.status_code == 200, r.text
    data = alex_cal.events()[0].data
    assert "X-MOONLIGHT-SKIP-HOLIDAYS:1" in data and "EXDATE" in data and "20261225T083000" in data
    days = [e["start"][:10] for e in events(client, "2026-12-21", "2027-01-02") if e["title"] == "School run"]
    assert days == ["2026-12-21", "2026-12-22", "2026-12-23", "2026-12-24", "2026-12-29", "2026-12-30", "2026-12-31"]
    sync(client, acct)  # read back from the server: still a simple, editable repeat
    ev = by_title(events(client, "2026-12-21", "2026-12-22"), "School run")[0]
    assert ev["custom_repeat"] is False and ev["repeat"]["skip_holidays"] is True
