// Moonlight's own line icons (24px grid, stroke = currentColor).
import { SVGProps } from "react";

type P = SVGProps<SVGSVGElement> & { size?: number };
const base = (size = 24, p: P) => ({
  width: size, height: size, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor",
  strokeWidth: 2, strokeLinecap: "round" as const, strokeLinejoin: "round" as const, ...p,
});

export const IconCalendar = ({ size, ...p }: P) => (
  <svg {...base(size, p)}><rect x="3" y="4.5" width="18" height="16" rx="3" /><path d="M3 9.5h18M8 2.5v4M16 2.5v4" /><circle cx="8" cy="14" r=".6" fill="currentColor" /><circle cx="12" cy="14" r=".6" fill="currentColor" /><circle cx="16" cy="14" r=".6" fill="currentColor" /></svg>
);
export const IconChores = ({ size, ...p }: P) => (
  <svg {...base(size, p)}><rect x="3.5" y="3.5" width="17" height="17" rx="4.5" /><path d="M8 12.2l2.8 2.8L16.5 9" /></svg>
);
export const IconStar = ({ size, filled, ...p }: P & { filled?: boolean }) => (
  <svg {...base(size, p)}><path d="M12 3.2l2.6 5.4 5.9.8-4.3 4.1 1 5.9L12 16.6l-5.2 2.8 1-5.9L3.5 9.4l5.9-.8z" fill={filled ? "currentColor" : "none"} /></svg>
);
export const IconMeals = ({ size, ...p }: P) => (
  <svg {...base(size, p)}><path d="M6 3v7a2 2 0 002 2v9M10 3v7a2 2 0 01-2 2M8 3v5" /><path d="M17 21V3c-2.2 1-3.5 3.5-3.5 7v3H17" /></svg>
);
export const IconRecipes = ({ size, ...p }: P) => (
  <svg {...base(size, p)}><path d="M5 4.5A1.5 1.5 0 016.5 3H19v15H6.5A1.5 1.5 0 005 19.5z" /><path d="M5 19.5A1.5 1.5 0 006.5 21H19v-3" /><path d="M10 7v4M12 7v4M14 7v4M12 11v4" /></svg>
);
export const IconLists = ({ size, ...p }: P) => (
  <svg {...base(size, p)}><path d="M9.5 6.5H20M9.5 12H20M9.5 17.5H20" /><path d="M4 6.5l1 1 2-2M4 12l1 1 2-2" /><circle cx="5.2" cy="17.5" r="1.2" /></svg>
);
export const IconHome = ({ size, ...p }: P) => (
  <svg {...base(size, p)}><path d="M3.5 11L12 4l8.5 7" /><path d="M5.5 9.5V20h13V9.5" /><path d="M10 20v-5h4v5" /></svg>
);
export const IconShield = ({ size, ...p }: P) => (
  <svg {...base(size, p)}><path d="M12 3l7.5 3v5.5c0 4.6-3.2 8.3-7.5 9.5-4.3-1.2-7.5-4.9-7.5-9.5V6z" /><path d="M8.8 12l2.3 2.3 4.2-4.4" /></svg>
);
export const IconBolt = ({ size, ...p }: P) => (
  <svg {...base(size, p)}><path d="M13.5 2.5L5 13.5h6l-1 8 8.5-11h-6z" /></svg>
);
export const IconCctv = ({ size, ...p }: P) => (
  <svg {...base(size, p)}><rect x="3" y="6.5" width="13" height="11" rx="2.5" /><path d="M16 10.5l5-3v9l-5-3" /></svg>
);
export const IconPhotos = ({ size, ...p }: P) => (
  <svg {...base(size, p)}><rect x="3" y="4.5" width="18" height="15" rx="3" /><circle cx="9" cy="10" r="1.8" /><path d="M21 16l-5-5-8.5 8.5" /></svg>
);
/** Nursery: a stack of toy blocks. */
export const IconNursery = ({ size, ...p }: P) => (
  <svg {...base(size, p)}><rect x="3.5" y="13" width="8" height="7.5" rx="1.5" /><rect x="12.5" y="13" width="8" height="7.5" rx="1.5" /><path d="M12 3.5l4.5 7.5h-9z" /></svg>
);
export const IconSettings = ({ size, ...p }: P) => (
  <svg {...base(size, p)}><circle cx="12" cy="12" r="3" /><path d="M12 2.8v2.4M12 18.8v2.4M21.2 12h-2.4M5.2 12H2.8M18.5 5.5l-1.7 1.7M7.2 16.8l-1.7 1.7M18.5 18.5l-1.7-1.7M7.2 7.2L5.5 5.5" /></svg>
);
export const IconPlus = ({ size, ...p }: P) => <svg {...base(size, p)}><path d="M12 5v14M5 12h14" /></svg>;
export const IconLeft = ({ size, ...p }: P) => <svg {...base(size, p)}><path d="M15 5l-7 7 7 7" /></svg>;
export const IconRight = ({ size, ...p }: P) => <svg {...base(size, p)}><path d="M9 5l7 7-7 7" /></svg>;
export const IconUp = ({ size, ...p }: P) => <svg {...base(size, p)}><path d="M5 15l7-7 7 7" /></svg>;
export const IconDown = ({ size, ...p }: P) => <svg {...base(size, p)}><path d="M5 9l7 7 7-7" /></svg>;
export const IconClose = ({ size, ...p }: P) => <svg {...base(size, p)}><path d="M6 6l12 12M18 6L6 18" /></svg>;
export const IconCheck = ({ size, ...p }: P) => <svg {...base(size, p)}><path d="M5 12.5l4.5 4.5L19 7.5" /></svg>;
export const IconTrash = ({ size, ...p }: P) => <svg {...base(size, p)}><path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3" /></svg>;
/** A filled raindrop, for the chance of rain. */
export const IconDrop = ({ size = 16 }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3.5s-6 6.6-6 10.9a6 6 0 0012 0C18 10.1 12 3.5 12 3.5z" fill="currentColor" /></svg>
);
export const IconCamera = ({ size, ...p }: P) => <svg {...base(size, p)}><path d="M4 8h3l1.6-2.4h6.8L17 8h3a1 1 0 011 1v9a1 1 0 01-1 1H4a1 1 0 01-1-1V9a1 1 0 011-1z" /><circle cx="12" cy="13.2" r="3.4" /></svg>;
export const IconPin = ({ size, ...p }: P) => <svg {...base(size, p)}><path d="M12 21s-6.5-6-6.5-11a6.5 6.5 0 0113 0c0 5-6.5 11-6.5 11z" /><circle cx="12" cy="10" r="2.3" /></svg>;
export const IconRepeat = ({ size, ...p }: P) => <svg {...base(size, p)}><path d="M17 2.5l3 3-3 3" /><path d="M4 11.5v-1a5 5 0 015-5h11M7 21.5l-3-3 3-3" /><path d="M20 12.5v1a5 5 0 01-5 5H4" /></svg>;
export const IconCart = ({ size, ...p }: P) => <svg {...base(size, p)}><path d="M3 4h2.5l2.2 11h10.6l2-8H7" /><circle cx="9.5" cy="19.5" r="1.3" /><circle cx="17" cy="19.5" r="1.3" /></svg>;
export const IconFlame = ({ size, ...p }: P) => <svg {...base(size, p)}><path d="M12 21c-3.9 0-6.5-2.6-6.5-6.2 0-3.6 3-5.6 3.6-9.3 2.4 1.4 3.4 3.4 3.4 5.2 1-.6 1.8-1.6 2-2.9 2 1.7 4 4.2 4 7 0 3.6-2.6 6.2-6.5 6.2z" /></svg>;
export const IconLock = ({ size, ...p }: P) => <svg {...base(size, p)}><rect x="5" y="10.5" width="14" height="10" rx="2.5" /><path d="M8 10.5V8a4 4 0 018 0v2.5" /></svg>;

// Playback (filled glyphs read better at a glance on a wall screen).
export const IconPlay = ({ size, ...p }: P) => <svg {...base(size, p)}><path d="M7.5 4.8v14.4a1 1 0 001.5.9l11.3-7.2a1 1 0 000-1.7L9 4a1 1 0 00-1.5.8z" fill="currentColor" /></svg>;
export const IconPause = ({ size, ...p }: P) => <svg {...base(size, p)}><rect x="6" y="4.5" width="4" height="15" rx="1.2" fill="currentColor" /><rect x="14" y="4.5" width="4" height="15" rx="1.2" fill="currentColor" /></svg>;
export const IconNext = ({ size, ...p }: P) => <svg {...base(size, p)}><path d="M5 5.6v12.8a.9.9 0 001.4.8l9.4-6.4a.9.9 0 000-1.5L6.4 4.8A.9.9 0 005 5.6z" fill="currentColor" /><path d="M19 5v14" /></svg>;
export const IconPrev = ({ size, ...p }: P) => <svg {...base(size, p)}><path d="M19 5.6v12.8a.9.9 0 01-1.4.8l-9.4-6.4a.9.9 0 010-1.5l9.4-6.5a.9.9 0 011.4.8z" fill="currentColor" /><path d="M5 5v14" /></svg>;
export const IconVolume = ({ size, ...p }: P) => <svg {...base(size, p)}><path d="M4 9.5h3.5L12 5.5v13l-4.5-4H4z" fill="currentColor" /><path d="M15.5 9a4 4 0 010 6M18 6.5a7.5 7.5 0 010 11" /></svg>;
export const IconMute = ({ size, ...p }: P) => <svg {...base(size, p)}><path d="M4 9.5h3.5L12 5.5v13l-4.5-4H4z" fill="currentColor" /><path d="M16 9.5l5 5M21 9.5l-5 5" /></svg>;
export const IconShuffle = ({ size, ...p }: P) => <svg {...base(size, p)}><path d="M3 7h3.5c4.5 0 6.5 10 11 10H21M3 17h3.5c1.6 0 2.8-1.3 3.8-3M13.7 10c1-1.7 2.2-3 3.8-3H21" /><path d="M18.5 4.5L21 7l-2.5 2.5M18.5 14.5L21 17l-2.5 2.5" /></svg>;
export const IconRepeatOne = ({ size, ...p }: P) => <svg {...base(size, p)}><path d="M17 2.5l3 3-3 3" /><path d="M4 11.5v-1a5 5 0 015-5h11M7 21.5l-3-3 3-3" /><path d="M20 12.5v1a5 5 0 01-5 5H4" /><path d="M11 10.5l1.3-.8v4.8" strokeWidth="1.6" /></svg>;
export const IconMusic = ({ size, ...p }: P) => <svg {...base(size, p)}><path d="M9 18V5.5l11-2V16" /><circle cx="6.5" cy="18" r="2.5" /><circle cx="17.5" cy="16" r="2.5" /></svg>;

/** Crescent logo mark. */
export const Logo = ({ size = 32 }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden>
    <defs>
      <linearGradient id="mlg" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0" stopColor="#7C8CF8" /><stop offset="1" stopColor="#B38CF0" />
      </linearGradient>
    </defs>
    <rect width="32" height="32" rx="9" fill="url(#mlg)" />
    <path d="M19.5 7.5a9 9 0 100 17 7.2 7.2 0 010-17z" fill="#fff" />
    <circle cx="23" cy="10" r="1.3" fill="#fff" opacity=".85" />
    <circle cx="25.5" cy="15" r=".9" fill="#fff" opacity=".7" />
  </svg>
);

/** Weather glyphs keyed by Home Assistant condition names. Colourful, not stroke-only. */
export function WeatherIcon({ condition, size = 24 }: { condition: string; size?: number }) {
  const sun = <g><circle cx="12" cy="12" r="4.2" fill="#FFB938" />{[0, 45, 90, 135, 180, 225, 270, 315].map((a) => <path key={a} d="M12 3.2v1.9" stroke="#FFB938" strokeWidth="1.8" strokeLinecap="round" transform={`rotate(${a} 12 12)`} />)}</g>;
  const cloud = (x = 0, y = 0, fill = "#C9D3E3") => <path transform={`translate(${x} ${y})`} d="M7.5 19h9.2a3.8 3.8 0 00.4-7.6 5.2 5.2 0 00-10 1.3A3.2 3.2 0 007.5 19z" fill={fill} />;
  let g;
  switch (condition) {
    case "sunny": g = sun; break;
    case "clear-night": g = <path d="M14.5 3.5A8.5 8.5 0 1 0 20.5 14.5A7 7 0 0 1 14.5 3.5z" fill="#8F9BF2" />; break;
    case "partlycloudy": g = <g><g transform="translate(-3 -3) scale(.85)">{sun}</g>{cloud(1, 1)}</g>; break;
    case "cloudy": case "fog": g = <g>{cloud(-1, -2, "#AEB9CC")}{cloud(1, 1)}</g>; break;
    case "lightning-rainy":
      g = <g>{cloud(0, -3, "#AEB9CC")}<path d="M13.2 15.5l-2.4 3.6h2.4l-1.6 3.4" stroke="#FFB938" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" fill="none" /><path d="M8.5 18.5l-1 2.5M17.5 18.5l-1 2.5" stroke="#5B9BEA" strokeWidth="1.8" strokeLinecap="round" /></g>; break;
    case "rainy": case "pouring":
      g = <g>{cloud(0, -3, "#AEB9CC")}<path d="M9 18.5l-1 2.5M13 18.5l-1 2.5M17 18.5l-1 2.5" stroke="#5B9BEA" strokeWidth="1.8" strokeLinecap="round" /></g>; break;
    case "snowy": g = <g>{cloud(0, -3)}<circle cx="9" cy="20" r="1" fill="#9CC3F0" /><circle cx="13" cy="21" r="1" fill="#9CC3F0" /><circle cx="17" cy="20" r="1" fill="#9CC3F0" /></g>; break;
    case "windy": g = <path d="M3 9h11a2.5 2.5 0 10-2.5-2.5M3 13h15a2.5 2.5 0 11-2.5 2.5M3 17h8" stroke="#8FA3BF" strokeWidth="1.8" strokeLinecap="round" fill="none" />; break;
    default: g = cloud();
  }
  return <svg width={size} height={size} viewBox="0 0 24 24" aria-label={condition}>{g}</svg>;
}
export const IconMic = ({ size, ...p }: P) => <svg {...base(size, p)}><rect x="9" y="3" width="6" height="11" rx="3" /><path d="M5.5 11a6.5 6.5 0 0013 0M12 17.5V21" /></svg>;
