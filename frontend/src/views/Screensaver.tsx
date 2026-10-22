import { CSSProperties, MutableRefObject, PointerEvent, ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { PhotoAlbum, SlidePhoto } from "../api/types";
import { addDays, fmtFull, fmtTime, isoDT, parse, today } from "../dates";
import { useApp, useData, useNow } from "../state";
import { ApiError } from "../api/types";
import { IconCamera, IconDrop, IconEyeOff, IconPhotos, WeatherIcon } from "../components/icons";
import { ScreensaverNowPlaying, useMedia } from "./NowPlaying";
import { alertTitle, useSaverCamera } from "./SecurityAlerts";
import { CameraVideo } from "./SecurityView";

// Fallback "photos": painted scenes, shown when Immich isn't set up, nothing is chosen or Immich can't be reached.
const SCENES = [
  { sky: ["#1B2A4A", "#4B3F72", "#E58A6B"], hills: ["#2D2240", "#3C2E52", "#4D3B63"], sun: "#FFD6A0", y: 62 },
  { sky: ["#8EC5FC", "#B7D8F5", "#F3E7D3"], hills: ["#5E8C61", "#76A36B", "#9BBF7D"], sun: "#FFF4D6", y: 30 },
  { sky: ["#0F1C3F", "#1E3166", "#355C8C"], hills: ["#0B1530", "#14224A", "#1C2E5C"], sun: "#F4F1E6", y: 25 },
  { sky: ["#F6D365", "#FDA085", "#F38181"], hills: ["#8E4B5B", "#A65C66", "#C07A72"], sun: "#FFF1C9", y: 55 },
  { sky: ["#A1C4FD", "#C2E9FB", "#E8F6F8"], hills: ["#3E7C8C", "#5698A3", "#7DB5B8"], sun: "#FFFFFF", y: 22 },
];

function Scene({ s }: { s: (typeof SCENES)[number] }) {
  return (
    <svg viewBox="0 0 1600 900" preserveAspectRatio="xMidYMid slice" className="ss-scene">
      <defs>
        <linearGradient id={`sky${s.y}`} x1="0" y1="0" x2="0" y2="1">
          {s.sky.map((c, i) => <stop key={i} offset={i / (s.sky.length - 1)} stopColor={c} />)}
        </linearGradient>
      </defs>
      <rect width="1600" height="900" fill={`url(#sky${s.y})`} />
      <circle cx="1150" cy={s.y * 9} r="70" fill={s.sun} opacity=".9" />
      <path d="M0 620 C 250 520 450 560 700 600 S 1200 520 1600 580 V900 H0z" fill={s.hills[2]} />
      <path d="M0 700 C 300 640 500 700 800 690 S 1300 620 1600 680 V900 H0z" fill={s.hills[1]} />
      <path d="M0 790 C 400 740 700 800 1000 780 S 1400 750 1600 770 V900 H0z" fill={s.hills[0]} />
    </svg>
  );
}

const REFETCH_MS = 10 * 60_000; // the server refreshes its Immich list every few minutes

export function Screensaver({ onWake }: { onWake: () => void }) {
  const { api, settings } = useApp();
  const now = useNow(10000);
  const seconds = Math.max(3, settings?.screensaver_seconds ?? 10);
  const [broken, setBroken] = useState(""); // the photo list whose images wouldn't load (Immich down)
  const [data, reload] = useData((api) => api.screensaverPhotos(), ["photos"], []);
  useEffect(() => {
    const t = setInterval(() => { setBroken(""); reload(); }, REFETCH_MS); // also retry photos that failed to load
    return () => clearInterval(t);
  }, [reload]);
  const albums = useMemo(() => albumsOf(data?.photos ?? [], data?.albums), [data]);
  const listKey = albums.map((a) => `${a.id}:${a.photos.map((p) => p.id).join()}`).join("|");
  const usePhotos = albums.length > 0 && broken !== listKey;
  const [shown, setShown] = useState<SlidePhoto | null>(null);
  const [album, setAlbum] = useState<{ name: string; at: number } | null>(null);
  const t = today();
  const [events] = useData((api) => api.events(t, addDays(t, 2)), ["events"], [t]);
  const [weather] = useData((api) => api.weather(), ["settings"], []);
  const nowS = isoDT(now);
  const next = (events ?? []).find((e) => !e.all_day && e.start > nowS);
  const { np } = useMedia();
  const music = !!np?.show;
  const day = weather?.daily.find((d) => d.date === t);
  const cam = useSaverCamera(); // someone at a camera: its video takes the photo's place until they've gone
  const [hiding, setHiding] = useState<SlidePhoto | null>(null); // asking "hide this photo?"; the slideshow waits
  const [note, setNote] = useState<{ text: string; at: number } | null>(null);
  // Swipe left for the next photo, right for the one before; a tap (no swipe) still wakes the screen.
  const skip = useRef<((step: 1 | -1) => void) | null>(null);
  const touch = useRef<{ x: number; y: number; swiped: boolean } | null>(null);
  const onDown = (e: PointerEvent) => {
    const onControl = (e.target as HTMLElement).closest("button, input, a, .ss-np");
    touch.current = onControl ? null : { x: e.clientX, y: e.clientY, swiped: false };
  };
  const onUp = (e: PointerEvent) => {
    const t0 = touch.current;
    if (!t0) return;
    const dx = e.clientX - t0.x, dy = e.clientY - t0.y;
    if (Math.abs(dx) > 60 && Math.abs(dx) > 1.5 * Math.abs(dy) && !cam && usePhotos && !hiding) {
      t0.swiped = true;
      skip.current?.(dx < 0 ? 1 : -1);
    }
  };
  const onClick = () => {
    const swiped = touch.current?.swiped;
    touch.current = null;
    if (!swiped) onWake();
  };
  const hide = async (photo: SlidePhoto) => {
    setHiding(null);
    try {
      const r = await api.hidePhoto(photo.id);
      forget(photo.id, albums);
      setShown(null);
      const out = r.removed.length ? ` · taken out of ${names(r.removed)} in Immich` : "";
      const kept = r.failed.length ? ` · still in ${names(r.failed)} (${r.failed[0].error})` : "";
      setNote({ text: `Photo hidden${out}${kept}`, at: Date.now() });
    } catch (e) {
      setNote({ text: e instanceof ApiError ? `Couldn't hide it: ${e.message}` : "Couldn't hide the photo", at: Date.now() });
    }
  };
  return (
    <div className="screensaver" onPointerDown={onDown} onPointerUp={onUp} onClick={onClick} onDragStart={(e) => e.preventDefault()}>
      {data && (usePhotos
        ? <PhotoShow key={listKey} albums={albums} seconds={seconds} paused={!!hiding} skip={skip} onFail={() => setBroken(listKey)} onShow={setShown}
            onAlbum={(name) => setAlbum({ name, at: Date.now() })} />
        : <SceneShow seconds={seconds} />)}
      {cam && <div className="ss-cam"><CameraVideo key={cam.camera} cam={cam} width={1920} fit="contain" /></div>}
      <div className="ss-shade" />
      {cam && <div className="ss-cam-label"><span className="sec-live-dot" />{alertTitle(cam)}</div>}
      {!cam && usePhotos && shown && (
        <div className="ss-tr">{/* the photo's details, and under them the button to hide it */}
          {settings?.photo_details !== false && <PhotoCaption photo={shown} />}
          <button className="ss-hide" aria-label="Don't show this photo again" onClick={(e) => { e.stopPropagation(); setHiding(shown); }}>
            <IconEyeOff size={24} />
          </button>
        </div>
      )}
      {!cam && usePhotos && album && !note && <AlbumToast key={album.at} name={album.name} />}
      {note && <AlbumToast key={note.at} name={note.text} icon={<IconEyeOff size={22} />} onDone={() => setNote(null)} />}
      {hiding && <HideConfirm photo={hiding} albums={albums} onHide={() => hide(hiding)} onCancel={() => setHiding(null)} />}
      <div className="ss-info">
        {weather && <div className="ss-wx">
          <WeatherIcon condition={weather.current.condition} size={44} /> {weather.current.temp}°
          {day && <span className="ss-hilo">{day.high}° / {day.low}°{!!day.rain && <> · <IconDrop size={18} />{day.rain}%</>}</span>}
        </div>}
        <div className="ss-time">{now.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })}</div>
        <div className="ss-date">{fmtFull(t)}</div>
      </div>
      <div className="ss-right">
        {music && <ScreensaverNowPlaying />}
        {next && <div className="ss-next">Next: <b>{next.title}</b> at {fmtTime(next.start)}</div>}
      </div>
    </div>
  );
}

/** When and where the photo on screen was taken, small at the top right: "14 July 2025 · 3:30pm", the place
 * underneath, and a camera beside them so it reads as the photo's details rather than today's. */
function PhotoCaption({ photo }: { photo: SlidePhoto }) {
  // Immich's local time is the wall clock where the photo was taken; use its digits as they are.
  const taken = photo.taken_at?.match(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/)?.[0];
  const when = taken && `${parse(taken).toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" })} · ${fmtTime(taken)}`;
  if (!when && !photo.place) return null;
  return (
    <div key={photo.id} className="ss-caption">
      <span className="ss-cap-text">{when && <span>{when}</span>}{photo.place && <span>{photo.place}</span>}</span>
      <IconCamera size={22} />
    </div>
  );
}

/** The album's name, for a few seconds when the screensaver starts and when it moves on to another album. */
function AlbumToast({ name, icon, onDone }: { name: string; icon?: ReactNode; onDone?: () => void }) {
  const [on, setOn] = useState(true);
  const done = useRef(onDone);
  done.current = onDone;
  useEffect(() => { const t = setTimeout(() => { setOn(false); done.current?.(); }, 5000); return () => clearTimeout(t); }, []);
  return on ? <div className="ss-album" role="status">{icon ?? <IconPhotos size={22} />} {name}</div> : null;
}

const names = (xs: { name: string }[]) => xs.map((x) => x.name).join(", ");
/** The real Immich albums a photo is playing from (not favourites or "on this day"); it may be in others too. */
const albumsWith = (id: string, albums: Album[]) =>
  albums.filter((a) => a.id !== "favorites" && a.id !== "on-this-day" && a.photos.some((p) => p.id === id));

/** "Hide this photo?" over the screensaver. Taps stay inside it, so answering doesn't wake the screen; it gives up
 * after half a minute if nobody answers. */
function HideConfirm({ photo, albums, onHide, onCancel }: { photo: SlidePhoto; albums: Album[]; onHide: () => void; onCancel: () => void }) {
  const from = albumsWith(photo.id, albums);
  const cancel = useRef(onCancel);
  cancel.current = onCancel;
  useEffect(() => { const t = setTimeout(() => cancel.current(), 30_000); return () => clearTimeout(t); }, []);
  return (
    <div className="ss-confirm-bg" onClick={(e) => { e.stopPropagation(); onCancel(); }}>
      <div className="ss-confirm" role="dialog" aria-label="Hide this photo?" onClick={(e) => e.stopPropagation()}>
        <img src={photo.url} alt="" />
        <div>
          <b>Hide this photo?</b>
          <p>It won't be shown on the screens again, and it's taken out of every Immich album it's in
            {from.length ? <>, including <b>{names(from)}</b></> : null}.
          </p>
          <div className="ss-confirm-btns">
            <button className="btn ghost" onClick={onCancel}>Cancel</button>
            <button className="btn danger-fill" onClick={onHide}><IconEyeOff size={20} /> Hide photo</button>
          </div>
        </div>
      </div>
    </div>
  );
}

/** Keep this screen's place in the album when a photo before it is hidden, so it doesn't skip the next one. */
function forget(id: string, albums: Album[]) {
  const place = loadPlace();
  const i = albums.find((a) => a.id === place.album)?.photos.findIndex((p) => p.id === id) ?? -1;
  if (i >= 0 && place.next !== undefined && i < place.next) savePlace({ ...place, next: place.next - 1 });
}

function SceneShow({ seconds }: { seconds: number }) {
  const [i, setI] = useState(0);
  useEffect(() => { const t = setInterval(() => setI((x) => x + 1), seconds * 1000); return () => clearInterval(t); }, [seconds]);
  return <>{SCENES.map((s, k) => <div key={k} className={"ss-slide" + (k === i % SCENES.length ? " on" : "")}><Scene s={s} /></div>)}</>;
}

interface Album { id: string; name: string; updated_at: string | null; photos: SlidePhoto[] }

/** The albums to play, with their photos. A server older than 0.5.3 sends no albums: then all photos, shuffled, as one. */
function albumsOf(photos: SlidePhoto[], albums: PhotoAlbum[] | undefined): Album[] {
  if (!albums) return photos.length ? [{ id: "photos", name: "Photos", updated_at: null, photos: shuffle(photos) }] : [];
  const byId = new Map(photos.map((p) => [p.id, p]));
  return albums.map((a) => ({ ...a, photos: a.photos.map((id) => byId.get(id)).filter((p): p is SlidePhoto => !!p) }))
    .filter((a) => a.photos.length);
}

function shuffle<T>(xs: T[]): T[] {
  const a = [...xs];
  for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; }
  return a;
}

// Where this screen is up to, so the slideshow carries on after the screen is used or turned off.
const PLACE_KEY = "moonlight.screensaver";
interface Place { album?: string; next?: number; recent?: string[]; memories?: string }
function loadPlace(): Place {
  try { return JSON.parse(localStorage.getItem(PLACE_KEY) ?? "{}") ?? {}; } catch { return {}; }
}
function savePlace(p: Place) {
  try { localStorage.setItem(PLACE_KEY, JSON.stringify(p)); } catch { /* storage blocked */ }
}

/** The next album: "on this day" first each day, then at random with recently changed albums far more likely
 * (one changed today is about 10 times as likely as one last changed a year ago), never one of the last few shown. */
export function pickAlbum(albums: Album[], place: Place, day: string, now = Date.now()): Album {
  const memories = albums.find((a) => a.id === "on-this-day");
  if (memories && place.memories !== day) return memories;
  const k = Math.min(3, albums.length - 1);
  const avoid = new Set(k > 0 ? (place.recent ?? []).slice(-k) : []);
  const pool = albums.filter((a) => !avoid.has(a.id));
  const weight = (a: Album) => {
    if (a.id === "on-this-day") return 1.5;
    const t = a.updated_at ? Date.parse(a.updated_at) : NaN;
    const days = Number.isNaN(t) ? 180 : Math.max(0, (now - t) / 86_400_000);
    return Math.max(0.04, 1 / (1 + days / 40));
  };
  const w = pool.map(weight);
  let r = Math.random() * w.reduce((x, y) => x + y, 0);
  for (let i = 0; i < pool.length; i++) { r -= w[i]; if (r <= 0) return pool[i]; }
  return pool[pool.length - 1];
}

interface Slide { key: number; photo: SlidePhoto; aspect: number; quick?: boolean }

/** Load and decode an image; resolves with its aspect ratio (from the pixels, so EXIF rotation is already in it). */
function load(url: string): Promise<number> {
  const img = new Image();
  img.src = url;
  return img.decode().then(() => img.naturalWidth / Math.max(1, img.naturalHeight));
}

/** Immich photos, one whole album at a time (oldest photo first), crossfading, with a slow Ken Burns zoom (off for
 * prefers-reduced-motion). Carries on where this screen was up to; `onAlbum` names the album when it starts.
 * A photo that won't load is skipped; if several in a row fail, `onFail` hands back to the painted scenes. */
function PhotoShow({ albums: list, seconds, paused, skip, onFail, onShow, onAlbum }: {
  albums: Album[]; seconds: number; paused: boolean; skip: MutableRefObject<((step: 1 | -1) => void) | null>;
  onFail: () => void; onShow: (p: SlidePhoto) => void; onAlbum: (name: string) => void;
}) {
  const pausedRef = useRef(paused);
  pausedRef.current = paused;
  const box = useRef<HTMLDivElement>(null);
  const [albums] = useState(list); // keyed by the list's ids, so a refetch doesn't restart it
  const [slides, setSlides] = useState<Slide[]>([]);
  const albumRef = useRef(onAlbum);
  albumRef.current = onAlbum;
  const failRef = useRef(onFail);
  failRef.current = onFail;
  const showRef = useRef(onShow);
  showRef.current = onShow;
  useEffect(() => {
    let alive = true, failures = 0, busy = false, shown = false, named = "";
    const total = albums.reduce((n, a) => n + a.photos.length, 0);
    const giveUp = Math.min(3, total);
    const place = loadPlace();
    let album = albums.find((a) => a.id === place.album);
    let n = place.next ?? 0;
    // What this screen has shown since the screensaver started, so a swipe back can go over them again.
    const trail: [Album, SlidePhoto][] = [];
    let at = -1;
    const nextPhoto = (): [Album, SlidePhoto] => {
      if (!album || n >= album.photos.length) { // finished that album (or none yet): choose another
        const day = today();
        album = pickAlbum(albums, place, day);
        n = 0;
        place.recent = [...(place.recent ?? []).filter((id) => id !== album!.id), album.id].slice(-10);
        if (album.id === "on-this-day") place.memories = day;
      }
      const photo = album.photos[n++];
      savePlace({ ...place, album: album.id, next: n });
      return [album, photo];
    };
    // Swap only once the next photo is decoded, so the crossfade never shows a half-loaded image.
    const advance = (step: 1 | -1 = 1, quick = false) => {
      if (busy || !alive || at + step < 0) return;
      busy = true;
      at += step;
      if (at === trail.length) trail.push(nextPhoto()); // past the end of what's been shown: carry on as usual
      const [from, photo] = trail[at];
      if (trail.length > 200) { trail.shift(); at--; }
      load(photo.url).then((aspect) => {
        failures = 0;
        shown = true;
        busy = false;
        if (!alive) return;
        setSlides((s) => [...s.slice(-1), { key: Date.now(), photo, aspect, quick }]);
        showRef.current(photo);
        if (named !== from.id) { named = from.id; albumRef.current(from.name); }
      }, () => {
        busy = false;
        if (++failures >= giveUp) { if (alive) failRef.current(); }
        else if (!shown) advance(); // nothing on screen yet: try the next one straight away
        else if (quick) advance(step, true); // a swipe skips a photo that won't load
      });
    };
    advance();
    if (total < 2) return () => { alive = false; skip.current = null; };
    let t = setInterval(() => { if (!pausedRef.current) advance(); }, seconds * 1000);
    skip.current = (step) => { // a swipe: show that photo now, and give it the full time on screen
      advance(step, true);
      clearInterval(t);
      t = setInterval(() => { if (!pausedRef.current) advance(); }, seconds * 1000);
    };
    return () => { alive = false; clearInterval(t); skip.current = null; };
  }, [albums, seconds, skip]);
  const el = box.current;
  const screenAspect = el && el.clientHeight ? el.clientWidth / el.clientHeight : window.innerWidth / Math.max(1, window.innerHeight);
  return (
    <div className="ss-photos" ref={box}>
      {slides.map((s, i) => {
        // A photo much taller (or wider) than the screen is shown whole over a blurred copy of itself.
        const fit = Math.max(s.aspect / screenAspect, screenAspect / s.aspect) > 1.4 ? "contain" : "cover";
        const style = { "--kb": `${seconds + 2}s`, "--ox": `${(s.key % 3) * 50}%`, "--oy": `${(s.key % 2) * 100}%` } as CSSProperties;
        return (
          <div key={s.key} className={`ss-photo ${fit}` + (i === slides.length - 1 ? " top" : "") + (s.quick ? " quick" : "")} style={style}>
            {fit === "contain" && <img className="ss-blur" src={s.photo.url} alt="" />}
            <img className="ss-img" src={s.photo.url} alt="" />
          </div>
        );
      })}
    </div>
  );
}
