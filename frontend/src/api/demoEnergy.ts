// Demo-mode energy: a sunny afternoon with solar on the roof, a home battery charging, the car taking the spare solar
// and the heat pump warming the house. The numbers drift a little every few seconds, as real sensors do.
import { Api, ApiError, EnergyCandidate, EnergyKind, EnergyOptions, EnergyOverview, EnergySettings, EnergySettingsPatch, EnergySlot, Topic } from "./types";

type Extras = Pick<Api, "energy" | "energyOptions">;

const SLOTS: Record<EnergySlot, [EnergyKind, string, string]> = {
  solar_power: ["power", "sensor.inverter_pv_power", "Inverter PV power"],
  solar_today: ["energy", "sensor.inverter_pv_energy_today", "Inverter PV energy today"],
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
  heat_pump_mode: ["state", "sensor.heat_pump_operation", "Heat pump operation"],
  heat_pump_power: ["power", "sensor.heat_pump_power", "Heat pump power"],
  heat_pump_today: ["energy", "sensor.heat_pump_energy_today", "Heat pump energy today"],
  heat_pump_flow: ["temperature", "sensor.heat_pump_flow_temperature", "Heat pump flow temperature"],
  heat_pump_tank: ["temperature", "sensor.hot_water_tank_temperature", "Hot water tank temperature"],
  outdoor_temp: ["temperature", "sensor.heat_pump_outdoor_temperature", "Heat pump outdoor temperature"],
};
const GROUP = (s: EnergySlot) => (s.startsWith("heat_pump") || s === "outdoor_temp" ? "heat_pump" : s.split("_")[0]) as EnergyOptions["slots"][EnergySlot]["group"];

export function demoEnergy(emit: (...t: Topic[]) => void, settings: () => EnergySettings | undefined): Extras {
  let tick = 0;
  setInterval(() => { tick++; emit("energy"); }, 5000);
  const wobble = (base: number, amount: number, phase: number) => Math.round(base + Math.sin(tick / 2 + phase) * amount);
  const on = (slot: EnergySlot) => (settings()?.entities?.[slot] ?? SLOTS[slot][1]) !== "";
  return {
    async energy(): Promise<EnergyOverview> {
      const solar = wobble(3150, 180, 0);
      const hp = wobble(780, 40, 1);
      const car = wobble(2150, 120, 2);
      const battery = -wobble(900, 60, 3); // charging
      const home = 1050 + hp + car + wobble(0, 40, 4);
      const grid = home - solar - battery; // what solar and the battery don't cover comes from the grid
      const g = settings()?.grid_invert ? -grid : grid;
      const b = settings()?.battery_invert ? -battery : battery;
      return {
        configured: true, reachable: true, error: null, updated: new Date().toISOString(),
        solar: on("solar_power") || on("solar_today") ? { power: on("solar_power") ? solar : null, today: on("solar_today") ? 11.4 : null } : null,
        battery: on("battery_soc") || on("battery_power") ? { soc: on("battery_soc") ? 72 : null, power: on("battery_power") ? b : null, state: on("battery_power") ? (b < -30 ? "charging" : b > 30 ? "discharging" : "idle") : null } : null,
        grid: on("grid_power") ? { power: g, state: g > 30 ? "importing" : g < -30 ? "exporting" : "idle", import_today: on("grid_import_today") ? 6.2 : null, export_today: on("grid_export_today") ? 3.9 : null } : null,
        home: on("home_power") || on("home_today") ? { power: on("home_power") ? home : null, today: on("home_today") ? 14.8 : null, computed: false } : null,
        car: on("car_plug") || on("car_status") || on("car_power") || on("car_soc")
          ? { plugged_in: true, charging: true, status: "Charging", power: on("car_power") ? car : null, soc: on("car_soc") ? 64 : null, range: on("car_range") ? 168 : null, range_unit: "mi", session: on("car_session") ? 5.3 : null }
          : null,
        heat_pump: on("heat_pump_mode") || on("heat_pump_power")
          ? { running: true, doing: "Heating the house", power: on("heat_pump_power") ? hp : null, today: on("heat_pump_today") ? 6.1 : null, flow_temp: on("heat_pump_flow") ? 34.5 : null, tank_temp: on("heat_pump_tank") ? 47 : null, outdoor_temp: on("outdoor_temp") ? 9 : null }
          : null,
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
