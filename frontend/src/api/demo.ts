// In-browser implementation of the Moonlight API (see API.md), seeded from seed/demo.json.
// Used by the published preview so the interface can be tried without the add-on.
import seed from "../../../seed/demo.json";
import {
  Account, Api, ApiError, Balance, BusyStatus, SyncCalendar, pickCalendar, CalEvent, Chore, ChoreDay, Item, LedgerEntry, Meal, Occurrence,
  DEFAULT_IDLE, DEFAULT_SCREENS, HolidayCountry, HolidayRegion, Layout, Person, PersonIn, Recipe, RecipeIn, Reward, SECTIONS, ScreenSetup, SecuritySettings, Settings, TaskList, Topic, Weather,
} from "./types";
import { demoExtras } from "./demoPhotos";
import { demoMedia } from "./demoMedia";
import { demoSecurity } from "./demoSecurity";
import { addDays, dayCode, diffDays, iso, isoDT, parse, today, weekStart } from "../dates";
import { metricNote, parseIngredient, parseText, stepTimers, stepUses } from "../recipes/recipeText";

interface Completion { chore_id: string; date: string; at: string }
/** A recipe as the add-on stores it: ingredient lines and steps; the rest is worked out when read (recipeOut). */
interface RecipeRow {
  id: string; title: string; emoji: string; description?: string; photo?: string | null; rating?: number; favourite?: boolean;
  servings?: number | null; prep_minutes?: number | null; cook_minutes?: number | null; minutes: number | null;
  ingredients: string[]; steps?: { text: string; minutes: number | null; photo: string | null }[]; tags?: string[];
  notes?: string; url: string | null; cooked_count?: number; last_cooked?: string | null; created_at?: string; updated_at?: string;
}
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
  recipes: RecipeRow[];
  /** Uploaded pictures as data: URLs (shrunk by the screens first). */
  images?: Record<string, string>;
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
    recipes: S.recipes.map((r: any) => ({ url: null, minutes: null, ...r,
      steps: (r.steps ?? []).map((x: any) => ({ text: x.text, minutes: x.minutes ?? null, photo: null })) })),
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
const HA_CALENDARS: [string, string][] = [
  ["calendar.bin_collections", "Bin collections"],
  ["calendar.free_electricity_sessions", "Free electricity sessions"],
  ["calendar.workday_alex", "Workday Alex"],
];

function busyBlocks(calendarId: string, mon: string): CalEvent[] {
  const B: [number, string, string, BusyStatus][] = [
    [0, "10:30", "11:30", "busy"], [0, "11:00", "12:00", "busy"], [0, "14:00", "15:30", "busy"], [0, "15:30", "16:30", "tentative"], [1, "09:00", "10:30", "busy"], [1, "13:00", "14:00", "tentative"],
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

// England and Wales bank holidays, the only public holidays the demo knows (the add-on covers ~200 countries).
const BANK_HOLIDAYS: Record<string, string> = {
  "2025-01-01": "New Year's Day",
  "2025-04-18": "Good Friday",
  "2025-04-21": "Easter Monday",
  "2025-05-05": "May Day",
  "2025-05-26": "Spring Bank Holiday",
  "2025-08-25": "Late Summer Bank Holiday",
  "2025-12-25": "Christmas Day",
  "2025-12-26": "Boxing Day",
  "2026-01-01": "New Year's Day",
  "2026-04-03": "Good Friday",
  "2026-04-06": "Easter Monday",
  "2026-05-04": "May Day",
  "2026-05-25": "Spring Bank Holiday",
  "2026-08-31": "Late Summer Bank Holiday",
  "2026-12-25": "Christmas Day",
  "2026-12-26": "Boxing Day",
  "2026-12-28": "Boxing Day (observed)",
  "2027-01-01": "New Year's Day",
  "2027-03-26": "Good Friday",
  "2027-03-29": "Easter Monday",
  "2027-05-03": "May Day",
  "2027-05-31": "Spring Bank Holiday",
  "2027-08-30": "Late Summer Bank Holiday",
  "2027-12-25": "Christmas Day",
  "2027-12-26": "Boxing Day",
  "2027-12-27": "Christmas Day (observed)",
  "2027-12-28": "Boxing Day (observed)",
  "2028-01-01": "New Year's Day",
  "2028-01-03": "New Year's Day (observed)",
  "2028-04-14": "Good Friday",
  "2028-04-17": "Easter Monday",
  "2028-05-01": "May Day",
  "2028-05-29": "Spring Bank Holiday",
  "2028-08-28": "Late Summer Bank Holiday",
  "2028-12-25": "Christmas Day",
  "2028-12-26": "Boxing Day",
};
export const DEMO_HOLIDAY_COUNTRIES: HolidayCountry[] = [
  { code: "GB", name: "United Kingdom", subdivs: [{ code: "ENG", name: "England" }, { code: "WLS", name: "Wales" }] },
];
let holidayRegion: HolidayRegion = { country: "GB", subdiv: "ENG" };
const holidayOn = (date: string): string | undefined => (holidayRegion.country ? BANK_HOLIDAYS[date] : undefined);

function isDue(c: Chore, date: string): boolean {
  const s = c.schedule;
  if (s.type !== "once" && s.skip_holidays && holidayOn(date)) return false;
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
    if (!ok || (r.skip_holidays && holidayOn(d))) continue;
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
    const condition = CONDITIONS[(h >> 8) % CONDITIONS.length];
    const wet = ({ rainy: 40, pouring: 70, cloudy: 10 } as Record<string, number>)[condition] ?? 0;
    return { date, high, low, condition, rain: wet && wet + ((h >> 12) % 6) * 5 };
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
  holidayRegion = st.settings.holidays ?? { country: "GB", subdiv: "ENG" };

  const save = () => { try { localStorage.setItem(KEY, JSON.stringify(st)); } catch { /* private mode */ } };
  const emit = (...topics: Topic[]) => { save(); topics.forEach((t) => listeners.forEach((l) => l(t))); };
  const clone = <T>(x: T): T => JSON.parse(JSON.stringify(x));
  const ok = async <T>(x: T): Promise<T> => clone(x);
  // Same rules as the backend's recipe_fields (POST: all fields; PATCH: only those given).
  const recipeFields = (b: Partial<RecipeIn>, partial = false, checkImages = true): Partial<RecipeRow> => {
    const out: Partial<RecipeRow> = {};
    const has = (k: keyof RecipeIn) => !partial || k in b;
    const int = (k: "servings" | "prep_minutes" | "cook_minutes" | "minutes" | "rating", lo: number, hi: number) => {
      const v = b[k];
      if (v == null || (v as unknown) === "") return null;
      if (!Number.isInteger(v) || v < lo || v > hi) throw new ApiError(400, `${k} must be between ${lo} and ${hi}`);
      return v;
    };
    const img = (v: string | null | undefined, what: string) => {
      if (!v) return null;
      if (checkImages && !st.images?.[v]) throw new ApiError(400, `${what} must be an uploaded picture or null`);
      return v;
    };
    if (has("title")) {
      if (!b.title?.trim()) throw new ApiError(400, "title is required");
      out.title = b.title.trim().slice(0, 120);
    }
    if (has("emoji")) out.emoji = (b.emoji ?? "").trim().slice(0, 8);
    if (has("description")) out.description = (b.description ?? "").trim();
    if (has("notes")) out.notes = (b.notes ?? "").trim();
    if (has("url")) out.url = b.url?.trim() || null;
    if (has("photo")) out.photo = img(b.photo, "photo");
    if (has("rating")) out.rating = int("rating", 0, 5) ?? 0;
    if (has("favourite")) out.favourite = !!b.favourite;
    if (has("servings")) out.servings = int("servings", 1, 100);
    for (const k of ["prep_minutes", "cook_minutes", "minutes"] as const) if (has(k)) out[k] = int(k, 0, 10000);
    if (has("ingredients")) out.ingredients = (b.ingredients ?? []).map((i) => (typeof i === "string" ? i : (i as { text: string }).text).trim()).filter(Boolean);
    if (has("steps")) out.steps = (b.steps ?? []).map((x) => (typeof x === "string" ? { text: x } : x))
      .map((x) => {
        if (x.minutes != null && !(x.minutes > 0 && x.minutes <= 1440)) throw new ApiError(400, "step minutes must be a number from 0 to 1440, or null");
        return { text: x.text.trim(), minutes: x.minutes ?? null, photo: img(x.photo, "step photo") };
      }).filter((x) => x.text || x.photo);
    if (has("tags")) out.tags = [...new Set((b.tags ?? []).map((t) => t.trim().toLowerCase().slice(0, 30)).filter(Boolean))].slice(0, 20);
    return out;
  };
  const imageUrl = (id: string | null | undefined) => (id ? st.images?.[id] ?? null : null);
  /** The Recipe the add-on would return for a stored row (see routes/recipes.py recipe_out). */
  const recipeOut = (r: RecipeRow | (Partial<RecipeRow> & { id: null; title: string })): Recipe => {
    const ingredients = (r.ingredients ?? []).map(parseIngredient);
    const total = r.minutes ?? (r.prep_minutes == null && r.cook_minutes == null ? null : (r.prep_minutes ?? 0) + (r.cook_minutes ?? 0));
    return {
      id: r.id as string, title: r.title, emoji: r.emoji ?? "", description: r.description ?? "", photo: r.photo ?? null,
      photo_url: imageUrl(r.photo), rating: r.rating ?? 0, favourite: !!r.favourite, servings: r.servings ?? null,
      prep_minutes: r.prep_minutes ?? null, cook_minutes: r.cook_minutes ?? null, minutes: total,
      ingredients,
      steps: (r.steps ?? []).map((x) => ({ text: x.text, minutes: x.minutes, photo: x.photo, photo_url: imageUrl(x.photo),
        timers: stepTimers(x.text, x.minutes), metric_text: metricNote(x.text), uses: stepUses(x.text, ingredients) })),
      tags: r.tags ?? [], notes: r.notes ?? "", url: r.url ?? null, cooked_count: r.cooked_count ?? 0,
      last_cooked: r.last_cooked ?? null, created_at: r.created_at ?? null, updated_at: r.updated_at ?? null,
    };
  };
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

  // Compact demo screens have a (pretend) Music Assistant kitchen speaker; others have none until set in Settings.
  const mediaPlayers = () => ({ large: "", compact: "media_player.kitchen", phone: "", ...st.settings.media_players });
  const settingsOut = (): Settings => {
    const { pin, ...rest } = st.settings;
    return { weather_entity: "", holidays: holidayRegion, ...rest, screens: { ...DEFAULT_SCREENS, ...rest.screens }, media_players: mediaPlayers(), pin_set: !!pin };
  };

  return {
    mode: "demo",
    subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); },
    settings: async () => settingsOut(),
    async updateSettings({ pin, new_pin, ...patch }) {
      checkPin(pin);
      if (new_pin != null && new_pin !== "" && !/^\d{4}$/.test(new_pin)) throw new ApiError(400, "new_pin must be 4 digits");
      const { media_players, idle_minutes, screens, security, ...rest } = patch;
      if (rest.weather_entity != null && rest.weather_entity !== "" && !/^weather\.[a-z0-9_]+$/.test(rest.weather_entity))
        throw new ApiError(400, "weather_entity must be a weather entity id like weather.home, or empty for demo weather");
      if (rest.weather_entity === null) rest.weather_entity = "";
      if (rest.holidays) {
        const { country = "", subdiv = "" } = rest.holidays;
        const known = DEMO_HOLIDAY_COUNTRIES.find((x) => x.code === country);
        if (country && !known) throw new ApiError(400, `No public holidays known for country ${country}`);
        if (subdiv && !known?.subdivs.some((x) => x.code === subdiv)) throw new ApiError(400, `${subdiv} isn't a region of ${country}`);
        rest.holidays = { country, subdiv };
        holidayRegion = rest.holidays;
      }
      Object.assign(st.settings, rest);
      if (media_players) {
        if (Object.entries(media_players).some(([k, v]) => !["large", "compact", "phone"].includes(k) || (v !== "" && !/^media_player\.[a-z0-9_]+$/.test(v ?? ""))))
          throw new ApiError(400, "media_players must map large/compact/phone to a media_player entity id or empty");
        st.settings.media_players = { ...st.settings.media_players, ...media_players };
      }
      if (security) {
        const cur = st.settings.security ?? {};
        const next: SecuritySettings = { ...cur, cameras: { ...cur.cameras }, popup: { large: true, compact: true, phone: false, tv: false, ...cur.popup, ...security.popup } };
        if (security.alarm_entity === null) delete next.alarm_entity;
        else if (security.alarm_entity !== undefined) next.alarm_entity = security.alarm_entity;
        for (const [k, v] of Object.entries(security.cameras ?? {})) {
          if (v === null) { delete next.cameras![k]; continue; }
          const cam = { ...next.cameras![k], ...v };
          if (v.person === null) delete cam.person;
          next.cameras![k] = cam;
        }
        st.settings.security = next;
      }
      if (idle_minutes) st.settings.idle_minutes = { ...st.settings.idle_minutes, ...idle_minutes };
      if (screens) {
        const cur = { ...DEFAULT_SCREENS, ...st.settings.screens };
        for (const [k, conf] of Object.entries(screens) as [Layout, Partial<ScreenSetup>][]) {
          const next = { ...cur[k], ...conf };
          next.sections = SECTIONS.filter((x) => next.sections.includes(x));
          if (!next.sections.length) throw new ApiError(400, `screens.${k}.sections must not be empty`);
          if (!next.sections.includes(next.start)) {
            if (conf.start) throw new ApiError(400, `screens.${k}.start must be one of its sections`);
            next.start = next.sections[0];
          }
          cur[k] = next;
        }
        st.settings.screens = cur;
      }
      if (new_pin) st.settings.pin = new_pin;
      emit("settings", "media", ...(security ? (["security", "security_alert"] as const) : []), ...(patch.holidays ? (["events", "chores"] as const) : []));
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
    async updateChore(id, patch) {
      const ch = find(st.chores, id);
      if ("title" in patch && !patch.title?.trim()) throw new ApiError(400, "title is required");
      if (patch.person_id && !st.people.some((p) => p.id === patch.person_id)) throw new ApiError(400, "person_id must be an existing person");
      Object.assign(ch, patch);
      emit("chores"); return clone(ch);
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
    async updateReward(id, patch) {
      const rw = find(st.rewards, id);
      if (patch.title !== undefined && !patch.title.trim()) throw new ApiError(400, "title is required");
      if (patch.cost !== undefined && !(patch.cost >= 0)) throw new ApiError(400, "cost must be >= 0");
      Object.assign(rw, patch); emit("rewards"); return clone(rw);
    },
    async deleteReward(id) { find(st.rewards, id); st.rewards = st.rewards.filter((r) => r.id !== id); emit("rewards"); },
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
    async updateList(id, patch) {
      const l = find(st.lists, id);
      if (patch.name !== undefined && !patch.name.trim()) throw new ApiError(400, "name is required");
      Object.assign(l, patch); emit("lists");
      return (await this.lists()).find((x) => x.id === id)!;
    },
    async deleteList(id) {
      find(st.lists, id);
      st.lists = st.lists.filter((l) => l.id !== id);
      st.items = st.items.filter((i) => i.list_id !== id);
      emit("lists");
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
    recipes: async () => [...st.recipes].sort((a, b) => a.title.localeCompare(b.title)).map(recipeOut),
    // The preview is all sample data; it has its own Reset instead (Settings > Demo).
    sampleData: async () => ({ remaining: 0 }),
    removeSampleData: async () => 0,
    async createRecipe(r) {
      const now = nowDT();
      const rec = { id: uid("rc"), minutes: null, url: null, ingredients: [], ...recipeFields(r), created_at: now, updated_at: now } as RecipeRow;
      st.recipes.push(rec);
      emit("recipes");
      return recipeOut(rec);
    },
    async updateRecipe(id, patch) {
      const rec = find(st.recipes, id);
      Object.assign(rec, recipeFields(patch, true), { updated_at: nowDT() });
      emit("recipes");
      return recipeOut(rec);
    },
    async deleteRecipe(id) {
      find(st.recipes, id);
      st.recipes = st.recipes.filter((r) => r.id !== id);
      for (const m of st.meals) if (m.recipe_id === id) m.recipe_id = null;
      emit("recipes", "meals");
    },
    async recipeCooked(id) {
      const rec = find(st.recipes, id);
      rec.cooked_count = (rec.cooked_count ?? 0) + 1;
      rec.last_cooked = today();
      emit("recipes");
      return recipeOut(rec);
    },
    async recipeToList(rid, lid, items) {
      const r = recipeOut(find(st.recipes, rid));
      find(st.lists, lid);
      const lines = (items ?? r.ingredients.filter((i) => !i.heading).map((i) => i.text)).map((t) => t.trim()).filter(Boolean);
      for (const title of lines) {
        st.items.push({ id: uid("it"), list_id: lid, title, done: false, person_id: null, due: null, created_at: nowDT(), sort: -1000, done_at: null });
      }
      emit("lists");
      return lines.length;
    },
    previewRecipe: async (r) => recipeOut({ id: null, ...recipeFields({ title: "-", ...r }, false, false) } as RecipeRow & { id: null }),
    async importRecipe(from) {
      if ("text" in from) {
        if (!from.text.trim()) throw new ApiError(400, "Send a url, some text, or images");
        const d = parseText(from.text);
        if (!d.ingredients.length && !d.steps.length) throw new ApiError(422, "No recipe found in that text.");
        return recipeOut({ id: null, ...recipeFields({ ...d, title: d.title || "Untitled recipe", url: null }, false, false) } as RecipeRow & { id: null });
      }
      if ("url" in from) throw new ApiError(422, "This preview can't open web pages. On your Moonlight, paste a recipe link here and it fills everything in.");
      throw new ApiError(409, "Reading photos needs Claude: add an Anthropic API key in Settings › Recipes. The iPhone app can read photos on the phone without one.");
    },
    async uploadImage(data) {
      const url = await new Promise<string>((res, rej) => { const fr = new FileReader(); fr.onload = () => res(String(fr.result)); fr.onerror = rej; fr.readAsDataURL(data); });
      const id = uid("img");
      st.images = { ...(st.images ?? {}), [id]: url };
      save();
      return { id, url };
    },
    recipeReader: async () => ({ configured: false, model: "claude-opus-5-5", key_hint: null }),
    recipeBatches: async () => [],
    async scanCookbook() { throw new ApiError(409, "Scanning a cookbook needs Claude: add an Anthropic API key in Settings › Recipes."); },
    async retryBatch() { throw new ApiError(404, "That scan is finished or was cancelled"); },
    async deleteBatch() { throw new ApiError(404, "That scan is finished or was cancelled"); },
    async saveAllDrafts() { throw new ApiError(404, "That scan is finished or was cancelled"); },
    async saveDraft() { throw new ApiError(404, "That recipe was already saved or put aside"); },
    async dismissDraft() { throw new ApiError(404, "That recipe was already saved or put aside"); },
    async exportRecipes() { throw new ApiError(409, "Exporting works with Moonlight running in Home Assistant."); },
    async importRecipes() { throw new ApiError(409, "Importing works with Moonlight running in Home Assistant."); },
    async saveRecipeReader() { throw new ApiError(400, "The preview can't use an API key. Add it on your Moonlight."); },
    removeRecipeReader: async () => ({ configured: false, model: "claude-opus-5-5", key_hint: null }),
    async weather() {
      const w = demoWeather();
      const e = st.settings.weather_entity;
      const names: Record<string, string> = { "weather.forecast_home": "Forecast Home", "weather.met_office_london": "Met Office London" };
      return e ? { ...w, source: "homeassistant" as const, entity: e, name: names[e] ?? e } : w;
    },
    async holidays(start, end, r) {
      if (end < start) throw new ApiError(400, "end must not be before start");
      if (r?.country && !DEMO_HOLIDAY_COUNTRIES.some((x) => x.code === r.country)) throw new ApiError(400, `No public holidays known for country ${r.country}`);
      if (!(r ?? holidayRegion).country) return [];
      return Object.entries(BANK_HOLIDAYS).filter(([d]) => d >= start && d <= end).map(([date, name]) => ({ date, name }));
    },
    holidayCountries: async () => DEMO_HOLIDAY_COUNTRIES,
    // A pretend Home Assistant with a few weather integrations (the forecast itself stays the demo one).
    weatherEntities: async () => {
      const now = demoWeather().current;
      return [
        { entity_id: "weather.forecast_home", name: "Forecast Home", available: true, condition: now.condition, temperature: now.temp, unit: "C", attribution: "Weather forecast from met.no" },
        { entity_id: "weather.met_office_london", name: "Met Office London", available: true, condition: "rainy", temperature: now.temp - 1, unit: "C", attribution: "Met Office" },
        { entity_id: "weather.openweathermap", name: "OpenWeatherMap", available: false, condition: null, temperature: null, unit: "C", attribution: null },
      ];
    },
    ...demoExtras(checkPin, emit, (l) => { // screens + simulated Immich, kept in memory
      const s = settingsOut();
      return { ...(s.screens?.[l] ?? DEFAULT_SCREENS[l]), speaker: s.media_players?.[l] ?? "", idle_minutes: s.idle_minutes?.[l] ?? DEFAULT_IDLE[l] };
    }),
    ...demoMedia(emit, mediaPlayers), // a pretend kitchen speaker
    ...demoSecurity(emit, () => st.settings.security, checkPin), // a pretend alarm and cameras
    accounts: async () => accts().map(acctOut),
    async connectAccount(a) {
      checkPin(a.pin);
      await wait(900); // "checking with iCloud"
      if (!a.username.trim() || !a.password.trim()) throw new ApiError(400, "Enter the Apple ID and app-specific password");
      if (accts().some((x) => x.username === a.username && x.kind === a.kind)) throw new ApiError(400, "That account is already connected");
      const first = !accts().some((x) => x.kind !== "ics" && x.kind !== "ha");
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
      if (["ics", "ha"].includes(find(accts(), id).kind)) st.events = st.events.filter((e) => !e.calendar_id || !mine.has(e.calendar_id));
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
    // A pretend Home Assistant with a few calendar integrations.
    haCalendars: async () => {
      await wait(400);
      const added = new Set(accts().filter((a) => a.kind === "ha").map((a) => a.username));
      return HA_CALENDARS.map(([entity_id, name]) => ({ entity_id, name, added: added.has(entity_id) }));
    },
    async addHaCalendar(f) {
      checkPin(f.pin);
      const found = HA_CALENDARS.find(([id]) => id === f.entity_id);
      if (!found) throw new ApiError(400, `Home Assistant has no calendar called ${f.entity_id}`);
      if (accts().some((a) => a.kind === "ha" && a.username === f.entity_id)) throw new ApiError(400, "That calendar is already added");
      await wait(600);
      const label = f.label?.trim() || found[1];
      const acct = { id: uid("acct"), kind: "ha" as const, label, username: f.entity_id, password: "", server_url: f.entity_id, status: "ok" as const, last_error: null, last_sync: nowDT(), calendar_count: 1 };
      const person = st.people.find((x) => x.id === f.person_ids[0]);
      const cal: SyncCalendar = {
        id: uid("cal"), account_id: acct.id, name: label, color: f.color ?? person?.color ?? "#8A94A6", person_ids: f.person_ids, visible: true,
        read_only: true, busy_blocks: false, busy_blocks_auto: false, busy_blocks_set: false,
      };
      accts().push(acct); cals().push(cal);
      const mon = weekStart(today(), "monday");
      const allDay = (d: string, title: string) => ({ id: uid("ev"), title, person_ids: [], start: `${d}T00:00`, end: `${addDays(d, 1)}T00:00`, all_day: true, location: "", notes: "", repeat: null, calendar_id: cal.id });
      if (f.entity_id === "calendar.bin_collections") {
        for (let w = 0; w < 8; w++) st.events.push(allDay(addDays(mon, 1 + w * 7), w % 2 ? "General waste" : "Recycling and garden"));
      } else if (f.entity_id.startsWith("calendar.workday")) {
        for (let d = 0; d < 21; d++) if (d % 7 < 5) st.events.push(allDay(addDays(mon, d), "Workday"));
      } else {
        [2, 9].forEach((d) => st.events.push({ ...allDay(addDays(mon, d), "Free electricity"), start: `${addDays(mon, d)}T13:00`, end: `${addDays(mon, d)}T15:00`, all_day: false }));
      }
      emit("accounts", "events");
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
      if (patch.name !== undefined) {
        cal.source_name ??= cal.name;
        cal.name = patch.name?.trim() || cal.source_name;
        delete patch.name;
        const acct = find(accts(), cal.account_id);
        if (acct.kind === "ics" || acct.kind === "ha") acct.label = cal.name;
      }
      Object.assign(cal, patch);
      emit("accounts", "events");
      return clone(cal);
    },
    async resetDemo() {
      st = buildSeed();
      holidayRegion = { country: "GB", subdiv: "ENG" };
      emit("people", "events", "chores", "points", "rewards", "lists", "meals", "recipes", "settings", "accounts");
    },
  };
}

export { iso };
