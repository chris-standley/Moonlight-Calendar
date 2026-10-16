export type Role = "adult" | "child";
export interface Person { id: string; name: string; initials: string; color: string; role: Role; sort: number }
/** Name (max 40 chars) and colour (#RRGGBB) are required; sort defaults to after everyone else. */
export interface PersonIn { name: string; color: string; role: Role; sort?: number }

export interface Settings {
  family_name: string;
  week_start: "monday" | "sunday";
  temp_unit: "C" | "F";
  /** Light, dark, or "auto" (match the device's own setting; the default). */
  theme?: Theme;
  pin_set: boolean;
  chore_approval: boolean;
  /** Photo screensaver: seconds per photo, idle minutes per screen (0 = never). Photos come from Immich. */
  screensaver_seconds?: number;
  /** Show when and where each screensaver photo was taken (default true). */
  photo_details?: boolean;
  idle_minutes?: Partial<Record<Layout, number>>;
  timezone?: string;
  /** Speaker (HA media_player entity) per screen layout; "" = no Now playing card on that screen. */
  media_players?: Partial<Record<Layout, string>>;
  /** Home Assistant weather entity the screens show; "" = built-in demo forecast. */
  weather_entity?: string;
  /** Per kind of screen: the sections its menu shows (Settings always) and the one it opens on. */
  screens?: Partial<Record<Layout, ScreenSetup>>;
  /** Public holidays that repeats can skip: ISO country code and optional region ("" = whole country). */
  holidays?: HolidayRegion;
}
export interface HolidayRegion { country: string; subdiv: string }
export interface Holiday { date: string; name: string }
export interface HolidayCountry { code: string; name: string; subdivs: { code: string; name: string }[] }
export type Section = "today" | "calendar" | "chores" | "rewards" | "meals" | "lists";
export const SECTIONS: Section[] = ["today", "calendar", "chores", "rewards", "meals", "lists"];
export interface ScreenSetup { start: Section; sections: Section[] }
export const DEFAULT_SCREENS: Record<Layout, ScreenSetup> = {
  large: { start: "calendar", sections: ["calendar", "chores", "rewards", "meals", "lists"] },
  compact: { start: "today", sections: [...SECTIONS] },
  phone: { start: "today", sections: [...SECTIONS] },
};

export type Freq = "daily" | "weekly" | "monthly";
export interface Repeat { freq: Freq; interval: number; byday?: string[]; until?: string | null; skip_holidays?: boolean }

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
export type ChoreSchedule =
  | { type: "daily"; skip_holidays?: boolean }
  | { type: "weekly"; days: string[]; skip_holidays?: boolean }
  | { type: "once"; date: string };
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
/** One ingredient line as read by the add-on (API.md "Recipes"). `text` is the saved line; the rest is derived from it. */
export interface Ingredient {
  text: string; quantity: number | null; quantity_max: number | null; unit: string; name: string; note: string; heading: boolean;
  /** Set for cups, ounces, pounds, pints...: the same amount in grams or millilitres (unrounded). */
  metric: { quantity: number; quantity_max: number | null; unit: "g" | "ml" } | null;
}
export interface StepTimer { seconds: number; label: string }
export interface Step {
  text: string; minutes: number | null; photo: string | null; photo_url: string | null;
  /** Times the step mentions, ready to start. */
  timers: StepTimer[];
  /** The text with metric figures added in brackets, or null when nothing needed converting. */
  metric_text: string | null;
  /** Ingredients the step mentions (indexes into `ingredients`), in the order it mentions them. */
  uses: number[];
}
export interface Recipe {
  /** null for an unsaved draft (preview, import). */
  id: string; title: string; emoji: string; description: string; photo: string | null; photo_url: string | null;
  rating: number; favourite: boolean; servings: number | null; prep_minutes: number | null; cook_minutes: number | null;
  /** Total: as saved, else prep + cook. */
  minutes: number | null;
  ingredients: Ingredient[]; steps: Step[]; tags: string[]; notes: string; url: string | null;
  cooked_count: number; last_cooked: string | null; created_at: string | null; updated_at: string | null;
}
export interface StepIn { text: string; minutes?: number | null; photo?: string | null }
export interface RecipeIn {
  title: string; emoji?: string; description?: string; photo?: string | null; rating?: number; favourite?: boolean;
  servings?: number | null; prep_minutes?: number | null; cook_minutes?: number | null; minutes?: number | null;
  ingredients?: string[]; steps?: StepIn[]; tags?: string[]; notes?: string; url?: string | null;
}
export type RecipeImport = { url: string } | { text: string; use_reader?: boolean } | { images: string[] };
export interface RecipeReader { configured: boolean; model: string; key_hint: string | null }
export interface UploadedImage { id: string; url: string }

export interface WeatherEntity {
  entity_id: string; name: string; available: boolean;
  condition: string | null; temperature: number | null; unit: "C" | "F"; attribution: string | null;
}
export interface Weather {
  /** "homeassistant" when read from the chosen weather entity (Settings > Weather), else the built-in demo forecast. */
  source?: "homeassistant" | "demo";
  entity?: string | null;
  /** The entity's friendly name, when from Home Assistant. */
  name?: string;
  unit?: "C" | "F";
  current: { temp: number; condition: string };
  /** `rain`: chance of rain or snow that day in percent, null when the weather entity doesn't say. */
  daily: { date: string; high: number; low: number; condition: string; rain?: number | null }[];
}

export type Theme = "auto" | "light" | "dark";

/** Screen style: a big wall screen, a small touch screen, a phone. */
export type Layout = "large" | "compact" | "phone";
/** Not screens: "service" = the Home Assistant integration, "app" = the iPhone and iPad app (a person's device). */
export interface Display {
  id: string; name: string; layout: Layout | "service" | "app"; created_at: string; last_seen: string | null; revoked: boolean; current: boolean;
  /** Screens only: what it shows (its own choices, else its style's) and whether it has choices of its own. */
  setup?: DisplaySetup; own_setup?: boolean;
}
/** A paired screen's setup: menu sections, the one it opens on, its speaker ("" = none), screensaver delay (0 = never). */
export interface DisplaySetup { start: Section; sections: Section[]; speaker: string; idle_minutes: number }
export interface DisplayPatch { pin: string; name?: string; layout?: Layout; setup?: Partial<DisplaySetup> | null }
export const DEFAULT_IDLE: Record<Layout, number> = { large: 5, compact: 3, phone: 0 };
export const STYLE_LABEL: Record<Layout, string> = { large: "Large", compact: "Compact", phone: "Phone" };

// Photo screensaver source: the family's Immich server. Moonlight keeps the API key (write-only) and proxies previews.
export type ImmichStatus = "unconfigured" | "pending" | "ok" | "auth_failed" | "error";
export interface ImmichConfig {
  configured: boolean; server_url: string; key_set: boolean; album_ids: string[]; favorites: boolean; memories: boolean;
  /** HTTPS without checking the certificate (self-signed, or one made for a domain name while Moonlight uses the IP). */
  skip_cert_check: boolean;
  status: ImmichStatus; last_error: string | null; last_refresh: string | null; photo_count: number; version: string | null;
}
export interface ImmichAlbum { id: string; name: string; asset_count: number; shared: boolean }
/** PUT /api/immich: `api_key` may be left out once one is saved. */
export interface ImmichIn { server_url?: string; api_key?: string; album_ids?: string[]; favorites?: boolean; memories?: boolean; skip_cert_check?: boolean; pin: string }
export interface ImmichTest { ok: true; version: string | null; albums: ImmichAlbum[] }
/** A screensaver photo. `url` is ready for <img src> (the HTTP client prefixes the base path). Width/height may be null. */
/** `taken_at`: local time where it was taken (show the digits as they are). `place`: HA zone name or town, if known. */
export interface SlidePhoto { id: string; width: number | null; height: number | null; taken_at: string | null; place?: string | null; url: string }
export interface ScreensaverPhotos { source: "immich" | "none"; status: ImmichStatus; photos: SlidePhoto[] }

export type Topic = "people" | "events" | "chores" | "points" | "rewards" | "lists" | "meals" | "recipes" | "settings" | "photos" | "displays" | "accounts" | "media";

/** GET /api/media/now-playing: the speaker set for this screen's layout (see API.md "Music"). */
export interface NowPlaying {
  layout: Layout;
  configured: boolean;
  entity: string | null;
  name: string | null;
  /** HA media_player state: playing, paused, idle, off, standby, buffering, unavailable... */
  state: string;
  /** Worth showing: playing/paused/buffering, or idle with a track still loaded. */
  show: boolean;
  title: string | null; artist: string | null; album: string | null;
  /** Seconds; position was `position` at `position_updated_at` (HA's clock; compare with server_time). */
  duration: number | null; position: number | null; position_updated_at: string | null;
  volume: number | null; muted: boolean | null; shuffle: boolean | null; repeat: "off" | "all" | "one" | null;
  source: string | null; app: string | null; music_assistant: boolean;
  has_art: boolean;
  /** Ready to use as <img src> (served by Moonlight; changes with the track). */
  art_url: string | null;
  supports: { play_pause: boolean; previous: boolean; next: boolean; volume: boolean; mute: boolean; shuffle: boolean; repeat: boolean; seek: boolean };
  reachable: boolean;
  error: string | null;
  server_time: string;
}
export type MediaAction = "play_pause" | "play" | "pause" | "next" | "previous" | "volume_set" | "volume_mute" | "shuffle_set" | "repeat_set";
export interface MediaPlayerOption { entity_id: string; name: string; state: string; music_assistant: boolean }
export interface MediaFavourite { uri: string; name: string; media_type: string }

// Calendar sync (iCloud / CalDAV / published calendar links / Home Assistant calendars). Passwords and link URLs are write-only.
export type AccountKind = "icloud" | "caldav" | "ics" | "ha";
export type AccountStatus = "ok" | "auth_failed" | "error";
/** For kind "ics" `server_url` is a masked form of the link (host/…/calendar.ics) and `username` is "".
 *  For kind "ha" both are the Home Assistant entity id (calendar.bins). */
export interface Account {
  id: string; kind: AccountKind; label: string; username: string; server_url: string;
  status: AccountStatus; last_error: string | null; last_sync: string | null; calendar_count: number;
}
export interface AccountIn { kind: AccountKind; username: string; password: string; server_url?: string; label?: string; pin: string }
export interface SyncCalendar {
  id: string; account_id: string; name: string; color: string; person_ids: string[]; visible: boolean; read_only: boolean;
  /** The server's own name; `name` is the household's name for it when one was set. */
  source_name?: string;
  /** Shown as "Chris – busy" blocks: the household's choice, else automatic (every summary is Busy/Free/...). */
  busy_blocks?: boolean; busy_blocks_auto?: boolean; busy_blocks_set?: boolean;
}
/** A published ICS link (webcal:// or https://); read-only, polled every 15 minutes. */
export interface FeedIn { url: string; label?: string; person_ids: string[]; color?: string; pin: string }
/** A Home Assistant calendar entity (bin days, Workday, energy sessions); read-only, polled every 15 minutes. */
export interface HaCalendar { entity_id: string; name: string; added: boolean }
export interface HaCalendarIn { entity_id: string; label?: string; person_ids: string[]; color?: string; pin: string }
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
  /** `new_pin` (4 digits) replaces the parent PIN; `pin` must be the current one. */
  updateSettings(patch: Partial<Omit<Settings, "screens">> & { screens?: Partial<Record<Layout, Partial<ScreenSetup>>>; pin: string; new_pin?: string }): Promise<Settings>;
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
  updateChore(id: string, patch: Partial<Omit<Chore, "id">>): Promise<Chore>;
  deleteChore(id: string): Promise<void>;
  completeChore(id: string, date: string): Promise<number>;
  uncompleteChore(id: string, date: string): Promise<number>;
  points(): Promise<Balance[]>;
  ledger(personId: string): Promise<LedgerEntry[]>;
  adjustPoints(personId: string, change: number, reason: string, pin: string): Promise<number>;
  rewards(): Promise<Reward[]>;
  createReward(r: Omit<Reward, "id">): Promise<Reward>;
  updateReward(id: string, patch: Partial<Omit<Reward, "id">>): Promise<Reward>;
  deleteReward(id: string): Promise<void>;
  redeem(rewardId: string, personId: string, pin: string): Promise<number>;
  lists(): Promise<TaskList[]>;
  createList(l: Pick<TaskList, "name" | "emoji" | "color" | "kind">): Promise<TaskList>;
  updateList(id: string, patch: Partial<Pick<TaskList, "name" | "emoji" | "color" | "kind" | "sort">>): Promise<TaskList>;
  /** Deletes the list and all its items. */
  deleteList(id: string): Promise<void>;
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
  /** Adds the chosen lines (as shown, already scaled), else every ingredient. */
  recipeToList(recipeId: string, listId: string, items?: string[]): Promise<number>;
  createRecipe(r: RecipeIn): Promise<Recipe>;
  /** Made it today: counts up and remembers the day. */
  recipeCooked(id: string): Promise<Recipe>;
  /** How a recipe body reads once saved (parsed ingredients, timers, metric), without saving it. */
  previewRecipe(r: Partial<RecipeIn>): Promise<Recipe>;
  /** An unsaved draft from a web page, text, or photos (uploaded first). 422/409 carry a message to show. */
  importRecipe(from: RecipeImport): Promise<Recipe>;
  /** Upload a picture (already shrunk); use the id as a recipe's or step's photo. */
  uploadImage(data: Blob): Promise<UploadedImage>;
  recipeReader(): Promise<RecipeReader>;
  saveRecipeReader(r: { api_key?: string; model?: string | null; pin: string }): Promise<RecipeReader>;
  removeRecipeReader(pin: string): Promise<RecipeReader>;
  /** Rows of the demo family seeded on first start that are still present (see API.md "Settings"). */
  sampleData(): Promise<{ remaining: number }>;
  removeSampleData(pin: string): Promise<number>;
  updateRecipe(id: string, patch: Partial<RecipeIn>): Promise<Recipe>;
  /** Meals planned from it keep their title and lose the link. */
  deleteRecipe(id: string): Promise<void>;
  weather(): Promise<Weather>;
  /** Home Assistant's weather entities with current conditions (Settings > Weather). */
  weatherEntities(): Promise<WeatherEntity[]>;
  /** Public holidays start..end inclusive (YYYY-MM-DD), in the household's region or the one given (a preview). */
  holidays(start: string, end: string, region?: HolidayRegion): Promise<Holiday[]>;
  /** Countries and their regions with known public holidays (Settings > Display). */
  holidayCountries(): Promise<HolidayCountry[]>;
  // Wall screens (see API.md "Screens")
  displays(): Promise<Display[]>;
  approveDisplay(code: string, name: string, layout: Layout | null, pin: string): Promise<Display>;
  revokeDisplay(id: string, pin: string): Promise<void>;
  /** Rename a screen, change its style or its setup (`setup: null` = follow its style again). */
  updateDisplay(id: string, patch: DisplayPatch): Promise<Display>;
  /** The paired screen this is (null in the Home Assistant app, a browser with auth off, or the demo). */
  thisScreen(): Promise<Display | null>;
  // Photo screensaver (Immich; see API.md "Photo screensaver")
  immich(): Promise<ImmichConfig>;
  saveImmich(c: ImmichIn): Promise<ImmichConfig>;
  disconnectImmich(pin: string): Promise<void>;
  /** Without server_url/api_key the saved ones are tested. */
  testImmich(t: { server_url?: string; api_key?: string; skip_cert_check?: boolean; pin: string }): Promise<ImmichTest>;
  immichAlbums(): Promise<ImmichAlbum[]>;
  screensaverPhotos(): Promise<ScreensaverPhotos>;
  accounts(): Promise<Account[]>;
  connectAccount(a: AccountIn): Promise<Account>;
  reconnectAccount(id: string, creds: { password: string; username?: string; pin: string }): Promise<Account>;
  removeAccount(id: string, pin: string): Promise<void>;
  syncAccount(id: string): Promise<Account>;
  /** Test a calendar link: how many events it has (nothing is saved). */
  previewFeed(url: string): Promise<FeedPreview>;
  addFeed(f: FeedIn): Promise<Account>;
  /** Home Assistant's calendar entities (409 when Moonlight isn't connected to Home Assistant). */
  haCalendars(): Promise<HaCalendar[]>;
  addHaCalendar(f: HaCalendarIn): Promise<Account>;
  /** Paste a new link (verified first) and/or rename. */
  updateFeed(id: string, patch: { url?: string; label?: string; pin: string }): Promise<Account>;
  calendars(): Promise<SyncCalendar[]>;
  /** busy_blocks: null = automatic. */
  updateCalendar(id: string, patch: Partial<Pick<SyncCalendar, "person_ids" | "visible" | "color">> & { busy_blocks?: boolean | null; name?: string | null }): Promise<SyncCalendar>;
  // Music (see API.md "Music"): the speaker set for a screen layout, through Home Assistant / Music Assistant.
  nowPlaying(layout: Layout): Promise<NowPlaying>;
  mediaCommand(layout: Layout, action: MediaAction, value?: number | boolean | string): Promise<NowPlaying>;
  mediaPlayers(): Promise<MediaPlayerOption[]>;
  mediaFavourites(layout: Layout): Promise<MediaFavourite[]>;
  playFavourite(layout: Layout, uri: string): Promise<NowPlaying>;
  resetDemo?(): Promise<void>;
}
