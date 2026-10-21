"""Energy (solar, battery, grid, car, heat pump) against a fake Home Assistant. Run from backend/ with `python -m pytest`."""
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

from moonlight import energy  # noqa: E402
from moonlight.main import create_app  # noqa: E402

TOKEN = "supervisor-secret"
PIN = "1234"


def st(eid, state, **attrs):
    return {"entity_id": eid, "state": state, "attributes": attrs, "last_changed": "2026-10-21T08:00:00+00:00"}


def W(eid, v, name, unit="W"):
    return st(eid, str(v), unit_of_measurement=unit, device_class="power", friendly_name=name)


def KWH(eid, v, name, unit="kWh"):
    return st(eid, str(v), unit_of_measurement=unit, device_class="energy", friendly_name=name)


def ha_states():
    """Shaped like a real house: a GivEnergy AC inverter (GivTCP), a myenergi zappi, a Kia, a Daikin Altherma with a
    Shelly Pro EM on its supply, and plenty of things that mustn't be picked."""
    return [
        W("sensor.givtcp_inv01_pv_power", 2450, "GivTCP Power PV Power"),
        KWH("sensor.givtcp_inv01_pv_energy_today_kwh", 7.0, "GivTCP Energy PV Energy Today kWh"),
        KWH("sensor.givtcp_inv01_pv_energy_total_kwh", 34733.0, "GivTCP Energy PV Energy Total kWh"),
        W("sensor.givtcp_inv01_battery_power", 1518, "GivTCP Power Battery Power"),
        W("sensor.givtcp_inv01_charge_power", 0, "GivTCP Power Charge Power"),
        st("sensor.givtcp_inv01_soc", "64", unit_of_measurement="%", friendly_name="GivTCP Power SOC"),
        st("number.givtcp_inv01_target_soc", "100", unit_of_measurement="%", friendly_name="GivTCP Control Target SOC"),
        W("sensor.givtcp_inv01_grid_power", 120, "GivTCP Power Grid Power"),  # GivTCP: positive = exporting
        W("sensor.givtcp_inv01_grid_power_inverted", -120, "GivTCP Power Grid Power Inverted"),
        W("sensor.givtcp_inv01_load_power", 3848, "GivTCP Power Load Power"),
        W("sensor.givtcp_power_house_load_3_min_median", 1282, "GivTCP Power House load 3 min median"),
        KWH("sensor.givtcp_inv01_load_energy_today_kwh", 17.5, "GivTCP Energy Load Energy Today kWh"),
        KWH("sensor.givtcp_inv01_import_energy_today_kwh", 12.9, "GivTCP Energy Import Energy Today kWh"),
        KWH("sensor.givtcp_inv01_export_energy_today_kwh", 1.8, "GivTCP Energy Export Energy Today kWh"),
        st("sensor.givtcp_inv01_import_energy_today_kwh_cost", "2.22", unit_of_measurement="GBP"),
        KWH("sensor.predbat_givtcp_0_pv_today", 7.0, "GivTCP 0 PV Energy Today"),
        st("sensor.fairfields_solar_forecast_power_now", "0", unit_of_measurement="W", friendly_name="Solar Forecast Power Now"),
        st("sensor.myenergi_zappi_plug_status", "EV Connected", friendly_name="myenergi Zappi Plug status"),
        st("sensor.myenergi_zappi_status", "Paused", friendly_name="myenergi Zappi Status"),
        W("sensor.myenergi_zappi_power_ct_internal_load", 0, "myenergi Zappi power ct internal load"),
        W("sensor.myenergi_zappi_power_ct_grid", 76, "myenergi Zappi power ct grid"),
        W("sensor.myenergi_eddi_power_ct_internal_load", 0, "Eddi CT internal load"),
        st("sensor.myenergi_eddi_status", "Paused", friendly_name="Eddi status"),
        KWH("sensor.myenergi_zappi_charge_added_session", 0, "myenergi Zappi Charge added session"),
        st("binary_sensor.e_niro_ev_battery_plug", "on", friendly_name="E-NIRO EV Battery Plug"),
        st("sensor.e_niro_ev_battery_level", "50", unit_of_measurement="%", device_class="battery", friendly_name="E-NIRO EV Battery Level"),
        st("sensor.e_niro_car_battery_level", "82", unit_of_measurement="%", friendly_name="E-NIRO Car Battery Level"),
        st("sensor.e_niro_ev_range", "129.0", unit_of_measurement="mi", friendly_name="E-NIRO EV Range"),
        st("sensor.iphone_battery_level", "40", unit_of_measurement="%", device_class="battery", friendly_name="iPhone Battery Level"),
        st("sensor.altherma_operation_type", "Space", friendly_name="EspAltherma Altherma Operation Type"),
        st("select.heat_pump_energy", "Heating", options=["Heating", "Hot Water"],
           friendly_name="shellyproem50-abc Energy Meter 1 Heat Pump Energy"),
        KWH("sensor.heat_pump_energy_heating", 4453.0, "shellyproem50-abc Energy Meter 1 Heat Pump Energy Heating"),
        W("sensor.shellyproem50_abc_em0_power", 1.2, "shellyproem50-abc Energy Meter 0 Power"),
        W("sensor.shellyproem50_abc_em1_power", 774.2, "shellyproem50-abc Energy Meter 1 Power"),
        st("sensor.shellyproem50_abc_em1_apparent_power", "854.5", unit_of_measurement="VA", friendly_name="shellyproem50-abc Energy Meter 1 Apparent power"),
        KWH("sensor.altherma_climatecontrol_heating_daily_electrical_consumption", 4, "Altherma ClimateControl Heating daily electrical consumption"),
        KWH("sensor.altherma_domestichotwatertank_heating_daily_electrical_consumption", 3, "Altherma DomesticHotWaterTank Heating daily electrical consumption"),
        KWH("sensor.altherma_climatecontrol_heating_weekly_electrical_consumption", 7, "Altherma ClimateControl Heating weekly electrical consumption"),
        st("sensor.altherma_climatecontrol_leaving_water_temperature", "28", unit_of_measurement="°C", friendly_name="Altherma ClimateControl Leaving water temperature"),
        st("sensor.altherma_domestichotwatertank_tank_temperature", "45", unit_of_measurement="°C", friendly_name="Altherma DomesticHotWaterTank Tank temperature"),
        st("sensor.altherma_climatecontrol_outdoor_temperature", "9", unit_of_measurement="°C", friendly_name="Altherma ClimateControl Outdoor temperature"),
        st("light.kitchen", "on", friendly_name="Kitchen"),
    ]


PREFS = {
    "energy_sources": [
        {"type": "solar", "stat_energy_from": "sensor.givtcp_inv01_pv_energy_total_kwh", "stat_rate": "sensor.givtcp_inv01_pv_power"},
        {"type": "grid", "stat_energy_from": "sensor.givtcp_inv01_import_energy_total_kwh",
         "power_config": {"stat_rate_inverted": "sensor.givtcp_inv01_grid_power"}, "stat_rate": "sensor.givtcp_inv01_grid_power_inverted"},
        {"type": "battery", "stat_energy_from": "sensor.x", "power_config": {"stat_rate": "sensor.givtcp_inv01_battery_power"},
         "stat_rate": "sensor.givtcp_inv01_battery_power"},
    ],
    "device_consumption": [{"stat_consumption": "sensor.heat_pump_energy_heating", "name": "Heating - Heat Pump"}],
}


class FakeHA:
    def __init__(self):
        self.states = {s["entity_id"]: s for s in ha_states()}

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.headers.get("authorization") != f"Bearer {TOKEN}":
            return httpx.Response(401)
        if request.url.path == "/core/api/states":
            return httpx.Response(200, json=list(self.states.values()))
        return httpx.Response(404)


class FakeWS:
    def __init__(self, prefs=PREFS):
        self.prefs = prefs

    def __call__(self, url):
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
                if msg["type"] == "auth":
                    self.out.put_nowait({"type": "auth_ok"})
                elif msg["type"] == "energy/get_prefs":
                    if fake.prefs is None:
                        self.out.put_nowait({"id": msg["id"], "type": "result", "success": False,
                                             "error": {"code": "not_found", "message": "No prefs"}})
                    else:
                        self.out.put_nowait({"id": msg["id"], "type": "result", "success": True, "result": fake.prefs})

            async def recv(self):
                return json.dumps(await self.out.get())

        return Conn()


@pytest.fixture
def fake():
    return FakeHA()


@pytest.fixture
def client(tmp_path, fake, monkeypatch):
    from moonlight import home_security

    monkeypatch.setattr(home_security, "STATES_TTL", 0)
    energy.reset()
    svc = energy.EnergyService("http://supervisor/core/api", TOKEN, transport=httpx.MockTransport(fake.handler),
                               ws_connect=FakeWS())
    svc.start = lambda: None
    energy.set_service(svc)
    app = create_app(db_path=str(tmp_path / "t.db"), demo=False, auth_enabled=False)
    c = TestClient(app)
    c.patch("/api/settings", json={"pin": PIN})
    yield c
    energy.reset()


# ---------------------------------------------------------------- finding entities

def test_suggest_from_energy_dashboard_and_names():
    auto, flags = energy.suggest(ha_states(), PREFS)
    one = {k: v[0] for k, v in auto.items() if len(v) == 1}
    assert one["solar_power"] == "sensor.givtcp_inv01_pv_power"
    assert one["solar_today"] == "sensor.givtcp_inv01_pv_energy_today_kwh"  # the inverter's, not Predbat's copy
    assert one["battery_power"] == "sensor.givtcp_inv01_battery_power" and flags["battery_invert"] is False
    assert one["battery_soc"] == "sensor.givtcp_inv01_soc"  # not the target, the car or a phone
    assert one["grid_power"] == "sensor.givtcp_inv01_grid_power_inverted" and flags["grid_invert"] is False
    assert one["home_power"] == "sensor.givtcp_inv01_load_power"
    assert one["home_today"] == "sensor.givtcp_inv01_load_energy_today_kwh"
    assert one["grid_import_today"] == "sensor.givtcp_inv01_import_energy_today_kwh"
    assert one["grid_export_today"] == "sensor.givtcp_inv01_export_energy_today_kwh"
    assert one["car_plug"] == "sensor.myenergi_zappi_plug_status"
    assert one["car_status"] == "sensor.myenergi_zappi_status"
    assert one["car_power"] == "sensor.myenergi_zappi_power_ct_internal_load"
    assert one["car_soc"] == "sensor.e_niro_ev_battery_level"  # not the 12 V battery
    assert one["car_range"] == "sensor.e_niro_ev_range"
    assert one["car_session"] == "sensor.myenergi_zappi_charge_added_session"
    assert one["heat_pump_mode"] == "sensor.altherma_operation_type"
    assert one["heat_pump_power"] == "sensor.shellyproem50_abc_em1_power"  # the meter the heat pump's energy is on
    assert sorted(auto["heat_pump_today"]) == [
        "sensor.altherma_climatecontrol_heating_daily_electrical_consumption",
        "sensor.altherma_domestichotwatertank_heating_daily_electrical_consumption"]  # heating + hot water
    assert one["heat_pump_flow"] == "sensor.altherma_climatecontrol_leaving_water_temperature"
    assert one["heat_pump_tank"] == "sensor.altherma_domestichotwatertank_tank_temperature"
    assert one["outdoor_temp"] == "sensor.altherma_climatecontrol_outdoor_temperature"


def test_suggest_without_energy_dashboard():
    auto, flags = energy.suggest(ha_states(), None)
    assert auto["solar_power"] == ["sensor.givtcp_inv01_pv_power"]
    assert auto["battery_power"] == ["sensor.givtcp_inv01_battery_power"]
    assert flags == {}


def test_inverted_grid_from_dashboard():
    prefs = {"energy_sources": [{"type": "grid", "power_config": {"stat_rate_inverted": "sensor.givtcp_inv01_grid_power"}}]}
    found, flags = energy.from_prefs(prefs)
    assert found["grid_power"] == "sensor.givtcp_inv01_grid_power" and flags["grid_invert"] is True


def test_mode_words():
    assert energy.mode_label("Space") == "Heating the house"
    assert energy.mode_label("DHW") == "Heating hot water"
    assert energy.mode_label("Hot Water") == "Heating hot water"
    assert energy.mode_label("heating") == "Heating the house"
    assert energy.mode_label("Defrost") == "Defrosting"
    assert energy.mode_label("standby") == "Idle"
    assert energy.mode_label("unavailable") is None


def test_plug_and_charging_words():
    assert energy.plugged_in(st("sensor.p", "EV Connected")) is True
    assert energy.plugged_in(st("sensor.p", "EV Disconnected")) is False
    assert energy.plugged_in(st("binary_sensor.p", "off")) is False
    assert energy.charging_from_status(st("sensor.s", "Paused")) is False
    assert energy.charging_from_status(st("sensor.s", "Charging")) is True
    assert energy.charging_from_status(st("sensor.s", "Charging complete")) is False
    assert energy.charging_from_status(st("sensor.s", "Diverting")) is True


# ---------------------------------------------------------------- overview

def test_overview(client):
    r = client.get("/api/energy").json()
    assert r["configured"] and r["reachable"]
    assert r["solar"] == {"power": 2450, "today": 7.0}
    assert r["battery"] == {"soc": 64, "power": 1518, "state": "discharging"}
    assert r["grid"]["power"] == -120 and r["grid"]["state"] == "exporting"
    assert r["grid"]["import_today"] == 12.9 and r["grid"]["export_today"] == 1.8
    assert r["home"] == {"power": 3848, "today": 17.5, "computed": False}
    car = r["car"]
    assert car["plugged_in"] is True and car["charging"] is False and car["status"] == "Plugged in · paused"
    assert car["soc"] == 50 and car["range"] == 129 and car["range_unit"] == "mi"
    hp = r["heat_pump"]
    assert hp["running"] is True and hp["doing"] == "Heating the house" and hp["power"] == 774
    assert hp["today"] == 7.0 and hp["flow_temp"] == 28.0 and hp["tank_temp"] == 45.0 and hp["outdoor_temp"] == 9.0


def test_car_charging_and_heat_pump_idle(client, fake):
    fake.states["sensor.myenergi_zappi_status"]["state"] = "Charging"
    fake.states["sensor.myenergi_zappi_power_ct_internal_load"]["state"] = "7.2"
    fake.states["sensor.myenergi_zappi_power_ct_internal_load"]["attributes"]["unit_of_measurement"] = "kW"
    fake.states["sensor.shellyproem50_abc_em1_power"]["state"] = "12"
    r = client.get("/api/energy").json()
    assert r["car"]["charging"] is True and r["car"]["power"] == 7200 and r["car"]["status"] == "Charging"
    assert r["heat_pump"]["running"] is False and r["heat_pump"]["doing"] == "Idle"
    fake.states["sensor.myenergi_zappi_plug_status"]["state"] = "EV Disconnected"
    fake.states["sensor.myenergi_zappi_status"]["state"] = "Paused"
    fake.states["sensor.myenergi_zappi_power_ct_internal_load"]["state"] = "0"
    r = client.get("/api/energy").json()
    assert r["car"]["plugged_in"] is False and r["car"]["status"] == "Not plugged in"


def test_settings_pick_none_and_flip(client):
    r = client.patch("/api/settings", json={"pin": PIN, "energy": {
        "entities": {"home_power": "", "car_plug": "binary_sensor.e_niro_ev_battery_plug", "solar_power": None},
        "grid_invert": True}})
    assert r.status_code == 200, r.text
    assert r.json()["energy"]["entities"] == {"home_power": "", "car_plug": "binary_sensor.e_niro_ev_battery_plug"}
    r = client.get("/api/energy").json()
    assert r["grid"]["power"] == 120 and r["grid"]["state"] == "importing"
    # No home sensor: worked out from what comes in (solar + battery + grid).
    assert r["home"]["computed"] is True and r["home"]["power"] == 2450 + 1518 + 120
    opts = client.get("/api/energy/options").json()
    assert opts["slots"]["home_power"] == {"kind": "power", "group": "home", "entities": [], "auto": False,
                                           "suggested": ["sensor.givtcp_inv01_load_power"]}
    assert opts["slots"]["solar_power"]["auto"] is True and opts["grid_invert"] is True
    assert any(c["entity_id"] == "sensor.shellyproem50_abc_em1_power" for c in opts["candidates"]["power"])
    assert any(c["entity_id"] == "binary_sensor.e_niro_ev_battery_plug" for c in opts["candidates"]["state"])


def test_settings_validation(client):
    assert client.patch("/api/settings", json={"pin": PIN, "energy": {"entities": {"nope": ""}}}).status_code == 400
    assert client.patch("/api/settings", json={"pin": PIN, "energy": {"entities": {"solar_power": "light.kitchen"}}}).status_code == 400
    assert client.patch("/api/settings", json={"pin": PIN, "energy": {"grid_invert": "yes"}}).status_code == 400


def test_nothing_set_shows_nothing(client):
    client.patch("/api/settings", json={"pin": PIN, "energy": {"entities": {s: "" for s in energy.SLOTS}}})
    r = client.get("/api/energy").json()
    assert all(r[k] is None for k in ("solar", "battery", "grid", "home", "car", "heat_pump"))


def test_without_home_assistant(tmp_path):
    energy.set_service(None)
    try:
        c = TestClient(create_app(db_path=str(tmp_path / "t.db"), demo=False, auth_enabled=False))
        r = c.get("/api/energy").json()
        assert r["configured"] is False and r["solar"] is None
        assert c.get("/api/energy/options").status_code == 409
    finally:
        energy.reset()


def test_broadcasts_are_spaced_out(client, monkeypatch):
    from moonlight import common

    sent = []

    async def broadcast(*topics):
        sent.extend(topics)

    monkeypatch.setattr(common.hub, "broadcast", broadcast)
    monkeypatch.setattr(energy, "BROADCAST_EVERY", 0.2)

    async def run():
        await energy._changed()
        await energy._changed()
        await energy._changed()
        assert sent == ["energy"]
        await asyncio.sleep(0.3)
        assert sent == ["energy", "energy"]

    asyncio.run(run())


def test_energy_section_added_once(tmp_path):
    from moonlight import db

    path = str(tmp_path / "old.db")
    create_app(db_path=path, demo=False, auth_enabled=False)
    with sqlite3.connect(path) as c:
        c.execute("DELETE FROM settings WHERE key = ?", (db.ENERGY_MARKER,))
        c.execute("INSERT OR REPLACE INTO settings(key, value) VALUES('screens', ?)", (json.dumps(
            {"large": {"start": "calendar", "sections": ["calendar", "security"]},
             "phone": {"start": "today", "sections": ["today"]}}),))
    db.init_db()
    with sqlite3.connect(path) as c:
        screens = json.loads(c.execute("SELECT value FROM settings WHERE key = 'screens'").fetchone()[0])
        assert screens["large"]["sections"] == ["calendar", "security", "energy"]
        assert screens["phone"]["sections"] == ["today", "energy"]
        c.execute("UPDATE settings SET value = ? WHERE key = 'screens'",
                  (json.dumps({"large": {"start": "calendar", "sections": ["calendar"]}}),))
    db.init_db()
    with sqlite3.connect(path) as c:
        assert json.loads(c.execute("SELECT value FROM settings WHERE key = 'screens'").fetchone()[0])["large"]["sections"] == ["calendar"]
