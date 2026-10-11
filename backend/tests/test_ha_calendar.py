"""Read-only calendars from Home Assistant calendar entities (ha_calendar.py), against httpx.MockTransport."""
from __future__ import annotations

import asyncio
import sys
from datetime import date
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from moonlight import caldav_sync, ha_calendar, ics_feed  # noqa: E402
from moonlight.main import create_app  # noqa: E402

PIN = "4321"
TODAY = date(2026, 10, 10)

BINS = [
    {"summary": "Recycling", "start": {"date": "2026-10-13"}, "end": {"date": "2026-10-14"},
     "uid": "bins-recycling", "recurrence_id": "20261013", "rrule": "FREQ=WEEKLY;INTERVAL=2"},
    {"summary": "Recycling", "start": {"date": "2026-10-27"}, "end": {"date": "2026-10-28"},
     "uid": "bins-recycling", "recurrence_id": "20261027", "rrule": "FREQ=WEEKLY;INTERVAL=2"},
    {"summary": "General waste", "start": {"date": "2026-10-20"}, "end": {"date": "2026-10-21"},
     "description": "Black bin", "uid": None, "recurrence_id": None, "rrule": None},
]
ENERGY = [
    {"summary": "Free electricity", "start": {"dateTime": "2026-10-18T12:00:00+01:00"},
     "end": {"dateTime": "2026-10-18T14:00:00+01:00"}, "location": "", "uid": "fe-1"},
]


class FakeHA:
    def __init__(self):
        self.calendars = {"calendar.bins": ("Bin collections", BINS), "calendar.energy": ("Energy sessions", ENERGY),
                          "calendar.moonlight_mia": ("Moonlight Mia", [])}
        self.requests: list[httpx.Request] = []
        self.down = False

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.down:
            raise httpx.ConnectError("down")
        assert request.headers["Authorization"] == "Bearer test-token"
        path = request.url.path.removeprefix("/core/api")
        if path == "/calendars":
            return httpx.Response(200, json=[{"entity_id": k, "name": v[0]} for k, v in self.calendars.items()])
        entity = path.removeprefix("/calendars/")
        if entity in self.calendars:
            assert request.url.params["start"].startswith("2026-08-11")
            return httpx.Response(200, json=self.calendars[entity][1])
        return httpx.Response(404, json={"message": "Entity not found"})


@pytest.fixture
def ha(monkeypatch):
    f = FakeHA()
    monkeypatch.setattr(ha_calendar, "transport", httpx.MockTransport(f))
    monkeypatch.setattr(ics_feed, "today", lambda tz: TODAY)
    monkeypatch.setenv("SUPERVISOR_TOKEN", "test-token")
    monkeypatch.delenv("MOONLIGHT_HA_TOKEN", raising=False)
    monkeypatch.delenv("MOONLIGHT_HA_URL", raising=False)
    monkeypatch.delenv("MOONLIGHT_TIMEZONE", raising=False)
    return f


@pytest.fixture
def client(tmp_path, ha):
    app = create_app(db_path=str(tmp_path / "test.db"), demo=False, static_dir=tmp_path / "no-dist", sync=False,
                     auth_enabled=False)
    with TestClient(app) as c:
        assert c.patch("/api/settings", json={"pin": PIN}).status_code == 200
        c.people = {n: c.post("/api/people", json={"name": n, "color": col, "role": "adult"}).json()["id"]
                    for n, col in [("Chris", "#4F7CEC"), ("Sam", "#9B6BE0")]}
        yield c


def cal_events(client, acct):
    cal = next(c for c in client.get("/api/calendars").json() if c["account_id"] == acct["id"])
    evs = client.get("/api/events?start=2026-10-01&end=2026-11-01").json()
    return [e for e in evs if e["calendar_id"] == cal["id"]]


def test_list_add_and_show_ha_calendars(client, ha):
    found = client.get("/api/ha/calendars").json()
    assert [(f["entity_id"], f["name"], f["added"]) for f in found] == [
        ("calendar.bins", "Bin collections", False), ("calendar.energy", "Energy sessions", False)]

    everyone = list(client.people.values())
    r = client.post("/api/accounts", json={"kind": "ha", "entity_id": "calendar.bins", "person_ids": everyone,
                                           "pin": PIN})
    assert r.status_code == 200, r.text
    bins = r.json()
    assert (bins["kind"], bins["label"], bins["server_url"], bins["status"]) == (
        "ha", "Bin collections", "calendar.bins", "ok")
    evs = sorted((e["title"], e["start"], e["all_day"], e["source"]) for e in cal_events(client, bins))
    assert evs == [("General waste", "2026-10-20T00:00", True, "ha"),
                   ("Recycling", "2026-10-13T00:00", True, "ha"),
                   ("Recycling", "2026-10-27T00:00", True, "ha")]
    assert all(e["person_ids"] == everyone for e in cal_events(client, bins))
    cal = next(c for c in client.get("/api/calendars").json() if c["account_id"] == bins["id"])
    assert cal["read_only"] and cal["name"] == "Bin collections"

    energy = client.post("/api/accounts", json={"kind": "ha", "entity_id": "calendar.energy", "label": "Energy",
                                                "person_ids": [], "pin": PIN}).json()
    [fe] = cal_events(client, energy)
    assert (fe["title"], fe["start"], fe["end"], fe["all_day"]) == (
        "Free electricity", "2026-10-18T12:00", "2026-10-18T14:00", False)
    assert [f["added"] for f in client.get("/api/ha/calendars").json()] == [True, True]

    # Events are read-only.
    ev = cal_events(client, bins)[0]
    assert client.patch(f"/api/events/{ev['id']}", json={"title": "x"}).status_code in (400, 403)

    # A poll picks up changes and drops events that went away.
    ha.calendars["calendar.bins"] = ("Bin collections", BINS[:1] + [{**BINS[2], "summary": "Black bin"}])
    assert caldav_sync.sync_account(bins["id"]) is True
    assert sorted(e["title"] for e in cal_events(client, bins)) == ["Black bin", "Recycling"]
    assert caldav_sync.sync_account(bins["id"]) is False

    # Rename, then remove.
    client.patch(f"/api/accounts/{bins['id']}", json={"pin": PIN, "label": "Bins"})
    assert any(c["name"] == "Bins" for c in client.get("/api/calendars").json())
    assert client.request("DELETE", f"/api/accounts/{bins['id']}", json={"pin": PIN}).status_code == 200
    assert not [c for c in client.get("/api/calendars").json() if c["account_id"] == bins["id"]]


def test_ha_calendar_errors(client, ha, monkeypatch):
    add = {"kind": "ha", "person_ids": [], "pin": PIN}
    assert client.post("/api/accounts", json={**add, "entity_id": "sensor.x"}).status_code == 400
    assert client.post("/api/accounts", json={**add, "entity_id": "calendar.nope"}).status_code == 400
    assert client.post("/api/accounts", json={**add, "entity_id": "calendar.bins", "pin": "0000"}).status_code == 403
    acct = client.post("/api/accounts", json={**add, "entity_id": "calendar.bins"}).json()
    assert client.post("/api/accounts", json={**add, "entity_id": "calendar.bins"}).status_code == 400

    ha.down = True
    assert client.get("/api/ha/calendars").status_code == 502
    with pytest.raises(caldav_sync.SyncError):
        caldav_sync.sync_account(acct["id"])
    a = next(a for a in client.get("/api/accounts").json() if a["id"] == acct["id"])
    assert a["status"] == "error" and "Home Assistant" in a["last_error"]
    assert len(cal_events(client, acct)) == 3  # cached events stay

    ha.down = False
    del ha.calendars["calendar.bins"]
    with pytest.raises(caldav_sync.SyncError, match="doesn't have that calendar"):
        caldav_sync.sync_account(acct["id"])

    monkeypatch.delenv("SUPERVISOR_TOKEN")
    assert client.get("/api/ha/calendars").status_code == 409


def test_ha_calendars_poll_on_the_feed_interval(tmp_path, ha, monkeypatch):
    monkeypatch.setenv("MOONLIGHT_FEED_SECONDS", "600")
    app = create_app(db_path=str(tmp_path / "t.db"), demo=False, static_dir=tmp_path / "x", sync=False,
                     auth_enabled=False)
    with TestClient(app) as c:
        c.patch("/api/settings", json={"pin": PIN})
        acct = c.post("/api/accounts", json={"kind": "ha", "entity_id": "calendar.energy", "person_ids": [],
                                             "pin": PIN}).json()
        mgr = caldav_sync.SyncManager(interval=120)
        assert mgr.interval_for(acct["id"]) == 600
        asyncio.run(mgr.sync_one(acct["id"]))
        assert mgr.state[acct["id"]]["fails"] == 0
