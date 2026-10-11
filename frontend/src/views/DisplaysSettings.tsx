import { useEffect, useState } from "react";
import { ApiError, DEFAULT_SCREENS, Display, ImmichAlbum, ImmichConfig, Layout, MediaPlayerOption, SECTIONS, Section, Settings } from "../api/types";
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

const KINDS: { layout: Layout; title: string; note: string }[] = [
  { layout: "hallway", title: "Hallway screen", note: "Big wall screen" },
  { layout: "kitchen", title: "Kitchen screen", note: "10in touch screen" },
  { layout: "phone", title: "Phones", note: "Home Assistant app and phone browsers; no pairing needed" },
];
const SECTION_LABEL: Record<Section, string> = {
  today: "Today", calendar: "Calendar", chores: "Chores", rewards: "Rewards", meals: "Meals", lists: "Lists",
};
const SPEAKER_WHERE: Record<Layout, string> = {
  kitchen: "Card on Today, album art on the screensaver",
  hallway: "Small player in the top bar",
  phone: "Small player in the top bar",
};
const IDLE_OPTS = [0, 1, 3, 5, 10, 30].map((v) => ({ value: String(v), label: v === 0 ? "Never" : `${v} min` }));
const DEFAULT_IDLE: Record<Layout, number> = { hallway: 5, kitchen: 3, phone: 0 };

/** Settings > Screens: each kind of screen (its sections, start page, speaker, screensaver and the paired
 *  devices showing it), plus connections such as the Home Assistant integration. */
export function ScreensPanel() {
  const { api, settings, askPin, toast } = useApp();
  const [screens] = useData((a) => a.displays(), ["displays"], []);
  const [players, setPlayers] = useState<MediaPlayerOption[] | null>(null);
  const [playersError, setPlayersError] = useState<string | null>(null);
  const [pairing, setPairing] = useState(false);
  const [setting, setSetting] = useState<Layout | null>(null);
  const [renaming, setRenaming] = useState<Display | null>(null);
  const now = useNow(30_000);
  useEffect(() => {
    api.mediaPlayers().then((p) => { setPlayers(p); setPlayersError(null); })
      .catch((e) => setPlayersError(e instanceof ApiError ? e.message : "Couldn't reach Home Assistant"));
  }, [api]);

  async function revoke(d: Display) {
    const pin = await askPin(d.layout === "service" ? `Disconnect ${d.name}? It stops getting Moonlight's data.`
      : `Remove ${d.name}? It will need pairing again.`);
    if (!pin) return;
    try { await api.revokeDisplay(d.id, pin); toast(`${d.name} removed`); }
    catch (e) { toast(e instanceof ApiError ? e.message : "Couldn't remove"); }
  }
  const speakerName = (id: string) => players?.find((p) => p.entity_id === id)?.name ?? id;
  const services = (screens ?? []).filter((d) => d.layout === "service");

  return (
    <section className="panel screens-panel">
      <div className="panel-head">
        <h2 className="panel-title">Screens</h2>
        <button className="btn small" onClick={() => setPairing(true)}>Pair a new screen</button>
      </div>
      <p className="muted screens-help">
        A wall screen opens <code>http://&lt;home-assistant&gt;:8091/display/kitchen</code> (or <code>/display/hallway</code>)
        and shows a 6-digit code to enter here.
      </p>
      {KINDS.map(({ layout, title, note }) => {
        const setup = settings?.screens?.[layout] ?? DEFAULT_SCREENS[layout];
        const speaker = settings?.media_players?.[layout] ?? "";
        const idle = settings?.idle_minutes?.[layout] ?? DEFAULT_IDLE[layout];
        const devices = (screens ?? []).filter((d) => d.layout === layout);
        return (
          <div key={layout} className="screen-kind">
            <div className="screen-kind-head">
              <span className={`screen-ico ${layout}`} aria-hidden />
              <div className="screen-main">
                <b>{title}</b>
                <span>
                  Opens on {SECTION_LABEL[setup.start]} · {setup.sections.length} section{setup.sections.length === 1 ? "" : "s"}
                  {" · "}{speaker ? speakerName(speaker) : "No speaker"}
                  {" · "}{idle ? `Screensaver after ${idle} min` : "No screensaver"}
                </span>
              </div>
              <button className="btn ghost small" onClick={() => setSetting(layout)}>Set up</button>
            </div>
            {layout === "phone" ? <div className="screen-note muted">{note}</div> : (
              <div className="screen-list">
                {devices.map((d) => (
                  <div key={d.id} className="screen-row">
                    <div className="screen-main">
                      <b>{d.name}{d.current && <em className="screen-this">This screen</em>}</b>
                      <span>Paired · seen {ago(d.last_seen, now).toLowerCase()}</span>
                    </div>
                    <button className="btn ghost small" onClick={() => setRenaming(d)}>Rename</button>
                    <button className="btn ghost small danger" onClick={() => revoke(d)}>Remove</button>
                  </div>
                ))}
                {screens && devices.length === 0 && <div className="screen-note muted">No {title.toLowerCase()} paired yet.</div>}
              </div>
            )}
          </div>
        );
      })}
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
      {setting && <ScreenSetupSheet layout={setting} title={KINDS.find((k) => k.layout === setting)!.title}
        players={players} playersError={playersError} onClose={() => setSetting(null)} />}
      {renaming && <RenameSheet display={renaming} onClose={() => setRenaming(null)} />}
    </section>
  );
}

/** One kind of screen: which sections its menu shows, the one it opens on, its speaker and screensaver delay. */
function ScreenSetupSheet({ layout, title, players, playersError, onClose }: {
  layout: Layout; title: string; players: MediaPlayerOption[] | null; playersError: string | null; onClose: () => void;
}) {
  const { api, settings, askPin, toast } = useApp();
  const setup = settings?.screens?.[layout] ?? DEFAULT_SCREENS[layout];
  const [sections, setSections] = useState<Section[]>(setup.sections);
  const [start, setStart] = useState<Section>(setup.start);
  const [speaker, setSpeaker] = useState(settings?.media_players?.[layout] ?? "");
  const [idle, setIdle] = useState(settings?.idle_minutes?.[layout] ?? DEFAULT_IDLE[layout]);
  const [saving, setSaving] = useState(false);
  const shown = SECTIONS.filter((x) => sections.includes(x));
  const opensOn = shown.includes(start) ? start : shown[0];
  function toggle(x: Section) {
    if (sections.includes(x)) { if (sections.length > 1) setSections(sections.filter((y) => y !== x)); }
    else setSections([...sections, x]);
  }
  async function save() {
    const pin = await askPin(`Change the ${title.toLowerCase()}`);
    if (!pin) return;
    setSaving(true);
    try {
      await api.updateSettings({
        pin, screens: { [layout]: { sections: shown, start: opensOn } },
        media_players: { [layout]: speaker }, idle_minutes: { [layout]: idle },
      });
      toast("Saved");
      onClose();
    } catch (e) { toast(e instanceof ApiError ? e.message : "Couldn't save"); }
    finally { setSaving(false); }
  }
  return (
    <Sheet title={title} onClose={onClose} footer={<>
      <button className="btn ghost" onClick={onClose}>Cancel</button>
      <span style={{ flex: 1 }} />
      <button className="btn" disabled={saving} onClick={save}>{saving ? "Saving…" : "Save"}</button>
    </>}>
      <div className="form">
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

function RenameSheet({ display, onClose }: { display: Display; onClose: () => void }) {
  const { api, askPin, toast } = useApp();
  const [name, setName] = useState(display.name);
  async function save() {
    if (!name.trim()) return;
    const pin = await askPin(`Rename ${display.name}`);
    if (!pin) return;
    try { await api.renameDisplay(display.id, name.trim(), pin); toast("Renamed"); onClose(); }
    catch (e) { toast(e instanceof ApiError ? e.message : "Couldn't rename"); }
  }
  return (
    <Sheet title={`Rename ${display.name}`} onClose={onClose} footer={<>
      <button className="btn ghost" onClick={onClose}>Cancel</button>
      <span style={{ flex: 1 }} />
      <button className="btn" disabled={!name.trim()} onClick={save}>Save</button>
    </>}>
      <form className="form" onSubmit={(e) => { e.preventDefault(); save(); }}>
        <label className="field-label">Name</label>
        <input className="input" value={name} maxLength={60} autoFocus onChange={(e) => setName(e.target.value)} />
      </form>
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

function photoCount(n: number) { return `${n} photo${n === 1 ? "" : "s"}`; }

function sourceText(c: ImmichConfig, albums: ImmichAlbum[] | undefined): string {
  const names = c.album_ids.map((id) => albums?.find((a) => a.id === id)?.name).filter(Boolean) as string[];
  const parts = [
    names.length === c.album_ids.length && names.length <= 3 ? names.join(", ") : c.album_ids.length ? `${c.album_ids.length} album${c.album_ids.length === 1 ? "" : "s"}` : "",
    c.favorites ? "favourites" : "", c.memories ? "on this day" : "",
  ].filter(Boolean);
  return parts.length ? parts.join(" + ") : "No albums chosen yet";
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
  const [chosen, setChosen] = useState<string[]>(cfg.album_ids);
  const [favorites, setFavorites] = useState(cfg.favorites);
  const [memories, setMemories] = useState(cfg.memories);
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
      const r = await api.testImmich({ server_url: url.trim(), api_key: key.trim() || undefined, pin: p });
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
      const r = await api.saveImmich({ server_url: url.trim(), api_key: key.trim() || undefined, album_ids: chosen, favorites, memories, pin: p });
      toast(r.status === "ok" ? `Saved · ${photoCount(r.photo_count)}` : "Saved, but Immich can't be reached right now");
      onClose();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't save");
    } finally { setBusy(null); }
  }
  const toggle = (id: string) => setChosen((c) => (c.includes(id) ? c.filter((x) => x !== id) : [...c, id]));
  const nothing = !chosen.length && !favorites && !memories;

  return (
    <Sheet title={cfg.configured ? "Screensaver photos" : "Connect Immich"} onClose={onClose} footer={<>
      <button className="btn ghost" onClick={onClose}>Cancel</button>
      <span style={{ flex: 1 }} />
      <button className="btn ghost" disabled={!canTest || !!busy} onClick={test}>{busy === "test" ? "Testing…" : "Test connection"}</button>
      <button className="btn" disabled={!canTest || !!busy || (!cfg.configured && !albums)} onClick={save}>{busy === "save" ? "Saving…" : "Save"}</button>
    </>}>
      <form className="form" onSubmit={(e) => { e.preventDefault(); test(); }}>
        <label className="field-label">Immich address</label>
        <input className="input" placeholder="http://homeassistant.local:2283" value={url} autoCapitalize="off" spellCheck={false}
          onChange={(e) => { setUrl(e.target.value); setChecked(null); }} autoFocus={!cfg.configured} />
        <label className="field-label">API key</label>
        <input className="input" type="password" autoComplete="new-password" value={key}
          placeholder={cfg.key_set ? "Saved · type a new key to replace it" : "Paste the key from Immich"}
          onChange={(e) => { setKey(e.target.value); setChecked(null); }} />
        <p className="muted connect-note">
          In Immich: Account Settings › API Keys › New API Key (permissions album.read, asset.read and asset.view;
          memory.read for "on this day"). The key stays on this Moonlight add-on and is never sent to the screens.
          {api.mode === "demo" && " (Demo: any address and key work; the key “wrong” is rejected.)"}
        </p>
        {error && <div className="connect-error" role="alert">{error}</div>}
        {checked && <div className="immich-ok" role="status">{checked}</div>}
        {albums && (<>
          <label className="field-label">Albums to show</label>
          {albums.length === 0 && <p className="muted connect-note">No albums in this Immich account yet.</p>}
          <div className="chip-row immich-albums">
            {albums.map((a) => (
              <button type="button" key={a.id} className={"chip-btn" + (chosen.includes(a.id) ? " on" : "")}
                aria-pressed={chosen.includes(a.id)} onClick={() => toggle(a.id)}>
                {a.name} <span>{a.asset_count}</span>
              </button>
            ))}
          </div>
          <div className="set-row"><span>Also show favourites</span>
            <button type="button" className={"toggle" + (favorites ? " on" : "")} onClick={() => setFavorites(!favorites)} aria-pressed={favorites} aria-label="Also show favourites"><span /></button>
          </div>
          <div className="set-row"><span>Also show "on this day" memories</span>
            <button type="button" className={"toggle" + (memories ? " on" : "")} onClick={() => setMemories(!memories)} aria-pressed={memories} aria-label="Also show on this day memories"><span /></button>
          </div>
          {nothing && <p className="muted connect-note">Choose at least one album (or favourites) to show photos.</p>}
          <p className="muted connect-note">Photos only (videos are skipped). New photos added in Immich show up within a few minutes.</p>
        </>)}
        {!albums && !cfg.configured && <p className="muted connect-note">Test the connection to choose albums.</p>}
        {changedLogin && cfg.configured && <p className="muted connect-note">A new address or key is checked with Immich when you save.</p>}
        <button type="submit" hidden />
      </form>
    </Sheet>
  );
}
