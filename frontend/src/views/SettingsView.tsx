import { useEffect, useState } from "react";
import { ApiError, STYLE_LABEL, Theme, Weather } from "../api/types";
import { useApp, useData } from "../state";
import { Segmented } from "../components/ui";
import { WeatherIcon } from "../components/icons";
import { ScreensaverPanel, ScreensPanel } from "./DisplaysSettings";
import { CalendarsPanel } from "./CalendarsSettings";
import { FamilyPanel } from "./FamilySettings";
import { WeatherPicker } from "./WeatherSettings";
import { HolidayPicker } from "./HolidaySettings";
import { RecipesPanel } from "./RecipeSettings";
import { NurseryPanel } from "./NurserySettings";
import { SecurityPanel } from "./SecuritySettings";
import { EnergyPanel } from "./EnergySettings";
import { MusicPanel } from "./MusicSettings";
import { useHolidayRegionName } from "../components/holidays";

export function SettingsView({ onScreensaver }: { onScreensaver: () => void }) {
  const { api, people, settings, askPin, toast, layout, screen } = useApp();
  const noFamily = people.length === 0;
  const [wx, setWx] = useState<Weather | null>(null);
  const [pickWx, setPickWx] = useState(false);
  const [pickHols, setPickHols] = useState(false);
  const holidayRegion = useHolidayRegionName();
  useEffect(() => { api.weather().then(setWx).catch(() => setWx(null)); }, [api, settings?.weather_entity]);
  const wxName = !settings ? "…" : !settings.weather_entity ? "Demo forecast"
    : wx?.entity === settings.weather_entity && wx.name ? wx.name : settings.weather_entity;
  async function setWeekStart(v: "monday" | "sunday") {
    const pin = await askPin("Change the first day of the week");
    if (!pin) return;
    try { await api.updateSettings({ week_start: v, pin }); toast("Saved"); }
    catch (e) { toast(e instanceof ApiError ? e.message : "Couldn't save"); }
  }
  async function setTheme(v: Theme) {
    const pin = await askPin("Change the appearance");
    if (!pin) return;
    try { await api.updateSettings({ theme: v, pin }); toast("Saved"); }
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
  /** Shows on this screen only what Home Assistant's moonlight.show_notification and start_timer would. */
  async function testAlert(what: "fullscreen" | "toast" | "timer" | "up") {
    const screens = screen ? [screen.id] : undefined;
    try {
      if (what === "up") {
        await api.createAlert({ kind: "timer", label: "Test count up", description: "From Settings", icon: "☕", since: "now",
          duration: 30, screens, id: "test-up" });
      } else if (what === "timer") {
        await api.createAlert({ kind: "timer", style: "fullscreen", label: "Test timer", description: "From Settings", icon: "⏲️", duration: 15,
          finished_for: 30, screens, id: "test-timer" });
      } else {
        await api.createAlert({ title: "Test notification", message: "Home Assistant can show messages like this one.",
          icon: "🔔", style: what, duration: what === "toast" ? 10 : 0, screens, id: `test-${what}` });
      }
    } catch (e) { toast(e instanceof ApiError ? e.message : "Couldn't show it"); }
  }
  return (
    <div className="settings">
      <div className="toolbar"><div className="toolbar-l"><h1 className="toolbar-title">Settings</h1></div></div>
      <div className="settings-body">
        <CalendarsPanel />
        <FamilyPanel first={noFamily} />
        <section className="panel">
          <h2 className="panel-title">Display</h2>
          <div className="set-row"><span>Appearance</span>
            <Segmented value={settings?.theme ?? "auto"} onChange={setTheme}
              options={[{ value: "auto", label: "Match device" }, { value: "light", label: "Light" }, { value: "dark", label: "Dark" }]} />
          </div>
          <div className="set-row"><span>Week starts on</span>
            <Segmented value={settings?.week_start ?? "monday"} onChange={setWeekStart} options={[{ value: "monday", label: "Monday" }, { value: "sunday", label: "Sunday" }]} />
          </div>
          <div className="set-row"><span>This screen</span><b>{screen ? `${screen.name} · ` : ""}{STYLE_LABEL[layout]}</b></div>
          <div className="set-row"><span>Weather</span>
            <span className="set-pin"><b className="set-wx">{wx && <WeatherIcon condition={wx.current.condition} size={26} />}{wxName}</b>
              <button className="btn ghost small" onClick={() => setPickWx(true)}>Change</button></span>
          </div>
          <div className="set-row"><span>Public holidays</span>
            <span className="set-pin"><b>{holidayRegion || "None"}</b>
              <button className="btn ghost small" onClick={() => setPickHols(true)}>Change</button></span>
          </div>
          {(screen || api.mode === "demo") && (
            <div className="set-row"><span>Test a notification</span>
              <span className="set-tests">
                <button className="btn ghost small" onClick={() => testAlert("fullscreen")}>Full screen</button>
                <button className="btn ghost small" onClick={() => testAlert("toast")}>Toast</button>
                <button className="btn ghost small" onClick={() => testAlert("timer")}>Timer</button>
                <button className="btn ghost small" onClick={() => testAlert("up")}>Count up</button>
              </span>
            </div>
          )}
          <div className="set-row"><span>Parent PIN</span>
            <span className="set-pin"><b>{settings?.pin_set ? "Set" : "Not set"}</b>
              <button className="btn ghost small" onClick={changePin}>{settings?.pin_set ? "Change" : "Set PIN"}</button></span>
          </div>
        </section>
        {pickWx && <WeatherPicker onClose={() => setPickWx(false)} />}
        {pickHols && <HolidayPicker onClose={() => setPickHols(false)} />}
        <RecipesPanel />
        <NurseryPanel />
        <SecurityPanel />
        <EnergyPanel />
        <MusicPanel />
        <SampleDataPanel />
        <ScreensPanel />
        <ScreensaverPanel onScreensaver={onScreensaver} />
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

/** Shown while the demo family seeded on first start is still (partly) here. */
function SampleDataPanel() {
  const { api, askPin, toast } = useApp();
  const [data, reload] = useData((a) => a.sampleData(), ["people", "events", "chores", "lists", "meals", "recipes", "rewards"], []);
  if (!data?.remaining) return null;
  async function remove() {
    const pin = await askPin("Remove the sample family's data");
    if (!pin) return;
    try { const n = await api.removeSampleData(pin); toast(`Removed ${n} sample items`); reload(); }
    catch (e) { toast(e instanceof ApiError ? e.message : "Couldn't remove the sample data"); }
  }
  return (
    <section className="panel">
      <h2 className="panel-title">Sample data</h2>
      <p className="muted connect-note">
        Moonlight started with a pretend family's events, chores, stars, rewards, list items, recipes and meals.
        {" "}{data.remaining} of them are still here. Removing them keeps everything you added yourself.
      </p>
      <div className="set-row"><span>Sample family</span><button className="btn ghost danger small" onClick={remove}>Remove sample data</button></div>
    </section>
  );
}
