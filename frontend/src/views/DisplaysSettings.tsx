import { useEffect, useState } from "react";
import {
  ApiError, DEFAULT_IDLE, DEFAULT_SCREENS, Display, DisplaySetup, ImmichAlbum, ImmichConfig, ImmichMode, ImmichSeason, Layout, MediaPlayerOption, SECTIONS, STYLE_LABEL,
  Section, Settings,
} from "../api/types";
import { useApp, useData, useNow } from "../state";
import { Segmented, Sheet } from "../components/ui";
import { IconPhotos } from "../components/icons";


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

const STYLES: { layout: Layout; note: string }[] = [
  { layout: "large", note: "Big wall screen" },
  { layout: "compact", note: "Small touch screen" },
  { layout: "phone", note: "Held in the hand" },
];
const SECTION_LABEL: Record<Section, string> = {
  today: "Today", calendar: "Calendar", chores: "Chores", rewards: "Rewards", meals: "Meals", recipes: "Recipes", lists: "Lists",
};
const SPEAKER_WHERE: Record<Layout, string> = {
  compact: "Card on Today, album art on the screensaver",
  large: "Small player in the top bar",
  phone: "Small player in the top bar",
};
const IDLE_OPTS = [0, 1, 3, 5, 10, 30].map((v) => ({ value: String(v), label: v === 0 ? "Never" : `${v} min` }));
const STYLE_OPTS = STYLES.map((x) => ({ value: x.layout, label: STYLE_LABEL[x.layout] }));

/** What a screen of this style shows without choices of its own (Settings `screens`, `media_players`, `idle_minutes`). */
function styleSetup(settings: Settings | null, layout: Layout): DisplaySetup {
  const s = settings?.screens?.[layout] ?? DEFAULT_SCREENS[layout];
  return { ...s, speaker: settings?.media_players?.[layout] ?? "", idle_minutes: settings?.idle_minutes?.[layout] ?? DEFAULT_IDLE[layout] };
}

/** Settings > Screens: every paired screen (its name, style and what it shows), what each style shows in the
 *  Home Assistant app, and connections such as the Home Assistant integration. */
export function ScreensPanel() {
  const { api, settings, askPin, toast } = useApp();
  const [screens] = useData((a) => a.displays(), ["displays", "settings"], []);
  const [players, setPlayers] = useState<MediaPlayerOption[] | null>(null);
  const [playersError, setPlayersError] = useState<string | null>(null);
  const [pairing, setPairing] = useState(false);
  const [editing, setEditing] = useState<{ display?: Display; layout: Layout } | null>(null);
  const now = useNow(30_000);
  useEffect(() => {
    api.mediaPlayers().then((p) => { setPlayers(p); setPlayersError(null); })
      .catch((e) => setPlayersError(e instanceof ApiError ? e.message : "Couldn't reach Home Assistant"));
  }, [api]);

  async function revoke(d: Display) {
    const pin = await askPin(`Disconnect ${d.name}? It stops getting Moonlight's data.`);
    if (!pin) return;
    try { await api.revokeDisplay(d.id, pin); toast(`${d.name} removed`); }
    catch (e) { toast(e instanceof ApiError ? e.message : "Couldn't remove"); }
  }
  const speakerName = (id: string) => players?.find((p) => p.entity_id === id)?.name ?? id;
  const summary = (s: DisplaySetup) =>
    `Opens on ${SECTION_LABEL[s.start]} · ${s.sections.length} section${s.sections.length === 1 ? "" : "s"} · `
    + `${s.speaker ? speakerName(s.speaker) : "No speaker"} · ${s.idle_minutes ? `Screensaver after ${s.idle_minutes} min` : "No screensaver"}`;
  const devices = (screens ?? []).filter((d) => d.layout !== "service" && d.layout !== "app");
  const apps = (screens ?? []).filter((d) => d.layout === "app");
  const services = (screens ?? []).filter((d) => d.layout === "service");

  return (
    <section className="panel screens-panel">
      <div className="panel-head">
        <h2 className="panel-title">Screens</h2>
        <button className="btn small" onClick={() => setPairing(true)}>Pair</button>
      </div>
      <p className="muted screens-help">
        Every screen opens <code>http://&lt;home-assistant&gt;:8091/display</code> and shows a 6-digit code to enter here.
        Name it, pick its style, then choose what it shows.
        Away from home, use Moonlight's https address; with Home Assistant's address set up, the pairing screen also
        offers Sign in with Home Assistant.
      </p>
      <div className="screen-list">
        {devices.map((d) => {
          const l = d.layout as Layout;
          return (
            <button key={d.id} className="screen-row screen-device" onClick={() => setEditing({ display: d, layout: l })}>
              <span className={`screen-ico ${l}`} aria-hidden />
              <span className="screen-main">
                <b>{d.name}{d.current && <em className="screen-this">This screen</em>}</b>
                <span>{STYLE_LABEL[l]} · {d.setup ? summary(d.setup) : ""}</span>
                <span>Seen {ago(d.last_seen, now).toLowerCase()}{d.own_setup ? "" : ` · Uses the ${STYLE_LABEL[l]} settings`}</span>
              </span>
              <span className="btn ghost small">Set up</span>
            </button>
          );
        })}
        {screens && devices.length === 0 && <div className="screen-note muted">No screens paired yet.</div>}
      </div>
      <h3 className="screens-sub">Phones and tablets</h3>
      <div className="screen-list">
        {apps.map((d) => (
          <div key={d.id} className="screen-row">
            <span className="screen-ico phone" aria-hidden />
            <div className="screen-main">
              <b>{d.name}</b>
              <span>Moonlight app · seen {ago(d.last_seen, now).toLowerCase()}</span>
            </div>
            <button className="btn ghost small danger" onClick={() => revoke(d)}>Disconnect</button>
          </div>
        ))}
        {screens && apps.length === 0 && (
          <div className="screen-note muted">
            The Moonlight app for iPhone and iPad shows a code to enter with Pair, or signs in with Home Assistant.
          </div>
        )}
      </div>
      <h3 className="screens-sub">In the Home Assistant app</h3>
      <p className="muted screens-help">
        What Moonlight shows when it's opened from Home Assistant (the sidebar or the phone app), by screen size. Paired
        screens use these too until they're set up on their own.
      </p>
      <div className="screen-list">
        {STYLES.map(({ layout, note }) => (
          <div key={layout} className="screen-row">
            <span className={`screen-ico ${layout}`} aria-hidden />
            <div className="screen-main">
              <b>{STYLE_LABEL[layout]} <em className="screen-kind-note">{note}</em></b>
              <span>{summary(styleSetup(settings, layout))}</span>
            </div>
            <button className="btn ghost small" onClick={() => setEditing({ layout })}>Set up</button>
          </div>
        ))}
      </div>
      <h3 className="screens-sub">Connections</h3>
      <div className="screen-list">
        {services.map((d) => (
          <div key={d.id} className="screen-row">
            <span className="screen-ico service" aria-hidden />
            <div className="screen-main">
              <b>{d.name}</b>
              <span>Moonlight integration · seen {ago(d.last_seen, now).toLowerCase()}</span>
            </div>
            <button className="btn ghost small danger" onClick={() => revoke(d)}>Disconnect</button>
          </div>
        ))}
        {screens && services.length === 0 && (
          <div className="screen-note muted">
            Install the Moonlight integration in Home Assistant (HACS) and it finds the add-on by itself under
            Settings › Devices &amp; services.
          </div>
        )}
      </div>
      {pairing && <PairSheet onClose={() => setPairing(false)} />}
      {editing && <SetupSheet display={editing.display} layout={editing.layout}
        players={players} playersError={playersError} onClose={() => setEditing(null)} />}
    </section>
  );
}

/** One paired screen (name, style, what it shows; remove), or one style's settings for the Home Assistant app. */
function SetupSheet({ display, layout: initialLayout, players, playersError, onClose }: {
  display?: Display; layout: Layout; players: MediaPlayerOption[] | null; playersError: string | null; onClose: () => void;
}) {
  const { api, settings, askPin, toast } = useApp();
  const initial = display?.setup ?? styleSetup(settings, initialLayout);
  const [name, setName] = useState(display?.name ?? "");
  const [layout, setLayout] = useState<Layout>(initialLayout);
  const [sections, setSections] = useState<Section[]>(initial.sections);
  const [start, setStart] = useState<Section>(initial.start);
  const [speaker, setSpeaker] = useState(initial.speaker);
  const [idle, setIdle] = useState(initial.idle_minutes);
  const [saving, setSaving] = useState(false);
  const [removing, setRemoving] = useState(false);
  const shown = SECTIONS.filter((x) => sections.includes(x));
  const opensOn = shown.includes(start) ? start : shown[0];
  const setup: DisplaySetup = { sections: shown, start: opensOn, speaker, idle_minutes: idle };
  const changed = JSON.stringify(setup) !== JSON.stringify({ sections: initial.sections, start: initial.start, speaker: initial.speaker, idle_minutes: initial.idle_minutes });
  const title = display ? display.name : `${STYLE_LABEL[initialLayout]} screens`;
  function toggle(x: Section) {
    if (sections.includes(x)) { if (sections.length > 1) setSections(sections.filter((y) => y !== x)); }
    else setSections([...sections, x]);
  }
  async function save() {
    if (display && !name.trim()) return;
    const pin = await askPin(`Change ${display ? display.name : `the ${title.toLowerCase()}`}`);
    if (!pin) return;
    setSaving(true);
    try {
      if (display) {
        await api.updateDisplay(display.id, {
          pin, ...(name.trim() !== display.name ? { name: name.trim() } : {}), ...(layout !== display.layout ? { layout } : {}),
          ...(changed ? { setup } : {}),
        });
      } else {
        await api.updateSettings({
          pin, screens: { [layout]: { sections: shown, start: opensOn } },
          media_players: { [layout]: speaker }, idle_minutes: { [layout]: idle },
        });
      }
      toast("Saved");
      onClose();
    } catch (e) { toast(e instanceof ApiError ? e.message : "Couldn't save"); }
    finally { setSaving(false); }
  }
  async function followStyle() {
    if (!display) return;
    const pin = await askPin(`Use the ${STYLE_LABEL[layout].toLowerCase()} settings on ${display.name}`);
    if (!pin) return;
    try { await api.updateDisplay(display.id, { pin, setup: null, ...(layout !== display.layout ? { layout } : {}) }); toast("Saved"); onClose(); }
    catch (e) { toast(e instanceof ApiError ? e.message : "Couldn't save"); }
  }
  async function remove() {
    if (!display) return;
    if (!removing) { setRemoving(true); return; }
    const pin = await askPin(`Remove ${display.name}? It will need pairing again.`);
    if (!pin) return;
    try { await api.revokeDisplay(display.id, pin); toast(`${display.name} removed`); onClose(); }
    catch (e) { toast(e instanceof ApiError ? e.message : "Couldn't remove"); }
  }
  return (
    <Sheet title={title} onClose={onClose} footer={<>
      {display ? <button className="btn ghost danger" onClick={remove}>{removing ? "Tap again to remove" : "Remove"}</button>
        : <button className="btn ghost" onClick={onClose}>Cancel</button>}
      <span style={{ flex: 1 }} />
      <button className="btn" disabled={saving || (!!display && !name.trim())} onClick={save}>{saving ? "Saving…" : "Save"}</button>
    </>}>
      <div className="form">
        {display && (<>
          <label className="field-label">Name</label>
          <input className="input" value={name} maxLength={60} onChange={(e) => setName(e.target.value)} placeholder="e.g. Kitchen" />
          <label className="field-label">Style</label>
          <Segmented value={layout} options={STYLE_OPTS} onChange={(v) => setLayout(v as Layout)} />
          <p className="muted connect-note">
            {layout === "large" ? "For a big wall screen: a week at a glance." : layout === "compact" ? "For a small touch screen, like a 10in kitchen display." : "For a phone held in the hand."}
            {layout !== display.layout && " The screen switches as soon as you save."}
          </p>
          {display.own_setup
            ? <p className="muted connect-note">This screen has its own setup. <button type="button" className="link-btn" style={{ display: "inline", margin: 0 }} onClick={followStyle}>Use the {STYLE_LABEL[layout].toLowerCase()} settings instead</button></p>
            : <p className="muted connect-note">Uses the {STYLE_LABEL[display.layout as Layout].toLowerCase()} settings until you change something below.</p>}
        </>)}
        <label className="field-label">Sections in the menu</label>
        <div className="section-toggles">
          {SECTIONS.map((x) => (
            <div key={x} className="set-row"><span>{SECTION_LABEL[x]}</span>
              <button className={"toggle" + (sections.includes(x) ? " on" : "")} aria-pressed={sections.includes(x)}
                aria-label={`Show ${SECTION_LABEL[x]}`} disabled={sections.includes(x) && sections.length === 1}
                onClick={() => toggle(x)}><span /></button>
            </div>
          ))}
          <div className="set-row muted"><span>Settings</span><span>Always shown</span></div>
        </div>
        <label className="field-label">Opens on</label>
        <div className="chip-row">
          {shown.map((x) => (
            <button key={x} type="button" className={"chip-btn" + (opensOn === x ? " on" : "")} onClick={() => setStart(x)}>{SECTION_LABEL[x]}</button>
          ))}
        </div>
        <label className="field-label">Speaker</label>
        <p className="muted connect-note">{SPEAKER_WHERE[layout]}. Speakers come from Home Assistant; with Music Assistant, Sonos and others appear here.</p>
        {playersError && <div className="form-error">{playersError}</div>}
        {!players && !playersError && <div className="screens-empty">Asking Home Assistant…</div>}
        <div className="player-list">
          <button type="button" className={"player-row" + (speaker === "" ? " on" : "")} onClick={() => setSpeaker("")}>
            <span className="player-main"><b>None</b><span>No Now playing on this screen</span></span>
          </button>
          {(players ?? []).map((p) => (
            <button type="button" key={p.entity_id} className={"player-row" + (speaker === p.entity_id ? " on" : "")} onClick={() => setSpeaker(p.entity_id)}>
              <span className="player-main"><b>{p.name}</b><span>{p.entity_id} · {p.state}</span></span>
              {p.music_assistant && <span className="tag ma">Music Assistant</span>}
            </button>
          ))}
        </div>
        <label className="field-label">Photo screensaver starts after</label>
        <Segmented value={String(idle)} options={IDLE_OPTS} onChange={(v) => setIdle(Number(v))} />
      </div>
    </Sheet>
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
    const pin = await askPin("Pair a screen or phone");
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
    <Sheet title="Pair a screen or phone" onClose={onClose} footer={<>
      <button className="btn ghost" onClick={onClose}>Cancel</button>
      <button className="btn" disabled={!valid || busy} onClick={submit}>Pair</button>
    </>}>
      <div className="form">
        <div className="field-label">Code shown on the screen or in the app</div>
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
        <div className="field-label">Style (screens only)</div>
        <Segmented value={layout} onChange={setLayout} options={[{ value: "auto", label: "By its size" }, ...STYLE_OPTS]} />
        {error && <div className="form-error">{error}</div>}
      </div>
    </Sheet>
  );
}

function photoCount(n: number) { return `${n} photo${n === 1 ? "" : "s"}`; }

function albumNames(ids: string[], albums: ImmichAlbum[] | undefined): string {
  const names = ids.map((id) => albums?.find((a) => a.id === id)?.name).filter(Boolean) as string[];
  return names.length === ids.length && names.length <= 3 ? names.join(", ") : `${ids.length} album${ids.length === 1 ? "" : "s"}`;
}

function sourceText(c: ImmichConfig, albums: ImmichAlbum[] | undefined): string {
  if (c.season_now?.length) return `${albumNames(c.season_now, albums)} (in season)`;
  const parts = [
    c.mode === "all" ? `All albums${c.excluded_album_ids.length ? ` except ${albumNames(c.excluded_album_ids, albums)}` : ""}`
      : c.album_ids.length ? albumNames(c.album_ids, albums) : "",
    c.favorites ? "favourites" : "", c.memories ? "on this day" : "",
  ].filter(Boolean);
  return parts.length ? parts.join(" + ") : "No albums chosen yet";
}

const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
const MONTH_DAYS = [31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
const pad2 = (n: number) => String(n).padStart(2, "0");

/** A day of the year as "MM-DD", picked as day + month. */
function DayOfYear({ value, onChange, label }: { value: string; onChange: (v: string) => void; label: string }) {
  const m = Number(value.slice(0, 2)), d = Number(value.slice(3));
  return (
    <span className="season-day">
      <select className="input" aria-label={`${label} day`} value={d} onChange={(e) => onChange(`${pad2(m)}-${pad2(Number(e.target.value))}`)}>
        {Array.from({ length: MONTH_DAYS[m - 1] }, (_, i) => <option key={i} value={i + 1}>{i + 1}</option>)}
      </select>
      <select className="input" aria-label={`${label} month`} value={m}
        onChange={(e) => { const nm = Number(e.target.value); onChange(`${pad2(nm)}-${pad2(Math.min(d, MONTH_DAYS[nm - 1]))}`); }}>
        {MONTHS.map((name, i) => <option key={i} value={i + 1}>{name}</option>)}
      </select>
    </span>
  );
}

function statusText(c: ImmichConfig): string {
  if (c.status === "auth_failed") return "Immich stopped accepting the API key · showing landscapes until it's replaced";
  if (c.status === "error") return `Can't reach Immich${c.last_error ? `: ${c.last_error}` : ""} · ${c.photo_count ? "showing the photos it had" : "showing landscapes"}`;
  if (c.status === "pending") return "Checking Immich…";
  return `${photoCount(c.photo_count)}${c.version ? ` · Immich ${c.version}` : ""}`;
}

/** Settings > Photo screensaver: photos from Immich, how long per photo, when to start. */
export function ScreensaverPanel({ onScreensaver }: { onScreensaver: () => void }) {
  const { api, settings, askPin, toast } = useApp();
  const [cfg] = useData((a) => a.immich(), ["photos"], []);
  const [albums] = useData((a) => (cfg?.configured ? a.immichAlbums().catch(() => undefined) : Promise.resolve(undefined)), ["photos"], [cfg?.configured]);
  const [editing, setEditing] = useState(false);
  async function save(patch: Partial<Settings>, why: string) {
    const pin = await askPin(why);
    if (!pin) return;
    try { await api.updateSettings({ ...patch, pin }); toast("Saved"); }
    catch (e) { toast(e instanceof ApiError ? e.message : "Couldn't save"); }
  }
  async function disconnect() {
    const pin = await askPin("Disconnect Immich? The screensaver goes back to painted landscapes (nothing changes in Immich).");
    if (!pin) return;
    try { await api.disconnectImmich(pin); toast("Immich disconnected"); }
    catch (e) { toast(e instanceof ApiError ? e.message : "Couldn't disconnect"); }
  }
  const secs = settings?.screensaver_seconds ?? 10;
  return (
    <section className="panel immich-panel">
      <div className="cal-panel-head">
        <h2 className="panel-title">Photo screensaver</h2>
        {cfg && !cfg.configured && <button className="btn small" onClick={() => setEditing(true)}><IconPhotos size={20} /> Connect Immich</button>}
      </div>
      {cfg && !cfg.configured && (
        <p className="muted cal-intro">
          Show photos from your <b>Immich</b> server: choose albums, favourites or "on this day" memories. Moonlight
          fetches them for the screens, so the screens never need Immich's address or key. Until then the screensaver
          shows painted landscapes.
        </p>
      )}
      {cfg?.configured && (
        <div className="acct">
          <div className="acct-head">
            <span className={`status-dot s-${cfg.status === "pending" ? "ok" : cfg.status}`} aria-label={cfg.status} />
            <div className="acct-name">
              <b>{sourceText(cfg, albums)}</b>
              <span className={cfg.status !== "ok" ? `s-${cfg.status}` : undefined}>Immich at {cfg.server_url} · {statusText(cfg)}</span>
            </div>
            <div className="acct-actions">
              <button className="btn small" onClick={() => setEditing(true)}>{cfg.status === "auth_failed" ? "Replace key" : "Choose photos"}</button>
              <button className="btn ghost small danger" onClick={disconnect}>Disconnect</button>
            </div>
          </div>
        </div>
      )}
      <div className="set-col"><span>Each photo for</span>
        <Segmented value={String(secs)} onChange={(v) => save({ screensaver_seconds: Number(v) }, "Change photo timing")}
          options={[5, 10, 20, 30, 60].map((v) => ({ value: String(v), label: `${v}s` }))} />
      </div>
      <div className="set-col"><span>When and where each photo was taken</span>
        <Segmented value={settings?.photo_details === false ? "hide" : "show"}
          onChange={(v) => save({ photo_details: v === "show" }, "Change photo details")}
          options={[{ value: "show", label: "Show" }, { value: "hide", label: "Hide" }]} />
      </div>
      <p className="muted connect-note">Places use your Home Assistant zones (like Home) when a photo was taken inside one, otherwise the town.</p>
      <p className="muted connect-note">When each screen starts the screensaver is set per screen under Screens.</p>
      <div className="set-row"><span>Try it</span><button className="btn ghost" onClick={onScreensaver}>Show now</button></div>
      {editing && cfg && <ImmichSheet cfg={cfg} onClose={() => setEditing(false)} />}
    </section>
  );
}

/** Connect Immich (address + API key, tested before saving) and choose what the screensaver shows. */
function ImmichSheet({ cfg, onClose }: { cfg: ImmichConfig; onClose: () => void }) {
  const { api, askPin, toast } = useApp();
  const [url, setUrl] = useState(cfg.server_url);
  const [key, setKey] = useState("");
  const [albums, setAlbums] = useState<ImmichAlbum[] | null>(null);
  const [mode, setMode] = useState<ImmichMode>(cfg.mode ?? "albums");
  const [chosen, setChosen] = useState<string[]>(cfg.album_ids);
  const [excluded, setExcluded] = useState<string[]>(cfg.excluded_album_ids ?? []);
  const [seasons, setSeasons] = useState<ImmichSeason[]>(cfg.seasons ?? []);
  const [favorites, setFavorites] = useState(cfg.favorites);
  const [memories, setMemories] = useState(cfg.memories);
  const [skipCert, setSkipCert] = useState(cfg.skip_cert_check);
  const https = /^https:/i.test(url.trim());
  const [pin, setPin] = useState<string | null>(null);
  const [busy, setBusy] = useState<"test" | "save" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [checked, setChecked] = useState<string | null>(null);
  const changedLogin = url.trim() !== cfg.server_url || !!key.trim();
  const canTest = /^https?:\/\/\S+/.test(url.trim()) && (!!key.trim() || cfg.key_set);

  useEffect(() => {
    if (!cfg.configured || cfg.status === "auth_failed") return;
    api.immichAlbums().then(setAlbums).catch((e) => setError(e instanceof ApiError ? e.message : "Couldn't load the albums"));
  }, [api, cfg.configured, cfg.status]);

  async function getPin(why: string) {
    if (pin) return pin;
    const p = await askPin(why);
    if (p) setPin(p);
    return p;
  }
  async function test() {
    if (!canTest || busy) return;
    const p = await getPin("Test the Immich connection");
    if (!p) return;
    setBusy("test"); setError(null); setChecked(null);
    try {
      const r = await api.testImmich({ server_url: url.trim(), api_key: key.trim() || undefined, skip_cert_check: https && skipCert, pin: p });
      setAlbums(r.albums);
      setChecked(`Connected${r.version ? ` to Immich ${r.version}` : ""} · ${r.albums.length} album${r.albums.length === 1 ? "" : "s"}`);
    } catch (e) {
      setAlbums(null);
      setError(e instanceof ApiError ? e.message : "Couldn't reach Immich. Check the address and try again.");
    } finally { setBusy(null); }
  }
  async function save() {
    if (!canTest || busy) return;
    const p = await getPin(cfg.configured ? "Change the screensaver photos" : "Connect Immich");
    if (!p) return;
    setBusy("save"); setError(null);
    try {
      const r = await api.saveImmich({ server_url: url.trim(), api_key: key.trim() || undefined, mode, album_ids: chosen, excluded_album_ids: excluded, seasons, favorites, memories, skip_cert_check: https && skipCert, pin: p });
      toast(r.status === "ok" ? `Saved · ${photoCount(r.photo_count)}` : "Saved, but Immich can't be reached right now");
      onClose();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't save");
    } finally { setBusy(null); }
  }
  const flip = (xs: string[], id: string) => (xs.includes(id) ? xs.filter((x) => x !== id) : [...xs, id]);
  const seasonal = new Set(seasons.map((s) => s.album_id));
  const isOn = (id: string) => (mode === "all" ? !excluded.includes(id) : chosen.includes(id));
  const toggle = (id: string) => (mode === "all" ? setExcluded((x) => flip(x, id)) : setChosen((c) => flip(c, id)));
  const nothing = mode === "albums" && !chosen.filter((id) => !seasonal.has(id)).length && !favorites && !memories;
  const setSeason = (i: number, patch: Partial<ImmichSeason>) => setSeasons((xs) => xs.map((s, k) => (k === i ? { ...s, ...patch } : s)));
  const free = albums?.filter((a) => !seasonal.has(a.id)) ?? [];

  return (
    <Sheet title={cfg.configured ? "Screensaver photos" : "Connect Immich"} onClose={onClose} footer={<>
      <button className="btn ghost" onClick={onClose}>Cancel</button>
      <span style={{ flex: 1 }} />
      <button className="btn ghost" disabled={!canTest || !!busy} onClick={test}>{busy === "test" ? "Testing…" : "Test connection"}</button>
      <button className="btn" disabled={!canTest || !!busy || (!cfg.configured && !albums)} onClick={save}>{busy === "save" ? "Saving…" : "Save"}</button>
    </>}>
      <form className="form" onSubmit={(e) => { e.preventDefault(); test(); }}>
        <label className="field-label">Immich address</label>
        <input className="input" placeholder="http://192.168.1.10:2283" value={url} autoCapitalize="off" spellCheck={false}
          onChange={(e) => { setUrl(e.target.value); setChecked(null); }} autoFocus={!cfg.configured} />
        <label className="field-label">API key</label>
        <input className="input" type="password" autoComplete="new-password" value={key}
          placeholder={cfg.key_set ? "Saved · type a new key to replace it" : "Paste the key from Immich"}
          onChange={(e) => { setKey(e.target.value); setChecked(null); }} />
        {https && (
          <div className="set-row"><span>Skip certificate check</span>
            <button type="button" className={"toggle" + (skipCert ? " on" : "")} onClick={() => { setSkipCert(!skipCert); setChecked(null); }}
              aria-pressed={skipCert} aria-label="Skip certificate check"><span /></button>
          </div>
        )}
        {https && skipCert && <p className="muted connect-note">For a self-signed certificate, or one made for a domain name while you enter the IP address. Only use it on your home network.</p>}
        <p className="muted connect-note">
          In Immich: Account Settings › API Keys › New API Key (permissions album.read, asset.read and asset.view;
          memory.read for "on this day"). The key stays on this Moonlight add-on and is never sent to the screens.
          {api.mode === "demo" && " (Demo: any address and key work; the key “wrong” is rejected.)"}
        </p>
        {error && <div className="connect-error" role="alert">{error}</div>}
        {checked && <div className="immich-ok" role="status">{checked}</div>}
        {albums && (<>
          <div className="set-col"><span>Show</span>
            <Segmented value={mode} onChange={setMode}
              options={[{ value: "albums", label: "Chosen albums" }, { value: "all", label: "All albums" }]} />
          </div>
          <label className="field-label">{mode === "all" ? "Albums to show (tap one to leave it out)" : "Albums to show"}</label>
          {albums.length === 0 && <p className="muted connect-note">No albums in this Immich account yet.</p>}
          <div className="chip-row immich-albums">
            {albums.filter((a) => !seasonal.has(a.id)).map((a) => (
              <button type="button" key={a.id} className={"chip-btn" + (isOn(a.id) ? " on" : mode === "all" ? " off" : "")}
                aria-pressed={isOn(a.id)} onClick={() => toggle(a.id)}>
                {a.name} <span>{a.asset_count}</span>
              </button>
            ))}
          </div>
          {mode === "all" && <p className="muted connect-note">New albums made in Immich are shown too, unless you leave them out here.</p>}
          <label className="field-label">Seasonal albums</label>
          <p className="muted connect-note">
            Shown on their own between their dates (like Christmas from 1 to 26 December) and hidden the rest of the year.
          </p>
          {seasons.map((s, i) => (
            <div className="season-row" key={i}>
              <select className="input" aria-label="Seasonal album" value={s.album_id} onChange={(e) => setSeason(i, { album_id: e.target.value })}>
                {albums.filter((a) => a.id === s.album_id || !seasonal.has(a.id)).map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
                {!albums.some((a) => a.id === s.album_id) && <option value={s.album_id}>Album no longer in Immich</option>}
              </select>
              <span className="season-dates">
                <DayOfYear label="From" value={s.start} onChange={(v) => setSeason(i, { start: v })} />
                <span>to</span>
                <DayOfYear label="To" value={s.end} onChange={(v) => setSeason(i, { end: v })} />
              </span>
              <button type="button" className="btn ghost small danger" onClick={() => setSeasons((xs) => xs.filter((_, k) => k !== i))}>Remove</button>
            </div>
          ))}
          {free.length > 0 && seasons.length < 20 && (
            <div><button type="button" className="btn ghost small" onClick={() => {
              const pick = free.find((a) => /christmas|xmas|festive/i.test(a.name)) ?? free[0];
              setSeasons((xs) => [...xs, { album_id: pick.id, start: "12-01", end: "12-26" }]);
            }}>Add a seasonal album</button></div>
          )}
          <div className="set-row"><span>Also show favourites</span>
            <button type="button" className={"toggle" + (favorites ? " on" : "")} onClick={() => setFavorites(!favorites)} aria-pressed={favorites} aria-label="Also show favourites"><span /></button>
          </div>
          <div className="set-row"><span>Also show "on this day" memories</span>
            <button type="button" className={"toggle" + (memories ? " on" : "")} onClick={() => setMemories(!memories)} aria-pressed={memories} aria-label="Also show on this day memories"><span /></button>
          </div>
          {nothing && <p className="muted connect-note">Choose at least one album (or favourites) to show photos.</p>}
          <p className="muted connect-note">
            The screensaver plays one whole album at a time, choosing recently changed albums most often and "on this day"
            first. Photos only (videos are skipped). New photos added in Immich show up within a few minutes.
          </p>
        </>)}
        {!albums && !cfg.configured && <p className="muted connect-note">Test the connection to choose albums.</p>}
        {changedLogin && cfg.configured && <p className="muted connect-note">A new address or key is checked with Immich when you save.</p>}
        <button type="submit" hidden />
      </form>
    </Sheet>
  );
}
