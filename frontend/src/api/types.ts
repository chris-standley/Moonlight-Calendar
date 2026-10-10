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
  /** Photo screensaver: album id (null = all photos), seconds per photo, idle minutes per screen (0 = never). */
  screensaver_album?: string | null;
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
  /** In a read-only calendar (e.g. a calendar link): can't be edited or deleted here. */
  read_only?: boolean;
  /** Set only on calendars shown as busy blocks (free/busy feeds); "free" events are never returned. */
  busy?: BusyStatus | null;
}
export type BusyStatus = "busy" | "tentative" | "away" | "elsewhere" | "free";
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
export interface Album { id: string; name: string; created_at: string; photo_count: number; cover_photo_id: string | null }
export interface Photo {
  id: string; album_id: string; filename: string; width: number; height: number;
  taken_at: string | null; uploaded_at: string; uploaded_by: string | null;
  /** Ready to use as <img src> (the HTTP client prefixes the ingress base path). */
  display_url: string; thumb_url: string;
}
export interface UploadResult { uploaded: Photo[]; errors: { filename: string; detail: string }[] }

export type Topic = "people" | "events" | "chores" | "points" | "rewards" | "lists" | "meals" | "recipes" | "settings" | "photos" | "displays" | "accounts";

// Calendar sync (iCloud / CalDAV / published calendar links). Passwords and link URLs are write-only.
export type AccountKind = "icloud" | "caldav" | "ics";
export type AccountStatus = "ok" | "auth_failed" | "error";
/** For kind "ics" `server_url` is a masked form of the link (host/…/calendar.ics) and `username` is "". */
export interface Account {
  id: string; kind: AccountKind; label: string; username: string; server_url: string;
  status: AccountStatus; last_error: string | null; last_sync: string | null; calendar_count: number;
}
export interface AccountIn { kind: AccountKind; username: string; password: string; server_url?: string; label?: string; pin: string }
export interface SyncCalendar {
  id: string; account_id: string; name: string; color: string; person_ids: string[]; visible: boolean; read_only: boolean;
  /** Shown as "Chris – busy" blocks: the household's choice, else automatic (every summary is Busy/Free/...). */
  busy_blocks?: boolean; busy_blocks_auto?: boolean; busy_blocks_set?: boolean;
}
/** A published ICS link (webcal:// or https://); read-only, polled every 15 minutes. */
export interface FeedIn { url: string; label?: string; person_ids: string[]; color?: string; pin: string }
export interface FeedPreview { event_count: number; name: string; busy_only: boolean; masked_url: string }

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
  // Photos
  albums(): Promise<Album[]>;
  createAlbum(name: string): Promise<Album>;
  deleteAlbum(id: string, pin: string): Promise<void>;
  photos(albumId?: string | null): Promise<Photo[]>;
  uploadPhotos(albumId: string | null, files: File[]): Promise<UploadResult>;
  deletePhoto(id: string, pin: string): Promise<void>;
  accounts(): Promise<Account[]>;
  connectAccount(a: AccountIn): Promise<Account>;
  reconnectAccount(id: string, creds: { password: string; username?: string; pin: string }): Promise<Account>;
  removeAccount(id: string, pin: string): Promise<void>;
  syncAccount(id: string): Promise<Account>;
  /** Test a calendar link: how many events it has (nothing is saved). */
  previewFeed(url: string): Promise<FeedPreview>;
  addFeed(f: FeedIn): Promise<Account>;
  /** Paste a new link (verified first) and/or rename. */
  updateFeed(id: string, patch: { url?: string; label?: string; pin: string }): Promise<Account>;
  calendars(): Promise<SyncCalendar[]>;
  /** busy_blocks: null = automatic. */
  updateCalendar(id: string, patch: Partial<Pick<SyncCalendar, "person_ids" | "visible" | "color">> & { busy_blocks?: boolean | null }): Promise<SyncCalendar>;
  resetDemo?(): Promise<void>;
}
