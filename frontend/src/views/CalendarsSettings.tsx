import { useState } from "react";
import { Account, AccountKind, ApiError, SyncCalendar } from "../api/types";
import { useApp, useData } from "../state";
import { Avatar, PersonPicker, Sheet } from "../components/ui";

type IconProps = { size?: number };
const svg = (size = 24) => ({ width: size, height: size, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 2, strokeLinecap: "round" as const, strokeLinejoin: "round" as const });
export const IconCloud = ({ size }: IconProps) => (
  <svg {...svg(size)}><path d="M7 18.5h10.5a4 4 0 00.6-7.96A6 6 0 006.4 9.6 4.5 4.5 0 007 18.5z" /></svg>
);
export const IconAlert = ({ size }: IconProps) => (
  <svg {...svg(size)}><path d="M12 3.5l9.5 16.5h-19z" /><path d="M12 10v4.5M12 17.4v.1" /></svg>
);
const IconSync = ({ size }: IconProps) => (
  <svg {...svg(size)}><path d="M20 11a8 8 0 00-14.3-4.2L4 9M4 4v5h5M4 13a8 8 0 0014.3 4.2L20 15m0 5v-5h-5" /></svg>
);

const PALETTE = ["#FF9500", "#FF2968", "#CC73E1", "#1BADF8", "#63DA38", "#FFCC00", "#A2845E", "#8A94A6"];
export const APPLE_PASSWORDS_URL = "https://account.apple.com/account/manage/section/security";

/** "just now", "5 min ago", "3 h ago", "12 Oct" from a naive local ISO datetime. */
function ago(iso: string | null): string {
  if (!iso) return "never";
  const t = new Date(iso.length <= 16 ? iso + ":00" : iso).getTime();
  const min = Math.round((Date.now() - t) / 60000);
  if (min < 1) return "just now";
  if (min < 60) return `${min} min ago`;
  if (min < 24 * 60) return `${Math.round(min / 60)} h ago`;
  return new Date(t).toLocaleDateString("en-GB", { day: "numeric", month: "short" });
}

function statusText(a: Account): string {
  if (a.status === "auth_failed") return "Sign-in stopped working · reconnect to keep syncing";
  if (a.status === "error") return `Couldn't sync${a.last_error ? `: ${a.last_error}` : ""} · retrying`;
  return `Synced ${ago(a.last_sync)}`;
}

const kindName = (k: AccountKind) => (k === "icloud" ? "iCloud" : "CalDAV");

export function CalendarsPanel() {
  const { api, people, askPin, toast } = useApp();
  const [accounts] = useData((a) => a.accounts(), ["accounts"], []);
  const [calendars] = useData((a) => a.calendars(), ["accounts"], []);
  const [connect, setConnect] = useState<{ account?: Account } | null>(null);
  const [editing, setEditing] = useState<SyncCalendar | null>(null);
  const [syncing, setSyncing] = useState<string | null>(null);

  async function syncNow(a: Account) {
    setSyncing(a.id);
    try {
      const r = await api.syncAccount(a.id);
      toast(r.status === "ok" ? "Calendars up to date" : r.status === "auth_failed" ? "iCloud needs reconnecting" : "Couldn't sync right now");
    } catch (e) { toast(e instanceof ApiError ? e.message : "Couldn't sync"); }
    finally { setSyncing(null); }
  }
  async function remove(a: Account) {
    const pin = await askPin(`Disconnect ${a.label}? Its events leave this screen (nothing is deleted in ${kindName(a.kind)}).`);
    if (!pin) return;
    try { await api.removeAccount(a.id, pin); toast("Disconnected"); }
    catch (e) { toast(e instanceof ApiError ? e.message : "Couldn't disconnect"); }
  }
  async function toggle(cal: SyncCalendar) {
    try { await api.updateCalendar(cal.id, { visible: !cal.visible }); }
    catch (e) { toast(e instanceof ApiError ? e.message : "Couldn't save"); }
  }

  return (
    <section className="panel cal-panel">
      <div className="cal-panel-head">
        <h2 className="panel-title">Calendars</h2>
        <button className="btn small" onClick={() => setConnect({})}><IconCloud size={20} /> Connect iCloud</button>
      </div>
      {accounts && accounts.length === 0 && (
        <p className="muted cal-intro">
          Connect each adult's iCloud calendar. iCloud stays the master copy: changes made on phones appear here
          within a couple of minutes, and events added here go straight to iCloud.
          {api.mode === "demo" && " (Demo: any Apple ID works; the password “wrong” shows a failed sign-in.)"}
        </p>
      )}
      {accounts?.map((a) => (
        <div key={a.id} className="acct">
          <div className="acct-head">
            <span className={`status-dot s-${a.status}`} aria-label={a.status} />
            <div className="acct-name">
              <b>{a.label}</b>
              <span className={a.status !== "ok" ? `s-${a.status}` : undefined}>{kindName(a.kind)} · {statusText(a)}</span>
            </div>
            <div className="acct-actions">
              {a.status === "auth_failed" && <button className="btn small" onClick={() => setConnect({ account: a })}>Reconnect</button>}
              <button className="btn ghost small" disabled={syncing === a.id} onClick={() => syncNow(a)}>
                <IconSync size={18} /> {syncing === a.id ? "Syncing…" : "Sync now"}
              </button>
              <button className="btn ghost small danger" onClick={() => remove(a)}>Remove</button>
            </div>
          </div>
          <div className="cal-list">
            {calendars?.filter((c) => c.account_id === a.id).map((c) => {
              const who = c.person_ids.map((id) => people.find((p) => p.id === id)).filter(Boolean);
              return (
                <div key={c.id} className={"cal-row" + (c.visible ? "" : " off")}>
                  <button className="cal-swatch" style={{ background: c.color }} onClick={() => setEditing(c)} aria-label={`Edit ${c.name}`} />
                  <button className="cal-name" onClick={() => setEditing(c)}>
                    <b>{c.name}</b>
                    {c.read_only && <span className="tag">Read-only</span>}
                  </button>
                  <button className="cal-who" onClick={() => setEditing(c)}>
                    {who.length ? who.map((p) => <Avatar key={p!.id} person={p!} size={1.7} />) : <span className="muted">Choose people</span>}
                  </button>
                  <button className={"toggle" + (c.visible ? " on" : "")} onClick={() => toggle(c)} aria-pressed={c.visible} aria-label={`Show ${c.name}`}><span /></button>
                </div>
              );
            })}
            {calendars && !calendars.some((c) => c.account_id === a.id) && <div className="muted cal-none">No event calendars found in this account.</div>}
          </div>
        </div>
      ))}
      {connect && <ConnectSheet account={connect.account} onClose={() => setConnect(null)} />}
      {editing && <CalendarSheet cal={editing} onClose={() => setEditing(null)} />}
    </section>
  );
}

function ConnectSheet({ account, onClose }: { account?: Account; onClose: () => void }) {
  const { api, askPin, toast } = useApp();
  const [kind, setKind] = useState<AccountKind>(account?.kind ?? "icloud");
  const [username, setUsername] = useState(account?.username ?? "");
  const [password, setPassword] = useState("");
  const [server, setServer] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const icloud = kind === "icloud";
  const valid = username.trim() && password.trim() && (icloud || !!account || /^https?:\/\//.test(server.trim()));

  async function submit() {
    if (!valid || busy) return;
    const pin = await askPin(account ? `Reconnect ${account.label}` : `Connect ${icloud ? "iCloud" : "a calendar server"}`);
    if (!pin) return;
    setBusy(true); setError(null);
    try {
      if (account) {
        await api.reconnectAccount(account.id, { username: username.trim(), password: password.trim(), pin });
        toast("Reconnected");
      } else {
        const a = await api.connectAccount({ kind, username: username.trim(), password: password.trim(), server_url: icloud ? undefined : server.trim(), pin });
        toast(a.status === "ok" ? `Connected · found ${a.calendar_count} calendar${a.calendar_count === 1 ? "" : "s"}` : "Connected, but sign-in failed");
      }
      onClose();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't connect. Check the network and try again.");
    } finally { setBusy(false); }
  }

  return (
    <Sheet title={account ? `Reconnect ${kindName(account.kind)}` : icloud ? "Connect iCloud" : "Connect a CalDAV server"} onClose={onClose} footer={<>
      <button className="btn ghost" onClick={onClose}>Cancel</button>
      <span style={{ flex: 1 }} />
      <button className="btn" disabled={!valid || busy} onClick={submit}>{busy ? (icloud ? "Checking with iCloud…" : "Checking…") : account ? "Reconnect" : "Connect"}</button>
    </>}>
      <form className="form" onSubmit={(e) => { e.preventDefault(); submit(); }}>
        {icloud && (
          <p className="connect-help">
            Use an <b>app-specific password</b>, not the normal Apple ID password. Make one at{" "}
            <a href={APPLE_PASSWORDS_URL} target="_blank" rel="noreferrer">account.apple.com</a> › Sign-In and Security › App-Specific Passwords.
          </p>
        )}
        {!icloud && !account && (<>
          <label className="field-label">Server URL</label>
          <input className="input" placeholder="https://dav.example.com/" value={server} onChange={(e) => setServer(e.target.value)} autoCapitalize="off" spellCheck={false} />
        </>)}
        <label className="field-label">{icloud ? "Apple ID" : "Username"}</label>
        <input className="input" type={icloud ? "email" : "text"} placeholder={icloud ? "name@icloud.com" : "username"} value={username}
          onChange={(e) => setUsername(e.target.value)} autoComplete="username" autoCapitalize="off" spellCheck={false} autoFocus={!account} />
        <label className="field-label">{icloud ? "App-specific password" : "Password"}</label>
        <input className="input" type="password" placeholder={icloud ? "xxxx-xxxx-xxxx-xxxx" : ""} value={password}
          onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" autoFocus={!!account} />
        {error && <div className="connect-error" role="alert">{error}</div>}
        <p className="muted connect-note">Stored only on this Moonlight add-on and used only to talk to {icloud ? "iCloud" : "that server"}. A PIN is needed to connect.</p>
        {!account && (
          <button type="button" className="link-btn" onClick={() => { setKind(icloud ? "caldav" : "icloud"); setError(null); }}>
            {icloud ? "Use another CalDAV server instead" : "Use iCloud instead"}
          </button>
        )}
        <button type="submit" hidden />
      </form>
    </Sheet>
  );
}

function CalendarSheet({ cal, onClose }: { cal: SyncCalendar; onClose: () => void }) {
  const { api, people, toast } = useApp();
  const [who, setWho] = useState(cal.person_ids);
  const [color, setColor] = useState(cal.color);
  const [visible, setVisible] = useState(cal.visible);
  const colors = PALETTE.includes(cal.color) ? PALETTE : [cal.color, ...PALETTE.slice(0, -1)];
  async function save() {
    try { await api.updateCalendar(cal.id, { person_ids: who, color, visible }); onClose(); }
    catch (e) { toast(e instanceof ApiError ? e.message : "Couldn't save"); }
  }
  return (
    <Sheet title={cal.name} onClose={onClose} footer={<>
      <button className="btn ghost" onClick={onClose}>Cancel</button>
      <span style={{ flex: 1 }} />
      <button className="btn" onClick={save}>Save</button>
    </>}>
      <div className="form">
        <label className="field-label">Whose calendar is this?</label>
        <PersonPicker people={people} value={who} onChange={setWho} />
        <p className="muted connect-note">Its events show in these people's colours and columns. Leave empty to show them in the calendar colour.</p>
        <label className="field-label">Colour</label>
        <div className="swatches">
          {colors.map((c) => (
            <button key={c} className={"swatch" + (c === color ? " on" : "")} style={{ background: c }} onClick={() => setColor(c)} aria-label={c} aria-pressed={c === color} />
          ))}
        </div>
        <div className="set-row"><span>Show on Moonlight</span>
          <button className={"toggle" + (visible ? " on" : "")} onClick={() => setVisible(!visible)} aria-pressed={visible}><span /></button>
        </div>
        {cal.read_only && <p className="muted connect-note">This calendar is read-only, so its events can't be edited here.</p>}
      </div>
    </Sheet>
  );
}
