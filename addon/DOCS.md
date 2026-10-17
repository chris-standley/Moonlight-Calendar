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
- `require_pairing` (default `true`): wall screens on port 8091 must be paired before they can use Moonlight.
  Moonlight in the Home Assistant sidebar is always signed in.
- `ssl` (default `false`), `certfile` (default `fullchain.pem`), `keyfile` (default `privkey.pem`): serve Moonlight
  over HTTPS on port 8443 with a certificate in `/ssl`, for access from the internet (see below).
- `external_url` (optional, e.g. `https://moonlight.example.com`): Moonlight's address from the internet. The iPhone
  and iPad app switch to it when the home address doesn't answer.
- `homeassistant_url` (optional, e.g. `https://ha.example.com`): Home Assistant's address for "Sign in with Home
  Assistant". Empty = the external URL set in Home Assistant (Settings > System > Network).

The household timezone defaults to Home Assistant's (Settings > System > General) and can be changed in
Moonlight's Settings. The weather comes from a Home Assistant weather entity you pick in Moonlight
(Settings > Display > Weather, which lists them with their current conditions); until then it shows a demo forecast.

## Wall screens

Every screen opens the same address: `http://<ha-host>:8091/display`. It shows a 6-digit code: in Moonlight (sidebar
or phone) go to Settings > Screens > Pair, enter the code and the PIN, and give the screen a name. The
screen remembers its pairing. Tap it in Settings > Screens to rename it, pick its style (Large for a big wall screen,
Compact for a small touch screen, Phone) and choose what it shows: the sections in its menu, the one it opens on, its
speaker and when the photo screensaver starts. Remove it there too.

Below the screens, "In the Home Assistant app" sets the same choices per style for Moonlight opened from Home
Assistant's sidebar or phone app. Paired screens follow those until they're given choices of their own.

For Home Assistant automations and entities, install the Moonlight integration through HACS (custom repository
`https://github.com/chris-standley/Moonlight-Calendar`, type Integration) and restart Home Assistant. The add-on
announces itself, so Moonlight appears under Settings > Devices & services as discovered: select Configure. No pairing
code is needed.

## Access from the internet

Moonlight can be port forwarded safely: it has its own HTTPS port, separate from the home-network port 8091.

1. Get a certificate into `/ssl`. With the **Let's Encrypt** app and a wildcard certificate (`*.example.com`) it
   already is, as `fullchain.pem` and `privkey.pem`. Make a DNS record for Moonlight's name (e.g.
   `moonlight.example.com`) pointing at your home's public IP, the same way as for Home Assistant.
2. In the add-on's Configuration: turn on `ssl` (check `certfile` and `keyfile` match the file names in `/ssl`), and
   set `external_url` to the address people will use, e.g. `https://moonlight.example.com` (add `:<port>` if your
   router forwards something other than 443).
3. Under **Network**, give `8443/tcp` a host port (e.g. 8443), and on your router forward the outside port (443 for an
   address without a port) to that host port on the Home Assistant machine. Restart the add-on.

What changes once HTTPS is on:
- On the HTTPS port every device must be paired (or signed in with Home Assistant), even if `require_pairing` is
  off. Home Assistant ingress isn't accepted there, responses tell browsers to stay on HTTPS (HSTS), and the API
  documentation pages are hidden.
- Port 8091 keeps working as before for wall screens, the Apple TV and the Home Assistant integration, but only
  answers addresses on your home network, so forwarding it by mistake exposes nothing.
- Wrong parent PINs are limited to 10 per 15 minutes per address, and new pairing codes to 10 per 10 minutes.
- The certificate is reloaded within an hour of Let's Encrypt renewing it.

Signing in away from home:
- **Sign in with Home Assistant**: the pairing screen (and the iPhone app's setup) offers it when Home Assistant's
  address is known (its external URL, or `homeassistant_url`). It opens Home Assistant's own login page (with its
  two-factor authentication, if you use it); afterwards the device appears in Settings > Screens as "<name>'s phone"
  and can be revoked there. Any Home Assistant user can sign in, so only give Home Assistant accounts to people who
  may use Moonlight.
- **A pairing code** works too: open `https://moonlight.example.com/display` and approve the code from the Home
  Assistant app (Moonlight in the sidebar > Settings > Screens).

Wall screens at home can stay on `http://<ha-host>:8091`. If they should use the https name instead, the router has
to send that name back into the house (most do; otherwise add a local DNS record for it).

## Music

A screen can show what's playing on a speaker (album art, title, progress, play/pause, skip, volume) and
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
3. Pick it: in Moonlight go to Settings > Screens, tap the screen and choose its speaker (Music Assistant players are
   marked). Compact screens show a card on Today; large screens and phones show a small player in the top bar.

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
"Can view when I'm busy" and copy the ICS link; its busy time shows as a thin bar down the side of the Day view and one line per day in Week and Schedule (first start, last finish and the free gaps). Some workplaces block
publishing. Treat the link like a password.

Settings > Calendars > Home Assistant shows one of Home Assistant's own calendars (bin collections, Workday,
energy saving sessions), read-only and refreshed every 15 minutes. Pick everyone as its people for household
things like bin day. To turn calendar events or appliances into chores (bins out the night before, empty the
dishwasher when it finishes), use the Moonlight integration's `moonlight.add_chore` action in an automation.

Repeating events and chores can repeat on chosen days (tap the days under Weekly or Chosen days) and can skip
public holidays. Pick the country and region in Settings > Display > Public holidays (England's bank holidays
until you choose, when Home Assistant's timezone is Europe/London). Skipped dates are written to iCloud too, so
the event is also missing on those days on phones.

## Recipes

The Recipes section holds the family's recipes: picture, rating, servings and times, ingredients and steps (with step
pictures). Amounts scale with the servings you pick; cups, ounces, pounds and °F stay as written with grams,
millilitres and °C shown beside them. Times in a step ("simmer for 10 minutes") get a timer button, and cook mode
shows one step at a time, with the amounts of the ingredients it uses, with the screen kept on. Hands-free
(the microphone button) listens for "next", "back", "repeat", "start the timer" and "stop the timer" and reads each
step aloud; on the wall screens it needs a browser with speech recognition (Chrome does; it's hidden where it isn't
available). Add to list, and planning a meal with a recipe, offer the
ingredients for a shopping list.

Bring recipes in from a web page (most recipe sites mark out their recipes, so they come straight in), pasted text,
or photos. The iPhone app reads photos on the phone. To read photos on the wall screens and in the browser, or to
let Claude read handwriting and pages without a recipe layout, add an Anthropic API key in Settings > Recipes (from
console.anthropic.com; the photos and text are then sent to Anthropic). Pictures are kept in Moonlight's database.

## Photo screensaver

The screensaver shows photos from Immich. In Moonlight go to Settings > Photo screensaver > Connect Immich, enter
Immich's address (e.g. `http://192.168.1.10:2283`, using your server's IP address: `.local` names often don't work from inside an add-on, and a reverse-proxy address only works if that proxy can reach Immich) and an API key made in Immich (Account Settings > API Keys;
permissions `album.read`, `asset.read`, `asset.view`, plus `memory.read` for "on this day"), test the connection and
choose albums, or choose All albums and tap the ones to leave out. Under Seasonal albums, add an album with its dates
(for example Christmas, 1 to 26 December): it is hidden the rest of the year and shown on its own between those dates. The screens get the photos through Moonlight and never see the key. Without Immich the screensaver shows
painted landscapes. If Immich is itself a Home Assistant add-on, check its port (2283) is filled in under the add-on's Network settings; Immich opened only through the Home Assistant sidebar can't be reached by Moonlight. If Immich uses HTTPS, start the address with `https://`; when its certificate is self-signed or made for a domain name rather than the IP address, turn on Skip certificate check.

## Data

The database is `/data/moonlight.db` (including the Immich address and API key); it is part of the add-on's backups and
survives updates and restarts. Older versions kept uploaded photos in `/data/photos`; Moonlight no longer uses that
folder.
