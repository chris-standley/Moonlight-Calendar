import { AlertsNow, Api, ApiError, Cookbook, Display, MediaBrowse, MediaItem, MediaQueue, NowPlaying, NurseryUpdate, SecurityAlert, SecurityOverview, Recipe, RecipeBatch, ScreensaverPhotos, HiddenPhoto, Topic, UploadedImage } from "./types";
import { authStatus, getToken, notifyUnpaired } from "./pairing";

const PING_MS = 25_000;
const ALL_TOPICS: Topic[] = ["people", "events", "chores", "points", "rewards", "lists", "meals", "recipes", "settings", "photos",
  "displays", "accounts", "media", "security", "security_alert", "nursery", "alerts", "energy"];

/** Talks to the Moonlight add-on. `base` is "" when served by the add-on itself (works under HA ingress too). */
export function httpApi(base = ""): Api {
  const listeners = new Set<(t: Topic) => void>();

  async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
    const headers: Record<string, string> = {};
    const token = getToken();
    if (token) headers.Authorization = `Bearer ${token}`;
    const raw = body instanceof Blob;
    if (body !== undefined) headers["Content-Type"] = raw ? (body.type || "application/octet-stream") : "application/json";
    const res = await fetch(base + path, {
      method,
      headers,
      body: body === undefined ? undefined : raw ? body : JSON.stringify(body),
    });
    if (res.status === 401) notifyUnpaired(); // revoked or never paired: back to the pairing screen
    if (!res.ok) {
      let msg = res.statusText;
      try { msg = (await res.json()).detail ?? msg; } catch { /* not json, e.g. a proxy's error page */ }
      // Never an empty toast: proxies (Home Assistant ingress) often send no status text.
      if (!String(msg ?? "").trim()) msg = res.status >= 500 ? `Moonlight didn't answer properly (error ${res.status}). Try again in a moment.` : `Request failed (error ${res.status})`;
      throw new ApiError(res.status, String(msg));
    }
    return res.json() as Promise<T>;
  }
  const get = <T>(p: string) => req<T>("GET", p);
  async function download(path: string): Promise<{ file: Blob; name: string }> {
    const token = getToken();
    const res = await fetch(base + path, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
    if (res.status === 401) notifyUnpaired();
    if (!res.ok) throw new ApiError(res.status, `Couldn't make the file (error ${res.status})`);
    const name = /filename="([^"]+)"/.exec(res.headers.get("Content-Disposition") ?? "")?.[1] ?? "Moonlight recipes";
    return { file: await res.blob(), name };
  }
  const q = (o: Record<string, string>) => "?" + new URLSearchParams(o).toString();
  // Picture urls are absolute API paths; under Home Assistant ingress they need the ingress prefix.
  const pic = (u: string | null) => (u ? base + u : null);
  const rec = (r: Recipe): Recipe => ({ ...r, photo_url: pic(r.photo_url), steps: r.steps.map((s) => ({ ...s, photo_url: pic(s.photo_url) })) });
  const recipe = async (p: Promise<Recipe>) => rec(await p);
  const batch = (b: RecipeBatch): RecipeBatch => ({ ...b, drafts: b.drafts.map((d) => ({ ...d, recipe: rec(d.recipe) })) });
  const cam = <T extends { live_url: string; snapshot_url: string; video_url: string | null; video_hd_url: string | null }>(c: T): T =>
    ({ ...c, live_url: base + c.live_url, snapshot_url: base + c.snapshot_url, video_url: c.video_url && base + c.video_url,
      video_hd_url: c.video_hd_url && base + c.video_hd_url });
  const artUrl = async (p: Promise<NowPlaying>): Promise<NowPlaying> => { const np = await p; return { ...np, art_url: np.art_url && base + np.art_url }; };

  let ws: WebSocket | null = null;
  let serverVersion: string | null = null; // from the first "hello"; a different one later means Moonlight was updated
  let heard = 0; // when the socket last brought anything (a pong at least every PING_MS while it's alive)
  let connections = 0;
  let up = false;
  let again: ReturnType<typeof setTimeout> | undefined; // the next attempt after a drop
  const watchers = new Set<(up: boolean) => void>();
  function setUp(u: boolean) {
    if (u === up) return;
    up = u;
    watchers.forEach((w) => w(u));
  }
  function connect() {
    clearTimeout(again);
    const url = new URL(base + "/api/ws", location.href);
    url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
    const token = getToken();
    if (token) url.searchParams.set("token", token);
    const sock = new WebSocket(url);
    ws = sock;
    heard = Date.now();
    // A screen whose Wi-Fi dozed (old tablets do) can be left holding a socket that's dead without ever closing, and
    // would miss every change from then on. Ask for a pong now and then; when nothing comes back, start again.
    const keepalive = setInterval(() => {
      if (sock.readyState === WebSocket.CLOSING || sock.readyState === WebSocket.CLOSED) { clearInterval(keepalive); return; }
      if (Date.now() - heard > PING_MS * 2.5) {
        // close() on a dead connection can take minutes to report back, so don't wait for it.
        clearInterval(keepalive);
        sock.onclose = null;
        sock.close();
        if (ws === sock) ws = null;
        setUp(false);
        connect();
        return;
      }
      if (sock.readyState === WebSocket.OPEN) try { sock.send("ping"); } catch { /* closing anyway */ }
    }, PING_MS);
    sock.onopen = () => {
      setUp(true);
      // Back after a gap: anything could have changed meanwhile, so everything showing loads again.
      if (connections++ > 0) ALL_TOPICS.forEach((t) => listeners.forEach((l) => l(t)));
    };
    sock.onmessage = (m) => {
      heard = Date.now();
      try {
        const msg = JSON.parse(m.data);
        // Wall screens stay open for weeks: after an update, load the new screens instead of running the old code.
        if (msg.type === "hello" && msg.version) {
          if (serverVersion && serverVersion !== msg.version) location.reload();
          serverVersion = msg.version;
        }
        if (msg.type === "changed") listeners.forEach((l) => l(msg.topic));
        // A screen was revoked: if it was this one, drop back to pairing straight away.
        if (msg.type === "changed" && msg.topic === "displays") {
          authStatus(base).then((s) => { if (!s.authorised) notifyUnpaired(); }).catch(() => { /* offline */ });
        }
      } catch { /* ignore */ }
    };
    sock.onclose = () => {
      clearInterval(keepalive);
      if (ws !== sock) return; // already replaced
      ws = null;
      setUp(false);
      again = setTimeout(connect, 3000);
    };
  }

  return {
    mode: "live",
    subscribe(fn) {
      listeners.add(fn);
      if (!ws) connect();
      return () => listeners.delete(fn);
    },
    connection(fn) {
      watchers.add(fn);
      fn(up);
      return () => watchers.delete(fn);
    },
    reconnect() {
      if (ws?.readyState === WebSocket.OPEN) return;
      const old = ws;
      ws = null;
      if (old) { old.onclose = null; try { old.close(); } catch { /* already gone */ } }
      connect();
    },
    async alerts() {
      const r = await get<AlertsNow>("/api/alerts");
      return { ...r, alerts: r.alerts.map((a) => ({ ...a, image: a.image?.startsWith("/") ? base + a.image : a.image })) };
    },
    createAlert: (a) => req("POST", "/api/alerts", a),
    dismissAlert: async (id) => { await req("POST", `/api/alerts/${encodeURIComponent(id)}/dismiss`); },
    settings: () => get("/api/settings"),
    updateSettings: (patch) => req("PATCH", "/api/settings", patch),
    verifyPin: async (pin) => (await req<{ ok: boolean }>("POST", "/api/pin/verify", { pin })).ok,
    people: () => get("/api/people"),
    createPerson: (p) => req("POST", "/api/people", p),
    updatePerson: (id, patch) => req("PATCH", `/api/people/${id}`, patch),
    deletePerson: async (id, pin) => { await req("DELETE", `/api/people/${id}`, { pin }); },
    events: (start, end) => get("/api/events" + q({ start, end })),
    createEvent: (e) => req("POST", "/api/events", e),
    updateEvent: (id, e) => req("PATCH", `/api/events/${id}`, e),
    deleteEvent: async (id) => { await req("DELETE", `/api/events/${id}`); },
    allChores: () => get("/api/chores/all"),
    chores: (date) => get("/api/chores" + q({ date })),
    createChore: (c) => req("POST", "/api/chores", c),
    updateChore: (id, patch) => req("PATCH", `/api/chores/${id}`, patch),
    deleteChore: async (id) => { await req("DELETE", `/api/chores/${id}`); },
    completeChore: async (id, date) => (await req<{ balance: number }>("POST", `/api/chores/${id}/complete`, { date })).balance,
    uncompleteChore: async (id, date) => (await req<{ balance: number }>("DELETE", `/api/chores/${id}/complete` + q({ date }))).balance,
    points: () => get("/api/points"),
    ledger: (pid) => get(`/api/points/${pid}/ledger`),
    adjustPoints: async (person_id, change, reason, pin) =>
      (await req<{ balance: number }>("POST", "/api/points/adjust", { person_id, change, reason, pin })).balance,
    rewards: () => get("/api/rewards"),
    createReward: (r) => req("POST", "/api/rewards", r),
    updateReward: (id, patch) => req("PATCH", `/api/rewards/${id}`, patch),
    deleteReward: async (id) => { await req("DELETE", `/api/rewards/${id}`); },
    redeem: async (rid, person_id, pin) => (await req<{ balance: number }>("POST", `/api/rewards/${rid}/redeem`, { person_id, pin })).balance,
    lists: () => get("/api/lists"),
    createList: (l) => req("POST", "/api/lists", l),
    updateList: (id, patch) => req("PATCH", `/api/lists/${id}`, patch),
    deleteList: async (id) => { await req("DELETE", `/api/lists/${id}`); },
    items: (lid) => get(`/api/lists/${lid}/items`),
    addItem: (lid, title, person_id = null, due = null) => req("POST", `/api/lists/${lid}/items`, { title, person_id, due }),
    updateItem: (id, patch) => req("PATCH", `/api/items/${id}`, patch),
    deleteItem: async (id) => { await req("DELETE", `/api/items/${id}`); },
    clearDone: async (lid) => { await req("POST", `/api/lists/${lid}/clear-done`); },
    meals: (start, end) => get("/api/meals" + q({ start, end })),
    createMeal: (m) => req("POST", "/api/meals", m),
    updateMeal: (id, m) => req("PATCH", `/api/meals/${id}`, m),
    deleteMeal: async (id) => { await req("DELETE", `/api/meals/${id}`); },
    recipes: async () => (await get<Recipe[]>("/api/recipes")).map(rec),
    createRecipe: (r) => recipe(req("POST", "/api/recipes", r)),
    recipeCooked: (id) => recipe(req("POST", `/api/recipes/${id}/cooked`, {})),
    previewRecipe: (r) => recipe(req("POST", "/api/recipes/preview", r)),
    importRecipe: (from) => recipe(req("POST", "/api/recipes/import", from)),
    async uploadImage(data) { const r = await req<UploadedImage>("POST", "/api/images", data); return { ...r, url: base + r.url }; },
    recipeReader: () => get("/api/recipes-reader"),
    recipeBatches: async () => (await get<RecipeBatch[]>("/api/recipes-batches")).map(batch),
    scanCookbook: async (images, cheaper = false, book = "", isbn) => batch(await req<RecipeBatch>("POST", "/api/recipes-batches", { images, cheaper, book, isbn })),
    findCookbook: async (isbn) => { const b = await get<Cookbook>(`/api/cookbooks/${encodeURIComponent(isbn)}`); return { ...b, cover_url: pic(b.cover_url) }; },
    retryBatch: async (id) => batch(await req<RecipeBatch>("POST", `/api/recipes-batches/${id}/retry`, {})),
    deleteBatch: async (id) => { await req("DELETE", `/api/recipes-batches/${id}`); },
    saveAllDrafts: async (id) => (await req<{ saved: number }>("POST", `/api/recipes-batches/${id}/save-all`, {})).saved,
    saveDraft: (id, r) => recipe(req("POST", `/api/recipe-drafts/${id}/save`, r ?? {})),
    dismissDraft: async (id) => { await req("DELETE", `/api/recipe-drafts/${id}`); },
    exportRecipes: (format) => download("/api/recipes/export" + q({ format })),
    importRecipes: (file) => req("POST", "/api/recipes/collection", file),
    saveRecipeReader: (r) => req("PUT", "/api/recipes-reader", r),
    removeRecipeReader: (pin) => req("DELETE", "/api/recipes-reader", { pin }),
    sampleData: () => get("/api/sample-data"),
    removeSampleData: async (pin) => (await req<{ removed: number }>("POST", "/api/sample-data/remove", { pin })).removed,
    updateRecipe: (id, patch) => recipe(req("PATCH", `/api/recipes/${id}`, patch)),
    deleteRecipe: async (id) => { await req("DELETE", `/api/recipes/${id}`); },
    recipeToList: async (rid, list_id, items) => (await req<{ added: number }>("POST", `/api/recipes/${rid}/to-list`, { list_id, items })).added,
    weather: () => get("/api/weather"),
    weatherEntities: () => get("/api/weather/entities"),
    holidays: (start, end, r) => get(`/api/holidays?start=${start}&end=${end}${r ? `&country=${encodeURIComponent(r.country)}&subdiv=${encodeURIComponent(r.subdiv)}` : ""}`),
    holidayCountries: () => get("/api/holidays/countries"),
    displays: () => get("/api/displays"),
    approveDisplay: (code, name, layout, pin) => req("POST", "/api/displays/approve", { code, name, layout, pin }),
    revokeDisplay: async (id, pin) => { await req("DELETE", `/api/displays/${id}`, { pin }); },
    updateDisplay: (id, patch) => req("PATCH", `/api/displays/${id}`, patch),
    thisScreen: async () => (await get<{ display: Display | null }>("/api/auth/status")).display,
    immich: () => get("/api/immich"),
    saveImmich: (c) => req("PUT", "/api/immich", c),
    disconnectImmich: async (pin) => { await req("DELETE", "/api/immich", { pin }); },
    testImmich: (t) => req("POST", "/api/immich/test", t),
    immichAlbums: () => get("/api/immich/albums"),
    async screensaverPhotos() {
      const r = await get<ScreensaverPhotos>("/api/screensaver/photos");
      return { ...r, photos: r.photos.map((p) => ({ ...p, url: base + p.url })) };
    },
    hidePhoto: (id) => req("POST", `/api/screensaver/photos/${id}/hide`),
    async hiddenPhotos(limit, offset = 0) {
      const r = await get<{ total: number; photos: HiddenPhoto[] }>(`/api/immich/hidden?limit=${limit}&offset=${offset}`);
      return { ...r, photos: r.photos.map((p) => ({ ...p, url: base + p.url })) };
    },
    restorePhoto: async (id, pin) => { await req("POST", `/api/immich/hidden/${id}/restore`, { pin }); },
    nursery: () => get("/api/nursery"),
    saveNursery: (c) => req("PUT", "/api/nursery", c),
    disconnectNursery: async (pin) => { await req("DELETE", "/api/nursery", { pin }); },
    syncNursery: () => req("POST", "/api/nursery/sync"),
    nurseryUpdates: async () => (await get<NurseryUpdate[]>("/api/nursery/updates"))
      .map((u) => ({ ...u, photos: u.photos.map((p) => ({ ...p, url: base + p.url })) })),
    accounts: () => get("/api/accounts"),
    connectAccount: (a) => req("POST", "/api/accounts", a),
    reconnectAccount: (id, creds) => req("PATCH", `/api/accounts/${id}`, creds),
    removeAccount: async (id, pin) => { await req("DELETE", `/api/accounts/${id}`, { pin }); },
    syncAccount: (id) => req("POST", `/api/accounts/${id}/sync`),
    previewFeed: (url) => req("POST", "/api/accounts/feed-preview", { url }),
    addFeed: (f) => req("POST", "/api/accounts", { kind: "ics", ...f }),
    haCalendars: () => get("/api/ha/calendars"),
    addHaCalendar: (f) => req("POST", "/api/accounts", { kind: "ha", ...f }),
    updateFeed: (id, patch) => req("PATCH", `/api/accounts/${id}`, patch),
    calendars: () => get("/api/calendars"),
    updateCalendar: (id, patch) => req("PATCH", `/api/calendars/${id}`, patch),
    nowPlaying: (layout) => artUrl(get("/api/media/now-playing" + q({ layout }))),
    mediaCommand: (layout, action, value) => artUrl(req("POST", "/api/media/command", { layout, action, value })),
    mediaPlayers: () => get("/api/media/players"),
    mediaFavourites: (layout) => get("/api/media/favourites" + q({ layout })),
    playFavourite: (layout, uri) => artUrl(req("POST", "/api/media/play", { layout, uri })),
    async mediaQueue(layout) {
      const r = await get<MediaQueue>("/api/media/queue" + q({ layout }));
      return { ...r, items: r.items.map((t) => ({ ...t, thumb: pic(t.thumb) })) };
    },
    mediaQueueAction: async (layout, action, key) => { await req("POST", "/api/media/queue", { layout, action, key }); },
    async mediaBrowse(layout, id, type) {
      const r = await get<MediaBrowse>("/api/media/browse" + q({ layout, ...(id !== undefined ? { id, type: type ?? "" } : {}) }));
      return { ...r, thumb: pic(r.thumb), items: r.items.map((i) => ({ ...i, thumb: pic(i.thumb) })) };
    },
    mediaSearch: async (layout, text) => (await get<MediaItem[]>("/api/media/search" + q({ layout, q: text }))).map((i) => ({ ...i, thumb: pic(i.thumb) })),
    mediaPlay: (layout, item, enqueue) => artUrl(req("POST", "/api/media/play", { layout, id: item.id, type: item.type, enqueue })),
    mediaRooms: (layout) => get("/api/media/rooms" + q({ layout })),
    mediaRoomAction: (layout, room, action, value) => req("POST", "/api/media/rooms", { layout, room, action, value }),
    musicAssistant: () => get("/api/media/music-assistant"),
    saveMusicAssistant: (link) => req("PUT", "/api/media/music-assistant", link),
    removeMusicAssistant: (pin) => req("DELETE", "/api/media/music-assistant", { pin }),
    async security() {
      const r = await get<SecurityOverview>("/api/security");
      return { ...r, cameras: r.cameras.map(cam), alerts: r.alerts.map(cam) };
    },
    securityAlerts: async () => (await get<SecurityAlert[]>("/api/security/alerts")).map(cam),
    securityOptions: (refresh = false) => get("/api/security/options" + (refresh ? "?refresh=true" : "")),
    testSecurityAlert: async (camera, pin) => { await req("POST", "/api/security/test-alert", { camera, pin }); },
    setAlarm: (action, code) => req("POST", "/api/security/alarm", { action, ...(code ? { code } : {}) }),
    energy: () => get("/api/energy"),
    energyOptions: (refresh = false) => get("/api/energy/options" + (refresh ? "?refresh=true" : "")),
  };
}
