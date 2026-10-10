import { Api, ApiError, ScreensaverPhotos, Topic } from "./types";
import { authStatus, getToken, notifyUnpaired } from "./pairing";

/** Talks to the Moonlight add-on. `base` is "" when served by the add-on itself (works under HA ingress too). */
export function httpApi(base = ""): Api {
  const listeners = new Set<(t: Topic) => void>();

  async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
    const headers: Record<string, string> = {};
    const token = getToken();
    if (token) headers.Authorization = `Bearer ${token}`;
    if (body !== undefined) headers["Content-Type"] = "application/json";
    const res = await fetch(base + path, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (res.status === 401) notifyUnpaired(); // revoked or never paired: back to the pairing screen
    if (!res.ok) {
      let msg = res.statusText;
      try { msg = (await res.json()).detail ?? msg; } catch { /* not json */ }
      throw new ApiError(res.status, String(msg));
    }
    return res.json() as Promise<T>;
  }
  const get = <T>(p: string) => req<T>("GET", p);
  const q = (o: Record<string, string>) => "?" + new URLSearchParams(o).toString();

  let ws: WebSocket | null = null;
  function connect() {
    const url = new URL(base + "/api/ws", location.href);
    url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
    const token = getToken();
    if (token) url.searchParams.set("token", token);
    ws = new WebSocket(url);
    ws.onmessage = (m) => {
      try {
        const msg = JSON.parse(m.data);
        if (msg.type === "changed") listeners.forEach((l) => l(msg.topic));
        // A screen was revoked: if it was this one, drop back to pairing straight away.
        if (msg.type === "changed" && msg.topic === "displays") {
          authStatus(base).then((s) => { if (!s.authorised) notifyUnpaired(); }).catch(() => { /* offline */ });
        }
      } catch { /* ignore */ }
    };
    ws.onclose = () => { ws = null; setTimeout(connect, 3000); };
  }

  return {
    mode: "live",
    subscribe(fn) {
      listeners.add(fn);
      if (!ws) connect();
      return () => listeners.delete(fn);
    },
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
    deleteChore: async (id) => { await req("DELETE", `/api/chores/${id}`); },
    completeChore: async (id, date) => (await req<{ balance: number }>("POST", `/api/chores/${id}/complete`, { date })).balance,
    uncompleteChore: async (id, date) => (await req<{ balance: number }>("DELETE", `/api/chores/${id}/complete` + q({ date }))).balance,
    points: () => get("/api/points"),
    ledger: (pid) => get(`/api/points/${pid}/ledger`),
    adjustPoints: async (person_id, change, reason, pin) =>
      (await req<{ balance: number }>("POST", "/api/points/adjust", { person_id, change, reason, pin })).balance,
    rewards: () => get("/api/rewards"),
    createReward: (r) => req("POST", "/api/rewards", r),
    redeem: async (rid, person_id, pin) => (await req<{ balance: number }>("POST", `/api/rewards/${rid}/redeem`, { person_id, pin })).balance,
    lists: () => get("/api/lists"),
    createList: (l) => req("POST", "/api/lists", l),
    items: (lid) => get(`/api/lists/${lid}/items`),
    addItem: (lid, title, person_id = null, due = null) => req("POST", `/api/lists/${lid}/items`, { title, person_id, due }),
    updateItem: (id, patch) => req("PATCH", `/api/items/${id}`, patch),
    deleteItem: async (id) => { await req("DELETE", `/api/items/${id}`); },
    clearDone: async (lid) => { await req("POST", `/api/lists/${lid}/clear-done`); },
    meals: (start, end) => get("/api/meals" + q({ start, end })),
    createMeal: (m) => req("POST", "/api/meals", m),
    updateMeal: (id, m) => req("PATCH", `/api/meals/${id}`, m),
    deleteMeal: async (id) => { await req("DELETE", `/api/meals/${id}`); },
    recipes: () => get("/api/recipes"),
    recipeToList: async (rid, list_id) => (await req<{ added: number }>("POST", `/api/recipes/${rid}/to-list`, { list_id })).added,
    weather: () => get("/api/weather"),
    displays: () => get("/api/displays"),
    approveDisplay: (code, name, layout, pin) => req("POST", "/api/displays/approve", { code, name, layout, pin }),
    revokeDisplay: async (id, pin) => { await req("DELETE", `/api/displays/${id}`, { pin }); },
    immich: () => get("/api/immich"),
    saveImmich: (c) => req("PUT", "/api/immich", c),
    disconnectImmich: async (pin) => { await req("DELETE", "/api/immich", { pin }); },
    testImmich: (t) => req("POST", "/api/immich/test", t),
    immichAlbums: () => get("/api/immich/albums"),
    async screensaverPhotos() {
      const r = await get<ScreensaverPhotos>("/api/screensaver/photos");
      return { ...r, photos: r.photos.map((p) => ({ ...p, url: base + p.url })) };
    },
    accounts: () => get("/api/accounts"),
    connectAccount: (a) => req("POST", "/api/accounts", a),
    reconnectAccount: (id, creds) => req("PATCH", `/api/accounts/${id}`, creds),
    removeAccount: async (id, pin) => { await req("DELETE", `/api/accounts/${id}`, { pin }); },
    syncAccount: (id) => req("POST", `/api/accounts/${id}/sync`),
    calendars: () => get("/api/calendars"),
    updateCalendar: (id, patch) => req("PATCH", `/api/calendars/${id}`, patch),
  };
}
