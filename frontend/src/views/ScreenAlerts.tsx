import { useCallback, useEffect, useRef, useState } from "react";
import { ScreenAlert } from "../api/types";
import { useApp } from "../state";
import { IconClose } from "../components/icons";
import { chime, unlockAudio } from "../recipes/timers";
import { fmtClock } from "../recipes/recipeText";

/** A chime is only played for something that just happened, not for one that was already up when the screen loaded. */
const FRESH_MS = 30_000;

/** Time left on a timer: 4:05, 1:02:03, or for a countdown to a day "3 days 4 hr". */
export function fmtLeft(ms: number): string {
  const s = Math.max(0, Math.ceil(ms / 1000));
  if (s < 86_400) return fmtClock(s);
  const d = Math.floor(s / 86_400), h = Math.floor((s % 86_400) / 3600);
  return `${d} ${d === 1 ? "day" : "days"}${h ? ` ${h} hr` : ""}`;
}

/** Notifications and timers from Home Assistant (see API.md "Notifications and timers"): full screen ones cover
 * everything, the screensaver too; toasts and small timers stack in the top corner. A tap on × dismisses one on
 * every screen; a full screen timer can also be made small on this screen only. */
export function ScreenAlerts() {
  const { api, toast } = useApp();
  const [alerts, setAlerts] = useState<ScreenAlert[]>([]);
  const [skew, setSkew] = useState(0); // server clock minus this one
  const [now, setNow] = useState(() => Date.now());
  const [small, setSmall] = useState<Set<string>>(() => new Set());
  const chimed = useRef(new Set<string>());

  const load = useCallback(() => {
    api.alerts().then((r) => { setSkew(r.server_time - Date.now()); setAlerts(r.alerts); setNow(Date.now()); })
      .catch(() => { /* offline: keep what's showing */ });
  }, [api]);
  useEffect(() => { load(); return api.subscribe((t) => { if (t === "alerts") load(); }); }, [api, load]);
  // A tap anywhere lets the screen play sound from then on (most kiosk browsers allow it without).
  useEffect(() => {
    const unlock = () => unlockAudio();
    window.addEventListener("pointerdown", unlock, { once: true });
    return () => window.removeEventListener("pointerdown", unlock);
  }, []);

  const t = now + skew;
  const live = alerts.filter((a) => a.expires_at === null || a.expires_at > t);
  const timing = live.some((a) => a.kind === "timer");
  const nextEnd = Math.min(...live.map((a) => a.expires_at ?? Infinity));
  useEffect(() => {
    // Tick every second while a timer shows; otherwise only when the next one is due to go.
    const wait = timing ? 1000 - (Date.now() % 1000) + 5 : nextEnd === Infinity ? 0 : Math.max(50, nextEnd - t + 50);
    if (!wait) return;
    const h = setTimeout(() => setNow(Date.now()), Math.min(wait, 2 ** 31 - 1));
    return () => clearTimeout(h);
  }, [timing, nextEnd, t]);

  // Chime for a new notification that asks for one, and for a timer getting to zero.
  useEffect(() => {
    for (const a of live) {
      if (!a.chime || chimed.current.has(a.id + a.created_at)) continue;
      const at = a.kind === "timer" ? a.ends_at! : a.created_at;
      if (at > t) continue;
      chimed.current.add(a.id + a.created_at);
      if (t - at < FRESH_MS) chime(true);
    }
  });

  const dismiss = (a: ScreenAlert) => {
    setAlerts((cur) => cur.filter((x) => x.id !== a.id));
    api.dismissAlert(a.id).catch((e) => { if (e?.status !== 404) { toast(e.message); load(); } });
  };
  const shrink = (a: ScreenAlert) => setSmall((s) => new Set(s).add(a.id + a.created_at));

  const full = live.filter((a) => a.style === "fullscreen" && !small.has(a.id + a.created_at));
  const corner = live.filter((a) => !full.includes(a)).reverse();
  const top = full[full.length - 1];
  return (
    <>
      {corner.length > 0 && (
        <div className="ha-toasts" aria-live="polite">
          {corner.slice(0, 4).map((a) => (a.kind === "timer"
            ? <TimerCard key={a.id} a={a} t={t} onDismiss={dismiss} />
            : <NoteCard key={a.id} a={a} onDismiss={dismiss} />))}
        </div>
      )}
      {top && (
        <div className={"ha-full" + (top.kind === "timer" && t >= top.ends_at! ? " done" : "")} role="alertdialog" aria-live="assertive">
          {top.kind === "timer" ? <FullTimer a={top} t={t} /> : <FullNote a={top} />}
          <div className="ha-full-actions">
            {top.kind === "timer" && <button className="btn ghost big" onClick={() => shrink(top)}>Make small</button>}
            {top.dismissible && <button className="btn big" onClick={() => dismiss(top)}>{top.kind === "timer" && t < top.ends_at! ? "Cancel timer" : "Dismiss"}</button>}
          </div>
          {full.length > 1 && <div className="ha-full-more">{full.length - 1} more</div>}
        </div>
      )}
    </>
  );
}

function FullNote({ a }: { a: ScreenAlert }) {
  return (
    <div className="ha-full-body">
      {a.icon && <div className="ha-full-icon">{a.icon}</div>}
      {a.title && <h1>{a.title}</h1>}
      {a.message && <p>{a.message}</p>}
      {a.image && <img className="ha-full-img" src={a.image} alt="" />}
    </div>
  );
}

function FullTimer({ a, t }: { a: ScreenAlert; t: number }) {
  const left = a.ends_at! - t;
  const total = Math.max(1, a.ends_at! - a.started_at!);
  const done = left <= 0;
  const R = 46, C = 2 * Math.PI * R;
  return (
    <div className="ha-full-body">
      <div className="ha-ring">
        <svg viewBox="0 0 100 100" aria-hidden>
          <circle cx="50" cy="50" r={R} className="ha-ring-track" />
          <circle cx="50" cy="50" r={R} className="ha-ring-fill" strokeDasharray={C}
            strokeDashoffset={done ? 0 : C * (1 - Math.min(1, Math.max(0, left / total)))} />
        </svg>
        <div className="ha-ring-text">
          {a.icon && <span className="ha-ring-icon">{a.icon}</span>}
          <b>{done ? "Time's up" : fmtLeft(left)}</b>
        </div>
      </div>
      <h1>{a.label}</h1>
      {a.description && <p>{a.description}</p>}
    </div>
  );
}

function NoteCard({ a, onDismiss }: { a: ScreenAlert; onDismiss: (a: ScreenAlert) => void }) {
  return (
    <div className="ha-toast">
      {a.icon && <span className="ha-toast-icon">{a.icon}</span>}
      <div className="ha-toast-text">
        {a.title && <b>{a.title}</b>}
        {a.message && <span>{a.message}</span>}
      </div>
      {a.image && <img src={a.image} alt="" />}
      {a.dismissible && <button className="kt-btn" onClick={() => onDismiss(a)} aria-label="Dismiss"><IconClose size={18} /></button>}
    </div>
  );
}

function TimerCard({ a, t, onDismiss }: { a: ScreenAlert; t: number; onDismiss: (a: ScreenAlert) => void }) {
  const left = a.ends_at! - t;
  const done = left <= 0;
  const total = Math.max(1, a.ends_at! - a.started_at!);
  return (
    <div className={"ktimer ha-timer" + (done ? " ringing" : "")}
      style={{ ["--done" as string]: `${Math.min(100, Math.max(0, 100 - (left / total) * 100))}%` }}>
      {a.icon && <span className="ha-toast-icon">{a.icon}</span>}
      <div className="kt-main">
        <b>{done ? "Time's up" : fmtLeft(left)}</b>
        <span>{a.label}{a.description ? ` · ${a.description}` : ""}</span>
      </div>
      {a.dismissible && <button className="kt-btn" onClick={() => onDismiss(a)} aria-label={done ? "Dismiss" : "Cancel timer"}><IconClose size={18} /></button>}
    </div>
  );
}
