import { useEffect, useState } from "react";
import { ApiError, Display, ImmichAlbum, ImmichConfig, Layout, Settings } from "../api/types";
import { useApp, useData, useNow } from "../state";
import { Segmented, Sheet } from "../components/ui";
import { IconPhotos } from "../components/icons";

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
        Wall screens open <code>http://&lt;home-assistant&gt;:8091/display/kitchen</code> and show a 6-digit code.
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
  const idle = { hallway: 5, kitchen: 3, phone: 0, ...settings?.idle_minutes };
  const idleOpts = [0, 1, 3, 5, 10, 30].map((v) => ({ value: String(v), label: v === 0 ? "Never" : `${v} min` }));
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
      {(["hallway", "kitchen"] as const).map((l) => (
        <div key={l} className="set-col"><span>{l === "hallway" ? "Hallway" : "Kitchen"} starts after</span>
          <Segmented value={String(idle[l])} options={idleOpts}
            onChange={(v) => save({ idle_minutes: { [l]: Number(v) } }, "Change screensaver timing")} />
        </div>
      ))}
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
