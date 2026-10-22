import { CSSProperties, PointerEvent as ReactPointerEvent, useCallback, useEffect, useRef, useState } from "react";
import { ScreenAlert } from "../api/types";
import { useApp } from "../state";
import { IconClose } from "../components/icons";
import { chime, unlockAudio } from "../recipes/timers";
import { fmtClock } from "../recipes/recipeText";
import { fmtTime } from "../dates";

/** A chime is only played for something that just happened, not for one that was already up when the screen loaded. */
const FRESH_MS = 30_000;

/** Time left on a timer: 4:05, 1:02:03, or for a countdown to a day "3 days 4 hr". */
export function fmtLeft(ms: number): string {
  const s = Math.max(0, Math.ceil(ms / 1000));
  if (s < 86_400) return fmtClock(s);
  const d = Math.floor(s / 86_400), h = Math.floor((s % 86_400) / 3600);
  return `${d} ${d === 1 ? "day" : "days"}${h ? ` ${h} hr` : ""}`;
}

/** Time gone on a timer counting up, the same way: 0:00 at the start, then 4:05. */
export function fmtSince(ms: number): string {
  return fmtLeft(Math.floor(Math.max(0, ms) / 1000) * 1000);
}

/** "10:41am" for an epoch time, on this screen's clock. */
function clockAt(ms: number): string {
  const d = new Date(ms);
  return fmtTime(`0000-00-00T${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`);
}

/** A countdown that got to zero (one counting up never does). */
const isDone = (a: ScreenAlert, t: number) => a.kind === "timer" && a.ends_at != null && t >= a.ends_at;
/** How far along the bar or ring is, 0 to 1: a countdown towards zero; counting up, towards when it goes (if set). */
function progress(a: ScreenAlert, t: number): number {
  const end = a.count_up ? a.expires_at : a.ends_at;
  if (end == null) return 0;
  return Math.min(1, Math.max(0, (t - a.started_at!) / Math.max(1, end - a.started_at!)));
}

/** Notifications and timers from Home Assistant (see API.md "Notifications and timers"): full screen ones cover
 * everything, the screensaver too (until `shrink_at`, if set); toasts and small timers stack in the top corner. A tap
 * on × or a swipe right dismisses a corner one on every screen; a swipe up (or Make small, on a timer) puts a full
 * screen one in the corner on this screen only. */
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
  const nextEnd = Math.min(...live.flatMap((a) => [a.expires_at ?? Infinity, a.shrink_at && a.shrink_at > t ? a.shrink_at : Infinity]));
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
      const at = a.kind === "timer" && !a.count_up ? a.ends_at! : a.created_at;
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

  const full = live.filter((a) => a.style === "fullscreen" && !small.has(a.id + a.created_at) && !(a.shrink_at && t >= a.shrink_at));
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
      {top && <FullView key={top.id + top.created_at} a={top} t={t} more={full.length - 1} onShrink={shrink} onDismiss={dismiss} />}
    </>
  );
}

/** Dragging one way (right, or up) moves the element with the finger; let go far enough along and `onSwipe` runs,
 * otherwise it springs back. A drag the other way, or mostly across, is left alone (taps still work). */
function useSwipe(dir: "right" | "up", onSwipe: (() => void) | null) {
  const start = useRef<{ x: number; y: number; id: number; moving: boolean } | null>(null);
  const [off, setOff] = useState(0);
  const offRef = useRef(0);
  const move = (v: number) => { offRef.current = v; setOff(v); };
  const end = (el: HTMLElement, ok: boolean) => {
    const s = start.current;
    start.current = null;
    if (!s?.moving) return;
    const size = dir === "right" ? el.offsetWidth : el.offsetHeight;
    if (ok && onSwipe && offRef.current > Math.min(140, size * 0.3)) {
      move(size * 1.2);
      setTimeout(onSwipe, 160);
    } else move(0);
  };
  const handlers = onSwipe ? {
    onPointerDown: (e: ReactPointerEvent<HTMLElement>) => { start.current = { x: e.clientX, y: e.clientY, id: e.pointerId, moving: false }; },
    onPointerMove: (e: ReactPointerEvent<HTMLElement>) => {
      const s = start.current;
      if (!s || e.pointerId !== s.id) return;
      const along = dir === "right" ? e.clientX - s.x : s.y - e.clientY;
      const across = Math.abs(dir === "right" ? e.clientY - s.y : e.clientX - s.x);
      if (!s.moving) {
        if (across > 12 && across > Math.abs(along)) { start.current = null; return; }
        if (along < 12) return;
        s.moving = true;
        e.currentTarget.setPointerCapture(e.pointerId);
      }
      move(Math.max(0, along));
    },
    onPointerUp: (e: ReactPointerEvent<HTMLElement>) => end(e.currentTarget, true),
    onPointerCancel: (e: ReactPointerEvent<HTMLElement>) => end(e.currentTarget, false),
  } : {};
  const dragging = start.current?.moving ?? false;
  const style: CSSProperties | undefined = off || dragging ? {
    transform: dir === "right" ? `translateX(${off}px)` : `translateY(${-off}px)`,
    opacity: dir === "right" ? Math.max(0.2, 1 - off / 500) : undefined, // a full screen one slides up whole
    transition: dragging ? "none" : "transform 0.16s ease-out, opacity 0.16s ease-out",
  } : undefined;
  return { handlers, style };
}

function FullView({ a, t, more, onShrink, onDismiss }: {
  a: ScreenAlert; t: number; more: number; onShrink: (a: ScreenAlert) => void; onDismiss: (a: ScreenAlert) => void;
}) {
  const swipe = useSwipe("up", () => onShrink(a));
  return (
    <div className={"ha-full" + (isDone(a, t) ? " done" : "")} role="alertdialog" aria-live="assertive" {...swipe.handlers} style={swipe.style}>
      {a.kind === "timer" ? <FullTimer a={a} t={t} /> : <FullNote a={a} />}
      <div className="ha-full-actions">
        {a.kind === "timer" && <button className="btn ghost big" onClick={() => onShrink(a)}>Make small</button>}
        {a.dismissible && <button className="btn big" onClick={() => onDismiss(a)}>{a.kind === "timer" && !a.count_up && !isDone(a, t) ? "Cancel timer" : "Dismiss"}</button>}
      </div>
      {more > 0 && <div className="ha-full-more">{more} more</div>}
      <div className="ha-full-hint" aria-hidden>Swipe up to make small</div>
    </div>
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
  const done = isDone(a, t);
  // Counting up with no end: the ring stays full.
  const along = a.count_up && a.expires_at == null ? 1 : progress(a, t);
  const R = 46, C = 2 * Math.PI * R;
  return (
    <div className="ha-full-body">
      <div className="ha-ring">
        <svg viewBox="0 0 100 100" aria-hidden>
          <circle cx="50" cy="50" r={R} className="ha-ring-track" />
          <circle cx="50" cy="50" r={R} className="ha-ring-fill" strokeDasharray={C}
            strokeDashoffset={done ? 0 : a.count_up ? C * (1 - along) : C * along} />
        </svg>
        <div className="ha-ring-text">
          {a.icon && <span className="ha-ring-icon">{a.icon}</span>}
          <b>{done ? "Time's up" : a.count_up ? fmtSince(t - a.started_at!) : fmtLeft(a.ends_at! - t)}</b>
          {a.count_up && <span className="ha-ring-since">since {clockAt(a.started_at!)}</span>}
        </div>
      </div>
      <h1>{a.label}</h1>
      {a.description && <p>{a.description}</p>}
    </div>
  );
}

function NoteCard({ a, onDismiss }: { a: ScreenAlert; onDismiss: (a: ScreenAlert) => void }) {
  const swipe = useSwipe("right", a.dismissible ? () => onDismiss(a) : null);
  return (
    <div className="ha-toast" {...swipe.handlers} style={swipe.style}>
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
  const done = isDone(a, t);
  const detail = a.description || (a.count_up ? `since ${clockAt(a.started_at!)}` : "");
  const swipe = useSwipe("right", a.dismissible ? () => onDismiss(a) : null);
  return (
    <div className={"ktimer ha-timer" + (done ? " ringing" : "") + (a.count_up ? " up" : "")} {...swipe.handlers}
      style={{ ["--done" as string]: `${progress(a, t) * 100}%`, ...swipe.style }}>
      {a.icon && <span className="ha-toast-icon">{a.icon}</span>}
      <div className="kt-main">
        <b>{done ? "Time's up" : a.count_up ? fmtSince(t - a.started_at!) : fmtLeft(a.ends_at! - t)}</b>
        <span>{a.label}{detail ? ` · ${detail}` : ""}</span>
      </div>
      {a.dismissible && <button className="kt-btn" onClick={() => onDismiss(a)} aria-label={done || a.count_up ? "Dismiss" : "Cancel timer"}><IconClose size={18} /></button>}
    </div>
  );
}
