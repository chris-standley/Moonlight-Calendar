# Moonlight API (v0.1)

All JSON. Times are household-local, naive ISO strings (`2026-10-12T09:00`), dates are `YYYY-MM-DD`.
Ids are strings. Every mutation broadcasts `{"type":"changed","topic":<topic>}` on the WebSocket `/api/ws`
(topics: `people`, `events`, `chores`, `points`, `rewards`, `lists`, `meals`, `recipes`, `settings`, `photos`, `displays`, `accounts`).
Errors: `{"detail": "..."}` with 400 (bad input / not enough points), 401 (screen not paired, see Screens),
403 (wrong PIN), 404, 413 (upload too large).

The frontend has two interchangeable clients: HTTP (talks to this API) and Demo (in-browser
implementation of the same contract, used for the published preview). Keep them in step.

## Settings
- `GET /api/settings` -> `{family_name, week_start: "monday"|"sunday", temp_unit: "C"|"F", pin_set: bool, chore_approval: bool, timezone,
  screensaver_album: id|null, screensaver_seconds: int, idle_minutes: {hallway, kitchen, phone}}`
  `screensaver_album` null = all photos; `screensaver_seconds` 3..3600 (default 10); `idle_minutes` per layout, 0 = never
  (default `{hallway: 5, kitchen: 3, phone: 0}`).
  `timezone` = household IANA zone (default `Europe/London`); synced events are converted to it.
- `PATCH /api/settings` body: any of `family_name, week_start, temp_unit, chore_approval, timezone, screensaver_album,
  screensaver_seconds, idle_minutes`, plus `pin` (required) -> settings. `idle_minutes` may be partial (`{kitchen: 10}`,
  merged) or one number (applies to hallway and kitchen).
- `POST /api/pin/verify` `{pin}` -> `{ok: bool}`

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
  `repeat` = null | `{freq: "daily"|"weekly"|"monthly", interval: int>=1, byday: ["MO",..] (weekly only, optional), until: date|null}`
  All-day events: `start` = `YYYY-MM-DDT00:00`, `end` = next day `T00:00` (exclusive), may span days.
  An occurrence is included if it overlaps [start, end).
- `POST /api/events` Event without id -> Event
- `PATCH /api/events/{id}` partial -> Event (edits the whole series)
- `DELETE /api/events/{id}` -> `{ok: true}`

Events also carry `calendar_id` (null = local-only), `source` (null | `"icloud"` | `"caldav"`),
`custom_repeat` (bool) and `color` (the calendar's colour, null for local events). See Calendar sync.

## Calendar sync (iCloud / CalDAV)
iCloud is the master. Moonlight caches events locally and polls every account (default every 120 s,
env `MOONLIGHT_SYNC_SECONDS`): one PROPFIND on the calendar home gives every calendar's ctag; only
changed calendars are listed and only changed events downloaded. Errors back off exponentially; an
account whose login is rejected gets `status: "auth_failed"` and is not retried until it is reconnected.

Account = `{id, kind: "icloud"|"caldav", label, username, server_url, status: "ok"|"auth_failed"|"error",
last_error: str|null, last_sync: datetime|null, calendar_count}`. The password is never returned.
Calendar = `{id, account_id, name, color, person_ids: [id], visible: bool, read_only: bool}`.
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
- `GET /api/calendars` -> `[Calendar]`; `PATCH /api/calendars/{id}` `{person_ids?, visible?, color?}` -> Calendar.
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

## Chores
Chore = `{id, title, emoji, person_id, points, time_of_day: "morning"|"afternoon"|"evening"|"anytime", schedule, sort}`
`schedule` = `{type: "daily"}` | `{type: "weekly", days: ["MO",..]}` | `{type: "once", date}`
- `GET /api/chores/all` -> `[Chore]`
- `GET /api/chores?date=YYYY-MM-DD` -> `[ChoreDay]`: chores due that date,
  ChoreDay = Chore + `{date, completed: bool, completed_at: str|null, streak: int}`.
  `streak` = number of consecutive due dates, walking back from `date` (counting `date` only if completed;
  if `date` is not completed, start at the previous due date), that were completed. Look back max 60 days.
- `POST /api/chores` / `PATCH /api/chores/{id}` / `DELETE /api/chores/{id}`
- `POST /api/chores/{id}/complete` `{date}` -> `{completed: true, balance}`; idempotent; adds ledger `+points`
  with reason `"<emoji> <title>"`.
- `DELETE /api/chores/{id}/complete?date=` -> `{completed: false, balance}`; adds ledger `-points`, reason `"Undo: <title>"`.

## Points and rewards
- `GET /api/points` -> `[{person_id, balance}]` for every person
- `GET /api/points/{person_id}/ledger` -> `[{id, person_id, change, reason, at}]` newest first, max 100
- `POST /api/points/adjust` `{person_id, change, reason, pin}` -> `{balance}`
Reward = `{id, title, emoji, cost, person_id: id|null (null = any child)}`
- `GET /api/rewards`; `POST /api/rewards`; `DELETE /api/rewards/{id}`
- `POST /api/rewards/{id}/redeem` `{person_id, pin}` -> `{balance}`; 403 bad PIN, 400 if balance < cost;
  ledger `-cost`, reason `"<emoji> <title>"`.

## Lists
List = `{id, name, emoji, color, kind: "grocery"|"todo", sort, open_count, done_count}`
Item = `{id, list_id, title, done, person_id|null, due: date|null, created_at, sort}`
- `GET /api/lists`; `POST /api/lists` `{name, emoji, color, kind}`; `DELETE /api/lists/{id}`
- `GET /api/lists/{id}/items` -> open items first (by sort), then done items (by done time desc)
- `POST /api/lists/{id}/items` `{title, person_id?, due?}` -> Item
- `PATCH /api/items/{id}` `{title?, done?, person_id?, due?}`; `DELETE /api/items/{id}`
- `POST /api/lists/{id}/clear-done`

## Meals and recipes
Meal = `{id, date, slot: "breakfast"|"lunch"|"dinner"|"snack", title, notes, recipe_id|null}`
- `GET /api/meals?start&end` (end exclusive); `POST /api/meals`; `PATCH /api/meals/{id}`; `DELETE /api/meals/{id}`
Recipe = `{id, title, emoji, minutes, ingredients: [str], url|null}`
- `GET /api/recipes`; `POST /api/recipes`
- `POST /api/recipes/{id}/to-list` `{list_id}` -> `{added: int}` adds each ingredient as an item

## Weather
- `GET /api/weather` -> `{source: "homeassistant"|"demo", entity: str|null, unit: "C"|"F", current: {temp, condition}, daily: [{date, high, low, condition}]}`
  up to 10 days from today. Temperatures are whole numbers in the settings' `temp_unit`.
  `condition` uses HA's names: `sunny, partlycloudy, cloudy, rainy, pouring, snowy, fog, windy, lightning-rainy, clear-night`
  (HA's `snowy-rainy`/`hail` -> `snowy`, `windy-variant` -> `windy`, `exceptional` -> `cloudy`).
  With the add-on option `weather_entity` (env `MOONLIGHT_WEATHER_ENTITY`) set, read from that HA weather entity
  (state + `weather.get_forecasts` daily) via the Supervisor API, cached 10 minutes; if HA can't be reached the
  last good forecast is kept for up to an hour, then it falls back to the deterministic demo forecast (`source: "demo"`).

## Summary (for the Home Assistant integration)
- `GET /api/summary?date=YYYY-MM-DD&now=YYYY-MM-DDTHH:MM` (both optional; default today / now) ->
  `{version, family_name, date, now, people: [PersonSummary], dinner: Meal|null, next_event: EventSummary|null, lists: [List + {items: [Item]}]}`
  PersonSummary = Person + `{balance, chores: [{id, title, emoji, points, time_of_day, completed, streak}], chores_total,
  chores_done, chores_left, all_done, event: EventSummary|null}` where `chores` are those due on `date` and `event` is the
  person's current or next occurrence (not yet ended, next 31 days).
  `next_event` = first occurrence starting at or after `now`. `dinner` = first `dinner` meal on `date`.
  EventSummary = `{id, occurrence_id, title, person_ids, start, end, all_day, location}`.

## Health
- `GET /api/health` -> `{ok: true, version}`

## Screens (pairing and access)
Who may call `/api/*`:
- **HA ingress**: requests with an `X-Ingress-Path` header coming from the Supervisor ingress proxy (`172.30.32.2`,
  override with `MOONLIGHT_INGRESS_IPS`). HA has already authenticated the user.
- **A paired screen**: its display token as the `moonlight_display` cookie (HttpOnly, long-lived), `Authorization: Bearer <token>`,
  or `?token=` (used by the WebSocket, and once on a kiosk's first page load: the server then sets the cookie).
- **Everyone** when `MOONLIGHT_AUTH=off`. Default: on inside the add-on (`SUPERVISOR_TOKEN` set; add-on option
  `require_pairing`, default true), off elsewhere (local dev, tests).

Otherwise `/api/*` returns 401 `{"detail": "This screen is not paired", "pairing": true}` and `/api/ws` is closed;
open without auth: `/api/health`, `/api/auth/status`, `/api/pair/*`. HTML and assets are always served so the pairing
screen loads. A 401 makes the frontend show the pairing screen (so revoking kicks a screen back to pairing).

Display = `{id, name, layout: "hallway"|"kitchen"|"phone"|"service", created_at, last_seen|null, revoked, current: bool}`
(`current` = the screen making the request; `last_seen` updated at most once a minute).
- `GET /api/auth/status` -> `{required: bool, authorised: bool, via: "ingress"|"display"|"open"|null, display: Display|null}`
- `POST /api/pair/start` `{layout, name?}` -> `{pair_id, code: "6 digits", layout, expires_in: 600}`; the unpaired screen shows the code.
  `layout: "service"` is for a non-screen client (the Home Assistant integration sends `{layout: "service", name: "Home Assistant"}`);
  `name` is a suggestion used if the approver leaves the name blank.
- `GET /api/pair/{pair_id}` -> `{status: "pending", expires_in}` | `{status: "expired"}` |
  `{status: "approved", token, display}` (once only; also sets the cookie). The screen stores the token in localStorage and reloads.
- `POST /api/displays/approve` `{code, name?, layout?, pin}` (authorised session) -> Display. 404 if no screen waits with that code.
  `layout` defaults to what the screen asked for; `name` to the suggested name, else "<Layout> screen". A `service`
  pairing always stays `service` (the approver's `layout` is ignored), and a screen can't be approved as `service`.
- `GET /api/displays` -> `[Display]` (not revoked)
- `DELETE /api/displays/{id}` `{pin}` -> `{ok: true}`; that token stops working on its next request.
Tokens are 256-bit random strings, stored as SHA-256 hashes.

## Photos (screensaver albums)
Album = `{id, name, created_at, photo_count, cover_photo_id|null}`. An album "Family" always exists (created on start).
Photo = `{id, album_id, filename, width, height, taken_at|null (EXIF DateTimeOriginal), uploaded_at, uploaded_by|null,
display_url, thumb_url}`. `width`/`height` are after EXIF rotation. `uploaded_by` = the paired screen's name, or the HA
user's display name via ingress. URLs are absolute paths (`/api/photos/{id}/display`); clients prefix their base path.
- `GET /api/albums`; `POST /api/albums` `{name}` -> Album; `DELETE /api/albums/{id}` `{pin}` -> `{ok, deleted_photos}`
  (deletes its photos; resets `screensaver_album` if it pointed there)
- `GET /api/photos?album=<id>` -> `[Photo]` newest first by `taken_at` (else `uploaded_at`); no `album` = all
- `POST /api/photos` multipart: `files` (repeat, max 30 per request, 25 MB each), optional `album_id` (default: first album)
  -> `{uploaded: [Photo], errors: [{filename, detail}]}`. If nothing was stored: 413 (all too large) or 400 with the reasons.
  Accepts anything Pillow reads (JPEG, PNG, WebP, GIF, ...) and HEIC when `pillow-heif` is installed (otherwise HEIC is
  rejected with a message). Stored under `$MOONLIGHT_DATA/photos/` (default: next to the DB; `/data` in the add-on):
  `originals/` (as uploaded), `display/` (max 2560px long edge, JPEG q85, EXIF orientation applied) and
  `thumbs/` (400px short edge, max 800px long edge).
- `DELETE /api/photos/{id}` `{pin}` -> `{ok: true}`
- `GET /api/photos/{id}/display`, `GET /api/photos/{id}/thumb` -> image/jpeg, `Cache-Control: private, max-age=31536000, immutable`.
  Need the same auth as the rest of `/api` (paired screens send the cookie with `<img>` requests).

## Display
- `GET /display/{hallway|kitchen|phone}` and every non-`/api` path serve the SPA `index.html`.
