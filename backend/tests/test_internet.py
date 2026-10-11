"""Internet access: the HTTPS listener, the home-network-only plain port, brute-force limits, Sign in with HA."""
from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from moonlight.main import create_app  # noqa: E402
from moonlight.routes import ha_login  # noqa: E402

PIN = "4321"
INGRESS = {"X-Ingress-Path": "/api/hassio_ingress/abc123"}


@pytest.fixture
def https_env(monkeypatch):
    monkeypatch.setenv("MOONLIGHT_SSL_CERT", "/ssl/fullchain.pem")
    monkeypatch.setenv("MOONLIGHT_SSL_KEY", "/ssl/privkey.pem")
    monkeypatch.setenv("MOONLIGHT_EXTERNAL_URL", "https://moonlight.example.com")
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    monkeypatch.delenv("MOONLIGHT_HA_LOGIN_URL", raising=False)


def make(tmp_path, auth_enabled=False):
    return create_app(db_path=str(tmp_path / "t.db"), demo=False, static_dir=tmp_path / "x", auth_enabled=auth_enabled)


def web(app, ip="81.2.69.160"):
    """A browser on the internet, through the port forward."""
    return TestClient(app, base_url="https://moonlight.example.com", client=(ip, 50000))


def home(app, ip="192.168.1.50", **kw):
    return TestClient(app, client=(ip, 51000), **kw)


def ha_user(app):
    c = TestClient(app, client=("172.30.32.2", 40000), headers=INGRESS)
    assert c.patch("/api/settings", json={"pin": PIN}).status_code == 200
    return c


def test_https_always_needs_pairing(tmp_path, https_env):
    app = make(tmp_path, auth_enabled=False)  # require_pairing: false only opens the home network
    assert home(app).get("/api/people").status_code == 200
    s = web(app)
    r = s.get("/api/people")
    assert r.status_code == 401
    assert r.headers["strict-transport-security"].startswith("max-age=")
    assert r.headers["x-frame-options"] == "DENY"
    assert s.get("/api/auth/status").json()["required"] is True
    # Ingress headers mean nothing on the internet port, even from the Supervisor's address.
    assert web(app, ip="172.30.32.2").get("/api/people", headers=INGRESS).status_code == 401
    assert s.get("/docs").status_code == 404 and s.get("/openapi.json").status_code == 404
    h = s.get("/api/health").json()
    assert h["external_url"] == "https://moonlight.example.com" and h["ha_login"] is False
    assert "strict-transport-security" in s.get("/display/phone").headers


def test_plain_port_is_home_only_while_https_is_on(tmp_path, https_env):
    app = make(tmp_path, auth_enabled=True)
    assert home(app, ip="81.2.69.160").get("/api/health").status_code == 403
    assert home(app, ip="81.2.69.160").get("/display/kitchen").status_code == 403
    assert home(app, ip="192.168.1.50").get("/api/health").status_code == 200
    assert home(app, ip="fd00::5").get("/api/health").status_code == 200
    assert ha_user(app).get("/api/people").status_code == 200  # ingress still works


def test_plain_port_open_to_all_without_https(tmp_path, monkeypatch):
    monkeypatch.delenv("MOONLIGHT_SSL_CERT", raising=False)
    app = make(tmp_path)
    assert home(app, ip="81.2.69.160").get("/api/health").status_code == 200


def test_pairing_over_https_sets_a_secure_cookie(tmp_path, https_env):
    app = make(tmp_path, auth_enabled=True)
    s = web(app)
    start = s.post("/api/pair/start", json={"layout": "phone"}).json()
    assert ha_user(app).post("/api/displays/approve", json={"code": start["code"], "pin": PIN}).status_code == 200
    r = s.get(f"/api/pair/{start['pair_id']}")
    assert "Secure" in r.headers["set-cookie"]
    assert s.get("/api/people").status_code == 200  # the cookie is enough


def test_wrong_pins_are_limited(tmp_path):
    app = make(tmp_path)
    c = home(app)
    assert c.patch("/api/settings", json={"pin": PIN}).status_code == 200
    for _ in range(10):
        assert c.post("/api/pin/verify", json={"pin": "0000"}).json() == {"ok": False}
    r = c.post("/api/pin/verify", json={"pin": PIN})
    assert r.status_code == 429 and "Retry-After" in r.headers
    assert c.request("DELETE", "/api/displays/x", json={"pin": PIN}).status_code == 429
    # Someone else on another address is not locked out.
    assert home(app, ip="192.168.1.51").post("/api/pin/verify", json={"pin": PIN}).json() == {"ok": True}


def test_pairing_codes_are_limited(tmp_path):
    app = make(tmp_path, auth_enabled=True)
    s = home(app)
    for _ in range(10):
        assert s.post("/api/pair/start", json={"layout": "kitchen"}).status_code == 200
    assert s.post("/api/pair/start", json={"layout": "kitchen"}).status_code == 429
    assert home(app, ip="192.168.1.51").post("/api/pair/start", json={"layout": "kitchen"}).status_code == 200


# ---------------------------------------------------------------- Sign in with Home Assistant

@pytest.fixture
def fake_ha(monkeypatch):
    monkeypatch.setenv("MOONLIGHT_HA_LOGIN_URL", "https://ha.example.com")
    calls = {}

    async def exchange(code, client_id, login_url):
        calls["exchange"] = (code, client_id, login_url)
        if code != "good":
            raise ha_login.HTTPException(status_code=400, detail="Home Assistant didn't accept the sign-in. Try again.")
        return "http://homeassistant:8123", "access", "refresh"

    async def user(base, access):
        return {"id": "u1", "name": "Chris", "is_admin": True}

    async def revoke(base, refresh):
        calls["revoked"] = refresh

    monkeypatch.setattr(ha_login, "exchange_code", exchange)
    monkeypatch.setattr(ha_login, "current_user", user)
    monkeypatch.setattr(ha_login, "revoke", revoke)
    return calls


def _start(client, **params):
    r = client.get("/api/auth/ha/start", params=params, follow_redirects=False)
    assert r.status_code == 302, r.text
    loc = urlsplit(r.headers["location"])
    return loc, {k: v[0] for k, v in parse_qs(loc.query).items()}


def test_sign_in_with_home_assistant(tmp_path, https_env, fake_ha):
    app = make(tmp_path, auth_enabled=True)
    s = web(app)
    assert s.get("/api/health").json()["ha_login"] is True
    loc, q = _start(s, layout="phone")
    assert f"{loc.scheme}://{loc.netloc}{loc.path}" == "https://ha.example.com/auth/authorize"
    assert q["client_id"] == "https://moonlight.example.com/"
    assert q["redirect_uri"] == "https://moonlight.example.com/api/auth/ha/callback"
    r = s.get("/api/auth/ha/callback", params={"state": q["state"], "code": "good"}, follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/display/phone"
    assert "Secure" in r.headers["set-cookie"]
    assert fake_ha["exchange"] == ("good", "https://moonlight.example.com/", "https://ha.example.com")
    assert fake_ha["revoked"] == "refresh"
    assert s.get("/api/people").status_code == 200
    names = [d["name"] for d in ha_user(app).get("/api/displays").json()]
    assert names == ["Chris's phone"]
    # The state is single use.
    assert s.get("/api/auth/ha/callback", params={"state": q["state"], "code": "good"}).status_code == 400


def test_sign_in_for_the_app(tmp_path, https_env, fake_ha):
    app = make(tmp_path, auth_enabled=True)
    s = web(app)
    _, q = _start(s, layout="phone", name="iPhone", app=1)
    r = s.get("/api/auth/ha/callback", params={"state": q["state"], "code": "good"}, follow_redirects=False)
    loc = urlsplit(r.headers["location"])
    assert (loc.scheme, loc.netloc) == ("moonlight", "signed-in")
    token = parse_qs(loc.query)["token"][0]
    assert parse_qs(loc.query)["server"] == ["https://moonlight.example.com"]
    assert web(app).get("/api/people", headers={"Authorization": f"Bearer {token}"}).status_code == 200
    assert [d["name"] for d in ha_user(app).get("/api/displays").json()] == ["Chris's iPhone"]


def test_sign_in_failures(tmp_path, https_env, fake_ha):
    app = make(tmp_path, auth_enabled=True)
    s = web(app)
    assert s.get("/api/auth/ha/callback", params={"state": "made-up", "code": "good"}).status_code == 400
    _, q = _start(s)
    assert s.get("/api/auth/ha/callback", params={"state": q["state"], "code": "bad"}).status_code == 400
    _, q = _start(s)
    assert s.get("/api/auth/ha/callback", params={"state": q["state"], "error": "access_denied"}).status_code == 400
    assert ha_user(app).get("/api/displays").json() == []


def test_sign_in_unavailable_without_ha_address(tmp_path, https_env):
    app = make(tmp_path, auth_enabled=True)
    assert web(app).get("/api/auth/ha/start", follow_redirects=False).status_code == 404
