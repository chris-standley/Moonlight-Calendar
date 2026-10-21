"""Energy: solar, the home battery, the grid, the car charger and the heat pump, read from Home Assistant entities
and drawn on the screens as a house with the power flowing between them.

Each thing shown is a "slot" (solar_power, battery_soc, car_plug, heat_pump_mode, ...) filled by one entity. A slot
is automatic until the household picks an entity for it in Settings > Energy (or "" for none):

- Home Assistant's own Energy dashboard comes first: its solar, battery and grid power sensors (`stat_rate`, with
  HA's signs: battery positive when discharging, grid positive when importing) and any device whose name says car
  or heat pump.
- Then entity ids and names, preferring the same device as what was already found (an inverter's "..._soc" next to
  its "..._battery_power"). A heat pump's power is found from an energy sensor called "... Heat Pump ..." whose
  name starts the same way as a power sensor (a Shelly's "Energy Meter 1 Heat Pump Energy" and "Energy Meter 1
  Power"). Anything else is picked in Settings.

Also shown: the solar forecast (when the panels start, what today and tomorrow should make), inside, outside and tank
temperatures, Predbat's plan (its `predbat.*` entities) and the heat pump's COP. Moonlight works COP out itself: the
heat going into the water (flow rate x how much warmer it leaves than it comes back, from a controller such as
ESPAltherma that puts its readings on one entity's attributes, or from separate sensors) against the power meter, now
and added up since midnight for heating, hot water and overall.

Power is shown in watts (kW sensors are converted), energy in kWh. Battery and grid can be flipped in Settings for
sensors that use the opposite sign. The chosen entities are followed over Home Assistant's WebSocket, and changes
broadcast `energy` at most every few seconds (power sensors change constantly)."""
from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from . import db, home_security, media

log = logging.getLogger("moonlight.energy")

KEY = "energy"
ENTITY_RE = re.compile(r"^(sensor|binary_sensor|select|input_select|input_number|number|climate|water_heater|switch|"
                       r"input_boolean|predbat)\.[a-z0-9_]+$")
DISCOVERY_TTL = 300.0
BROADCAST_EVERY = 4.0        # seconds between `energy` broadcasts while power keeps changing
IDLE_WATTS = 30.0            # below this a flow is drawn as nothing moving
HEAT_PUMP_RUNNING_WATTS = 100.0  # a heat pump's controls draw a little even when it's off
CAR_CHARGING_WATTS = 200.0

# slot -> (kind, group). Kinds decide which entities Settings offers for it.
SLOTS: dict[str, tuple[str, str]] = {
    "solar_power": ("power", "solar"),
    "solar_today": ("energy", "solar"),
    "solar_forecast": ("energy", "solar"),
    "solar_forecast_tomorrow": ("energy", "solar"),
    "battery_soc": ("percent", "battery"),
    "battery_power": ("power", "battery"),
    "grid_power": ("power", "grid"),
    "grid_import_today": ("energy", "grid"),
    "grid_export_today": ("energy", "grid"),
    "home_power": ("power", "home"),
    "home_today": ("energy", "home"),
    "car_plug": ("state", "car"),
    "car_status": ("state", "car"),
    "car_power": ("power", "car"),
    "car_soc": ("percent", "car"),
    "car_range": ("number", "car"),
    "car_session": ("energy", "car"),
    "heat_pump_mode": ("state", "heat_pump"),
    "heat_pump_power": ("power", "heat_pump"),
    "heat_pump_today": ("energy", "heat_pump"),
    "heat_pump_flow": ("temperature", "heat_pump"),
    "heat_pump_return": ("temperature", "heat_pump"),
    "heat_pump_flow_rate": ("number", "heat_pump"),
    "heat_pump_details": ("state", "heat_pump"),
    "inside_temp": ("temperature", "temperatures"),
    "outdoor_temp": ("temperature", "temperatures"),
    "heat_pump_tank": ("temperature", "temperatures"),
    "plan_status": ("state", "plan"),
    "plan_cost_today": ("number", "plan"),
    "plan_rate_now": ("number", "plan"),
    "plan_rate_export": ("number", "plan"),
    "plan_battery_hours": ("number", "plan"),
    "plan_charge_start": ("state", "plan"),
    "plan_charge_end": ("state", "plan"),
    "plan_cheap_start": ("state", "plan"),
    "plan_cheap_end": ("state", "plan"),
}
# Predbat's own entities, found by id.
PREDBAT = {"plan_status": "predbat.status", "plan_cost_today": "predbat.cost_today", "plan_rate_now": "predbat.rates",
           "plan_rate_export": "predbat.rates_export", "plan_battery_hours": "predbat.battery_hours_left",
           "plan_charge_start": "predbat.best_charge_start", "plan_charge_end": "predbat.best_charge_end",
           "plan_cheap_start": "predbat.low_rate_start", "plan_cheap_end": "predbat.low_rate_end"}

# A heat pump controller (ESPAltherma and the like) that puts all its readings on one entity's attributes.
DETAIL_ATTRS = {
    "flow_rate": [r"^flow sensor.*l/min", r"flow.*\(l/min\)", r"flow.?rate"],
    "flow_temp": [r"leaving water temp.*after", r"leaving water temp", r"^lwt"],
    "return_temp": [r"inlet water temp", r"return water temp", r"^ewt"],
    "tank_temp": [r"dhw tank temp", r"tank temp"],
    "inside_temp": [r"indoor ambient temp", r"room temp"],
    "outdoor_temp": [r"outdoor air temp", r"outdoor temp"],
    "hot_water": [r"3.?way valve"],
    "defrost": [r"^defrost operation", r"defrost"],
}
FLAGS = ("battery_invert", "grid_invert")

POWER_UNITS = {"w": 1.0, "kw": 1000.0, "mw": 1_000_000.0}
ENERGY_UNITS = {"wh": 0.001, "kwh": 1.0, "mwh": 1000.0}
TEMP_UNITS = {"°c", "°f", "c", "f"}

HEAT_PUMP_WORDS = r"(heat_?pump|heatpump|ashp|gshp|altherma|ecodan|arotherm|vitocal|aquarea|samsung_ehs|mitsubishi_ecodan)"
CAR_EXCLUDE = re.compile(r"(phone|ipad|iphone|watch|tablet|laptop|remote|sensor_battery)")

WATER_HEAT = 4186.0          # J per litre per degree
COP_MIN_WH = 50.0            # don't give a day's COP on less electricity than this
COP_KEY = "energy_cop_day"   # settings key holding today's running totals, so a restart doesn't lose them
COP_SAMPLE_EVERY = 10.0
COP_SAVE_EVERY = 300.0

# What the heat pump is doing, from its mode entity (lower case) -> words on the screen.
MODE_WORDS = [
    (re.compile(r"defrost"), "Defrosting"),
    (re.compile(r"(dhw|hot.?water|domestic|tank|sanitary|water.?heat)"), "Heating hot water"),
    (re.compile(r"(cool)"), "Cooling"),
    (re.compile(r"^(space|heat|heating|space.?heat\w*|ch|central.?heating|room)$|space"), "Heating the house"),
    (re.compile(r"^(off|standby|idle|stop|stopped|none|0)$"), "Idle"),
]


# ---------------------------------------------------------------- settings

def saved(c) -> dict:
    val = db.get_setting(c, KEY, {}) or {}
    return val if isinstance(val, dict) else {}


def apply_settings(c, body: dict) -> bool:
    """PATCH /api/settings `energy`: {entities?: {slot: entity id | "" (none) | null (automatic)},
    battery_invert?: bool, grid_invert?: bool}. Returns True if `energy` was present."""
    if KEY not in body:
        return False
    from .common import bad

    val = body[KEY]
    if not isinstance(val, dict):
        raise bad("energy must be an object")
    out = saved(c)
    if "entities" in val:
        ents = val["entities"]
        if not isinstance(ents, dict):
            raise bad("energy.entities must be an object like {\"solar_power\": \"sensor.pv_power\"}")
        merged = dict(out.get("entities") or {})
        for slot, eid in ents.items():
            if slot not in SLOTS:
                raise bad(f"energy.entities: {slot} isn't something Moonlight shows")
            if eid is None:
                merged.pop(slot, None)
            elif not isinstance(eid, str) or (eid and not ENTITY_RE.match(eid)):
                raise bad(f"energy.entities.{slot} must be an entity id, \"\" for none, or null for automatic")
            else:
                merged[slot] = eid
        out["entities"] = merged
    for flag in FLAGS:
        if flag in val:
            if val[flag] is not None and not isinstance(val[flag], bool):
                raise bad(f"energy.{flag} must be true, false or null")
            if val[flag] is None:
                out.pop(flag, None)
            else:
                out[flag] = val[flag]
    db.set_setting(c, KEY, out)
    return True


# ---------------------------------------------------------------- reading values (pure)

def _attrs(state: dict | None) -> dict:
    return (state or {}).get("attributes") or {}


def _name(state: dict | None, entity: str) -> str:
    return str(_attrs(state).get("friendly_name") or entity.split(".", 1)[1].replace("_", " ").capitalize())


def _unit(state: dict | None) -> str:
    return str(_attrs(state).get("unit_of_measurement") or "").strip().lower()


def _float(state: dict | None) -> float | None:
    if not state:
        return None
    v = media._num(state.get("state"))
    return v if v is not None and v == v else None  # no NaN


def watts(state: dict | None) -> float | None:
    v = _float(state)
    if v is None:
        return None
    return v * POWER_UNITS.get(_unit(state), 1.0)


def kwh(state: dict | None) -> float | None:
    v = _float(state)
    if v is None:
        return None
    return v * ENERGY_UNITS.get(_unit(state), 1.0)


def kind_of(entity: str, state: dict | None) -> str | None:
    """Which slots an entity could fill: power, energy, percent, temperature, number or state."""
    domain = entity.split(".", 1)[0]
    unit, dc = _unit(state), str(_attrs(state).get("device_class") or "")
    if domain in ("select", "input_select", "climate", "water_heater", "binary_sensor", "switch", "input_boolean"):
        return "state"
    if unit in POWER_UNITS or dc == "power":
        return "power"
    if unit in ENERGY_UNITS or dc == "energy":
        return "energy"
    if unit in TEMP_UNITS or dc == "temperature":
        return "temperature"
    if unit == "%":
        return "percent"
    if domain in ("sensor", "predbat") and _float(state) is None and not unit:
        return "state"
    if _float(state) is not None:
        return "number"
    return None


def mode_label(raw: str | None) -> str | None:
    if raw is None:
        return None
    low = raw.strip().lower().replace("_", " ")
    if low in ("", "unknown", "unavailable"):
        return None
    for pat, words in MODE_WORDS:
        if pat.search(low):
            return words
    return raw.strip().replace("_", " ")[:1].upper() + raw.strip().replace("_", " ")[1:]


def _mode_raw(state: dict | None) -> str | None:
    if not state:
        return None
    domain = str(state.get("entity_id") or "").split(".", 1)[0]
    if domain == "climate":
        return str(_attrs(state).get("hvac_action") or state.get("state") or "")
    return str(state.get("state") or "")


def plugged_in(state: dict | None) -> bool | None:
    if not state:
        return None
    s = str(state.get("state") or "").strip().lower()
    if s in ("", "unknown", "unavailable"):
        return None
    if s in ("on", "true", "connected", "plugged", "plugged in"):
        return True
    if s in ("off", "false", "available", "a", "idle", "ready"):
        return False
    return not re.search(r"(disconnect|unplug|not.?connected|not.?plugged|no.?(ev|car|vehicle))", s)


def charging_from_status(state: dict | None) -> bool | None:
    if not state:
        return None
    s = str(state.get("state") or "").strip().lower()
    if s in ("", "unknown", "unavailable"):
        return None
    if s in ("on", "true"):
        return True
    if s in ("off", "false"):
        return False
    if re.search(r"(not|complete|finish|paused|stopp|waiting|fault|error|idle|disconnect|full)", s):
        return False
    return bool(re.search(r"(charg|boost|divert)", s))


def _pretty(state: dict | None) -> str | None:
    if not state:
        return None
    s = str(state.get("state") or "").strip()
    if s.lower() in ("", "unknown", "unavailable"):
        return None
    if s.lower() in ("on", "off"):
        return None
    s = s.replace("_", " ")
    return s[:1].upper() + s[1:]


def _round(v: float | None, places: int = 0) -> float | int | None:
    if v is None:
        return None
    return round(v) if places == 0 else round(v, places)


def details(state: dict | None) -> dict[str, Any]:
    """A controller's attribute readings by name: {flow_rate, flow_temp, return_temp, tank_temp, inside_temp,
    outdoor_temp, hot_water, defrost} (whichever it has)."""
    out: dict[str, Any] = {}
    attrs = _attrs(state)
    for key, pats in DETAIL_ATTRS.items():
        for pat in pats:
            rx = re.compile(pat, re.I)
            hit = next((k for k in attrs if isinstance(k, str) and rx.search(k)), None)
            if hit is None:
                continue
            v = attrs[hit]
            if key in ("hot_water", "defrost"):
                out[key] = str(v).strip().lower() in ("on", "true", "1", "yes")
            else:
                n = media._num(v)
                if n is not None and n == n:
                    out[key] = float(n)
            break
    return out


def _is_detail_source(state: dict | None) -> bool:
    d = details(state)
    return "flow_rate" in d and "flow_temp" in d and "return_temp" in d


def heat_output(eff: dict, states: dict[str, dict | None]) -> dict:
    """What the heat pump puts into the water right now: {heat (W), power (W), hot_water, defrost}. Heat is the water
    flow times how much warmer it leaves than it comes back."""
    ents: dict[str, list[str]] = eff["entities"]

    def st(slot: str) -> dict | None:
        es = ents.get(slot) or []
        return states.get(es[0]) if es else None

    d = details(st("heat_pump_details"))
    rate = d.get("flow_rate") if "flow_rate" in d else _float(st("heat_pump_flow_rate"))
    if "flow_temp" in d and "return_temp" in d:
        lwt, ret = d["flow_temp"], d["return_temp"]
    else:
        lwt, ret = _float(st("heat_pump_flow")), _float(st("heat_pump_return"))
    rate_unit = _unit(st("heat_pump_flow_rate")) if "flow_rate" not in d else "l/min"
    if rate is not None and rate_unit in ("l/h", "lph"):
        rate /= 60
    elif rate is not None and rate_unit in ("m³/h", "m3/h"):
        rate = rate * 1000 / 60
    heat = rate / 60 * WATER_HEAT * (lwt - ret) if None not in (rate, lwt, ret) else None
    mode = mode_label(_mode_raw(st("heat_pump_mode")))
    hot_water = d.get("hot_water")
    if hot_water is None:
        hot_water = mode == "Heating hot water"
    p = watts(st("heat_pump_power"))
    return {"heat": heat, "power": max(p, 0.0) if p is not None else None, "hot_water": bool(hot_water),
            "defrost": bool(d.get("defrost")) or mode == "Defrosting"}


def _when(state: dict | None) -> str | None:
    """A time entity as an ISO date-time: its timestamp/date attribute, else a full date-time state."""
    if not state:
        return None
    for v in (_attrs(state).get("timestamp"), _attrs(state).get("date"), state.get("state")):
        dt = _parse_dt(v)
        if dt is not None:
            return dt.isoformat()
    return None


def _parse_dt(v: Any) -> datetime | None:
    if isinstance(v, datetime):
        return v if v.tzinfo else None
    if not isinstance(v, str) or len(v) < 16:
        return None
    try:
        dt = datetime.fromisoformat(v.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else None


def solar_window(state: dict | None, now: datetime) -> tuple[str | None, str | None]:
    """When today's forecast says the panels start and stop producing, from a Solcast-style detailed forecast
    (half-hour periods with `period_start` and `pv_estimate` in kW)."""
    attrs = _attrs(state)
    rows = attrs.get("detailedForecast") or attrs.get("detailed_forecast") or attrs.get("forecast") or []
    if not isinstance(rows, list):
        return None, None
    today = now.astimezone(_zone()).date()
    on: list[datetime] = []
    step = timedelta(minutes=30)
    for r in rows:
        if not isinstance(r, dict):
            continue
        start = _parse_dt(r.get("period_start") or r.get("start") or r.get("datetime"))
        est = media._num(r.get("pv_estimate", r.get("estimate")))
        if start is None or est is None or start.astimezone(_zone()).date() != today:
            continue
        if est >= 0.05:
            on.append(start)
    if len(rows) > 1 and isinstance(rows[0], dict) and isinstance(rows[1], dict):
        a, b = _parse_dt(rows[0].get("period_start")), _parse_dt(rows[1].get("period_start"))
        if a and b and b > a:
            step = b - a
    if not on:
        return None, None
    return min(on).isoformat(), (max(on) + step).isoformat()


def _zone() -> ZoneInfo:
    try:
        with db.connect() as c:
            return ZoneInfo(db.get_setting(c, "timezone", db.default_timezone()))
    except Exception:
        return ZoneInfo(db.FALLBACK_TIMEZONE)


def _ratio(heat: float, elec: float) -> float | None:
    return round(heat / elec, 1) if elec >= COP_MIN_WH and heat > 0 else None


def build(eff: dict, states: dict[str, dict | None], cop_day: dict | None = None, now: datetime | None = None) -> dict:
    """The house: {solar, battery, grid, home, car, heat_pump, temperatures, plan}, each None when nothing is set for it."""
    ents: dict[str, list[str]] = eff["entities"]
    now = now or datetime.now(timezone.utc)

    def st(slot: str) -> dict | None:
        es = ents.get(slot) or []
        return states.get(es[0]) if es else None

    def power(slot: str) -> float | None:
        return watts(st(slot))

    def energy(slot: str) -> float | None:
        vals = [kwh(states.get(e)) for e in ents.get(slot) or []]
        vals = [v for v in vals if v is not None]
        return round(sum(vals), 2) if vals else None

    def has(*slots: str) -> bool:
        return any(ents.get(s) for s in slots)

    def number(slot: str, places: int = 1) -> float | None:
        v = _float(st(slot))
        return round(v, places) if v is not None else None

    out: dict[str, Any] = {}

    if has("solar_power", "solar_today"):
        p = power("solar_power")
        starts, ends = solar_window(st("solar_forecast"), now)
        out["solar"] = {"power": _round(max(p, 0.0)) if p is not None else None, "today": energy("solar_today"),
                        "forecast_today": energy("solar_forecast"), "forecast_tomorrow": energy("solar_forecast_tomorrow"),
                        "starts": starts, "ends": ends}
    else:
        out["solar"] = None

    if has("battery_soc", "battery_power"):
        p = power("battery_power")
        if p is not None and eff["battery_invert"]:
            p = -p
        soc = _float(st("battery_soc"))
        state = None if p is None else "discharging" if p > IDLE_WATTS else "charging" if p < -IDLE_WATTS else "idle"
        out["battery"] = {"soc": _round(soc) if soc is not None else None, "power": _round(p), "state": state}
    else:
        out["battery"] = None

    if has("grid_power", "grid_import_today", "grid_export_today"):
        p = power("grid_power")
        if p is not None and eff["grid_invert"]:
            p = -p
        state = None if p is None else "importing" if p > IDLE_WATTS else "exporting" if p < -IDLE_WATTS else "idle"
        out["grid"] = {"power": _round(p), "state": state, "import_today": energy("grid_import_today"),
                       "export_today": energy("grid_export_today")}
    else:
        out["grid"] = None

    home = power("home_power")
    computed = False
    if home is None:
        parts = [(out["solar"] or {}).get("power"), (out["battery"] or {}).get("power"), (out["grid"] or {}).get("power")]
        if any(x is not None for x in parts) and out["grid"] and out["grid"]["power"] is not None:
            home = max(sum(x or 0 for x in parts), 0.0)  # what comes in is what the house uses
            computed = True
    out["home"] = ({"power": _round(home), "today": energy("home_today"), "computed": computed}
                   if home is not None or has("home_today") else None)

    if has("car_plug", "car_status", "car_power", "car_soc"):
        plug, status = st("car_plug"), st("car_status")
        p = power("car_power")
        plugged = plugged_in(plug)
        charging = charging_from_status(status)
        if p is not None and p >= CAR_CHARGING_WATTS:
            charging = True
        elif charging is None and p is not None:
            charging = False
        if charging is None and plug is not None and str(plug.get("state") or "").strip().lower() == "charging":
            charging = True
        if charging:
            plugged = True
        soc = _float(st("car_soc"))
        rng = _float(st("car_range"))
        if charging:
            label = "Charging"
        elif plugged is False:
            label = "Not plugged in"
        else:
            label = _pretty(status) or ("Plugged in" if plugged else None)
            if label and plugged and label.lower() in ("paused", "stopped", "idle", "waiting"):
                label = f"Plugged in · {label.lower()}"
        out["car"] = {"plugged_in": plugged, "charging": bool(charging) if charging is not None else None,
                      "status": label, "power": _round(max(p, 0.0)) if p is not None else None,
                      "soc": _round(soc) if soc is not None else None,
                      "range": _round(rng) if rng is not None else None,
                      "range_unit": _attrs(st("car_range")).get("unit_of_measurement") if rng is not None else None,
                      "session": energy("car_session")}
    else:
        out["car"] = None

    d = details(st("heat_pump_details"))
    if has("heat_pump_mode", "heat_pump_power"):
        p = power("heat_pump_power")
        mode = mode_label(_mode_raw(st("heat_pump_mode")))
        if p is not None:
            running = p >= HEAT_PUMP_RUNNING_WATTS
        else:
            running = mode not in (None, "Idle")
        hw = heat_output(eff, states)
        if running and hw["defrost"]:
            mode = "Defrosting"
        elif running and d.get("hot_water"):
            mode = "Heating hot water"
        doing = (mode if mode not in (None, "Idle") else "Running") if running else "Idle"
        cop = None
        if running and hw["heat"] is not None and hw["power"] and hw["heat"] > 0:
            cop = round(hw["heat"] / hw["power"], 1)
        day = cop_day or {}
        heat, elec = day.get("heat") or {}, day.get("elec") or {}
        cop_today = None
        if day:
            cop_today = {"heating": _ratio(heat.get("heating", 0.0), elec.get("heating", 0.0)),
                         "hot_water": _ratio(heat.get("hot_water", 0.0), elec.get("hot_water", 0.0)),
                         "overall": _ratio(sum(heat.values()), sum(elec.values()))}
            if not any(cop_today.values()):
                cop_today = None
        flow = number("heat_pump_flow")
        if flow is None and "flow_temp" in d:
            flow = round(d["flow_temp"], 1)
        out["heat_pump"] = {"running": running, "doing": doing, "power": _round(max(p, 0.0)) if p is not None else None,
                            "today": energy("heat_pump_today"), "flow_temp": flow,
                            "heat": _round(hw["heat"]) if hw["heat"] is not None and running else None,
                            "cop": cop if cop is not None and 0 < cop < 12 else None, "cop_today": cop_today}
    else:
        out["heat_pump"] = None

    temps = {"inside": number("inside_temp"), "outside": number("outdoor_temp"), "tank": number("heat_pump_tank")}
    for key, slot, attr in (("inside", "inside_temp", "inside_temp"), ("outside", "outdoor_temp", "outdoor_temp"),
                            ("tank", "heat_pump_tank", "tank_temp")):
        # Nothing picked for it: the heat pump controller's own reading will do.
        if temps[key] is None and attr in d and eff.get("auto", {}).get(slot, True):
            temps[key] = round(d[attr], 1)
    out["temperatures"] = temps if any(v is not None for v in temps.values()) else None

    if has(*PREDBAT):
        def window(a: str, b: str) -> dict | None:
            start, end = _when(st(a)), _when(st(b))
            if start is None:
                return None
            rate = media._num(_attrs(st(a)).get("rate"))
            return {"start": start, "end": end, "rate": round(rate, 2) if rate is not None else None}

        status = _pretty(st("plan_status"))
        hours = number("plan_battery_hours")
        out["plan"] = {"status": status, "cost_today": number("plan_cost_today", 2),
                       "cost_unit": _attrs(st("plan_cost_today")).get("unit_of_measurement"),
                       "rate_now": number("plan_rate_now", 2), "rate_export": number("plan_rate_export", 2),
                       "rate_unit": _attrs(st("plan_rate_now")).get("unit_of_measurement"),
                       "battery_hours": hours, "charge": window("plan_charge_start", "plan_charge_end"),
                       "cheap": window("plan_cheap_start", "plan_cheap_end")}
    else:
        out["plan"] = None
    return out


class CopDay:
    """Today's heat out and electricity in, split into heating and hot water, added up from samples every few
    seconds. Starts again at local midnight."""

    MAX_GAP = 120.0  # seconds; a longer gap (Home Assistant away) isn't counted

    def __init__(self, saved: dict | None = None) -> None:
        self.day: str | None = None
        self.heat: dict[str, float] = {"heating": 0.0, "hot_water": 0.0}
        self.elec: dict[str, float] = {"heating": 0.0, "hot_water": 0.0, "idle": 0.0}
        self.last: float | None = None
        if isinstance(saved, dict) and isinstance(saved.get("day"), str):
            self.day = saved["day"]
            for k in self.heat:
                self.heat[k] = float((saved.get("heat") or {}).get(k) or 0.0)
            for k in self.elec:
                self.elec[k] = float((saved.get("elec") or {}).get(k) or 0.0)

    def sample(self, at: float, today: str, sample: dict, running: bool) -> None:
        if self.day != today:
            self.day = today
            self.heat = {k: 0.0 for k in self.heat}
            self.elec = {k: 0.0 for k in self.elec}
            self.last = None
        last, self.last = self.last, at
        if last is None or not 0 < at - last <= self.MAX_GAP:
            return
        hours = (at - last) / 3600
        mode = "hot_water" if sample["hot_water"] else "heating"
        if sample["heat"] is not None:
            self.heat[mode] += sample["heat"] * hours
        if sample["power"] is not None:
            self.elec[mode if running else "idle"] += sample["power"] * hours

    def as_dict(self) -> dict:
        return {"day": self.day, "heat": dict(self.heat), "elec": dict(self.elec)}


# ---------------------------------------------------------------- finding entities (pure)

def _words(entity: str, state: dict | None) -> str:
    return (entity.split(".", 1)[1] + " " + re.sub(r"[^a-z0-9]+", "_", _name(state, entity).lower())).strip()


def _prefix(entity: str) -> str:
    """sensor.givac3_ce2048g006_battery_power -> givac3_ce2048g006_ (the device part most integrations use)."""
    obj = entity.split(".", 1)[1]
    parts = obj.split("_")
    return "_".join(parts[:2]) + "_" if len(parts) > 2 else obj


def _stat_entity(v: Any) -> str | None:
    return v if isinstance(v, str) and ENTITY_RE.match(v) else None


def from_prefs(prefs: dict | None) -> tuple[dict[str, str], dict[str, bool]]:
    """Slots and sign flips from Home Assistant's Energy dashboard."""
    found: dict[str, str] = {}
    flags: dict[str, bool] = {}
    if not isinstance(prefs, dict):
        return found, flags
    for src in prefs.get("energy_sources") or []:
        if not isinstance(src, dict):
            continue
        kind = src.get("type")
        pc = src.get("power_config") if isinstance(src.get("power_config"), dict) else {}
        if kind == "solar" and "solar_power" not in found and _stat_entity(src.get("stat_rate")):
            found["solar_power"] = src["stat_rate"]
        if kind in ("battery", "grid"):
            slot = f"{kind}_power"
            if slot in found:
                continue
            if _stat_entity(src.get("stat_rate")):
                found[slot] = src["stat_rate"]
                flags[f"{kind}_invert"] = False
            elif _stat_entity(pc.get("stat_rate")):
                found[slot] = pc["stat_rate"]
                flags[f"{kind}_invert"] = False
            elif _stat_entity(pc.get("stat_rate_inverted")):
                found[slot] = pc["stat_rate_inverted"]
                flags[f"{kind}_invert"] = True
    for dev in prefs.get("device_consumption") or []:
        if not isinstance(dev, dict) or not _stat_entity(dev.get("stat_rate")):
            continue
        name = str(dev.get("name") or "").lower()
        if re.search(r"heat.?pump|ashp", name):
            found.setdefault("heat_pump_power", dev["stat_rate"])
        elif re.search(r"\b(car|ev|charger|zappi|wallbox|ohme|easee)\b", name):
            found.setdefault("car_power", dev["stat_rate"])
    return found, flags


# slot -> patterns tried in order over "<object id> <name as snake_case>"; `near` slots prefer the same device.
PATTERNS: dict[str, list[str]] = {
    "solar_power": [r"(pv|solar)_?power(?!_?forecast)", r"(pv|solar).*power"],
    "solar_today": [r"(pv|solar).*(today|daily)", r"(today|daily).*(pv|solar)"],
    "solar_forecast": [r"(pv|solar)_forecast.*forecast_today", r"solcast.*today", r"forecast_today",
                       r"energy_production_today"],
    "solar_forecast_tomorrow": [r"(pv|solar)_forecast.*forecast_tomorrow", r"solcast.*tomorrow", r"forecast_tomorrow",
                                r"energy_production_tomorrow"],
    "battery_soc": [r"(^|_)soc($|_)", r"state_of_charge", r"battery_(level|percent|charge)"],
    "battery_power": [r"battery_power", r"battery.*power"],
    "grid_power": [r"grid_power", r"grid.*power"],
    "grid_import_today": [r"import.*(today|daily)", r"grid.*(today|daily)"],
    "grid_export_today": [r"export.*(today|daily)"],
    "home_power": [r"(load|house|home)_power", r"(house|home)_(load|consumption)", r"consumption_power"],
    "home_today": [r"(load|house|home|consumption).*(today|daily)"],
    "car_plug": [r"plug_status", r"(ev|car|vehicle|charger).*plug", r"plug.*(ev|car)", r"cable_(connected|state)"],
    "car_status": [r"(zappi|charger|wallbox|ohme|easee|evse)_status", r"(charger|charging|charge)_(status|state)"],
    "car_power": [r"zappi.*internal_load", r"(charger|wallbox|ohme|easee|evse|ev_charger).*power",
                  r"(ev|car).*charg\w*_power"],
    "car_soc": [r"ev_battery_level", r"(^|_)ev_(soc|state_of_charge)", r"(vehicle|car)_(soc|state_of_charge)",
                r"(tesla|ioniq|niro|leaf|id\d|enyaq|model_[3ysx]).*battery_level"],
    "car_range": [r"ev_range", r"(electric|battery|est)_range", r"(vehicle|car)_range"],
    "car_session": [r"charge_added_session", r"session_energy", r"charge_energy_added", r"energy_added"],
    "heat_pump_mode": [HEAT_PUMP_WORDS + r".*operation", HEAT_PUMP_WORDS + r".*(mode|state|status)$",
                       HEAT_PUMP_WORDS + r".*3_?way"],
    "heat_pump_power": [HEAT_PUMP_WORDS + r".*power(?!_factor)"],
    "heat_pump_today": [HEAT_PUMP_WORDS + r".*(today|daily)"],
    "heat_pump_flow": [HEAT_PUMP_WORDS + r".*(leaving_water|flow)_temp", r"(leaving_water|flow)_temp"],
    "heat_pump_return": [HEAT_PUMP_WORDS + r".*(return|inlet)_?(water_)?temp", r"(return|inlet)_water_temp"],
    "heat_pump_flow_rate": [HEAT_PUMP_WORDS + r".*(water_)?flow_?rate", r"water_flow_rate"],
    "inside_temp": [HEAT_PUMP_WORDS + r".*(room|indoor|inside).*temp", r"(indoor|inside)_temp", r"room_temp"],
    "heat_pump_tank": [HEAT_PUMP_WORDS + r".*(tank|dhw|hot_water).*temp", r"(dhw|hot_water)_tank.*temp"],
    "outdoor_temp": [HEAT_PUMP_WORDS + r".*outdoor.*temp"],
}
EXCLUDE: dict[str, str] = {
    "solar_power": r"forecast|predbat|estimate",
    "solar_today": r"forecast|predbat|tomorrow|remaining|estimate|cost",
    "solar_forecast": r"remaining|predbat|tomorrow|peak|cost|weather|power|d3|day_3",
    "solar_forecast_tomorrow": r"remaining|predbat|peak|cost|weather|power|d3|day_3",
    "heat_pump_flow_rate": r"gas|air|refrig",
    "inside_temp": r"target|setpoint|set_point|offset|outdoor|outside",
    "battery_soc": r"car|ev_|vehicle|e_niro|tesla|phone|predbat|target|reserve|cutoff|min|max",
    "battery_power": r"car|ev_|vehicle|predbat|rate|max|limit",
    "grid_power": r"predbat|limit|export_limit|zappi|eddi|ct",
    "grid_import_today": r"cost|predbat|battery|ppkwh",
    "grid_export_today": r"cost|predbat|compensation|battery",
    "home_power": r"predbat|median|average|forecast",
    "home_today": r"predbat|forecast|cost",
    "car_status": r"eddi|plug",
    "car_power": r"eddi|predbat|givac|battery",
    "car_soc": r"car_battery_level|12v|aux",
    "heat_pump_power": r"apparent|reactive|factor",
    "heat_pump_today": r"weekly|monthly|yearly|cost",
}
NEAR = {"solar_today": ("solar_power",), "battery_soc": ("battery_power",), "home_power": ("grid_power", "battery_power"),
        "home_today": ("grid_power", "battery_power"), "grid_import_today": ("grid_power",),
        "grid_export_today": ("grid_power",), "car_status": ("car_plug", "car_power"), "car_power": ("car_plug",),
        "car_range": ("car_soc",), "heat_pump_flow": ("heat_pump_mode",), "heat_pump_tank": ("heat_pump_mode",),
        "outdoor_temp": ("heat_pump_mode",), "heat_pump_return": ("heat_pump_flow",),
        "heat_pump_flow_rate": ("heat_pump_mode",), "inside_temp": ("heat_pump_mode",),
        "solar_forecast_tomorrow": ("solar_forecast",)}
SUM_SLOTS = ("heat_pump_today",)  # a heat pump often counts heating and hot water apart: add them up


def suggest(states: list[dict], prefs: dict | None) -> tuple[dict[str, list[str]], dict[str, bool]]:
    """Automatic entities for every slot (lists: some slots add several up) and sign flips."""
    by_id = {s["entity_id"]: s for s in states if isinstance(s, dict) and isinstance(s.get("entity_id"), str)
             and ENTITY_RE.match(s["entity_id"])}
    usable = {e: s for e, s in by_id.items() if s.get("state") not in ("unavailable",)}
    kinds = {e: kind_of(e, s) for e, s in usable.items()}
    words = {e: _words(e, s) for e, s in usable.items()}
    pref, flags = from_prefs(prefs)
    out: dict[str, list[str]] = {slot: [e] for slot, e in pref.items() if e in by_id}

    def match(slot: str) -> list[str]:
        kind = SLOTS[slot][0]
        excl = re.compile(EXCLUDE[slot]) if slot in EXCLUDE else None
        near = [_prefix(out[n][0]) for n in NEAR.get(slot, ()) if out.get(n)]
        for pat in PATTERNS.get(slot, []):
            rx = re.compile(pat)
            hits = [e for e, w in words.items() if (kinds[e] == kind or (kind == "number" and kinds[e] in ("number",)))
                    and rx.search(w) and not (excl and excl.search(w))
                    and not (slot.startswith("car") and CAR_EXCLUDE.search(w))]
            if hits:
                hits.sort(key=lambda e: (not any(e.split(".", 1)[1].startswith(p) for p in near), e.split(".", 1)[0] != "sensor",
                                         len(e), e))
                return hits
        return []

    for slot in SLOTS:
        if slot in out:
            continue
        if slot in PREDBAT:
            if PREDBAT[slot] in usable:
                out[slot] = [PREDBAT[slot]]
            continue
        if slot == "heat_pump_details":
            got = next((e for e, s in sorted(usable.items()) if e.startswith("sensor.") and _is_detail_source(s)), None)
            if got:
                out[slot] = [got]
            continue
        if slot == "heat_pump_power":
            got = _heat_pump_power(usable, kinds)
            if got:
                out[slot] = [got]
                continue
        hits = match(slot)
        if not hits:
            continue
        if slot in SUM_SLOTS:
            # Heating + hot water from the same device, else just one.
            brand = lambda e: e.split(".", 1)[1].split("_")[0]  # noqa: E731
            same = [e for e in hits if brand(e) == brand(hits[0])]
            out[slot] = same[:2] if len(same) == 2 else hits[:1]
        else:
            out[slot] = hits[:1]
    return out, flags


def _heat_pump_power(states: dict[str, dict], kinds: dict[str, str | None]) -> str | None:
    """A power sensor named like the meter an energy sensor called "<meter> Heat Pump ..." belongs to."""
    for e, s in states.items():
        name = _name(s, e)
        m = re.search(r"heat\s*pump", name, re.I)
        if not m or kinds.get(e) not in ("energy", "power"):
            continue
        meter = name[:m.start()].strip()
        if len(meter) < 4:
            continue
        for e2, s2 in states.items():
            n2 = _name(s2, e2)
            if kinds.get(e2) == "power" and n2.startswith(meter) and re.search(r"power$", n2.strip(), re.I) \
                    and not re.search(r"apparent|reactive|factor", n2, re.I):
                return e2
    return None


def effective(auto: dict[str, list[str]], auto_flags: dict[str, bool], conf: dict) -> dict:
    """The household's picks over the automatic ones: {entities: {slot: [entity...]}, battery_invert, grid_invert,
    auto: {slot: bool}}."""
    mine = conf.get("entities") or {}
    ents: dict[str, list[str]] = {}
    is_auto: dict[str, bool] = {}
    for slot in SLOTS:
        if slot in mine:
            ents[slot] = [mine[slot]] if mine[slot] else []
            is_auto[slot] = False
        else:
            ents[slot] = list(auto.get(slot) or [])
            is_auto[slot] = True
    flags = {f: bool(conf[f]) if isinstance(conf.get(f), bool) else bool(auto_flags.get(f, False)) for f in FLAGS}
    # A picked battery or grid sensor isn't the dashboard's, so the dashboard's sign doesn't apply to it.
    for f, slot in (("battery_invert", "battery_power"), ("grid_invert", "grid_power")):
        if not isinstance(conf.get(f), bool) and not is_auto[slot]:
            flags[f] = False
    return {"entities": ents, **flags, "auto": is_auto}


def watch_list(eff: dict) -> set[str]:
    return {e for es in eff["entities"].values() for e in es}


def candidates(states: list[dict]) -> dict[str, list[dict]]:
    """For Settings: entities by kind, with their current value."""
    out: dict[str, list[dict]] = {k: [] for k in ("power", "energy", "percent", "temperature", "number", "state")}
    for s in states:
        e = s.get("entity_id") if isinstance(s, dict) else None
        if not isinstance(e, str) or not ENTITY_RE.match(e):
            continue
        k = kind_of(e, s)
        if k is None:
            continue
        if k == "state" and e.startswith(("binary_sensor.", "switch.", "input_boolean.")):
            dc = str(_attrs(s).get("device_class") or "")
            if dc not in ("plug", "battery_charging", "power", "running", "connectivity") and not re.search(
                    r"(plug|charg|heat|pump|cable|running)", e):
                continue
        unit = _attrs(s).get("unit_of_measurement")
        out[k].append({"entity_id": e, "name": _name(s, e), "state": s.get("state"), "unit": unit or None})
    for rows in out.values():
        rows.sort(key=lambda r: r["name"].lower())
    return out


# ---------------------------------------------------------------- service

class EnergyService(home_security.SecurityService):
    """The security service's REST + WebSocket helpers, following the energy entities instead."""
    watch_re = ENTITY_RE
    subject = "the energy sensors"

    def __init__(self, *args, **kw) -> None:
        super().__init__(*args, **kw)
        self.auto: dict[str, list[str]] | None = None
        self.auto_flags: dict[str, bool] = {}
        self.all: list[dict] = []
        self.auto_at = -1e9
        self._auto_lock = asyncio.Lock()
        self.last_broadcast = 0.0
        self._later: asyncio.Task | None = None
        self.cop = CopDay(self._load_cop())
        self._cop_task: asyncio.Task | None = None
        self._cop_saved = 0.0

    @staticmethod
    def _load_cop() -> dict | None:
        with contextlib.suppress(Exception), db.connect() as c:
            return db.get_setting(c, COP_KEY, None)
        return None

    def save_cop(self) -> None:
        self._cop_saved = self.clock()
        with contextlib.suppress(Exception), db.connect() as c:
            db.set_setting(c, COP_KEY, self.cop.as_dict())

    async def sample_cop(self) -> None:
        """Add the last few seconds of heat out and electricity in to today's totals."""
        eff = await self.setup()
        ents = eff["entities"]
        if not ents.get("heat_pump_power"):
            return
        states = await self.states_for(sorted(watch_list(eff)))
        out = heat_output(eff, states)
        running = out["power"] is not None and out["power"] >= HEAT_PUMP_RUNNING_WATTS
        self.cop.sample(self.clock(), datetime.now(_zone()).date().isoformat(), out, running)
        if self.clock() - self._cop_saved >= COP_SAVE_EVERY:
            self.save_cop()

    async def _cop_loop(self) -> None:
        while True:
            try:
                await self.sample_cop()
            except asyncio.CancelledError:
                raise
            except Exception as e:  # Home Assistant away: try again next time
                log.debug("COP sample skipped: %s", media._describe(e))
            await asyncio.sleep(COP_SAMPLE_EVERY)

    def start_cop(self) -> None:
        if self._cop_task is None or self._cop_task.done():
            self._cop_task = asyncio.get_running_loop().create_task(self._cop_loop())

    async def stop_cop(self) -> None:
        if self._cop_task:
            self._cop_task.cancel()
            with contextlib.suppress(BaseException):
                await self._cop_task
            self._cop_task = None
            self.save_cop()

    async def find(self, force: bool = False) -> dict[str, list[str]]:
        async with self._auto_lock:
            if self.auto is not None and not force and self.clock() - self.auto_at < DISCOVERY_TTL:
                return self.auto
            try:
                states = await self.all_states()
            except Exception as e:
                self.found_error = "Home Assistant is unreachable"
                self.last_error = media._describe(e)
                if self.auto is not None:
                    return self.auto
                raise media.MediaError(self.found_error)
            prefs = None
            try:
                prefs, = await self._ws_commands({"type": "energy/get_prefs"})
            except Exception as e:
                log.info("Couldn't read Home Assistant's Energy dashboard: %s", media._describe(e))
            self.auto, self.auto_flags = suggest(states, prefs if isinstance(prefs, dict) else None)
            self.all = states
            self.auto_at = self.clock()
            self.found_error = None
            for s in states:
                if isinstance(s, dict) and s.get("entity_id") in self.watched | set(self.states):
                    self._store(s["entity_id"], s)
            self._all_at = self.clock()
            return self.auto

    async def setup(self, force: bool = False) -> dict:
        auto = await self.find(force)
        with db.connect() as c:
            conf = saved(c)
        eff = effective(auto, self.auto_flags, conf)
        self.set_watched(watch_list(eff))
        return eff


async def overview(svc: EnergyService) -> dict:
    """GET /api/energy."""
    eff = await svc.setup()
    states = await svc.states_for(sorted(watch_list(eff)))
    house = build(eff, states, svc.cop.as_dict() if svc.cop.day else None)
    return {"configured": True, "reachable": svc.last_error is None, "error": svc.found_error,
            "updated": media.utc_now_iso(), **house}


def not_connected(error: str) -> dict:
    return {"configured": False, "reachable": False, "error": error, "updated": None, "solar": None, "battery": None,
            "grid": None, "home": None, "car": None, "heat_pump": None, "temperatures": None, "plan": None}


# ---------------------------------------------------------------- module-level service

_service: EnergyService | None = None
_configured = False


def from_env() -> EnergyService | None:
    import os

    token = os.environ.get("MOONLIGHT_HA_TOKEN") or os.environ.get("SUPERVISOR_TOKEN") or ""
    if not token:
        return None
    url = os.environ.get("MOONLIGHT_HA_URL") or media.SUPERVISOR_API
    return EnergyService(url, token, on_change=_changed)


async def _changed() -> None:
    """Power changes every few seconds: tell the screens at most every BROADCAST_EVERY seconds."""
    from .common import hub

    svc = service()
    if svc is None:
        await hub.broadcast("energy")
        return
    wait = BROADCAST_EVERY - (time.monotonic() - svc.last_broadcast)
    if wait > 0:
        if svc._later is None or svc._later.done():
            async def later():
                await asyncio.sleep(wait)
                svc.last_broadcast = time.monotonic()
                await hub.broadcast("energy")
            svc._later = asyncio.get_running_loop().create_task(later())
        return
    svc.last_broadcast = time.monotonic()
    await hub.broadcast("energy")


def set_service(svc: EnergyService | None) -> None:
    global _service, _configured
    _service, _configured = svc, True


def reset() -> None:
    global _service, _configured
    _service, _configured = None, False


def service() -> EnergyService | None:
    global _service, _configured
    if not _configured:
        _service, _configured = from_env(), True
    return _service


async def settings_changed() -> None:
    from .common import hub

    svc = service()
    if svc is not None:
        with contextlib.suppress(Exception):
            await svc.setup()
    await hub.broadcast("energy")


async def start() -> None:
    svc = service()
    if svc is None:
        return
    with contextlib.suppress(Exception):
        await svc.setup()
    svc.start()
    svc.start_cop()


async def stop() -> None:
    svc = service()
    if svc is not None:
        if svc._later:
            svc._later.cancel()
        await svc.stop_cop()
        await svc.stop()
