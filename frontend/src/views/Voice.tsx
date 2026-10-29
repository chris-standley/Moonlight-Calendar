import { createContext, FormEvent, ReactNode, RefObject, useCallback, useContext, useEffect, useRef, useState } from "react";
import { Api, VoiceEvent, VoiceLink, VoiceMode, VoiceStatus } from "../api/types";
import { Layout, useApp } from "../state";
import { IconClose, IconMic } from "../components/icons";
import { chime, Mic, MIC_PROBLEM, MicError, micProblem, openMic } from "../voice/mic";

/* Assist, Home Assistant's voice assistant, on this screen: tap the mic (or say the wake word, where it's on) and
 * ask. Moonlight relays the microphone to Home Assistant and shows what was heard and the answer, and speaks it. */

type Phase = "idle" | "listening" | "thinking" | "speaking";
interface Turn { you?: string; reply?: string; failed?: boolean }

const CONVERSATION_MS = 5 * 60_000; // a follow-up within this long carries on the same conversation
const LISTEN_MAX_MS = 15_000; // stop listening even if Home Assistant hasn't heard the end yet
const CLOSE_AFTER_MS = 12_000; // the sheet goes once the answer has been on screen this long, untouched
const RETRY_MS = 5_000;

const FAILED: Record<string, string> = {
  "stt-no-text-recognized": "Sorry, I didn't catch that.",
  "stt-stream-failed": "Sorry, I didn't catch that.",
  "stt-provider-missing": "Home Assistant has no speech-to-text yet. Add Whisper (Settings › Voice).",
  "tts-not-supported": "Home Assistant couldn't say the answer out loud.",
  unreachable: "Couldn't reach Home Assistant.",
};

interface VoiceCtx {
  status: VoiceStatus | null;
  /** Hands-free wake word is listening on this screen now. */
  waking: boolean;
  open(): void;
}
const Ctx = createContext<VoiceCtx>({ status: null, waking: false, open: () => undefined });
export const useVoice = () => useContext(Ctx);

export function VoiceProvider({ api, layout, children }: { api: Api; layout: Layout; children: ReactNode }) {
  const [status, setStatus] = useState<VoiceStatus | null>(null);
  const [shown, setShown] = useState(false);
  const [phase, setPhase] = useState<Phase>("idle");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [notice, setNotice] = useState<string | null>(null);
  const [waking, setWaking] = useState(false);
  const levelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let live = true;
    const load = () => api.voiceStatus(layout).then((s) => { if (live) setStatus(s); }).catch(() => { if (live) setStatus(null); });
    load();
    const off = api.subscribe((t) => { if (t === "settings") load(); });
    return () => { live = false; off(); };
  }, [api, layout]);

  const pipeline = status?.pipelines.find((p) => p.id === status.pipeline);
  const canHear = !!status?.available && !!pipeline?.stt;
  const wakeWanted = canHear && !!status?.wake && !!status?.wake_engine && api.mode === "live" && micProblem() === null;

  // Everything the event handler needs, without re-creating the link on every render.
  const r = useRef({
    link: null as VoiceLink | null, mic: null as Mic | null, micFailed: null as string | null, streaming: false,
    mode: null as VoiceMode | null, audio: null as HTMLAudioElement | null, conv: { id: null as string | null, at: 0 },
    again: false, shown: false, wake: false, done: false, woke: false, wakeFailed: false, listenTimer: 0, closeTimer: 0, retryTimer: 0,
  });
  r.current.shown = shown;
  r.current.wake = wakeWanted;

  const setTurn = (patch: Partial<Turn>) => setTurns((t) => (t.length ? [...t.slice(0, -1), { ...t[t.length - 1], ...patch }] : [patch]));
  const newTurn = () => setTurns((t) => [...t.slice(-3), {}]);

  const scheduleClose = useCallback(() => {
    clearTimeout(r.current.closeTimer);
    r.current.closeTimer = window.setTimeout(() => setShown(false), CLOSE_AFTER_MS);
  }, []);

  const stopListening = () => {
    const s = r.current;
    clearTimeout(s.listenTimer);
    // In a wake word run only once it has woken: before that, ending the audio would end the run.
    if (s.streaming && (s.mode !== "wake" || s.woke)) s.link?.stop();
    s.streaming = false;
  };

  const ensureMic = useCallback(async (): Promise<boolean> => {
    const s = r.current;
    if (s.mic) return true;
    try {
      s.mic = await openMic();
      s.micFailed = null;
      s.mic.onChunk = (pcm, level) => {
        if (s.streaming && !s.audio) s.link?.audio(pcm);
        if (s.shown && levelRef.current) levelRef.current.style.setProperty("--level", s.streaming ? level.toFixed(2) : "0");
      };
      return true;
    } catch (e) {
      s.micFailed = e instanceof MicError ? e.message : MIC_PROBLEM.unsupported;
      return false;
    }
  }, []);

  const releaseMic = () => {
    const s = r.current;
    if (s.wake || !s.mic) return; // the wake word keeps it
    s.mic.stop();
    s.mic = null;
  };

  // Listening for the wake word again (after an answer, a drop, or when it's switched on).
  const startWake = useCallback(async () => {
    const s = r.current;
    if (!s.wake || s.mode) return;
    if (!(await ensureMic())) { setWaking(false); return; }
    if (!s.wake || s.mode) return;
    s.link ??= api.voice(layout, (e) => onEventRef.current(e));
    s.mode = "wake";
    s.woke = false;
    s.wakeFailed = false;
    s.streaming = true;
    s.link.start("wake");
    setWaking(true);
  }, [api, layout, ensureMic]);

  const finish = useCallback(() => {
    const s = r.current;
    s.mode = null;
    s.streaming = false;
    setPhase("idle");
    if (s.again && s.shown) { s.again = false; void listenRef.current(); return; }
    s.again = false;
    if (s.shown) scheduleClose();
    clearTimeout(s.retryTimer);
    // A wake word run that failed before it woke (Home Assistant restarting, say) tries again in a little while.
    if (s.wake) s.retryTimer = window.setTimeout(() => void startWake(), s.wakeFailed ? RETRY_MS : 0);
    else releaseMic();
  }, [scheduleClose, startWake]);

  const onEvent = useCallback((e: VoiceEvent) => {
    const s = r.current;
    switch (e.type) {
      case "woke":
        s.woke = true;
        chime();
        clearTimeout(s.closeTimer);
        setNotice(null);
        newTurn();
        setShown(true);
        setPhase("listening");
        s.listenTimer = window.setTimeout(stopListening, LISTEN_MAX_MS);
        break;
      case "listening":
        if (s.mode !== "wake") setPhase("listening");
        break;
      case "speech_end":
        stopListening();
        setPhase("thinking");
        break;
      case "heard":
        stopListening();
        setTurn({ you: e.text || "…" });
        setPhase("thinking");
        break;
      case "thinking":
        setPhase("thinking");
        break;
      case "reply":
        setTurn({ reply: e.text || "Done." });
        s.conv = { id: e.conversation_id, at: Date.now() };
        s.again = e.continue;
        break;
      case "audio": {
        const a = new Audio(e.url);
        s.audio = a;
        setPhase("speaking");
        const end = () => { if (s.audio !== a) return; s.audio = null; if (s.done) finish(); };
        a.onended = end;
        a.onerror = end;
        a.play().catch(end); // a browser that blocks sound without a tap: the answer is on screen anyway
        break;
      }
      case "error":
        stopListening();
        s.again = false;
        if (s.mode === "wake" && !s.woke) {
          // Nobody asked anything yet: no need to show it (a timeout is just the hour being up).
          if (e.code !== "wake-word-timeout") { s.wakeFailed = true; console.warn("Wake word:", e.code, e.message); }
          break;
        }
        setTurn({ reply: FAILED[e.code] ?? (e.message || "Something went wrong."), failed: true });
        break;
      case "done":
        s.done = true;
        if (!s.audio) finish();
        break;
      case "closed":
        s.link = null;
        s.audio = null;
        if (s.mode && s.mode !== "wake") setTurn({ reply: FAILED.unreachable, failed: true });
        s.mode = null;
        s.streaming = false;
        setPhase("idle");
        setWaking(false);
        clearTimeout(s.retryTimer);
        if (s.wake) s.retryTimer = window.setTimeout(() => void startWake(), RETRY_MS);
        break;
    }
    if (e.type !== "done") s.done = false;
  }, [finish, startWake]);
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;

  const run = useCallback((mode: "listen" | "text", text?: string) => {
    const s = r.current;
    clearTimeout(s.closeTimer);
    s.audio?.pause();
    s.audio = null;
    s.link ??= api.voice(layout, (e) => onEventRef.current(e));
    const conversation_id = Date.now() - s.conv.at < CONVERSATION_MS ? s.conv.id : null;
    s.mode = mode;
    s.done = false;
    s.again = false;
    newTurn();
    setNotice(null);
    if (mode === "text") {
      s.streaming = false;
      setTurn({ you: text });
      setPhase("thinking");
      s.link.start("text", { text, conversation_id });
    } else {
      s.streaming = true;
      setPhase("listening");
      s.link.start("listen", { conversation_id });
      s.listenTimer = window.setTimeout(stopListening, LISTEN_MAX_MS);
    }
  }, [api, layout]);

  const listen = useCallback(async () => {
    const s = r.current;
    if (!(await ensureMic())) {
      setNotice(s.micFailed);
      setPhase("idle");
      return;
    }
    run("listen");
  }, [ensureMic, run]);
  const listenRef = useRef(listen);
  listenRef.current = listen;

  const open = useCallback(() => {
    setShown(true);
    setTurns([]);
    if (canHear) void listen();
    else setNotice(status?.available ? "Home Assistant has no speech-to-text yet, so type instead (Settings › Voice)." : status?.reason ?? "Assist isn't available");
  }, [canHear, listen, status]);

  const close = useCallback(() => {
    const s = r.current;
    clearTimeout(s.closeTimer);
    clearTimeout(s.listenTimer);
    s.audio?.pause();
    s.audio = null;
    s.again = false;
    if (s.mode && (s.mode !== "wake" || s.woke)) { // a wake word run that never woke just carries on
      s.link?.cancel();
      s.mode = null;
      s.streaming = false;
    }
    setShown(false);
    setPhase("idle");
    if (s.wake) void startWake();
    else releaseMic();
  }, [startWake]);

  // Hands-free: listen for the wake word while it's on for this screen; let go of everything when it isn't.
  useEffect(() => {
    const s = r.current;
    if (wakeWanted) { void startWake(); return; }
    setWaking(false);
    if (s.mode === "wake") { s.link?.cancel(); s.mode = null; s.streaming = false; }
    if (!s.shown && s.mic) { s.mic.stop(); s.mic = null; }
  }, [wakeWanted, startWake]);
  useEffect(() => () => {
    const s = r.current;
    [s.closeTimer, s.listenTimer, s.retryTimer].forEach(clearTimeout);
    s.audio?.pause();
    s.link?.close();
    s.mic?.stop();
  }, []);

  return (
    <Ctx.Provider value={{ status, waking, open }}>
      {children}
      {shown && <VoiceSheet phase={phase} turns={turns} notice={notice} canHear={canHear} levelRef={levelRef}
        onListen={() => void listen()} onStop={stopListening} onText={(t) => run("text", t)} onClose={close}
        onTouch={() => clearTimeout(r.current.closeTimer)} />}
    </Ctx.Provider>
  );
}

const PHASE_LABEL: Record<Phase, string> = { idle: "Ask me something", listening: "Listening…", thinking: "Thinking…", speaking: "" };

function VoiceSheet({ phase, turns, notice, canHear, levelRef, onListen, onStop, onText, onClose, onTouch }: {
  phase: Phase; turns: Turn[]; notice: string | null; canHear: boolean; levelRef: RefObject<HTMLDivElement | null>;
  onListen(): void; onStop(): void; onText(t: string): void; onClose(): void; onTouch(): void;
}) {
  const [text, setText] = useState("");
  const shown = turns.filter((t) => t.you || t.reply);
  const send = (e: FormEvent) => {
    e.preventDefault();
    if (!text.trim()) return;
    onText(text.trim());
    setText("");
  };
  return (
    <div className="voice-scrim" onPointerDown={onTouch} onClick={onClose}>
      <div className="voice-card" onClick={(e) => e.stopPropagation()} role="dialog" aria-label="Assist">
        <button className="icon-btn voice-close" onClick={onClose} aria-label="Close"><IconClose /></button>
        <div className="voice-turns" aria-live="polite">
          {shown.map((t, i) => (
            <div key={i} className="voice-turn">
              {t.you && <p className="voice-you">{t.you}</p>}
              {t.reply && <p className={"voice-reply" + (t.failed ? " failed" : "")}>{t.reply}</p>}
            </div>
          ))}
          {notice && <p className="voice-notice">{notice}</p>}
        </div>
        <div className={`voice-orb ${phase}`} ref={levelRef}>
          <button className="voice-mic" disabled={!canHear} aria-label={phase === "listening" ? "Stop listening" : "Talk"}
            onClick={phase === "listening" ? onStop : onListen}><IconMic size={34} /></button>
        </div>
        <div className="voice-phase">{PHASE_LABEL[phase]}</div>
        <form className="voice-type" onSubmit={send}>
          <input className="input" value={text} onChange={(e) => setText(e.target.value)} placeholder="Or type a question" aria-label="Question" />
          <button className="btn" disabled={!text.trim()}>Ask</button>
        </form>
      </div>
    </div>
  );
}

/** The top bar's mic: opens Assist. A dot shows while the wake word is listening. */
export function VoiceButton() {
  const { status, waking, open } = useVoice();
  const { layout } = useApp();
  if (!status?.available) return null;
  return (
    <button className={"tb-voice" + (waking ? " waking" : "")} onClick={open} aria-label="Assist">
      <IconMic size={layout === "large" ? 30 : 24} />
    </button>
  );
}
