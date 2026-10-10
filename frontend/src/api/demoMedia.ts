// Demo-mode music: a pretend kitchen speaker playing made-up tracks. The album art is painted on a canvas at
// runtime (abstract shapes, nothing copyrighted) and handed out as a data: URL.
import { Api, ApiError, Layout, MediaAction, MediaFavourite, MediaPlayerOption, NowPlaying, Topic } from "./types";

type Extras = Pick<Api, "nowPlaying" | "mediaCommand" | "mediaPlayers" | "mediaFavourites" | "playFavourite">;

interface Track { title: string; artist: string; album: string; secs: number; colors: [string, string, string]; shape: "sun" | "waves" | "rings" | "hills" }
const TRACKS: Track[] = [
  { title: "Saturday Pancakes", artist: "The Marmalade Collective", album: "Kitchen Radio", secs: 214, colors: ["#F6B26B", "#E06C75", "#FFE9C7"], shape: "sun" },
  { title: "Window Light", artist: "Juniper & Vale", album: "Slow Mornings", secs: 187, colors: ["#5B8DEF", "#A7C7F2", "#F4F7FB"], shape: "waves" },
  { title: "Copper Kettle Waltz", artist: "Orla Finch Trio", album: "Small Rooms", secs: 242, colors: ["#2F4858", "#C9844B", "#F3D9A4"], shape: "rings" },
  { title: "Lanterns", artist: "Northbound Tide", album: "Harbour Songs", secs: 199, colors: ["#3B2C55", "#B86FC4", "#FFD3A1"], shape: "hills" },
  { title: "Green Tomato Swing", artist: "Dot & the Dashes", album: "Sunday Best", secs: 176, colors: ["#2FB58A", "#F2C94C", "#FDF6E3"], shape: "sun" },
];
const RADIO: Track = { title: "Moonlight FM", artist: "Easy listening, all day", album: "Live radio", secs: 0, colors: ["#1B2A4A", "#6C7BF0", "#FFFFFF"], shape: "waves" };
const FAVOURITES: (MediaFavourite & { tracks: number[] | "radio" })[] = [
  { uri: "library://playlist/sunday-kitchen", name: "Sunday Kitchen", media_type: "playlist", tracks: [0, 1, 2, 3, 4] },
  { uri: "library://playlist/dinner-jazz", name: "Dinner Jazz", media_type: "playlist", tracks: [2, 4, 0] },
  { uri: "library://radio/moonlight-fm", name: "Moonlight FM", media_type: "radio", tracks: "radio" },
];
const PLAYERS: MediaPlayerOption[] = [
  { entity_id: "media_player.kitchen", name: "Kitchen", state: "playing", music_assistant: true },
  { entity_id: "media_player.living_room", name: "Living Room", state: "idle", music_assistant: true },
  { entity_id: "media_player.lounge_tv", name: "Lounge TV", state: "off", music_assistant: false },
];

const artCache = new Map<string, string>();
function paintArt(t: Track): string {
  const key = t.title;
  const hit = artCache.get(key);
  if (hit) return hit;
  const S = 320;
  const c = document.createElement("canvas");
  c.width = S; c.height = S;
  const g = c.getContext("2d");
  if (!g) return "";
  const [a, b, light] = t.colors;
  const bg = g.createLinearGradient(0, 0, S, S);
  bg.addColorStop(0, a); bg.addColorStop(1, b);
  g.fillStyle = bg; g.fillRect(0, 0, S, S);
  g.fillStyle = light; g.strokeStyle = light;
  if (t.shape === "sun") {
    g.globalAlpha = 0.9; g.beginPath(); g.arc(S * 0.62, S * 0.4, S * 0.2, 0, Math.PI * 2); g.fill();
    g.globalAlpha = 0.35;
    for (let i = 0; i < 6; i++) { g.fillRect(0, S * (0.66 + i * 0.055), S, S * 0.022); }
  } else if (t.shape === "waves") {
    g.lineWidth = S * 0.025; g.globalAlpha = 0.75;
    for (let i = 0; i < 7; i++) {
      g.beginPath();
      for (let x = 0; x <= S; x += 8) g.lineTo(x, S * (0.25 + i * 0.09) + Math.sin(x / 34 + i) * S * 0.03);
      g.stroke();
    }
  } else if (t.shape === "rings") {
    g.lineWidth = S * 0.03;
    for (let i = 1; i <= 6; i++) { g.globalAlpha = 1 - i * 0.13; g.beginPath(); g.arc(S * 0.35, S * 0.62, i * S * 0.075, 0, Math.PI * 2); g.stroke(); }
  } else {
    g.globalAlpha = 0.85; g.beginPath(); g.arc(S * 0.7, S * 0.3, S * 0.08, 0, Math.PI * 2); g.fill();
    [0.62, 0.72, 0.84].forEach((y, i) => {
      g.globalAlpha = 0.25 + i * 0.25; g.beginPath(); g.moveTo(0, S);
      for (let x = 0; x <= S; x += 16) g.lineTo(x, S * y + Math.sin(x / 50 + i * 2) * S * 0.05);
      g.lineTo(S, S); g.fill();
    });
  }
  g.globalAlpha = 1;
  const url = c.toDataURL("image/jpeg", 0.85);
  artCache.set(key, url);
  return url;
}

interface Player {
  state: "playing" | "paused" | "idle" | "off";
  queue: number[] | "radio";
  index: number;
  pos: number;      // seconds at posAt
  posAt: number;    // ms epoch
  volume: number; muted: boolean; shuffle: boolean; repeat: "off" | "all" | "one";
}

export function demoMedia(emit: (...t: Topic[]) => void, players: () => Partial<Record<Layout, string>>): Extras {
  const state = new Map<string, Player>();
  state.set("media_player.kitchen", { state: "playing", queue: [0, 1, 2, 3, 4], index: 0, pos: 52, posAt: Date.now(), volume: 0.32, muted: false, shuffle: false, repeat: "all" });
  state.set("media_player.living_room", { state: "idle", queue: [], index: 0, pos: 0, posAt: Date.now(), volume: 0.2, muted: false, shuffle: false, repeat: "off" });
  state.set("media_player.lounge_tv", { state: "off", queue: [], index: 0, pos: 0, posAt: Date.now(), volume: 0.5, muted: false, shuffle: false, repeat: "off" });
  const timers = new Map<string, ReturnType<typeof setTimeout>>();

  const track = (p: Player): Track | null => p.queue === "radio" ? RADIO : p.queue.length ? TRACKS[p.queue[p.index % p.queue.length]] : null;
  const position = (p: Player) => p.pos + (p.state === "playing" ? (Date.now() - p.posAt) / 1000 : 0);

  /** Advance past finished tracks (lazily, plus a timer so screens hear about it). */
  function settle(entity: string, p: Player) {
    const t = track(p);
    if (p.state === "playing" && t && t.secs) {
      let pos = position(p);
      while (t && pos >= track(p)!.secs) {
        pos -= track(p)!.secs;
        if (!step(p, 1, true)) { pos = 0; break; }
      }
      p.pos = pos; p.posAt = Date.now();
    }
    clearTimeout(timers.get(entity));
    const cur = track(p);
    if (p.state === "playing" && cur && cur.secs) {
      timers.set(entity, setTimeout(() => { settle(entity, p); emit("media"); }, (cur.secs - p.pos) * 1000 + 50));
    }
  }
  /** Move through the queue; false when it ran off the end (playback stops). */
  function step(p: Player, dir: 1 | -1, auto = false): boolean {
    if (p.queue === "radio" || !p.queue.length) return true;
    if (auto && p.repeat === "one") return true;
    let i = p.shuffle && dir === 1 ? p.index + 1 + Math.floor(Math.random() * Math.max(1, p.queue.length - 1)) : p.index + dir;
    if (i >= p.queue.length) {
      if (p.repeat === "off" && auto) { p.state = "idle"; p.index = 0; return false; }
      i = i % p.queue.length;
    }
    if (i < 0) i = p.queue.length - 1;
    p.index = i; p.pos = 0; p.posAt = Date.now();
    return true;
  }

  function out(layout: Layout): NowPlaying {
    const entity = players()[layout] ?? "";
    const now = new Date().toISOString();
    const base: NowPlaying = {
      layout, configured: !!entity, entity: entity || null, name: null, state: "off", show: false, title: null, artist: null,
      album: null, duration: null, position: null, position_updated_at: null, volume: null, muted: null, shuffle: null,
      repeat: null, source: null, app: null, music_assistant: false, has_art: false, art_url: null,
      supports: { play_pause: false, previous: false, next: false, volume: false, mute: false, shuffle: false, repeat: false, seek: false },
      reachable: true, error: null, server_time: now,
    };
    const p = entity ? state.get(entity) : undefined;
    const info = PLAYERS.find((x) => x.entity_id === entity);
    if (!entity) return base;
    if (!p || !info) return { ...base, state: "unavailable" };
    settle(entity, p);
    const t = track(p);
    const ma = info.music_assistant;
    return {
      ...base, name: info.name, state: p.state, show: p.state === "playing" || p.state === "paused" || (p.state === "idle" && !!t),
      title: t?.title ?? null, artist: t?.artist ?? null, album: t?.album ?? null,
      duration: t?.secs || null, position: t?.secs ? p.pos : null, position_updated_at: new Date(p.posAt).toISOString(),
      volume: p.volume, muted: p.muted, shuffle: ma ? p.shuffle : null, repeat: ma ? p.repeat : null,
      source: ma ? "Music Assistant Queue" : null, app: ma ? "music_assistant" : null, music_assistant: ma,
      has_art: !!t, art_url: t ? paintArt(t) : null,
      supports: { play_pause: true, previous: p.queue !== "radio", next: p.queue !== "radio", volume: true, mute: true, shuffle: ma, repeat: ma, seek: false },
    };
  }

  const entityOf = (layout: Layout) => {
    const e = players()[layout];
    if (!e) throw new ApiError(409, `No media player is set for the ${layout} screen`);
    const p = state.get(e);
    if (!p) throw new ApiError(502, `${e} was not found in Home Assistant`);
    return { e, p };
  };
  const later = <T>(x: T) => new Promise<T>((r) => setTimeout(() => r(x), 120)); // a speaker answers a beat later

  return {
    nowPlaying: async (layout) => out(layout),
    async mediaCommand(layout, action: MediaAction, value) {
      const { e, p } = entityOf(layout);
      p.pos = position(p); p.posAt = Date.now();
      switch (action) {
        case "play_pause": p.state = p.state === "playing" ? "paused" : track(p) ? "playing" : p.state; break;
        case "play": if (track(p)) p.state = "playing"; break;
        case "pause": if (p.state === "playing") p.state = "paused"; break;
        case "next": step(p, 1); if (p.state === "idle") p.state = "playing"; break;
        case "previous": if (p.pos > 4) { p.pos = 0; } else step(p, -1); break;
        case "volume_set": {
          const v = Number(value);
          if (!(v >= 0 && v <= 1)) throw new ApiError(400, "value must be a volume between 0 and 1");
          p.volume = Math.round(v * 100) / 100; if (v > 0) p.muted = false; break;
        }
        case "volume_mute": p.muted = !!value; break;
        case "shuffle_set": p.shuffle = !!value; break;
        case "repeat_set": p.repeat = value === "all" || value === "one" ? value : "off"; break;
        default: throw new ApiError(400, "Unknown action");
      }
      settle(e, p);
      emit("media");
      return later(out(layout));
    },
    mediaPlayers: async () => PLAYERS.map((x) => ({ ...x, state: state.get(x.entity_id)?.state ?? x.state })),
    async mediaFavourites(layout) {
      const e = players()[layout];
      const info = PLAYERS.find((x) => x.entity_id === e);
      return info?.music_assistant ? FAVOURITES.map(({ uri, name, media_type }) => ({ uri, name, media_type })) : [];
    },
    async playFavourite(layout, uri) {
      const { e, p } = entityOf(layout);
      const fav = FAVOURITES.find((f) => f.uri === uri);
      if (!fav) throw new ApiError(404, "That isn't one of the Music Assistant favourites");
      p.queue = fav.tracks === "radio" ? "radio" : [...fav.tracks];
      p.index = 0; p.pos = 0; p.posAt = Date.now(); p.state = "playing";
      settle(e, p);
      emit("media");
      return later(out(layout));
    },
  };
}
