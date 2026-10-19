import { useCallback, useEffect, useState } from "react";
import { Api, NurseryConfig, NurseryUpdate } from "../api/types";
import { useApp } from "../state";
import { diffDays, fmtDayMonth, fmtDow, fmtTime, relativeDay, today } from "../dates";
import { Empty, Sheet } from "../components/ui";
import { IconClose, IconLeft, IconNursery, IconRight } from "../components/icons";

// Nursery updates from Tapestry: a section on the large screens, a button in the top bar on the smaller ones. Each
// device remembers the newest update it has shown, so the others can say how many are new.
const SEEN_KEY = "moonlight.nursery.seen";
const FIRST_DAYS = 3; // on a device that has never opened them, updates from the last few days count as new

function readSeen(): string {
  try { const v = localStorage.getItem(SEEN_KEY); if (v) return v; } catch { /* private mode */ }
  const d = new Date(Date.now() - FIRST_DAYS * 86400000);
  return d.toISOString().slice(0, 10);
}

export interface NurseryFeed {
  config: NurseryConfig | null;
  updates: NurseryUpdate[];
  /** Updates newer than the last one shown on this device. */
  unread: number;
  markSeen: () => void;
}

export function useNurseryFeed(api: Api): NurseryFeed {
  const [config, setConfig] = useState<NurseryConfig | null>(null);
  const [updates, setUpdates] = useState<NurseryUpdate[]>([]);
  const [seen, setSeen] = useState(readSeen);
  useEffect(() => {
    const load = () => {
      api.nursery().then((c) => {
        setConfig(c);
        if (c.configured) api.nurseryUpdates().then(setUpdates).catch((e) => console.error(e));
        else setUpdates([]);
      }).catch(() => setConfig(null));
    };
    load();
    return api.subscribe((t) => { if (t === "nursery") load(); });
  }, [api]);
  const unread = updates.filter((u) => u.date > seen).length;
  const markSeen = useCallback(() => {
    const newest = updates[0]?.date;
    if (!newest || newest <= seen) return;
    setSeen(newest);
    try { localStorage.setItem(SEEN_KEY, newest); } catch { /* private mode */ }
  }, [updates, seen]);
  return { config, updates, unread, markSeen };
}

/** "Today, 10:30am", "Yesterday", "Mon 13 Oct, 2pm". */
export function whenText(date: string): string {
  const day = date.slice(0, 10);
  const ago = diffDays(today(), day);
  const dayText = ago === 0 || ago === 1 ? relativeDay(day) : `${fmtDow(day)} ${fmtDayMonth(day)}`;
  return date.length > 10 && date.slice(11, 16) !== "00:00" ? `${dayText}, ${fmtTime(date)}` : dayText;
}

function Kids({ update }: { update: NurseryUpdate }) {
  if (!update.children.length) return null;
  return (
    <span className="ns-kids">
      {update.children.map((k) => (
        <span key={k.name} className="ns-kid" style={k.color ? { background: k.color, color: "#fff" } : undefined}>
          {k.name.split(" ")[0]}
        </span>
      ))}
    </span>
  );
}

/** One update in full: words, photos (tap for full screen) and comments. */
function Detail({ update, onPhoto }: { update: NurseryUpdate; onPhoto: (u: NurseryUpdate, i: number) => void }) {
  return (
    <article className="ns-detail">
      <div className="ns-meta"><Kids update={update} /><span>{whenText(update.date)}{update.author && ` · ${update.author}`}</span></div>
      <h2 className="ns-title">{update.title}</h2>
      {update.notes && <p className="ns-notes">{update.notes}</p>}
      {update.photos.length > 0 && (
        <div className={"ns-photos n" + Math.min(update.photos.length, 4)}>
          {update.photos.map((p, i) => (
            <button key={p.url} className="ns-photo" onClick={() => onPhoto(update, i)} aria-label={`Photo ${i + 1}`}>
              <img src={p.url} alt="" loading="lazy" />
              {p.video && <span className="ns-video" aria-label="Video">▶</span>}
            </button>
          ))}
        </div>
      )}
      {update.comments.length > 0 && (
        <div className="ns-comments">
          {update.comments.map((c, i) => (
            <div key={i} className="ns-comment"><b>{c.author || "Comment"}</b> {c.text}</div>
          ))}
        </div>
      )}
    </article>
  );
}

/** Every update one under the other (the smaller screens). */
function Feed({ updates, onPhoto }: { updates: NurseryUpdate[]; onPhoto: (u: NurseryUpdate, i: number) => void }) {
  return (
    <div className="ns-feed">
      {updates.map((u) => <div key={u.id} className="ns-card"><Detail update={u} onPhoto={onPhoto} /></div>)}
    </div>
  );
}

/** A photo filling the screen; tap the sides or swipe to move through the update's photos. */
function Lightbox({ update, start, onClose }: { update: NurseryUpdate; start: number; onClose: () => void }) {
  const [i, setI] = useState(start);
  const n = update.photos.length;
  const step = useCallback((d: number) => setI((x) => (x + d + n) % n), [n]);
  useEffect(() => {
    const k = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); if (e.key === "ArrowRight") step(1); if (e.key === "ArrowLeft") step(-1); };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose, step]);
  const [x0, setX0] = useState<number | null>(null);
  const photo = update.photos[i];
  return (
    <div className="ns-lightbox" onClick={onClose}
      onPointerDown={(e) => setX0(e.clientX)}
      onPointerUp={(e) => { if (x0 !== null && Math.abs(e.clientX - x0) > 50) { e.stopPropagation(); step(e.clientX < x0 ? 1 : -1); } setX0(null); }}>
      <img src={photo.url} alt="" onClick={(e) => e.stopPropagation()} draggable={false} />
      <div className="ns-lb-cap" onClick={(e) => e.stopPropagation()}>
        <b>{update.title}</b><span>{whenText(update.date)}{n > 1 && ` · ${i + 1} of ${n}`}{photo.video && " · a still from a video, which plays in the Tapestry app"}</span>
      </div>
      <button className="icon-btn ns-lb-close" onClick={onClose} aria-label="Close"><IconClose /></button>
      {n > 1 && <>
        <button className="icon-btn ns-lb-prev" onClick={(e) => { e.stopPropagation(); step(-1); }} aria-label="Previous photo"><IconLeft /></button>
        <button className="icon-btn ns-lb-next" onClick={(e) => { e.stopPropagation(); step(1); }} aria-label="Next photo"><IconRight /></button>
      </>}
    </div>
  );
}

function Status({ config }: { config: NurseryConfig }) {
  if (config.status === "auth_failed") return <div className="connect-error">Tapestry stopped accepting the login. Update it in Settings › Nursery.</div>;
  if (config.status === "error" && config.last_error) return <div className="ns-stale">Couldn't check Tapestry just now. Showing the updates already here.</div>;
  return null;
}

function NotConnected() {
  const { go } = useApp();
  return (
    <Empty>
      <IconNursery size={48} />
      <p>Nursery updates from Tapestry show here once Tapestry is connected.</p>
      <button className="btn" onClick={() => go("settings")}>Open Settings</button>
    </Empty>
  );
}

/** The large screens' Nursery section: the updates down the side, the chosen one in full. */
export function NurseryView({ feed }: { feed: NurseryFeed }) {
  const { config, updates, markSeen } = feed;
  const { layout } = useApp();
  const [pick, setPick] = useState<string | null>(null);
  const [photo, setPhoto] = useState<{ u: NurseryUpdate; i: number } | null>(null);
  useEffect(() => { markSeen(); }, [markSeen]);
  const chosen = updates.find((u) => u.id === pick) ?? updates[0];
  const fresh = updates.filter((u) => u.date.slice(0, 10) === today()).length;
  return (
    <div className="nursery">
      <div className="toolbar"><div className="toolbar-l">
        <h1 className="toolbar-title">Nursery{config?.school_name && <span className="sub">{config.school_name}</span>}</h1>
      </div>{fresh > 0 && <div className="toolbar-r"><span className="ns-today">{fresh} today</span></div>}</div>
      {config && <Status config={config} />}
      {!config?.configured ? <NotConnected /> : !updates.length ? <Empty>No updates from nursery yet.</Empty> : layout !== "large" ? (
        <div className="ns-scroll"><Feed updates={updates} onPhoto={(u, i) => setPhoto({ u, i })} /></div>
      ) : (
        <div className="ns-split">
          <div className="ns-list">
            {updates.map((u) => (
              <button key={u.id} className={"ns-item" + (u === chosen ? " on" : "")} onClick={() => setPick(u.id)}>
                {u.photos[0] ? <img className="ns-thumb" src={u.photos[0].url} alt="" loading="lazy" /> : <span className="ns-thumb none"><IconNursery size={26} /></span>}
                <span className="ns-item-text">
                  <b>{u.title}</b>
                  <span>{whenText(u.date)}</span>
                  <Kids update={u} />
                </span>
              </button>
            ))}
          </div>
          {chosen && <div className="ns-pane panel"><Detail update={chosen} onPhoto={(u, i) => setPhoto({ u, i })} /></div>}
        </div>
      )}
      {photo && <Lightbox update={photo.u} start={photo.i} onClose={() => setPhoto(null)} />}
    </div>
  );
}

/** Top-bar button on the smaller screens (shown once Tapestry is connected), with how many updates are new. */
export function NurseryButton({ feed }: { feed: NurseryFeed }) {
  const [open, setOpen] = useState(false);
  if (!feed.config?.configured) return null;
  return (
    <>
      <button className={"tb-nursery" + (feed.unread ? " new" : "")} onClick={() => setOpen(true)}
        aria-label={feed.unread ? `Nursery updates, ${feed.unread} new` : "Nursery updates"}>
        <IconNursery size={24} />
        {feed.unread > 0 && <span className="tb-badge">{feed.unread > 9 ? "9+" : feed.unread}</span>}
      </button>
      {open && <NurserySheet feed={feed} onClose={() => { feed.markSeen(); setOpen(false); }} />}
    </>
  );
}

function NurserySheet({ feed, onClose }: { feed: NurseryFeed; onClose: () => void }) {
  const [photo, setPhoto] = useState<{ u: NurseryUpdate; i: number } | null>(null);
  return (
    <Sheet wide title={<>Nursery{feed.config?.school_name && <span className="ns-sheet-sub">{feed.config.school_name}</span>}</>} onClose={onClose}>
      {feed.config && <Status config={feed.config} />}
      {!feed.updates.length ? <Empty>No updates from nursery yet.</Empty> : <Feed updates={feed.updates} onPhoto={(u, i) => setPhoto({ u, i })} />}
      {photo && <Lightbox update={photo.u} start={photo.i} onClose={() => setPhoto(null)} />}
    </Sheet>
  );
}
