import { useEffect, useState } from "react";
import { ApiError, Layout, STYLE_LABEL, VoiceReplies, VoiceSettings, VoiceStatus } from "../api/types";
import { useApp } from "../state";
import { Segmented } from "../components/ui";
import { MIC_PROBLEM, micProblem } from "../voice/mic";

const STYLES: Layout[] = ["large", "compact", "phone"];
const REPLIES: { value: VoiceReplies; label: string }[] = [
  { value: "screen", label: "This screen" }, { value: "speaker", label: "Its speaker" }, { value: "none", label: "Text only" },
];

/** Settings › Voice: Assist from Home Assistant. Which assistant (pipeline), the wake word per style of screen,
 * and where answers are spoken. */
export function VoicePanel() {
  const { api, layout, settings, askPin, toast } = useApp();
  const [status, setStatus] = useState<VoiceStatus | null>(null);
  useEffect(() => { api.voiceStatus(layout).then(setStatus).catch(() => setStatus(null)); }, [api, layout, settings?.voice]);

  async function save(voice: Partial<Omit<VoiceSettings, "wake">> & { wake?: Partial<Record<Layout, boolean>> }, why: string) {
    const pin = await askPin(why);
    if (!pin) return;
    try { await api.updateSettings({ voice, pin }); toast("Saved"); }
    catch (e) { toast(e instanceof ApiError ? e.message : "Couldn't save"); }
  }

  if (status && !status.available) {
    return (
      <section className="panel">
        <h2 className="panel-title">Voice</h2>
        <p className="muted connect-note">{status.reason ?? "Assist isn't available"}. Voice comes from Home Assistant's Assist, so this needs
          Moonlight running as the add-on.</p>
      </section>
    );
  }
  const pipeline = status?.pipelines.find((p) => p.id === status.pipeline);
  const preferred = status?.pipelines.find((p) => p.id === status.preferred);
  const wake = status?.wake_by_layout ?? { large: false, compact: false, phone: false };
  const mic = micProblem();
  const missing = pipeline && [!pipeline.stt && "speech-to-text (Whisper)", !pipeline.tts && "a voice (Piper)"].filter(Boolean);
  return (
    <section className="panel">
      <h2 className="panel-title">Voice</h2>
      <p className="muted connect-note">Tap the microphone at the top of any screen and ask Home Assistant's Assist anything it can do:
        turn on lights, add to a list, set a timer, ask the weather. With the wake word on, just say it ("Okay Nabu") from across the room.
        What Assist can control is set in Home Assistant under Settings › Voice assistants › Expose.</p>
      <div className="set-row"><span>Assistant</span>
        <select className="input voice-select" value={settings?.voice?.pipeline ?? ""} disabled={!status}
          onChange={(e) => save({ pipeline: e.target.value }, "Change the assistant")}>
          <option value="">{preferred ? `Home Assistant's preferred (${preferred.name})` : "Home Assistant's preferred"}</option>
          {status?.pipelines.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
      </div>
      {missing && missing.length > 0 && (
        <p className="connect-error">{pipeline!.name} has no {missing.join(" or ")} yet, so screens can only take typed questions.
          Add it in Home Assistant (Settings › Voice assistants).</p>
      )}
      <div className="set-row"><span>Wake word on</span>
        <span className="set-pin sec-popup-on">
          {STYLES.map((l) => (
            <button key={l} className={"chip-btn" + (wake[l] ? " on" : "")} disabled={!status}
              onClick={() => save({ wake: { [l]: !wake[l] } }, "Change where the wake word listens")}>{STYLE_LABEL[l]}</button>
          ))}
        </span>
      </div>
      {status && !status.wake_engine && Object.values(wake).some(Boolean) && (
        <p className="connect-error">Home Assistant has no wake word engine. Add the openWakeWord add-on.</p>
      )}
      <p className="muted connect-note">The wake word is {pipeline?.wake_word ? <b>{pipeline.wake_word.replace(/_/g, " ")}</b> : "the assistant's own"} (change it in
        Home Assistant's assistant settings). Screens listening for it stream their microphone to Home Assistant, which does the listening, and show a green dot on the microphone.</p>
      <div className="set-row"><span>Answers out loud on</span>
        <Segmented value={settings?.voice?.replies ?? "screen"} options={REPLIES} onChange={(v) => save({ replies: v }, "Change where answers are spoken")} />
      </div>
      <div className="set-row stack"><span>This screen's microphone</span>
        <span className="muted">{mic ? MIC_PROBLEM[mic] : "Ready (the browser asks the first time)."}</span>
      </div>
    </section>
  );
}
