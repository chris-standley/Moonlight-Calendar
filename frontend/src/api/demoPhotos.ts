// Demo-mode screens and a simulated Immich server for the photo screensaver. Sample photos are painted on a canvas
// at runtime (so the single-file preview stays small). Kept in memory only.
import { Api, ApiError, Display, DisplaySetup, ImmichAlbum, ImmichConfig, ImmichMode, ImmichSeason, Layout, PhotoAlbum, SECTIONS, SlidePhoto, Topic } from "./types";
import { addDays, isoDT, today } from "../dates";

type Extras = Pick<Api, "displays" | "approveDisplay" | "revokeDisplay" | "updateDisplay" | "thisScreen" | "immich" | "saveImmich" | "disconnectImmich" |
  "testImmich" | "immichAlbums" | "screensaverPhotos">;

interface Look { name: string; sky: string[]; sun: string; sunY: number; hills: string[]; water?: boolean; stars?: boolean; w?: number; h?: number; ago: number; place?: string }
const LOOKS: Look[] = [
  { name: "lake-sunset.jpg", place: "Windermere", sky: ["#1B2A4A", "#5B4A86", "#F09A73", "#FFD3A1"], sun: "#FFE3B5", sunY: 0.52, hills: ["#2A2140", "#3B2C55", "#523D6B"], water: true, ago: 12 },
  { name: "spring-meadow.jpg", place: "Home", sky: ["#7FB7F5", "#B9DAF7", "#EEF4EA"], sun: "#FFF8DC", sunY: 0.2, hills: ["#3F7A47", "#5E9A57", "#8FBF74"], ago: 40 },
  { name: "mountain-night.jpg", sky: ["#070D24", "#13224F", "#2C4C80"], sun: "#F5F1E2", sunY: 0.22, hills: ["#060B1E", "#0E1A3C", "#1B2C58"], stars: true, ago: 75 },
  { name: "beach-day.jpg", place: "St Ives", sky: ["#5AB0F0", "#A6D8F7", "#F6E7C8"], sun: "#FFFFFF", sunY: 0.16, hills: ["#E8CF9C", "#3B9CB6", "#5CB8CC"], water: true, ago: 110 },
  { name: "autumn-hills.jpg", place: "Peppa Pig World", sky: ["#F6C27A", "#F59B6B", "#E06C6C"], sun: "#FFF0C2", sunY: 0.45, hills: ["#6E2F3A", "#9A4A3E", "#C4713F"], ago: 160 },
  { name: "misty-morning.jpg", sky: ["#9FB7C9", "#C9D6DF", "#EEF1F2"], sun: "#FFFFFF", sunY: 0.3, hills: ["#4F6B78", "#6F8A95", "#9AB0B8"], water: true, ago: 220 },
  { name: "lavender-dusk.jpg", place: "Home", sky: ["#2E2350", "#7B5BA6", "#E9A8C8"], sun: "#FFE1EC", sunY: 0.58, hills: ["#2B1D46", "#4A3270", "#6E4F98"], w: 1000, h: 1400, ago: 300 },
];

function rand(seed: number) { return () => { seed = (seed * 16807) % 2147483647; return seed / 2147483647; }; }

function paint(look: Look, w: number, h: number, seed: number): HTMLCanvasElement {
  const c = document.createElement("canvas");
  c.width = w; c.height = h;
  const g = c.getContext("2d")!;
  const r = rand(seed);
  const sky = g.createLinearGradient(0, 0, 0, h * 0.75);
  look.sky.forEach((col, i) => sky.addColorStop(i / (look.sky.length - 1), col));
  g.fillStyle = sky; g.fillRect(0, 0, w, h);
  if (look.stars) for (let i = 0; i < 220; i++) { g.fillStyle = `rgba(255,255,255,${0.3 + r() * 0.6})`; g.fillRect(r() * w, r() * h * 0.55, 1.6, 1.6); }
  const sx = w * (0.55 + r() * 0.25), sy = h * look.sunY, sr = Math.min(w, h) * 0.06;
  const glow = g.createRadialGradient(sx, sy, sr * 0.5, sx, sy, sr * 6);
  glow.addColorStop(0, look.sun + "AA"); glow.addColorStop(1, look.sun + "00");
  g.fillStyle = glow; g.fillRect(0, 0, w, h);
  g.fillStyle = look.sun; g.beginPath(); g.arc(sx, sy, sr, 0, Math.PI * 2); g.fill();
  const horizon = h * 0.62;
  look.hills.slice().reverse().forEach((col, k) => {
    const base = horizon + k * h * 0.09 - h * 0.12;
    g.fillStyle = col; g.beginPath(); g.moveTo(0, h);
    let y = base - r() * h * 0.08;
    for (let x = 0; x <= w; x += w / 60) { y += (r() - 0.5) * h * (0.035 - k * 0.008); y = Math.min(Math.max(y, base - h * 0.16), base + h * 0.05); g.lineTo(x, y); }
    g.lineTo(w, h); g.closePath(); g.fill();
  });
  if (look.water) {
    const wy = h * 0.74;
    const water = g.createLinearGradient(0, wy, 0, h);
    water.addColorStop(0, look.sky[look.sky.length - 2] + "EE"); water.addColorStop(1, look.sky[0] + "FF");
    g.fillStyle = water; g.fillRect(0, wy, w, h - wy);
    g.fillStyle = look.sun + "55";
    for (let i = 0; i < 26; i++) { const yy = wy + 6 + i * (h - wy) / 28; const ww = sr * (2.2 - i * 0.05) * (0.6 + r()); g.fillRect(sx - ww / 2, yy, ww, 2.5); }
  }
  const mist = g.createLinearGradient(0, horizon - h * 0.1, 0, horizon + h * 0.1);
  mist.addColorStop(0, "rgba(255,255,255,0)"); mist.addColorStop(0.5, "rgba(255,255,255,0.12)"); mist.addColorStop(1, "rgba(255,255,255,0)");
  g.fillStyle = mist; g.fillRect(0, horizon - h * 0.1, w, h * 0.2);
  return c;
}

const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));

// The pretend Immich library: which sample photos are in which album, favourites and "on this day".
const ALBUMS: (ImmichAlbum & { looks: number[] })[] = [
  { id: "5d0c7c52-3f7e-4d55-9a8e-0f6a1b2c3d41", name: "Family", asset_count: 7, shared: true, updated_at: "2026-09-20T10:00:00.000Z", looks: [0, 1, 2, 3, 4, 5, 6] },
  { id: "8a1f2e33-6b4c-4e9a-8d17-2c3b4a5d6e72", name: "Garden", asset_count: 3, shared: false, updated_at: "2026-06-02T10:00:00.000Z", looks: [1, 4, 5] },
  { id: "c47b9d10-2e8f-4a63-b5c4-7d8e9f0a1b23", name: "Summer holiday", asset_count: 3, shared: false, updated_at: "2026-08-14T10:00:00.000Z", looks: [0, 3, 6] },
  { id: "e2a6f0b8-91d3-4c5e-a7f2-3b4c5d6e7f80", name: "Christmas", asset_count: 2, shared: true, updated_at: "2025-12-27T10:00:00.000Z", looks: [2, 5] },
];
const FAVOURITES = [2, 3];
const ON_THIS_DAY = [5];

/** `styleSetup`: what a screen of that style shows without choices of its own (from the demo's settings). */
export function demoExtras(checkPin: (pin: string) => void, emit: (...t: Topic[]) => void, styleSetup: (l: Layout) => DisplaySetup): Extras {
  const ago = (min: number) => isoDT(new Date(Date.now() - min * 60_000));
  type Stored = Omit<Display, "setup" | "own_setup"> & { own?: Partial<DisplaySetup> };
  let displays: Stored[] = [
    { id: "ds_hall", name: "Hallway", layout: "large", created_at: ago(60 * 24 * 20), last_seen: ago(1), revoked: false, current: false },
    { id: "ds_kitchen", name: "Kitchen", layout: "compact", created_at: ago(60 * 24 * 19), last_seen: ago(3), revoked: false, current: false },
    { id: "ds_phone", name: "Alex's iPhone", layout: "app", created_at: ago(60 * 24 * 2), last_seen: ago(12), revoked: false, current: false },
    { id: "ds_ha", name: "Home Assistant", layout: "service", created_at: ago(60 * 24 * 19), last_seen: ago(1), revoked: false, current: false },
  ];
  const out1 = ({ own, ...d }: Stored): Display => d.layout === "service" || d.layout === "app" ? { ...d }
    : { ...d, setup: { ...styleSetup(d.layout), ...own }, own_setup: !!own && Object.keys(own).length > 0 };
  let n = 0;
  const uid = (p: string) => `${p}_${Date.now().toString(36)}${(n++).toString(36)}`;
  const find = <T extends { id: string }>(xs: T[], id: string) => { const x = xs.find((a) => a.id === id); if (!x) throw new ApiError(404, "Not found"); return x; };

  // Starts connected to one album, so the preview's screensaver shows photos. Any address and key work;
  // the key "wrong" is rejected and an address containing "offline" can't be reached.
  type Cfg = { server_url: string; key: string; mode: ImmichMode; album_ids: string[]; excluded_album_ids: string[]; seasons: ImmichSeason[];
    favorites: boolean; memories: boolean; skip_cert_check?: boolean };
  let cfg: Cfg | null = { server_url: "http://192.168.1.10:2283", key: "demo", mode: "albums", album_ids: [ALBUMS[0].id], excluded_album_ids: [],
    seasons: [], favorites: false, memories: false };
  let refreshed = ago(2);
  let painted: SlidePhoto[] | null = null;
  function library(): SlidePhoto[] {
    if (painted) return painted;
    const t = today();
    painted = LOOKS.map((look, i) => {
      const w = look.w ?? 1800, h = look.h ?? 1200;
      return {
        id: `0000000${i}-demo-4000-8000-00000000000${i}`, width: w, height: h,
        taken_at: `${addDays(t, -look.ago)}T${String(9 + i).padStart(2, "0")}:30:00`, place: look.place ?? null,
        url: paint(look, w, h, 1000 + i * 7919).toDataURL("image/jpeg", 0.85),
      };
    });
    return painted;
  }
  const looksOf = (ids: string[]) => ids.flatMap((id) => ALBUMS.find((a) => a.id === id)?.looks ?? []);
  const seasonNow = (c: Cfg) => {
    const md = today().slice(5);
    return [...new Set(c.seasons.filter((s) => (s.start <= s.end ? s.start <= md && md <= s.end : md >= s.start || md <= s.end)).map((s) => s.album_id))];
  };
  // Like the add-on: whole albums (newest first), seasonal ones only in their dates, hidden albums' photos hidden everywhere.
  const groups = (): (Omit<PhotoAlbum, "photos"> & { looks: number[] })[] => {
    if (!cfg) return [];
    const now = seasonNow(cfg);
    const hidden = now.length ? [] : [...cfg.seasons.map((s) => s.album_id), ...(cfg.mode === "all" ? cfg.excluded_album_ids : [])];
    const hide = new Set(looksOf(hidden));
    const ids = now.length ? now : cfg.mode === "all" ? ALBUMS.map((a) => a.id).filter((id) => !hidden.includes(id)) : cfg.album_ids.filter((id) => !hidden.includes(id));
    const out = ALBUMS.filter((a) => ids.includes(a.id)).sort((a, b) => (b.updated_at ?? "").localeCompare(a.updated_at ?? ""))
      .map(({ id, name, updated_at, looks }) => ({ id, name, updated_at: updated_at ?? null, looks }));
    if (!now.length && cfg.favorites) out.push({ id: "favorites", name: "Favourites", updated_at: null, looks: FAVOURITES });
    if (!now.length && cfg.memories) out.push({ id: "on-this-day", name: "On this day", updated_at: today(), looks: ON_THIS_DAY });
    return out.map((g) => ({ ...g, looks: g.looks.filter((i) => !hide.has(i)) })).filter((g) => g.looks.length);
  };
  const chosen = (): SlidePhoto[] => [...new Set(groups().flatMap((g) => g.looks))].sort().map((i) => library()[i]);
  const out = (): ImmichConfig => cfg
    ? { configured: true, server_url: cfg.server_url, key_set: true, mode: cfg.mode, album_ids: [...cfg.album_ids],
        excluded_album_ids: [...cfg.excluded_album_ids], seasons: cfg.seasons.map((s) => ({ ...s })), season_now: seasonNow(cfg), favorites: cfg.favorites,
        memories: cfg.memories, skip_cert_check: !!cfg.skip_cert_check, status: "ok", last_error: null, last_refresh: refreshed, photo_count: chosen().length, version: "3.3.1" }
    : { configured: false, server_url: "", key_set: false, mode: "albums", album_ids: [], excluded_album_ids: [], seasons: [], favorites: false, memories: false, skip_cert_check: false, status: "unconfigured",
        last_error: null, last_refresh: null, photo_count: 0, version: null };
  const albums = () => ALBUMS.map(({ looks, ...a }) => ({ ...a }));
  async function check(url: string, key: string) {
    await wait(700); // "talking to Immich"
    if (!/^https?:\/\/[^/\s]+/.test(url)) throw new ApiError(400, "server_url must look like http://192.168.1.10:2283");
    if (!key.trim()) throw new ApiError(400, "api_key is required");
    if (url.includes("offline")) throw new ApiError(502, `Couldn't reach Immich at ${url} (ConnectError)`);
    if (key.trim() === "wrong") throw new ApiError(400, "Immich didn't accept the API key");
  }
  const clean = (u: string) => u.trim().replace(/\/+$/, "").replace(/\/api$/, "");

  return {
    displays: async () => displays.map(out1),
    thisScreen: async () => null,
    async approveDisplay(code, name, layout, pin) {
      checkPin(pin);
      if (!/^\d{6}$/.test(code)) throw new ApiError(400, "Enter the 6-digit code shown on the screen");
      const l = layout ?? "compact";
      const d: Stored = { id: uid("ds"), name: name || (l === "phone" ? "Phone" : `${l[0].toUpperCase()}${l.slice(1)} screen`), layout: l, created_at: ago(0), last_seen: ago(0), revoked: false, current: false };
      displays = [...displays, d];
      emit("displays");
      return out1(d);
    },
    async updateDisplay(id, { pin, name, layout, setup }) {
      checkPin(pin);
      const d = { ...find(displays, id) };
      if (name !== undefined) { if (!name.trim()) throw new ApiError(400, "name is required"); d.name = name.trim().slice(0, 60); }
      if (layout !== undefined) d.layout = layout;
      if (setup === null) d.own = undefined;
      else if (setup) {
        const own = { ...d.own, ...setup };
        if (own.sections) {
          own.sections = SECTIONS.filter((x) => own.sections!.includes(x));
          if (!own.sections.length) throw new ApiError(400, "setup.sections must not be empty");
        }
        const shown = own.sections ?? styleSetup(d.layout as Layout).sections;
        if (!shown.includes(own.start ?? styleSetup(d.layout as Layout).start)) own.start = shown[0];
        d.own = own;
      }
      displays = displays.map((x) => (x.id === id ? d : x));
      emit("displays");
      return out1(d);
    },
    async revokeDisplay(id, pin) { checkPin(pin); find(displays, id); displays = displays.filter((d) => d.id !== id); emit("displays"); },
    immich: async () => out(),
    async saveImmich({ pin, server_url, api_key, mode, album_ids, excluded_album_ids, seasons, favorites, memories, skip_cert_check }) {
      checkPin(pin);
      const url = server_url !== undefined ? clean(server_url) : cfg?.server_url ?? "";
      const key = api_key ? api_key.trim() : cfg?.key ?? "";
      if (!cfg || url !== cfg.server_url || key !== cfg.key) await check(url, key);
      cfg = { server_url: url, key, mode: mode ?? cfg?.mode ?? "albums", album_ids: album_ids ?? cfg?.album_ids ?? [],
        excluded_album_ids: excluded_album_ids ?? cfg?.excluded_album_ids ?? [], seasons: seasons ?? cfg?.seasons ?? [], favorites: favorites ?? cfg?.favorites ?? false,
        memories: memories ?? cfg?.memories ?? false, skip_cert_check: skip_cert_check ?? cfg?.skip_cert_check ?? false };
      refreshed = ago(0);
      emit("photos");
      return out();
    },
    async disconnectImmich(pin) { checkPin(pin); cfg = null; emit("photos"); },
    async testImmich({ pin, server_url, api_key }) {
      checkPin(pin);
      const url = server_url ? clean(server_url) : cfg?.server_url;
      const key = api_key || cfg?.key;
      if (!url || !key) throw new ApiError(400, "Enter the Immich address and an API key");
      await check(url, key);
      return { ok: true, version: "3.3.1", albums: albums() };
    },
    async immichAlbums() { if (!cfg) throw new ApiError(404, "Immich isn't connected"); return albums(); },
    screensaverPhotos: async () => cfg
      ? { source: "immich", status: "ok", photos: chosen(), albums: groups().map(({ looks, ...g }) => ({ ...g, photos: looks.map((i) => library()[i].id) })) }
      : { source: "none", status: "unconfigured", photos: [], albums: [] },
  };
}
