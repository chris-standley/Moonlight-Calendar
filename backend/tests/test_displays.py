"""Screen pairing and the auth middleware: run from backend/ with `python -m pytest`."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from moonlight.main import create_app  # noqa: E402

PIN = "4321"
INGRESS_IP = "172.30.32.2"
INGRESS = {"X-Ingress-Path": "/api/hassio_ingress/abc123", "X-Remote-User-Display-Name": "Chris"}


# ---------------------------------------------------------------- auth on

@pytest.fixture
def app_on(tmp_path):
    return create_app(db_path=str(tmp_path / "t.db"), demo=False, static_dir=tmp_path / "no-dist", auth_enabled=True)


@pytest.fixture
def ha(app_on):
    """A Home Assistant user arriving through ingress."""
    c = TestClient(app_on, client=(INGRESS_IP, 40000), headers=INGRESS)
    assert c.patch("/api/settings", json={"pin": PIN}).status_code == 200
    return c


def lan(app, **kw):
    return TestClient(app, client=("192.168.1.50", 51000), **kw)


def pair(ha_client, screen, name="Kitchen", layout="kitchen"):
    start = screen.post("/api/pair/start", json={"layout": layout}).json()
    r = ha_client.post("/api/displays/approve", json={"code": start["code"], "name": name, "pin": PIN})
    assert r.status_code == 200, r.text
    r = screen.get(f"/api/pair/{start['pair_id']}")
    assert r.json()["status"] == "approved"
    return r.json()["token"], r.json()["display"]


def test_unpaired_lan_is_locked_out(app_on, ha):
    s = lan(app_on)
    assert s.get("/api/people").status_code == 401
    assert s.get("/api/people").json()["pairing"] is True
    assert s.post("/api/events", json={}).status_code == 401
    assert s.get("/api/health").status_code == 200
    assert s.get("/api/auth/status").json() == {"required": True, "authorised": False, "via": None, "display": None}
    # HTML still served so the pairing screen can load.
    assert s.get("/display/kitchen").status_code == 200
    # Faking the ingress header from the LAN, or the ingress IP without the header, is not enough.
    assert s.get("/api/people", headers=INGRESS).status_code == 401
    assert TestClient(app_on, client=(INGRESS_IP, 1)).get("/api/people").status_code == 401
    # A made-up token is rejected.
    assert s.get("/api/people", headers={"Authorization": "Bearer mlt_nope"}).status_code == 401
    with pytest.raises(WebSocketDisconnect):
        with s.websocket_connect("/api/ws") as ws:
            ws.receive_json()


def test_ingress_allowed(ha):
    assert ha.get("/api/people").status_code == 200
    st = ha.get("/api/auth/status").json()
    assert st["authorised"] and st["via"] == "ingress"
    with ha.websocket_connect("/api/ws") as ws:
        assert ws.receive_json()["type"] == "hello"


def test_pairing_flow(app_on, ha):
    screen = lan(app_on)
    start = screen.post("/api/pair/start", json={"layout": "kitchen"}).json()
    assert len(start["code"]) == 6 and start["code"].isdigit() and start["expires_in"] == 600
    assert screen.get(f"/api/pair/{start['pair_id']}").json()["status"] == "pending"
    assert screen.get("/api/pair/not-a-real-id").json() == {"status": "expired"}

    # Approving needs an authorised session, the right PIN and a waiting code.
    assert lan(app_on).post("/api/displays/approve", json={"code": start["code"], "pin": PIN}).status_code == 401
    assert ha.post("/api/displays/approve", json={"code": start["code"], "pin": "0000"}).status_code == 403
    bad_code = "000000" if start["code"] != "000000" else "111111"
    assert ha.post("/api/displays/approve", json={"code": bad_code, "pin": PIN}).status_code == 404
    assert ha.post("/api/displays/approve", json={"code": "12ab", "pin": PIN}).status_code == 400
    r = ha.post("/api/displays/approve", json={"code": start["code"], "name": "Kitchen", "pin": PIN})
    assert r.status_code == 200
    d = r.json()
    assert d["name"] == "Kitchen" and d["layout"] == "compact" and d["revoked"] is False

    r = screen.get(f"/api/pair/{start['pair_id']}")
    body = r.json()
    assert body["status"] == "approved" and body["token"].startswith("mlt_") and body["display"]["id"] == d["id"]
    sc = r.headers["set-cookie"]
    assert "moonlight_display=" in sc and "HttpOnly" in sc and "Max-Age=" in sc
    # Handed out once only.
    assert screen.get(f"/api/pair/{start['pair_id']}").json()["status"] == "expired"
    # The cookie now opens the API, and the screen shows up with last_seen.
    assert screen.get("/api/people").status_code == 200
    st = screen.get("/api/auth/status").json()
    assert st["via"] == "display" and st["display"]["name"] == "Kitchen"
    listed = screen.get("/api/displays").json()
    assert [x["id"] for x in listed] == [d["id"]] and listed[0]["current"] is True and listed[0]["last_seen"]
    assert ha.get("/api/displays").json()[0]["current"] is False
    # The token is stored hashed.
    import sqlite3
    from moonlight import db
    raw = sqlite3.connect(db.db_path()).execute("SELECT token_hash FROM displays").fetchone()[0]
    assert body["token"] not in raw


def test_token_bearer_query_and_websocket(app_on, ha):
    token, _ = pair(ha, lan(app_on))
    assert lan(app_on, headers={"Authorization": f"Bearer {token}"}).get("/api/people").status_code == 200
    # ?token= on the first page load (TouchKio) sets the long-lived cookie.
    fresh = lan(app_on)
    r = fresh.get(f"/display/kitchen?token={token}")
    assert r.status_code == 200 and "moonlight_display=" in r.headers.get("set-cookie", "")
    assert fresh.get("/api/people").status_code == 200
    # Bearer without cookie also (re)sets it.
    r = lan(app_on).get("/api/people", headers={"Authorization": f"Bearer {token}"})
    assert "moonlight_display=" in r.headers.get("set-cookie", "")
    with lan(app_on).websocket_connect(f"/api/ws?token={token}") as ws:
        assert ws.receive_json()["type"] == "hello"


def test_service_pairing_home_assistant(app_on, ha):
    """The HA integration pairs as a non-screen "service" client with a suggested name, then uses a Bearer token."""
    hass = lan(app_on)
    st = hass.get("/api/auth/status").json()
    assert st["required"] is True and st["authorised"] is False
    start = hass.post("/api/pair/start", json={"layout": "service", "name": "Home Assistant"}).json()
    assert start["layout"] == "service"
    # The approver can't turn it into a screen; a blank name falls back to the suggested one.
    r = ha.post("/api/displays/approve", json={"code": start["code"], "name": "", "layout": "kitchen", "pin": PIN})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["layout"] == "service" and d["name"] == "Home Assistant"
    token = hass.get(f"/api/pair/{start['pair_id']}").json()["token"]
    client = lan(app_on, headers={"Authorization": f"Bearer {token}"})
    assert client.get("/api/summary").status_code == 200
    assert client.get("/api/auth/status").json()["authorised"] is True
    with lan(app_on).websocket_connect("/api/ws", headers={"Authorization": f"Bearer {token}"}) as ws:
        assert ws.receive_json()["type"] == "hello"
    assert [x["layout"] for x in ha.get("/api/displays").json()] == ["service"]
    # Revoking it locks the integration out again (it then re-pairs via a reauth flow).
    assert ha.request("DELETE", f"/api/displays/{d['id']}", json={"pin": PIN}).status_code == 200
    assert client.get("/api/summary").status_code == 401


def test_pair_start_validation(app_on, ha):
    s = lan(app_on)
    assert s.post("/api/pair/start", json={"layout": "toaster"}).status_code == 400
    assert s.post("/api/pair/start", json={"layout": "kitchen", "name": 5}).status_code == 400
    # A screen can't be approved as a service, and a screen's suggested name is used when none is typed.
    start = s.post("/api/pair/start", json={"layout": "hallway", "name": "Landing"}).json()
    assert ha.post("/api/displays/approve",
                   json={"code": start["code"], "layout": "service", "pin": PIN}).status_code == 400
    d = ha.post("/api/displays/approve", json={"code": start["code"], "pin": PIN}).json()
    assert d["layout"] == "large" and d["name"] == "Landing"


def test_revoked_screen_is_rejected(app_on, ha):
    screen = lan(app_on)
    token, d = pair(ha, screen)
    assert screen.get("/api/people").status_code == 200
    assert ha.request("DELETE", f"/api/displays/{d['id']}", json={"pin": "0000"}).status_code == 403
    assert ha.request("DELETE", f"/api/displays/{d['id']}", json={"pin": PIN}).status_code == 200
    r = screen.get("/api/people")
    assert r.status_code == 401
    assert "Max-Age=0" in r.headers.get("set-cookie", "")  # stale cookie cleared
    assert lan(app_on, headers={"Authorization": f"Bearer {token}"}).get("/api/people").status_code == 401
    with pytest.raises(WebSocketDisconnect):
        with lan(app_on).websocket_connect(f"/api/ws?token={token}") as ws:
            ws.receive_json()
    assert ha.get("/api/displays").json() == []
    assert ha.request("DELETE", f"/api/displays/{d['id']}", json={"pin": PIN}).status_code == 404


def test_auth_off_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("MOONLIGHT_AUTH", raising=False)
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    app = create_app(db_path=str(tmp_path / "t.db"), demo=False, static_dir=tmp_path / "x")
    assert lan(app).get("/api/people").status_code == 200
    monkeypatch.setenv("SUPERVISOR_TOKEN", "abc")  # inside the add-on: on unless MOONLIGHT_AUTH=off
    app = create_app(db_path=str(tmp_path / "t.db"), demo=False, static_dir=tmp_path / "x")
    assert lan(app).get("/api/people").status_code == 401
    monkeypatch.setenv("MOONLIGHT_AUTH", "off")
    app = create_app(db_path=str(tmp_path / "t.db"), demo=False, static_dir=tmp_path / "x")
    assert lan(app).get("/api/people").status_code == 200


def test_rename_screen(app_on, ha):
    _, d = pair(ha, lan(app_on), name="Kitchen")
    r = ha.patch(f"/api/displays/{d['id']}", json={"name": "Kitchen wall", "pin": PIN})
    assert r.status_code == 200 and r.json()["name"] == "Kitchen wall"
    assert [x["name"] for x in ha.get("/api/displays").json()] == ["Kitchen wall"]
    assert ha.patch(f"/api/displays/{d['id']}", json={"name": "x", "pin": "0000"}).status_code == 403
    assert ha.patch(f"/api/displays/{d['id']}", json={"name": " ", "pin": PIN}).status_code == 400
    assert ha.patch("/api/displays/nope", json={"name": "x", "pin": PIN}).status_code == 404


def test_one_address_and_per_screen_setup(app_on, ha):
    s = lan(app_on)
    assert s.get("/display").status_code == 200
    token, d = pair(ha, s, name="Landing", layout="large")
    assert d["layout"] == "large" and d["own_setup"] is False
    assert d["setup"] == {"start": "calendar", "sections": ["calendar", "chores", "rewards", "meals", "recipes", "lists",
                                                         "nursery", "security", "energy"],
                          "speaker": "", "idle_minutes": 5}
    auth = {"Authorization": f"Bearer {token}"}
    me = s.get("/api/auth/status", headers=auth).json()["display"]
    assert me["name"] == "Landing" and me["current"] and me["setup"]["start"] == "calendar"

    # Its own setup: other screens of the same style keep following the style.
    _, other = pair(ha, lan(app_on), name="Study", layout="large")
    r = ha.patch(f"/api/displays/{d['id']}", json={"pin": PIN, "setup": {
        "sections": ["meals", "today"], "start": "meals", "speaker": "media_player.landing", "idle_minutes": 10}})
    assert r.status_code == 200, r.text
    assert r.json()["setup"] == {"start": "meals", "sections": ["today", "meals"], "speaker": "media_player.landing",
                                 "idle_minutes": 10} and r.json()["own_setup"] is True
    shown = {x["name"]: x for x in ha.get("/api/displays").json()}
    assert shown["Study"]["setup"]["start"] == "calendar" and shown["Study"]["own_setup"] is False
    # Style settings change the screens that follow them, not the one with its own setup.
    ha.patch("/api/settings", json={"pin": PIN, "screens": {"large": {"start": "chores"}}})
    shown = {x["name"]: x for x in ha.get("/api/displays").json()}
    assert shown["Study"]["setup"]["start"] == "chores" and shown["Landing"]["setup"]["start"] == "meals"

    # Hiding the start section moves the start; a new style keeps its own setup; null follows the style again.
    r = ha.patch(f"/api/displays/{d['id']}", json={"pin": PIN, "setup": {"sections": ["today"]}}).json()
    assert r["setup"]["start"] == "today"
    r = ha.patch(f"/api/displays/{d['id']}", json={"pin": PIN, "layout": "kitchen", "name": "Kitchen"}).json()
    assert (r["layout"], r["name"], r["setup"]["sections"]) == ("compact", "Kitchen", ["today"])
    r = ha.patch(f"/api/displays/{d['id']}", json={"pin": PIN, "setup": None}).json()
    assert r["own_setup"] is False and r["setup"]["start"] == "today" and r["setup"]["idle_minutes"] == 3

    for bad in ({"setup": {"sections": []}}, {"setup": {"start": "settings"}}, {"setup": {"speaker": "light.x"}},
                {"setup": {"idle_minutes": -1}}, {"setup": {"colour": "red"}}, {"setup": []}, {"layout": "tv"}):
        assert ha.patch(f"/api/displays/{d['id']}", json={"pin": PIN, **bad}).status_code == 400, bad
    assert ha.patch(f"/api/displays/{other['id']}", json={"pin": "0000", "layout": "phone"}).status_code == 403


def test_old_style_names_are_renamed(tmp_path):
    import sqlite3

    from moonlight import db

    path = str(tmp_path / "old.db")
    create_app(db_path=path, demo=False, static_dir=tmp_path / "x", auth_enabled=True)
    with sqlite3.connect(path) as c:
        c.execute("INSERT INTO displays(id, name, layout, token_hash, created_at, revoked) "
                  "VALUES('ds_1', 'Hall', 'hallway', 'h1', '2026-10-01', 0), ('ds_2', 'Kit', 'kitchen', 'h2', '2026-10-01', 0)")
        c.execute("INSERT INTO settings(key, value) VALUES('idle_minutes', '{\"hallway\": 9, \"kitchen\": 2, \"phone\": 0}')")
    db.init_db()
    with sqlite3.connect(path) as c:
        assert dict(c.execute("SELECT id, layout FROM displays")) == {"ds_1": "large", "ds_2": "compact"}
        assert c.execute("SELECT value FROM settings WHERE key = 'idle_minutes'").fetchone()[0] == \
            '{"large": 9, "compact": 2, "phone": 0}'


def test_recipes_join_menus_that_show_meals_once(tmp_path):
    import json
    import sqlite3

    from moonlight import db

    path = str(tmp_path / "old.db")
    create_app(db_path=path, demo=False, static_dir=tmp_path / "x", auth_enabled=True)
    with sqlite3.connect(path) as c:
        c.execute("DELETE FROM settings WHERE key = ?", (db.RECIPES_MARKER,))
        c.execute("INSERT OR REPLACE INTO settings(key, value) VALUES('screens', ?)", (json.dumps(
            {"large": {"start": "meals", "sections": ["calendar", "meals", "lists"]},
             "compact": {"start": "today", "sections": ["today", "lists"]}}),))
        c.execute("INSERT INTO displays(id, name, layout, token_hash, created_at, revoked, setup) "
                  "VALUES('ds_1', 'Hall', 'large', 'h1', '2026-10-01', 0, ?)", (json.dumps({"sections": ["meals"]}),))
    db.init_db()
    with sqlite3.connect(path) as c:
        screens = json.loads(c.execute("SELECT value FROM settings WHERE key = 'screens'").fetchone()[0])
        assert screens["large"]["sections"] == ["calendar", "meals", "recipes", "lists"]
        assert screens["compact"]["sections"] == ["today", "lists"]
        assert json.loads(c.execute("SELECT setup FROM displays").fetchone()[0])["sections"] == ["meals", "recipes"]
        # Hiding Recipes later sticks.
        c.execute("UPDATE settings SET value = ? WHERE key = 'screens'",
                  (json.dumps({"large": {"start": "meals", "sections": ["meals"]}}),))
    db.init_db()
    with sqlite3.connect(path) as c:
        assert json.loads(c.execute("SELECT value FROM settings WHERE key = 'screens'").fetchone()[0])["large"]["sections"] == ["meals"]


def test_the_phone_app_is_not_a_screen(app_on, ha):
    phone = lan(app_on)
    start = phone.post("/api/pair/start", json={"layout": "app", "name": "iPhone"}).json()
    assert start["layout"] == "app"
    r = ha.post("/api/displays/approve", json={"code": start["code"], "layout": "large", "pin": PIN})
    d = r.json()
    assert (d["layout"], d["name"]) == ("app", "iPhone")  # the approver can't make it a screen
    assert "setup" not in d
    token = phone.get(f"/api/pair/{start['pair_id']}").json()["token"]
    assert lan(app_on, headers={"Authorization": f"Bearer {token}"}).get("/api/people").status_code == 200
    assert ha.patch(f"/api/displays/{d['id']}", json={"pin": PIN, "layout": "phone"}).status_code == 400
    assert ha.patch(f"/api/displays/{d['id']}", json={"pin": PIN, "name": "Chris's iPhone"}).json()["name"] == "Chris's iPhone"
