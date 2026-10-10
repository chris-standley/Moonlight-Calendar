export type Role = "adult" | "child";
export interface Person { id: string; name: string; initials: string; color: string; role: Role; sort: number }
/** Name (max 40 chars) and colour (#RRGGBB) are required; sort defaults to after everyone else. */
export interface PersonIn { name: string; color: string; role: Role; sort?: number }

export interface Settings {
  family_name: string;
  week_start: "monday" | "sunday";
  temp_unit: "C" | "F";
  pin_set: boolean;
  chore_approval: boolean;
  /** Photo screensaver: seconds per photo, idle minutes per screen (0 = never). Photos come from Immich. */
  screensaver_seconds?: number;
  idle_minutes?: Partial<Record<"hallway" | "kitchen" | "phone", number>>;
  timezone?: string;
}

export type Freq = "daily" | "weekly" | "monthly";
export interface Repeat { freq: Freq; interval: number; byday?: string[]; until?: string | null }

export interface EventIn {
  title: string;
  person_ids: string[];
  start: string;
  end: string;
  all_day: boolean;
  location?: string;
  notes?: string;
  repeat?: Repeat | null;
  /** Synced calendar to write to; null = only on Moonlight; omitted = server default. */
  calendar_id?: string | null;
}
export interface CalEvent extends EventIn {
  id: string;
  source?: AccountKind | null;
  /** Recurrence from iCloud that Moonlight can't edit (EXDATE, COUNT, moved occurrences...). */
  custom_repeat?: boolean;
  color?: string | null;
}
export interface Occurrence extends CalEvent { occurrence_id: string; recurring: boolean }

export type TimeOfDay = "morning" | "afternoon" | "evening" | "anytime";
export type ChoreSchedule = { type: "daily" } | { type: "weekly"; days: string[] } | { type: "once"; date: string };
export interface Chore {
  id: string; title: string; emoji: string; person_id: string; points: number;
  time_of_day: TimeOfDay; schedule: ChoreSchedule; sort: number;
}
export interface ChoreDay extends Chore { date: string; completed: boolean; completed_at: string | null; streak: number }

export interface Balance { person_id: string; balance: number }
export interface LedgerEntry { id: string; person_id: string; change: number; reason: string; at: string }
export interface Reward { id: string; title: string; emoji: string; cost: number; person_id: string | null }

export interface TaskList { id: string; name: string; emoji: string; color: string; kind: "grocery" | "todo"; sort: number; open_count: number; done_count: number }
export interface Item { id: string; list_id: string; title: string; done: boolean; person_id: string | null; due: string | null; created_at: string; sort: number }

export type Slot = "breakfast" | "lunch" | "dinner" | "snack";
export interface Meal { id: string; date: string; slot: Slot; title: string; notes: string; recipe_id: string | null }
export interface Recipe { id: string; title: string; emoji: string; minutes: number; ingredients: string[]; url: string | null }

export interface Weather {
  /** "homeassistant" when read from the add-on's weather_entity, else the built-in demo forecast. */
  source?: "homeassistant" | "demo";
  entity?: string | null;
  unit?: "C" | "F";
  current: { temp: number; condition: string };
  daily: { date: string; high: number; low: number; condition: string }[];
}

export type Layout = "hallway" | "kitchen" | "phone";
/** "service" = a non-screen client such as the Home Assistant integration. */
export interface Display { id: string; name: string; layout: Layout | "service"; created_at: string; last_seen: string | null; revoked: boolean; current: boolean }

// Photo screensaver source: the family's Immich server. Moonlight keeps the API key (write-only) and proxies previews.
export type ImmichStatus = "unconfigured" | "pending" | "ok" | "auth_failed" | "error";
export interface ImmichConfig {
  configured: boolean; server_url: string; key_set: boolean; album_ids: string[]; favorites: boolean; memories: boolean;
  status: ImmichStatus; last_error: string | null; last_refresh: string | null; photo_count: number; version: string | null;
}
export interface ImmichAlbum { id: string; name: string; asset_count: number; shared: boolean }
/** PUT /api/immich: `api_key` may be left out once one is saved. */
export interface ImmichIn { server_url?: string; api_key?: string; album_ids?: string[]; favorites?: boolean; memories?: boolean; pin: string }
export interface ImmichTest { ok: true; version: string | null; albums: ImmichAlbum[] }
/** A screensaver photo. `url` is ready for <img src> (the HTTP client prefixes the base path). Width/height may be null. */
export interface SlidePhoto { id: string; width: number | null; height: number | null; taken_at: string | null; url: string }
export interface ScreensaverPhotos { source: "immich" | "none"; status: ImmichStatus; photos: SlidePhoto[] }

export type Topic = "people" | "events" | "chores" | "points" | "rewards" | "lists" | "meals" | "recipes" | "settings" | "photos" | "displays" | "accounts";

// Calendar sync (iCloud / CalDAV). The password is write-only.
export type AccountKind = "icloud" | "caldav";
export type AccountStatus = "ok" | "auth_failed" | "error";
export interface Account {
  id: string; kind: AccountKind; label: string; username: string; server_url: string;
  status: AccountStatus; last_error: string | null; last_sync: string | null; calendar_count: number;
}
export interface AccountIn { kind: AccountKind; username: string; password: string; server_url?: string; label?: string; pin: string }
export interface SyncCalendar { id: string; account_id: string; name: string; color: string; person_ids: string[]; visible: boolean; read_only: boolean }

/** Default calendar for a new event (mirrors the server): the first person's own visible, writable calendar before shared ones. */
export function pickCalendar(cals: SyncCalendar[], personIds: string[]): string | null {
  const pid = personIds[0];
  const mine = cals.filter((c) => c.visible && !c.read_only && pid && c.person_ids.includes(pid));
  return mine.reduce<SyncCalendar | null>((best, c) => (!best || c.person_ids.length < best.person_ids.length ? c : best), null)?.id ?? null;
}

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

/** Both the HTTP client and the in-browser demo implement this. Mirrors API.md. */
export interface Api {
  mode: "live" | "demo";
  subscribe(fn: (topic: Topic) => void): () => void;
  settings(): Promise<Settings>;
  updateSettings(patch: Partial<Settings> & { pin: string }): Promise<Settings>;
  verifyPin(pin: string): Promise<boolean>;
  people(): Promise<Person[]>;
  createPerson(p: PersonIn): Promise<Person>;
  updatePerson(id: string, patch: Partial<PersonIn>): Promise<Person>;
  /** Needs the PIN. Deletes their chores, star history and personal rewards; takes them off events, items and calendars. */
  deletePerson(id: string, pin: string): Promise<void>;
  events(start: string, end: string): Promise<Occurrence[]>;
  createEvent(e: EventIn): Promise<CalEvent>;
  updateEvent(id: string, e: Partial<EventIn>): Promise<CalEvent>;
  deleteEvent(id: string): Promise<void>;
  allChores(): Promise<Chore[]>;
  chores(date: string): Promise<ChoreDay[]>;
  createChore(c: Omit<Chore, "id" | "sort">): Promise<Chore>;
  deleteChore(id: string): Promise<void>;
  completeChore(id: string, date: string): Promise<number>;
  uncompleteChore(id: string, date: string): Promise<number>;
  points(): Promise<Balance[]>;
  ledger(personId: string): Promise<LedgerEntry[]>;
  adjustPoints(personId: string, change: number, reason: string, pin: string): Promise<number>;
  rewards(): Promise<Reward[]>;
  createReward(r: Omit<Reward, "id">): Promise<Reward>;
  redeem(rewardId: string, personId: string, pin: string): Promise<number>;
  lists(): Promise<TaskList[]>;
  createList(l: Pick<TaskList, "name" | "emoji" | "color" | "kind">): Promise<TaskList>;
  items(listId: string): Promise<Item[]>;
  addItem(listId: string, title: string, personId?: string | null, due?: string | null): Promise<Item>;
  updateItem(id: string, patch: Partial<Pick<Item, "title" | "done" | "person_id" | "due">>): Promise<Item>;
  deleteItem(id: string): Promise<void>;
  clearDone(listId: string): Promise<void>;
  meals(start: string, end: string): Promise<Meal[]>;
  createMeal(m: Omit<Meal, "id">): Promise<Meal>;
  updateMeal(id: string, m: Partial<Omit<Meal, "id">>): Promise<Meal>;
  deleteMeal(id: string): Promise<void>;
  recipes(): Promise<Recipe[]>;
  recipeToList(recipeId: string, listId: string): Promise<number>;
  weather(): Promise<Weather>;
  // Wall screens (see API.md "Screens")
  displays(): Promise<Display[]>;
  approveDisplay(code: string, name: string, layout: Layout | null, pin: string): Promise<Display>;
  revokeDisplay(id: string, pin: string): Promise<void>;
  // Photo screensaver (Immich; see API.md "Photo screensaver")
  immich(): Promise<ImmichConfig>;
  saveImmich(c: ImmichIn): Promise<ImmichConfig>;
  disconnectImmich(pin: string): Promise<void>;
  /** Without server_url/api_key the saved ones are tested. */
  testImmich(t: { server_url?: string; api_key?: string; pin: string }): Promise<ImmichTest>;
  immichAlbums(): Promise<ImmichAlbum[]>;
  screensaverPhotos(): Promise<ScreensaverPhotos>;
  accounts(): Promise<Account[]>;
  connectAccount(a: AccountIn): Promise<Account>;
  reconnectAccount(id: string, creds: { password: string; username?: string; pin: string }): Promise<Account>;
  removeAccount(id: string, pin: string): Promise<void>;
  syncAccount(id: string): Promise<Account>;
  calendars(): Promise<SyncCalendar[]>;
  updateCalendar(id: string, patch: Partial<Pick<SyncCalendar, "person_ids" | "visible" | "color">>): Promise<SyncCalendar>;
  resetDemo?(): Promise<void>;
}
