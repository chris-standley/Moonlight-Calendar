// Demo-mode energy: a sunny afternoon with solar on the roof, a home battery charging, the car taking the spare solar
// and the heat pump warming the house. The numbers drift a little every few seconds, as real sensors do.
import { Api, ApiError, EnergyCandidate, EnergyKind, EnergyOptions, EnergyOverview, EnergySettings, EnergySettingsPatch, EnergySlot, Topic } from "./types";

type Extras = Pick<Api, "energy" | "energyOptions">;

const SLOTS: Record<EnergySlot, [EnergyKind, string, string]> = {
  solar_power: ["power", "sensor.inverter_pv_power", "Inverter PV power"],
  solar_today: ["energy", "sensor.inverter_pv_energy_today", "Inverter PV energy today"],
  solar_forecast: ["energy", "sensor.solar_forecast_today", "Solar forecast today"],
  solar_forecast_tomorrow: ["energy", "sensor.solar_forecast_tomorrow", "Solar forecast tomorrow"],
  battery_soc: ["percent", "sensor.inverter_soc", "Inverter battery SOC"],
  battery_power: ["power", "sensor.inverter_battery_power", "Inverter battery power"],
  grid_power: ["power", "sensor.inverter_grid_power", "Inverter grid power"],
  grid_import_today: ["energy", "sensor.inverter_import_today", "Inverter import today"],
  grid_export_today: ["energy", "sensor.inverter_export_today", "Inverter export today"],
  home_power: ["power", "sensor.inverter_load_power", "Inverter load power"],
  home_today: ["energy", "sensor.inverter_load_today", "Inverter load today"],
  car_plug: ["state", "sensor.charger_plug_status", "Charger plug status"],
  car_status: ["state", "sensor.charger_status", "Charger status"],
  car_power: ["power", "sensor.charger_power", "Charger power"],
  car_soc: ["percent", "sensor.car_ev_battery_level", "Car EV battery level"],
  car_range: ["number", "sensor.car_ev_range", "Car EV range"],
  car_session: ["energy", "sensor.charger_session_energy", "Charger session energy"],
  car_limit: ["percent", "number.car_charge_limit", "Car charge limit"],
  car_ready: ["state", "select.car_ready_time", "Car ready time"],
  heat_pump_mode: ["state", "sensor.heat_pump_operation", "Heat pump operation"],
  heat_pump_power: ["power", "sensor.heat_pump_power", "Heat pump power"],
  heat_pump_today: ["energy", "sensor.heat_pump_energy_today", "Heat pump energy today"],
  heat_pump_flow: ["temperature", "sensor.heat_pump_flow_temperature", "Heat pump flow temperature"],
  heat_pump_return: ["temperature", "sensor.heat_pump_return_temperature", "Heat pump return temperature"],
  heat_pump_flow_rate: ["number", "sensor.heat_pump_flow_rate", "Heat pump flow rate"],
  heat_pump_details: ["state", "sensor.heat_pump_controller", "Heat pump controller"],
  inside_temp: ["temperature", "sensor.living_room_temperature", "Living room temperature"],
  outdoor_temp: ["temperature", "sensor.heat_pump_outdoor_temperature", "Heat pump outdoor temperature"],
  heat_pump_tank: ["temperature", "sensor.hot_water_tank_temperature", "Hot water tank temperature"],
  heating_target: ["temperature", "sensor.heating_set_point", "Heating set point"],
  tank_target: ["temperature", "sensor.dhw_setpoint", "Hot water set point"],
  inside_humidity: ["percent", "sensor.hallway_humidity", "Hallway humidity"],
  outside_humidity: ["percent", "sensor.outside_humidity", "Outside humidity"],
  plan_status: ["state", "predbat.status", "Predbat status"],
  plan_cost_today: ["number", "predbat.cost_today", "Cost so far today"],
  plan_rate_now: ["number", "predbat.rates", "Import rates"],
  plan_rate_export: ["number", "predbat.rates_export", "Export rates"],
  plan_battery_hours: ["number", "predbat.battery_hours_left", "Predicted battery hours left"],
  plan_charge_start: ["state", "predbat.best_charge_start", "Predicted charge start time"],
  plan_charge_end: ["state", "predbat.best_charge_end", "Predicted charge end time"],
  plan_cheap_start: ["state", "predbat.low_rate_start", "Next low rate start"],
  plan_cheap_end: ["state", "predbat.low_rate_end", "Next low rate end"],
  cheap_off_peak: ["state", "binary_sensor.octopus_off_peak", "Octopus off peak"],
  cheap_dispatches: ["state", "binary_sensor.octopus_intelligent_dispatching", "Octopus intelligent dispatching"],
};
const GROUP = (s: EnergySlot) => (["inside_temp", "outdoor_temp", "heat_pump_tank", "heating_target", "tank_target", "inside_humidity", "outside_humidity"].includes(s) ? "temperatures"
  : s.startsWith("heat_pump") ? "heat_pump" : s.split("_")[0]) as EnergyOptions["slots"][EnergySlot]["group"];

/** Today at hh:mm local, as ISO with the offset (the way Home Assistant sends times). */
function at(h: number, m: number, days = 0): string {
  const d = new Date(); d.setHours(h, m, 0, 0); d.setDate(d.getDate() + days);
  const off = -d.getTimezoneOffset(), sign = off >= 0 ? "+" : "-", pad = (n: number) => String(Math.floor(Math.abs(n))).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(h)}:${pad(m)}:00${sign}${pad(off / 60)}:${pad(off % 60)}`;
}

export function demoEnergy(emit: (...t: Topic[]) => void, settings: () => EnergySettings | undefined): Extras {
  let tick = 0;
  setInterval(() => { tick++; emit("energy"); }, 5000);
  const wobble = (base: number, amount: number, phase: number) => Math.round(base + Math.sin(tick / 2 + phase) * amount);
  const on = (slot: EnergySlot) => (settings()?.entities?.[slot] ?? SLOTS[slot][1]) !== "";
  return {
    async energy(): Promise<EnergyOverview> {
      // The sun follows the clock: up from 7:40 to 17:30, strongest at lunchtime.
      const now = new Date(), hour = now.getHours() + now.getMinutes() / 60;
      const sun = Math.max(0, Math.sin(Math.PI * (hour - 7.67) / (17.5 - 7.67)));
      const solar = sun > 0 ? Math.round(3600 * sun + Math.sin(tick / 2) * 180 * sun) : 0;
      const today = +(11.4 * Math.min(1, Math.max(0, (hour - 7.67) / (17.5 - 7.67)))).toFixed(1);
      const hp = wobble(780, 40, 1);
      const car = solar > 1500 ? wobble(2150, 120, 2) : 0;
      const battery = solar > 1500 ? -wobble(900, 60, 3) : wobble(450, 40, 3); // charging from spare solar, else helping out
      const home = 1050 + hp + car + wobble(0, 40, 4);
      const grid = home - solar - battery; // what solar and the battery don't cover comes from the grid
      const g = settings()?.grid_invert ? -grid : grid;
      const b = settings()?.battery_invert ? -battery : battery;
      const heat = hp * (3.9 + Math.sin(tick / 3) * 0.2);
      return {
        configured: true, reachable: true, error: null, updated: new Date().toISOString(),
        solar: on("solar_power") || on("solar_today")
          ? { power: on("solar_power") ? solar : null, today: on("solar_today") ? today : null, forecast_today: on("solar_forecast") ? 12.6 : null,
            forecast_tomorrow: on("solar_forecast_tomorrow") ? 9.8 : null, starts: on("solar_forecast") ? at(7, 40) : null, ends: on("solar_forecast") ? at(17, 30) : null }
          : null,
        battery: on("battery_soc") || on("battery_power") ? { soc: on("battery_soc") ? 72 : null, power: on("battery_power") ? b : null, state: on("battery_power") ? (b < -30 ? "charging" : b > 30 ? "discharging" : "idle") : null } : null,
        grid: on("grid_power") ? { power: g, state: g > 30 ? "importing" : g < -30 ? "exporting" : "idle", import_today: on("grid_import_today") ? 6.2 : null, export_today: on("grid_export_today") ? 3.9 : null } : null,
        home: on("home_power") || on("home_today") ? { power: on("home_power") ? home : null, today: on("home_today") ? 14.8 : null, computed: false } : null,
        car: on("car_plug") || on("car_status") || on("car_power") || on("car_soc")
          ? { plugged_in: true, charging: car > 0, status: car > 0 ? "Charging" : "Plugged in · waiting", power: on("car_power") ? car : null, soc: on("car_soc") ? 64 : null, range: on("car_range") ? 168 : null, range_unit: "mi", session: on("car_session") ? 5.3 : null,
            limit: on("car_limit") ? 80 : null, ready: on("car_ready") ? at(7, 0, hour >= 7 ? 1 : 0) : null }
          : null,
        heat_pump: on("heat_pump_mode") || on("heat_pump_power")
          ? { running: true, doing: "Heating the house", power: on("heat_pump_power") ? hp : null, today: on("heat_pump_today") ? 6.1 : null, flow_temp: on("heat_pump_flow") ? 34.5 : null,
            heat: Math.round(heat), cop: +(heat / hp).toFixed(1), cop_today: { heating: 3.8, hot_water: 2.7, overall: 3.5 } }
          : null,
        temperatures: on("inside_temp") || on("outdoor_temp") || on("heat_pump_tank")
          ? { inside: on("inside_temp") ? 19.5 : null, outside: on("outdoor_temp") ? 9 : null, tank: on("heat_pump_tank") ? 47 : null,
            heating_target: on("heating_target") ? 19 : null, tank_target: on("tank_target") ? 46 : null,
            inside_humidity: on("inside_humidity") ? 55 : null, outside_humidity: on("outside_humidity") ? 94 : null }
          : null,
        plan: on("plan_status")
          ? { status: "Demand", cost_today: 138, cost_unit: "p", rate_now: hour >= 23.5 || hour < 5.5 ? 6.6 : 34.69, rate_export: 12, rate_unit: "p", battery_hours: 4.5,
            charge: { start: at(23, 30), end: at(5, 30, 1), rate: 6.6 }, cheap: { start: at(23, 30), end: at(5, 30, 1), rate: 6.6 } }
          : null,
        tariff: on("cheap_off_peak") || on("cheap_dispatches")
          ? { cheap_now: hour >= 23.5 || hour < 6, cheap_until: hour >= 23.5 || hour < 6 ? at(6, 0, hour >= 23.5 ? 1 : 0) : null,
            next: hour >= 23.5 || hour < 6 ? null : { start: at(23, 30), end: at(6, 0, 1) }, bonus: [{ start: at(5, 30, hour >= 6 ? 1 : 0), end: at(6, 0, hour >= 6 ? 1 : 0) }], dispatching: false }
          : null,
        sun: { night: hour >= 18 || hour < 7, next: hour >= 18 ? at(7, 0, 1) : hour < 7 ? at(7, 0) : at(18, 0) },
      };
    },
    async energyOptions(): Promise<EnergyOptions> {
      const mine = settings()?.entities ?? {};
      const candidates: Record<EnergyKind, EnergyCandidate[]> = { power: [], energy: [], percent: [], temperature: [], number: [], state: [] };
      for (const [kind, entity_id, name] of Object.values(SLOTS)) candidates[kind].push({ entity_id, name, state: "1", unit: null });
      const slots = Object.fromEntries((Object.keys(SLOTS) as EnergySlot[]).map((s) => {
        const auto = !(s in mine);
        const ent = auto ? [SLOTS[s][1]] : mine[s] ? [mine[s]!] : [];
        return [s, { kind: SLOTS[s][0], group: GROUP(s), entities: ent, auto, suggested: [SLOTS[s][1]] }];
      })) as EnergyOptions["slots"];
      return { slots, battery_invert: !!settings()?.battery_invert, grid_invert: !!settings()?.grid_invert, candidates };
    },
  };
}

/** Settings > Energy in the demo: the same rules as the add-on. */
export function applyEnergyPatch(cur: EnergySettings | undefined, patch: EnergySettingsPatch): EnergySettings {
  const next: EnergySettings = { ...cur, entities: { ...cur?.entities } };
  for (const [slot, v] of Object.entries(patch.entities ?? {}) as [EnergySlot, string | null][]) {
    if (!(slot in SLOTS)) throw new ApiError(400, `energy.entities: ${slot} isn't something Moonlight shows`);
    if (v === null) delete next.entities![slot];
    else next.entities![slot] = v;
  }
  for (const f of ["battery_invert", "grid_invert"] as const) {
    if (patch[f] === null) delete next[f];
    else if (patch[f] !== undefined) next[f] = patch[f]!;
  }
  return next;
}
