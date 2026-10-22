import { useState } from "react";
import { ApiError, MusicAssistantLink } from "../api/types";
import { useApp, useData } from "../state";
import { Sheet } from "../components/ui";

/** Settings › Music: which speaker each screen uses lives in Settings › Screens; this is Moonlight's own (optional)
 * connection to Music Assistant, which Home Assistant can't give it: the whole queue, and changing it. */
export function MusicPanel() {
  const { api, askPin, toast } = useApp();
  const [link, reload] = useData((a) => a.musicAssistant(), ["media"], []);
  const [editing, setEditing] = useState(false);
  async function disconnect() {
    const pin = await askPin("Disconnect Music Assistant");
    if (!pin) return;
    try { await api.removeMusicAssistant(pin); toast("Music Assistant disconnected"); reload(); }
    catch (e) { toast(e instanceof ApiError ? e.message : "Couldn't disconnect"); }
  }
  return (
    <section className="panel">
      <h2 className="panel-title">Music</h2>
      <p className="muted connect-note">Screens with a speaker (Settings › Screens) get a Music section: what's playing, the queue, your
        library and the other rooms. It all goes through Home Assistant. Home Assistant only knows the current and next track of a
        Music Assistant queue, so to see and change the whole queue, connect Moonlight to Music Assistant too.</p>
      <div className="set-row stack"><span>Music Assistant</span>
        <span className="set-pin"><b className="clip">{link?.token_set ? `Connected · ${link.url || link.detected_url || "found automatically"}` : "Not connected"}</b>
          <button className="btn ghost small" onClick={() => setEditing(true)}>{link?.token_set ? "Change" : "Connect"}</button>
          {link?.token_set && <button className="btn ghost small danger" onClick={disconnect}>Disconnect</button>}</span>
      </div>
      {editing && <LinkSheet link={link} onClose={() => { setEditing(false); reload(); }} />}
    </section>
  );
}

function LinkSheet({ link, onClose }: { link: MusicAssistantLink | undefined; onClose: () => void }) {
  const { api, askPin, toast } = useApp();
  const [url, setUrl] = useState(link?.url ?? "");
  const [token, setToken] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  async function save() {
    const pin = await askPin("Connect Music Assistant");
    if (!pin) return;
    setBusy(true);
    setError(null);
    try {
      await api.saveMusicAssistant({ url: url.trim(), ...(token.trim() ? { token: token.trim() } : {}), pin });
      toast("Connected to Music Assistant");
      onClose();
    } catch (e) { setError(e instanceof ApiError ? e.message : "Couldn't connect"); }
    finally { setBusy(false); }
  }
  return (
    <Sheet title="Music Assistant" onClose={onClose} footer={<>
      <span style={{ flex: 1 }} />
      <button className="btn ghost" onClick={onClose}>Cancel</button>
      <button className="btn" onClick={save} disabled={busy || (!token.trim() && !link?.token_set)}>{busy ? "Connecting…" : "Connect"}</button>
    </>}>
      <div className="form">
        <p className="muted connect-note">In Music Assistant, open Settings › Profile and create a long-lived token, then paste it here.
          Moonlight keeps it on your Home Assistant and never shows it again.</p>
        <label className="field-label">Token</label>
        <input className="input" type="password" autoComplete="off" value={token} onChange={(e) => setToken(e.target.value)}
          placeholder={link?.token_set ? "Unchanged" : ""} aria-label="Token" />
        <label className="field-label">Address (leave empty to use the one Music Assistant gives Home Assistant)</label>
        <input className="input" value={url} onChange={(e) => setUrl(e.target.value)} inputMode="url" aria-label="Address"
          placeholder={link?.detected_url ?? "http://homeassistant.local:8095"} />
        {error && <div className="connect-error" role="alert">{error}</div>}
      </div>
    </Sheet>
  );
}
