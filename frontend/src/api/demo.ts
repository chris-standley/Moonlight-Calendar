// In-browser implementation of the Moonlight API (see API.md), seeded from seed/demo.json.
// Used by the published preview so the interface can be tried without the add-on.
import seed from "../../../seed/demo.json";
import {
  Account, Api, ApiError, Balance, BusyStatus, SyncCalendar, pickCalendar, CalEvent, Chore, ChoreDay, Item, LedgerEntry, Meal, Occurrence,
  Person, PersonIn, Recipe, Reward, Settings, TaskList, Topic, Weather,
} from "./types";
import { demoExtras } from "./demoPhotos";
import { demoMedia } from "./demoMedia";
import { addDays, dayCode, diffDays, iso, isoDT, parse, today, weekStart } from "../dates";

interface Completion { chore_id: string; date: string; at: string }
interface State {
  seededOn: string;
  settings: Omit<Settings, "pin_set"> & { pin: string };
  people: Person[];
  events: CalEvent[];
  chores: Chore[];
  completions: Completion[];
  ledger: LedgerEntry[];
  rewards: Reward[];
  lists: Omit<TaskList, "open_count" | "done_count">[];
  items: (Item & { done_at: string | null })[];
  meals: Meal[];
  recipes: Recipe[];
  // Simulated iCloud (optional so older saved demo states still load).
  accounts?: (Account & { password: string })[];
  calendars?: SyncCalendar[];
}

const KEY = "moonlight-demo-v1";
let n = 0;
const uid = (p: string) => `${p}_${Date.now().toString(36)}${(n++).toString(36)}`;
/** Same rule as the backend: first letter, or first + last initials for several words. */
const initials = (name: string) => {
  const parts = name.split(/\s+/).filter(Boolean);
  if (!parts.length) return "?";
  return (parts.length === 1 ? parts[0][0] : parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
};
/** Mirrors the backend's person validation (name required, max 40; colour #RGB or #RRGGBB, stored as #RRGGBB). */
function personFields(p: Partial<PersonIn>, partial: boolean): Partial<PersonIn> {
  const out: Partial<PersonIn> = {};
  if (p.name !== undefined || !partial) {
    const name = (p.name ?? "").trim();
    if (!name) throw new ApiError(400, "name is required");
    if (name.length > 40) throw new ApiError(400, "name must be at most 40 characters");
    out.name = name;
  }
  if (p.color !== undefined || !partial) {
    let c = (p.color ?? "").trim();
    if (!/^#([0-9a-f]{3}|[0-9a-f]{6})$/i.test(c)) throw new ApiError(400, "color must look like #RRGGBB");
    if (c.length === 4) c = "#" + [...c.slice(1)].map((x) => x + x).join("");
    out.color = c.toUpperCase();
  }
  if (p.role !== undefined || !partial) {
    const role = p.role ?? "child";
    if (role !== "adult" && role !== "child") throw new ApiError(400, "role must be one of adult, child");
    out.role = role;
  }
  if (p.sort !== undefined) out.sort = Math.trunc(Number(p.sort));
  return out;
}
const nowDT = () => isoDT(new Date());

function buildSeed(): State {
  const t = today();
  const mon = weekStart(t, "monday");
  const S = seed as any;
  const events: CalEvent[] = S.events.map((e: any) => {
    const d = addDays(mon, e.day);
    if (e.all_day) {
      const last = addDays(mon, e.end_day ?? e.day);
      return { id: e.id, title: e.title, person_ids: e.person_ids, start: `${d}T00:00`, end: `${addDays(last, 1)}T00:00`, all_day: true, location: e.location ?? "", notes: "", repeat: e.repeat ?? null };
    }
    return { id: e.id, title: e.title, person_ids: e.person_ids, start: `${d}T${e.start}`, end: `${d}T${e.end}`, all_day: false, location: e.location ?? "", notes: "", repeat: e.repeat ?? null };
  });
  const chores: Chore[] = S.chores.map((c: any, i: number) => ({ ...c, sort: i }));
  const completions: Completion[] = [];
  const ledger: LedgerEntry[] = [];
  for (const [cid, agos] of Object.entries(S.completions_ago)) {
    if (cid.startsWith("_")) continue;
    const chore = chores.find((c) => c.id === cid)!;
    for (const ago of agos as number[]) {
      const date = addDays(t, -ago);
      if (!isDue(chore, date)) continue;
      const at = `${date}T${chore.time_of_day === "evening" ? "19:10" : chore.time_of_day === "afternoon" ? "16:20" : "07:45"}`;
      completions.push({ chore_id: cid, date, at });
      if (chore.points) ledger.push({ id: uid("lg"), person_id: chore.person_id, change: chore.points, reason: `${chore.emoji} ${chore.title}`, at });
    }
  }
  for (const b of S.bonus_points) ledger.push({ id: uid("lg"), person_id: b.person_id, change: b.change, reason: b.reason, at: `${addDays(t, -b.ago)}T18:00` });
  const lists = S.lists.map((l: any, i: number) => ({ id: l.id, name: l.name, emoji: l.emoji, color: l.color, kind: l.kind, sort: i }));
  const items: State["items"] = [];
  S.lists.forEach((l: any) => l.items.forEach((it: any, i: number) => items.push({
    id: uid("it"), list_id: l.id, title: it.title, done: !!it.done, person_id: it.person_id ?? null,
    due: it.due_day != null ? addDays(mon, it.due_day) : null, created_at: nowDT(), sort: i, done_at: it.done ? `${addDays(t, -1)}T12:00` : null,
  })));
  const meals: Meal[] = S.meals.map((m: any) => ({ id: uid("ml"), date: addDays(mon, m.day), slot: m.slot, title: m.title, notes: "", recipe_id: m.recipe_id ?? null }));
  return {
    seededOn: t,
    settings: { ...S.settings },
    people: S.people.map((p: any) => ({ ...p, initials: initials(p.name) })),
    events: [...events, ...busyBlocks(WORK_CAL, mon)], chores, completions, ledger,
    rewards: S.rewards, lists, items, meals,
    recipes: S.recipes.map((r: any) => ({ url: null, ...r })),
    // A published Outlook calendar ("Can view when I'm busy") for Alex: busy blocks only.
    accounts: [{
      id: "acct_work", kind: "ics", label: "Work", username: "", password: "",
      server_url: "outlook.office365.com/…/calendar.ics", status: "ok", last_error: null, last_sync: nowDT(), calendar_count: 1,
    }],
    calendars: [{
      id: WORK_CAL, account_id: "acct_work", name: "Work", color: "#4F7CEC", person_ids: ["p_alex"], visible: true,
      read_only: true, busy_blocks: true, busy_blocks_auto: true, busy_blocks_set: false,
    }],
  };
}

const WORK_CAL = "cal_work";
/** Free/busy blocks as an Outlook "Can view when I'm busy" feed publishes them (titles are just the status). */
function busyBlocks(calendarId: string, mon: string): CalEvent[] {
  const B: [number, string, string, BusyStatus][] = [
    [0, "10:30", "11:30", "busy"], [0, "14:00", "15:30", "busy"], [1, "09:00", "10:30", "busy"], [1, "13:00", "14:00", "tentative"],
    [2, "11:00", "12:00", "busy"], [2, "12:30", "13:00", "free"], [2, "15:00", "17:00", "busy"], [3, "09:30", "11:00", "busy"],
    [3, "13:30", "14:00", "tentative"], [4, "10:00", "12:00", "busy"], [7, "10:30", "11:30", "busy"], [7, "14:00", "16:00", "busy"],
    [9, "09:00", "10:00", "busy"], [9, "13:00", "15:00", "tentative"], [10, "11:00", "12:30", "busy"], [11, "15:00", "16:00", "busy"],
  ];
  const title = (b: BusyStatus) => b[0].toUpperCase() + b.slice(1);
  const out: CalEvent[] = B.map(([day, s, e, busy], i) => {
    const d = addDays(mon, day);
    return { id: `ev_work${i}`, title: title(busy), person_ids: [], start: `${d}T${s}`, end: `${d}T${e}`, all_day: false, location: "", notes: "", repeat: null, calendar_id: calendarId, busy };
  });
  out.push({ id: "ev_work_away", title: "Away", person_ids: [], start: `${addDays(mon, 15)}T00:00`, end: `${addDays(mon, 16)}T00:00`, all_day: true, location: "", notes: "", repeat: null, calendar_id: calendarId, busy: "away" });
  return out;
}

/** Same idea as the backend: host plus the last path segment, never the secret parts. */
function maskUrl(url: string): string {
  try {
    const u = new URL(url);
    const last = u.pathname.split("/").filter(Boolean).pop() ?? "";
    return last ? `${u.hostname}/…/${last.length > 24 ? last.slice(0, 4) + "…" : last}` : u.hostname;
  } catch { return "link"; }
}

function isDue(c: Chore, date: string): boolean {
  const s = c.schedule;
  if (s.type === "daily") return true;
  if (s.type === "weekly") return s.days.includes(dayCode(date));
  return s.date === date;
}

/** Expand an event into the occurrences overlapping [start, end). */
export function expand(e: CalEvent, start: string, end: string): Occurrence[] {
  const s0 = parse(e.start), e0 = parse(e.end);
  const durMin = Math.round((e0.getTime() - s0.getTime()) / 60000);
  const rs = `${start}T00:00`, re = `${end}T00:00`;
  const overlaps = (a: string, b: string) => a < re && (b > rs || (a === b && a >= rs));
  if (!e.repeat) return overlaps(e.start, e.end) ? [{ ...e, occurrence_id: `${e.id}@${e.start.slice(0, 10)}`, recurring: false }] : [];
  const r = e.repeat;
  const first = e.start.slice(0, 10);
  const time = e.start.slice(11, 16);
  const spanDays = Math.ceil(durMin / 1440) + 1;
  const out: Occurrence[] = [];
  let d = addDays(start, -spanDays);
  if (d < first) d = first;
  const interval = Math.max(1, r.interval || 1);
  const byday = r.byday && r.byday.length ? r.byday : [dayCode(first)];
  for (; d < end; d = addDays(d, 1)) {
    if (r.until && d > r.until) break;
    let ok = false;
    if (r.freq === "daily") ok = diffDays(d, first) % interval === 0;
    else if (r.freq === "weekly") ok = byday.includes(dayCode(d)) && (diffDays(weekStart(d, "monday"), weekStart(first, "monday")) / 7) % interval === 0;
    else if (r.freq === "monthly") {
      const a = parse(d), b = parse(first);
      ok = a.getDate() === b.getDate() && ((a.getFullYear() - b.getFullYear()) * 12 + a.getMonth() - b.getMonth()) % interval === 0;
    }
    if (!ok) continue;
    const os = parse(`${d}T${time}`);
    const oe = new Date(os.getTime() + durMin * 60000);
    const ostr = isoDT(os), oestr = isoDT(oe);
    if (overlaps(ostr, oestr)) out.push({ ...e, start: ostr, end: oestr, occurrence_id: `${e.id}@${d}`, recurring: true });
  }
  return out;
}

const CONDITIONS = ["sunny", "partlycloudy", "partlycloudy", "cloudy", "rainy", "sunny", "pouring", "cloudy", "windy", "fog"];
function hash(s: string) { let h = 2166136261; for (const ch of s) { h ^= ch.charCodeAt(0); h = Math.imul(h, 16777619); } return h >>> 0; }
export function demoWeather(): Weather {
  const t = today();
  const daily = Array.from({ length: 10 }, (_, i) => {
    const date = addDays(t, i), h = hash(date);
    const high = 11 + (h % 8), low = high - 4 - ((h >> 4) % 4);
    return { date, high, low, condition: CONDITIONS[(h >> 8) % CONDITIONS.length] };
  });
  const hour = new Date().getHours();
  const cur = daily[0];
  const temp = Math.round(cur.low + (cur.high - cur.low) * Math.max(0, Math.sin(((hour - 6) / 16) * Math.PI)));
  return { source: "demo", entity: null, unit: "C", current: { temp, condition: hour >= 19 || hour < 7 ? (cur.condition === "sunny" ? "clear-night" : cur.condition) : cur.condition }, daily };
}

export function demoApi(): Api {
  const listeners = new Set<(t: Topic) => void>();
  let st: State;
  try {
    const raw = localStorage.getItem(KEY);
    const parsed = raw ? (JSON.parse(raw) as State) : null;
    st = parsed && parsed.seededOn === today() ? parsed : buildSeed();
  } catch { st = buildSeed(); }

  const save = () => { try { localStorage.setItem(KEY, JSON.stringify(st)); } catch { /* private mode */ } };
  const emit = (...topics: Topic[]) => { save(); topics.forEach((t) => listeners.forEach((l) => l(t))); };
  const clone = <T>(x: T): T => JSON.parse(JSON.stringify(x));
  const ok = async <T>(x: T): Promise<T> => clone(x);
  const find = <T extends { id: string }>(arr: T[], id: string): T => {
    const x = arr.find((a) => a.id === id);
    if (!x) throw new ApiError(404, "Not found");
    return x;
  };
  const checkPin = (pin: string) => { if (pin !== st.settings.pin) throw new ApiError(403, "Wrong PIN"); };
  const balance = (pid: string) => st.ledger.filter((l) => l.person_id === pid).reduce((a, l) => a + l.change, 0);
  const isDone = (cid: string, date: string) => st.completions.some((c) => c.chore_id === cid && c.date === date);

  function streak(c: Chore, date: string): number {
    let d = date, count = 0;
    if (!isDone(c.id, d)) d = addDays(d, -1);
    for (let i = 0; i < 60; i++, d = addDays(d, -1)) {
      if (!isDue(c, d)) continue;
      if (!isDone(c.id, d)) break;
      count++;
    }
    return count;
  }
  // ---- simulated iCloud: any Apple ID "discovers" Family + one calendar per adult; password "wrong" fails sign-in.
  const ICLOUD_COLORS = ["#FF9500", "#1BADF8", "#CC73E1", "#63DA38", "#FF2968", "#A2845E"];
  const accts = () => (st.accounts ??= []);
  const cals = () => (st.calendars ??= []);
  const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));
  const acctOut = (a: Account & { password: string }): Account => {
    const { password, ...rest } = a;
    return { ...clone(rest), calendar_count: cals().filter((c) => c.account_id === a.id).length };
  };
  const calOf = (id: string | null | undefined) => (id ? cals().find((c) => c.id === id) : undefined);
  const decorate = (e: CalEvent): CalEvent => {
    const cal = calOf(e.calendar_id);
    if (!cal) return { ...e, calendar_id: null, source: null, custom_repeat: false, color: null, read_only: false, busy: null };
    const acct = accts().find((a) => a.id === cal.account_id);
    return {
      ...e, person_ids: e.person_ids.length ? e.person_ids : cal.person_ids, source: acct?.kind ?? "icloud", custom_repeat: false,
      color: cal.color, read_only: cal.read_only, busy: cal.busy_blocks ? e.busy ?? "busy" : null,
    };
  };
  const writable = (id: string) => {
    const ev = find(st.events, id);
    const cal = calOf(ev.calendar_id);
    if (cal?.read_only) throw new ApiError(403, `“${ev.title}” is in a read-only calendar and can't be changed here.`);
    return ev;
  };
  const feedUrl = (raw: string) => {
    const url = raw.trim().replace(/^webcals?:\/\//i, "https://");
    if (!/^https?:\/\/[^/\s]+/i.test(url)) throw new ApiError(400, "Paste a calendar link starting with https:// or webcal://");
    return url;
  };
  const previewOf = (url: string) => {
    if (/fail|error|html/i.test(url)) throw new ApiError(502, "That link didn't return a calendar (.ics) file. Check you copied the ICS link, not the HTML one.");
    const busy = /outlook|office365|exchange/i.test(url);
    return { event_count: busy ? 17 : 6, name: busy ? "Calendar" : "School term dates", busy_only: busy, masked_url: maskUrl(url) };
  };
  const defaultCalendar = (personIds: string[]) => pickCalendar(cals(), personIds);
  const targetCalendar = (e: { calendar_id?: string | null; person_ids: string[] }) => {
    if (e.calendar_id === undefined) return defaultCalendar(e.person_ids);
    if (e.calendar_id && !calOf(e.calendar_id)) throw new ApiError(400, "Unknown calendar");
    return e.calendar_id ?? null;
  };

  // The demo kitchen screen has a (pretend) Music Assistant speaker; other screens have none until set in Settings.
  const mediaPlayers = () => ({ hallway: "", kitchen: "media_player.kitchen", phone: "", ...st.settings.media_players });
  const settingsOut = (): Settings => {
    const { pin, ...rest } = st.settings;
    return { ...rest, media_players: mediaPlayers(), pin_set: !!pin };
  };

  return {
    mode: "demo",
    subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); },
    settings: async () => settingsOut(),
    async updateSettings({ pin, new_pin, ...patch }) {
      checkPin(pin);
      if (new_pin != null && new_pin !== "" && !/^\d{4}$/.test(new_pin)) throw new ApiError(400, "new_pin must be 4 digits");
      const { media_players, ...rest } = patch;
      Object.assign(st.settings, rest);
      if (media_players) {
        if (Object.entries(media_players).some(([k, v]) => !["hallway", "kitchen", "phone"].includes(k) || (v !== "" && !/^media_player\.[a-z0-9_]+$/.test(v ?? ""))))
          throw new ApiError(400, "media_players must map hallway/kitchen/phone to a media_player entity id or empty");
        st.settings.media_players = { ...st.settings.media_players, ...media_players };
      }
      if (new_pin) st.settings.pin = new_pin;
      emit("settings", "media");
      return settingsOut();
    },
    verifyPin: async (pin) => pin === st.settings.pin,
    people: async () => clone([...st.people].sort((a, b) => a.sort - b.sort || a.name.localeCompare(b.name))),
    async createPerson(p) {
      const f = personFields(p, false) as PersonIn;
      const sort = f.sort ?? Math.max(-1, ...st.people.map((x) => x.sort)) + 1;
      const person: Person = { id: uid("p"), name: f.name, color: f.color, role: f.role, sort, initials: initials(f.name) };
      st.people.push(person);
      emit("people", "points");
      return clone(person);
    },
    async updatePerson(id, patch) {
      const person = find(st.people, id);
      Object.assign(person, personFields(patch, true));
      person.initials = initials(person.name);
      emit("people");
      return clone(person);
    },
    async deletePerson(id, pin) {
      checkPin(pin);
      find(st.people, id);
      // Same as the backend: events and list items stay (minus this person); their chores, stars and own rewards go.
      st.people = st.people.filter((p) => p.id !== id);
      for (const e of st.events) e.person_ids = e.person_ids.filter((x) => x !== id);
      const gone = new Set(st.chores.filter((c) => c.person_id === id).map((c) => c.id));
      st.completions = st.completions.filter((c) => !gone.has(c.chore_id));
      st.chores = st.chores.filter((c) => !gone.has(c.id));
      st.ledger = st.ledger.filter((l) => l.person_id !== id);
      st.rewards = st.rewards.filter((r) => r.person_id !== id);
      for (const it of st.items) if (it.person_id === id) it.person_id = null;
      for (const c of cals()) c.person_ids = c.person_ids.filter((x) => x !== id);
      emit("people", "events", "chores", "points", "rewards", "lists", "accounts");
    },
    async events(start, end) {
      return st.events.filter((e) => !e.calendar_id || calOf(e.calendar_id)?.visible !== false)
        .map(decorate).filter((e) => e.busy !== "free").flatMap((e) => expand(e, start, end))
        .sort((a, b) => a.start.localeCompare(b.start) || a.title.localeCompare(b.title));
    },
    async createEvent(e) {
      const ev: CalEvent = { location: "", notes: "", repeat: null, ...e, calendar_id: targetCalendar(e), id: uid("ev") };
      st.events.push(ev); emit("events"); return decorate(clone(ev));
    },
    async updateEvent(id, patch) {
      const ev = writable(id);
      if (patch.calendar_id !== undefined) patch = { ...patch, calendar_id: targetCalendar({ ...ev, ...patch }) };
      Object.assign(ev, patch); emit("events"); return decorate(clone(ev));
    },
    async deleteEvent(id) { writable(id); st.events = st.events.filter((e) => e.id !== id); emit("events"); },
    allChores: async () => clone(st.chores),
    async chores(date) {
      return st.chores.filter((c) => isDue(c, date)).sort((a, b) => a.sort - b.sort).map((c): ChoreDay => {
        const comp = st.completions.find((x) => x.chore_id === c.id && x.date === date);
        return { ...clone(c), date, completed: !!comp, completed_at: comp?.at ?? null, streak: streak(c, date) };
      });
    },
    async createChore(c) {
      const ch: Chore = { ...c, id: uid("ch"), sort: st.chores.length };
      st.chores.push(ch); emit("chores"); return clone(ch);
    },
    async deleteChore(id) { st.chores = st.chores.filter((c) => c.id !== id); emit("chores"); },
    async completeChore(id, date) {
      const c = find(st.chores, id);
      if (!isDone(id, date)) {
        const at = nowDT();
        st.completions.push({ chore_id: id, date, at });
        if (c.points) st.ledger.push({ id: uid("lg"), person_id: c.person_id, change: c.points, reason: `${c.emoji} ${c.title}`, at });
        emit("chores", "points");
      }
      return balance(c.person_id);
    },
    async uncompleteChore(id, date) {
      const c = find(st.chores, id);
      if (isDone(id, date)) {
        st.completions = st.completions.filter((x) => !(x.chore_id === id && x.date === date));
        if (c.points) st.ledger.push({ id: uid("lg"), person_id: c.person_id, change: -c.points, reason: `Undo: ${c.title}`, at: nowDT() });
        emit("chores", "points");
      }
      return balance(c.person_id);
    },
    points: async (): Promise<Balance[]> => st.people.map((p) => ({ person_id: p.id, balance: balance(p.id) })),
    ledger: async (pid) => clone(st.ledger.filter((l) => l.person_id === pid).sort((a, b) => b.at.localeCompare(a.at)).slice(0, 100)),
    async adjustPoints(pid, change, reason, pin) {
      checkPin(pin);
      st.ledger.push({ id: uid("lg"), person_id: pid, change, reason, at: nowDT() });
      emit("points");
      return balance(pid);
    },
    rewards: () => ok(st.rewards),
    async createReward(r) { const rw = { ...r, id: uid("rw") }; st.rewards.push(rw); emit("rewards"); return clone(rw); },
    async redeem(rid, pid, pin) {
      checkPin(pin);
      const r = find(st.rewards, rid);
      if (balance(pid) < r.cost) throw new ApiError(400, "Not enough stars yet");
      st.ledger.push({ id: uid("lg"), person_id: pid, change: -r.cost, reason: `${r.emoji} ${r.title}`, at: nowDT() });
      emit("points");
      return balance(pid);
    },
    async lists() {
      return st.lists.map((l) => ({
        ...clone(l),
        open_count: st.items.filter((i) => i.list_id === l.id && !i.done).length,
        done_count: st.items.filter((i) => i.list_id === l.id && i.done).length,
      }));
    },
    async createList(l) {
      const nl = { ...l, id: uid("ls"), sort: st.lists.length };
      st.lists.push(nl); emit("lists");
      return { ...clone(nl), open_count: 0, done_count: 0 };
    },
    async items(lid) {
      const its = st.items.filter((i) => i.list_id === lid);
      const open = its.filter((i) => !i.done).sort((a, b) => a.sort - b.sort);
      const done = its.filter((i) => i.done).sort((a, b) => (b.done_at ?? "").localeCompare(a.done_at ?? ""));
      return clone([...open, ...done]).map(({ done_at, ...i }) => i);
    },
    async addItem(lid, title, person_id = null, due = null) {
      find(st.lists, lid);
      const minSort = Math.min(0, ...st.items.filter((i) => i.list_id === lid).map((i) => i.sort));
      const it = { id: uid("it"), list_id: lid, title, done: false, person_id, due, created_at: nowDT(), sort: minSort - 1, done_at: null };
      st.items.push(it); emit("lists");
      const { done_at, ...out } = it; return out;
    },
    async updateItem(id, patch) {
      const it = find(st.items, id);
      if (patch.done !== undefined && patch.done !== it.done) it.done_at = patch.done ? nowDT() : null;
      Object.assign(it, patch); emit("lists");
      const { done_at, ...out } = clone(it); return out;
    },
    async deleteItem(id) { st.items = st.items.filter((i) => i.id !== id); emit("lists"); },
    async clearDone(lid) { st.items = st.items.filter((i) => !(i.list_id === lid && i.done)); emit("lists"); },
    meals: async (start, end) => clone(st.meals.filter((m) => m.date >= start && m.date < end)),
    async createMeal(m) { const ml = { ...m, id: uid("ml") }; st.meals.push(ml); emit("meals"); return clone(ml); },
    async updateMeal(id, patch) { const ml = find(st.meals, id); Object.assign(ml, patch); emit("meals"); return clone(ml); },
    async deleteMeal(id) { st.meals = st.meals.filter((m) => m.id !== id); emit("meals"); },
    recipes: () => ok(st.recipes),
    async recipeToList(rid, lid) {
      const r = find(st.recipes, rid);
      for (const ing of r.ingredients) {
        st.items.push({ id: uid("it"), list_id: lid, title: ing, done: false, person_id: null, due: null, created_at: nowDT(), sort: -1000, done_at: null });
      }
      emit("lists");
      return r.ingredients.length;
    },
    weather: async () => demoWeather(),
    ...demoExtras(checkPin, emit), // screens + simulated Immich, kept in memory
    ...demoMedia(emit, mediaPlayers), // a pretend kitchen speaker
    accounts: async () => accts().map(acctOut),
    async connectAccount(a) {
      checkPin(a.pin);
      await wait(900); // "checking with iCloud"
      if (!a.username.trim() || !a.password.trim()) throw new ApiError(400, "Enter the Apple ID and app-specific password");
      if (accts().some((x) => x.username === a.username && x.kind === a.kind)) throw new ApiError(400, "That account is already connected");
      const first = !accts().some((x) => x.kind !== "ics");
      const acct = {
        id: uid("acct"), kind: a.kind, label: a.label || a.username, username: a.username, password: a.password,
        server_url: a.kind === "icloud" ? "https://caldav.icloud.com/" : a.server_url ?? "",
        status: (a.password === "wrong" ? "auth_failed" : "ok") as Account["status"],
        last_error: a.password === "wrong" ? "iCloud did not accept the Apple ID or app-specific password. Reconnect it in Settings > Calendars." : null,
        last_sync: a.password === "wrong" ? null : nowDT(), calendar_count: 0,
      };
      accts().push(acct);
      const adults = st.people.filter((p) => p.role === "adult");
      const found = first
        ? [{ name: "Family", person_ids: st.people.map((p) => p.id) }, ...adults.map((p) => ({ name: p.name, person_ids: [p.id] }))]
        : [{ name: a.username.split("@")[0].replace(/^./, (c) => c.toUpperCase()), person_ids: [] as string[] }];
      const newCals = found.map((f, i): SyncCalendar => ({
        id: uid("cal"), account_id: acct.id, name: f.name, person_ids: f.person_ids, visible: true, read_only: false,
        color: ICLOUD_COLORS[(cals().length + i) % ICLOUD_COLORS.length],
      }));
      cals().push(...newCals);
      if (first && acct.status === "ok") {
        // Pretend the demo family's events came from iCloud: one adult's events into their calendar, the rest into Family.
        for (const e of st.events) {
          if (e.calendar_id) continue; // already from a calendar link
          const own = e.person_ids.length === 1 ? newCals.find((c) => c.person_ids.length === 1 && c.person_ids[0] === e.person_ids[0]) : undefined;
          e.calendar_id = (own ?? newCals[0]).id;
        }
      }
      emit("accounts", "events");
      return acctOut(acct);
    },
    async reconnectAccount(id, creds) {
      checkPin(creds.pin);
      const acct = find(accts(), id);
      await wait(700);
      if (creds.password === "wrong" || !creds.password) throw new ApiError(400, "iCloud didn't accept that Apple ID and app-specific password. Check both and try again.");
      Object.assign(acct, { password: creds.password, username: creds.username ?? acct.username, status: "ok", last_error: null, last_sync: nowDT() });
      const mine = cals().filter((c) => c.account_id === id);
      if (mine.length && !st.events.some((e) => mine.some((c) => c.id === e.calendar_id))) {
        for (const e of st.events) if (!e.calendar_id) e.calendar_id = mine[0].id;
      }
      emit("accounts", "events");
      return acctOut(acct);
    },
    async removeAccount(id, pin) {
      checkPin(pin);
      find(accts(), id);
      const mine = new Set(cals().filter((c) => c.account_id === id).map((c) => c.id));
      // A real removal forgets the cached iCloud events; the demo keeps them as local events instead
      // (except a calendar link's, which are dropped like the real thing).
      if (find(accts(), id).kind === "ics") st.events = st.events.filter((e) => !e.calendar_id || !mine.has(e.calendar_id));
      for (const e of st.events) if (e.calendar_id && mine.has(e.calendar_id)) e.calendar_id = null;
      st.calendars = cals().filter((c) => !mine.has(c.id));
      st.accounts = accts().filter((a) => a.id !== id);
      emit("accounts", "events");
    },
    async syncAccount(id) {
      const acct = find(accts(), id);
      await wait(600);
      if (acct.status !== "auth_failed") { acct.last_sync = nowDT(); acct.status = "ok"; acct.last_error = null; }
      emit("accounts");
      return acctOut(acct);
    },
    async previewFeed(raw) {
      const url = feedUrl(raw);
      await wait(800); // "fetching the link"
      return previewOf(url);
    },
    async addFeed(f) {
      checkPin(f.pin);
      const url = feedUrl(f.url);
      await wait(800);
      if (accts().some((a) => a.kind === "ics" && a.password === url)) throw new ApiError(400, "That calendar link is already added");
      const p = previewOf(url);
      const label = f.label?.trim() || p.name || "Calendar link";
      const acct = { id: uid("acct"), kind: "ics" as const, label, username: "", password: url, server_url: p.masked_url, status: "ok" as const, last_error: null, last_sync: nowDT(), calendar_count: 1 };
      const person = st.people.find((x) => x.id === f.person_ids[0]);
      const cal: SyncCalendar = {
        id: uid("cal"), account_id: acct.id, name: label, color: f.color ?? person?.color ?? "#8A94A6", person_ids: f.person_ids, visible: true,
        read_only: true, busy_blocks: p.busy_only, busy_blocks_auto: p.busy_only, busy_blocks_set: false,
      };
      accts().push(acct); cals().push(cal);
      const mon = weekStart(today(), "monday");
      if (p.busy_only) st.events.push(...busyBlocks(cal.id, mon).map((e) => ({ ...e, id: uid("ev") })));
      else ["Harvest festival", "Flu vaccinations", "Non-uniform day", "Book fair", "INSET day", "Christmas fair"].forEach((title, i) => {
        const d = addDays(mon, 3 + i * 4);
        st.events.push({ id: uid("ev"), title, person_ids: [], start: `${d}T00:00`, end: `${addDays(d, 1)}T00:00`, all_day: true, location: "", notes: "", repeat: null, calendar_id: cal.id });
      });
      emit("accounts", "events");
      return acctOut(acct);
    },
    async updateFeed(id, patch) {
      checkPin(patch.pin);
      const acct = find(accts(), id);
      if (patch.url !== undefined) {
        const url = feedUrl(patch.url);
        await wait(700);
        Object.assign(acct, { password: url, server_url: previewOf(url).masked_url, status: "ok", last_error: null, last_sync: nowDT() });
      }
      if (patch.label?.trim()) {
        acct.label = patch.label.trim();
        for (const c of cals()) if (c.account_id === id) c.name = acct.label;
      }
      emit("accounts", "events");
      return acctOut(acct);
    },
    calendars: async () => clone(cals()),
    async updateCalendar(id, patch) {
      const cal = find(cals(), id);
      if (patch.busy_blocks !== undefined) {
        const auto = !!cal.busy_blocks_auto;
        Object.assign(cal, { busy_blocks: patch.busy_blocks ?? auto, busy_blocks_set: patch.busy_blocks !== null });
        delete patch.busy_blocks;
      }
      Object.assign(cal, patch);
      emit("accounts", "events");
      return clone(cal);
    },
    async resetDemo() {
      st = buildSeed();
      emit("people", "events", "chores", "points", "rewards", "lists", "meals", "recipes", "settings", "accounts");
    },
  };
}

export { iso };
