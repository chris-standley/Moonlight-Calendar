# Moonlight

## Install

1. Settings > Apps > App Store > ⋮ (top right) > Repositories, add
   `https://github.com/chris-standley/home-assistant-apps` and close the dialog.
2. Find **Moonlight** in the store (⋮ > Check for updates if it is not listed yet) and click **Install**.
   Home Assistant downloads the prebuilt image for your machine (amd64 or aarch64) from GitHub's container registry.
3. Set the options below, **Start**, and turn on **Show in sidebar**.

New versions show up as an update on the app page.

## Options

- `demo` (default `true`): seed the demo family (people, events, chores, lists, meals) into an **empty** database
  on first start. Turn it off before the first start for a blank household; it does nothing once data exists.
- `weather_entity` (optional, e.g. `weather.home`): show that Home Assistant weather entity and its daily forecast.
  Empty = a built-in demo forecast.
- `media_player_entity` (optional, e.g. `media_player.kitchen`): the speaker the kitchen screen shows and controls
  (see Music below). Other screens can be given one in Moonlight's Settings > Music.
- `require_pairing` (default `true`): wall screens on port 8099 must be paired before they can use Moonlight.
  Moonlight in the Home Assistant sidebar is always signed in.

The household timezone defaults to Home Assistant's (Settings > System > General) and can be changed in
Moonlight's Settings.

## Wall screens

On the screen's browser open `http://<ha-host>:8099/display/hallway` (or `kitchen`, `phone`). It shows a 6-digit
code: in Moonlight (sidebar or phone) go to Settings > Screens > Pair a new screen and enter the code and the PIN.
The screen remembers its pairing; revoke it in the same place.

## Music

The kitchen screen can show what's playing on a speaker (album art, title, progress, play/pause, skip, volume) and
put the album art on the screensaver. Moonlight drives the speaker through Home Assistant, so anything that is a
`media_player` entity works; for Sonos the recommended route is Music Assistant:

1. Install the **Music Assistant Server** add-on (music-assistant.io > Installation has the add-on repository and
   an install button) and start it. In its web UI add
   your music sources (Spotify, a local library, radio...) under Settings > Music providers, and add **Sonos** under
   Settings > Player providers so your speakers show up as players.
2. In Home Assistant, Settings > Devices & services: the **Music Assistant** integration is usually discovered
   automatically; otherwise Add integration > Music Assistant. It creates a `media_player` entity for each Music
   Assistant player (e.g. `media_player.kitchen`). Use that entity rather than the one from Home Assistant's own Sonos
   integration: it knows Music Assistant's queue, and Moonlight can then offer your Music Assistant favourites.
3. Pick it: set the add-on option `media_player_entity`, or in Moonlight go to Settings > Music and choose a speaker
   for the kitchen (Music Assistant players are marked). The hallway and phones can get one too; they show a small
   player in the top bar.

Moonlight follows the speaker over Home Assistant's WebSocket API, so changes made in the Sonos or Music Assistant
apps appear straight away; while Home Assistant restarts it falls back to checking every few seconds. Album art is
fetched by the add-on and passed on to the screens, which never see a Home Assistant token.

## Calendars

Settings > Calendars > Connect iCloud with an Apple ID and an app-specific password
(account.apple.com > Sign-In and Security > App-Specific Passwords), then choose which person each calendar
belongs to. Moonlight syncs every 2 minutes and writes changes made on the screens back to iCloud.

Settings > Calendars > Add calendar link shows a read-only published calendar (an ICS / webcal link), such
as a work calendar, school term dates or bin days, refreshed every 15 minutes. For an Outlook / Microsoft 365
work calendar: Outlook on the web > Settings > Calendar > Shared calendars > Publish a calendar, choose
"Can view when I'm busy" and copy the ICS link; its events show as "busy" blocks. Some workplaces block
publishing. Treat the link like a password.

## Photo screensaver

The screensaver shows photos from Immich. In Moonlight go to Settings > Photo screensaver > Connect Immich, enter
Immich's address (e.g. `http://homeassistant.local:2283`) and an API key made in Immich (Account Settings > API Keys;
permissions `album.read`, `asset.read`, `asset.view`, plus `memory.read` for "on this day"), test the connection and
choose albums. The screens get the photos through Moonlight and never see the key. Without Immich the screensaver shows
painted landscapes.

## Data

The database is `/data/moonlight.db` (including the Immich address and API key); it is part of the add-on's backups and
survives updates and restarts. Older versions kept uploaded photos in `/data/photos`; Moonlight no longer uses that
folder.
