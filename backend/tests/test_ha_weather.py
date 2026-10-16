"""Weather from a (fake) Home Assistant: run from backend/ with `python -m pytest`."""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from datetime import date, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from moonlight import ha_client  # noqa: E402
from moonlight.main import create_app  # noqa: E402

TODAY = date(2026, 10, 10)
ENTITY = "weather.home"


def ha_state(unit="°C", temp=14.6, state="partlycloudy"):
    return {"entity_id": ENTITY, "state": state,
            "attributes": {"temperature": temp, "temperature_unit": unit, "friendly_name": "Home"}}


def ha_forecast(n=12, start=TODAY - timedelta(days=1), high=15.4, low=7.6, cond="rainy"):
    # Daily entries at local midnight in Europe/London (BST) expressed in UTC, like many integrations.
    return {"changed_states": [], "service_response": {ENTITY: {"forecast": [
        {"datetime": f"{(start + timedelta(days=i - 1)).isoformat()}T23:00:00+00:00",
         "temperature": high + i, "templow": low, "condition": "snowy-rainy" if i == 2 else cond,
         **({"precipitation_probability": 64.6} if i == 1 else {})}
        for i in range(n)]}}}


class FakeHA:
    """Counts requests, checks auth, answers like HA's REST API."""

    def __init__(self, state=None, forecast=None, fail=False):
        self.state = state or ha_state()
        self.forecast = forecast or ha_forecast()
        self.fail = fail
        self.calls: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(f"{request.method} {request.url.path}?{request.url.query.decode()}")
        if self.fail:
            return httpx.Response(502, json={"message": "Bad gateway"})
        if request.headers.get("authorization") != "Bearer tok":
            return httpx.Response(401, json={"message": "Unauthorized"})
        if request.method == "GET" and request.url.path == "/core/api/states":
            return httpx.Response(200, json=[
                self.state,
                {"entity_id": "weather.forecast_garden", "state": "unavailable", "attributes": {"friendly_name": "Garden"}},
                {"entity_id": "weather.met_office", "state": "rainy",
                 "attributes": {"temperature": 9.04, "temperature_unit": "°C", "friendly_name": "Met Office",
                                "attribution": "Met Office"}},
                {"entity_id": "sensor.outside", "state": "12", "attributes": {}},
            ])
        if request.method == "GET" and request.url.path == f"/core/api/states/{ENTITY}":
            return httpx.Response(200, json=self.state)
        if request.method == "POST" and request.url.path == "/core/api/services/weather/get_forecasts":
            assert "return_response" in request.url.query.decode()
            assert json.loads(request.content) == {"entity_id": ENTITY, "type": "daily"}
            return httpx.Response(200, json=self.forecast)
        return httpx.Response(404, json={"message": "Entity not found."})


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


BST = timezone(timedelta(hours=1))


def make(fake: FakeHA, clock=None) -> ha_client.HAWeather:
    return ha_client.HAWeather(ENTITY, "http://supervisor/core/api", "tok",
                               transport=httpx.MockTransport(fake.handler),
                               clock=clock or Clock(), today=lambda: TODAY, tz=BST)


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _reset_client():
    ha_client.reset()
    yield
    ha_client.reset()


def test_success_shape():
    fake = FakeHA()
    w = run(make(fake).get())
    assert w["unit"] == "C"
    assert w["current"] == {"temp": 14.6, "condition": "partlycloudy"}
    # Yesterday dropped, dates converted to local, 10 days max, unknown conditions mapped.
    assert [d["date"] for d in w["daily"]] == [(TODAY + timedelta(days=i)).isoformat() for i in range(10)]
    assert w["daily"][0]["condition"] == "rainy" and w["daily"][1]["condition"] == "snowy"
    # Chance of rain rounded to a whole percent; missing stays null.
    assert w["daily"][0]["rain"] == 65 and w["daily"][1]["rain"] is None
    assert len(fake.calls) == 2


def test_get_weather_converts_and_rounds():
    fake = FakeHA()
    ha_client.set_client(make(fake))
    c = run(ha_client.get_weather("C"))
    assert c["source"] == "homeassistant" and c["entity"] == ENTITY and c["unit"] == "C"
    assert c["current"]["temp"] == 15
    assert c["daily"][0] == {"date": TODAY.isoformat(), "high": 16, "low": 8, "condition": "rainy", "rain": 65}
    f = run(ha_client.get_weather("F"))
    assert f["unit"] == "F" and f["current"]["temp"] == 58      # 14.6 C = 58.3 F
    assert f["daily"][0]["high"] == 62 and f["daily"][0]["low"] == 46  # 16.4 C, 7.6 C


def test_fahrenheit_entity_to_celsius():
    fake = FakeHA(state=ha_state(unit="°F", temp=59), forecast=ha_forecast(high=50, low=32))
    ha_client.set_client(make(fake))
    w = run(ha_client.get_weather("C"))
    assert w["current"]["temp"] == 15
    assert w["daily"][0]["low"] == 0 and w["daily"][0]["high"] == 11  # 51 F
    assert run(ha_client.get_weather("F"))["current"]["temp"] == 59


def test_cache_ten_minutes():
    fake, clock = FakeHA(), Clock()
    client = make(fake, clock)
    run(client.get())
    clock.t += 599
    run(client.get())
    assert client.fetches == 1
    clock.t += 2
    run(client.get())
    assert client.fetches == 2 and len(fake.calls) == 4


def test_error_falls_back_to_demo_and_logs_once(caplog):
    fake, clock = FakeHA(fail=True), Clock()
    ha_client.set_client(make(fake, clock))
    with caplog.at_level(logging.WARNING, logger="moonlight.ha"):
        w = run(ha_client.get_weather("C"))
        assert w["source"] == "demo" and len(w["daily"]) == 10
        clock.t += 61  # past the retry back-off: tries again, still failing
        run(ha_client.get_weather("C"))
    assert len(fake.calls) == 2
    assert sum("Couldn't read weather" in r.getMessage() for r in caplog.records) == 1


def test_unavailable_entity_and_stale_cache():
    fake, clock = FakeHA(), Clock()
    client = make(fake, clock)
    first = run(client.get())
    fake.state = ha_state(state="unavailable")
    clock.t += 700
    assert run(client.get()) == first          # HA hiccup: keep the last good forecast for a while
    clock.t += 3600
    assert run(client.get()) is None            # too old: caller shows demo weather


def test_no_entity_is_demo(monkeypatch):
    monkeypatch.delenv("MOONLIGHT_WEATHER_ENTITY", raising=False)
    assert ha_client.client() is None
    ha_client.reset()
    monkeypatch.setenv("MOONLIGHT_WEATHER_ENTITY", "weather.home")
    monkeypatch.setenv("MOONLIGHT_HA_URL", "http://ha.local:8123/api")
    monkeypatch.setenv("MOONLIGHT_HA_TOKEN", "abc")
    c = ha_client.client()
    assert c.entity == "weather.home" and c.base_url == "http://ha.local:8123/api" and c.token == "abc"


def test_weather_endpoint_uses_ha_and_settings_unit(tmp_path):
    fake = FakeHA()
    app = create_app(db_path=str(tmp_path / "w.db"), demo=False, static_dir=tmp_path / "none")
    ha_client.set_client(make(fake))
    with TestClient(app) as c:
        assert c.get("/api/weather").json()["unit"] == "C"
        assert c.patch("/api/settings", json={"pin": "1111", "temp_unit": "F"}).status_code == 200
        w = c.get("/api/weather").json()
        assert w["source"] == "homeassistant" and w["unit"] == "F" and w["current"]["temp"] == 58
    ha_client.set_client(None)
    with TestClient(app) as c:
        w = c.get("/api/weather").json()
        assert w["source"] == "demo" and w["entity"] is None and w["unit"] == "F"


def test_weather_entities_and_choosing_one(tmp_path, monkeypatch):
    monkeypatch.delenv("MOONLIGHT_WEATHER_ENTITY", raising=False)
    monkeypatch.setenv("SUPERVISOR_TOKEN", "tok")
    monkeypatch.delenv("MOONLIGHT_HA_TOKEN", raising=False)
    monkeypatch.delenv("MOONLIGHT_HA_URL", raising=False)
    fake = FakeHA()
    ha_client.set_transport(httpx.MockTransport(fake.handler))
    app = create_app(db_path=str(tmp_path / "e.db"), demo=False, static_dir=tmp_path / "none", auth_enabled=False)
    with TestClient(app) as c:
        ents = c.get("/api/weather/entities").json()
        assert [e["entity_id"] for e in ents] == ["weather.home", "weather.met_office", "weather.forecast_garden"]
        assert ents[1] == {"entity_id": "weather.met_office", "name": "Met Office", "available": True,
                           "condition": "rainy", "temperature": 9.0, "unit": "C", "attribution": "Met Office"}
        assert ents[2]["available"] is False and ents[2]["condition"] is None
        # Nothing chosen yet: demo weather.
        assert c.get("/api/settings").json()["weather_entity"] == ""
        assert c.get("/api/weather").json()["source"] == "demo"
        assert c.patch("/api/settings", json={"pin": "1111", "weather_entity": "sensor.outside"}).status_code == 400
        assert c.patch("/api/settings", json={"pin": "1111", "weather_entity": ENTITY}).json()["weather_entity"] == ENTITY
        w = c.get("/api/weather").json()
        assert w["source"] == "homeassistant" and w["entity"] == ENTITY
        assert c.patch("/api/settings", json={"pin": "1111", "weather_entity": None}).json()["weather_entity"] == ""
        assert c.get("/api/weather").json()["source"] == "demo"


def test_weather_entities_without_home_assistant(tmp_path, monkeypatch):
    for k in ("SUPERVISOR_TOKEN", "MOONLIGHT_HA_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    app = create_app(db_path=str(tmp_path / "n.db"), demo=False, static_dir=tmp_path / "none", auth_enabled=False)
    with TestClient(app) as c:
        r = c.get("/api/weather/entities")
        assert r.status_code == 409 and "Home Assistant" in r.json()["detail"]


def test_saved_entity_overrides_env(tmp_path, monkeypatch):
    monkeypatch.setenv("MOONLIGHT_WEATHER_ENTITY", "weather.old")
    app = create_app(db_path=str(tmp_path / "o.db"), demo=False, static_dir=tmp_path / "none", auth_enabled=False)
    with TestClient(app) as c:
        assert c.get("/api/settings").json()["weather_entity"] == "weather.old"
        assert c.patch("/api/settings", json={"pin": "1111", "weather_entity": ""}).json()["weather_entity"] == ""
