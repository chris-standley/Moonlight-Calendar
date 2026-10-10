import { CSSProperties, useEffect, useMemo, useRef, useState } from "react";
import { Photo } from "../api/types";
import { addDays, fmtFull, fmtTime, isoDT, today } from "../dates";
import { useApp, useData, useNow } from "../state";
import { WeatherIcon } from "../components/icons";

// Fallback "photos": generated scenes, shown until the family uploads some (Photos view).
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

/** `album`: undefined = the screensaver album from settings, null = all photos, or an album id. */
export function Screensaver({ onWake, album }: { onWake: () => void; album?: string | null }) {
  const { settings } = useApp();
  const now = useNow(10000);
  const albumId = album !== undefined ? album : settings?.screensaver_album ?? null;
  const seconds = Math.max(3, settings?.screensaver_seconds ?? 10);
  const [photos] = useData((api) => api.photos(albumId), ["photos"], [albumId]);
  const t = today();
  const [events] = useData((api) => api.events(t, addDays(t, 2)), ["events"], [t]);
  const [weather] = useData((api) => api.weather(), [], []);
  const nowS = isoDT(now);
  const next = (events ?? []).find((e) => !e.all_day && e.start > nowS);
  return (
    <div className="screensaver" onClick={onWake}>
      {photos && (photos.length ? <PhotoShow photos={photos} seconds={seconds} /> : <SceneShow seconds={seconds} />)}
      <div className="ss-shade" />
      <div className="ss-info">
        <div className="ss-time">{now.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })}</div>
        <div className="ss-date">{fmtFull(t)}</div>
        {weather && <div className="ss-wx"><WeatherIcon condition={weather.current.condition} size={36} /> {weather.current.temp}°</div>}
        {next && <div className="ss-next">Next: <b>{next.title}</b> at {fmtTime(next.start)}</div>}
      </div>
      <div className="ss-family">{settings?.family_name}</div>
    </div>
  );
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

interface Slide { key: number; photo: Photo }

/** Uploaded photos: shuffled, crossfading, with a slow Ken Burns zoom (off for prefers-reduced-motion). */
function PhotoShow({ photos, seconds }: { photos: Photo[]; seconds: number }) {
  const box = useRef<HTMLDivElement>(null);
  const order = useMemo(() => shuffle(photos), [photos]);
  const [slides, setSlides] = useState<Slide[]>(() => [{ key: 0, photo: order[0] }]);
  useEffect(() => { setSlides([{ key: Date.now(), photo: order[0] }]); }, [order]);
  useEffect(() => {
    if (order.length < 2) return;
    let n = 0, alive = true;
    const t = setInterval(() => {
      n = (n + 1) % order.length;
      const photo = order[n];
      const img = new Image();
      img.src = photo.display_url;
      // Swap only once the next photo is decoded, so the crossfade never shows a half-loaded image.
      img.decode().catch(() => undefined).then(() => {
        if (alive) setSlides((s) => [...s.slice(-1), { key: Date.now(), photo }]);
      });
    }, seconds * 1000);
    return () => { alive = false; clearInterval(t); };
  }, [order, seconds]);
  const el = box.current;
  const screenAspect = el && el.clientHeight ? el.clientWidth / el.clientHeight : window.innerWidth / Math.max(1, window.innerHeight);
  return (
    <div className="ss-photos" ref={box}>
      {slides.map((s, i) => {
        const aspect = s.photo.width / Math.max(1, s.photo.height);
        // A photo much taller (or wider) than the screen is shown whole over a blurred copy of itself.
        const fit = Math.max(aspect / screenAspect, screenAspect / aspect) > 1.4 ? "contain" : "cover";
        const style = { "--kb": `${seconds + 2}s`, "--ox": `${(s.key % 3) * 50}%`, "--oy": `${(s.key % 2) * 100}%` } as CSSProperties;
        return (
          <div key={s.key} className={`ss-photo ${fit}` + (i === slides.length - 1 ? " top" : "")} style={style}>
            {fit === "contain" && <img className="ss-blur" src={s.photo.display_url} alt="" />}
            <img className="ss-img" src={s.photo.display_url} alt="" />
          </div>
        );
      })}
    </div>
  );
}
