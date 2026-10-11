import { useEffect, useState } from "react";
import { ApiError, Weather } from "../api/types";
import { useApp } from "../state";
import { Segmented } from "../components/ui";
import { ScreensaverPanel, ScreensPanel } from "./DisplaysSettings";
import { CalendarsPanel } from "./CalendarsSettings";
import { FamilyPanel } from "./FamilySettings";
import { MusicPanel } from "./MusicSettings";

export function SettingsView({ onScreensaver }: { onScreensaver: () => void }) {
  const { api, people, settings, askPin, toast, layout } = useApp();
  const noFamily = people.length === 0;
  const [wx, setWx] = useState<Weather | null>(null);
  useEffect(() => { api.weather().then(setWx).catch(() => setWx(null)); }, [api]);
  const wxSource = !wx ? "…" : wx.source === "homeassistant" ? `Home Assistant: ${wx.entity}` : "Demo forecast";
  async function setWeekStart(v: "monday" | "sunday") {
    const pin = await askPin("Change the first day of the week");
    if (!pin) return;
    try { await api.updateSettings({ week_start: v, pin }); toast("Saved"); }
    catch (e) { toast(e instanceof ApiError ? e.message : "Couldn't save"); }
  }
  async function changePin() {
    // With no PIN yet, the new PIN is also the one that authorises the change (see PATCH /api/settings).
    let current: string | null = null;
    if (settings?.pin_set) {
      current = await askPin("Enter your current PIN");
      if (!current) return;
    }
    const next = await askPin("Choose a new 4-digit PIN", { check: false });
    if (!next) return;
    const again = await askPin("Enter the new PIN again", { check: false });
    if (!again) return;
    if (again !== next) { toast("The PINs didn't match. Nothing changed."); return; }
    try { await api.updateSettings({ pin: current ?? next, new_pin: next }); toast("Parent PIN changed"); }
    catch (e) { toast(e instanceof ApiError ? e.message : "Couldn't change the PIN"); }
  }
  return (
    <div className="settings">
      <div className="toolbar"><div className="toolbar-l"><h1 className="toolbar-title">Settings</h1></div></div>
      <div className="settings-body">
        <CalendarsPanel />
        <FamilyPanel first={noFamily} />
        <section className="panel">
          <h2 className="panel-title">Display</h2>
          <div className="set-row"><span>Week starts on</span>
            <Segmented value={settings?.week_start ?? "monday"} onChange={setWeekStart} options={[{ value: "monday", label: "Monday" }, { value: "sunday", label: "Sunday" }]} />
          </div>
          <div className="set-row"><span>This screen</span><b>{layout === "hallway" ? "Hallway (27 in)" : layout === "kitchen" ? "Kitchen (10 in)" : "Phone"}</b></div>
          <div className="set-row"><span>Weather</span><b>{wxSource}</b></div>
          <div className="set-row"><span>Parent PIN</span>
            <span className="set-pin"><b>{settings?.pin_set ? "Set" : "Not set"}</b>
              <button className="btn ghost small" onClick={changePin}>{settings?.pin_set ? "Change" : "Set PIN"}</button></span>
          </div>
        </section>
        <ScreensPanel />
        <ScreensaverPanel onScreensaver={onScreensaver} />
        <MusicPanel />
        {api.mode === "demo" && api.resetDemo && (
          <section className="panel">
            <h2 className="panel-title">Demo</h2>
            <p className="muted">This preview runs on a demo family in your browser.</p>
            <div className="set-row"><span>Demo data</span><button className="btn ghost" onClick={async () => { await api.resetDemo!(); toast("Demo data reset"); }}>Reset</button></div>
          </section>
        )}
      </div>
    </div>
  );
}
