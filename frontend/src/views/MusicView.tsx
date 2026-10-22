// The Music tab, on screens with a speaker (Settings > Screens > Set up > Speaker): what's playing with big art and the
// controls, then three panes: Up next (the queue), Library (browse and search Music Assistant, or a Sonos speaker's
// favourites; play now, next, or at the end of the queue) and Rooms (group speakers, each room's volume).
import { ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { ApiError, Enqueue, MediaBrowse, MediaItem, MediaRooms, QueueTrack } from "../api/types";
import { useApp } from "../state";
import { Segmented } from "../components/ui";
import {
  IconCheck, IconClose, IconLeft, IconMore, IconMusic, IconPlay, IconPlayNext, IconPlus, IconQueue, IconSearch, IconSpeakers, IconTrash,
} from "../components/icons";
import { Art, fmtDuration, Progress, Transport, useMedia, Volume, VolumeSlider } from "./NowPlaying";

type Pane = "queue" | "library" | "rooms";

/** Refetch on the `media` topic (the speaker changed), a beat later so a burst of changes is one fetch. */
function useMediaData<T>(load: () => Promise<T>, deps: unknown[]): [T | null, string | null, () => void] {
  const { api } = useApp();
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const seq = useRef(0);
  const loadRef = useRef(load);
  loadRef.current = load;
  const run = useCallback(() => {
    const my = ++seq.current;
    loadRef.current().then((d) => { if (my === seq.current) { setData(d); setError(null); } })
      .catch((e) => { if (my === seq.current) setError(e instanceof ApiError ? e.message : "Couldn't reach the speaker"); });
  }, []);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { run(); }, deps);
  useEffect(() => {
    let t: ReturnType<typeof setTimeout> | null = null;
    const off = api.subscribe((topic) => { if (topic === "media") { if (t) clearTimeout(t); t = setTimeout(run, 400); } });
    return () => { off(); if (t) clearTimeout(t); };
  }, [api, run]);
  return [data, error, run];
}

export function MusicView() {
  const { np, at } = useMedia();
  const [pane, setPane] = useState<Pane | null>(null);
  const shown: Pane = pane ?? (np?.show ? "queue" : "library");
  const playing = !!np?.show;
  return (
    <div className={"music-view" + (playing ? "" : " idle")}>
      <section className="mu-hero">
        {playing && np.art_url && <img className="np-backdrop" src={np.art_url} alt="" />}
        <div className="mu-hero-in">
          {np && playing ? <>
            <div className="mu-now">
              <Art np={np} className="big" />
              <div className="mu-now-text">
                <div className="np-where"><IconMusic size={16} /> {np.name}</div>
                <div className="np-title">{np.title ?? "Unknown track"}</div>
                {(np.artist || np.album) && <div className="np-artist">{[np.artist, np.album].filter(Boolean).join(" · ")}</div>}
              </div>
            </div>
            <div className="np-detail">
              <Progress np={np} at={at} times />
              <Transport np={np} big />
              <Volume np={np} />
            </div>
          </> : (
            <div className="mu-nothing">
              <span className="np-art-none"><IconMusic size={44} /></span>
              <b>Nothing playing</b>
              <span>{np?.configured ? `on ${np.name ?? np.entity ?? "the speaker"}. Pick something from the library.` : "Set a speaker for this screen in Settings › Screens."}</span>
              {np?.error && <span className="mu-err">{np.error}</span>}
            </div>
          )}
        </div>
      </section>
      <section className="panel mu-side">
        <Segmented<Pane> value={shown} onChange={setPane} options={[
          { value: "queue", label: <><IconQueue size={18} /> Up next</> },
          { value: "library", label: <><IconMusic size={18} /> Library</> },
          { value: "rooms", label: <><IconSpeakers size={18} /> Rooms</> },
        ]} />
        <div className="mu-pane">
          {shown === "queue" && <QueuePane onLibrary={() => setPane("library")} />}
          {shown === "library" && <LibraryPane />}
          {shown === "rooms" && <RoomsPane />}
        </div>
      </section>
    </div>
  );
}

// ---------------------------------------------------------------- Up next

function QueuePane({ onLibrary }: { onLibrary: () => void }) {
  const { api, layout, toast } = useApp();
  const [q, error] = useMediaData(() => api.mediaQueue(layout), [api, layout]);
  const [pick, setPick] = useState<QueueTrack | null>(null);
  if (!q) return error ? <p className="mu-note">{error}</p> : <p className="mu-note">Loading…</p>;
  const current = q.items.find((t) => t.current);
  const next = q.items.filter((t) => !t.current);
  async function act(t: QueueTrack, action: "play" | "remove" | "next") {
    setPick(null);
    try { await api.mediaQueueAction(layout, action, t.key); toast(action === "play" ? `Playing ${t.title}` : action === "remove" ? "Removed" : `${t.title} plays next`); }
    catch (e) { toast(e instanceof ApiError ? e.message : "The speaker didn't respond"); }
  }
  const canAct = q.can_jump || q.can_remove || q.can_move;
  if (!q.items.length) {
    return (
      <div className="mu-empty">
        <IconQueue size={36} />
        <b>The queue is empty</b>
        <button className="btn" onClick={onLibrary}>Find something to play</button>
      </div>
    );
  }
  const more = q.full && q.current != null ? q.total - (q.current + q.items.length) : 0;
  return (
    <div className="mu-list">
      {current && <>
        <h3 className="mu-h">Now playing</h3>
        <TrackRow t={current} />
      </>}
      {next.length > 0 && <h3 className="mu-h">Up next{q.full && q.total ? <span> · {q.total - (q.current ?? -1) - 1} tracks</span> : null}</h3>}
      {next.map((t) => <TrackRow key={t.key} t={t} onClick={canAct ? () => setPick(t) : undefined} />)}
      {more > 0 && <p className="mu-note">and {more} more</p>}
      {!q.full && q.source === "music_assistant" && (
        <p className="mu-note">Home Assistant only says what's on now and next. Connect Music Assistant in Settings › Music to see and change the whole queue.</p>
      )}
      {pick && (
        <Actions title={pick.title} sub={pick.artist} onClose={() => setPick(null)} actions={[
          q.can_jump && { label: "Play now", icon: <IconPlay size={22} />, run: () => act(pick, "play") },
          q.can_move && { label: "Play next", icon: <IconPlayNext size={22} />, run: () => act(pick, "next") },
          q.can_remove && { label: "Remove from queue", icon: <IconTrash size={22} />, run: () => act(pick, "remove"), danger: true },
        ]} />
      )}
    </div>
  );
}

function TrackRow({ t, onClick }: { t: QueueTrack; onClick?: () => void }) {
  return (
    <button type="button" className={"mu-track" + (t.current ? " on" : "")} onClick={onClick} disabled={!onClick && !t.current}>
      <Thumb src={t.thumb} />
      <span className="mu-track-text"><b>{t.title || "Unknown track"}</b>{(t.artist || t.album) && <span>{[t.artist, t.album].filter(Boolean).join(" · ")}</span>}</span>
      {t.current ? <span className="ss-np-eq" aria-label="Playing"><i /><i /><i /></span>
        : t.duration ? <span className="mu-dur">{fmtDuration(t.duration)}</span> : null}
      {onClick && <IconMore size={20} className="mu-more" />}
    </button>
  );
}

function Thumb({ src, round }: { src: string | null; round?: boolean }) {
  const [failed, setFailed] = useState<string | null>(null);
  return (
    <span className={"mu-thumb" + (round ? " round" : "")}>
      {src && failed !== src ? <img src={src} alt="" loading="lazy" draggable={false} onError={() => setFailed(src)} /> : <IconMusic size={18} />}
    </span>
  );
}

// ---------------------------------------------------------------- Library

interface Crumb { id: string; type: string; title: string }
const FIRST = ["albums", "playlists", "podcasts", "radio", "artists", "audiobooks", "tracks"];
const CONTAINERS = new Set(["album", "playlist", "podcast", "artist", "audiobook", "directory", "genre", "channel", "app"]);

function LibraryPane() {
  const { api, layout, toast } = useApp();
  const { np } = useMedia();
  const [root, setRoot] = useState<MediaBrowse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [path, setPath] = useState<Crumb[]>([]);
  const [page, setPage] = useState<MediaBrowse | null>(null);
  const [loading, setLoading] = useState(false);
  const [query, setQuery] = useState("");
  const [found, setFound] = useState<MediaItem[] | null>(null);
  const [pick, setPick] = useState<MediaItem | null>(null);
  const ma = !!np?.music_assistant;

  // The top level: its sections become the chips (a single folder, like a Sonos speaker's Favourites, is opened).
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        let top = await api.mediaBrowse(layout);
        if (top.items.length === 1 && top.items[0].can_expand) top = await api.mediaBrowse(layout, top.items[0].id, top.items[0].type);
        if (!alive) return;
        const order = (i: MediaItem) => { const k = FIRST.indexOf(i.id); return k < 0 ? 99 : k; };
        const items = [...top.items].sort((a, b) => order(a) - order(b));
        setRoot({ ...top, items });
        const first = items.find((i) => i.can_expand);
        if (first) setPath([{ id: first.id, type: first.type, title: first.title }]);
      } catch (e) { if (alive) setError(e instanceof ApiError ? e.message : "Couldn't open the library"); }
    })();
    return () => { alive = false; };
  }, [api, layout]);

  const here = path[path.length - 1];
  useEffect(() => {
    if (!here) return;
    let alive = true;
    setLoading(true);
    api.mediaBrowse(layout, here.id, here.type).then((p) => { if (alive) { setPage(p); setLoading(false); } })
      .catch((e) => { if (alive) { setLoading(false); toast(e instanceof ApiError ? e.message : "Couldn't open that"); setPath((x) => x.slice(0, -1)); } });
    return () => { alive = false; };
  }, [api, layout, here?.id, here?.type, toast]); // eslint-disable-line react-hooks/exhaustive-deps

  // Search as you type (Music Assistant only), a moment after the last key.
  useEffect(() => {
    const text = query.trim();
    if (!text) { setFound(null); return; }
    const t = setTimeout(() => {
      api.mediaSearch(layout, text).then(setFound).catch((e) => { setFound([]); toast(e instanceof ApiError ? e.message : "Search didn't work"); });
    }, 450);
    return () => clearTimeout(t);
  }, [api, layout, query, toast]);

  async function play(item: { id: string; type: string; title: string }, enqueue: Enqueue) {
    setPick(null);
    try {
      await api.mediaPlay(layout, item, enqueue);
      toast(enqueue === "replace" ? `Playing ${item.title}` : enqueue === "next" ? `${item.title} plays next` : `${item.title} added to the queue`);
    } catch (e) { toast(e instanceof ApiError ? e.message : "Couldn't play that"); }
  }
  const open = (i: MediaItem) => {
    if (i.can_expand) { setQuery(""); setPath((p) => [...p, { id: i.id, type: i.type, title: i.title }]); }
    else if (i.can_play) setPick(i);
  };

  if (error) return <p className="mu-note">{error}</p>;
  if (!root) return <p className="mu-note">Loading…</p>;
  const chips = root.items.filter((i) => i.can_expand);
  const searching = found !== null;
  const items = searching ? found : page?.id === here?.id ? page.items : [];
  const deep = path.length > 1 && !searching;
  return (
    <div className="mu-lib">
      {ma && (
        <label className="mu-search">
          <IconSearch size={20} />
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search albums, artists, playlists, podcasts…" enterKeyHint="search" />
          {query && <button type="button" aria-label="Clear" onClick={() => setQuery("")}><IconClose size={18} /></button>}
        </label>
      )}
      {!searching && !deep && chips.length > 1 && (
        <div className="mu-chips">
          {chips.map((c) => (
            <button key={c.id} className={"chip-btn" + (here?.id === c.id ? " on" : "")} onClick={() => setPath([{ id: c.id, type: c.type, title: c.title }])}>{c.title}</button>
          ))}
        </div>
      )}
      {deep && page && page.id === here.id && (
        <div className="mu-head">
          <button className="icon-btn" aria-label="Back" onClick={() => setPath((p) => p.slice(0, -1))}><IconLeft /></button>
          <Thumb src={page.thumb} />
          <div className="mu-head-text"><b>{page.title}</b>{page.subtitle && <span>{page.subtitle}</span>}</div>
          {page.can_play && <div className="mu-head-btns">
            <button className="btn small" onClick={() => play({ ...page, title: page.title }, "replace")}><IconPlay size={18} /> Play</button>
            <button className="btn small ghost" onClick={() => play(page, "next")}><IconPlayNext size={18} /> Next</button>
            <button className="btn small ghost" onClick={() => play(page, "add")}><IconPlus size={18} /> Queue</button>
          </div>}
        </div>
      )}
      {deep && (!page || page.id !== here.id) && (
        <div className="mu-head"><button className="icon-btn" aria-label="Back" onClick={() => setPath((p) => p.slice(0, -1))}><IconLeft /></button><b>{here.title}</b></div>
      )}
      <div className="mu-scroll">
        {loading && !searching && !items.length && <p className="mu-note">Loading…</p>}
        {!loading && !items.length && <p className="mu-note">{searching ? "Nothing found." : "Nothing here yet."}</p>}
        <Grid items={items.filter(isTile)} onOpen={open} onMore={setPick} />
        {items.some((i) => !isTile(i)) && (
          <div className="mu-list">
            {items.filter((i) => !isTile(i)).map((i, k) => (
              <button type="button" key={i.id + k} className="mu-track" onClick={() => open(i)}>
                <Thumb src={i.thumb} />
                <span className="mu-track-text"><b>{i.title}</b>{i.subtitle && <span>{i.subtitle}</span>}</span>
                {i.can_play && <IconMore size={20} className="mu-more" />}
              </button>
            ))}
          </div>
        )}
        {!searching && page && page.more > 0 && <p className="mu-note">and {page.more} more: search to find them</p>}
      </div>
      {pick && (
        <Actions title={pick.title} sub={pick.subtitle} thumb={pick.thumb} onClose={() => setPick(null)} actions={[
          { label: "Play now", icon: <IconPlay size={22} />, run: () => play(pick, "replace") },
          { label: "Play next", icon: <IconPlayNext size={22} />, run: () => play(pick, "next") },
          { label: "Add to queue", icon: <IconPlus size={22} />, run: () => play(pick, "add") },
          pick.can_expand && { label: "Open", icon: <IconMore size={22} />, run: () => { setPick(null); open({ ...pick, can_play: false }); } },
        ]} />
      )}
    </div>
  );
}

/** Albums, playlists, podcasts... are tiles with art; tracks and episodes are rows. */
const isTile = (i: MediaItem) => i.can_expand || CONTAINERS.has(i.kind) || i.kind === "radio" || i.type === "radio";

function Grid({ items, onOpen, onMore }: { items: MediaItem[]; onOpen: (i: MediaItem) => void; onMore: (i: MediaItem) => void }) {
  if (!items.length) return null;
  return (
    <div className="mu-grid">
      {items.map((i, k) => (
        <div key={i.id + k} className="mu-tile">
          <div className="mu-tile-cover">
            <button type="button" className="mu-tile-art" onClick={() => onOpen(i)} aria-label={i.title}>
              <Thumb src={i.thumb} round={i.kind === "artist"} />
            </button>
            {i.can_play && <button type="button" className="mu-tile-play" aria-label={`Play ${i.title}`} onClick={() => onMore(i)}><IconPlay size={20} /></button>}
          </div>
          <button type="button" className="mu-tile-text" onClick={() => onOpen(i)}>
            <b>{i.title}</b>{i.subtitle && <span>{i.subtitle}</span>}
          </button>
        </div>
      ))}
    </div>
  );
}

interface Action { label: string; icon: ReactNode; run: () => void; danger?: boolean }

function Actions({ title, sub, thumb, actions, onClose }: {
  title: string; sub?: string | null; thumb?: string | null; actions: (Action | false)[]; onClose: () => void;
}) {
  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);
  return (
    <div className="scrim" onClick={onClose}>
      <div className="sheet mu-actions" onClick={(e) => e.stopPropagation()} role="dialog" aria-label={title}>
        <div className="mu-actions-head">
          {thumb !== undefined && <Thumb src={thumb} />}
          <div className="mu-track-text"><b>{title}</b>{sub && <span>{sub}</span>}</div>
          <button className="icon-btn" onClick={onClose} aria-label="Close"><IconClose /></button>
        </div>
        {actions.filter((a): a is Action => !!a).map((a) => (
          <button key={a.label} className={"mu-action" + (a.danger ? " danger" : "")} onClick={a.run}>{a.icon}{a.label}</button>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- Rooms

function RoomsPane() {
  const { api, layout, toast } = useApp();
  const [rooms, error, reload] = useMediaData<MediaRooms>(() => api.mediaRooms(layout), [api, layout]);
  const [busy, setBusy] = useState<string | null>(null);
  const [local, setLocal] = useState<MediaRooms | null>(null);
  useEffect(() => setLocal(null), [rooms]);
  const r = local ?? rooms;
  if (!r) return error ? <p className="mu-note">{error}</p> : <p className="mu-note">Loading…</p>;
  async function act(room: string, action: "join" | "unjoin" | "volume" | "mute", value?: number | boolean) {
    if (action === "join" || action === "unjoin") setBusy(room);
    try { setLocal(await api.mediaRoomAction(layout, room, action, value)); }
    catch (e) { toast(e instanceof ApiError ? e.message : "The speaker didn't respond"); reload(); }
    finally { setBusy(null); }
  }
  const others = r.rooms.filter((x) => !x.this);
  return (
    <div className="mu-list mu-rooms">
      {!r.can_group && <p className="mu-note">This speaker can't play in a group from Moonlight. Each room's volume still works.</p>}
      {r.can_group && others.length === 0 && <p className="mu-note">No other speakers it can play with were found in Home Assistant.</p>}
      {r.rooms.map((x) => (
        <div key={x.entity_id} className={"mu-room" + (x.grouped ? " on" : "")}>
          <div className="mu-room-top">
            <span className="mu-room-name"><b>{x.name}</b>
              <span>{x.this ? "This screen's speaker" : x.playing ? `Playing ${x.playing}` : x.grouped ? "In this group" : x.state === "off" ? "Off" : "Not playing"}</span></span>
            {!x.this && r.can_group && (
              <button className={"mu-join" + (x.grouped ? " on" : "")} disabled={busy === x.entity_id}
                onClick={() => act(x.entity_id, x.grouped ? "unjoin" : "join")}>
                {x.grouped ? <><IconCheck size={18} /> In group</> : <><IconPlus size={18} /> Add</>}
              </button>
            )}
          </div>
          {x.can_volume && x.volume != null && (
            <VolumeSlider volume={x.volume} muted={!!x.muted} canMute label={`${x.name} volume`}
              onSet={(v) => act(x.entity_id, "volume", v)} onMute={(m) => act(x.entity_id, "mute", m)} />
          )}
        </div>
      ))}
    </div>
  );
}

