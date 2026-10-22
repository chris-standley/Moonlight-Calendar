import { useEffect, useState } from "react";
import { Account, AccountKind, ApiError, FeedPreview, HaCalendar, SyncCalendar } from "../api/types";
import { useApp, useData } from "../state";
import { Avatar, PersonPicker, Sheet } from "../components/ui";
import { IconDown } from "../components/icons";

type IconProps = { size?: number };
const svg = (size = 24) => ({ width: size, height: size, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 2, strokeLinecap: "round" as const, strokeLinejoin: "round" as const });
export const IconCloud = ({ size }: IconProps) => (
  <svg {...svg(size)}><path d="M7 18.5h10.5a4 4 0 00.6-7.96A6 6 0 006.4 9.6 4.5 4.5 0 007 18.5z" /></svg>
);
export const IconAlert = ({ size }: IconProps) => (
  <svg {...svg(size)}><path d="M12 3.5l9.5 16.5h-19z" /><path d="M12 10v4.5M12 17.4v.1" /></svg>
);
const IconLink = ({ size }: IconProps) => (
  <svg {...svg(size)}><path d="M10 14a4.5 4.5 0 006.4 0l3-3a4.5 4.5 0 00-6.4-6.4l-1 1" /><path d="M14 10a4.5 4.5 0 00-6.4 0l-3 3a4.5 4.5 0 006.4 6.4l1-1" /></svg>
);
const IconHome = ({ size }: IconProps) => (
  <svg {...svg(size)}><path d="M3 11.5 12 4l9 7.5" /><path d="M5.5 9.5V20h13V9.5" /><path d="M10 20v-5.5h4V20" /></svg>
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
  if (a.status === "error") return `Couldn't ${single(a.kind) ? "refresh" : "sync"}${a.last_error ? `: ${a.last_error}` : ""} · retrying`;
  return `${single(a.kind) ? "Checked" : "Synced"} ${ago(a.last_sync)}`;
}

const kindName = (k: AccountKind) => (k === "icloud" ? "iCloud" : k === "ics" ? "Calendar link" : k === "ha" ? "Home Assistant" : "CalDAV");
/** One read-only calendar, refreshed every 15 minutes (a published link or a Home Assistant calendar). */
const single = (k: AccountKind) => k === "ics" || k === "ha";

/** The Calendars card folded away: how many calendars show, and any account that needs attention. */
function FoldedSummary({ accounts, shown, onOpen }: { accounts: Account[]; shown: number; onOpen: () => void }) {
  const trouble = accounts.filter((a) => a.status !== "ok");
  return (
    <button className="cal-folded muted" onClick={onOpen}>
      {accounts.length
        ? `${shown} calendar${shown === 1 ? "" : "s"} shown from ${accounts.length} source${accounts.length === 1 ? "" : "s"}`
        : "No calendars connected yet"}
      {trouble.map((a) => <span key={a.id} className={`s-${a.status}`}><span className={`status-dot s-${a.status}`} /> {a.label}: {statusText(a)}</span>)}
    </button>
  );
}

export function CalendarsPanel() {
  const { api, people, askPin, toast } = useApp();
  const [accounts] = useData((a) => a.accounts(), ["accounts"], []);
  const [calendars] = useData((a) => a.calendars(), ["accounts"], []);
  const [connect, setConnect] = useState<{ account?: Account } | null>(null);
  const [feed, setFeed] = useState<{ account?: Account } | null>(null);
  const [haOpen, setHaOpen] = useState(false);
  const [editing, setEditing] = useState<SyncCalendar | null>(null);
  const [syncing, setSyncing] = useState<string | null>(null);
  const [open, setOpen] = useState(false); // folded away by default: set up once, rarely changed

  async function syncNow(a: Account) {
    setSyncing(a.id);
    try {
      const r = await api.syncAccount(a.id);
      toast(r.status === "ok" ? "Calendars up to date" : r.status === "auth_failed" ? "iCloud needs reconnecting" : r.kind === "ics" ? "Couldn't refresh that link right now" : r.kind === "ha" ? "Couldn't reach Home Assistant right now" : "Couldn't sync right now");
    } catch (e) { toast(e instanceof ApiError ? e.message : "Couldn't sync"); }
    finally { setSyncing(null); }
  }
  async function remove(a: Account) {
    const pin = await askPin(single(a.kind) ? `Remove ${a.kind === "ics" ? "the calendar link " : ""}${a.label}? Its events leave this screen.`
      : `Disconnect ${a.label}? Its events leave this screen (nothing is deleted in ${kindName(a.kind)}).`);
    if (!pin) return;
    try { await api.removeAccount(a.id, pin); toast("Disconnected"); }
    catch (e) { toast(e instanceof ApiError ? e.message : "Couldn't disconnect"); }
  }
  async function toggle(cal: SyncCalendar) {
    try { await api.updateCalendar(cal.id, { visible: !cal.visible }); }
    catch (e) { toast(e instanceof ApiError ? e.message : "Couldn't save"); }
  }

  return (
    <section className={"panel cal-panel" + (open ? "" : " folded")}>
      <div className="cal-panel-head">
        <button className="cal-fold" aria-expanded={open} onClick={() => setOpen(!open)}>
          <h2 className="panel-title">Calendars</h2>
          <IconDown size={22} />
        </button>
        {open && <div className="cal-head-btns">
          <button className="btn ghost small" onClick={() => setHaOpen(true)}><IconHome size={20} /> Home Assistant</button>
          <button className="btn ghost small" onClick={() => setFeed({})}><IconLink size={20} /> Add calendar link</button>
          <button className="btn small" onClick={() => setConnect({})}><IconCloud size={20} /> Connect iCloud</button>
        </div>}
      </div>
      {!open && accounts && <FoldedSummary accounts={accounts} shown={calendars?.filter((c) => c.visible).length ?? 0} onOpen={() => setOpen(true)} />}
      {open && accounts && !accounts.some((a) => !single(a.kind)) && (
        <p className="muted cal-intro">
          Connect each adult's iCloud calendar. iCloud stays the master copy: changes made on phones appear here
          within a couple of minutes, and events added here go straight to iCloud. To show a calendar you can only
          read (a work calendar, school term dates), add its published link instead. Home Assistant calendars
          (bin days, Workday, energy sessions) can be shown too.
          {api.mode === "demo" && " (Demo: any Apple ID works; the password “wrong” shows a failed sign-in.)"}
        </p>
      )}
      {open && accounts?.map((a) => (
        <div key={a.id} className="acct">
          <div className="acct-head">
            <span className={`status-dot s-${a.status}`} aria-label={a.status} />
            <div className="acct-name">
              <b>{a.label}</b>
              <span className={a.status !== "ok" ? `s-${a.status}` : undefined}>{kindName(a.kind)}{single(a.kind) && <> · <span className="acct-src">{a.server_url}</span></>} · {statusText(a)}</span>
            </div>
            <div className="acct-actions">
              {a.status === "auth_failed" && <button className="btn small" onClick={() => setConnect({ account: a })}>Reconnect</button>}
              {a.kind === "ics" && a.status === "error" && <button className="btn small" onClick={() => setFeed({ account: a })}>Paste new link</button>}
              <button className="btn ghost small" disabled={syncing === a.id} onClick={() => syncNow(a)}>
                <IconSync size={18} /> {syncing === a.id ? (single(a.kind) ? "Refreshing…" : "Syncing…") : single(a.kind) ? "Refresh" : "Sync now"}
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
                    {c.busy_blocks ? <span className="tag">Busy times</span> : c.read_only && <span className="tag">Read-only</span>}
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
      {feed && <FeedSheet account={feed.account} onClose={() => setFeed(null)} />}
      {haOpen && <HaCalendarSheet onClose={() => setHaOpen(false)} />}
      {editing && <CalendarSheet cal={editing} feed={accounts?.find((a) => a.id === editing.account_id)?.kind === "ics"} onClose={() => setEditing(null)} />}
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

function CalendarSheet({ cal, feed, onClose }: { cal: SyncCalendar; feed?: boolean; onClose: () => void }) {
  const { api, people, toast } = useApp();
  const [who, setWho] = useState(cal.person_ids);
  const [color, setColor] = useState(cal.color);
  const [visible, setVisible] = useState(cal.visible);
  const [name, setName] = useState(cal.name);
  const source = cal.source_name ?? cal.name;
  // null = automatic (on when every event is just "Busy" / "Free" ...).
  const [busy, setBusy] = useState<boolean | null>(cal.busy_blocks_set ? !!cal.busy_blocks : null);
  const busyOn = busy ?? !!cal.busy_blocks_auto;
  const colors = PALETTE.includes(cal.color) ? PALETTE : [cal.color, ...PALETTE.slice(0, -1)];
  async function save() {
    try { await api.updateCalendar(cal.id, { name: name.trim() === source ? null : name, person_ids: who, color, visible, ...(feed ? { busy_blocks: busy } : {}) }); onClose(); }
    catch (e) { toast(e instanceof ApiError ? e.message : "Couldn't save"); }
  }
  return (
    <Sheet title={cal.name} onClose={onClose} footer={<>
      <button className="btn ghost" onClick={onClose}>Cancel</button>
      <span style={{ flex: 1 }} />
      <button className="btn" onClick={save}>Save</button>
    </>}>
      <div className="form">
        <label className="field-label">Name</label>
        <input className="input" value={name} maxLength={80} onChange={(e) => setName(e.target.value)} placeholder={source} />
        {name.trim() !== source && <p className="muted connect-note">Called “{source}” in {cal.read_only ? "its source" : "the calendar app"}. <button type="button" className="link-btn" style={{ display: "inline", margin: 0 }} onClick={() => setName(source)}>Use that</button></p>}
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
        {feed && (<>
          <div className="set-row"><span>Show as busy blocks</span>
            <button className={"toggle" + (busyOn ? " on" : "")} onClick={() => setBusy(!busyOn)} aria-pressed={busyOn}><span /></button>
          </div>
          <p className="muted connect-note">
            {busyOn ? `Events show as “${people.find((p) => p.id === who[0])?.name ?? "Someone"} – busy” blocks; free time is hidden.` : "Events show with their own titles."}
            {busy === null ? (cal.busy_blocks_auto ? " Turned on automatically: this link only shares busy times." : " Automatic: turns on when a link only shares busy times.")
              : <> <button type="button" className="link-btn" style={{ display: "inline", margin: 0 }} onClick={() => setBusy(null)}>Use automatic</button></>}
          </p>
        </>)}
        {cal.read_only && <p className="muted connect-note">This calendar is read-only, so its events can't be edited here.</p>}
      </div>
    </Sheet>
  );
}

const OUTLOOK_HELP = "Outlook on the web: Settings › Calendar › Shared calendars › Publish a calendar";

/** Add (or replace the link of) a read-only calendar from a published ICS link. */
function FeedSheet({ account, onClose }: { account?: Account; onClose: () => void }) {
  const { api, people, askPin, toast } = useApp();
  const [url, setUrl] = useState("");
  const [label, setLabel] = useState(account?.label ?? "");
  const [who, setWho] = useState<string[]>(people.filter((p) => p.role === "adult").slice(0, 1).map((p) => p.id));
  const [found, setFound] = useState<{ url: string; preview: FeedPreview } | null>(null);
  const [busy, setBusy] = useState<"" | "check" | "save">("");
  const [error, setError] = useState<string | null>(null);
  const trimmed = url.trim();
  const looksOk = /^(https?|webcals?):\/\/\S+/i.test(trimmed);
  const checked = found?.url === trimmed ? found.preview : null;

  async function check() {
    if (!looksOk || busy) return;
    setBusy("check"); setError(null);
    try {
      const preview = await api.previewFeed(trimmed);
      setFound({ url: trimmed, preview });
      if (!label.trim() && preview.name && preview.name.toLowerCase() !== "calendar") setLabel(preview.name);
    } catch (e) {
      setFound(null);
      setError(e instanceof ApiError ? e.message : "Couldn't fetch that link. Check the network and try again.");
    } finally { setBusy(""); }
  }
  async function submit() {
    if (!looksOk || busy) return;
    const name = label.trim() || (checked?.busy_only ? "Work" : checked?.name) || "";
    const pin = await askPin(account ? `Replace the link for ${account.label}` : `Add ${name || "this calendar"}`);
    if (!pin) return;
    setBusy("save"); setError(null);
    try {
      if (account) {
        await api.updateFeed(account.id, { url: trimmed, label: label.trim() || undefined, pin });
        toast("Link updated");
      } else {
        await api.addFeed({ url: trimmed, label: name || undefined, person_ids: who, pin });
        toast(`Added ${name || "calendar"}`);
      }
      onClose();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't add that link. Check the network and try again.");
    } finally { setBusy(""); }
  }

  return (
    <Sheet title={account ? `New link for ${account.label}` : "Add calendar link"} onClose={onClose} footer={<>
      <button className="btn ghost" onClick={onClose}>Cancel</button>
      <span style={{ flex: 1 }} />
      <button className="btn" disabled={!looksOk || !!busy} onClick={submit}>{busy === "save" ? "Adding…" : account ? "Use this link" : "Add calendar"}</button>
    </>}>
      <form className="form" onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <div className="connect-help">
          Shows a calendar you can read but not change, refreshed every 15 minutes: a work calendar, school term dates, bin days.
          <ol>
            <li><b>Work (Outlook / Microsoft 365):</b> {OUTLOOK_HELP}. Pick the calendar, choose <b>Can view when I'm busy</b> (or <b>Can view titles and locations</b>), Publish, then copy the <b>ICS</b> link.</li>
            <li><b>Anything else:</b> copy its “subscribe” or iCal link (webcal:// or https://…ics).</li>
          </ol>
          Some workplaces turn publishing off; if there's no Publish option, ask IT or use a personal calendar instead.
        </div>
        <label className="field-label">Calendar link</label>
        <div className="feed-row">
          <input className="input" placeholder="webcal://… or https://…/calendar.ics" value={url}
            onChange={(e) => { setUrl(e.target.value); setError(null); }} onBlur={() => { if (!checked) check(); }}
            autoCapitalize="off" autoCorrect="off" spellCheck={false} autoFocus />
          <button type="button" className="btn ghost small" disabled={!looksOk || !!busy} onClick={check}>{busy === "check" ? "Checking…" : "Check link"}</button>
        </div>
        {checked && (
          <div className="feed-found" role="status">
            Found {checked.event_count} event{checked.event_count === 1 ? "" : "s"}{checked.busy_only ? " · busy times only, shown as busy blocks" : ""}
          </div>
        )}
        {error && <div className="connect-error" role="alert">{error}</div>}
        <label className="field-label">Name</label>
        <input className="input" placeholder={checked?.busy_only ? "Work" : checked?.name || "e.g. Work, School, Bins"} value={label} onChange={(e) => setLabel(e.target.value)} />
        {!account && (<>
          <label className="field-label">Whose calendar is it?</label>
          <PersonPicker people={people} value={who} onChange={setWho} />
        </>)}
        <p className="muted connect-note">
          The link works like a password: anyone who has it can read the calendar. It's kept only on this Moonlight add-on and never shown in full. A PIN is needed to add it.
        </p>
        <button type="submit" hidden />
      </form>
    </Sheet>
  );
}

/** Show a Home Assistant calendar entity (bin collections, Workday, energy sessions): read-only, refreshed every 15 minutes. */
function HaCalendarSheet({ onClose }: { onClose: () => void }) {
  const { api, people, askPin, toast } = useApp();
  const [found, setFound] = useState<HaCalendar[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pick, setPick] = useState<HaCalendar | null>(null);
  const [label, setLabel] = useState("");
  const [who, setWho] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    api.haCalendars().then((f) => { setFound(f); setError(null); })
      .catch((e) => setError(e instanceof ApiError ? e.message : "Couldn't reach Home Assistant"));
  }, [api]);
  async function submit() {
    if (!pick || saving) return;
    const name = label.trim() || pick.name;
    const pin = await askPin(`Add ${name}`);
    if (!pin) return;
    setSaving(true); setError(null);
    try {
      await api.addHaCalendar({ entity_id: pick.entity_id, label: label.trim() || undefined, person_ids: who, pin });
      toast(`Added ${name}`);
      onClose();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't add that calendar");
    } finally { setSaving(false); }
  }
  return (
    <Sheet title="Home Assistant calendar" onClose={onClose} footer={<>
      <button className="btn ghost" onClick={onClose}>Cancel</button>
      <span style={{ flex: 1 }} />
      <button className="btn" disabled={!pick || saving} onClick={submit}>{saving ? "Adding…" : "Add calendar"}</button>
    </>}>
      <p className="muted connect-note">
        Shows a calendar from Home Assistant, such as bin collections, Workday or energy saving sessions. Its events
        can't be changed here, and it's checked every 15 minutes.
      </p>
      {!found && !error && <div className="screens-empty">Asking Home Assistant…</div>}
      <div className="player-list">
        {(found ?? []).map((c) => (
          <button key={c.entity_id} className={"player-row" + (pick?.entity_id === c.entity_id ? " on" : "")}
            disabled={c.added} onClick={() => setPick(c)} aria-pressed={pick?.entity_id === c.entity_id}>
            <span className="player-main"><b>{c.name}</b><span>{c.added ? "Already on Moonlight" : c.entity_id}</span></span>
          </button>
        ))}
        {found && found.length === 0 && <div className="screens-empty">Home Assistant has no calendars yet.</div>}
      </div>
      {error && <div className="connect-error" role="alert">{error}</div>}
      {pick && (
        <div className="form">
          <label className="field-label">Name</label>
          <input className="input" placeholder={pick.name} value={label} onChange={(e) => setLabel(e.target.value)} />
          <label className="field-label">Whose calendar is it?</label>
          <PersonPicker people={people} value={who} onChange={setWho} />
          <p className="muted connect-note">Pick everyone for household things like bin day. Leave it empty to show the events in the calendar's own colour.</p>
        </div>
      )}
    </Sheet>
  );
}
