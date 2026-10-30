# Moonlight API (v0.1)

All JSON. Times are household-local, naive ISO strings (`2026-10-12T09:00`), dates are `YYYY-MM-DD`.
Ids are strings. Every mutation broadcasts `{"type":"changed","topic":<topic>}` on the WebSocket `/api/ws`
(topics: `people`, `events`, `chores`, `points`, `rewards`, `lists`, `meals`, `recipes`, `settings`, `photos`, `displays`, `accounts`, `media`).
`media` is also sent whenever the configured speaker changes in Home Assistant (see Music).
Errors: `{"detail": "..."}` with 400 (bad input / not enough points), 401 (screen not paired, see Screens),
403 (wrong PIN), 404, 502 (a connected service such as iCloud or Immich can't be reached), and 500 for anything
unexpected (still `{"detail"}`: "Something went wrong (…). The add-on log has the details.").

The frontend has two interchangeable clients: HTTP (talks to this API) and Demo (in-browser
implementation of the same contract, used for the published preview). Keep them in step.

## Settings
- `GET /api/settings` -> `{family_name, week_start: "monday"|"sunday", temp_unit: "C"|"F", theme: "auto"|"light"|"dark", pin_set: bool, chore_approval: bool, timezone,
  screensaver_seconds: int, idle_minutes: {large, compact, phone}, photo_details: bool,
  media_players: {large, compact, phone}, screens: {large, compact, phone}, holidays: {country, subdiv},
  security: {alarm_entity?, cameras?, popup: {large, compact, phone, tv}}, energy: {entities?, battery_invert?, grid_invert?, hide?},
  voice: {pipeline, wake: {large, compact, phone}, replies}}`
  Keys are screen styles (`large` wall screen, `compact` small touch screen, `phone`; the old names `hallway` and
  `kitchen` are accepted as input). These per-style values are what the Home Assistant app shows, and what a paired
  screen uses until it has its own setup (see Screens).
  `screensaver_seconds` 3..3600 (default 10); `idle_minutes` per style, 0 = never
  (default `{large: 5, compact: 3, phone: 0}`). The screensaver's photos come from Immich (see Photo screensaver).
  `theme` (default `auto`) = light or dark for every screen and the Apple apps; `auto` follows each device's own setting.
  `photo_details` (default true) = show when and where each photo was taken, small at the top right.
  `timezone` = household IANA zone (default `Europe/London`); synced events are converted to it.
  `media_players` = the speaker (HA `media_player.*` entity id, `""` = none) each style shows; compact defaults to
  `MOONLIGHT_MEDIA_ENTITY` if set (development), the others to none.
  `screens` = per style `{start, sections}`: the sections its menu shows, in menu order, from `today, calendar,
  chores, rewards, meals, recipes, lists, nursery, security, energy` (Settings is always shown), and the one it opens on (default large
  `{start: "calendar", sections: all but today}`, compact `{start: "today", sections: all but nursery}`, phone the same). Upgrading to 0.6.0 adds `security` once to the large and compact menus, and 0.8.5 to the phone
  menus; upgrading to 0.8.0 adds `energy` once to every style's menu. `bar` (optional): up to 4 tabs from the sections
  plus `music` and `settings`, in order, kept in the bottom bar of a compact screen stood upright (the rest go under
  More); unset or null = the menu's first four.
  `weather_entity` = the HA weather entity the screens show (`""` = demo forecast; falls back to `MOONLIGHT_WEATHER_ENTITY`
  until one is saved).
  `holidays` = the public holidays that `skip_holidays` repeats leave out: ISO country code (`""` = none) and region
  code (`""` = whole country), e.g. `{country: "GB", subdiv: "ENG"}`, the default when the timezone is Europe/London
  (otherwise none). Dates come from the `holidays` package (see Public holidays).
- `PATCH /api/settings` body: any of `family_name, week_start, temp_unit, theme, chore_approval, timezone,
  screensaver_seconds, idle_minutes, photo_details, media_players, screens, weather_entity, holidays, security, energy, voice`, plus `pin` (required) -> settings.
  `voice` (merged, see Voice): `pipeline` an Assist pipeline id or `""` (Home Assistant's preferred one), `wake:
  {large?, compact?, phone?: bool}` (default all off), `replies`: `screen` (default) | `speaker` | `none`.
  `security` (merged, see Security): `alarm_entity` an `alarm_control_panel.*` id, `""` none, null automatic;
  `cameras: {"camera.x": {show?: bool, person?: "binary_sensor.y" | "" (never) | null (automatic)} | null}`;
  `popup: {large?, compact?, phone?, tv?: bool}` (default large and compact on; `tv` is the Apple TV app, off). Broadcasts `security` and `security_alert`.
  `energy` (merged, see Energy): `entities: {slot: entity id | "" (none) | null (automatic)}`, `battery_invert`,
  `grid_invert`: bool or null (automatic), `hide`: [parts (solar, battery, grid, home, car, heat_pump, plan) and temperatures-group slots left off the picture]. Broadcasts `energy`.
  An unknown `holidays` country or region is a 400; changing it broadcasts `events` and `chores` too.
  `screens` may be partial (`{compact: {start: "meals"}}`, merged per style); `sections` must not be empty and `start`
  must be one of them (hiding the start section moves it to the first one left). `media_players` may be partial
  (`{large: "media_player.kitchen"}`, merged; `""` or null clears one). `idle_minutes` may be partial (`{compact: 10}`,
  merged) or one number (applies to large and compact). `new_pin` (4 digits) replaces the parent PIN; with no PIN set
  yet, the first `pin` sent becomes it.
- `POST /api/pin/verify` `{pin}` -> `{ok: bool}`
- `GET /api/sample-data` -> `{remaining: int}`: rows of the demo family (seeded on first start) still present.
- `POST /api/sample-data/remove` `{pin}` -> `{removed: int}`: deletes the demo family's people, events, chores, stars,
  rewards, list items, recipes and meals; keeps anything added since (a demo list the family added items to stays)
  and leaves settings alone.

## People
- `GET /api/people` -> `[Person]` sorted by `sort`
  Person = `{id, name, initials, color, role: "adult"|"child", sort}`
- `POST /api/people` `{name, color, role?, sort?}` -> Person. `name` 1-40 chars (trimmed); `color` `#RRGGBB` (`#RGB` is
  expanded; stored upper-case); `role` defaults to `"child"`; `sort` defaults to after everyone else. No PIN.
- `PATCH /api/people/{id}` any of `{name, color, role, sort}` (same rules) -> Person. No PIN. Reorder by sending each
  person's new `sort`.
- `DELETE /api/people/{id}` `{pin}` -> `{ok: true}`; 403 wrong PIN, 404 unknown. Deletes their chores (and completions),
  their whole points ledger and rewards with their `person_id`; removes them from events' and calendars' `person_ids`
  (events stay, possibly with no people) and clears `person_id` on list items. Broadcasts `people, events, chores,
  points, rewards, lists, accounts`.
- A new install with demo data off has no people: every endpoint works with `[]`, and events may have `person_ids: []`.

## Events
- `GET /api/events?start=YYYY-MM-DD&end=YYYY-MM-DD` (end exclusive) -> `[Occurrence]` sorted by start,
  recurring events expanded on the server.
  Occurrence = Event fields + `{occurrence_id: "<id>@<YYYY-MM-DD>", recurring: bool}` with `start`/`end`
  shifted to that occurrence.
  Event = `{id, title, person_ids: [id], start, end, all_day, location, notes, repeat}`
  `repeat` = null | `{freq: "daily"|"weekly"|"monthly", interval: int>=1, byday: ["MO",..] (weekly only, optional), until: date|null,
  skip_holidays?: bool}`. `skip_holidays` leaves out occurrences on public holidays (Settings `holidays`); synced to
  iCloud/CalDAV as EXDATEs for the next 3 years plus an `X-MOONLIGHT-SKIP-HOLIDAYS` marker, so other apps skip them too.
  All-day events: `start` = `YYYY-MM-DDT00:00`, `end` = next day `T00:00` (exclusive), may span days.
  An occurrence is included if it overlaps [start, end).
- `POST /api/events` Event without id -> Event
- `PATCH /api/events/{id}` partial -> Event (edits the whole series)
- `DELETE /api/events/{id}` -> `{ok: true}`
- `POST /api/events/scan` `{image: id from POST /api/images, today?: YYYY-MM-DD}` -> draft event (not saved):
  `{title, start, end, all_day, location, notes, person_ids, attachments: [{id, url}], found_date: bool}`. Claude reads
  a photo of an invitation or flier (one Anthropic request, the key in Settings > Recipes); 409 without a key, 422
  when no event is found. A missing date gives today with `found_date: false`, a missing time all day, a missing end
  two hours on. `person_ids` are the family named on it.

Events also carry `calendar_id` (null = local-only), `source` (null | `"icloud"` | `"caldav"` | `"ics"`),
`custom_repeat` (bool), `color` (the calendar's colour, null for local events), `read_only` (bool: in a
read-only calendar, edits get 403) and `busy` (null, or on calendars shown as busy blocks one of
`"busy"|"tentative"|"away"|"elsewhere"`; `"free"` events of such calendars are left out). See Calendar sync
and Calendar links.
`attachments` = `[{id, url}]`: pictures kept with the event (a scanned invite), stored on Moonlight only, also for
synced events. Send `attachments` as a list of image ids (or the `{id, url}` objects) to set them, at most 10.

## Calendar sync (iCloud / CalDAV)
iCloud is the master. Moonlight caches events locally and polls every account (default every 120 s,
env `MOONLIGHT_SYNC_SECONDS`): one PROPFIND on the calendar home gives every calendar's ctag; only
changed calendars are listed and only changed events downloaded. Errors back off exponentially; an
account whose login is rejected gets `status: "auth_failed"` and is not retried until it is reconnected.

Account = `{id, kind: "icloud"|"caldav"|"ics", label, username, server_url, status: "ok"|"auth_failed"|"error",
last_error: str|null, last_sync: datetime|null, calendar_count}`. The password is never returned.
Calendar = `{id, account_id, name, source_name, color, person_ids: [id], visible: bool, read_only: bool,
busy_blocks: bool, busy_blocks_auto: bool, busy_blocks_set: bool}` (busy blocks: see Calendar links).
`name` is the household's own name for it when one was set, else `source_name` (the server's name).
- `GET /api/accounts` -> `[Account]`
- `POST /api/accounts` `{kind, username, password, server_url (caldav only), label?, pin}` -> Account.
  Logs in and discovers event calendars first: 400 if the login is rejected, 502 if the server can't be
  reached, 403 wrong PIN. iCloud uses `https://caldav.icloud.com/` with an app-specific password.
  New calendars are mapped to people by name ("Alex" -> Alex; "Family"/"Home" -> everyone).
- `PATCH /api/accounts/{id}` `{pin, password?, username?, label?}` -> Account. New credentials are
  verified first; this is how an `auth_failed` account is reconnected.
- `DELETE /api/accounts/{id}` `{pin}` -> `{ok: true}`. Forgets the account and its cached events (nothing
  is deleted in iCloud).
- `POST /api/accounts/{id}/sync` -> Account (after syncing now; check `status`).
- `GET /api/calendars` -> `[Calendar]`; `PATCH /api/calendars/{id}` `{name?, person_ids?, visible?, color?,
  busy_blocks?: true|false|null}` -> Calendar (`null` = automatic; `name` "" or `null` = the server's name
  again). The name survives syncs.
  Hidden calendars keep syncing but their events are left out of `GET /api/events`.
- `GET /api/sync/status` -> `{running, interval_seconds, needs_reconnect: bool,
  accounts: [{id, label, kind, status, last_sync, last_error}]}`

Synced events:
- People: the event's own list if it was saved with people different from its calendar's mapping
  (stored in the ICS as `X-MOONLIGHT-PEOPLE`), else the calendar's `person_ids`.
- Recurrence: simple RRULEs (DAILY/WEEKLY/MONTHLY with INTERVAL, plain BYDAY, UNTIL, in the household
  timezone) appear as `repeat`. Anything else (COUNT, EXDATE, moved/edited occurrences, BYSETPOS,
  "2nd Tuesday", other timezones) has `repeat: null, custom_repeat: true` and is expanded on the server
  from the original ICS; editing such an event keeps its rule unless `repeat` is sent.
- `POST /api/events` with `calendar_id` creates it in that calendar. Without `calendar_id` it goes to
  the first visible, writable calendar mapped to the first of `person_ids` (that person's own
  calendar before shared ones like Family), else stays local.
  `calendar_id: null` forces local-only. `PATCH` with `calendar_id` moves the event.
- Writes go to the server first (PUT with `If-Match` / `If-None-Match: *`, DELETE with `If-Match`) and are
  stored only once accepted. If the event changed on another device: 409 with a clear `detail`, and the
  latest version is already re-fetched. Read-only calendar: 400 (target) / 403 (edit). Server rejected
  the login or is unreachable: 502 (the account's `status` says which).

## Calendar links (published ICS, read-only)
An account of `kind: "ics"` is one read-only calendar from a published link (`webcal://` is fetched as
`https://`). The full URL is a secret: it is never returned; `server_url` is a masked form
(`outlook.office365.com/…/calendar.ics`) and `username` is `""`. Polled every 900 s
(`MOONLIGHT_FEED_SECONDS`) with `If-None-Match` / `If-Modified-Since`; a 304 or an identical body changes
nothing. Errors (unreachable, 401/403/404, not a calendar) set `status: "error"` with a `last_error`
message and back off (5, 10, 20... min, at most an hour); cached events stay meanwhile. The feed is cached
per UID (master + RECURRENCE-ID overrides), so a change replaces just the events that changed; timezones
(including Outlook's Windows names like "GMT Standard Time") and recurrence go through the same path as
CalDAV events. Only events touching [today - 60 days, today + 1 year] are kept; cancelled events are
dropped.
- `POST /api/accounts/feed-preview` `{url}` -> `{event_count, name, busy_only, masked_url}` (nothing saved;
  400 bad URL, 502 fetch/parse error with a `detail` that never contains the URL).
- `POST /api/accounts` `{kind: "ics", url, label?, person_ids?, color?, pin}` -> Account. Fetched first
  (same errors); `label` defaults to the feed's X-WR-CALNAME, `color` to the first person's colour.
  400 if the same link is already added.
- `PATCH /api/accounts/{id}` `{pin, url?, label?}` -> Account: a new link is fetched and replaces the
  events; `label` also renames the calendar.
- `POST /api/accounts/{id}/sync` `{force?: bool}` -> Account (`force` skips the conditional GET).
- Free/busy: every event gets a status from `X-MICROSOFT-CDO-BUSYSTATUS`, else a placeholder summary
  ("Busy", "Tentative", "Free", "Away"/"Out of Office", "Working elsewhere"), else `STATUS:TENTATIVE`,
  `TRANSP:TRANSPARENT` (= free), else busy. `busy_blocks_auto` is true when every summary is such a
  placeholder; `busy_blocks` = the household's choice (`busy_blocks_set`) or the automatic value. On such
  calendars events carry `busy` and screens show "Alex – busy" blocks; free ones are not returned.

## Home Assistant calendars (read-only)
An account of `kind: "ha"` is one read-only calendar from a Home Assistant calendar entity (bin collections,
Workday, energy saving sessions). `username` and `server_url` are the entity id. Events come from HA's
`GET /api/calendars/{entity}` (already expanded into occurrences) over the same connection as the weather
(Supervisor token in the add-on, or `MOONLIGHT_HA_URL` + `MOONLIGHT_HA_TOKEN`), are stored like a calendar
link's (same window, only changed events rewritten, `source: "ha"`) and polled every `MOONLIGHT_FEED_SECONDS`.
Errors set `status: "error"` and keep the cached events.
- `GET /api/ha/calendars` -> `[{entity_id, name, added: bool}]`, sorted by name. Moonlight's own entities
  (`calendar.moonlight_*`) are left out. 409 when Moonlight isn't connected to Home Assistant, 502 when HA errors.
- `POST /api/accounts` `{kind: "ha", entity_id, label?, person_ids?, color?, pin}` -> Account. `label` defaults
  to the entity's name. 400 not a `calendar.` entity, unknown to HA, or already added; 403 wrong PIN.
- `PATCH /api/accounts/{id}` `{pin, label}` renames it (and its calendar); `DELETE` and `/sync` work as for links.

## Chores
Chore = `{id, title, emoji, person_id, points, time_of_day: "morning"|"afternoon"|"evening"|"anytime", schedule, sort}`
`schedule` = `{type: "daily"}` | `{type: "weekly", days: ["MO",..]}` | `{type: "once", date}`; daily and weekly may add
`skip_holidays: true` (not due on public holidays, which also don't break a streak).
- `GET /api/chores/all` -> `[Chore]`
- `GET /api/chores?date=YYYY-MM-DD` -> `[ChoreDay]`: chores due that date,
  ChoreDay = Chore + `{date, completed: bool, completed_at: str|null, streak: int}`.
  `streak` = number of consecutive due dates, walking back from `date` (counting `date` only if completed;
  if `date` is not completed, start at the previous due date), that were completed. Look back max 60 days.
- `POST /api/chores` / `PATCH /api/chores/{id}` (any of title, emoji, person_id, points, time_of_day, schedule, sort) / `DELETE /api/chores/{id}` (also drops its completions)
- `POST /api/chores/{id}/complete` `{date}` -> `{completed: true, balance}`; idempotent; adds ledger `+points`
  with reason `"<emoji> <title>"`.
- `DELETE /api/chores/{id}/complete?date=` -> `{completed: false, balance}`; adds ledger `-points`, reason `"Undo: <title>"`.

## Points and rewards
- `GET /api/points` -> `[{person_id, balance}]` for every person
- `GET /api/points/{person_id}/ledger` -> `[{id, person_id, change, reason, at}]` newest first, max 100
- `POST /api/points/adjust` `{person_id, change, reason, pin}` -> `{balance}`
Reward = `{id, title, emoji, cost, person_id: id|null (null = any child)}`
- `GET /api/rewards`; `POST /api/rewards`; `PATCH /api/rewards/{id}` (any of title, emoji, cost, person_id);
  `DELETE /api/rewards/{id}`
- `POST /api/rewards/{id}/redeem` `{person_id, pin}` -> `{balance}`; 403 bad PIN, 400 if balance < cost;
  ledger `-cost`, reason `"<emoji> <title>"`.

## Lists
List = `{id, name, emoji, color, kind: "grocery"|"todo", sort, open_count, done_count}`
Item = `{id, list_id, title, done, person_id|null, due: date|null, created_at, sort}`
- `GET /api/lists`; `POST /api/lists` `{name, emoji, color, kind}`; `PATCH /api/lists/{id}` (any of name, emoji,
  color, kind, sort) -> List; `DELETE /api/lists/{id}` (and its items)
- `GET /api/lists/{id}/items` -> open items first (by sort), then done items (by done time desc)
- `POST /api/lists/{id}/items` `{title, person_id?, due?}` -> Item
- `PATCH /api/items/{id}` `{title?, done?, person_id?, due?}`; `DELETE /api/items/{id}`
- `POST /api/lists/{id}/clear-done`

## Meals
Meal = `{id, date, slot: "breakfast"|"lunch"|"dinner"|"snack", title, notes, recipe_id|null}`
- `GET /api/meals?start&end` (end exclusive); `POST /api/meals`; `PATCH /api/meals/{id}`; `DELETE /api/meals/{id}`

## Recipes
Recipe = `{id, title, emoji, description, photo: image id|null, photo_url|null, rating: 0..5 (0 = not rated),
favourite: bool, servings: int|null, prep_minutes|null, cook_minutes|null, minutes|null (total: as saved, else prep +
cook), ingredients: [Ingredient], steps: [Step], tags: [str], notes, url|null (where it came from), cooked_count,
last_cooked: date|null, created_at, updated_at, course: str|null, book: str ("" when none), book_page: int|null}`.
  `course` is one of `breakfast, starter, light, main, side, dessert, baking, snack, drink, extra` (Breakfast &
  brunch, Starters, Light bites, Main meals, Sides, Desserts, Baking, Snacks, Drinks, Sauces & extras), which the
  screens arrange the recipe box by; `book` and `book_page` are the cookbook it came from. Claude fills in the course
  and the printed page number when it reads a recipe; recipes saved before courses got a first guess from their tags.
- Ingredient = `{text, quantity: number|null, quantity_max: number|null (a range "3-4"), unit, name, note, heading: bool,
  metric: {quantity, quantity_max, unit: "g"|"ml"}|null}`, read from the saved line `text`, which is never changed.
  `unit` is a short name (`g, kg, ml, l, tsp, tbsp, cup, fl oz, oz, lb, pint, quart, gallon, stick, clove, tin, can,
  pinch, ...`; `""` for "2 eggs"). `metric` is set for non-metric measures only (cups as US 240 ml, pints as British
  568 ml, oz, lb, fl oz, sticks of butter); teaspoons and tablespoons are left alone. Lines like "For the sauce:" are
  `heading: true`. Screens scale `quantity`, `quantity_max` and `metric` by servings and rebuild the line; when
  `quantity` is null they show `text` as is.
- Step = `{text, minutes: number|null, photo|null, photo_url|null, timers: [{seconds, label}], metric_text: str|null,
  uses: [int]}`. `uses` are the ingredients the step mentions (indexes into `ingredients`, in the order the step
  mentions them), so screens can show their scaled amounts with the step; only lines with an amount count, and a
  word shared by two ingredients ("red onion", "spring onions") only counts when the step names the whole one.
  `timers` are the times the text mentions ("simmer for 10-15 minutes" -> 600, the shorter end) plus `minutes` when
  set; `metric_text` is `text` with metric figures added in brackets ("350°F (175°C)", "9-inch (23 cm)",
  "1 cup (240 ml)"), null when nothing needed converting.
- `GET /api/recipes` (by title); `GET /api/recipes/{id}`
- `POST /api/recipes` `{title, emoji?, description?, photo?, rating?, favourite?, servings? 1..100, prep_minutes?,
  cook_minutes?, minutes?, ingredients?: [str | {text}], steps?: [str | {text, minutes?, photo?}], tags?, notes?,
  url?, course?, book?, book_page?}` -> Recipe; `PATCH /api/recipes/{id}` (any of those); `DELETE /api/recipes/{id}` -> `{ok: true}`. Meals planned
  from a deleted recipe keep their title and get `recipe_id: null`. Tags are stored lower-case, without repeats.
- `POST /api/recipes/{id}/to-list` `{list_id, items?: [str]}` -> `{added}`: the chosen lines (the screens send them
  scaled, as shown), else every ingredient that isn't a heading.
- `POST /api/recipes/{id}/cooked` `{date?}` -> Recipe: made it (counts up; `last_cooked` keeps the latest date).
- `POST /api/recipes/preview` (a recipe body) -> Recipe with `id: null`, nothing saved: how the editor's lines read.
- `POST /api/recipes/import` -> an unsaved draft Recipe (`id: null`) for the editor, from one of:
  - `{url}`: a recipe web page's schema.org data (title, picture, servings, times, ingredients, steps and their
    pictures, tags). Pages without it are read by Claude when a key is set, else 422 asking to paste the text.
  - `{text, use_reader?}`: typed, pasted, or read from a photo on the phone (the iPhone app reads photos on the device
    with Apple's Vision). Read with built-in rules (title, Ingredients/Method headings, numbered steps, serves, prep
    and cook times), or by Claude with `use_reader: true` when a key is set.
  - `{images: [image ids]}` (up to 6 pages of one recipe): read by Claude; 409 when no key is set.
  422 with a `detail` to show when nothing could be read. Pictures on the web page are saved and set as `photo`.
- Other recipe apps: `GET /api/recipes/export?format=mela|paprika|schema` -> the whole recipe box as a file to
  download, pictures included: Mela `.melarecipes` (a zip of `.melarecipe` JSON, ingredient headings as `# ...`),
  Paprika `.paprikarecipes` (a zip of gzipped JSON) or a JSON list of schema.org Recipe objects (pictures as data URLs).
  `POST /api/recipes/collection` with a recipe file as the raw request body (500 MB at most) saves every recipe in it,
  skipping titles already in the box -> `{added, skipped: [titles], failed: [titles]}`. The kind of file is worked
  out from its contents: a Mela or Paprika collection or single recipe, schema.org JSON (a list, `@graph` or one
  Recipe), a zip of any of those, or a saved recipe web page; 422 when there are no recipes in it.
- Claude for reading photos (Settings › Recipes): `GET /api/recipes-reader` -> `{configured, model, key_hint}`;
  `PUT /api/recipes-reader` `{pin, api_key?, model?}` (an Anthropic API key, `sk-ant-...`, never returned; model
  defaults to `claude-opus-5-5`); `DELETE /api/recipes-reader` `{pin}`.
- Scanning a whole cookbook: each page photo is read by Claude on its own, four at a time, in the background (and
  after a restart) until every page is done; pages Anthropic is too busy for are tried 3 times. A recipe that carries
  on from the page before is joined to it, so a recipe is offered once the page after it is read (or it's the last).
  Batch = `{id, pages, read, reading: bool, cheaper: bool, book, failed: [{page, error}], saved, drafts: [{id, pages: [int] (from 1),
  recipe: Recipe (id null)}]}`. Every change sends `recipes`.
  - `GET /api/recipes-batches` -> [Batch]; `POST /api/recipes-batches` `{images: [image ids], in page order, up to 200,
    cheaper?: bool, book?: the cookbook's name, given to every recipe found, isbn?: a book from `GET /api/cookbooks/{isbn}`,
    whose title is used when `book` is empty (a different `book` renames it and its recipes)}` -> Batch (409 when no key is set). `cheaper` sends the pages as one Anthropic Message Batch: half
    the price, read when Anthropic has room (usually within the hour, at most a day); Moonlight checks on it every two
    minutes, cancels it when the scan is cleared, and failed pages tried again go as a new batch.
  - `POST /api/recipes-batches/{id}/retry` -> Batch: read the failed pages again.
  - Cookbook = `{isbn (ISBN-13), title, authors, publisher, year, cover (image id), cover_url, recipes: count}`.
    `GET /api/cookbooks` -> [Cookbook], A to Z. `GET /api/cookbooks/{isbn}` (10 or 13 digits, from the barcode on the
    back) -> Cookbook: one found before, or looked up in Open Library, then Google Books, and kept with its cover
    (400 when it isn't an ISBN, 404 when neither knows the book).
  - `POST /api/recipe-drafts/{id}/save` (optionally a full recipe body, as checked in the editor) -> Recipe;
    `DELETE /api/recipe-drafts/{id}`: don't keep it. `POST /api/recipes-batches/{id}/save-all` -> `{saved}`.
  - `DELETE /api/recipes-batches/{id}`: stop reading and drop the recipes not saved yet. A batch goes by itself once
    every page is read and every recipe found is saved or dropped.

## Pictures
- `POST /api/images` with the picture as the raw request body (JPEG, PNG, WebP or GIF, 10 MB at most; screens shrink
  photos first) -> `{id, url}`. Use the id as a recipe's or step's `photo`. Pictures nothing uses are removed after a day.
- `GET /api/images/{id}` -> the picture (cached for good: ids are never reused).

## Weather
- `GET /api/weather` -> `{source: "homeassistant"|"demo", entity: str|null, name?: str (the entity's friendly name), unit: "C"|"F", current: {temp, condition}, daily: [{date, high, low, condition, rain}]}`
  up to 10 days from today. Temperatures are whole numbers in the settings' `temp_unit`. `rain` is the day's chance
  of rain or snow in whole percent (HA's `precipitation_probability`), or null when the entity doesn't give one.
  `condition` uses HA's names: `sunny, partlycloudy, cloudy, rainy, pouring, snowy, fog, windy, lightning-rainy, clear-night`
  (HA's `snowy-rainy`/`hail` -> `snowy`, `windy-variant` -> `windy`, `exceptional` -> `cloudy`, `lightning` -> `lightning-rainy`).
  With Settings `weather_entity` set (or env `MOONLIGHT_WEATHER_ENTITY` before one is saved), read from that HA weather entity
  (state + `weather.get_forecasts` daily) via the Supervisor API, cached 10 minutes; if HA can't be reached the
  last good forecast is kept for up to an hour, then it falls back to the deterministic demo forecast (`source: "demo"`).
- `GET /api/weather/entities` -> `[{entity_id, name, available, condition|null, temperature|null, unit: "C"|"F",
  attribution|null}]`, HA's `weather.*` entities (available first, then by name) for Settings > Weather.
  409 when Moonlight has no Home Assistant connection, 502 when HA can't be reached.

## Public holidays
- `GET /api/holidays?start=YYYY-MM-DD&end=YYYY-MM-DD[&country=GB&subdiv=SCT]` (end inclusive, at most ~2 years) ->
  `[{date, name}]` sorted by date, for Settings `holidays` or the `country`/`subdiv` given (a preview before saving).
- `GET /api/holidays/countries` -> `[{code, name, subdivs: [{code, name}]}]` sorted by name, for the Settings picker.

## Music (now playing on a Home Assistant speaker)
The speaker is a Home Assistant `media_player` entity, typically one created by the Music Assistant integration (e.g. a
Sonos speaker). Screens only name their `layout` (`large|compact|phone`, default `compact`); the backend maps it to
the paired screen's own speaker (its setup), else the style's entity in `settings.media_players`, so a screen can't
read or control any other entity. Without Home Assistant
(`SUPERVISOR_TOKEN`, or `MOONLIGHT_HA_URL` + `MOONLIGHT_HA_TOKEN`) the commands return 409.
- `GET /api/media/now-playing?layout=compact` -> NowPlaying:
  `{layout, configured: bool, entity: str|null, name, state, show: bool, title, artist, album, duration, position,
  position_updated_at, volume: 0..1|null, muted: bool|null, shuffle: bool|null, repeat: "off"|"all"|"one"|null,
  source, app, music_assistant: bool, has_art: bool, art_url: str|null, supports: {play_pause, previous, next, volume,
  mute, shuffle, repeat, seek, grouping}, via: str|null, reachable: bool, error: str|null, server_time}`.
  `state` is HA's (`playing`, `paused`, `idle`, `off`, `standby`, `buffering`, `unavailable`, ...). `show` = worth
  showing: playing/paused/buffering, or idle/on with a track loaded. `duration`/`position` are seconds; the position
  was `position` at `position_updated_at` (HA's clock), so clients tick it locally using `server_time`.
  `supports` comes from the entity's `supported_features`. `music_assistant` = the entity has Music Assistant's
  `mass_player_type` attribute (or `app_id: music_assistant`). If HA is unreachable the last state is kept for 90 s,
  then `state: "unavailable", reachable: false`.
  `via`: when the speaker is a Music Assistant player that is idle while the Home Assistant entity it hands over to
  (its `active_queue`, e.g. the Sonos integration's own entity when someone plays from the Sonos app) is playing,
  NowPlaying describes and controls that entity instead and `via` is its entity id; `entity`/`name` stay the speaker's.
- `GET /api/media/art?layout=compact&v=<hash>` -> the album art image (or 404). Moonlight fetches HA's
  `entity_picture_local`/`entity_picture` (a `/api/media_player_proxy/...` path, with its own HA token, or a public
  URL fetched without any token) and caches the last 12 images. `v` is a hash of the picture URL; only the layout's
  current (or recently cached) picture is served, and no HA token ever reaches the screen. Cache-Control: immutable.
- `POST /api/media/command` `{layout, action, value?}` -> NowPlaying. Actions -> HA `media_player` services:
  `play_pause` (media_play_pause), `play`, `pause`, `next` (media_next_track), `previous` (media_previous_track),
  `volume_set` (value 0..1 -> volume_level), `volume_mute` (value bool -> is_volume_muted), `shuffle_set` (bool),
  `repeat_set` (`off|all|one`). 400 bad action/value, 409 no speaker for that layout, 502 HA unreachable or refused.
- `GET /api/media/players` -> `[{entity_id, name, state, music_assistant}]` every `media_player` in HA (Music
  Assistant ones first), for the Settings picker. 502 if HA can't be reached.
- `GET /api/media/favourites?layout=compact` -> `[{uri, name, media_type}]` Music Assistant favourite playlists (10)
  and radio stations (6), via `music_assistant.get_library` (favorite: true) on the first loaded Music Assistant
  config entry; cached 15 minutes. Empty for non-Music Assistant players or on any error.
- `POST /api/media/play` `{layout, uri}` -> NowPlaying. Plays one of those favourites with
  `music_assistant.play_media` (enqueue `replace`); 404 if `uri` isn't a current favourite.
  `{layout, id, type, enqueue}` plays anything from browse or search: `enqueue` is `replace` (play now, default),
  `next` (after the current track) or `add` (end of the queue). Music Assistant speakers use
  `music_assistant.play_media`; others `media_player.play_media` (enqueue only if the player supports it).

### Music tab (queue, library, rooms)
All of these take the screen's `layout` and act only on its speaker (or the entity it hands over to, see `via`).
Pictures in their answers are `/api/media/thumb?k=<key>` links: the add-on fetches them (with HA's token for HA
paths, Music Assistant's token for its image proxy) so no address or token reaches the screen.
- `GET /api/media/queue?layout=` -> `{source: "music_assistant"|"sonos"|null, full: bool, total, current: int|null,
  items: [{key, index, title, artist, album, duration, thumb, current}], can_jump, can_remove, can_move}`. Sources:
  Music Assistant's own API when Moonlight has a Music Assistant token (Settings › Music; up to 80 tracks from the
  current one), otherwise Home Assistant's `music_assistant.get_queue` (current and next track only, `full: false`),
  or for a Sonos integration entity `sonos.get_queue` (the whole queue).
- `POST /api/media/queue` `{layout, action: play|remove|next, key}` -> `{ok}`. Jump to a track, remove it, or move it
  to play next. 409 if the queue's source can't (see the `can_*` flags).
- `GET /api/media/browse?layout=&id=&type=` -> `{id, type, title, kind, can_play, can_expand, thumb, items: [same
  shape plus subtitle], more}`. Home Assistant's media browser for the speaker (`media_player/browse_media`); no `id`
  is the top level. Local media sources and app shortcuts are left out; at most 500 items (`more` = how many weren't
  sent).
- `GET /api/media/search?layout=&q=` -> `[item]` artists, albums, playlists, tracks, podcasts and radio from
  `music_assistant.search`. 409 for a speaker that isn't a Music Assistant player.
- `GET /api/media/thumb?k=` -> the picture (404 for an unknown key).
- `GET /api/media/rooms?layout=` -> `{entity, can_group, rooms: [{entity_id, name, state, this, grouped, volume,
  muted, playing, can_volume}]}`: this speaker first, then the speakers it can be grouped with (they support
  grouping, are available, and are the same kind: Music Assistant players with Music Assistant players, Sonos with
  Sonos).
- `POST /api/media/rooms` `{layout, room, action: join|unjoin|volume|mute, value?}` -> the rooms, as GET. `join`
  adds `room` to this speaker's group (`media_player.join`), `unjoin` takes it out, `volume` (0..1) and `mute`
  (bool) set that room. 404 if `room` isn't one of the listed rooms.

### Music Assistant connection (Settings › Music)
- `GET /api/media/music-assistant` -> `{url, detected_url, token_set}`. The token is never returned.
- `PUT /api/media/music-assistant` `{pin, url?, token?}` -> the same. `url` empty = the address Music Assistant gives
  Home Assistant (learnt from its picture links); token kept if left out. Checked first by asking Music Assistant for
  its players over its WebSocket API: 400 if the token is refused, 424 if Music Assistant can't be reached.
- `DELETE /api/media/music-assistant` `{pin}` -> forget the connection.

Live updates: the backend keeps one WebSocket to HA (`ws://supervisor/core/websocket`, or `MOONLIGHT_HA_WS_URL`)
with `subscribe_trigger` (state trigger on the configured entities). Every change broadcasts the `media` topic.
While that socket is down (HA restarting) it polls the entities' states every 5 s and retries with back-off
(5, 10, 20, 30, 60 s).

## Security (alarm, sensors and cameras from Home Assistant)
Read-only. The alarm is an `alarm_control_panel` entity: the Alarmo one by default (its state has `arm_mode` and
`open_sensors`), else the first panel. Sensors are the enabled ones set up in Alarmo, read with Alarmo's
`alarmo/sensors` WebSocket command (no Alarmo = no sensor list). Cameras are HA `camera` entities: UniFi Protect ones
are shown by default, one per camera (its best channel); each camera's person sensor is the "Person detected"
`binary_sensor` on the same device (entity registry `list_for_display`), else one named after the camera. What HA
offers is read again every 5 minutes (or with `refresh`). Screens only ever name a shown camera.
- `GET /api/security` (the wall screens and the iPhone and iPad app) -> `{configured, reachable, error, sensors_source: "alarmo"|"none",
  alarm: {entity_id, name, state, label, armed, alarmo, available, changed_by, last_changed, next_state, delay,
  open_sensors: [names], modes: ["away"|"home"|"night"|"vacation"], code_arm_required} | null,
  sensors: [{entity_id, name, group: "doors"|"windows"|"motion"|"environment"|"other", state, label ("Open",
  "Closed", "Motion", "Clear", "Detected", "Unavailable"...), active, available, armed (guarded in the current mode),
  last_changed}], cameras: [{entity_id, name, available, person: bool, snapshot_url, live_url}], alerts: [Alert]}`.
  `configured: false` without Home Assistant. Sensor names drop a device prefix most of them share ("Alarm Panel").
- `GET /api/security/alerts` -> `[{camera, name, since, test, live_url, snapshot_url, video_url, video_hd_url}]`: shown cameras whose person
  sensor is on now (or a test). Screens pop these up.
- `GET /api/security/options?refresh=false` -> `{alarm_entity, panels: [{entity_id, name, alarmo, state}],
  cameras: [{entity_id, name, show, person, auto_person, default_person, available}], person_sensors: [{entity_id,
  name}], sensors_source, sensor_count, popup}` for Settings > Security. 409 without HA, 502 HA unreachable.
- `GET /api/security/cameras/{entity}/snapshot?width=` -> a JPEG from HA's `/api/camera_proxy` (resized by HA to
  `width` and the camera's aspect; 160..1920). 404 for a camera that isn't shown.
- `GET /api/security/cameras/{entity}/live?width=` -> `multipart/x-mixed-replace` MJPEG for an `<img>`, made from
  snapshots about twice a second (the Supervisor proxy buffers whole answers, so HA's own MJPEG stream can't pass
  through). Screens watching the same camera share snapshots; a feed ends after 15 minutes; at most 8 at once (503).
  It's the fallback when a camera has no video.
- `GET /api/security/cameras/{entity}/hls/master_playlist.m3u8` (and the playlists and segments it names) -> HA's own
  HLS video of the camera, passed through so HA's stream token stays on the add-on. Cameras and alerts carry it as
  `video_url` (null when the camera can't stream). Uses the camera's medium-resolution channel when it's enabled in
  HA (lighter for the screens); a stale token is renewed once. The stream is started as soon as a person is seen.
- `GET /api/security/cameras/{entity}/hd/hls/master_playlist.m3u8` -> the same, always from the camera's own
  full-resolution stream: `video_hd_url` (equal to `video_url` when HA has no lighter channel). Large screens and the
  Apple TV play this one.
- `POST /api/security/alarm` `{action: "disarm"|"away"|"home"|"night"|"vacation", code?}` -> `{ok, state}`: calls
  `alarm_control_panel.alarm_disarm` / `alarm_arm_<mode>` with the code (never stored) and waits up to 4 s for the panel
  to change. A code is required to disarm (400 without). 403 when the code isn't accepted (Alarmo ignores a wrong
  code, so an unchanged state counts as refused); 5 refusals per 5 minutes per address, then 429. 409 when arming
  doesn't take (names the open sensors). 404 with no alarm chosen.
- `POST /api/security/test-alert` `{camera, pin}` -> `{ok, seconds: 20}`: pops the camera up on the screens as if a
  person were there.

Live updates: the panel, the sensors and the shown cameras' person sensors are followed over HA's WebSocket like the
speakers (polling `/api/states` while it's down). Any change broadcasts `security`; a change in which cameras have a
person broadcasts `security_alert`.

## Energy (solar, battery, grid, car and heat pump from Home Assistant)
Read-only; the screens draw it as a house with the power flowing between its parts. Each value is a slot filled by
one HA entity: `solar_power, solar_today, solar_forecast, solar_forecast_tomorrow, battery_soc, battery_power,
grid_power, grid_import_today, grid_export_today, home_power, home_today, car_plug, car_status, car_power, car_soc,
car_range, car_session, car_limit, car_ready, heat_pump_mode, heat_pump_power, heat_pump_today, heat_pump_flow, heat_pump_return,
heat_pump_flow_rate, heat_pump_details, inside_temp, outdoor_temp, heat_pump_tank, plan_status, plan_cost_today,
plan_rate_now, plan_rate_export, plan_battery_hours, plan_charge_start, plan_charge_end, plan_cheap_start,
plan_cheap_end, cheap_off_peak, cheap_dispatches`. `cheap_off_peak` and `cheap_dispatches` are the Octopus Energy
integration's off-peak and intelligent dispatching binary sensors (the latter found by its `planned_dispatches`
attribute); `car_limit` prefers the car's own (AC) charge limit, then Intelligent Octopus's charge target; `car_ready`
prefers Intelligent Octopus's target time. `heat_pump_details` is one entity carrying a controller's readings as attributes (ESPAltherma's
flow rate, leaving and inlet water, tank, indoor, outdoor, 3-way valve, defrost); the `plan_*` slots are Predbat's
`predbat.*` entities, found by id. A slot is automatic
until picked: HA's Energy dashboard first (`energy/get_prefs`: the solar, battery and grid `stat_rate` power sensors
with HA's signs, and devices named car or heat pump), then entity ids and names, preferring the same device as what
was found (an inverter's `..._soc` beside its `..._battery_power`; a heat pump's power from the meter its "Heat Pump"
energy sensor is named after). `heat_pump_today` may add two sensors up (heating and hot water). Read again every 5
minutes (or with `refresh`).
- `GET /api/energy` -> `{configured, reachable, error, updated, solar: {power, today, forecast_today,
  forecast_tomorrow, starts, ends} | null,
  battery: {soc, power (+ discharging, - charging), state: "charging"|"discharging"|"idle"|null} | null,
  grid: {power (+ importing, - exporting), state: "importing"|"exporting"|"idle"|null, import_today, export_today} | null,
  home: {power, today, computed} | null, car: {plugged_in, charging, status, power, soc, range, range_unit, session,
  limit (%), ready (ISO: a time of day becomes its next occurrence)} | null,
  heat_pump: {running, doing ("Heating the house", "Heating hot water", "Defrosting", "Cooling", "Running", "Idle"),
  power, today, flow_temp, heat, cop, cop_today: {heating, hot_water, overall} | null} | null,
  temperatures: {inside, outside, tank, heating_target, tank_target, inside_humidity, outside_humidity, hidden} | null, plan: {status, cost_today, cost_unit, rate_now, rate_export, rate_unit,
  battery_hours, charge: {start, end, rate} | null, cheap: {start, end, rate} | null} | null, tariff: {cheap_now,
  cheap_until, next: {start, end} | null, bonus: [{start, end}], dispatching} | null, sun: {night, next} | null}`.
  `sun`: from Home Assistant's `sun.sun` (watched, so sunset and sunrise push an update); `night` = below the horizon,
  when every screen, the apps and the iPhone widget draw the picture in its dark colours; `next` = the next sunrise
  (at night) or sunset (ISO). `tariff`: the off-peak
  window and planned car-charging slots merged; `bonus`: planned slots (up to 3) not inside the usual 23:30-05:30
  night rate. Power in W (kW sensors
  converted), energy in kWh. A part is null when none of its slots has an entity. `solar.starts`/`ends` (ISO): the
  first and last half hour of today's forecast with any output (a Solcast-style `detailedForecast` attribute).
  `heat_pump.heat` (W) = water flow × 4186 × (leaving − return temperature), from the controller's readings or the
  flow-rate and return slots; `cop` = heat ÷ power while running. `cop_today`: heat and electricity added up every
  10 seconds since local midnight (kept across restarts), split by the 3-way valve (or the mode) into heating and hot
  water; electricity while idle counts only in `overall`; null until 50 Wh has been used. A temperature with nothing
  picked falls back to the controller's reading. Under 30 W counts as idle; a heat pump runs from 100 W; a car is
  charging from 200 W or when its status says so. `home.computed`: no home sensor, so solar + battery + grid.
  A "today" (solar, import, export, home, heat pump) given a running-total meter (nothing in its id or name says
  today or daily) is its rise since local midnight: the meter's reading at midnight comes from Home Assistant's
  history (`history/history_during_period`), kept for the day; null until it's read, and counted from the first
  reading seen if HA has none from midnight.
  `configured: false` without Home Assistant.
- `GET /api/energy/options?refresh=false` -> `{slots: {slot: {kind: "power"|"energy"|"percent"|"temperature"|"number"|"state",
  group, entities: [ids in use], auto: bool, suggested: [ids automatic would use]}}, battery_invert, grid_invert, hide,
  candidates: {kind: [{entity_id, name, state, unit}]}}` for Settings > Energy. 409 without HA.

Live updates: the entities in use are followed over HA's WebSocket; changes broadcast `energy`, at most every 4
seconds.

## Notifications and timers (from Home Assistant)
Put up by the Home Assistant integration (`moonlight.show_notification`, `moonlight.start_timer`) or any paired
client; shown on every device or chosen ones; kept across restarts. Times are epoch milliseconds on the add-on's
clock.
- `GET /api/alerts` -> `{server_time, alerts: [Alert]}`: the ones this device shows (the HA panel, which isn't a
  paired screen, only those for all; the integration sees every one). Count down against `server_time`.
- `POST /api/alerts` -> Alert. Body:
  - `kind`: `notification` (default) or `timer`; `style`: `fullscreen` (default for notifications) or `toast` (default
    for timers: a card in the top corner).
  - `screens`: list (or comma-separated text) of `all` (default), screen names or ids (any case), or a style: `large`,
    `compact`, `phone`, `app` (the iPhone and iPad apps). Styles mean the devices paired at the time. An unknown name
    is a 400 that lists the screens.
  - `id`: your own id, to replace or clear it later (the same id again replaces it, e.g. restarting a timer); else one
    is made.
  - `full_screen_for` seconds: full screen that long, then a card in the corner (`shrink_at` on the Alert). Giving it
    without `style` means full screen; with `style: toast` it is a 400.
  - `icon` (an emoji), `dismissible` (default true; false = only `DELETE` clears it), `chime` (default false for
    notifications, true for timers: played when it appears / reaches zero).
  - notification: `title` and/or `message`, `image` (a web address), `duration` seconds (left out: 10 for a toast,
    0 for full screen; 0 = until dismissed or cleared).
  - timer: `label` (required), `description`, and either `duration` seconds or `until` (ISO date-time; without a zone
    it is the household's time) for a countdown, up to a year. `finished_for` seconds: how long "Time's up" stays
    (left out or 0: until dismissed or cleared).
  - timer counting up: `label`, `description` and `since`: `"now"` or an ISO date-time already gone (up to a year
    ago). `duration` seconds is then how long after `since` it goes (left out: until dismissed or cleared); `until`
    is a 400. `chime` defaults to false (played when it appears). It never finishes.
- Alert = `{id, kind, style, screens, icon, dismissible, chime, created_at, expires_at (null = until dismissed or
  cleared), shrink_at (null = full screen until it goes)}` + notification `{title, message, image}` or timer `{label, description, count_up, started_at, ends_at,
  finished, finished_for}` (`ends_at` null when it counts up from `started_at`).
- `POST /api/alerts/{id}/dismiss` -> `{ok}`: tapped or swiped away on a screen (the × or a swipe right on a corner
  card; a swipe up on a full screen one only makes it small on that screen); gone from every screen. 409 if not
  dismissible, 404 if already gone.
- `DELETE /api/alerts/{id}` -> `{ok}` (404 if gone); `DELETE /api/alerts?screens=Kitchen&screens=large` -> `{cleared:
  [ids]}`: the ones shown on those screens, or with no `screens` every one.

Live updates: topic `alerts`. A timer reaching zero and a screen dismissing one also send
`{"type": "alert", "event": "finished"|"dismissed", id, kind, title, screen}` on the WebSocket (`screen`: the name of
the screen that dismissed it); the integration fires these as `moonlight_alert` events.

## Voice (Assist from Home Assistant)
Screens talk to one of Home Assistant's Assist pipelines through Moonlight, so they need no Home Assistant login.
- `GET /api/voice?layout=` -> `{available, reason?, pipelines: [{id, name, language, stt, tts, wake_word, agent}],
  preferred, pipeline, wake_engine, wake, wake_by_layout, replies}`. `pipeline` is the one screens use (the saved one
  if it still exists, else HA's preferred); `stt`/`tts` say whether it has speech-to-text and a voice; `wake_engine`
  whether HA has a wake word engine (openWakeWord); `wake` whether the wake word is on for that style.
- WebSocket `/api/voice/ws?layout=` relays one screen to `assist_pipeline/run`, one run at a time:
  - screen -> `{"type": "start", "mode": "listen" | "wake" | "text", "text"?, "conversation_id"?}`, then binary
    16 kHz 16-bit mono PCM (listen, wake); `{"type": "stop"}` ends the audio (HA also ends it on silence);
    `{"type": "cancel"}` drops the run. A new `start` drops the run going.
  - screen <- `ready` (connected to HA), then per run: `waiting` (wake word run listening), `woke {phrase}`,
    `listening`, `speech_end`, `heard {text}`, `thinking`, `reply {text, kind, continue, conversation_id}`
    (`continue`: the assistant asked something back), `audio {url}` (the spoken reply, to play on the screen;
    with streaming text-to-speech it comes at the start of the run, before `reply`, so speech can begin while the
    agent is still answering), `silent` (that early audio won't come after all: drop it),
    `go {tab}` (a voice command asked for a section: "show the calendar"),
    `spoken {entity}` (played on the screen's speaker instead), `error {code, message}` (HA's pipeline error codes,
    e.g. `stt-no-text-recognized`, `wake-word-timeout`), `done`.
  - A wake run waits up to an hour for the wake word, then ends with `wake-word-timeout`; screens start another.
  - Speech runs stop at speech-to-text; the relay then sends the words to the agent in a second (intent) run in the
    same conversation, unless Moonlight answers them itself: timers ("set a 30 minute full screen timer", "pasta
    timer for 10 minutes", "cancel the timer", "how long is left on the timer") become Alerts on the asking screen
    (all screens when it isn't paired; full screen when asked), since Home Assistant's own timers need a voice
    satellite device. Everyday commands are Moonlight's too (voice_home.py): sections ("show the calendar"), the
    screen's speaker ("pause", "skip", "turn it up", "play Fleetwood Mac"), today's chores ("tick off Tom's teeth"),
    list items ("add milk to the shopping list"; a list Moonlight hasn't got goes on to HA), events ("add dentist to
    the calendar tomorrow at 3", "what's on tomorrow?"). Typed questions are checked the same way. Its answer is
    spoken with a text-to-speech run.
- `GET /api/voice/audio/{key}` -> the spoken reply's audio, streamed from HA (only keys the relay handed out; the
  last 32 are kept).
- `POST /api/voice/sample?seconds=20` records what screens listening for the wake word hear for the next `seconds`
  (at most 60; nothing is kept otherwise); `GET /api/voice/sample.wav` -> that recording (16 kHz mono WAV), to check a
  screen's microphone.
- `GET /api/voice/sample.json?start=&seconds=` -> `{rate, seconds, peak_dbfs_per_100ms, start, pcm16_b64}`: up to 10 s
  of that recording as base64, for tools that can't take binary.
Spoken replies on `speaker` use `media_player.play_media` with `announce: true` on the screen's speaker (its own, else
its style's); a screen with no speaker speaks them itself.

## Summary (for the Home Assistant integration)
- `GET /api/summary?date=YYYY-MM-DD&now=YYYY-MM-DDTHH:MM` (both optional; default today / now) ->
  `{version, family_name, date, now, people: [PersonSummary], dinner: Meal|null, next_event: EventSummary|null, lists: [List + {items: [Item]}]}`
  PersonSummary = Person + `{balance, chores: [{id, title, emoji, points, time_of_day, completed, streak}], chores_total,
  chores_done, chores_left, all_done, event: EventSummary|null}` where `chores` are those due on `date` and `event` is the
  person's current or next occurrence (not yet ended, next 31 days).
  `next_event` = first occurrence starting at or after `now`. `dinner` = first `dinner` meal on `date`.
  EventSummary = `{id, occurrence_id, title, person_ids, start, end, all_day, location}`.

## Health
- `GET /api/health` -> `{ok: true, version, instance, external_url: str|null, ha_login: bool}`. `instance` is a random
  id for this install, so the apps list a Moonlight they find under several names once. `external_url` is Moonlight's
  public address (add-on option), `ha_login` says whether Sign in with Home Assistant is available.

## Screens (pairing and access)
Who may call `/api/*`:
- **HA ingress**: requests with an `X-Ingress-Path` header coming from the Supervisor ingress proxy (`172.30.32.2`,
  override with `MOONLIGHT_INGRESS_IPS`). HA has already authenticated the user.
- **A paired screen**: its display token as the `moonlight_display` cookie (HttpOnly, long-lived), `Authorization: Bearer <token>`,
  or `?token=` (used by the WebSocket, and once on a kiosk's first page load: the server then sets the cookie).
- **Everyone** when `MOONLIGHT_AUTH=off`. Default: on inside the add-on (`SUPERVISOR_TOKEN` set; add-on option
  `require_pairing`, default true), off elsewhere (local dev, tests). Never on the HTTPS port.

HTTPS (`MOONLIGHT_SSL_CERT` + `MOONLIGHT_SSL_KEY`): a second listener on `MOONLIGHT_HTTPS_PORT` (8443). There auth is
always on, ingress headers are ignored, the cookie is `Secure`, responses carry HSTS, `X-Frame-Options: DENY`,
`nosniff`, and `/docs`, `/redoc`, `/openapi.json` are 404. While HTTPS is on, the plain port answers private
addresses only (403 otherwise). Wrong PINs: 10 per 15 minutes per client address, then 429 with `Retry-After`
(also for a right PIN, until the window passes). `POST /api/pair/start` and `/api/auth/ha/start`: 10 per 10 minutes.

Otherwise `/api/*` returns 401 `{"detail": "This screen is not paired", "pairing": true}` and `/api/ws` is closed;
open without auth: `/api/health`, `/api/auth/status`, `/api/pair/*`. HTML and assets are always served so the pairing
screen loads. A 401 makes the frontend show the pairing screen (so revoking kicks a screen back to pairing).

Every screen opens the same address, `/display`, and is told apart by the token it got when it was paired (a browser
can't read a MAC address). Each paired screen has a name, a style and its own setup.

Display = `{id, name, layout: "large"|"compact"|"phone"|"service"|"app", created_at, last_seen|null, revoked, current: bool,
setup?: {start, sections, speaker, idle_minutes, bar?}, own_setup?: bool}`
(`current` = the screen making the request; `last_seen` updated at most once a minute). Screens only: `setup` is what it
shows, its own choices over its style's (Settings `screens`, `media_players`, `idle_minutes`); `own_setup` says whether
it has choices of its own. The frontend takes the style from `GET /api/auth/status` and switches when it changes.
- `GET /api/auth/status` -> `{required: bool, authorised: bool, via: "ingress"|"display"|"open"|null, display: Display|null}`
- `POST /api/pair/start` `{layout, name?}` (`layout` = the style the screen guesses from its size, or `service` /
  `app` for the two kinds that aren't screens: the Home Assistant integration and the iPhone/iPad app, which have no
  style or setup and are listed apart) -> `{pair_id, code: "6 digits", layout, expires_in: 600}`; the unpaired screen shows the code.
  `layout: "service"` is for a non-screen client (the Home Assistant integration sends `{layout: "service", name: "Home Assistant"}`);
  `name` is a suggestion used if the approver leaves the name blank.
- `GET /api/pair/{pair_id}` -> `{status: "pending", expires_in}` | `{status: "expired"}` |
  `{status: "approved", token, display}` (once only; also sets the cookie). The screen stores the token in localStorage and reloads.
- `POST /api/displays/approve` `{code, name?, layout?, pin}` (authorised session) -> Display. 404 if no screen waits with that code.
  `layout` defaults to what the screen asked for; `name` to the suggested name, else "Large screen" and so on. A `service`
  pairing always stays `service` (the approver's `layout` is ignored), and a screen can't be approved as `service`.
- `GET /api/displays` -> `[Display]` (not revoked)
- `PATCH /api/displays/{id}` `{pin, name?, layout?, setup?}` -> Display. `setup` = `{start?, sections?, speaker?,
  idle_minutes?, bar?}` merged into the screen's own setup (`speaker` a `media_player.*` id or `""` for none; `bar` as in
  Settings `screens`, null = back to automatic; hiding the start
  section moves it to the first one left), or `null` to follow its style again. A `service` has no style or setup.
- `DELETE /api/displays/{id}` `{pin}` -> `{ok: true}`; that token stops working on its next request.

Home Assistant discovery: inside the add-on (`SUPERVISOR_TOKEN` set, `discovery: [moonlight]` in config.yaml) Moonlight
POSTs `{service: "moonlight", config: {host, port: 8091, token}}` to the Supervisor's `/discovery` on start (retrying
while HA starts). `host` is the add-on's hostname (`/addons/self/info`), `token` a `service` display named "Home
Assistant", kept in the settings table (never returned) and reused while it isn't revoked; after a revoke the next start
makes a new one. HA then offers the Moonlight integration under Devices & services. `MOONLIGHT_HA_DISCOVERY=0` turns it off.
Tokens are 256-bit random strings, stored as SHA-256 hashes.

Sign in with Home Assistant (open, no auth; needs Home Assistant's address: `MOONLIGHT_HA_LOGIN_URL`, else HA's
external URL via the Supervisor):
- `GET /api/auth/ha/start?layout=phone|compact|large&name=&app=0|1` -> 302 to `<ha>/auth/authorize` with
  `client_id=<origin>/`, `redirect_uri=<origin>/api/auth/ha/callback` (origin = `MOONLIGHT_EXTERNAL_URL` when the
  request came in on its host, else the request's own). 404 without an HA address.
- `GET /api/auth/ha/callback?state&code` -> swaps the code at `<ha>/auth/token` (inside the add-on
  `http://homeassistant:8123` first), reads `auth/current_user` over HA's WebSocket, revokes the HA token, and creates a
  Display named "<user>'s <name or layout>". Browser: 302 to `/display` with the cookie. `app=1`: 302 to
  `moonlight://signed-in?token=<token>&server=<origin>`. A bad or used state, a refused code or a cancelled login: an
  HTML page with status 400.

## Photo screensaver (Immich)
The screensaver shows photos from the family's [Immich](https://immich.app) server. Moonlight keeps the server address
and an API key, fetches the chosen albums' photo list and proxies preview images, so screens never talk to Immich or
see the key. Moonlight stores no photos of its own. Written against the Immich API of v3.3 (works with v1.1xx-v2.x):
`GET /api/albums`, `POST /api/search/metadata` (album contents and favourites; the flat `albumIds`/`isFavorite`/`type`
fields, falling back to the v3.2+ `filter` form if a server rejects them), `GET /api/memories?for=<date>&type=on_this_day`
and `GET /api/assets/{id}/thumbnail?size=preview` (EXIF orientation already applied), all with the `x-api-key` header.
The key needs `album.read`, `asset.read`, `asset.view` (and `memory.read` for "on this day", `albumAsset.delete` /
`albumAsset.create` for the hide button and Show again).

ImmichConfig = `{configured, server_url, key_set: bool, mode: "albums"|"all", album_ids: [id], excluded_album_ids: [id],
festive: bool, festive_now: bool, favorites: bool, memories: bool, skip_cert_check: bool,
status: "unconfigured"|"pending"|"ok"|"auth_failed"|"error", last_error|null, last_refresh|null, photo_count, version|null}`.
`mode` `albums` (default) shows `album_ids`; `all` shows every album except `excluded_album_ids` (albums made later
included). Favourites and memories are added in either mode. `festive` (default true): albums whose name has
Christmas, Xmas, festive, Yule(tide), Advent, Santa, nativity, carol(s) or Boxing Day as a word (any case; digits may
touch it, "Christmas2024") are hidden outside December, with their photos wherever else they appear. In December
(household timezone) only those and winter albums (winter, snow, frost, blizzard, skiing, sledging, ice skating...) are
shown, from the whole library and in either mode, minus `excluded_album_ids` in mode `all`, plus "on this day" if on
but not favourites (`festive_now: true`); with no festive albums, December is like any other month. The API key is never returned.
ImmichAlbum = `{id, name, asset_count, shared, updated_at|null}` (`updated_at` = Immich's last change to the album).
- `GET /api/immich` -> ImmichConfig
- `PUT /api/immich` `{pin, server_url, api_key, mode?, album_ids?, excluded_album_ids?, festive?, favorites?, memories?, skip_cert_check?}` -> ImmichConfig. `api_key` may be left out
  once one is saved. A new address or key is checked with Immich first: 400 key rejected, 502 unreachable, 403 wrong PIN.
  `server_url` is the Immich address (`http://192.168.1.10:2283`; a trailing `/api` is dropped). `skip_cert_check` (default
  false) uses HTTPS without checking the certificate, for a self-signed one or one made for a domain name. The 502 detail
  says what to try (IP instead of a `.local` name, http vs https, certificate, proxy answering 502, redirect, 404).
- `DELETE /api/immich` `{pin}` -> `{ok: true}` (forgets address, key and choice; nothing changes in Immich)
- `POST /api/immich/test` `{pin, server_url?, api_key?, skip_cert_check?}` -> `{ok: true, version|null, albums: [ImmichAlbum]}`; without
  `server_url`/`api_key` the saved ones are tested. Nothing is saved. 400 / 502 as above.
- `GET /api/immich/albums` -> `[ImmichAlbum]` live from Immich with the saved key (404 not connected, 400/502 as above)
- `GET /api/screensaver/photos` -> `{source: "immich"|"none", status, photos: [{id, width|null, height|null, taken_at|null, place|null, url}],
  albums: [{id, name, updated_at|null, photos: [photo id]}]}`.
  Images only (videos, trashed, hidden and locked assets skipped), from the albums shown (see ImmichConfig) plus
  favourites / today's memories if enabled, de-duplicated, at most 5000. `albums` groups them for playing one album at
  a time: albums most recently changed first, then `favorites` ("Favourites") and `on-this-day` ("On this day"), each
  album's photos oldest first (a photo can be in more than one). An album's contents are only fetched again when its
  `updated_at` or size changes. The screens play a whole album, then pick the next: "on this day" first each day, then
  at random weighted towards recently changed albums, not one of the last three; each screen keeps its place. The list is cached and refreshed every 5 minutes
  (`MOONLIGHT_IMMICH_REFRESH` seconds); if Immich can't be reached the last good list is kept (`status: "error"`, retried
  every minute). Empty `photos` = the screens show their built-in painted scenes. `taken_at` is Immich's local time
  (wall-clock time where the photo was taken, written with a `Z`: show its digits, don't convert it). `place` is the
  Home Assistant zone the photo's GPS position falls in (its friendly name, e.g. "Home"; the smallest if zones overlap),
  else the town Immich found for it (else region, else country); null without location data. Zones are read from HA
  over the same connection as the weather at each refresh; without HA only towns are used. `url` is an absolute path; clients
  prefix their base path.
- `POST /api/screensaver/photos/{id}/hide` -> `{ok: true, removed: [{id, name}], failed: [{id, name, error}]}`: the
  screensaver's hide button (no PIN; the screen asks first). Never shows the photo again and takes it out of every
  Immich album it is in, shown or not (`GET /api/albums?assetId=`, then `DELETE /api/albums/{id}/assets`, needs
  `albumAsset.delete`); favourites and memories are left alone.
  It is hidden even when Immich refuses (`failed`: a shared album the key's user can only view, a key without the
  permission, Immich down). 404 unless the id is in the current photo list.
- `GET /api/immich/hidden?limit=12&offset=0` -> `{total, photos: [{id, albums: [{id, name}], hidden_at, url}]}` hidden
  photos, newest first, a page at a time (`limit` 0-500, 0 = just the count; `albums` = taken out of).
- `POST /api/immich/hidden/{id}/restore` `{pin}` -> `{ok: true, restored: [{id, name}], failed: [{id, name, error}]}`:
  show it again, back into the albums it was taken out of (`PUT /api/albums/{id}/assets`, `albumAsset.create`).
- `GET /api/immich/assets/{id}/preview` -> the preview image streamed from Immich, `Cache-Control: private, max-age=86400`.
  404 unless the id is in the current photo list or hidden (so the proxy can't read the rest of the library), 502 if Immich fails.
  Needs the same auth as the rest of `/api` (paired screens send the cookie with `<img>` requests).
Changes broadcast the `photos` topic.

## Nursery (Tapestry)
Nursery updates from [Tapestry](https://tapestry.info), the early years learning journal. Tapestry has no public API,
so Moonlight signs in with the family's own email and password as the website does (`GET /login` for the CSRF token,
`POST /login`, and for accounts at more than one setting the `/select-school` page's `/visit-school/<id>` or
`/s/<slug>/` links) and reads the JSON endpoints Tapestry's web app uses: `GET /api/4/observations/list?perPage=N`
(newest first) and `GET /api/4/observations/get/{id}`, with `X-Requested-With: XMLHttpRequest`, `X-CSRF-TOKEN` and
`X-TAPESTRY-VERSION: 3`. Unofficial: it may need changing if Tapestry changes its site. Logins that use Google,
Microsoft or a verification code can't be used. The newest 20 observations are checked every 30 minutes
(`MOONLIGHT_TAPESTRY_SECONDS`; 10 minutes after a network error); new ones, and ones whose list entry changed (edited,
new photos or comments), are read in full. The newest 40 are kept: text in the database, photos (up to 12 per update,
the still for a video) as files in `nursery/` beside it, because Tapestry's photo links are signed and expire. A
rejected login stops the checks until it is changed, so the account isn't locked.

NurseryConfig = `{configured, email, school, school_name|null, status: "unconfigured"|"pending"|"ok"|"auth_failed"|"error",
last_error|null, last_sync|null, count}`. The password is never returned.
NurseryUpdate = `{id, title, notes, author, date, children: [{name, person_id|null, color|null}], photos: [{url, video}],
comments: [{author, date|null, text}], added_at}`. `notes` is plain text with line breaks. `date` is when the nursery
wrote it, household time (`YYYY-MM-DDTHH:MM:SS`, or a bare date). `person_id`/`color`: the Moonlight person with the
same first name, if any. `video`: the picture is a video's still (the video stays on Tapestry).
- `GET /api/nursery` -> NurseryConfig
- `PUT /api/nursery` `{pin, email, password?, school?}` -> NurseryConfig. Signs in to Tapestry first (400 with the reason
  when it doesn't accept the login, 424 when Tapestry can't be reached or refuses Moonlight), then reads the newest updates. `password` may be left out to keep
  the saved one (same email). `school`: the setting's name, part of it or its slug, for logins at more than one (""
  = the first). Another account's email forgets the previous account's updates.
- `DELETE /api/nursery` `{pin}` -> `{ok: true}` (forgets the login, updates and photos; nothing changes on Tapestry)
- `POST /api/nursery/sync` -> NurseryConfig after checking Tapestry now (404 not connected, 400 / 424 as above)
- `GET /api/nursery/updates?limit=40` -> `[NurseryUpdate]`, newest first
- `GET /api/nursery/photos/{id}/{n}?v=...` -> the photo (`url` above), `Cache-Control: private, max-age=604800, immutable`
Changes broadcast the `nursery` topic. The `nursery` menu section is shown on screens only once Tapestry is connected;
it is in the large screens' menus by default, and other screens show a button in the top bar instead.

## Display
- `GET /display` and every non-`/api` path serve the SPA `index.html`. Older `/display/hallway`, `/display/kitchen` and
  `/display/phone` addresses keep working; a paired screen's style comes from the server either way.
