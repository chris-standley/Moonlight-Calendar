// Demo-mode screens and photos. Sample photos are painted on a canvas at runtime (so the single-file preview
// stays small); uploads are read with FileReader and kept in memory only (too big for localStorage).
import { Album, Api, ApiError, Display, Photo, Topic, UploadResult } from "./types";
import { addDays, isoDT, today } from "../dates";

type Extras = Pick<Api, "displays" | "approveDisplay" | "revokeDisplay" | "albums" | "createAlbum" | "deleteAlbum" | "photos" | "uploadPhotos" | "deletePhoto">;

interface Look { name: string; sky: string[]; sun: string; sunY: number; hills: string[]; water?: boolean; stars?: boolean; w?: number; h?: number; ago: number }
const LOOKS: Look[] = [
  { name: "lake-sunset.jpg", sky: ["#1B2A4A", "#5B4A86", "#F09A73", "#FFD3A1"], sun: "#FFE3B5", sunY: 0.52, hills: ["#2A2140", "#3B2C55", "#523D6B"], water: true, ago: 12 },
  { name: "spring-meadow.jpg", sky: ["#7FB7F5", "#B9DAF7", "#EEF4EA"], sun: "#FFF8DC", sunY: 0.2, hills: ["#3F7A47", "#5E9A57", "#8FBF74"], ago: 40 },
  { name: "mountain-night.jpg", sky: ["#070D24", "#13224F", "#2C4C80"], sun: "#F5F1E2", sunY: 0.22, hills: ["#060B1E", "#0E1A3C", "#1B2C58"], stars: true, ago: 75 },
  { name: "beach-day.jpg", sky: ["#5AB0F0", "#A6D8F7", "#F6E7C8"], sun: "#FFFFFF", sunY: 0.16, hills: ["#E8CF9C", "#3B9CB6", "#5CB8CC"], water: true, ago: 110 },
  { name: "autumn-hills.jpg", sky: ["#F6C27A", "#F59B6B", "#E06C6C"], sun: "#FFF0C2", sunY: 0.45, hills: ["#6E2F3A", "#9A4A3E", "#C4713F"], ago: 160 },
  { name: "misty-morning.jpg", sky: ["#9FB7C9", "#C9D6DF", "#EEF1F2"], sun: "#FFFFFF", sunY: 0.3, hills: ["#4F6B78", "#6F8A95", "#9AB0B8"], water: true, ago: 220 },
  { name: "lavender-dusk.jpg", sky: ["#2E2350", "#7B5BA6", "#E9A8C8"], sun: "#FFE1EC", sunY: 0.58, hills: ["#2B1D46", "#4A3270", "#6E4F98"], w: 1000, h: 1400, ago: 300 },
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

function scaled(src: CanvasImageSource, w: number, h: number, maxLong: number, minShort = 0): string {
  const s = Math.min(1, maxLong / Math.max(w, h), minShort ? Math.max(minShort / Math.min(w, h), 0) : 1);
  const c = document.createElement("canvas");
  c.width = Math.max(1, Math.round(w * s)); c.height = Math.max(1, Math.round(h * s));
  c.getContext("2d")!.drawImage(src, 0, 0, c.width, c.height);
  return c.toDataURL("image/jpeg", 0.85);
}

function readFile(f: File): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const fr = new FileReader();
    fr.onerror = () => reject(new Error("read"));
    fr.onload = () => { const img = new Image(); img.onload = () => resolve(img); img.onerror = () => reject(new Error("decode")); img.src = String(fr.result); };
    fr.readAsDataURL(f);
  });
}

export function demoExtras(checkPin: (pin: string) => void, emit: (...t: Topic[]) => void): Extras {
  const ago = (min: number) => isoDT(new Date(Date.now() - min * 60_000));
  let displays: Display[] = [
    { id: "ds_hall", name: "Hallway", layout: "hallway", created_at: ago(60 * 24 * 20), last_seen: ago(1), revoked: false, current: false },
    { id: "ds_kitchen", name: "Kitchen", layout: "kitchen", created_at: ago(60 * 24 * 19), last_seen: ago(3), revoked: false, current: false },
  ];
  let albums: Album[] = [{ id: "al_family", name: "Family", created_at: ago(60 * 24 * 30), photo_count: 0, cover_photo_id: null }];
  let photos: Photo[] | null = null;
  let n = 0;
  const uid = (p: string) => `${p}_${Date.now().toString(36)}${(n++).toString(36)}`;
  const find = <T extends { id: string }>(xs: T[], id: string) => { const x = xs.find((a) => a.id === id); if (!x) throw new ApiError(404, "Not found"); return x; };

  function all(): Photo[] {
    if (photos) return photos;
    const t = today();
    photos = LOOKS.map((look, i) => {
      const w = look.w ?? 1800, h = look.h ?? 1200;
      const c = paint(look, w, h, 1000 + i * 7919);
      const id = `ph_demo${i}`;
      return {
        id, album_id: "al_family", filename: look.name, width: w, height: h,
        taken_at: `${addDays(t, -look.ago)}T${String(9 + i).padStart(2, "0")}:30:00`, uploaded_at: ago(60 * 24 * 7 + i),
        uploaded_by: i % 2 ? "Kitchen" : "Mum", display_url: c.toDataURL("image/jpeg", 0.85), thumb_url: scaled(c, w, h, 800, 400),
      };
    });
    return photos;
  }
  const albumOut = (a: Album): Album => {
    const ps = all().filter((p) => p.album_id === a.id);
    return { ...a, photo_count: ps.length, cover_photo_id: ps[0]?.id ?? null };
  };
  const sortKey = (p: Photo) => p.taken_at ?? p.uploaded_at;

  return {
    displays: async () => displays.map((d) => ({ ...d })),
    async approveDisplay(code, name, layout, pin) {
      checkPin(pin);
      if (!/^\d{6}$/.test(code)) throw new ApiError(400, "Enter the 6-digit code shown on the screen");
      const l = layout ?? "kitchen";
      const d: Display = { id: uid("ds"), name: name || `${l[0].toUpperCase()}${l.slice(1)} screen`, layout: l, created_at: ago(0), last_seen: ago(0), revoked: false, current: false };
      displays = [...displays, d];
      emit("displays");
      return { ...d };
    },
    async revokeDisplay(id, pin) { checkPin(pin); find(displays, id); displays = displays.filter((d) => d.id !== id); emit("displays"); },
    albums: async () => albums.map(albumOut),
    async createAlbum(name) {
      const a: Album = { id: uid("al"), name, created_at: ago(0), photo_count: 0, cover_photo_id: null };
      albums = [...albums, a]; emit("photos"); return albumOut(a);
    },
    async deleteAlbum(id, pin) {
      checkPin(pin); find(albums, id);
      albums = albums.filter((a) => a.id !== id);
      photos = all().filter((p) => p.album_id !== id);
      if (!albums.length) albums = [{ id: uid("al"), name: "Family", created_at: ago(0), photo_count: 0, cover_photo_id: null }];
      emit("photos");
    },
    photos: async (albumId) => all().filter((p) => !albumId || p.album_id === albumId).sort((a, b) => sortKey(b).localeCompare(sortKey(a))),
    async uploadPhotos(albumId, files): Promise<UploadResult> {
      const target = albumId ?? albums[0].id;
      find(albums, target);
      const out: UploadResult = { uploaded: [], errors: [] };
      for (const f of files) {
        if (f.size > 25 * 1024 * 1024) { out.errors.push({ filename: f.name, detail: `${f.name} is larger than 25 MB` }); continue; }
        try {
          const img = await readFile(f);
          const w = img.naturalWidth, h = img.naturalHeight;
          const p: Photo = {
            id: uid("ph"), album_id: target, filename: f.name, width: w, height: h, taken_at: null, uploaded_at: ago(0),
            uploaded_by: "This screen", display_url: scaled(img, w, h, 2560), thumb_url: scaled(img, w, h, 800, 400),
          };
          photos = [p, ...all()];
          out.uploaded.push(p);
        } catch { out.errors.push({ filename: f.name, detail: `${f.name}: not an image this browser can read` }); }
      }
      if (!out.uploaded.length) throw new ApiError(400, out.errors.map((e) => e.detail).join("; "));
      emit("photos");
      return out;
    },
    async deletePhoto(id, pin) { checkPin(pin); find(all(), id); photos = all().filter((p) => p.id !== id); emit("photos"); },
  };
}
