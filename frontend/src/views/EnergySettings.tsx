import { useCallback, useEffect, useState } from "react";
import { ApiError, EnergyCandidate, EnergyGroup, EnergyOptions, EnergySettingsPatch, EnergySlot } from "../api/types";
import { useApp } from "../state";

const GROUPS: { key: EnergyGroup; label: string; slots: [EnergySlot, string][] }[] = [
  { key: "solar", label: "Solar", slots: [["solar_power", "Power now"], ["solar_today", "Today"], ["solar_forecast", "Forecast today"],
    ["solar_forecast_tomorrow", "Forecast tomorrow"]] },
  { key: "battery", label: "Battery", slots: [["battery_soc", "Charge level"], ["battery_power", "Power in or out"]] },
  { key: "grid", label: "Grid", slots: [["grid_power", "Power in or out"], ["grid_import_today", "Bought today"], ["grid_export_today", "Sold today"]] },
  { key: "home", label: "Home", slots: [["home_power", "Using now"], ["home_today", "Used today"]] },
  { key: "car", label: "Car", slots: [["car_plug", "Plugged in"], ["car_status", "Charger status"], ["car_power", "Charging power"],
    ["car_soc", "Car battery"], ["car_range", "Range"], ["car_session", "Added this charge"]] },
  { key: "heat_pump", label: "Heat pump", slots: [["heat_pump_mode", "What it's doing"], ["heat_pump_power", "Power"], ["heat_pump_today", "Used today"],
    ["heat_pump_flow", "Flow temperature"], ["heat_pump_return", "Return temperature"], ["heat_pump_flow_rate", "Water flow rate"],
    ["heat_pump_details", "Controller readings (ESPAltherma)"]] },
  { key: "temperatures", label: "Temperatures", slots: [["inside_temp", "Inside"], ["heat_pump_tank", "Hot water tank"]] },
  { key: "plan", label: "Predbat", slots: [["plan_status", "Status"], ["plan_cost_today", "Cost today"], ["plan_rate_now", "Price now"],
    ["plan_rate_export", "Export price"], ["plan_battery_hours", "Battery hours left"], ["plan_charge_start", "Battery charge starts"],
    ["plan_charge_end", "Battery charge ends"], ["plan_cheap_start", "Cheap rate starts"], ["plan_cheap_end", "Cheap rate ends"]] },
];

const reading = (c: EnergyCandidate | undefined) => (c?.state == null ? "" : ` (${c.state}${c.unit ? ` ${c.unit}` : ""})`);

/** Settings › Energy: which Home Assistant entity fills each part of the house picture. */
export function EnergyPanel() {
  const { api, settings, askPin, toast } = useApp();
  const [opts, setOpts] = useState<EnergyOptions | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback((refresh = false) => {
    api.energyOptions(refresh).then((o) => { setOpts(o); setError(null); })
      .catch((e) => setError(e instanceof ApiError ? e.message : "Couldn't reach Home Assistant"));
  }, [api]);
  useEffect(() => { load(); }, [load, settings?.energy]);

  async function save(energy: EnergySettingsPatch, why: string) {
    const pin = await askPin(why);
    if (!pin) return;
    try { await api.updateSettings({ energy, pin }); toast("Saved"); }
    catch (e) { toast(e instanceof ApiError ? e.message : "Couldn't save"); }
  }

  if (error && !opts) {
    return (
      <section className="panel">
        <h2 className="panel-title">Energy</h2>
        <p className="muted connect-note">{error}. Energy comes from Home Assistant, so this needs Moonlight running as the add-on.</p>
      </section>
    );
  }
  const all = opts ? Object.values(opts.candidates).flat() : [];
  const byId = new Map(all.map((c) => [c.entity_id, c]));
  const nameOf = (ids: string[]) => ids.map((e) => byId.get(e)?.name ?? e).join(" + ");
  return (
    <section className="panel">
      <h2 className="panel-title">Energy</h2>
      <p className="muted connect-note">The house picture in Energy reads these Home Assistant sensors. Most are found on their own (from
        Home Assistant's Energy dashboard first); pick any that are wrong, or None to leave something out.</p>
      {!opts && <p className="muted">Looking in Home Assistant…</p>}
      {opts && GROUPS.map((g) => (
        <div key={g.key} className="en-set-group">
          <h3 className="sec-set-sub">{g.label}</h3>
          {g.slots.map(([slot, label]) => {
            const s = opts.slots[slot];
            const choices = s.kind === "number" ? [...opts.candidates.number, ...opts.candidates.percent] : opts.candidates[s.kind];
            return (
              <label key={slot} className="en-set-row"><span>{label}</span>
                <select className="input" value={s.auto ? "auto" : s.entities[0] ?? ""}
                  onChange={(e) => save({ entities: { [slot]: e.target.value === "auto" ? null : e.target.value } }, `Change ${g.label.toLowerCase()}: ${label.toLowerCase()}`)}>
                  <option value="auto">{s.suggested.length ? `Auto: ${nameOf(s.suggested)}${s.suggested.length === 1 ? reading(byId.get(s.suggested[0])) : ""}` : "Auto: none found"}</option>
                  <option value="">None</option>
                  {!s.auto && s.entities[0] && !choices.some((c) => c.entity_id === s.entities[0]) && <option value={s.entities[0]}>{s.entities[0]}</option>}
                  {choices.map((c) => <option key={c.entity_id} value={c.entity_id}>{c.name}{reading(c)}</option>)}
                </select>
              </label>
            );
          })}
          {(g.key === "battery" || g.key === "grid") && (() => {
            const flag = g.key === "battery" ? "battery_invert" : "grid_invert";
            return (
              <div className="set-row"><span>{g.key === "battery" ? "Flip direction (sensor is positive when charging)" : "Flip direction (sensor is positive when selling)"}</span>
                <button className={"toggle" + (opts[flag] ? " on" : "")} aria-pressed={opts[flag]} aria-label={`Flip the ${g.label.toLowerCase()} direction`}
                  onClick={() => save({ [flag]: !opts[flag] }, `Flip the ${g.label.toLowerCase()} direction`)}><span /></button>
              </div>
            );
          })()}
        </div>
      ))}
      {opts && <div className="set-row"><span>New sensors in Home Assistant?</span><button className="btn ghost small" onClick={() => load(true)}>Look again</button></div>}
    </section>
  );
}
