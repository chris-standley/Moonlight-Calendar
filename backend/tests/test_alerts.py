"""Notifications and timers from Home Assistant: run from backend/ with `python -m pytest`."""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from moonlight import alerts  # noqa: E402
from moonlight.main import create_app  # noqa: E402

PIN = "4321"
INGRESS = {"X-Ingress-Path": "/api/hassio_ingress/abc123"}


@pytest.fixture
def app(tmp_path):
    return create_app(db_path=str(tmp_path / "t.db"), demo=False, static_dir=tmp_path / "no-dist", auth_enabled=True)


@pytest.fixture
def ha(app):
    c = TestClient(app, client=("172.30.32.2", 40000), headers=INGRESS)
    assert c.patch("/api/settings", json={"pin": PIN}).status_code == 200
    return c


def pair(app, ha, name, layout):
    dev = TestClient(app, client=("192.168.1.50", 51000))
    start = dev.post("/api/pair/start", json={"layout": layout, "name": name}).json()
    assert ha.post("/api/displays/approve", json={"code": start["code"], "name": name, "pin": PIN}).status_code == 200
    token = dev.get(f"/api/pair/{start['pair_id']}").json()["token"]
    return TestClient(app, client=("192.168.1.50", 51000), headers={"Authorization": f"Bearer {token}"})


@pytest.fixture
def devices(app, ha):
    return {
        "kitchen": pair(app, ha, "Kitchen", "compact"),
        "hallway": pair(app, ha, "Hallway", "large"),
        "phone": pair(app, ha, "Chris's iPhone", "app"),
        "hass": pair(app, ha, "Home Assistant", "service"),
    }


def ids(client):
    r = client.get("/api/alerts")
    assert r.status_code == 200, r.text
    return [a["id"] for a in r.json()["alerts"]]


def test_notification_to_all_and_to_one(ha, devices):
    hass = devices["hass"]
    r = hass.post("/api/alerts", json={"title": "Dinner's ready", "message": "Come to the table", "icon": "🍝"})
    assert r.status_code == 200, r.text
    a = r.json()
    assert a["kind"] == "notification" and a["style"] == "fullscreen" and a["screens"] == ["all"]
    assert a["expires_at"] is None and a["dismissible"] is True  # full screen: until dismissed or cleared
    assert "display_ids" not in a
    for d in ("kitchen", "hallway", "phone"):
        assert ids(devices[d]) == [a["id"]]
    assert ids(ha) == [a["id"]]
    assert ids(hass) == [a["id"]]

    r = hass.post("/api/alerts", json={"title": "Washing done", "style": "toast", "screens": ["kitchen"]})
    t = r.json()
    assert t["expires_at"] - t["created_at"] == alerts.TOAST_SECONDS * 1000
    assert ids(devices["kitchen"]) == [a["id"], t["id"]]
    assert ids(devices["hallway"]) == [a["id"]]
    assert ids(ha) == [a["id"]]          # the HA panel isn't a paired screen: only "all" ones
    assert set(ids(hass)) == {a["id"], t["id"]}  # the integration sees every one


def test_targets_by_style_and_errors(devices):
    hass = devices["hass"]
    r = hass.post("/api/alerts", json={"title": "Hi", "screens": ["large", "app"]})
    assert r.status_code == 200, r.text
    assert ids(devices["hallway"]) and ids(devices["phone"]) and not ids(devices["kitchen"])
    r = hass.post("/api/alerts", json={"title": "Hi", "screens": "Kitchen, hallway"})
    assert r.status_code == 200
    r = hass.post("/api/alerts", json={"title": "Hi", "screens": ["Garage"]})
    assert r.status_code == 400 and "Garage" in r.json()["detail"] and "Kitchen" in r.json()["detail"]
    assert "Home Assistant" not in r.json()["detail"]
    assert hass.post("/api/alerts", json={}).status_code == 400
    assert hass.post("/api/alerts", json={"title": "x", "style": "banner"}).status_code == 400
    assert hass.post("/api/alerts", json={"title": "x", "duration": -1}).status_code == 400


def test_timer_and_countdown(devices):
    hass = devices["hass"]
    r = hass.post("/api/alerts", json={"kind": "timer", "label": "Pizza", "description": "Take it out", "duration": 600,
                                       "screens": ["Kitchen"], "finished_for": 120})
    assert r.status_code == 200, r.text
    t = r.json()
    assert t["style"] == "toast" and t["chime"] is True and t["finished"] is False
    assert t["ends_at"] - t["started_at"] == 600_000
    assert t["expires_at"] == t["ends_at"] + 120_000
    assert hass.post("/api/alerts", json={"kind": "timer", "duration": 60}).status_code == 400  # needs a label
    assert hass.post("/api/alerts", json={"kind": "timer", "label": "x"}).status_code == 400
    assert hass.post("/api/alerts", json={"kind": "timer", "label": "x", "duration": 5,
                                          "until": "2030-01-01T00:00"}).status_code == 400
    assert hass.post("/api/alerts", json={"kind": "timer", "label": "x", "until": "2001-01-01T00:00"}).status_code == 400
    soon = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%dT08:00")
    r = hass.post("/api/alerts", json={"kind": "timer", "label": "Holiday", "until": soon, "style": "fullscreen"})
    assert r.status_code == 200, r.text
    c = r.json()
    assert c["expires_at"] is None and c["ends_at"] > c["started_at"]
    # Same id again replaces it.
    r = hass.post("/api/alerts", json={"kind": "timer", "label": "Pizza", "duration": 300, "id": t["id"]})
    assert r.json()["ends_at"] - r.json()["started_at"] == 300_000
    assert ids(hass).count(t["id"]) == 1


def test_count_up_since(devices):
    hass = devices["hass"]
    r = hass.post("/api/alerts", json={"kind": "timer", "label": "Kettle boiled", "since": "now", "icon": "☕",
                                       "screens": ["Kitchen"], "id": "kettle"})
    assert r.status_code == 200, r.text
    k = r.json()
    assert k["count_up"] is True and k["ends_at"] is None and k["expires_at"] is None and k["chime"] is False
    assert abs(k["started_at"] - alerts.now_ms()) < 2000
    assert ids(devices["kitchen"]) == ["kettle"] and ids(devices["hallway"]) == []
    # From a moment in the past, going an hour after it.
    ago = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    r = hass.post("/api/alerts", json={"kind": "timer", "label": "Kettle boiled", "since": ago, "duration": 3600,
                                       "id": "kettle"})
    assert r.status_code == 200, r.text
    k = r.json()
    assert 590_000 < alerts.now_ms() - k["started_at"] < 610_000
    assert k["expires_at"] == k["started_at"] + 3_600_000
    assert ids(devices["hass"]).count("kettle") == 1
    later = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    for bad_body in ({"since": later}, {"since": "soon"}, {"since": "now", "until": later},
                     {"since": ago, "duration": 60}, {"since": "2001-01-01T00:00"}):
        assert hass.post("/api/alerts", json={"kind": "timer", "label": "x", **bad_body}).status_code == 400, bad_body
    # Counting up never finishes.
    sent = []

    async def capture(msg):
        sent.append(msg)

    orig = alerts.hub.send
    alerts.hub.send = capture
    try:
        asyncio.run(alerts.tick(k["started_at"] + 1_000_000))
    finally:
        alerts.hub.send = orig
    assert sent == []


def test_dismiss_clear_and_events(app, devices):
    hass, kitchen = devices["hass"], devices["kitchen"]
    a = hass.post("/api/alerts", json={"title": "Bins", "id": "bins"}).json()
    locked = hass.post("/api/alerts", json={"title": "Alarm on", "dismissible": False}).json()
    with hass.websocket_connect("/api/ws") as ws:
        assert ws.receive_json()["type"] == "hello"
        r = kitchen.post("/api/alerts/bins/dismiss")
        assert r.status_code == 200
        assert ws.receive_json() == {"type": "changed", "topic": "alerts"}
        assert ws.receive_json() == {"type": "alert", "event": "dismissed", "id": "bins", "kind": "notification",
                                     "title": "Bins", "screen": "Kitchen"}
    assert a["id"] not in ids(devices["hallway"])
    assert kitchen.post("/api/alerts/bins/dismiss").status_code == 404
    assert kitchen.post(f"/api/alerts/{locked['id']}/dismiss").status_code == 409
    assert hass.delete(f"/api/alerts/{locked['id']}").status_code == 200
    assert hass.delete(f"/api/alerts/{locked['id']}").status_code == 404

    hass.post("/api/alerts", json={"title": "One", "screens": ["Kitchen"]})
    hass.post("/api/alerts", json={"title": "Two", "screens": ["Hallway"]})
    hass.post("/api/alerts", json={"title": "Three"})
    r = hass.delete("/api/alerts", params={"screens": ["Hallway"]})
    assert len(r.json()["cleared"]) == 2
    assert len(ids(kitchen)) == 1
    assert len(hass.delete("/api/alerts").json()["cleared"]) == 1


def test_timer_finishes_and_expires(app, devices):
    hass = devices["hass"]
    t = hass.post("/api/alerts", json={"kind": "timer", "label": "Eggs", "duration": 1, "finished_for": 5}).json()
    toast = hass.post("/api/alerts", json={"title": "Hello", "style": "toast", "duration": 1}).json()
    sent = []

    async def capture(msg):
        sent.append(msg)

    async def changed(*topics):
        sent.extend(topics)

    hub = alerts.hub
    orig = hub.send, hub.broadcast
    hub.send, hub.broadcast = capture, changed
    try:
        asyncio.run(alerts.tick(max(t["ends_at"], toast["expires_at"])))
        assert {"type": "alert", "event": "finished", "id": t["id"], "kind": "timer", "title": "Eggs",
                "screen": None} in sent
        assert "alerts" in sent  # the toast's second is up
        assert ids(hass) == [t["id"]]
        sent.clear()
        asyncio.run(alerts.tick(t["ends_at"] + 2000))
        assert sent == []  # announced once
        asyncio.run(alerts.tick(t["expires_at"]))
        assert sent == ["alerts"] and ids(hass) == []
    finally:
        hub.send, hub.broadcast = orig
    assert toast["id"] not in ids(hass)


def test_kept_across_restart(tmp_path, app, devices):
    hass = devices["hass"]
    a = hass.post("/api/alerts", json={"title": "Stays", "dismissible": False}).json()
    again = create_app(db_path=str(tmp_path / "t.db"), demo=False, static_dir=tmp_path / "no-dist", auth_enabled=False)
    assert [x["id"] for x in TestClient(again).get("/api/alerts").json()["alerts"]] == [a["id"]]


def test_unpaired_cannot_post(app):
    assert TestClient(app, client=("192.168.1.9", 1)).post("/api/alerts", json={"title": "x"}).status_code == 401
