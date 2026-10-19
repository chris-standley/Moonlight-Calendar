"""Security (alarm, Alarmo's sensors, cameras) against a fake Home Assistant: REST via httpx.MockTransport, the
WebSocket commands via a small in-memory fake. Run from backend/ with `python -m pytest`."""
from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from moonlight import home_security  # noqa: E402
from moonlight.main import create_app  # noqa: E402

TOKEN = "supervisor-secret"
PIN = "1234"
JPEG = b"\xff\xd8\xff\xe0" + b"frame" * 20


def st(eid, state, **attrs):
    return {"entity_id": eid, "state": state, "attributes": attrs, "last_changed": "2026-10-19T08:00:00+00:00"}


def ha_states():
    return [
        st("alarm_control_panel.alarm", "disarmed", friendly_name="Alarm", arm_mode=None, open_sensors=None,
           changed_by="Chris", next_state="disarmed"),
        st("alarm_control_panel.dream_machine_pro_alarm_manager", "disarmed", friendly_name="Dream Machine Pro Alarm Manager"),
        st("binary_sensor.front_door", "off", friendly_name="Alarm Panel front_door", device_class="door"),
        st("binary_sensor.side_door", "on", friendly_name="Alarm Panel side_door", device_class="door"),
        st("binary_sensor.lounge", "off", friendly_name="Alarm Panel lounge", device_class="motion"),
        st("binary_sensor.study", "on", friendly_name="Alarm Panel study", device_class="motion"),
        st("binary_sensor.kitchen_window", "unavailable", friendly_name="Kitchen Window open", device_class="window"),
        st("binary_sensor.e_niro_trunk", "off", friendly_name="E-NIRO Trunk", device_class="door"),
        st("camera.driveway", "recording", friendly_name="Driveway High resolution channel", width=3840, height=2160,
           attribution="Powered by UniFi Protect Server", supported_features=2),
        st("camera.driveway_medium", "recording", friendly_name="Driveway Medium resolution channel",
           attribution="Powered by UniFi Protect Server", supported_features=2),
        st("camera.front_doorbell", "recording", friendly_name="Doorbell", width=1600, height=1200,
           attribution="Powered by UniFi Protect Server", supported_features=2),
        st("camera.printer", "unavailable", friendly_name="P1S Camera"),
        st("binary_sensor.driveway_person_detected", "off", friendly_name="Driveway Person detected"),
        st("binary_sensor.front_door_person_detected", "off", friendly_name="Front Doorbell Person detected"),
        st("light.kitchen", "on", friendly_name="Kitchen"),
    ]


REGISTRY = {"entity_categories": {}, "entities": [
    {"ei": "camera.driveway", "pl": "unifiprotect", "di": "dev_drive"},
    {"ei": "camera.driveway_medium", "pl": "unifiprotect", "di": "dev_drive"},
    {"ei": "camera.front_doorbell", "pl": "unifiprotect", "di": "dev_bell"},
    {"ei": "camera.printer", "pl": "bambu_lab", "di": "dev_printer"},
    {"ei": "binary_sensor.driveway_person_detected", "pl": "unifiprotect", "di": "dev_drive"},
    {"ei": "binary_sensor.front_door_person_detected", "pl": "unifiprotect", "di": "dev_bell"},
]}

ALARMO = {
    "binary_sensor.front_door": {"type": "door", "modes": ["armed_away", "armed_home"], "enabled": True},
    "binary_sensor.side_door": {"type": "door", "modes": ["armed_away"], "enabled": True},
    "binary_sensor.lounge": {"type": "motion", "modes": ["armed_away"], "enabled": True},
    "binary_sensor.study": {"type": "motion", "modes": ["armed_away"], "enabled": False},
    "binary_sensor.kitchen_window": {"type": "window", "modes": ["armed_away", "armed_home"], "enabled": True},
}


class FakeHA:
    def __init__(self):
        self.states = {s["entity_id"]: s for s in ha_states()}
        self.requests: list[httpx.Request] = []
        self.down = False
        self.hls_tokens = {"camera.driveway_medium": "abc123", "camera.driveway": "hd999", "camera.front_doorbell": "bell456"}

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.down:
            raise httpx.ConnectError("connection refused", request=request)
        if request.headers.get("authorization") != f"Bearer {TOKEN}":
            return httpx.Response(401)
        path = request.url.path
        if path == "/core/api/states":
            return httpx.Response(200, json=list(self.states.values()))
        if path.startswith("/core/api/hls/"):
            token, rest = path[len("/core/api/hls/"):].split("/", 1)
            if token not in self.hls_tokens.values():
                return httpx.Response(404)
            if rest == "master_playlist.m3u8":
                return httpx.Response(200, text="#EXTM3U\nplaylist.m3u8\n",
                                      headers={"content-type": "application/vnd.apple.mpegurl"})
            return httpx.Response(200, content=b"m4s:" + rest.encode() + b"?" + request.url.query,
                                  headers={"content-type": "video/iso.segment"})
        if path.startswith("/core/api/camera_proxy/"):
            if path.rsplit("/", 1)[1] not in self.states:
                return httpx.Response(404)
            return httpx.Response(200, content=JPEG, headers={"content-type": "image/jpeg"})
        return httpx.Response(404)


class FakeWS:
    """Answers auth and the registry / Alarmo commands; `alarmo=None` = Alarmo isn't installed."""

    def __init__(self, alarmo=ALARMO, fail=False, ha=None):
        self.ha = ha
        self.alarmo = alarmo
        self.fail = fail
        self.sent: list[dict] = []

    def __call__(self, url):
        if self.fail:
            raise OSError("no websocket")
        fake = self

        class Conn:
            def __init__(self):
                self.out: asyncio.Queue = asyncio.Queue()
                self.out.put_nowait({"type": "auth_required"})

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def send(self, raw):
                msg = json.loads(raw)
                fake.sent.append(msg)
                if msg["type"] == "auth":
                    ok = msg["access_token"] == TOKEN
                    self.out.put_nowait({"type": "auth_ok" if ok else "auth_invalid"})
                elif msg["type"] == "config/entity_registry/list_for_display":
                    self.out.put_nowait({"id": msg["id"], "type": "result", "success": True, "result": REGISTRY})
                elif msg["type"] == "alarmo/sensors":
                    if fake.alarmo is None:
                        self.out.put_nowait({"id": msg["id"], "type": "result", "success": False,
                                             "error": {"code": "unknown_command", "message": "Unknown command."}})
                    else:
                        self.out.put_nowait({"id": msg["id"], "type": "result", "success": True, "result": fake.alarmo})
                elif msg["type"] == "camera/stream":
                    token = (fake.ha.hls_tokens if fake.ha else {}).get(msg["entity_id"])
                    if token:
                        self.out.put_nowait({"id": msg["id"], "type": "result", "success": True,
                                             "result": {"url": f"/api/hls/{token}/master_playlist.m3u8"}})
                    else:
                        self.out.put_nowait({"id": msg["id"], "type": "result", "success": False,
                                             "error": {"code": "start_stream_failed", "message": "no stream"}})
                elif msg["type"] == "subscribe_trigger":
                    self.out.put_nowait({"id": msg["id"], "type": "result", "success": True})

            async def recv(self):
                return json.dumps(await self.out.get())

            async def close(self):
                pass

        return Conn()


def make_service(fake, ws=None):
    return home_security.SecurityService("http://supervisor/core/api", TOKEN, transport=httpx.MockTransport(fake.handler),
                                         ws_connect=ws or FakeWS(ha=fake))


@pytest.fixture
def fake():
    return FakeHA()


@pytest.fixture
def client(tmp_path, fake, monkeypatch):
    monkeypatch.setattr(home_security, "STATES_TTL", 0)  # every read sees the fake's latest states
    home_security.reset()
    svc = make_service(fake)
    svc.start = lambda: None  # no live watcher in these tests: every read goes to REST
    home_security.set_service(svc)
    app = create_app(db_path=str(tmp_path / "t.db"), demo=False, auth_enabled=False)
    c = TestClient(app)
    c.patch("/api/settings", json={"pin": PIN})
    yield c
    home_security.reset()


# ---------------------------------------------------------------- discovery

def test_discover_pairs_cameras_with_person_sensors():
    found = home_security.discover(ha_states(), REGISTRY["entities"], ALARMO)
    cams = {c["entity_id"]: c for c in found["cameras"]}
    assert cams["camera.driveway"]["name"] == "Driveway" and cams["camera.driveway"]["default_show"]
    assert cams["camera.driveway"]["default_person"] == "binary_sensor.driveway_person_detected"
    # Renamed in HA ("Doorbell") while its sensor is "Front Doorbell Person detected": matched through the device.
    assert cams["camera.front_doorbell"]["default_person"] == "binary_sensor.front_door_person_detected"
    assert not cams["camera.driveway_medium"]["default_show"]  # the same camera's lower channel
    assert not cams["camera.printer"]["default_show"]  # not Protect
    assert [p["entity_id"] for p in found["panels"]][0] == "alarm_control_panel.alarm"  # Alarmo's panel first
    assert set(found["alarmo_sensors"]) == {"binary_sensor.front_door", "binary_sensor.side_door",
                                            "binary_sensor.lounge", "binary_sensor.kitchen_window"}


def test_discover_without_registry_matches_by_name():
    found = home_security.discover(ha_states(), None, None)
    cams = {c["entity_id"]: c for c in found["cameras"]}
    assert cams["camera.driveway"]["default_person"] == "binary_sensor.driveway_person_detected"
    assert cams["camera.front_doorbell"]["default_person"] == ""
    assert found["alarmo_sensors"] is None


def test_tidy_names():
    names = home_security.tidy_names({"a": "Alarm Panel front_door", "b": "Alarm Panel side_door",
                                      "c": "Alarm Panel lounge", "d": "Kitchen Window open"})
    assert names == {"a": "Front door", "b": "Side door", "c": "lounge", "d": "Kitchen Window open"}


# ---------------------------------------------------------------- overview

def test_overview(client, fake):
    r = client.get("/api/security").json()
    assert r["configured"] and r["reachable"] and r["sensors_source"] == "alarmo"
    assert r["alarm"]["entity_id"] == "alarm_control_panel.alarm" and r["alarm"]["label"] == "Disarmed"
    assert r["alarm"]["changed_by"] == "Chris" and r["alarm"]["alarmo"] is True and not r["alarm"]["armed"]
    sensors = {s["entity_id"]: s for s in r["sensors"]}
    assert set(sensors) == {"binary_sensor.front_door", "binary_sensor.side_door", "binary_sensor.lounge",
                            "binary_sensor.kitchen_window"}  # Alarmo's enabled ones only: no car, no disabled study
    assert sensors["binary_sensor.side_door"]["label"] == "Open" and sensors["binary_sensor.side_door"]["active"]
    assert sensors["binary_sensor.front_door"]["label"] == "Closed"
    assert sensors["binary_sensor.lounge"]["label"] == "Clear" and sensors["binary_sensor.lounge"]["group"] == "motion"
    assert sensors["binary_sensor.kitchen_window"]["label"] == "Unavailable"
    assert sensors["binary_sensor.side_door"]["name"] == "Side door"
    assert [s["group"] for s in r["sensors"]][:2] == ["doors", "doors"] and r["sensors"][0]["entity_id"] == "binary_sensor.side_door"
    assert [c["entity_id"] for c in r["cameras"]] == ["camera.front_doorbell", "camera.driveway"]
    assert r["cameras"][1]["live_url"] == "/api/security/cameras/camera.driveway/live"
    assert r["alerts"] == []
    assert TOKEN not in json.dumps(r)


def test_armed_and_person_alert(client, fake):
    fake.states["alarm_control_panel.alarm"]["state"] = "armed_home"
    fake.states["binary_sensor.driveway_person_detected"]["state"] = "on"
    r = client.get("/api/security").json()
    assert r["alarm"]["armed"] and r["alarm"]["label"] == "Armed home"
    guards = {s["entity_id"]: s["armed"] for s in r["sensors"]}
    assert guards["binary_sensor.front_door"] and not guards["binary_sensor.lounge"]  # lounge only guards "away"
    assert [a["camera"] for a in r["alerts"]] == ["camera.driveway"] and r["alerts"][0]["name"] == "Driveway"
    assert client.get("/api/security/alerts").json()[0]["live_url"] == "/api/security/cameras/camera.driveway/live"


def test_open_sensors_blocking_arming(client, fake):
    fake.states["alarm_control_panel.alarm"]["attributes"]["open_sensors"] = {"binary_sensor.side_door": "on"}
    assert client.get("/api/security").json()["alarm"]["open_sensors"] == ["Side door"]


def test_without_alarmo(tmp_path, fake):
    home_security.reset()
    home_security.set_service(make_service(fake, FakeWS(alarmo=None)))
    c = TestClient(create_app(db_path=str(tmp_path / "n.db"), demo=False, auth_enabled=False))
    r = c.get("/api/security").json()
    assert r["sensors_source"] == "none" and r["sensors"] == [] and r["alarm"]["label"] == "Disarmed"
    assert len(r["cameras"]) == 2
    home_security.reset()


def test_websocket_down_still_shows_cameras(tmp_path, fake):
    home_security.reset()
    home_security.set_service(make_service(fake, FakeWS(fail=True)))
    c = TestClient(create_app(db_path=str(tmp_path / "w.db"), demo=False, auth_enabled=False))
    r = c.get("/api/security").json()
    assert r["sensors"] == [] and [x["entity_id"] for x in r["cameras"]] == ["camera.front_doorbell", "camera.driveway"]
    home_security.reset()


def test_ha_unreachable(client, fake):
    fake.down = True
    r = client.get("/api/security").json()
    assert r["configured"] and not r["reachable"] and r["error"]
    assert client.get("/api/security/options").status_code == 502


def test_no_home_assistant(tmp_path, monkeypatch):
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    monkeypatch.delenv("MOONLIGHT_HA_TOKEN", raising=False)
    home_security.reset()
    c = TestClient(create_app(db_path=str(tmp_path / "x.db"), demo=False, auth_enabled=False))
    r = c.get("/api/security").json()
    assert r["configured"] is False and r["cameras"] == []
    assert c.get("/api/security/alerts").json() == []
    assert c.get("/api/security/options").status_code == 409
    home_security.reset()


# ---------------------------------------------------------------- settings

def test_options_and_settings(client, fake):
    o = client.get("/api/security/options").json()
    assert o["alarm_entity"] == "alarm_control_panel.alarm" and o["sensor_count"] == 4
    assert o["popup"] == {"large": True, "compact": True, "phone": False, "tv": False}
    assert {p["entity_id"] for p in o["person_sensors"]} == {"binary_sensor.driveway_person_detected",
                                                             "binary_sensor.front_door_person_detected"}
    r = client.patch("/api/settings", json={"pin": PIN, "security": {
        "alarm_entity": "", "popup": {"compact": False, "tv": True},
        "cameras": {"camera.driveway": {"show": False}, "camera.printer": {"show": True, "person": ""},
                    "camera.front_doorbell": {"person": "binary_sensor.driveway_person_detected"}}}})
    assert r.status_code == 200, r.text
    assert r.json()["security"]["popup"] == {"large": True, "compact": False, "phone": False, "tv": True}
    s = client.get("/api/security").json()
    assert s["alarm"] is None and s["sensors"] and [c["entity_id"] for c in s["cameras"]] == ["camera.front_doorbell", "camera.printer"]
    fake.states["binary_sensor.driveway_person_detected"]["state"] = "on"
    assert [a["camera"] for a in client.get("/api/security/alerts").json()] == ["camera.front_doorbell"]
    # Back to automatic.
    client.patch("/api/settings", json={"pin": PIN, "security": {"alarm_entity": None,
                                                                 "cameras": {"camera.front_doorbell": {"person": None}}}})
    o = client.get("/api/security/options").json()
    bell = next(c for c in o["cameras"] if c["entity_id"] == "camera.front_doorbell")
    assert o["alarm_entity"] == "alarm_control_panel.alarm" and bell["auto_person"]
    assert bell["person"] == "binary_sensor.front_door_person_detected"


@pytest.mark.parametrize("security", [
    "on", {"alarm_entity": "light.kitchen"}, {"cameras": {"light.kitchen": {"show": True}}},
    {"cameras": {"camera.driveway": {"show": "yes"}}}, {"cameras": {"camera.driveway": {"person": "light.x"}}},
    {"popup": {"attic": True}}, {"popup": {"large": "yes"}},
])
def test_bad_settings(client, security):
    assert client.patch("/api/settings", json={"pin": PIN, "security": security}).status_code == 400


def test_settings_need_the_pin(client):
    assert client.patch("/api/settings", json={"pin": "0000", "security": {"alarm_entity": ""}}).status_code == 403


# ---------------------------------------------------------------- pictures

def test_snapshot_only_for_shown_cameras(client, fake):
    r = client.get("/api/security/cameras/camera.driveway/snapshot?width=640")
    assert r.status_code == 200 and r.content == JPEG and r.headers["content-type"] == "image/jpeg"
    req = [q for q in fake.requests if q.url.path.startswith("/core/api/camera_proxy/")][-1]
    assert req.url.params["width"] == "640" and req.url.params["height"] == "360"  # both, or HA won't resize
    for other in ("camera.printer", "camera.driveway_medium", "light.kitchen", "camera.nope"):
        assert client.get(f"/api/security/cameras/{other}/snapshot").status_code == 404
        assert client.get(f"/api/security/cameras/{other}/live").status_code == 404


def test_live_feed_is_mjpeg(fake):
    svc = make_service(fake)

    async def first_frames():
        await svc.config()
        out = []
        async for chunk in svc.mjpeg("camera.driveway", 640, max_seconds=0.3, frame_seconds=0.05):
            out.append(chunk)
        return out

    frames = asyncio.run(first_frames())
    assert frames and frames[0].startswith(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: ")
    assert JPEG in frames[0] and svc.streams == 0
    # Screens watching the same camera at once share snapshots.
    fetches = [q for q in fake.requests if q.url.path.startswith("/core/api/camera_proxy/")]
    assert len(fetches) <= len(frames)


def test_live_route_streams(client, monkeypatch):
    # The test client reads the whole answer, so keep the feed short.
    monkeypatch.setattr(home_security, "STREAM_MAX_SECONDS", 1)
    with client.stream("GET", "/api/security/cameras/camera.driveway/live?width=480") as r:
        assert r.status_code == 200 and r.headers["content-type"].startswith("multipart/x-mixed-replace")
        first = next(r.iter_bytes())
        assert first.startswith(b"--frame")


def test_test_alert(client):
    assert client.post("/api/security/test-alert", json={"pin": "0000", "camera": "camera.driveway"}).status_code == 403
    assert client.post("/api/security/test-alert", json={"pin": PIN, "camera": "camera.printer"}).status_code == 404
    r = client.post("/api/security/test-alert", json={"pin": PIN, "camera": "camera.driveway"})
    assert r.status_code == 200
    alerts = client.get("/api/security/alerts").json()
    assert [a["camera"] for a in alerts] == ["camera.driveway"] and alerts[0]["test"] is True


# ---------------------------------------------------------------- menus

def test_security_section_added_once_to_wall_screens(tmp_path):
    from moonlight import db

    path = str(tmp_path / "old.db")
    create_app(db_path=path, demo=False, auth_enabled=False)
    with sqlite3.connect(path) as c:
        c.execute("DELETE FROM settings WHERE key = ?", (db.SECURITY_MARKER,))
        c.execute("INSERT OR REPLACE INTO settings(key, value) VALUES('screens', ?)", (json.dumps(
            {"large": {"start": "calendar", "sections": ["calendar", "lists"]},
             "phone": {"start": "today", "sections": ["today"]}}),))
        c.execute("INSERT INTO displays(id, name, layout, token_hash, created_at, revoked, setup) "
                  "VALUES('ds_1', 'Kitchen', 'compact', 'h1', '2026-10-01', 0, ?)", (json.dumps({"sections": ["today"]}),))
    db.init_db()
    with sqlite3.connect(path) as c:
        screens = json.loads(c.execute("SELECT value FROM settings WHERE key = 'screens'").fetchone()[0])
        assert screens["large"]["sections"] == ["calendar", "lists", "security"]
        assert screens["phone"]["sections"] == ["today"]
        assert json.loads(c.execute("SELECT setup FROM displays").fetchone()[0])["sections"] == ["today", "security"]
        c.execute("UPDATE settings SET value = ? WHERE key = 'screens'",
                  (json.dumps({"large": {"start": "calendar", "sections": ["calendar"]}}),))
    db.init_db()
    with sqlite3.connect(path) as c:
        assert json.loads(c.execute("SELECT value FROM settings WHERE key = 'screens'").fetchone()[0])["large"]["sections"] == ["calendar"]


def test_person_change_broadcasts_an_alert(client, fake, monkeypatch):
    from moonlight import common

    sent = []

    async def broadcast(*topics):
        sent.extend(topics)

    monkeypatch.setattr(common.hub, "broadcast", broadcast)
    asyncio.run(home_security._changed())  # e.g. a door sensor changed: no one at a camera
    assert sent == ["security"]
    fake.states["binary_sensor.front_door_person_detected"]["state"] = "on"
    sent.clear()
    asyncio.run(home_security._changed())
    assert sent == ["security", "security_alert"]
    sent.clear()
    asyncio.run(home_security._changed())  # still there: no new pop-up
    assert sent == ["security"]


# ---------------------------------------------------------------- video

def test_video_passes_through_without_the_token(client, fake):
    cams = {c["entity_id"]: c for c in client.get("/api/security").json()["cameras"]}
    url = cams["camera.driveway"]["video_url"]
    assert url == "/api/security/cameras/camera.driveway/hls/master_playlist.m3u8"
    r = client.get(url)
    assert r.status_code == 200 and "playlist.m3u8" in r.text and "abc123" not in r.text
    assert r.headers["content-type"].startswith("application/vnd.apple.mpegurl")
    # From the lighter medium channel (token abc123), with low-latency HLS's query passed on.
    r = client.get("/api/security/cameras/camera.driveway/hls/segment/12.3.m4s?_HLS_msn=12&_HLS_part=3")
    assert r.content == b"m4s:segment/12.3.m4s?_HLS_msn=12&_HLS_part=3"
    assert any("/hls/abc123/" in q.url.path for q in fake.requests)


def test_full_resolution_video_for_big_screens(client, fake):
    cams = {c["entity_id"]: c for c in client.get("/api/security").json()["cameras"]}
    url = cams["camera.driveway"]["video_hd_url"]
    assert url == "/api/security/cameras/camera.driveway/hd/hls/master_playlist.m3u8"
    assert client.get(url).status_code == 200
    assert any("/hls/hd999/" in q.url.path for q in fake.requests)
    assert not any("/hls/abc123/" in q.url.path for q in fake.requests)
    # A camera with no lighter channel has one stream for both.
    assert cams["camera.front_doorbell"]["video_hd_url"] == cams["camera.front_doorbell"]["video_url"]
    assert client.get("/api/security/cameras/camera.driveway/hd/hls/../states").status_code == 404


def test_video_token_renewed_when_the_stream_restarts(client, fake):
    assert client.get("/api/security/cameras/camera.front_doorbell/hls/master_playlist.m3u8").status_code == 200
    fake.hls_tokens["camera.front_doorbell"] = "new789"
    assert client.get("/api/security/cameras/camera.front_doorbell/hls/playlist.m3u8").status_code == 200


@pytest.mark.parametrize("path", ["../states", "segment/../../states", "x%2F..%2Fstates"])
def test_video_paths_are_checked(client, path):
    assert client.get(f"/api/security/cameras/camera.driveway/hls/{path}").status_code == 404


def test_no_video_for_hidden_or_streamless_cameras(client, fake):
    assert client.get("/api/security/cameras/camera.printer/hls/master_playlist.m3u8").status_code == 404
    fake.states["camera.front_doorbell"]["attributes"]["supported_features"] = 0
    svc = home_security.service()
    asyncio.run(svc.discover(force=True))
    cams = {c["entity_id"]: c for c in client.get("/api/security").json()["cameras"]}
    assert cams["camera.front_doorbell"]["video_url"] is None and cams["camera.front_doorbell"]["video_hd_url"] is None
    assert client.get("/api/security/cameras/camera.front_doorbell/hls/master_playlist.m3u8").status_code == 404
