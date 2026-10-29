// Demo-mode voice: a pretend Assist that "hears" a question a moment after you start talking and answers it, so the
// voice sheet can be tried (and photographed) without Home Assistant. Typed questions get a canned answer too.
import { Api, Layout, Settings, VoiceEvent, VoiceSettings } from "./types";

type Extras = Pick<Api, "voiceStatus" | "voice">;

export const DEFAULT_VOICE: VoiceSettings = { pipeline: "", wake: { large: false, compact: false, phone: false }, replies: "screen" };

const ANSWERS: [RegExp, string][] = [
  [/dinner|tea|eat/i, "Tonight it's spaghetti bolognese."],
  [/light/i, "Turned on the kitchen lights."],
  [/weather|rain|coat/i, "It's 14 degrees and cloudy, with a 20% chance of rain this afternoon."],
  [/timer/i, "Timer set for 10 minutes."],
];
const HEARD = "What's for dinner tonight?";

function answer(text: string): string {
  return ANSWERS.find(([re]) => re.test(text))?.[1] ?? "Sorry, I'm only a demo. In your home, Home Assistant answers here.";
}

export function demoVoice(voice: () => Settings["voice"]): Extras {
  return {
    async voiceStatus(layout: Layout) {
      const v = voice() ?? DEFAULT_VOICE;
      return {
        available: true, preferred: "demo", pipeline: v.pipeline || "demo", wake_engine: true,
        pipelines: [{ id: "demo", name: "Home Assistant", language: "en", stt: true, tts: true, wake_word: "ok_nabu", agent: "conversation.home_assistant" }],
        wake: v.wake[layout], wake_by_layout: v.wake, replies: v.replies,
      };
    },
    voice(_layout, onEvent) {
      const timers: ReturnType<typeof setTimeout>[] = [];
      const later = (ms: number, e: VoiceEvent) => timers.push(setTimeout(() => onEvent(e), ms));
      const clear = () => { timers.forEach(clearTimeout); timers.length = 0; };
      const reply = (at: number, text: string, conv: string | null | undefined) => {
        later(at, { type: "thinking" });
        later(at + 700, { type: "reply", text: answer(text), kind: "action_done", continue: false, conversation_id: conv || "demo-conversation" });
        later(at + 800, { type: "done" });
      };
      setTimeout(() => onEvent({ type: "ready" }), 50);
      return {
        start(mode, opts) {
          clear();
          if (mode === "text") { reply(100, opts?.text ?? "", opts?.conversation_id); return; }
          if (mode === "wake") { later(50, { type: "waiting" }); return; } // the demo never hears a wake word
          later(50, { type: "listening" });
          later(2200, { type: "speech_end" });
          later(2500, { type: "heard", text: HEARD });
          reply(2600, HEARD, opts?.conversation_id);
        },
        audio() { /* nobody's listening */ },
        stop() { /* it "hears" the silence itself */ },
        cancel() { clear(); },
        close() { clear(); },
      };
    },
  };
}
