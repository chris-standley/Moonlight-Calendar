import { CSSProperties, useEffect, useRef, useState } from "react";
import { SlidePhoto } from "../api/types";
import { addDays, fmtFull, fmtTime, isoDT, parse, today } from "../dates";
import { useApp, useData, useNow } from "../state";
import { IconDrop, WeatherIcon } from "../components/icons";
import { ScreensaverNowPlaying, useMedia } from "./NowPlaying";

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
  const { settings } = useApp();
  const now = useNow(10000);
  const seconds = Math.max(3, settings?.screensaver_seconds ?? 10);
  const [broken, setBroken] = useState(""); // the photo list whose images wouldn't load (Immich down)
  const [data, reload] = useData((api) => api.screensaverPhotos(), ["photos"], []);
  useEffect(() => {
    const t = setInterval(() => { setBroken(""); reload(); }, REFETCH_MS); // also retry photos that failed to load
    return () => clearInterval(t);
  }, [reload]);
  const photos = data?.photos ?? [];
  const listKey = photos.map((p) => p.id).join();
  const usePhotos = photos.length > 0 && broken !== listKey;
  const [shown, setShown] = useState<SlidePhoto | null>(null);
  const t = today();
  const [events] = useData((api) => api.events(t, addDays(t, 2)), ["events"], [t]);
  const [weather] = useData((api) => api.weather(), ["settings"], []);
  const nowS = isoDT(now);
  const next = (events ?? []).find((e) => !e.all_day && e.start > nowS);
  const { np } = useMedia();
  const music = !!np?.show && np.state === "playing";
  const day = weather?.daily.find((d) => d.date === t);
  return (
    <div className="screensaver" onClick={onWake}>
      {data && (usePhotos
        ? <PhotoShow key={listKey} photos={photos} seconds={seconds} onFail={() => setBroken(listKey)} onShow={setShown} />
        : <SceneShow seconds={seconds} />)}
      <div className="ss-shade" />
      {usePhotos && shown && settings?.photo_details !== false && <PhotoCaption photo={shown} />}
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

/** When and where the photo on screen was taken, small at the top right: "14 July 2025 · 3:30pm · Home". */
function PhotoCaption({ photo }: { photo: SlidePhoto }) {
  // Immich's local time is the wall clock where the photo was taken; use its digits as they are.
  const taken = photo.taken_at?.match(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/)?.[0];
  const parts = [
    taken && parse(taken).toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" }),
    taken && fmtTime(taken),
    photo.place,
  ].filter(Boolean);
  if (!parts.length) return null;
  return <div key={photo.id} className="ss-caption">{parts.join(" · ")}</div>;
}

function SceneShow({ seconds }: { seconds: number }) {
  const [i, setI] = useState(0);
  useEffect(() => { const t = setInterval(() => setI((x) => x + 1), seconds * 1000); return () => clearInterval(t); }, [seconds]);
  return <>{SCENES.map((s, k) => <div key={k} className={"ss-slide" + (k === i % SCENES.length ? " on" : "")}><Scene s={s} /></div>)}</>;
}

function shuffle<T>(xs: T[]): T[] {
  const a = [...xs];
  for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; }
  return a;
}

interface Slide { key: number; photo: SlidePhoto; aspect: number }

/** Load and decode an image; resolves with its aspect ratio (from the pixels, so EXIF rotation is already in it). */
function load(url: string): Promise<number> {
  const img = new Image();
  img.src = url;
  return img.decode().then(() => img.naturalWidth / Math.max(1, img.naturalHeight));
}

/** Immich photos: shuffled, crossfading, with a slow Ken Burns zoom (off for prefers-reduced-motion).
 * A photo that won't load is skipped; if several in a row fail, `onFail` hands back to the painted scenes. */
function PhotoShow({ photos, seconds, onFail, onShow }: {
  photos: SlidePhoto[]; seconds: number; onFail: () => void; onShow: (p: SlidePhoto) => void;
}) {
  const box = useRef<HTMLDivElement>(null);
  const [order] = useState(() => shuffle(photos)); // keyed by the list's ids, so a refetch doesn't restart it
  const [slides, setSlides] = useState<Slide[]>([]);
  const failRef = useRef(onFail);
  failRef.current = onFail;
  const showRef = useRef(onShow);
  showRef.current = onShow;
  useEffect(() => {
    let n = -1, alive = true, failures = 0, busy = false, shown = false;
    const giveUp = Math.min(3, order.length);
    // Swap only once the next photo is decoded, so the crossfade never shows a half-loaded image.
    const advance = () => {
      if (busy || !alive) return;
      busy = true;
      n = (n + 1) % order.length;
      const photo = order[n];
      load(photo.url).then((aspect) => {
        failures = 0;
        shown = true;
        busy = false;
        if (alive) { setSlides((s) => [...s.slice(-1), { key: Date.now(), photo, aspect }]); showRef.current(photo); }
      }, () => {
        busy = false;
        if (++failures >= giveUp) { if (alive) failRef.current(); }
        else if (!shown) advance(); // nothing on screen yet: try the next one straight away
      });
    };
    advance();
    if (order.length < 2) return () => { alive = false; };
    const t = setInterval(advance, seconds * 1000);
    return () => { alive = false; clearInterval(t); };
  }, [order, seconds]);
  const el = box.current;
  const screenAspect = el && el.clientHeight ? el.clientWidth / el.clientHeight : window.innerWidth / Math.max(1, window.innerHeight);
  return (
    <div className="ss-photos" ref={box}>
      {slides.map((s, i) => {
        // A photo much taller (or wider) than the screen is shown whole over a blurred copy of itself.
        const fit = Math.max(s.aspect / screenAspect, screenAspect / s.aspect) > 1.4 ? "contain" : "cover";
        const style = { "--kb": `${seconds + 2}s`, "--ox": `${(s.key % 3) * 50}%`, "--oy": `${(s.key % 2) * 100}%` } as CSSProperties;
        return (
          <div key={s.key} className={`ss-photo ${fit}` + (i === slides.length - 1 ? " top" : "")} style={style}>
            {fit === "contain" && <img className="ss-blur" src={s.photo.url} alt="" />}
            <img className="ss-img" src={s.photo.url} alt="" />
          </div>
        );
      })}
    </div>
  );
}
