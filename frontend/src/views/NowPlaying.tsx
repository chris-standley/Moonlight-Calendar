// "Now playing" for the speaker set for this screen (Settings > Screens > Set up): a card on Today (compact screens), a pill in
// the top bar elsewhere, a big sheet with album art, and a corner card on the screensaver.
import { createContext, CSSProperties, ReactNode, useCallback, useContext, useEffect, useRef, useState } from "react";
import { Api, ApiError, Layout, MediaAction, MediaFavourite, NowPlaying } from "../api/types";
import { useApp } from "../state";
import {
  IconClose, IconMusic, IconMute, IconNext, IconPause, IconPlay, IconPrev, IconRepeat, IconRepeatOne, IconShuffle, IconVolume,
} from "../components/icons";

interface MediaCtx {
  np: NowPlaying | null;
  /** Date.now() when `np` arrived, for ticking the progress bar locally. */
  at: number;
  act: (action: MediaAction, value?: number | boolean | string) => Promise<void>;
  openSheet: () => void;
}
const Ctx = createContext<MediaCtx>({ np: null, at: 0, act: async () => undefined, openSheet: () => undefined });
export const useMedia = () => useContext(Ctx);

/** Fetches now-playing for this screen's layout and refetches on the `media` topic (pushed from Home Assistant). */
export function MediaProvider({ api, layout, children }: { api: Api; layout: Layout; children: ReactNode }) {
  const [np, setNp] = useState<NowPlaying | null>(null);
  const [at, setAt] = useState(0);
  const atRef = useRef(0);
  atRef.current = at;
  const [sheet, setSheet] = useState(false);
  const seq = useRef(0);
  const set = useCallback((x: NowPlaying) => { setNp(x); setAt(Date.now()); }, []);
  const load = useCallback(() => {
    const my = ++seq.current;
    api.nowPlaying(layout).then((x) => { if (my === seq.current) set(x); }).catch(() => { /* offline: keep what we had */ });
  }, [api, layout, set]);
  useEffect(() => { load(); return api.subscribe((t) => { if (t === "media" || t === "settings") load(); }); }, [api, load]);
  // Belt and braces: an occasional refresh in case a push was missed (e.g. the screen's socket was reconnecting).
  const showing = !!np?.show;
  useEffect(() => { const t = setInterval(load, showing ? 30_000 : 120_000); return () => clearInterval(t); }, [load, showing]);
  useEffect(() => { if (!showing) setSheet(false); }, [showing]);

  const act = useCallback(async (action: MediaAction, value?: number | boolean | string) => {
    // Optimistic: the speaker takes a moment to report back; screens shouldn't feel laggy.
    const fetchedAt = atRef.current;
    setNp((cur) => cur && optimistic(cur, action, value, fetchedAt));
    if (action === "play_pause") setAt(Date.now());
    const my = ++seq.current;
    try { const x = await api.mediaCommand(layout, action, value); if (my === seq.current) set(x); }
    catch (e) { load(); throw e; }
  }, [api, layout, set, load]);

  return (
    <Ctx.Provider value={{ np, at, act, openSheet: () => setSheet(true) }}>
      {children}
      {sheet && np?.show && <NowPlayingSheet onClose={() => setSheet(false)} />}
    </Ctx.Provider>
  );
}

function optimistic(np: NowPlaying, action: MediaAction, value: unknown, fetchedAt: number): NowPlaying {
  switch (action) {
    case "play_pause": {
      // Freeze (or restart) the clock at the current position, measured from now on this screen.
      const now = new Date().toISOString();
      return { ...np, state: np.state === "playing" ? "paused" : "playing", position: posNow(np, fetchedAt), position_updated_at: now, server_time: now };
    }
    case "volume_set": return { ...np, volume: Number(value), muted: Number(value) > 0 ? false : np.muted };
    case "volume_mute": return { ...np, muted: !!value };
    case "shuffle_set": return { ...np, shuffle: !!value };
    case "repeat_set": return { ...np, repeat: value as NowPlaying["repeat"] };
    default: return np;
  }
}

/** Current position in seconds: HA's position at position_updated_at, plus the time since (if playing). */
export function posNow(np: NowPlaying, fetchedAt: number): number | null {
  if (np.position == null) return null;
  let p = np.position;
  if (np.state === "playing" && np.position_updated_at) {
    const sinceUpdate = (Date.parse(np.server_time) - Date.parse(np.position_updated_at)) / 1000;
    p += Math.max(0, sinceUpdate) + (fetchedAt ? Math.max(0, (Date.now() - fetchedAt) / 1000) : 0);
  }
  return np.duration ? Math.min(p, np.duration) : p;
}

const fmt = (s: number | null) => {
  if (s == null || !isFinite(s)) return "";
  const m = Math.floor(s / 60), sec = Math.floor(s % 60);
  return m >= 60 ? `${Math.floor(m / 60)}:${String(m % 60).padStart(2, "0")}:${String(sec).padStart(2, "0")}` : `${m}:${String(sec).padStart(2, "0")}`;
};

/** Re-render every second while something is playing. */
function useTick(on: boolean) {
  const [, setN] = useState(0);
  useEffect(() => { if (!on) return; const t = setInterval(() => setN((n) => n + 1), 1000); return () => clearInterval(t); }, [on]);
}

export function Art({ np, className }: { np: NowPlaying; className?: string }) {
  const [failed, setFailed] = useState<string | null>(null);
  const ok = np.art_url && failed !== np.art_url;
  return (
    <div className={"np-art" + (className ? " " + className : "")}>
      {ok ? <img src={np.art_url!} alt="" draggable={false} onError={() => setFailed(np.art_url)} /> : <span className="np-art-none"><IconMusic size={28} /></span>}
    </div>
  );
}

function Progress({ np, at, times }: { np: NowPlaying; at: number; times?: boolean }) {
  useTick(np.state === "playing");
  const pos = posNow(np, at);
  if (!np.duration || pos == null) return times ? <div className="np-progress live"><i style={{ width: "100%" }} /></div> : null;
  return (
    <div className="np-prog-wrap">
      <div className="np-progress"><i style={{ width: `${Math.min(100, (pos / np.duration) * 100)}%` }} /></div>
      {times && <div className="np-times"><span>{fmt(pos)}</span><span>-{fmt(np.duration - pos)}</span></div>}
    </div>
  );
}

function useCommand() {
  const { act } = useMedia();
  const { toast } = useApp();
  return useCallback((action: MediaAction, value?: number | boolean | string) => {
    act(action, value).catch((e) => toast(e instanceof ApiError ? e.message : "The speaker didn't respond"));
  }, [act, toast]);
}

function Transport({ np, big }: { np: NowPlaying; big?: boolean }) {
  const cmd = useCommand();
  const playing = np.state === "playing" || np.state === "buffering";
  const s = big ? 34 : 24;
  return (
    <div className={"np-transport" + (big ? " big" : "")} onClick={(e) => e.stopPropagation()}>
      {big && np.supports.shuffle && (
        <button className={"np-btn mode" + (np.shuffle ? " on" : "")} aria-label="Shuffle" onClick={() => cmd("shuffle_set", !np.shuffle)}><IconShuffle size={24} /></button>
      )}
      <button className="np-btn" aria-label="Previous" disabled={!np.supports.previous} onClick={() => cmd("previous")}><IconPrev size={s} /></button>
      <button className="np-btn play" aria-label={playing ? "Pause" : "Play"} disabled={!np.supports.play_pause} onClick={() => cmd("play_pause")}>
        {playing ? <IconPause size={s + 4} /> : <IconPlay size={s + 4} />}
      </button>
      <button className="np-btn" aria-label="Next" disabled={!np.supports.next} onClick={() => cmd("next")}><IconNext size={s} /></button>
      {big && np.supports.repeat && (
        <button className={"np-btn mode" + (np.repeat && np.repeat !== "off" ? " on" : "")} aria-label={`Repeat: ${np.repeat ?? "off"}`}
          onClick={() => cmd("repeat_set", np.repeat === "off" ? "all" : np.repeat === "all" ? "one" : "off")}>
          {np.repeat === "one" ? <IconRepeatOne size={24} /> : <IconRepeat size={24} />}
        </button>
      )}
    </div>
  );
}

/** Touch-friendly volume: follows the finger locally, sends at most a few updates a second. */
function Volume({ np }: { np: NowPlaying }) {
  const cmd = useCommand();
  const [local, setLocal] = useState<number | null>(null);
  const lastSent = useRef(0);
  const pending = useRef<ReturnType<typeof setTimeout> | null>(null);
  const release = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => { if (pending.current) clearTimeout(pending.current); if (release.current) clearTimeout(release.current); }, []);
  if (!np.supports.volume || np.volume == null) return null;
  const v = local ?? (np.muted ? 0 : np.volume);
  function change(x: number) {
    setLocal(x);
    if (release.current) clearTimeout(release.current);
    release.current = setTimeout(() => setLocal(null), 1500); // then follow the speaker again
    const send = () => { lastSent.current = Date.now(); pending.current = null; cmd("volume_set", x); };
    if (pending.current) clearTimeout(pending.current);
    const wait = 250 - (Date.now() - lastSent.current);
    if (wait <= 0) send(); else pending.current = setTimeout(send, wait);
  }
  return (
    <div className="np-volume" onClick={(e) => e.stopPropagation()}>
      <button className="np-btn small" aria-label={np.muted ? "Unmute" : "Mute"} disabled={!np.supports.mute}
        onClick={() => cmd("volume_mute", !np.muted)}>{np.muted || v === 0 ? <IconMute size={22} /> : <IconVolume size={22} />}</button>
      <input type="range" min={0} max={100} step={1} value={Math.round(v * 100)} aria-label="Volume"
        style={{ "--v": `${v * 100}%` } as CSSProperties}
        onChange={(e) => change(Number(e.target.value) / 100)} />
    </div>
  );
}

/** Today (compact screens): a card. Hidden when nothing is playing or queued. */
export function NowPlayingCard() {
  const { np, at, openSheet } = useMedia();
  if (!np?.show) return null;
  return (
    <section className={"panel np-card" + (np.state === "playing" ? " playing" : "")} onClick={openSheet} role="button" aria-label="Open now playing">
      <div className="np-top">
        <Art np={np} />
        <div className="np-text">
          <b>{np.title ?? "Unknown track"}</b>
          <span>{np.artist ?? np.album ?? np.name}</span>
        </div>
      </div>
      <Progress np={np} at={at} />
      <Transport np={np} />
      <Volume np={np} />
    </section>
  );
}

/** Top bar: a small pill (large screens, phones, and compact screens away from Today). */
export function NowPlayingPill() {
  const { np, openSheet } = useMedia();
  const cmd = useCommand();
  if (!np?.show) return null;
  const playing = np.state === "playing" || np.state === "buffering";
  return (
    <div className="np-pill" onClick={openSheet} role="button" aria-label="Open now playing">
      <Art np={np} />
      <span className="np-pill-text"><b>{np.title ?? "Playing"}</b>{np.artist && <span>{np.artist}</span>}</span>
      <button className="np-btn small" aria-label={playing ? "Pause" : "Play"} onClick={(e) => { e.stopPropagation(); cmd("play_pause"); }}>
        {playing ? <IconPause size={20} /> : <IconPlay size={20} />}
      </button>
    </div>
  );
}

function NowPlayingSheet({ onClose }: { onClose: () => void }) {
  const { np, at } = useMedia();
  const { api, layout, toast } = useApp();
  const [favs, setFavs] = useState<MediaFavourite[] | null>(null);
  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);
  const ma = !!np?.music_assistant;
  useEffect(() => { if (ma) api.mediaFavourites(layout).then(setFavs).catch(() => setFavs([])); }, [api, layout, ma]);
  if (!np) return null;
  async function play(f: MediaFavourite) {
    try { await api.playFavourite(layout, f.uri); toast(`Playing ${f.name}`); }
    catch (e) { toast(e instanceof ApiError ? e.message : "Couldn't play that"); }
  }
  return (
    <div className="scrim np-scrim" onClick={onClose}>
      <div className="sheet wide np-sheet" onClick={(e) => e.stopPropagation()} role="dialog" aria-label="Now playing">
        {np.art_url && <img className="np-backdrop" src={np.art_url} alt="" />}
        <div className="np-sheet-in">
          <Art np={np} className="big" />
          <div className="np-detail">
            <div className="np-where"><IconMusic size={16} /> {np.name}{np.source ? ` · ${np.source}` : ""}
              <button className="np-close" onClick={onClose} aria-label="Close"><IconClose size={22} /></button>
            </div>
            <div className="np-title">{np.title ?? "Unknown track"}</div>
            {np.artist && <div className="np-artist">{np.artist}</div>}
            {np.album && <div className="np-album">{np.album}</div>}
            <Progress np={np} at={at} times />
            <Transport np={np} big />
            <Volume np={np} />
            {favs && favs.length > 0 && (
              <div className="np-favs">
                <span>Favourites</span>
                <div className="np-fav-row">{favs.map((f) => <button key={f.uri} className="np-fav" onClick={() => play(f)}>{f.name}</button>)}</div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

/** Screensaver corner card while music is playing. */
export function ScreensaverNowPlaying() {
  const { np } = useMedia();
  if (!np?.show || np.state !== "playing") return null;
  return (
    <div className="ss-np">
      <Art np={np} />
      <div className="ss-np-text">
        <span className="ss-np-eq" aria-hidden><i /><i /><i /></span>
        <b>{np.title}</b>
        {np.artist && <span>{np.artist}</span>}
      </div>
    </div>
  );
}
