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


def KWH(eid, v, name, unit="kWh", **attrs):
    return st(eid, str(v), unit_of_measurement=unit, device_class="energy", friendly_name=name, **attrs)


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
        st("sun.sun", "below_horizon", next_rising="2026-10-22T06:42:33.275398+00:00",
           next_setting="2026-10-22T16:50:12.636133+00:00", friendly_name="Sun"),
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
        st("sensor.altherma_climatecontrol_room_temperature", "19.2", unit_of_measurement="°C", friendly_name="Altherma ClimateControl Room temperature"),
        st("sensor.living_room_room_temperature", "19.9", unit_of_measurement="°C", friendly_name="Living room Room temperature"),
        st("sensor.althermasensors", "Online", **{
            "friendly_name": "EspAltherma AlthermaSensors", "R1T-Outdoor air temp.": 8.6, "3way valve(On:DHW_Off:Space)": "OFF",
            "Defrost Operation": "OFF", "Leaving water temp. before BUH (R1T)": 34, "Leaving water temp. after BUH (R2T)": 33.9,
            "Inlet water temp.(R4T)": 29.1, "DHW tank temp. (R5T)": 44, "Indoor ambient temp. (R1T)": 19.2, "Flow sensor (l/min)": 11.4}),
        KWH("sensor.fairfields_solar_forecast_forecast_today", 8.04, "Fairfields Solar Forecast Forecast Today",
            detailedForecast=[{"period_start": f"2026-10-21T{h:02d}:{m:02d}:00+01:00", "pv_estimate": 0.4 if 8 <= h < 17 else 0.02}
                              for h in range(24) for m in (0, 30)]),
        KWH("sensor.fairfields_solar_forecast_forecast_tomorrow", 21.88, "Fairfields Solar Forecast Forecast Tomorrow"),
        KWH("sensor.fairfields_solar_forecast_forecast_remaining_today", 0.1, "Fairfields Solar Forecast Forecast Remaining Today"),
        st("predbat.status", "Demand", friendly_name="Status"),
        st("predbat.cost_today", "165.76", unit_of_measurement="p", friendly_name="Cost so far today"),
        st("predbat.rates", "34.69", unit_of_measurement="p", friendly_name="Import rates"),
        st("predbat.rates_export", "12.0", unit_of_measurement="p", friendly_name="Export rates"),
        st("predbat.battery_hours_left", "0.5", unit_of_measurement="hours", friendly_name="Predicted Battery Hours left"),
        st("predbat.best_charge_start", "23:30:00", timestamp="2026-10-21T23:30:00+0100", rate=6.6, device_class="timestamp"),
        st("predbat.best_charge_end", "05:30:00", timestamp="2026-10-22T05:30:00+0100", rate=6.6, device_class="timestamp"),
        st("binary_sensor.octopus_energy_00000000_abc_intelligent_dispatching", "off", friendly_name="Myenergi zappi Intelligent Dispatching",
           planned_dispatches=[{"start": "2026-10-21T23:30:00+01:00", "end": "2026-10-22T01:00:00+01:00"},
                               {"start": "2026-10-22T05:30:00+01:00", "end": "2026-10-22T06:00:00+01:00"}]),
        st("select.octopus_energy_00000000_abc_intelligent_target_time", "06:00", friendly_name="Myenergi zappi Intelligent Target Time"),
        st("number.octopus_energy_00000000_abc_intelligent_charge_target", "35.0", unit_of_measurement="%", device_class="battery",
           friendly_name="Myenergi zappi Intelligent Charge Target"),
        st("number.e_niro_ac_charging_limit", "80", unit_of_measurement="%", friendly_name="E-NIRO AC Charging Limit"),
        st("number.ef_d30561_charge_limit", "90", unit_of_measurement="%", friendly_name="EF-D30561 Battery Charge Limit"),
        st("binary_sensor.octopus_energy_electricity_123_456_off_peak", "off", friendly_name="Electricity Meter Off Peak Electricity",
           next_start="2026-10-21T23:30:00+01:00", next_end="2026-10-22T06:00:00+01:00"),
        st("binary_sensor.octopus_energy_electricity_123_789_export_off_peak", "off", friendly_name="Electricity Meter Export Off Peak"),
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
        self.midnight = {"sensor.heat_pump_energy_heating": "4448.5"}
        self.history_asked: list[dict] = []

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
                elif msg["type"] == "history/history_during_period":
                    fake.history_asked.append(msg)
                    self.out.put_nowait({"id": msg["id"], "type": "result", "success": True, "result": {
                        e: [{"s": fake.midnight[e], "lu": 0}] for e in msg["entity_ids"] if e in fake.midnight}})
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
    assert one["inside_temp"] == "sensor.altherma_climatecontrol_room_temperature"
    assert one["heat_pump_details"] == "sensor.althermasensors"
    assert one["solar_forecast"] == "sensor.fairfields_solar_forecast_forecast_today"
    assert one["solar_forecast_tomorrow"] == "sensor.fairfields_solar_forecast_forecast_tomorrow"
    assert one["plan_status"] == "predbat.status" and one["plan_charge_start"] == "predbat.best_charge_start"
    assert "plan_cheap_start" not in auto  # not in this Home Assistant
    assert one["car_limit"] == "number.e_niro_ac_charging_limit"  # the car's own, not Octopus's target or a home battery
    assert one["car_ready"] == "select.octopus_energy_00000000_abc_intelligent_target_time"
    assert one["cheap_off_peak"] == "binary_sensor.octopus_energy_electricity_123_456_off_peak"  # not the export one
    assert one["cheap_dispatches"] == "binary_sensor.octopus_energy_00000000_abc_intelligent_dispatching"


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
    solar = r["solar"]
    assert solar["power"] == 2450 and solar["today"] == 7.0
    assert solar["forecast_today"] == 8.04 and solar["forecast_tomorrow"] == 21.88
    assert r["battery"] == {"soc": 64, "power": 1518, "state": "discharging"}
    assert r["grid"]["power"] == -120 and r["grid"]["state"] == "exporting"
    assert r["grid"]["import_today"] == 12.9 and r["grid"]["export_today"] == 1.8
    assert r["home"] == {"power": 3848, "today": 17.5, "computed": False}
    car = r["car"]
    assert car["plugged_in"] is True and car["charging"] is False and car["status"] == "Plugged in · paused"
    assert car["soc"] == 50 and car["range"] == 129 and car["range_unit"] == "mi"
    hp = r["heat_pump"]
    assert hp["running"] is True and hp["doing"] == "Heating the house" and hp["power"] == 774
    assert hp["today"] == 7.0 and hp["flow_temp"] == 28.0
    # 11.4 l/min leaving at 33.9° and back at 29.1°: 3.8 kW of heat for 774 W
    assert hp["heat"] == 3818 and hp["cop"] == 4.9
    temps = r["temperatures"]
    assert {k: temps[k] for k in ("inside", "outside", "tank")} == {"inside": 19.2, "outside": 9.0, "tank": 45.0}
    plan = r["plan"]
    assert plan["status"] == "Demand" and plan["cost_today"] == 165.76 and plan["cost_unit"] == "p"
    assert plan["rate_now"] == 34.69 and plan["rate_export"] == 12.0 and plan["battery_hours"] == 0.5
    assert plan["charge"] == {"start": "2026-10-21T23:30:00+01:00", "end": "2026-10-22T05:30:00+01:00", "rate": 6.6}
    assert plan["cheap"] is None


def test_car_limit_ready_and_cheap_slots():
    from datetime import datetime, timezone
    by = {x["entity_id"]: x for x in ha_states()}
    auto, flags = energy.suggest(list(by.values()), PREFS)
    eff = energy.effective(auto, flags, {})
    r = energy.build(eff, by, now=datetime(2026, 10, 21, 20, 15, tzinfo=timezone.utc))  # 21:15 in London
    assert r["car"]["limit"] == 80 and r["car"]["ready"] == "2026-10-22T06:00:00+01:00"
    t = r["tariff"]
    assert t["cheap_now"] is False and t["dispatching"] is False
    assert t["next"] == {"start": "2026-10-21T23:30:00+01:00", "end": "2026-10-22T06:00:00+01:00"}
    assert t["bonus"] == [{"start": "2026-10-22T05:30:00+01:00", "end": "2026-10-22T06:00:00+01:00"}]  # after 05:30
    # In the middle of the night: cheap now, until the end of the run of slots
    r = energy.build(eff, by, now=datetime(2026, 10, 22, 0, 0, tzinfo=timezone.utc))
    assert r["tariff"]["cheap_now"] is True and r["tariff"]["cheap_until"] == "2026-10-22T06:00:00+01:00"
    # A daytime dispatch is a bonus slot and the next cheap slot
    disp = by["binary_sensor.octopus_energy_00000000_abc_intelligent_dispatching"]
    disp["attributes"]["planned_dispatches"] = [{"start": "2026-10-21T14:00:00+01:00", "end": "2026-10-21T15:30:00+01:00"}]
    t = energy.build(eff, by, now=datetime(2026, 10, 21, 11, 0, tzinfo=timezone.utc))["tariff"]
    assert t["next"] == {"start": "2026-10-21T14:00:00+01:00", "end": "2026-10-21T15:30:00+01:00"}
    assert t["bonus"] == [t["next"]]


def test_set_points_and_humidity():
    """Found by name (his Daikin set points and SwitchBot meters), not fooled by fridges or "indoor_outdoor" ids."""
    def pct(eid, v, name):
        return st(eid, v, unit_of_measurement="%", device_class="humidity", friendly_name=name)
    extra = [
        st("sensor.heating_set_point", "19", unit_of_measurement="°C", device_class="temperature",
           friendly_name="Altherma Heating Set Point"),
        st("sensor.dhw_setpoint", "46", unit_of_measurement="°C", device_class="temperature", friendly_name="DHW setpoint"),
        st("sensor.altherma_domestichotwatertank_setpoint_mode", "fixed", friendly_name="Setpoint mode"),
        pct("sensor.meter_2330_humidity", "57", "Kitchen Meter Pro Humidity"),
        pct("sensor.indoor_outdoor_meter_5d0e_humidity", "55", "Hallway Meter Humidity"),
        pct("sensor.indoor_outdoor_meter_3d2d_humidity", "56", "Bathroom Meter Humidity"),
        pct("sensor.indoor_outdoor_meter_3f0a_humidity", "94", "Outside Meter Humidity"),
        pct("sensor.indoor_outdoor_meter_2c0f_humidity", "76", "Kitchen Freezer Meter Humidity"),
        pct("sensor.openweathermap_humidity", "92", "OpenWeatherMap Humidity"),
    ]
    by = {x["entity_id"]: x for x in ha_states() + extra}
    auto, flags = energy.suggest(list(by.values()), PREFS)
    assert auto["heating_target"] == ["sensor.heating_set_point"] and auto["tank_target"] == ["sensor.dhw_setpoint"]
    assert auto["inside_humidity"][0] == "sensor.indoor_outdoor_meter_5d0e_humidity"
    assert auto["outside_humidity"][0] == "sensor.indoor_outdoor_meter_3f0a_humidity"
    t = energy.build(energy.effective(auto, flags, {}), by)["temperatures"]
    assert t["heating_target"] == 19 and t["tank_target"] == 46
    assert t["inside_humidity"] == 55 and t["outside_humidity"] == 94
    # No outside meter: the weather's humidity
    del by["sensor.indoor_outdoor_meter_3f0a_humidity"]
    auto, _ = energy.suggest(list(by.values()), PREFS)
    assert auto["outside_humidity"][0] == "sensor.openweathermap_humidity"


def test_running_total_meter_counts_from_midnight():
    by = {x["entity_id"]: x for x in ha_states()}
    auto, flags = energy.suggest(list(by.values()), PREFS)
    eff = energy.effective(auto, flags, {"entities": {"heat_pump_today": "sensor.heat_pump_energy_heating"}})
    assert energy.is_meter("sensor.heat_pump_energy_heating", by["sensor.heat_pump_energy_heating"])
    assert not energy.is_meter("sensor.givtcp_inv01_pv_energy_today_kwh", by["sensor.givtcp_inv01_pv_energy_today_kwh"])
    # Without a midnight reading it shows nothing rather than the lifetime total
    assert energy.build(eff, by)["heat_pump"]["today"] is None
    assert energy.build(eff, by, midnight={"sensor.heat_pump_energy_heating": 4448.5})["heat_pump"]["today"] == 4.5
    # A since-midnight sensor is shown as it is
    assert energy.build(eff, by)["solar"]["today"] == 7.0


def test_midnight_reading_from_history(client):
    svc = energy.service()
    ws = svc.ws_connect
    r = client.patch("/api/settings", json={"pin": PIN, "energy": {"entities": {"heat_pump_today": "sensor.heat_pump_energy_heating"}}})
    assert r.status_code == 200, r.text
    assert client.get("/api/energy").json()["heat_pump"]["today"] == 4.5
    asked = ws.history_asked[-1]
    assert asked["entity_ids"] == ["sensor.heat_pump_energy_heating"] and asked["include_start_time_state"] is True
    n = len(ws.history_asked)
    client.get("/api/energy")
    assert len(ws.history_asked) == n  # kept for the day


def test_night_after_sunset(client, fake):
    r = client.get("/api/energy").json()
    assert r["sun"] == {"night": True, "next": "2026-10-22T06:42:33+00:00"}
    fake.states["sun.sun"]["state"] = "above_horizon"
    assert energy.sun(fake.states["sun.sun"]) == {"night": False, "next": "2026-10-22T16:50:12+00:00"}
    assert energy.sun(None) is None


def test_solar_window():
    from datetime import datetime, timezone
    s = ha_states()
    fc = next(x for x in s if x["entity_id"] == "sensor.fairfields_solar_forecast_forecast_today")
    starts, ends = energy.solar_window(fc, datetime(2026, 10, 21, 5, 0, tzinfo=timezone.utc))
    assert starts == "2026-10-21T08:00:00+01:00" and ends == "2026-10-21T17:00:00+01:00"
    assert energy.solar_window(fc, datetime(2026, 10, 22, 5, 0, tzinfo=timezone.utc)) == (None, None)  # yesterday's
    assert energy.solar_window(st("sensor.x", "3"), datetime.now(timezone.utc)) == (None, None)


def test_heat_pump_details_and_hot_water():
    d = energy.details(st("sensor.esp", "Online", **{"3way valve(On:DHW_Off:Space)": "ON", "Flow sensor (l/min)": "12",
                                                     "Leaving water temp. after BUH (R2T)": 50, "Inlet water temp.(R4T)": 45}))
    assert d == {"flow_rate": 12.0, "flow_temp": 50.0, "return_temp": 45.0, "hot_water": True}


def test_cop_day():
    day = energy.CopDay()
    run = {"heat": 4000.0, "power": 1000.0, "hot_water": False, "defrost": False}
    day.sample(0, "2026-10-21", run, True)
    day.sample(3600 * 0 + 60, "2026-10-21", run, True)              # a minute of heating
    day.sample(120, "2026-10-21", run | {"heat": 2000.0, "hot_water": True}, True)  # a minute of hot water
    day.sample(1000, "2026-10-21", run, True)                       # a gap: not counted
    day.sample(1060, "2026-10-21", {"heat": 0.0, "power": 20.0, "hot_water": False, "defrost": False}, False)
    assert round(day.heat["heating"], 2) == 66.67 and round(day.elec["heating"], 2) == 16.67
    assert round(day.heat["hot_water"], 2) == 33.33 and round(day.elec["idle"], 3) == 0.333
    again = energy.CopDay(day.as_dict())
    assert again.as_dict() == day.as_dict()
    again.sample(1100, "2026-10-22", run, True)                     # midnight: starts again
    assert again.heat["heating"] == 0 and again.day == "2026-10-22"
    r = energy.build({"entities": {s: [] for s in energy.SLOTS} | {"heat_pump_power": ["sensor.p"]},
                      "battery_invert": False, "grid_invert": False, "auto": {}},
                     {"sensor.p": W("sensor.p", 1000, "P")},
                     {"day": "x", "heat": {"heating": 9000, "hot_water": 2000}, "elec": {"heating": 2400, "hot_water": 800, "idle": 50}})
    assert r["heat_pump"]["cop_today"] == {"heating": 3.8, "hot_water": 2.5, "overall": 3.4}


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
