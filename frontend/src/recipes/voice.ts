import { useEffect, useRef, useState } from "react";

// Hands-free cook mode: listens for a few short commands with the browser's speech recognition, and reads steps out
// loud. Where the browser has no speech recognition (Firefox, some kiosk builds of Chromium) the switch isn't shown.

export type VoiceCommand = "next" | "back" | "repeat" | "start-timer" | "stop-timer" | "ingredients";

const COMMANDS: [RegExp, VoiceCommand][] = [
  [/\b(start|set)\b.*\btimer\b|\btimer\b.*\bstart/, "start-timer"],
  [/\b(stop|cancel|silence)\b.*\btimer\b|\bstop\b/, "stop-timer"],
  [/\b(next|forward|done|go on|continue)\b/, "next"],
  [/\b(back|previous|go back|last step)\b/, "back"],
  [/\b(repeat|again|read|what was that|say that)\b/, "repeat"],
  [/\bingredients?\b/, "ingredients"],
];

/** What a heard phrase asks for, if anything. */
export function commandFor(phrase: string): VoiceCommand | null {
  const p = phrase.toLowerCase();
  for (const [re, cmd] of COMMANDS) if (re.test(p)) return cmd;
  return null;
}

type Recognition = {
  continuous: boolean; interimResults: boolean; lang: string;
  onresult: ((e: { resultIndex: number; results: ArrayLike<ArrayLike<{ transcript: string }> & { isFinal: boolean }> }) => void) | null;
  onend: (() => void) | null; onerror: ((e: { error: string }) => void) | null;
  start(): void; stop(): void;
};
const Ctor = (): (new () => Recognition) | undefined => {
  const w = window as unknown as { SpeechRecognition?: new () => Recognition; webkitSpeechRecognition?: new () => Recognition };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition;
};
export const voiceSupported = () => typeof window !== "undefined" && !!Ctor();

/** Read text aloud (cancelling anything still being read). */
export function speak(text: string) {
  if (typeof speechSynthesis === "undefined") return;
  speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.rate = 0.95;
  speechSynthesis.speak(u);
}

/** Listen while `on` is true; calls `onCommand` for each recognised command. Returns an error to show, if any. */
export function useVoice(on: boolean, onCommand: (c: VoiceCommand) => void): string | null {
  const handler = useRef(onCommand);
  handler.current = onCommand;
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const C = Ctor();
    if (!on || !C) return;
    let stopped = false;
    const rec = new C();
    rec.continuous = true;
    rec.interimResults = false;
    rec.lang = navigator.language || "en-GB";
    rec.onresult = (e) => {
      for (let i = e.resultIndex; i < e.results.length; i++) {
        if (!e.results[i].isFinal) continue;
        const cmd = commandFor(e.results[i][0].transcript);
        if (cmd) handler.current(cmd);
      }
    };
    rec.onerror = (e) => {
      if (e.error === "not-allowed" || e.error === "service-not-allowed") { stopped = true; setError("Moonlight isn't allowed to use the microphone here."); }
      else if (e.error === "network") { stopped = true; setError("Speech recognition isn't available on this screen."); }
    };
    // Recognition stops by itself after a while of silence: keep it going while cook mode is open.
    rec.onend = () => { if (!stopped) { try { rec.start(); } catch { /* already started */ } } };
    setError(null);
    try { rec.start(); } catch { /* already started */ }
    return () => { stopped = true; rec.onend = null; try { rec.stop(); } catch { /* not started */ } };
  }, [on]);
  return on ? error : null;
}
