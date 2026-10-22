// Demo-mode music: a pretend kitchen speaker playing made-up tracks. The album art is painted on a canvas at
// runtime (abstract shapes, nothing copyrighted) and handed out as a data: URL.
import {
  Api, ApiError, Enqueue, Layout, MediaAction, MediaBrowse, MediaFavourite, MediaItem, MediaPlayerOption, MediaRooms,
  MusicAssistantLink, NowPlaying, QueueTrack, Topic,
} from "./types";

type Extras = Pick<Api, "nowPlaying" | "mediaCommand" | "mediaPlayers" | "mediaFavourites" | "playFavourite" | "mediaQueue"
  | "mediaQueueAction" | "mediaBrowse" | "mediaSearch" | "mediaPlay" | "mediaRooms" | "mediaRoomAction" | "musicAssistant"
  | "saveMusicAssistant" | "removeMusicAssistant">;

interface Track { title: string; artist: string; album: string; secs: number; colors: [string, string, string]; shape: "sun" | "waves" | "rings" | "hills" }
const TRACKS: Track[] = [
  { title: "Saturday Pancakes", artist: "The Marmalade Collective", album: "Kitchen Radio", secs: 214, colors: ["#F6B26B", "#E06C75", "#FFE9C7"], shape: "sun" },
  { title: "Window Light", artist: "Juniper & Vale", album: "Slow Mornings", secs: 187, colors: ["#5B8DEF", "#A7C7F2", "#F4F7FB"], shape: "waves" },
  { title: "Copper Kettle Waltz", artist: "Orla Finch Trio", album: "Small Rooms", secs: 242, colors: ["#2F4858", "#C9844B", "#F3D9A4"], shape: "rings" },
  { title: "Lanterns", artist: "Northbound Tide", album: "Harbour Songs", secs: 199, colors: ["#3B2C55", "#B86FC4", "#FFD3A1"], shape: "hills" },
  { title: "Green Tomato Swing", artist: "Dot & the Dashes", album: "Sunday Best", secs: 176, colors: ["#2FB58A", "#F2C94C", "#FDF6E3"], shape: "sun" },
  // 5..
  { title: "Porch Light", artist: "Juniper & Vale", album: "Slow Mornings", secs: 201, colors: ["#5B8DEF", "#A7C7F2", "#F4F7FB"], shape: "waves" },
  { title: "Tidewater", artist: "Northbound Tide", album: "Harbour Songs", secs: 233, colors: ["#3B2C55", "#B86FC4", "#FFD3A1"], shape: "hills" },
  { title: "Hallway Shoes", artist: "Orla Finch Trio", album: "Small Rooms", secs: 168, colors: ["#2F4858", "#C9844B", "#F3D9A4"], shape: "rings" },
  { title: "Paper Boats", artist: "Northbound Tide", album: "Harbour Songs", secs: 190, colors: ["#3B2C55", "#B86FC4", "#FFD3A1"], shape: "hills" },
  { title: "Sleepy Tuesday", artist: "Juniper & Vale", album: "Slow Mornings", secs: 222, colors: ["#5B8DEF", "#A7C7F2", "#F4F7FB"], shape: "waves" },
  { title: "Marmalade Sky", artist: "The Marmalade Collective", album: "Kitchen Radio", secs: 207, colors: ["#F6B26B", "#E06C75", "#FFE9C7"], shape: "sun" },
  { title: "Big Band Breakfast", artist: "Dot & the Dashes", album: "Sunday Best", secs: 189, colors: ["#2FB58A", "#F2C94C", "#FDF6E3"], shape: "sun" },
  { title: "Attic Window", artist: "Orla Finch Trio", album: "Small Rooms", secs: 251, colors: ["#2F4858", "#C9844B", "#F3D9A4"], shape: "rings" },
  // Podcast episodes 13..
  { title: "The Dragon Who Couldn't Sneeze", artist: "Bedtime Tales", album: "Bedtime Tales", secs: 912, colors: ["#243B55", "#F7B267", "#FFF3D6"], shape: "rings" },
  { title: "The Moon's Lost Sock", artist: "Bedtime Tales", album: "Bedtime Tales", secs: 845, colors: ["#243B55", "#F7B267", "#FFF3D6"], shape: "rings" },
  { title: "Volcanoes!", artist: "Curious Kids", album: "Curious Kids", secs: 1320, colors: ["#E4572E", "#FFC914", "#FFF8E8"], shape: "hills" },
  { title: "Why Do Cats Purr?", artist: "Curious Kids", album: "Curious Kids", secs: 1205, colors: ["#E4572E", "#FFC914", "#FFF8E8"], shape: "hills" },
];
const ALBUMS = [...new Set(TRACKS.slice(0, 13).map((t) => t.album))].map((name, i) => ({
  id: `library://album/${i + 1}`, name, artist: TRACKS.find((t) => t.album === name)!.artist,
  tracks: TRACKS.map((t, k) => (t.album === name ? k : -1)).filter((k) => k >= 0),
}));
const PODCASTS = ["Bedtime Tales", "Curious Kids"].map((name, i) => ({
  id: `library://podcast/${i + 1}`, name, tracks: TRACKS.map((t, k) => (t.album === name ? k : -1)).filter((k) => k >= 0),
}));
const ARTISTS = [...new Set(TRACKS.slice(0, 13).map((t) => t.artist))];
const RADIO: Track = { title: "Moonlight FM", artist: "Easy listening, all day", album: "Live radio", secs: 0, colors: ["#1B2A4A", "#6C7BF0", "#FFFFFF"], shape: "waves" };
const FAVOURITES: (MediaFavourite & { tracks: number[] | "radio" })[] = [
  { uri: "library://playlist/sunday-kitchen", name: "Sunday Kitchen", media_type: "playlist", tracks: [0, 1, 2, 3, 4, 9, 10, 5] },
  { uri: "library://playlist/dinner-jazz", name: "Dinner Jazz", media_type: "playlist", tracks: [2, 4, 7, 12, 0] },
  { uri: "library://playlist/school-run", name: "School Run", media_type: "playlist", tracks: [4, 10, 0, 6, 8] },
  { uri: "library://radio/moonlight-fm", name: "Moonlight FM", media_type: "radio", tracks: "radio" },
];
const PLAYERS: MediaPlayerOption[] = [
  { entity_id: "media_player.kitchen", name: "Kitchen", state: "playing", music_assistant: true },
  { entity_id: "media_player.living_room", name: "Living Room", state: "idle", music_assistant: true },
  { entity_id: "media_player.dining_room", name: "Dining Room", state: "idle", music_assistant: true },
  { entity_id: "media_player.playroom", name: "Playroom", state: "idle", music_assistant: true },
  { entity_id: "media_player.lounge_tv", name: "Lounge TV", state: "off", music_assistant: false },
];

const artCache = new Map<string, string>();
function paintArt(t: Track): string {
  const key = t.album + t.shape;
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

export function demoMedia(emit: (...t: Topic[]) => void, players: () => Partial<Record<Layout, string>>, checkPin: (pin: string) => void): Extras {
  const state = new Map<string, Player>();
  state.set("media_player.kitchen", { state: "playing", queue: [0, 1, 2, 3, 4, 9, 10, 5, 7], index: 0, pos: 52, posAt: Date.now(), volume: 0.32, muted: false, shuffle: false, repeat: "all" });
  state.set("media_player.living_room", { state: "idle", queue: [], index: 0, pos: 0, posAt: Date.now(), volume: 0.2, muted: false, shuffle: false, repeat: "off" });
  state.set("media_player.dining_room", { state: "idle", queue: [], index: 0, pos: 0, posAt: Date.now(), volume: 0.25, muted: false, shuffle: false, repeat: "off" });
  state.set("media_player.playroom", { state: "idle", queue: [], index: 0, pos: 0, posAt: Date.now(), volume: 0.15, muted: false, shuffle: false, repeat: "off" });
  const groups = new Map<string, string>([["media_player.dining_room", "media_player.kitchen"]]); // member -> leader
  let ma: MusicAssistantLink = { url: "", detected_url: "http://homeassistant.local:8095", token_set: false };
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
      supports: { play_pause: false, previous: false, next: false, volume: false, mute: false, shuffle: false, repeat: false, seek: false, grouping: false },
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
      supports: { play_pause: true, previous: p.queue !== "radio", next: p.queue !== "radio", volume: true, mute: true, shuffle: ma, repeat: ma, seek: false, grouping: ma },
    };
  }

  const entityOf = (layout: Layout) => {
    const e = players()[layout];
    if (!e) throw new ApiError(409, `No media player is set for the ${layout} screen`);
    const p = state.get(e);
    if (!p) throw new ApiError(502, `${e} was not found in Home Assistant`);
    return { e, p };
  };
  function rooms(e: string): MediaRooms {
    const ma = PLAYERS.find((x) => x.entity_id === e)?.music_assistant ?? false;
    const leaderOf = (x: string) => groups.get(x) ?? x;
    const list = PLAYERS.filter((x) => x.entity_id === e || (ma && x.music_assistant)).map((x) => {
      const p = state.get(x.entity_id)!;
      const lead = state.get(leaderOf(x.entity_id))!;
      const t = track(lead);
      return { entity_id: x.entity_id, name: x.name, state: lead.state, this: x.entity_id === e,
        grouped: x.entity_id === e || leaderOf(x.entity_id) === leaderOf(e), volume: p.volume, muted: p.muted,
        playing: lead.state === "playing" || lead.state === "paused" ? t?.title ?? null : null, can_volume: true };
    });
    list.sort((a, b) => Number(b.this) - Number(a.this) || Number(b.grouped) - Number(a.grouped) || a.name.localeCompare(b.name));
    return { entity: e, can_group: ma, rooms: list };
  }
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
    async mediaQueue(layout) {
      const { e, p } = entityOf(layout);
      settle(e, p);
      if (p.queue === "radio" || !p.queue.length) return { source: "music_assistant", full: true, total: 0, current: null, items: [], can_jump: false, can_remove: false, can_move: false };
      const items: QueueTrack[] = p.queue.slice(p.index).map((k, i) => {
        const t = TRACKS[k];
        return { key: String(p.index + i), index: p.index + i, title: t.title, artist: t.artist, album: t.album, duration: t.secs, thumb: paintArt(t), current: i === 0 };
      });
      return { source: "music_assistant", full: ma.token_set, total: p.queue.length, current: p.index,
        items: ma.token_set ? items : items.slice(0, 2), can_jump: ma.token_set, can_remove: ma.token_set, can_move: ma.token_set };
    },
    async mediaQueueAction(layout, action, key) {
      const { e, p } = entityOf(layout);
      if (!ma.token_set) throw new ApiError(409, "Changing the queue needs Music Assistant connected in Settings > Music");
      const i = Number(key);
      if (p.queue === "radio" || !(i >= 0 && i < p.queue.length)) throw new ApiError(400, "That track isn't in the queue");
      if (action === "play") { p.index = i; p.pos = 0; p.posAt = Date.now(); p.state = "playing"; }
      else if (action === "remove") { p.queue.splice(i, 1); if (i < p.index) p.index--; }
      else { const [k] = p.queue.splice(i, 1); p.queue.splice(p.index + (i < p.index ? 0 : 1), 0, k); }
      settle(e, p);
      emit("media");
    },
    async mediaBrowse(layout, id, type) {
      entityOf(layout);
      const dir = (iid: string, title: string, kind: string): MediaItem => ({ id: iid, type: "music_assistant", title, subtitle: null, kind, can_play: false, can_expand: true, thumb: null });
      const albumItem = (a: (typeof ALBUMS)[number]): MediaItem => ({ id: a.id, type: "album", title: a.name, subtitle: a.artist, kind: "album", can_play: true, can_expand: true, thumb: paintArt(TRACKS[a.tracks[0]]) });
      const trackItem = (k: number): MediaItem => ({ id: `library://track/${k}`, type: "track", title: TRACKS[k].title, subtitle: TRACKS[k].artist, kind: "track", can_play: true, can_expand: false, thumb: paintArt(TRACKS[k]) });
      const wrap = (head: MediaItem, items: MediaItem[]): MediaBrowse => ({ ...head, items, more: 0 });
      await new Promise((r) => setTimeout(r, 80));
      if (id === undefined || id === "") return wrap(dir("", "Music Assistant", "directory"), [
        dir("artists", "Artists", "directory"), dir("albums", "Albums", "directory"), dir("tracks", "Tracks", "directory"),
        dir("playlists", "Playlists", "directory"), dir("radio", "Radio stations", "directory"), dir("podcasts", "Podcasts", "directory"),
        dir("audiobooks", "Audiobooks", "directory")]);
      if (id === "albums") return wrap(dir("albums", "Albums", "directory"), ALBUMS.map(albumItem));
      if (id === "tracks") return wrap(dir("tracks", "Tracks", "directory"), TRACKS.slice(0, 13).map((_, k) => trackItem(k)));
      if (id === "artists") return wrap(dir("artists", "Artists", "directory"), ARTISTS.map((a, i) => ({ id: `library://artist/${i}`, type: "artist", title: a, subtitle: null, kind: "artist", can_play: true, can_expand: true, thumb: paintArt(TRACKS.find((t) => t.artist === a)!) })));
      if (id === "playlists") return wrap(dir("playlists", "Playlists", "directory"), FAVOURITES.filter((f) => f.tracks !== "radio").map((f) => ({ id: f.uri, type: "playlist", title: f.name, subtitle: null, kind: "playlist", can_play: true, can_expand: true, thumb: paintArt(TRACKS[(f.tracks as number[])[0]]) })));
      if (id === "radio") return wrap(dir("radio", "Radio stations", "directory"), [{ id: "library://radio/moonlight-fm", type: "radio", title: "Moonlight FM", subtitle: null, kind: "radio", can_play: true, can_expand: false, thumb: paintArt(RADIO) }]);
      if (id === "podcasts") return wrap(dir("podcasts", "Podcasts", "directory"), PODCASTS.map((p) => ({ id: p.id, type: "podcast", title: p.name, subtitle: null, kind: "podcast", can_play: true, can_expand: true, thumb: paintArt(TRACKS[p.tracks[0]]) })));
      if (id === "audiobooks") return wrap(dir("audiobooks", "Audiobooks", "directory"), []);
      const album = ALBUMS.find((a) => a.id === id);
      if (album) return wrap(albumItem(album), album.tracks.map(trackItem));
      const pod = PODCASTS.find((p) => p.id === id);
      if (pod) return wrap({ id: pod.id, type: "podcast", title: pod.name, subtitle: null, kind: "podcast", can_play: true, can_expand: true, thumb: paintArt(TRACKS[pod.tracks[0]]) },
        pod.tracks.map((k) => ({ ...trackItem(k), id: `library://podcast_episode/${k}`, type: "podcast_episode", kind: "episode" })));
      const list = FAVOURITES.find((f) => f.uri === id && f.tracks !== "radio");
      if (list) return wrap({ id: list.uri, type: "playlist", title: list.name, subtitle: null, kind: "playlist", can_play: true, can_expand: true, thumb: paintArt(TRACKS[(list.tracks as number[])[0]]) }, (list.tracks as number[]).map(trackItem));
      const artist = /^library:\/\/artist\/(\d+)$/.exec(id ?? "");
      if (artist) {
        const name = ARTISTS[Number(artist[1])];
        return wrap({ id: id!, type: type ?? "artist", title: name, subtitle: null, kind: "artist", can_play: true, can_expand: true, thumb: null }, ALBUMS.filter((a) => a.artist === name).map(albumItem));
      }
      throw new ApiError(400, "Couldn't open that: Media not found");
    },
    async mediaSearch(layout, q) {
      const { e } = entityOf(layout);
      if (!PLAYERS.find((x) => x.entity_id === e)?.music_assistant) throw new ApiError(409, "Search needs a Music Assistant speaker");
      const n = q.trim().toLowerCase();
      if (!n) return [];
      const out: MediaItem[] = [];
      ALBUMS.filter((a) => (a.name + " " + a.artist).toLowerCase().includes(n)).forEach((a) => out.push({ id: a.id, type: "album", title: a.name, subtitle: a.artist, kind: "album", can_play: true, can_expand: true, thumb: paintArt(TRACKS[a.tracks[0]]) }));
      PODCASTS.filter((p) => p.name.toLowerCase().includes(n)).forEach((p) => out.push({ id: p.id, type: "podcast", title: p.name, subtitle: null, kind: "podcast", can_play: true, can_expand: true, thumb: paintArt(TRACKS[p.tracks[0]]) }));
      TRACKS.slice(0, 13).forEach((t, k) => { if ((t.title + " " + t.artist).toLowerCase().includes(n)) out.push({ id: `library://track/${k}`, type: "track", title: t.title, subtitle: t.artist, kind: "track", can_play: true, can_expand: false, thumb: paintArt(t) }); });
      return out;
    },
    async mediaPlay(layout, item, enqueue: Enqueue) {
      const { e, p } = entityOf(layout);
      const ids = (id: string): number[] | "radio" => {
        if (id.startsWith("library://radio/")) return "radio";
        const tr = /^library:\/\/(?:track|podcast_episode)\/(\d+)$/.exec(id);
        if (tr) return [Number(tr[1])];
        const a = ALBUMS.find((x) => x.id === id) ?? PODCASTS.find((x) => x.id === id);
        if (a) return [...a.tracks];
        const f = FAVOURITES.find((x) => x.uri === id);
        if (f) return f.tracks === "radio" ? "radio" : [...f.tracks];
        const ar = /^library:\/\/artist\/(\d+)$/.exec(id);
        if (ar) return ALBUMS.filter((x) => x.artist === ARTISTS[Number(ar[1])]).flatMap((x) => x.tracks);
        throw new ApiError(400, "Home Assistant rejected music_assistant.play_media: Media not found");
      };
      const add = ids(item.id);
      p.pos = position(p); p.posAt = Date.now();
      if (add === "radio" || p.queue === "radio" || enqueue === "replace" || !p.queue.length) {
        p.queue = add; p.index = 0; p.pos = 0; p.state = "playing";
      } else if (enqueue === "next") {
        p.queue.splice(p.index + 1, 0, ...add);
      } else {
        p.queue.push(...add);
      }
      settle(e, p);
      emit("media");
      return later(out(layout));
    },
    async mediaRooms(layout) {
      const { e } = entityOf(layout);
      return rooms(e);
    },
    async mediaRoomAction(layout, room, action, value) {
      const { e } = entityOf(layout);
      if (!rooms(e).rooms.some((r) => r.entity_id === room)) throw new ApiError(404, "That speaker can't be grouped with this one");
      const p = state.get(room)!;
      if (action === "join") { if (room === e) throw new ApiError(400, "A speaker is always in its own group"); groups.set(room, e); }
      else if (action === "unjoin") groups.delete(room);
      else if (action === "volume") { p.volume = Math.round(Number(value) * 100) / 100; if (p.volume > 0) p.muted = false; }
      else if (action === "mute") p.muted = !!value;
      emit("media");
      return later(rooms(e));
    },
    musicAssistant: async () => ({ ...ma }),
    async saveMusicAssistant({ pin, token, url }) {
      checkPin(pin);
      if (!token && !ma.token_set) throw new ApiError(400, "token is required: make one in Music Assistant under Settings > Profile");
      if (token && token.length < 8) throw new ApiError(400, "Music Assistant didn't accept the token");
      ma = { ...ma, url: url.trim(), token_set: true };
      emit("media");
      return { ...ma };
    },
    async removeMusicAssistant(pin) {
      checkPin(pin);
      ma = { ...ma, token_set: false };
      emit("media");
      return { ...ma };
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
