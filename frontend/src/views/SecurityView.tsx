import { useEffect, useState } from "react";
import { AlarmState, SecurityCamera, SecuritySensor, SensorGroup } from "../api/types";
import { useApp, useData, useNow } from "../state";
import { Empty } from "../components/ui";
import { IconCctv, IconClose, IconLock, IconShield } from "../components/icons";

const GROUP_LABEL: Record<SensorGroup, string> = {
  doors: "Doors", windows: "Windows", motion: "Motion", environment: "Smoke and leaks", other: "Other",
};
const GROUPS: SensorGroup[] = ["doors", "windows", "motion", "environment", "other"];

/** A Moonlight camera picture URL at a given width (demo pictures are data: URLs and stay as they are). */
export function sized(url: string, width: number, extra = ""): string {
  if (url.startsWith("data:")) return url;
  return `${url}${url.includes("?") ? "&" : "?"}width=${width}${extra}`;
}

export function ago(iso: string | null, now: Date): string {
  if (!iso) return "";
  const s = Math.max(0, (now.getTime() - new Date(iso).getTime()) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  const d = Math.floor(s / 86400);
  return d === 1 ? "yesterday" : `${d} days ago`;
}

/** Tone of the alarm card: calm when disarmed, accent when armed, amber while arming or in the entry delay. */
function tone(a: AlarmState): string {
  if (!a.available) return "off";
  if (a.state === "triggered") return "alarm";
  if (a.state === "arming" || a.state === "pending" || a.state === "disarming") return "busy";
  return a.armed ? "armed" : "calm";
}

export function SecurityView() {
  const { layout, go } = useApp();
  const [data] = useData((a) => a.security(), ["security", "security_alert", "settings"], []);
  const [live, setLive] = useState<SecurityCamera | null>(null);
  const now = useNow(30_000);
  if (!data) return <div className="security" />;
  if (!data.configured) {
    return (
      <div className="security">
        <div className="toolbar"><div className="toolbar-l"><h1 className="toolbar-title">Security</h1></div></div>
        <Empty>Security shows your alarm and cameras from Home Assistant. Run Moonlight as the Home Assistant add-on to use it.</Empty>
      </div>
    );
  }
  const people = new Set(data.alerts.map((a) => a.camera));
  const open = data.sensors.filter((s) => s.active && s.group !== "motion").length;
  const motion = data.sensors.filter((s) => s.active && s.group === "motion").length;
  return (
    <div className="security">
      <div className="toolbar">
        <div className="toolbar-l"><h1 className="toolbar-title">Security</h1></div>
        <div className="toolbar-r">
          {!data.reachable && <span className="sec-offline">Can't reach Home Assistant</span>}
          <button className="btn ghost small" onClick={() => go("settings")}>Settings</button>
        </div>
      </div>
      <div className={"sec-body" + (layout === "phone" ? " stack" : "")}>
        <div className="sec-side">
          {data.alarm ? <AlarmCard alarm={data.alarm} now={now} open={open} motion={motion} /> : (
            <section className="panel sec-alarm off"><div className="sec-alarm-main"><IconShield size={40} /><div><b>No alarm chosen</b>
              <span>Pick one in Settings › Security</span></div></div></section>
          )}
          <section className="panel sec-sensors">
            {data.sensors.length === 0 && (
              <p className="muted">{data.sensors_source === "alarmo" ? "Alarmo has no sensors set up." : "Sensors appear here once they're set up in Alarmo in Home Assistant."}</p>
            )}
            {GROUPS.map((g) => {
              const rows = data.sensors.filter((s) => s.group === g);
              if (!rows.length) return null;
              return (
                <div key={g} className="sec-group">
                  <h2 className="sec-group-title">{GROUP_LABEL[g]}</h2>
                  {rows.map((s) => <SensorRow key={s.entity_id} s={s} now={now} />)}
                </div>
              );
            })}
          </section>
        </div>
        <div className="sec-cams">
          {data.cameras.length === 0 && <Empty>No cameras to show. Choose them in Settings › Security.</Empty>}
          {data.cameras.map((c) => <CameraTile key={c.entity_id} cam={c} person={people.has(c.entity_id)} onOpen={() => setLive(c)} />)}
        </div>
      </div>
      {live && <LiveCamera name={live.name} url={live.live_url} onClose={() => setLive(null)} />}
    </div>
  );
}

function AlarmCard({ alarm, now, open, motion }: { alarm: AlarmState; now: Date; open: number; motion: number }) {
  const who = alarm.changed_by ? ` by ${alarm.changed_by}` : "";
  return (
    <section className={`panel sec-alarm ${tone(alarm)}`}>
      <div className="sec-alarm-main">
        <IconShield size={44} />
        <div>
          <b>{alarm.label}</b>
          <span>{alarm.last_changed ? `${ago(alarm.last_changed, now)}${who}` : alarm.name}</span>
        </div>
      </div>
      {alarm.open_sensors.length > 0 && <div className="sec-blocking">Can't arm: {alarm.open_sensors.join(", ")}</div>}
      <div className="sec-summary">
        <span className={open ? "warn" : ""}>{open ? `${open} open` : "All closed"}</span>
        {motion > 0 && <span className="motion">Motion in {motion} {motion === 1 ? "place" : "places"}</span>}
      </div>
    </section>
  );
}

function SensorRow({ s, now }: { s: SecuritySensor; now: Date }) {
  const state = !s.available ? "na" : s.active ? (s.group === "motion" ? "motion" : "open") : "ok";
  return (
    <div className={`sec-sensor ${state}`}>
      <i className="sec-dot" />
      <span className="sec-name">{s.name}</span>
      {s.armed && <span className="sec-armed" title="Guarded now"><IconLock size={16} /></span>}
      <span className="sec-state">{s.label}</span>
      <span className="sec-when">{ago(s.last_changed, now)}</span>
    </div>
  );
}

function CameraTile({ cam, person, onOpen }: { cam: SecurityCamera; person: boolean; onOpen: () => void }) {
  // A fresh picture every 10 seconds; the full live view is a tap away.
  const tick = Math.floor(useNow(10_000).getTime() / 10_000);
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [tick]);
  return (
    <button className={"sec-cam" + (person ? " person" : "")} onClick={onOpen}>
      {!failed && cam.available
        ? <img src={sized(cam.snapshot_url, 640, `&t=${tick}`)} alt="" onError={() => setFailed(true)} />
        : <span className="sec-cam-off"><IconCctv size={40} />{cam.available ? "No picture" : "Offline"}</span>}
      <span className="sec-cam-name">{cam.name}</span>
      {person && <span className="sec-cam-badge">Person</span>}
    </button>
  );
}

/** The camera full size, live. */
export function LiveCamera({ name, url, onClose }: { name: string; url: string; onClose: () => void }) {
  // The live feed ends after a quarter of an hour; open a new one before that if it's still showing.
  const [round, setRound] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setRound((r) => r + 1), 10 * 60_000);
    const k = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", k);
    return () => { clearInterval(t); window.removeEventListener("keydown", k); };
  }, [onClose]);
  return (
    <div className="sec-live" onClick={onClose}>
      <div className="sec-live-frame" onClick={(e) => e.stopPropagation()}>
        <img key={round} src={sized(url, 1280)} alt={name} />
        <div className="sec-live-bar"><span className="sec-live-dot" />{name}
          <button className="icon-btn" onClick={onClose} aria-label="Close"><IconClose /></button></div>
      </div>
    </div>
  );
}
