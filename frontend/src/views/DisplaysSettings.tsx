import { useState } from "react";
import { ApiError, Display, Layout, Settings } from "../api/types";
import { useApp, useData, useNow } from "../state";
import { Segmented, Sheet } from "../components/ui";

const LAYOUT_LABEL: Record<Display["layout"], string> = { hallway: "Hallway 27in", kitchen: "Kitchen 10in", phone: "Phone", service: "Integration" };

export function ago(isoTime: string | null, now: Date): string {
  if (!isoTime) return "Not seen yet";
  const mins = Math.floor((now.getTime() - new Date(isoTime).getTime()) / 60000);
  if (mins < 1) return "Just now";
  if (mins < 60) return `${mins} min ago`;
  const h = Math.floor(mins / 60);
  if (h < 24) return `${h} h ago`;
  const d = Math.floor(h / 24);
  return d === 1 ? "Yesterday" : `${d} days ago`;
}

/** Settings > Screens: paired wall screens, revoke, pair a new one with its 6-digit code. */
export function ScreensPanel() {
  const { api, askPin, toast } = useApp();
  const [screens] = useData((a) => a.displays(), ["displays"], []);
  const [pairing, setPairing] = useState(false);
  const now = useNow(30_000);

  async function revoke(d: Display) {
    const pin = await askPin(`Revoke ${d.name}? It will need pairing again.`);
    if (!pin) return;
    try { await api.revokeDisplay(d.id, pin); toast(`${d.name} revoked`); }
    catch (e) { toast(e instanceof ApiError ? e.message : "Couldn't revoke"); }
  }

  return (
    <section className="panel screens-panel">
      <div className="panel-head">
        <h2 className="panel-title">Screens</h2>
        <button className="btn small" onClick={() => setPairing(true)}>Pair a new screen</button>
      </div>
      <p className="muted screens-help">
        Wall screens open <code>http://&lt;home-assistant&gt;:8099/display/kitchen</code> and show a 6-digit code.
        Phones using the Home Assistant app don't need pairing. The Moonlight integration in Home Assistant shows
        a code to enter here too.
      </p>
      {screens && screens.length === 0 && <div className="screens-empty">No screens paired yet.</div>}
      <div className="screen-list">
        {(screens ?? []).map((d) => (
          <div key={d.id} className="screen-row">
            <span className={`screen-ico ${d.layout}`} aria-hidden />
            <div className="screen-main">
              <b>{d.name}{d.current && <em className="screen-this">This screen</em>}</b>
              <span>{LAYOUT_LABEL[d.layout]} · {ago(d.last_seen, now)}</span>
            </div>
            <button className="btn ghost small danger" onClick={() => revoke(d)}>Revoke</button>
          </div>
        ))}
      </div>
      {pairing && <PairSheet onClose={() => setPairing(false)} />}
    </section>
  );
}

function PairSheet({ onClose }: { onClose: () => void }) {
  const { api, askPin, toast } = useApp();
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [layout, setLayout] = useState<Layout | "auto">("auto");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const valid = /^\d{6}$/.test(code);

  async function submit() {
    if (!valid || busy) return;
    const pin = await askPin("Pair a new screen");
    if (!pin) return;
    setBusy(true);
    try {
      const d = await api.approveDisplay(code, name.trim(), layout === "auto" ? null : layout, pin);
      toast(`${d.name} paired`);
      onClose();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't pair that screen");
    } finally { setBusy(false); }
  }

  return (
    <Sheet title="Pair a new screen" onClose={onClose} footer={<>
      <button className="btn ghost" onClick={onClose}>Cancel</button>
      <button className="btn" disabled={!valid || busy} onClick={submit}>Pair screen</button>
    </>}>
      <div className="form">
        <div className="field-label">Code shown on the screen</div>
        <input className="input big pair-code-input" inputMode="numeric" autoComplete="one-time-code" placeholder="000000"
          maxLength={7} value={code} autoFocus
          onChange={(e) => { setCode(e.target.value.replace(/\D/g, "").slice(0, 6)); setError(null); }}
          onKeyDown={(e) => e.key === "Enter" && submit()} />
        <div className="field-label">Name</div>
        <input className="input" placeholder="e.g. Kitchen" value={name} maxLength={60} onChange={(e) => setName(e.target.value)} />
        <div className="chip-row">
          {["Hallway", "Kitchen", "Living room", "Bedroom"].map((n) => (
            <button key={n} className={"chip-btn" + (name === n ? " on" : "")} onClick={() => setName(n)}>{n}</button>
          ))}
        </div>
        <div className="field-label">Layout</div>
        <Segmented value={layout} onChange={setLayout} options={[
          { value: "auto", label: "As the screen asked" }, { value: "hallway", label: "Hallway" },
          { value: "kitchen", label: "Kitchen" }, { value: "phone", label: "Phone" },
        ]} />
        {error && <div className="form-error">{error}</div>}
      </div>
    </Sheet>
  );
}

/** Settings > Photo screensaver: which album, how long per photo, when to start. */
export function ScreensaverPanel({ onScreensaver }: { onScreensaver: () => void }) {
  const { api, settings, askPin, toast } = useApp();
  const [albums] = useData((a) => a.albums(), ["photos"], []);
  async function save(patch: Partial<Settings>, why: string) {
    const pin = await askPin(why);
    if (!pin) return;
    try { await api.updateSettings({ ...patch, pin }); toast("Saved"); }
    catch (e) { toast(e instanceof ApiError ? e.message : "Couldn't save"); }
  }
  const album = settings?.screensaver_album ?? null;
  const secs = settings?.screensaver_seconds ?? 10;
  const idle = { hallway: 5, kitchen: 3, phone: 0, ...settings?.idle_minutes };
  const idleOpts = [0, 1, 3, 5, 10, 30].map((v) => ({ value: String(v), label: v === 0 ? "Never" : `${v} min` }));
  return (
    <section className="panel">
      <h2 className="panel-title">Photo screensaver</h2>
      <div className="set-col"><span>Show photos from</span>
        <div className="chip-row">
          <button className={"chip-btn" + (album === null ? " on" : "")} onClick={() => album !== null && save({ screensaver_album: null }, "Change screensaver album")}>All photos</button>
          {(albums ?? []).map((a) => (
            <button key={a.id} className={"chip-btn" + (album === a.id ? " on" : "")}
              onClick={() => album !== a.id && save({ screensaver_album: a.id }, "Change screensaver album")}>{a.name}</button>
          ))}
        </div>
      </div>
      <div className="set-col"><span>Each photo for</span>
        <Segmented value={String(secs)} onChange={(v) => save({ screensaver_seconds: Number(v) }, "Change photo timing")}
          options={[5, 10, 20, 30, 60].map((v) => ({ value: String(v), label: `${v}s` }))} />
      </div>
      {(["hallway", "kitchen"] as const).map((l) => (
        <div key={l} className="set-col"><span>{l === "hallway" ? "Hallway" : "Kitchen"} starts after</span>
          <Segmented value={String(idle[l])} options={idleOpts}
            onChange={(v) => save({ idle_minutes: { [l]: Number(v) } }, "Change screensaver timing")} />
        </div>
      ))}
      <div className="set-row"><span>Try it</span><button className="btn ghost" onClick={onScreensaver}>Show now</button></div>
    </section>
  );
}
