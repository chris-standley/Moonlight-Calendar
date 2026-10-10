# Moonlight

Self-hosted family wall calendar for kitchen and hallway screens, packaged as a Home Assistant add-on.
Version 0.2: demo family data; iCloud calendar sync and read-only calendar links (Settings > Calendars).

| Folder | What it is |
|---|---|
| `API.md` | The HTTP + WebSocket contract shared by backend and frontend |
| `seed/demo.json` | Demo family (4 people, events, chores, rewards, lists, meals), dates relative to today |
| `backend/` | Python FastAPI + SQLite. `cd backend && python3 -m moonlight` (port 8099). Tests: `python3 -m pytest tests` |
| `frontend/` | React + TypeScript (Vite). `npm ci && npm run build` -> `dist/` served by the backend |
| `addon/` | Home Assistant add-on (config.yaml, multi-stage Dockerfile built from the repo root, DOCS.md). `repository.yaml` makes this repo an add-on repository |
| `custom_components/moonlight/` | HACS custom integration: Moonlight people, chores, stars, lists, meals and calendars as HA entities and services. See its [README](custom_components/moonlight/README.md) |
| `tests/` | Tests for the integration (`python3 -m pytest tests`; `tests/ha/` needs pytest-homeassistant-custom-component) |
| `screenshots/` | Every view at hallway (2560x1440), kitchen (1920x1200 at 2x zoom) and phone sizes |

## Install on Home Assistant

1. Settings > Add-ons > Add-on Store > ⋮ > Repositories, add `https://github.com/chris-standley/Moonlight-Calendar`.
2. **Moonlight** > Install (⋮ > Check for updates if it is not listed yet), set the options, Start, Show in sidebar.
3. Options: `demo` (seed the demo family into an empty database, default on), `weather_entity` (e.g. `weather.home`),
   `require_pairing` (default on). The household timezone defaults to Home Assistant's.
4. Pair wall screens on port 8099 (below) and connect iCloud in Settings > Calendars.

The add-on page's Documentation tab ([addon/DOCS.md](addon/DOCS.md)) has the details.

This needs the repo to be **public**. HA doesn't build anything: `config.yaml` names prebuilt images
(`ghcr.io/chris-standley/{arch}-moonlight-addon`), which `.github/workflows/addon.yml` builds for amd64 and aarch64
and pushes to GHCR on main when `version` in `addon/config.yaml` is new (or on a manual run). The GHCR packages must be
public too: if they don't inherit the repo's visibility, open each package on GitHub (Packages) > Package settings >
Change visibility > Public. Pull requests build both images and start them without pushing.

To release: bump `version` in `addon/config.yaml` and `__version__` in `backend/moonlight/__init__.py` (CI checks
they match) and merge to main; HA then offers the update.

Build an image locally from the repo root: `docker build -f addon/Dockerfile --build-arg
BUILD_FROM=ghcr.io/home-assistant/amd64-base-python:3.12-alpine3.20 .` (the Dockerfile builds the frontend itself).
A local add-on copied into `/addons` is not set up: HA builds those from the add-on folder alone, and this image
needs the whole repo.

## Screens

- Hallway: `http://<ha-host>:8099/display/hallway` (27in, 2560x1440, browser zoom 1, root font 20px). Opens on the week calendar.
- Kitchen: `http://<ha-host>:8099/display/kitchen` (Touch Display 2, 1920x1200, run TouchKio at 2x zoom = 960x600 CSS px). Opens on Today.
- Phone: `/display/phone`, or the HA sidebar via ingress.
- Kiosks need an emoji font for chore icons: `sudo apt install fonts-noto-color-emoji` on Raspberry Pi OS.

## Preview build

`npm run build:demo` builds one self-contained HTML file (`dist-demo/index.html`) that runs the whole app
against an in-browser copy of the API (`src/api/demo.ts`) seeded from `seed/demo.json`. Demo PIN: 1234.

## Pairing wall screens

On the add-on's LAN port every screen must be paired (HA users via ingress are already signed in). Open
`http://<ha-host>:8099/display/kitchen` on the kiosk: it shows a 6-digit code. In Moonlight (HA sidebar or phone)
go to Settings > Screens > Pair a new screen, enter the code and the PIN; the kiosk loads the app and remembers its
token (localStorage + an HttpOnly cookie). Revoke a screen there too. For TouchKio you can instead copy a token into
the URL once: `.../display/kitchen?token=...` (it is stored, then stripped). Add-on option `require_pairing: false`
turns this off. The Home Assistant integration (`custom_components/moonlight`) pairs the same way: its setup dialog
shows a code to enter there, and it is listed as "Home Assistant" (Integration) so it can be revoked too.

## Photos

Photos view (rail button; also in the phone's bottom bar): albums, upload (many at once, 25 MB each), delete with
the PIN, "Start slideshow". The idle screensaver shows the chosen album (Settings > Photo screensaver) with a
crossfade and slow zoom; portrait photos on a landscape screen are shown whole over a blurred copy. Files live in
`/data/photos` in the add-on. iPhone HEIC needs `pillow-heif` (installed when its wheel is available).

## iCloud calendars

Settings > Calendars > Connect iCloud with each adult's Apple ID and an app-specific password
(account.apple.com > Sign-In and Security > App-Specific Passwords). Moonlight talks CalDAV to
`caldav.icloud.com` directly, polls every 2 minutes (`MOONLIGHT_SYNC_SECONDS`), writes touchscreen edits
to iCloud first and maps each calendar to people. Credentials stay in the add-on database. Any other
CalDAV server works too (`kind: "caldav"` via the API). The sync tests run a local Radicale server:
`pip install radicale` before `python3 -m pytest tests`. Details in `API.md`.

## Calendar links (read-only)

Settings > Calendars > Add calendar link shows any published ICS calendar (`webcal://` or `https://`):
a work calendar, school term dates, bin days, public holidays. Paste the link, check it (shows how many
events it found), name it and pick whose calendar it is. Moonlight refreshes it every 15 minutes
(`MOONLIGHT_FEED_SECONDS`) with a conditional GET, keeps events from 60 days back to a year ahead and never
lets them be edited. The link is a secret: it is stored only in the add-on database and the API and
screens only ever show a masked form (`outlook.office365.com/…/calendar.ics`).

Work calendar (Outlook / Microsoft 365): Outlook on the web > Settings > Calendar > Shared calendars >
Publish a calendar, pick the calendar and **Can view when I'm busy** (or **Can view titles and
locations**), Publish, and copy the ICS link. Some workplaces turn publishing off. A free/busy-only
calendar (every event just "Busy", "Tentative", "Away", "Free") is shown automatically as hatched
"Alex – busy" blocks in the calendar's colour: tentative ones lighter, free time hidden. The calendar's
sheet in Settings can force this on or off. Outlook's Windows timezone names ("GMT Standard Time",
"Pacific Standard Time") are resolved by the `icalendar` library, from the feed's VTIMEZONE or its
Windows-to-IANA table. Tests: `backend/tests/test_ics_feed.py` (fixtures in `backend/tests/fixtures/`,
served by `httpx.MockTransport`).

## Home Assistant

- Weather: set the add-on option `weather_entity` (e.g. `weather.home`) to show that entity's forecast; empty = demo forecast.
- Entities and services: install the `moonlight` integration through HACS, see `custom_components/moonlight/README.md`.

## Your family

Settings > Family: add people (name, colour, adult or child), tap someone to edit them, reorder with the arrows,
rename the family. Removing someone needs the PIN and deletes their chores, stars and personal rewards (events and
list items stay). With the add-on option `demo: false` Moonlight starts empty and every screen points here.

## Not built yet

Profile photos for people; drag-to-reorder.
