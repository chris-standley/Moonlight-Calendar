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
  /** Settings > Security: the alarm panel ("" = none, absent = automatic), per-camera choices, pop-up per style. */
  security?: SecuritySettings;
  /** Settings > Energy: entity per slot ("" = none, absent = automatic) and sign flips. */
  energy?: EnergySettings;
}
export interface HolidayRegion { country: string; subdiv: string }
export interface Holiday { date: string; name: string }
export interface HolidayCountry { code: string; name: string; subdivs: { code: string; name: string }[] }
export type Section = "today" | "calendar" | "chores" | "rewards" | "meals" | "recipes" | "lists" | "nursery" | "security" | "energy";
export const SECTIONS: Section[] = ["today", "calendar", "chores", "rewards", "meals", "recipes", "lists", "nursery", "security", "energy"];
/** `bar`: up to four tabs kept in the bottom bar of a compact screen stood upright, the rest under More (unset = the menu's first four). */
export interface ScreenSetup { start: Section; sections: Section[]; bar?: BarTab[] | null }
export type BarTab = Section | "music" | "settings";
export const BAR_MAX = 4;
export const DEFAULT_SCREENS: Record<Layout, ScreenSetup> = {
  large: { start: "calendar", sections: ["calendar", "chores", "rewards", "meals", "recipes", "lists", "nursery", "security", "energy"] },
  compact: { start: "today", sections: SECTIONS.filter((s) => s !== "nursery") },
  phone: { start: "today", sections: SECTIONS.filter((s) => s !== "nursery") },
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
  /** A key of COURSES (recipes/courses.ts), or null. `book`: the cookbook it came from ("" when none). */
  course: string | null; book: string; book_page: number | null;
  cooked_count: number; last_cooked: string | null; created_at: string | null; updated_at: string | null;
}
export interface StepIn { text: string; minutes?: number | null; photo?: string | null }
export interface RecipeIn {
  title: string; emoji?: string; description?: string; photo?: string | null; rating?: number; favourite?: boolean;
  servings?: number | null; prep_minutes?: number | null; cook_minutes?: number | null; minutes?: number | null;
  ingredients?: string[]; steps?: StepIn[]; tags?: string[]; notes?: string; url?: string | null;
  course?: string | null; book?: string; book_page?: number | null;
}
export type RecipeImport = { url: string } | { text: string; use_reader?: boolean } | { images: string[] };
export interface RecipeReader { configured: boolean; model: string; key_hint: string | null }
export interface UploadedImage { id: string; url: string }
/** Files for other recipe apps: Mela (.melarecipes), Paprika (.paprikarecipes) or schema.org Recipe JSON. */
export type RecipeExportFormat = "mela" | "paprika" | "schema";
export interface RecipeImportResult { added: number; skipped: string[]; failed: string[] }
/** A recipe found in a cookbook scan, waiting to be checked. `pages` are page numbers in the scan, from 1. */
export interface RecipeDraft { id: string; pages: number[]; recipe: Recipe }
/** A whole cookbook being read by Claude, page by page (see API.md "Scanning a cookbook"). */
export interface RecipeBatch {
  id: string; pages: number; read: number; reading: boolean; saved: number;
  /** Sent as an Anthropic Message Batch: half price, usually read within the hour, at most a day. */
  cheaper: boolean;
  /** The cookbook's name, given to every recipe found. */
  book: string;
  failed: { page: number; error: string }[]; drafts: RecipeDraft[];
}

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
export interface DisplaySetup { start: Section; sections: Section[]; speaker: string; idle_minutes: number; bar?: BarTab[] | null }
export interface DisplayPatch { pin: string; name?: string; layout?: Layout; setup?: Partial<DisplaySetup> | null }
export const DEFAULT_IDLE: Record<Layout, number> = { large: 5, compact: 3, phone: 0 };
export const STYLE_LABEL: Record<Layout, string> = { large: "Large", compact: "Compact", phone: "Phone" };

// Photo screensaver source: the family's Immich server. Moonlight keeps the API key (write-only) and proxies previews.
export type ImmichStatus = "unconfigured" | "pending" | "ok" | "auth_failed" | "error";
/** `albums` = the chosen albums (+ favourites, memories); `all` = the whole library except the excluded albums. */
export type ImmichMode = "albums" | "all";
export interface ImmichConfig {
  configured: boolean; server_url: string; key_set: boolean; mode: ImmichMode; album_ids: string[]; excluded_album_ids: string[];
  /** Festive filter: albums named for Christmas only in December, and in December only those and winter albums. */
  festive: boolean; favorites: boolean; memories: boolean;
  /** It's December and only festive and winter albums are showing. */
  festive_now?: boolean;
  /** HTTPS without checking the certificate (self-signed, or one made for a domain name while Moonlight uses the IP). */
  skip_cert_check: boolean;
  status: ImmichStatus; last_error: string | null; last_refresh: string | null; photo_count: number; version: string | null;
}
export interface ImmichAlbum { id: string; name: string; asset_count: number; shared: boolean; updated_at?: string | null }
/** PUT /api/immich: `api_key` may be left out once one is saved. */
export interface ImmichIn { server_url?: string; api_key?: string; mode?: ImmichMode; album_ids?: string[]; excluded_album_ids?: string[]; festive?: boolean; favorites?: boolean; memories?: boolean; skip_cert_check?: boolean; pin: string }
export interface ImmichTest { ok: true; version: string | null; albums: ImmichAlbum[] }
/** A screensaver photo. `url` is ready for <img src> (the HTTP client prefixes the base path). Width/height may be null. */
/** `taken_at`: local time where it was taken (show the digits as they are). `place`: HA zone name or town, if known. */
export interface SlidePhoto { id: string; width: number | null; height: number | null; taken_at: string | null; place?: string | null; url: string }
/** One album's photos, oldest first. `id` is "favorites" or "on-this-day" for those; `updated_at` = last change in Immich. */
export interface PhotoAlbum { id: string; name: string; updated_at: string | null; photos: string[] }
/** `albums` (newest first) is what the screensaver plays, one whole album at a time; older servers send only `photos`. */
export interface ScreensaverPhotos { source: "immich" | "none"; status: ImmichStatus; photos: SlidePhoto[]; albums?: PhotoAlbum[] }
/** The screensaver's hide button: the albums (all it was in) it was taken out of in Immich, and any Immich wouldn't change (still hidden). */
export interface HideResult { ok: true; removed: { id: string; name: string }[]; failed: { id: string; name: string; error: string }[] }
/** A photo hidden from the screensaver; "Show again" puts it back in `albums`. */
export interface HiddenPhoto { id: string; albums: { id: string; name: string }[]; hidden_at: string; url: string }


/** Nursery updates from Tapestry (see API.md "Nursery"). The password is never sent back. */
export type NurseryStatus = "unconfigured" | "pending" | "ok" | "auth_failed" | "error";
export interface NurseryConfig {
  configured: boolean; email: string; school: string; school_name: string | null;
  status: NurseryStatus; last_error: string | null; last_sync: string | null; count: number;
}
/** PUT /api/nursery: `password` may be left out once saved (same email). `school`: name or part of it, "" = the first. */
export interface NurseryIn { email?: string; password?: string; school?: string; pin: string }
/** `url` is ready for <img src>. `video`: the still of a video (the video itself stays on Tapestry). */
export interface NurseryPhoto { url: string; video: boolean }
/** `date`: when the nursery wrote it, local time (YYYY-MM-DDTHH:MM:SS, or a bare date). `children[].person_id`: the
 * Moonlight person with the same first name, if any. */
export interface NurseryUpdate {
  id: string; title: string; notes: string; author: string; date: string;
  children: { name: string; person_id: string | null; color: string | null }[];
  photos: NurseryPhoto[]; comments: { author: string; date: string | null; text: string }[]; added_at: string;
}
export type Topic = "people" | "events" | "chores" | "points" | "rewards" | "lists" | "meals" | "recipes" | "settings" | "photos" | "displays" | "accounts" | "media" | "security" | "security_alert" | "nursery" | "alerts" | "energy";

// Security (see API.md "Security"): the alarm, Alarmo's sensors and the cameras, from Home Assistant.
/** Where a camera that sees a person pops up: each screen style, and the Apple TV app on its own. */
export type PopupTarget = Layout | "tv";
export interface SecuritySettings {
  alarm_entity?: string;
  /** null person = automatic (the camera's own "Person detected" sensor); "" = never pop up. */
  cameras?: Record<string, { show?: boolean; person?: string | null }>;
  popup?: Record<PopupTarget, boolean>;
}
export interface SecuritySettingsPatch {
  alarm_entity?: string | null;
  cameras?: Record<string, { show?: boolean; person?: string | null } | null>;
  popup?: Partial<Record<PopupTarget, boolean>>;
}
export interface AlarmState {
  entity_id: string; name: string;
  /** HA alarm state: disarmed, armed_home, armed_away, armed_night, arming, pending, triggered... */
  state: string; label: string; armed: boolean; alarmo: boolean; available: boolean;
  changed_by: string | null; last_changed: string | null; next_state: string | null; delay: number | null;
  /** Sensors keeping it from arming (Alarmo), by name. */
  open_sensors: string[];
  /** The ways it can be armed. */
  modes: AlarmMode[];
  /** Arming asks for the code too (disarming always does). */
  code_arm_required: boolean;
}
export type AlarmMode = "away" | "home" | "night" | "vacation";
export type SensorGroup = "doors" | "windows" | "motion" | "environment" | "other";
export interface SecuritySensor {
  entity_id: string; name: string; group: SensorGroup; state: string;
  /** "Open", "Closed", "Motion", "Clear", "Unavailable"... */
  label: string; active: boolean; available: boolean;
  /** Guarded in the alarm's current mode. */
  armed: boolean; last_changed: string | null;
}
/** `snapshot_url` / `live_url` are ready for <img src> (live is MJPEG, about two pictures a second). `video_url` is
 * Home Assistant's HLS video of the camera (smooth; hls.js or Safari), null when the camera has none; `video_hd_url` is its full
 * resolution for large screens (the same as `video_url` when Home Assistant has no lighter channel). */
export interface SecurityCamera { entity_id: string; name: string; available: boolean; person: boolean; snapshot_url: string; live_url: string; video_url: string | null; video_hd_url: string | null }
export interface SecurityAlert { camera: string; name: string; since: string | null; test: boolean; live_url: string; snapshot_url: string; video_url: string | null; video_hd_url: string | null }
export interface SecurityOverview {
  configured: boolean; reachable: boolean; error: string | null;
  /** "alarmo" when the sensor list came from Alarmo, "none" when there is no sensor list. */
  sensors_source: "alarmo" | "none";
  alarm: AlarmState | null; sensors: SecuritySensor[]; cameras: SecurityCamera[]; alerts: SecurityAlert[];
}
export interface SecurityOptions {
  alarm_entity: string;
  panels: { entity_id: string; name: string; alarmo: boolean; state: string }[];
  cameras: { entity_id: string; name: string; show: boolean; person: string; auto_person: boolean; default_person: string; available: boolean }[];
  person_sensors: { entity_id: string; name: string }[];
  sensors_source: "alarmo" | "none"; sensor_count: number;
  popup: Record<PopupTarget, boolean>;
}

// Energy (see API.md "Energy"): solar, battery, grid, car and heat pump from Home Assistant, drawn as a house.
export type EnergySlot =
  | "solar_power" | "solar_today" | "solar_forecast" | "solar_forecast_tomorrow" | "battery_soc" | "battery_power" | "grid_power" | "grid_import_today" | "grid_export_today"
  | "home_power" | "home_today" | "car_plug" | "car_status" | "car_power" | "car_soc" | "car_range" | "car_session" | "car_limit" | "car_ready"
  | "heat_pump_mode" | "heat_pump_power" | "heat_pump_today" | "heat_pump_flow" | "heat_pump_return" | "heat_pump_flow_rate"
  | "heat_pump_details" | "inside_temp" | "outdoor_temp" | "heat_pump_tank"
  | "heating_target" | "tank_target" | "inside_humidity" | "outside_humidity"
  | "plan_status" | "plan_cost_today" | "plan_rate_now" | "plan_rate_export" | "plan_battery_hours"
  | "plan_charge_start" | "plan_charge_end" | "plan_cheap_start" | "plan_cheap_end" | "cheap_off_peak" | "cheap_dispatches";
export type EnergyKind = "power" | "energy" | "percent" | "temperature" | "number" | "state";
export type EnergyGroup = "solar" | "battery" | "grid" | "home" | "car" | "heat_pump" | "temperatures" | "plan";
export interface EnergySettings { entities?: Partial<Record<EnergySlot, string>>; battery_invert?: boolean; grid_invert?: boolean; hide?: EnergyHide[] }
export interface EnergySettingsPatch { entities?: Partial<Record<EnergySlot, string | null>>; battery_invert?: boolean | null; grid_invert?: boolean | null;
  /** Parts and readings (the temperatures group) left off the picture. */
  hide?: EnergyHide[] }
export type EnergyPart = "solar" | "battery" | "grid" | "home" | "car" | "heat_pump" | "plan";
export type EnergyHide = EnergyPart | EnergySlot;
/** Power in watts, energy in kWh; null when the sensor has no reading. Each part is null when nothing is set for it. */
export interface EnergyOverview {
  configured: boolean; reachable: boolean; error: string | null; updated: string | null;
  /** forecast_*: kWh expected; starts/ends: when today's forecast has the panels producing (ISO). */
  solar: { power: number | null; today: number | null; forecast_today: number | null; forecast_tomorrow: number | null; starts: string | null; ends: string | null } | null;
  /** power: positive = discharging into the house, negative = charging. */
  battery: { soc: number | null; power: number | null; state: "charging" | "discharging" | "idle" | null } | null;
  /** power: positive = importing, negative = exporting. */
  grid: { power: number | null; state: "importing" | "exporting" | "idle" | null; import_today: number | null; export_today: number | null } | null;
  /** computed: no home sensor, so worked out from solar + battery + grid. */
  home: { power: number | null; today: number | null; computed: boolean } | null;
  car: { plugged_in: boolean | null; charging: boolean | null; status: string | null; power: number | null; soc: number | null; range: number | null; range_unit: string | null; session: number | null;
    /** limit: the % charging stops at; ready: when it should be done by (ISO). */
    limit: number | null; ready: string | null } | null;
  /** doing: "Heating the house", "Heating hot water", "Defrosting", "Idle"... */
  /** heat: watts going into the water; cop: heat ÷ power right now; cop_today: added up since midnight. */
  heat_pump: { running: boolean; doing: string; power: number | null; today: number | null; flow_temp: number | null; heat: number | null; cop: number | null;
    cop_today: { heating: number | null; hot_water: number | null; overall: number | null } | null } | null;
  /** °C; *_target: the heat pump's set points; humidity in %. */
  temperatures: { inside: number | null; outside: number | null; tank: number | null; heating_target?: number | null; tank_target?: number | null;
    inside_humidity?: number | null; outside_humidity?: number | null; hidden?: string[] } | null;
  /** From Predbat. Money in cost_unit/rate_unit (usually "p"); times ISO. */
  plan: { status: string | null; cost_today: number | null; cost_unit: string | null; rate_now: number | null; rate_export: number | null; rate_unit: string | null;
    battery_hours: number | null; charge: EnergyWindow | null; cheap: EnergyWindow | null } | null;
  tariff: EnergyTariff | null;
  /** Home Assistant's sun: night after sunset (the picture goes dark), and when that next changes (ISO). */
  sun?: { night: boolean; next: string | null } | null;
}
/** Cheap electricity from the Octopus Energy integration; bonus: car-charging slots outside the usual night hours. */
export interface EnergyTariff { cheap_now: boolean; cheap_until: string | null; next: { start: string; end: string } | null; bonus: { start: string; end: string }[]; dispatching: boolean | null }
export interface EnergyWindow { start: string; end: string | null; rate: number | null }
export interface EnergyCandidate { entity_id: string; name: string; state: string | null; unit: string | null }
export interface EnergyOptions {
  slots: Record<EnergySlot, { kind: EnergyKind; group: EnergyGroup; entities: string[]; auto: boolean; suggested: string[] }>;
  battery_invert: boolean; grid_invert: boolean; hide?: EnergyHide[];
  candidates: Record<EnergyKind, EnergyCandidate[]>;
}

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
  /** The player actually shown and driven when the speaker hands over to one it fronts (an idle Music Assistant
   * speaker while its Sonos plays from the Sonos app); null normally. */
  via?: string | null;
  has_art: boolean;
  /** Ready to use as <img src> (served by Moonlight; changes with the track). */
  art_url: string | null;
  supports: { play_pause: boolean; previous: boolean; next: boolean; volume: boolean; mute: boolean; shuffle: boolean; repeat: boolean; seek: boolean; grouping?: boolean };
  reachable: boolean;
  error: string | null;
  server_time: string;
}
export type MediaAction = "play_pause" | "play" | "pause" | "next" | "previous" | "volume_set" | "volume_mute" | "shuffle_set" | "repeat_set";
export interface MediaPlayerOption { entity_id: string; name: string; state: string; music_assistant: boolean }
export interface MediaFavourite { uri: string; name: string; media_type: string }

// The Music tab (see API.md "Music tab").
/** Something in the library: open it (can_expand) and/or play it (can_play). `thumb` is ready for <img src>. */
export interface MediaItem {
  id: string; type: string; title: string; subtitle: string | null;
  /** HA's media class (album, playlist, podcast, artist, track, directory...) or Music Assistant's media type. */
  kind: string;
  can_play: boolean; can_expand: boolean; thumb: string | null;
}
export interface MediaBrowse extends MediaItem { items: MediaItem[]; more: number }
export type Enqueue = "replace" | "next" | "add";
export interface QueueTrack {
  /** What to send back to jump to / remove / move it. */
  key: string; index: number | null;
  title: string; artist: string | null; album: string | null; duration: number | null; thumb: string | null; current: boolean;
}
export interface MediaQueue {
  source: "music_assistant" | "sonos" | "none";
  /** false: only the current and next track are known (Music Assistant without its own connection). */
  full: boolean; total: number; current: number | null; items: QueueTrack[];
  can_jump: boolean; can_remove: boolean; can_move: boolean;
}
export type QueueAction = "play" | "remove" | "next";
export interface MediaRoom {
  entity_id: string; name: string; state: string;
  /** This screen's speaker. */
  this: boolean;
  /** Playing together with this screen's speaker. */
  grouped: boolean;
  volume: number | null; muted: boolean | null; playing: string | null; can_volume: boolean;
}
export interface MediaRooms { entity: string; can_group: boolean; rooms: MediaRoom[] }
export type RoomAction = "join" | "unjoin" | "volume" | "mute";
/** Settings > Music: Moonlight's own connection to Music Assistant (for its whole queue). The token is write-only. */
export interface MusicAssistantLink { url: string; detected_url: string | null; token_set: boolean }

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

/** A notification or timer put on the screens, usually by Home Assistant (see API.md "Notifications and timers").
 * Times are epoch milliseconds on the server's clock. `expires_at` null = until dismissed or cleared. */
export interface ScreenAlert {
  id: string; kind: "notification" | "timer"; style: "fullscreen" | "toast"; screens: string[];
  icon: string; dismissible: boolean; chime: boolean; created_at: number; expires_at: number | null;
  /** notification */
  title?: string; message?: string; image?: string | null;
  /** timer: counts down to `ends_at` (a countdown to a date has a long one); `finished` once it got there. A
   * `count_up` one counts up from `started_at` instead (how long since the kettle boiled): `ends_at` is null. */
  label?: string; description?: string; count_up?: boolean; started_at?: number; ends_at?: number | null; finished?: boolean; finished_for?: number | null;
}
export interface AlertsNow { server_time: number; alerts: ScreenAlert[] }
/** POST /api/alerts: `duration` and `finished_for` in seconds, `until` an ISO date-time; `since` ("now" or an ISO
 * date-time) makes a timer count up, and then `duration` is how long after `since` it goes. */
export interface AlertIn {
  kind?: "notification" | "timer"; style?: "fullscreen" | "toast"; screens?: string[]; id?: string; icon?: string;
  dismissible?: boolean; chime?: boolean; title?: string; message?: string; image?: string; duration?: number;
  label?: string; description?: string; until?: string; since?: string; finished_for?: number;
}

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

/** Both the HTTP client and the in-browser demo implement this. Mirrors API.md. */
export interface Api {
  mode: "live" | "demo";
  subscribe(fn: (topic: Topic) => void): () => void;
  /** Live link to Moonlight: told now and on every change whether it's up. Only the real add-on has one. */
  connection?(fn: (up: boolean) => void): () => void;
  /** Try the live link again straight away instead of waiting for the next attempt. */
  reconnect?(): void;
  /** Notifications and timers shown on this device. */
  alerts(): Promise<AlertsNow>;
  createAlert(a: AlertIn): Promise<ScreenAlert>;
  /** Tapped away on this screen: gone everywhere. */
  dismissAlert(id: string): Promise<void>;
  settings(): Promise<Settings>;
  /** `new_pin` (4 digits) replaces the parent PIN; `pin` must be the current one. */
  updateSettings(patch: Partial<Omit<Settings, "screens" | "security" | "energy">> & { security?: SecuritySettingsPatch; energy?: EnergySettingsPatch; screens?: Partial<Record<Layout, Partial<ScreenSetup>>>; pin: string; new_pin?: string }): Promise<Settings>;
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
  /** Cookbook scans still being read or with recipes to check. */
  recipeBatches(): Promise<RecipeBatch[]>;
  /** Start reading a cookbook: page pictures in order (uploaded first). 409 when there's no Claude key. */
  scanCookbook(images: string[], cheaper?: boolean, book?: string): Promise<RecipeBatch>;
  retryBatch(id: string): Promise<RecipeBatch>;
  /** Stop reading and drop the recipes not checked yet. */
  deleteBatch(id: string): Promise<void>;
  saveAllDrafts(batchId: string): Promise<number>;
  /** Save a recipe found in a scan, as read or with the editor's changes. */
  saveDraft(id: string, r?: RecipeIn): Promise<Recipe>;
  dismissDraft(id: string): Promise<void>;
  /** The whole recipe box as a file for another app, pictures included. */
  exportRecipes(format: RecipeExportFormat): Promise<{ file: Blob; name: string }>;
  /** A recipe file from another app (any kind Moonlight reads, worked out from its contents), saved straight in. */
  importRecipes(file: Blob): Promise<RecipeImportResult>;
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
  /** Never show this photo again: takes it out of the Immich albums it's shown from. No PIN (the screen asks first). */
  hidePhoto(id: string): Promise<HideResult>;
  /** Newest first, a page at a time; limit 0 = just the count. */
  hiddenPhotos(limit: number, offset?: number): Promise<{ total: number; photos: HiddenPhoto[] }>;
  restorePhoto(id: string, pin: string): Promise<void>;
  // Nursery updates from Tapestry (see API.md "Nursery")
  nursery(): Promise<NurseryConfig>;
  /** Signs in to Tapestry first; 400 with a message when it doesn't accept the login. */
  saveNursery(c: NurseryIn): Promise<NurseryConfig>;
  disconnectNursery(pin: string): Promise<void>;
  syncNursery(): Promise<NurseryConfig>;
  nurseryUpdates(): Promise<NurseryUpdate[]>;
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
  /** What's playing and what's next. 409 no speaker. */
  mediaQueue(layout: Layout): Promise<MediaQueue>;
  mediaQueueAction(layout: Layout, action: QueueAction, key: string): Promise<void>;
  /** The speaker's library; no id = its top level. */
  mediaBrowse(layout: Layout, id?: string, type?: string): Promise<MediaBrowse>;
  /** Music Assistant speakers only (409 otherwise). */
  mediaSearch(layout: Layout, q: string): Promise<MediaItem[]>;
  mediaPlay(layout: Layout, item: { id: string; type: string }, enqueue: Enqueue): Promise<NowPlaying>;
  mediaRooms(layout: Layout): Promise<MediaRooms>;
  mediaRoomAction(layout: Layout, room: string, action: RoomAction, value?: number | boolean): Promise<MediaRooms>;
  musicAssistant(): Promise<MusicAssistantLink>;
  /** Checked against Music Assistant first: 400 token refused, 424 unreachable. url "" = the address it gives HA. */
  saveMusicAssistant(link: { url: string; token?: string; pin: string }): Promise<MusicAssistantLink>;
  removeMusicAssistant(pin: string): Promise<MusicAssistantLink>;
  // Security (see API.md "Security")
  security(): Promise<SecurityOverview>;
  securityAlerts(): Promise<SecurityAlert[]>;
  /** For Settings > Security; `refresh` asks Home Assistant again instead of using what it said a few minutes ago. */
  securityOptions(refresh?: boolean): Promise<SecurityOptions>;
  /** Pop a camera up on the screens for a few seconds, as if someone were there. */
  testSecurityAlert(camera: string, pin: string): Promise<void>;
  /** Arm or disarm the alarm; the code goes to Home Assistant as typed and isn't kept. 403 wrong code, 409 can't arm. */
  setAlarm(action: AlarmMode | "disarm", code?: string): Promise<{ ok: boolean; state: string }>;
  // Energy (see API.md "Energy")
  energy(): Promise<EnergyOverview>;
  /** For Settings > Energy; `refresh` asks Home Assistant again. */
  energyOptions(refresh?: boolean): Promise<EnergyOptions>;
  resetDemo?(): Promise<void>;
}
