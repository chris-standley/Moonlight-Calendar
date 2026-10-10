# Moonlight API (v0.1)

All JSON. Times are household-local, naive ISO strings (`2026-10-12T09:00`), dates are `YYYY-MM-DD`.
Ids are strings. Every mutation broadcasts `{"type":"changed","topic":<topic>}` on the WebSocket `/api/ws`
(topics: `people`, `events`, `chores`, `points`, `rewards`, `lists`, `meals`, `recipes`, `settings`, `photos`, `displays`, `accounts`, `media`).
`media` is also sent whenever the configured speaker changes in Home Assistant (see Music).
Errors: `{"detail": "..."}` with 400 (bad input / not enough points), 401 (screen not paired, see Screens),
403 (wrong PIN), 404, 502 (a connected service such as iCloud or Immich can't be reached).

The frontend has two interchangeable clients: HTTP (talks to this API) and Demo (in-browser
implementation of the same contract, used for the published preview). Keep them in step.

## Settings
- `GET /api/settings` -> `{family_name, week_start: "monday"|"sunday", temp_unit: "C"|"F", pin_set: bool, chore_approval: bool, timezone,
  screensaver_seconds: int, idle_minutes: {hallway, kitchen, phone},
  media_players: {hallway, kitchen, phone}}`
  `screensaver_seconds` 3..3600 (default 10); `idle_minutes` per layout, 0 = never
  (default `{hallway: 5, kitchen: 3, phone: 0}`). The screensaver's photos come from Immich (see Photo screensaver).
  `timezone` = household IANA zone (default `Europe/London`); synced events are converted to it.
  `media_players` = the speaker (HA `media_player.*` entity id, `""` = none) each layout shows; the kitchen defaults to
  the add-on option `media_player_entity`, the others to none.
- `PATCH /api/settings` body: any of `family_name, week_start, temp_unit, chore_approval, timezone,
  screensaver_seconds, idle_minutes, media_players`, plus `pin` (required) -> settings. `media_players` may be partial
  (`{hallway: "media_player.kitchen"}`, merged; `""` or null clears one). `idle_minutes` may be partial (`{kitchen: 10}`,
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

Events also carry `calendar_id` (null = local-only), `source` (null | `"icloud"` | `"caldav"` | `"ics"`),
`custom_repeat` (bool), `color` (the calendar's colour, null for local events), `read_only` (bool: in a
read-only calendar, edits get 403) and `busy` (null, or on calendars shown as busy blocks one of
`"busy"|"tentative"|"away"|"elsewhere"`; `"free"` events of such calendars are left out). See Calendar sync
and Calendar links.

## Calendar sync (iCloud / CalDAV)
iCloud is the master. Moonlight caches events locally and polls every account (default every 120 s,
env `MOONLIGHT_SYNC_SECONDS`): one PROPFIND on the calendar home gives every calendar's ctag; only
changed calendars are listed and only changed events downloaded. Errors back off exponentially; an
account whose login is rejected gets `status: "auth_failed"` and is not retried until it is reconnected.

Account = `{id, kind: "icloud"|"caldav"|"ics", label, username, server_url, status: "ok"|"auth_failed"|"error",
last_error: str|null, last_sync: datetime|null, calendar_count}`. The password is never returned.
Calendar = `{id, account_id, name, color, person_ids: [id], visible: bool, read_only: bool,
busy_blocks: bool, busy_blocks_auto: bool, busy_blocks_set: bool}` (busy blocks: see Calendar links).
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
- `GET /api/calendars` -> `[Calendar]`; `PATCH /api/calendars/{id}` `{person_ids?, visible?, color?,
  busy_blocks?: true|false|null}` -> Calendar (`null` = automatic).
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

## Music (now playing on a Home Assistant speaker)
The speaker is a Home Assistant `media_player` entity, typically one created by the Music Assistant integration (e.g. a
Sonos speaker). Screens only name their `layout` (`hallway|kitchen|phone`, default `kitchen`); the backend maps it to
the entity in `settings.media_players`, so a screen can't read or control any other entity. Without Home Assistant
(`SUPERVISOR_TOKEN`, or `MOONLIGHT_HA_URL` + `MOONLIGHT_HA_TOKEN`) the commands return 409.
- `GET /api/media/now-playing?layout=kitchen` -> NowPlaying:
  `{layout, configured: bool, entity: str|null, name, state, show: bool, title, artist, album, duration, position,
  position_updated_at, volume: 0..1|null, muted: bool|null, shuffle: bool|null, repeat: "off"|"all"|"one"|null,
  source, app, music_assistant: bool, has_art: bool, art_url: str|null, supports: {play_pause, previous, next, volume,
  mute, shuffle, repeat, seek}, reachable: bool, error: str|null, server_time}`.
  `state` is HA's (`playing`, `paused`, `idle`, `off`, `standby`, `buffering`, `unavailable`, ...). `show` = worth
  showing: playing/paused/buffering, or idle/on with a track loaded. `duration`/`position` are seconds; the position
  was `position` at `position_updated_at` (HA's clock), so clients tick it locally using `server_time`.
  `supports` comes from the entity's `supported_features`. `music_assistant` = the entity has Music Assistant's
  `mass_player_type` attribute (or `app_id: music_assistant`). If HA is unreachable the last state is kept for 90 s,
  then `state: "unavailable", reachable: false`.
- `GET /api/media/art?layout=kitchen&v=<hash>` -> the album art image (or 404). Moonlight fetches HA's
  `entity_picture_local`/`entity_picture` (a `/api/media_player_proxy/...` path, with its own HA token, or a public
  URL fetched without any token) and caches the last 12 images. `v` is a hash of the picture URL; only the layout's
  current (or recently cached) picture is served, and no HA token ever reaches the screen. Cache-Control: immutable.
- `POST /api/media/command` `{layout, action, value?}` -> NowPlaying. Actions -> HA `media_player` services:
  `play_pause` (media_play_pause), `play`, `pause`, `next` (media_next_track), `previous` (media_previous_track),
  `volume_set` (value 0..1 -> volume_level), `volume_mute` (value bool -> is_volume_muted), `shuffle_set` (bool),
  `repeat_set` (`off|all|one`). 400 bad action/value, 409 no speaker for that layout, 502 HA unreachable or refused.
- `GET /api/media/players` -> `[{entity_id, name, state, music_assistant}]` every `media_player` in HA (Music
  Assistant ones first), for the Settings picker. 502 if HA can't be reached.
- `GET /api/media/favourites?layout=kitchen` -> `[{uri, name, media_type}]` Music Assistant favourite playlists (10)
  and radio stations (6), via `music_assistant.get_library` (favorite: true) on the first loaded Music Assistant
  config entry; cached 15 minutes. Empty for non-Music Assistant players or on any error.
- `POST /api/media/play` `{layout, uri}` -> NowPlaying. Plays one of those favourites with
  `music_assistant.play_media` (enqueue `replace`); 404 if `uri` isn't a current favourite.

Live updates: the backend keeps one WebSocket to HA (`ws://supervisor/core/websocket`, or `MOONLIGHT_HA_WS_URL`)
with `subscribe_trigger` (state trigger on the configured entities). Every change broadcasts the `media` topic.
While that socket is down (HA restarting) it polls the entities' states every 5 s and retries with back-off
(5, 10, 20, 30, 60 s).

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

## Photo screensaver (Immich)
The screensaver shows photos from the family's [Immich](https://immich.app) server. Moonlight keeps the server address
and an API key, fetches the chosen albums' photo list and proxies preview images, so screens never talk to Immich or
see the key. Moonlight stores no photos of its own. Written against the Immich API of v3.3 (works with v1.1xx-v2.x):
`GET /api/albums`, `POST /api/search/metadata` (album contents and favourites; the flat `albumIds`/`isFavorite`/`type`
fields, falling back to the v3.2+ `filter` form if a server rejects them), `GET /api/memories?for=<date>&type=on_this_day`
and `GET /api/assets/{id}/thumbnail?size=preview` (EXIF orientation already applied), all with the `x-api-key` header.
The key needs `album.read`, `asset.read`, `asset.view` (and `memory.read` for "on this day").

ImmichConfig = `{configured, server_url, key_set: bool, album_ids: [id], favorites: bool, memories: bool,
status: "unconfigured"|"pending"|"ok"|"auth_failed"|"error", last_error|null, last_refresh|null, photo_count, version|null}`.
The API key is never returned. ImmichAlbum = `{id, name, asset_count, shared}`.
- `GET /api/immich` -> ImmichConfig
- `PUT /api/immich` `{pin, server_url, api_key, album_ids?, favorites?, memories?}` -> ImmichConfig. `api_key` may be left out
  once one is saved. A new address or key is checked with Immich first: 400 key rejected, 502 unreachable, 403 wrong PIN.
  `server_url` is the Immich address (`http://homeassistant.local:2283`; a trailing `/api` is dropped).
- `DELETE /api/immich` `{pin}` -> `{ok: true}` (forgets address, key and choice; nothing changes in Immich)
- `POST /api/immich/test` `{pin, server_url?, api_key?}` -> `{ok: true, version|null, albums: [ImmichAlbum]}`; without
  `server_url`/`api_key` the saved ones are tested. Nothing is saved. 400 / 502 as above.
- `GET /api/immich/albums` -> `[ImmichAlbum]` live from Immich with the saved key (404 not connected, 400/502 as above)
- `GET /api/screensaver/photos` -> `{source: "immich"|"none", status, photos: [{id, width|null, height|null, taken_at|null, url}]}`.
  Images only (videos, trashed, hidden and locked assets skipped), from the chosen albums plus favourites / today's
  memories if enabled, de-duplicated, at most 5000. The list is cached and refreshed every 5 minutes
  (`MOONLIGHT_IMMICH_REFRESH` seconds); if Immich can't be reached the last good list is kept (`status: "error"`, retried
  every minute). Empty `photos` = the screens show their built-in painted scenes. `url` is an absolute path; clients
  prefix their base path.
- `GET /api/immich/assets/{id}/preview` -> the preview image streamed from Immich, `Cache-Control: private, max-age=86400`.
  404 unless the id is in the current photo list (so the proxy can't read the rest of the library), 502 if Immich fails.
  Needs the same auth as the rest of `/api` (paired screens send the cookie with `<img>` requests).
Changes broadcast the `photos` topic.

## Display
- `GET /display/{hallway|kitchen|phone}` and every non-`/api` path serve the SPA `index.html`.
