import { useState } from "react";
import { ApiError, NurseryConfig } from "../api/types";
import { useApp, useData } from "../state";
import { Sheet } from "../components/ui";

function ago(iso: string | null): string {
  if (!iso) return "not yet";
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const h = Math.round(mins / 60);
  return h < 24 ? `${h} hour${h === 1 ? "" : "s"} ago` : `${Math.round(h / 24)} days ago`;
}

/** Settings › Nursery: the Tapestry login Moonlight reads the nursery's updates with. */
export function NurseryPanel() {
  const { api, askPin, toast } = useApp();
  const [cfg, reload] = useData((a) => a.nursery(), ["nursery"], []);
  const [editing, setEditing] = useState(false);
  const [checking, setChecking] = useState(false);
  async function check() {
    setChecking(true);
    try { const c = await api.syncNursery(); toast(`Checked: ${c.count} update${c.count === 1 ? "" : "s"}`); reload(); }
    catch (e) { toast(e instanceof ApiError ? e.message : "Couldn't check Tapestry"); }
    finally { setChecking(false); }
  }
  async function disconnect() {
    const pin = await askPin("Disconnect Tapestry");
    if (!pin) return;
    try { await api.disconnectNursery(pin); toast("Tapestry disconnected"); reload(); }
    catch (e) { toast(e instanceof ApiError ? e.message : "Couldn't disconnect"); }
  }
  return (
    <section className="panel">
      <h2 className="panel-title">Nursery</h2>
      <p className="muted connect-note">Updates from nursery on Tapestry: a Nursery section on large screens, and a button at the top of the
        smaller ones. Moonlight signs in to Tapestry with your login and checks every 30 minutes.</p>
      <div className="set-row stack"><span>Tapestry</span>
        <span className="set-pin"><b className="clip" title={cfg?.configured ? cfg.email : undefined}>{cfg?.configured ? cfg.email : "Not connected"}</b>
          <button className="btn ghost small" onClick={() => setEditing(true)}>{cfg?.configured ? "Change" : "Connect"}</button>
          {cfg?.configured && <button className="btn ghost small danger" onClick={disconnect}>Disconnect</button>}</span>
      </div>
      {cfg?.configured && <>
        <div className="set-row"><span>{cfg.school_name ?? "Nursery"}</span>
          <span className="set-pin"><b>{cfg.count} update{cfg.count === 1 ? "" : "s"} · checked {ago(cfg.last_sync)}</b>
            <button className="btn ghost small" disabled={checking} onClick={check}>{checking ? "Checking…" : "Check now"}</button></span>
        </div>
        {(cfg.status === "auth_failed" || cfg.status === "error") && cfg.last_error && <div className="connect-error" role="alert">{cfg.last_error}</div>}
      </>}
      {editing && <LoginSheet cfg={cfg} onClose={() => { setEditing(false); reload(); }} />}
    </section>
  );
}

function LoginSheet({ cfg, onClose }: { cfg: NurseryConfig | undefined; onClose: () => void }) {
  const { api, askPin, toast } = useApp();
  const [email, setEmail] = useState(cfg?.email ?? "");
  const [password, setPassword] = useState("");
  const [school, setSchool] = useState(cfg?.school ?? "");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const sameAccount = !!cfg?.configured && email.trim().toLowerCase() === cfg.email.toLowerCase();
  async function save() {
    const pin = await askPin("Connect Tapestry");
    if (!pin) return;
    setBusy(true);
    setError(null);
    try {
      const c = await api.saveNursery({ email: email.trim(), ...(password ? { password } : {}), school: school.trim(), pin });
      toast(c.count ? `Connected: ${c.count} update${c.count === 1 ? "" : "s"} from nursery` : "Connected to Tapestry");
      onClose();
    } catch (e) { setError(e instanceof ApiError ? e.message : "Couldn't connect"); }
    finally { setBusy(false); }
  }
  return (
    <Sheet title="Tapestry login" onClose={onClose} footer={<>
      <span style={{ flex: 1 }} />
      <button className="btn ghost" onClick={onClose}>Cancel</button>
      <button className="btn" onClick={save} disabled={busy || !email.includes("@") || (!password && !sameAccount)}>{busy ? "Signing in…" : "Connect"}</button>
    </>}>
      <div className="form">
        <p className="muted connect-note">The email and password you use at tapestryjournal.com. Moonlight keeps them on your Home Assistant
          and never shows the password again. Logins that use Google, Microsoft or a verification code can't be used.</p>
        <label className="field-label">Email</label>
        <input className="input" type="email" autoComplete="off" value={email} onChange={(e) => setEmail(e.target.value)} aria-label="Email" />
        <label className="field-label">Password</label>
        <input className="input" type="password" autoComplete="off" value={password} onChange={(e) => setPassword(e.target.value)}
          placeholder={sameAccount ? "Unchanged" : ""} aria-label="Password" />
        <label className="field-label">Nursery (only if your login has more than one)</label>
        <input className="input" value={school} onChange={(e) => setSchool(e.target.value)} placeholder="The first one" aria-label="Nursery name" />
        {error && <div className="connect-error" role="alert">{error}</div>}
      </div>
    </Sheet>
  );
}
