"""The add-on announcing itself to Home Assistant through the Supervisor (ha_discovery.py)."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from moonlight import auth, db, ha_discovery  # noqa: E402
from moonlight.main import create_app  # noqa: E402

PIN = "4321"


class FakeSupervisor:
    def __init__(self):
        self.posts: list[dict] = []
        self.fail = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer sup-token"
        if request.url.path == "/addons/self/info":
            return httpx.Response(200, json={"result": "ok", "data": {"hostname": "abc12345-moonlight"}})
        if request.url.path == "/discovery" and request.method == "POST":
            if self.fail:
                self.fail -= 1
                return httpx.Response(503)
            self.posts.append(json.loads(request.content))
            return httpx.Response(200, json={"result": "ok", "data": {"uuid": "u1"}})
        return httpx.Response(404)


@pytest.fixture
def sup(monkeypatch):
    f = FakeSupervisor()
    monkeypatch.setattr(ha_discovery, "transport", httpx.MockTransport(f))
    monkeypatch.setenv("SUPERVISOR_TOKEN", "sup-token")
    monkeypatch.delenv("MOONLIGHT_HA_DISCOVERY", raising=False)
    monkeypatch.setattr(ha_discovery, "_sleep", lambda s: asyncio.sleep(0))
    return f


def test_announce_reuses_token_until_revoked(tmp_path, sup):
    app = create_app(db_path=str(tmp_path / "t.db"), demo=False, static_dir=tmp_path / "x", sync=False,
                     auth_enabled=True)
    with TestClient(app) as ha:
        # Startup announced once (in the background).
        for _ in range(50):
            if sup.posts:
                break
            asyncio.run(asyncio.sleep(0.02))
        [first] = sup.posts
        assert first["service"] == "moonlight"
        assert first["config"]["host"] == "abc12345-moonlight" and first["config"]["port"] == 8091
        token = first["config"]["token"]

        # The token works on the LAN port and shows up as one "Home Assistant" connection.
        lan = TestClient(app, client=("172.30.33.5", 1), headers={"Authorization": f"Bearer {token}"})
        assert lan.get("/api/people").status_code == 200
        with db.connect() as c:
            rows = db.rows(c, "SELECT name, layout FROM displays WHERE revoked = 0")
        assert rows == [{"name": "Home Assistant", "layout": "service"}]

        # Announcing again (next start) keeps the same token.
        assert asyncio.run(ha_discovery.announce()) is True
        assert sup.posts[-1]["config"]["token"] == token
        with db.connect() as c:
            assert c.execute("SELECT COUNT(*) FROM displays").fetchone()[0] == 1
            did = db.row(c, "SELECT id FROM displays")["id"]
            c.execute("UPDATE displays SET revoked = 1 WHERE id = ?", (did,))

        # Once removed, the next announcement offers a new token.
        sup.fail = 1  # and a Supervisor hiccup is retried
        assert asyncio.run(ha_discovery.announce()) is True
        assert sup.posts[-1]["config"]["token"] != token
        assert auth.display_for_token(sup.posts[-1]["config"]["token"])["name"] == "Home Assistant"
        # The token is never part of the settings API.
        assert token not in json.dumps(ha.get("/api/settings", headers={}).json())


def test_no_discovery_outside_the_add_on(tmp_path, sup, monkeypatch):
    monkeypatch.delenv("SUPERVISOR_TOKEN")
    assert asyncio.run(ha_discovery.announce()) is False
    monkeypatch.setenv("SUPERVISOR_TOKEN", "sup-token")
    monkeypatch.setenv("MOONLIGHT_HA_DISCOVERY", "0")
    assert asyncio.run(ha_discovery.announce()) is False
    assert sup.posts == []
