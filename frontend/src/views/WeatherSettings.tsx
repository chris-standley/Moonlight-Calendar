import { useEffect, useState } from "react";
import { ApiError, WeatherEntity } from "../api/types";
import { useApp } from "../state";
import { Sheet } from "../components/ui";
import { WeatherIcon } from "../components/icons";

const CONDITION: Record<string, string> = {
  "clear-night": "Clear", cloudy: "Cloudy", exceptional: "Exceptional", fog: "Fog", hail: "Hail",
  lightning: "Lightning", "lightning-rainy": "Thunderstorms", partlycloudy: "Partly cloudy", pouring: "Pouring",
  rainy: "Rain", snowy: "Snow", "snowy-rainy": "Sleet", sunny: "Sunny", windy: "Windy", "windy-variant": "Windy",
};
export const conditionLabel = (c: string | null) => (c ? CONDITION[c] ?? c : "Unavailable");

/** Settings > Display > Weather: pick which Home Assistant weather entity the screens show. */
export function WeatherPicker({ onClose }: { onClose: () => void }) {
  const { api, settings, askPin, toast } = useApp();
  const current = settings?.weather_entity ?? "";
  const [entities, setEntities] = useState<WeatherEntity[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api.weatherEntities().then((e) => { setEntities(e); setError(null); })
      .catch((e) => setError(e instanceof ApiError ? e.message : "Couldn't reach Home Assistant"));
  }, [api]);
  async function choose(entity: string) {
    if (entity === current) { onClose(); return; }
    const pin = await askPin("Change the weather");
    if (!pin) return;
    try { await api.updateSettings({ weather_entity: entity, pin }); toast("Saved"); onClose(); }
    catch (e) { toast(e instanceof ApiError ? e.message : "Couldn't save"); }
  }
  const unit = settings?.temp_unit ?? "C";
  const temp = (w: WeatherEntity) => {
    if (w.temperature == null) return "";
    const t = w.unit === unit ? w.temperature : unit === "F" ? w.temperature * 9 / 5 + 32 : (w.temperature - 32) * 5 / 9;
    return `${Math.round(t)}°`;
  };
  return (
    <Sheet title="Weather" onClose={onClose}>
      <p className="muted connect-note">Shown in the top bar, on Today, in the calendar and on the screensaver.</p>
      {error && <div className="form-error">{error}</div>}
      {!entities && !error && <div className="screens-empty">Asking Home Assistant…</div>}
      <div className="player-list">
        {(entities ?? []).map((w) => (
          <button key={w.entity_id} className={"player-row wx-row" + (current === w.entity_id ? " on" : "")}
            onClick={() => choose(w.entity_id)} disabled={!w.available && current !== w.entity_id}>
            <span className="wx-icon">{w.condition ? <WeatherIcon condition={w.condition} size={34} /> : null}</span>
            <span className="player-main"><b>{w.name}</b>
              <span>{conditionLabel(w.condition)}{w.attribution ? ` · ${w.attribution}` : ` · ${w.entity_id}`}</span></span>
            <span className="wx-temp">{temp(w)}</span>
          </button>
        ))}
        {entities && entities.length === 0 && <div className="screens-empty">Home Assistant has no weather entities yet. Add a weather integration such as Met.no.</div>}
        <button className={"player-row" + (current === "" ? " on" : "")} onClick={() => choose("")}>
          <span className="player-main"><b>Demo forecast</b><span>Made-up weather, for trying Moonlight out</span></span>
        </button>
      </div>
    </Sheet>
  );
}
