import { useCallback, useEffect, useState } from "react";
import { ApiError, Layout, SecurityOptions, SecuritySettingsPatch, STYLE_LABEL } from "../api/types";
import { useApp } from "../state";
import { Sheet } from "../components/ui";

const STYLES: Layout[] = ["large", "compact", "phone"];

/** Settings › Security: which alarm, which cameras (and their person sensors), and where people pop up. */
export function SecurityPanel() {
  const { api, settings, askPin, toast } = useApp();
  const [opts, setOpts] = useState<SecurityOptions | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pickAlarm, setPickAlarm] = useState(false);
  const load = useCallback((refresh = false) => {
    api.securityOptions(refresh).then((o) => { setOpts(o); setError(null); })
      .catch((e) => setError(e instanceof ApiError ? e.message : "Couldn't reach Home Assistant"));
  }, [api]);
  useEffect(() => { load(); }, [load, settings?.security]);

  async function save(security: SecuritySettingsPatch, why: string) {
    const pin = await askPin(why);
    if (!pin) return false;
    try { await api.updateSettings({ security, pin }); toast("Saved"); return true; }
    catch (e) { toast(e instanceof ApiError ? e.message : "Couldn't save"); return false; }
  }
  async function test(camera: string) {
    const pin = await askPin("Test the pop-up");
    if (!pin) return;
    try { await api.testSecurityAlert(camera, pin); toast("Popping it up on the screens for 20 seconds"); }
    catch (e) { toast(e instanceof ApiError ? e.message : "Couldn't test it"); }
  }

  if (error && !opts) {
    return (
      <section className="panel">
        <h2 className="panel-title">Security</h2>
        <p className="muted connect-note">{error}. The alarm and cameras come from Home Assistant, so this needs Moonlight running as the add-on.</p>
      </section>
    );
  }
  const alarmName = !opts ? "…" : opts.alarm_entity ? (opts.panels.find((p) => p.entity_id === opts.alarm_entity)?.name ?? opts.alarm_entity) : "None";
  const popup = opts?.popup ?? { large: true, compact: true, phone: false };
  return (
    <section className="panel">
      <h2 className="panel-title">Security</h2>
      <p className="muted connect-note">The alarm, its sensors and the cameras, from Home Assistant. When a camera sees a person, its
        live video pops up in a corner of the screens (or takes the screensaver photo's place) until they've gone.</p>
      <div className="set-row"><span>Alarm</span>
        <span className="set-pin"><b>{alarmName}</b><button className="btn ghost small" onClick={() => setPickAlarm(true)} disabled={!opts}>Change</button></span>
      </div>
      <div className="set-row"><span>Sensors</span>
        <b>{!opts ? "…" : opts.sensors_source === "alarmo" ? `${opts.sensor_count} from Alarmo` : "Alarmo not found"}</b>
      </div>
      <div className="set-row"><span>Pop up people on</span>
        <span className="set-pin">
          {STYLES.map((l) => (
            <button key={l} className={"chip-btn" + (popup[l] ? " on" : "")} disabled={!opts}
              onClick={() => save({ popup: { [l]: !popup[l] } }, "Change where people pop up")}>{STYLE_LABEL[l]}</button>
          ))}
        </span>
      </div>
      <h3 className="sec-set-sub">Cameras <button className="btn ghost small" onClick={() => load(true)}>Look again</button></h3>
      {opts && opts.cameras.length === 0 && <div className="screens-empty">Home Assistant has no cameras yet. Add the UniFi Protect integration there.</div>}
      {opts?.cameras.map((c) => (
        <div key={c.entity_id} className="sec-set-cam">
          <div className="sec-set-cam-top">
            <span className="player-main"><b>{c.name}</b><span>{c.entity_id}{c.available ? "" : " · offline"}</span></span>
            {c.show && c.person && <button className="btn ghost small" onClick={() => test(c.entity_id)}>Test pop-up</button>}
            <button className={"toggle" + (c.show ? " on" : "")} aria-pressed={c.show} aria-label={`Show ${c.name}`}
              onClick={() => save({ cameras: { [c.entity_id]: { show: !c.show } } }, c.show ? "Hide a camera" : "Show a camera")}><span /></button>
          </div>
          {c.show && (
            <label className="sec-set-person"><span>Pop up when</span>
              <select className="input" value={c.auto_person ? "auto" : c.person}
                onChange={(e) => save({ cameras: { [c.entity_id]: { person: e.target.value === "auto" ? null : e.target.value } } }, "Change when a camera pops up")}>
                <option value="auto">{c.default_person ? `Auto: ${opts.person_sensors.find((p) => p.entity_id === c.default_person)?.name ?? c.default_person}` : "Auto: none found"}</option>
                {opts.person_sensors.map((p) => <option key={p.entity_id} value={p.entity_id}>{p.name}</option>)}
                <option value="">Never</option>
              </select>
            </label>
          )}
        </div>
      ))}
      {pickAlarm && opts && (
        <Sheet title="Alarm" onClose={() => setPickAlarm(false)}>
          <div className="player-list">
            {opts.panels.map((p) => (
              <button key={p.entity_id} className={"player-row" + (opts.alarm_entity === p.entity_id ? " on" : "")}
                onClick={async () => { if (await save({ alarm_entity: p.entity_id }, "Change the alarm")) setPickAlarm(false); }}>
                <span className="player-main"><b>{p.name}</b><span>{p.alarmo ? "Alarmo · " : ""}{p.entity_id}</span></span>
              </button>
            ))}
            <button className={"player-row" + (opts.alarm_entity === "" ? " on" : "")}
              onClick={async () => { if (await save({ alarm_entity: "" }, "Change the alarm")) setPickAlarm(false); }}>
              <span className="player-main"><b>None</b><span>Show only the sensors and cameras</span></span>
            </button>
          </div>
        </Sheet>
      )}
    </section>
  );
}
