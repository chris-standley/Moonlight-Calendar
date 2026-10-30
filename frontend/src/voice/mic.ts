// The screen's microphone as 16 kHz, 16-bit mono PCM: what Home Assistant's Assist takes. An AudioWorklet does the
// resampling off the main thread and hands over ~80 ms chunks.

const RATE = 16000;
const CHUNK = 1280; // samples: 80 ms

const WORKLET = `
class MoonlightMic extends AudioWorkletProcessor {
  constructor() { super(); this.step = sampleRate / ${RATE}; this.pos = 0; this.last = 0; this.buf = new Int16Array(${CHUNK}); this.n = 0; this.sum = 0; }
  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (!ch) return true;
    // Linear interpolation from the device's rate to 16 kHz, over [last sample of the previous block, ...this block].
    const len = ch.length;
    while (this.pos < len) {
      const i = Math.floor(this.pos), f = this.pos - i;
      const a = i === 0 ? this.last : ch[i - 1], b = ch[i];
      const v = Math.max(-1, Math.min(1, a + (b - a) * f));
      this.buf[this.n++] = v < 0 ? v * 0x8000 : v * 0x7fff;
      this.sum += v * v;
      if (this.n === ${CHUNK}) {
        this.port.postMessage({ pcm: this.buf.buffer, level: Math.sqrt(this.sum / ${CHUNK}) }, [this.buf.buffer]);
        this.buf = new Int16Array(${CHUNK}); this.n = 0; this.sum = 0;
      }
      this.pos += this.step;
    }
    this.pos -= len;
    this.last = ch[len - 1];
    return true;
  }
}
registerProcessor("moonlight-mic", MoonlightMic);
`;

export type MicProblem = "insecure" | "unsupported" | "denied" | "none";

/** Why this screen can't listen (null: it can try). Browsers only give pages a microphone over https or on localhost. */
export function micProblem(): MicProblem | null {
  if (!window.isSecureContext) return "insecure";
  if (!navigator.mediaDevices?.getUserMedia || typeof AudioWorkletNode === "undefined") return "unsupported";
  return null;
}

export const MIC_PROBLEM: Record<MicProblem, string> = {
  insecure: "This screen opens Moonlight over plain http, and browsers only allow the microphone over https. Open Moonlight's https address on this screen, or type instead.",
  unsupported: "This browser can't use a microphone. Type instead.",
  denied: "The microphone is blocked for Moonlight on this screen. Allow it in the browser's site settings.",
  none: "No microphone found. Plug one in (a USB speakerphone works well), or type instead.",
};

export interface Mic {
  /** Each chunk of audio while `on`; level is 0..1 (loudness, for the animation). */
  onChunk: ((pcm: ArrayBuffer, level: number) => void) | null;
  stop(): void;
}

export class MicError extends Error {
  constructor(public problem: MicProblem) { super(MIC_PROBLEM[problem]); }
}

export async function openMic(): Promise<Mic> {
  const why = micProblem();
  if (why) throw new MicError(why);
  let stream: MediaStream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
  } catch (e) {
    const name = (e as DOMException)?.name;
    throw new MicError(name === "NotFoundError" || name === "OverconstrainedError" ? "none" : name === "NotAllowedError" || name === "SecurityError" ? "denied" : "unsupported");
  }
  let ctx: AudioContext;
  try { ctx = new AudioContext({ sampleRate: RATE }); } // Chromium resamples the mic for us when it can
  catch { ctx = new AudioContext(); }
  const url = URL.createObjectURL(new Blob([WORKLET], { type: "text/javascript" }));
  try { await ctx.audioWorklet.addModule(url); } finally { URL.revokeObjectURL(url); }
  const src = ctx.createMediaStreamSource(stream);
  const node = new AudioWorkletNode(ctx, "moonlight-mic");
  // Through a silent gain to the speakers: some browsers only run a node that leads to the output.
  const mute = ctx.createGain();
  mute.gain.value = 0;
  src.connect(node).connect(mute).connect(ctx.destination);
  // A page that opens the microphone by itself (the wake word, after loading) may not be allowed to start audio
  // until someone touches the screen, and a kiosk can suspend it when the screen sleeps: keep asking.
  const wake = () => { if (ctx.state !== "running" && ctx.state !== "closed") void ctx.resume().catch(() => undefined); };
  ctx.onstatechange = wake;
  document.addEventListener("pointerdown", wake, true);
  document.addEventListener("visibilitychange", wake);
  const timer = window.setInterval(wake, 10_000);
  if (ctx.state === "suspended") await Promise.race([ctx.resume().catch(() => undefined), new Promise((r) => setTimeout(r, 1000))]);
  const mic: Mic = {
    onChunk: null,
    stop() {
      clearInterval(timer);
      ctx.onstatechange = null;
      document.removeEventListener("pointerdown", wake, true);
      document.removeEventListener("visibilitychange", wake);
      node.port.onmessage = null;
      src.disconnect();
      stream.getTracks().forEach((t) => t.stop());
      void ctx.close().catch(() => undefined);
    },
  };
  node.port.onmessage = (m) => mic.onChunk?.(m.data.pcm, Math.min(1, m.data.level * 4));
  return mic;
}

/** A soft two-note chime: "I'm listening". */
export function chime() {
  try {
    const ctx = new AudioContext();
    const t = ctx.currentTime;
    [660, 880].forEach((f, i) => {
      const o = ctx.createOscillator(), g = ctx.createGain();
      o.frequency.value = f;
      g.gain.setValueAtTime(0, t + i * 0.12);
      g.gain.linearRampToValueAtTime(0.18, t + i * 0.12 + 0.02);
      g.gain.exponentialRampToValueAtTime(0.001, t + i * 0.12 + 0.25);
      o.connect(g).connect(ctx.destination);
      o.start(t + i * 0.12);
      o.stop(t + i * 0.12 + 0.3);
    });
    setTimeout(() => void ctx.close().catch(() => undefined), 800);
  } catch { /* no audio output */ }
}
