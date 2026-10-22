import { useEffect, useRef, useState } from "react";
import { getToken } from "../api/pairing";
import { AlarmMode, AlarmState, ApiError, SecurityCamera, SecuritySensor, SensorGroup } from "../api/types";
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
  const { layout } = useApp();
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
                  <div className="sec-rows">{rows.map((s) => <SensorRow key={s.entity_id} s={s} now={now} />)}</div>
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
      {live && <LiveCamera name={live.name} cam={live} onClose={() => setLive(null)} />}
    </div>
  );
}

const MODE_LABEL: Record<AlarmMode, string> = { away: "Arm away", home: "Arm home", night: "Arm night", vacation: "Arm vacation" };

function AlarmCard({ alarm, now, open, motion }: { alarm: AlarmState; now: Date; open: number; motion: number }) {
  const { api, toast } = useApp();
  const [pad, setPad] = useState<AlarmMode | "disarm" | null>(null);
  const [busy, setBusy] = useState(false);
  const who = alarm.changed_by ? ` by ${alarm.changed_by}` : "";
  const disarmed = alarm.state === "disarmed";

  /** Arm or disarm; the code (if any) goes straight to Home Assistant. Returns an error to show on the pad. */
  async function send(action: AlarmMode | "disarm", code?: string): Promise<string | null> {
    setBusy(true);
    try {
      await api.setAlarm(action, code);
      setPad(null);
      toast(action === "disarm" ? "Disarmed" : "Arming");
      return null;
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : "Couldn't reach the alarm";
      if (!(e instanceof ApiError) || e.status !== 403) { setPad(null); toast(msg); }
      return msg;
    } finally {
      setBusy(false);
    }
  }
  const arm = (m: AlarmMode) => (alarm.code_arm_required ? setPad(m) : void send(m));

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
      {alarm.available && (
        <div className="sec-arm">
          {disarmed
            ? alarm.modes.map((m) => <button key={m} className="btn small" disabled={busy} onClick={() => arm(m)}>{MODE_LABEL[m]}</button>)
            : <button className="btn small danger-fill" disabled={busy} onClick={() => setPad("disarm")}>Disarm</button>}
        </div>
      )}
      {pad && <AlarmPad why={pad === "disarm" ? `Disarm ${alarm.name}` : `${MODE_LABEL[pad]}`} onCancel={() => setPad(null)}
        onCode={(code) => send(pad, code)} />}
    </section>
  );
}

/** A number pad for the alarm's own code (any length), sent to Home Assistant with ✓. */
function AlarmPad({ why, onCode, onCancel }: { why: string; onCode: (code: string) => Promise<string | null>; onCancel: () => void }) {
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  async function submit() {
    if (!code || sending) return;
    setSending(true);
    const err = await onCode(code);
    setSending(false);
    if (err) { setError(err); setCode(""); }
  }
  const keys = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "⌫", "0", "✓"];
  return (
    <div className="scrim" onClick={onCancel}>
      <div className="pinpad" onClick={(e) => e.stopPropagation()}>
        <div className="pin-why">{why}</div>
        <div className="pin-dots alarm-dots">{code.length ? [...code].map((_, i) => <span key={i} className="on" />) : <em>Enter the alarm code</em>}</div>
        <div className="pin-err">{error ?? " "}</div>
        <div className="pin-keys">
          {keys.map((k) => (
            <button key={k} className={k === "✓" ? "go" : undefined} disabled={sending || (k === "✓" && !code)} aria-label={k === "✓" ? "Send" : k === "⌫" ? "Delete" : k}
              onClick={() => (k === "✓" ? void submit() : setCode((c) => (k === "⌫" ? c.slice(0, -1) : (c + k).slice(0, 12))))}>{k}</button>
          ))}
        </div>
        <button className="btn ghost" onClick={onCancel}>Cancel</button>
      </div>
    </div>
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
  // Live, from the camera's lighter stream (several play at once); tap for it full size.
  return (
    <button className={"sec-cam" + (person ? " person" : "")} onClick={onOpen}>
      {cam.available
        ? <CameraVideo cam={cam} width={960} light />
        : <span className="sec-cam-off"><IconCctv size={40} />Offline</span>}
      <span className="sec-cam-name">{cam.name}</span>
      {person && <span className="sec-cam-badge">Person</span>}
    </button>
  );
}

type CamUrls = { live_url: string; snapshot_url: string; video_url: string | null; video_hd_url: string | null };

/** A camera, live: Home Assistant's HLS video when the camera has it (hls.js, or the browser itself on Apple
 * devices), else, or if the video fails, the snapshot MJPEG feed. The MJPEG feed also shows on top until the video
 * has its first picture, since a stream Home Assistant hasn't got running yet can take 10 seconds or more to start.
 * Large screens play the camera's full resolution; the others, and `light` ones (tiles), its lighter medium channel
 * when there is one. */
export function CameraVideo({ cam, width, fit = "cover", light = false }: { cam: CamUrls; width: number; fit?: "cover" | "contain"; light?: boolean }) {
  const { layout } = useApp();
  const ref = useRef<HTMLVideoElement>(null);
  const [failed, setFailed] = useState(false);
  const [playing, setPlaying] = useState(false);
  // The MJPEG feed ends after a quarter of an hour; open a new one before that if it's still showing.
  const [round, setRound] = useState(0);
  useEffect(() => { const t = setInterval(() => setRound((r) => r + 1), 10 * 60_000); return () => clearInterval(t); }, []);
  const video = failed ? null : (layout === "large" && !light ? cam.video_hd_url : null) ?? cam.video_url;
  useEffect(() => {
    const el = ref.current;
    setPlaying(false);
    if (!video || !el) return;
    let gone = false;
    let hls: { destroy(): void } | null = null;
    const fail = () => { if (!gone) setFailed(true); };
    const play = () => { el.play().catch(() => { /* autoplay of a muted video is allowed; ignore a race */ }); };
    // hls.js wherever the browser has Media Source; the browser's own HLS only where it hasn't (iPhones). Android's
    // own HLS player says it can play these streams but on older tablets never does.
    const native = () => {
      if (!el.canPlayType("application/vnd.apple.mpegurl")) { fail(); return; }
      el.src = video;
      el.addEventListener("error", fail);
      play();
    };
    import("hls.js").then(({ default: Hls }) => {
      if (gone) return;
      if (!Hls.isSupported()) { native(); return; }
      const h = new Hls({
        lowLatencyMode: true, backBufferLength: 10, manifestLoadingTimeOut: 25_000, manifestLoadingMaxRetry: 2,
        xhrSetup: (xhr) => { const t = getToken(); if (t) xhr.setRequestHeader("Authorization", `Bearer ${t}`); },
      });
      let recovered = false;
      h.on(Hls.Events.ERROR, (_e, d) => {
        if (!d.fatal) return;
        if (d.type === Hls.ErrorTypes.MEDIA_ERROR && !recovered) { recovered = true; h.recoverMediaError(); } else fail();
      });
      h.on(Hls.Events.MANIFEST_PARSED, play);
      h.loadSource(video);
      h.attachMedia(el);
      hls = h;
    }).catch(native);
    return () => {
      gone = true;
      hls?.destroy();
      el.removeEventListener("error", fail);
      el.removeAttribute("src");
      el.load();
    };
  }, [video]);
  const live = <img className={"cam-media " + fit} key={round} src={sized(cam.live_url, width)} alt="" />;
  if (!video) return live;
  return (
    <div className={"cam-media cam-stack " + fit}>
      <video ref={ref} className={"cam-media " + fit} muted autoPlay playsInline onPlaying={() => setPlaying(true)} />
      {!playing && live}
    </div>
  );
}

/** The camera full size, live. */
export function LiveCamera({ name, cam, onClose }: { name: string; cam: CamUrls; onClose: () => void }) {
  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);
  return (
    <div className="sec-live" onClick={onClose}>
      <div className="sec-live-frame" onClick={(e) => e.stopPropagation()}>
        <CameraVideo cam={cam} width={1280} fit="contain" />
        <div className="sec-live-bar"><span className="sec-live-dot" />{name}
          <button className="icon-btn" onClick={onClose} aria-label="Close"><IconClose /></button></div>
      </div>
    </div>
  );
}
