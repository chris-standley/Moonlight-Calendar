// Kitchen timers started from a recipe's steps. They live outside any one view, so they keep counting when the cook
// leaves cook mode, and a pill on every screen shows them (see TimerTray).
import { useEffect, useState } from "react";

export interface KitchenTimer {
  id: string;
  label: string;
  /** Recipe it came from, shown under the label. */
  recipe: string;
  endsAt: number;
  total: number;
  /** Set once it has gone off; cleared when dismissed. */
  ringing: boolean;
  pausedLeft: number | null;
}

let timers: KitchenTimer[] = [];
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((l) => l());
let tick: ReturnType<typeof setInterval> | null = null;

function loop() {
  if (tick) return;
  tick = setInterval(() => {
    const now = Date.now();
    let changed = false;
    for (const t of timers) {
      if (!t.ringing && t.pausedLeft == null && t.endsAt <= now) { t.ringing = true; changed = true; chime(); }
    }
    if (timers.some((t) => t.ringing) && now % 3000 < 1000) chime();
    if (changed) timers = [...timers];
    emit();
    if (!timers.length && tick) { clearInterval(tick); tick = null; }
  }, 1000);
}

export function startTimer(label: string, seconds: number, recipe: string): void {
  timers = [...timers, { id: `${Date.now()}${Math.random()}`, label, recipe, endsAt: Date.now() + seconds * 1000, total: seconds, ringing: false, pausedLeft: null }];
  unlockAudio();
  loop();
  emit();
}
export function stopTimer(id: string): void { timers = timers.filter((t) => t.id !== id); emit(); }
export function addTime(id: string, seconds: number): void {
  timers = timers.map((t) => t.id !== id ? t : t.pausedLeft != null ? { ...t, pausedLeft: t.pausedLeft + seconds }
    : { ...t, ringing: false, endsAt: Math.max(t.endsAt, Date.now()) + seconds * 1000 });
  emit();
}
export function togglePause(id: string): void {
  timers = timers.map((t) => t.id !== id || t.ringing ? t : t.pausedLeft != null
    ? { ...t, endsAt: Date.now() + t.pausedLeft, pausedLeft: null } : { ...t, pausedLeft: t.endsAt - Date.now() });
  emit();
}
export function secondsLeft(t: KitchenTimer): number {
  return (t.pausedLeft ?? t.endsAt - Date.now()) / 1000;
}

export function useTimers(): KitchenTimer[] {
  const [, setN] = useState(0);
  useEffect(() => { const l = () => setN((n) => n + 1); listeners.add(l); return () => { listeners.delete(l); }; }, []);
  return timers;
}

// ---------------------------------------------------------------- sound

let ctx: AudioContext | null = null;
/** Browsers only allow sound after a tap: starting a timer is that tap (kiosk browsers usually allow it anyway). */
export function unlockAudio() {
  try { ctx ??= new AudioContext(); if (ctx.state === "suspended") void ctx.resume(); } catch { /* no audio */ }
}
/** Three rising beeps. `start`: make the audio first (a kiosk lets a page play sound without a tap). */
export function chime(start = false) {
  if (!ctx && start) unlockAudio();
  if (!ctx) return;
  const t0 = ctx.currentTime;
  [0, 0.25, 0.5].forEach((d, i) => {
    const o = ctx!.createOscillator(), g = ctx!.createGain();
    o.type = "sine"; o.frequency.value = i === 2 ? 1175 : 880;
    g.gain.setValueAtTime(0.0001, t0 + d);
    g.gain.exponentialRampToValueAtTime(0.4, t0 + d + 0.02);
    g.gain.exponentialRampToValueAtTime(0.0001, t0 + d + 0.22);
    o.connect(g).connect(ctx!.destination);
    o.start(t0 + d); o.stop(t0 + d + 0.25);
  });
}
