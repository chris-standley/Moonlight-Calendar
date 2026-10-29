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
speaker and when the photo screensaver starts. Remove it there too. A compact screen can hang either way round:
turned upright, it rearranges every section to suit a tall screen and moves its menu to a bar along the bottom. Pick up
to four tabs for that bar under "Bottom bar when upright"; the rest are under More.

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

### Music tab

Every screen with a speaker gets a **Music** tab (the iPhone, iPad and Apple TV apps too, once phones have a speaker).
Tapping the music card on Today, or the player in the top bar, opens what's playing with an **Open Music** button that
goes straight to it:

- **Up next**: what's playing and the queue. Tap a track to play it now, play it next, or remove it.
- **Library**: your Music Assistant library and favourites (playlists, albums, artists, podcasts, radio) through Home
  Assistant's media browser, plus search on Music Assistant speakers. Play anything now, next, or at the end of the
  queue.
- **Rooms**: group other speakers with this one, take them out again, and set each room's volume.

Home Assistant only tells Moonlight the current and next track of a Music Assistant queue. For the whole queue (and to
reorder or remove tracks), make a long-lived token in the Music Assistant web UI under Settings > Profile and enter it
in Moonlight under Settings > Music. The address is normally worked out for you; enter it (e.g.
`http://homeassistant.local:8095`) if not. The token stays in the add-on. A speaker from Home Assistant's own Sonos
integration shows its whole Sonos queue without a token.

If a screen's speaker is a Music Assistant player that's idle while someone plays on that Sonos from the Sonos app,
the screen shows and controls what the Sonos app is playing.

The screensaver shows the album art with play/pause, skip and volume while music is playing (and for 15 minutes after
it's paused); tapping the controls doesn't wake the screen, and tapping anywhere else on the card opens the Music tab.

Moonlight follows the speaker over Home Assistant's WebSocket API, so changes made in the Sonos or Music Assistant
apps appear straight away; while Home Assistant restarts it falls back to checking every few seconds. Album art is
fetched by the add-on and passed on to the screens, which never see a Home Assistant token.

## Security

The Security section shows your alarm, its sensors and your cameras from Home Assistant, live, on the wall screens,
phones, the iPhone and iPad app and the Apple TV app:

- **Alarm**: the Alarmo alarm if you use Alarmo (otherwise the first alarm panel); choose another, or none, in
  Settings > Security. It shows armed or disarmed, who changed it and when, and which sensors stop it arming.
  Buttons arm it in each mode the panel offers (away, home, night, vacation) and disarm it. Disarming asks for the
  alarm code on a keypad; the code goes straight to Home Assistant and is never saved by Moonlight. After 5 wrong
  codes the screen has to wait 5 minutes.
- **Sensors**: the ones you set up in Alarmo, grouped into doors, windows, motion and smoke or leaks, with a lock on
  the ones guarded in the current mode.
- **Cameras**: UniFi Protect cameras appear on their own (through the UniFi Protect integration); other cameras can be
  turned on in Settings > Security. Each plays live (the camera's medium-resolution channel when it's enabled, so
  several can play at once on a Pi); tap one to watch it full size.

When a camera's "Person detected" sensor turns on, the camera pops up live in the corner of the wall screens (if the
screensaver is showing, the camera takes the photo's place full screen instead) and goes away 15 seconds after the person has gone; tap it to watch full size or the cross to close
it. Settings > Security chooses which styles of screen pop up (large and compact by default) and whether the Apple TV
app does (off by default, handy if the TV already shows cameras from HomeKit), which sensor each camera uses, and has a **Test pop-up** button. The live picture is Home Assistant's own video
stream of the camera. For a lighter stream on a Raspberry Pi, enable each camera's "Medium resolution channel" entity in
Home Assistant: compact screens then play it, while large screens and the Apple TV keep the full resolution. Turning on
"Preload stream" in each camera entity's settings makes the video start faster. Cameras that can't stream fall back to snapshots about twice a second.

## Energy

The Energy section draws your house with the power running between its parts, live from Home Assistant:

- **Solar**: what the panels make now and so far today. Before they start in the morning it says when they're
  expected to and how much the day should make (from a Solcast forecast), and after dark what tomorrow should make.
  The current weather's icon takes the sun's place unless it's sunny.
- **Battery**: how full it is, and whether it's charging or powering the house.
- **Grid**: buying or selling right now, and how much was bought and sold today.
- **Home**: what the house is using now and today.
- **Car**: plugged in or not, charging or not, how fast, the car's battery and range, what this charge added, and
  the charge limit and ready-by time (the car's own limit, and Intelligent Octopus's target time).
- **Heat pump**: whether it's running, what it's doing (heating the house, hot water, defrosting), what it draws,
  its flow temperature, and its COP: right now and for today, for heating, hot water and overall. Moonlight works
  COP out itself from the water flow rate and how much warmer the water leaves than it comes back (ESPAltherma's
  readings, or flow-rate and return-temperature sensors you pick) against the heat pump's power meter. Today's COP
  builds up while Moonlight is running and starts again at midnight.
- After sunset the picture switches to its night colours on every screen, the iPhone and Apple TV apps and the
  iPhone widget, and back at sunrise (from Home Assistant's sun).
- **Temperatures**: inside with the heating set point and humidity, the hot water tank with its set point, and outside (from a sensor, or the weather) with its humidity, shown above the heat pump. Each has a switch in Settings › Energy to leave it off the picture. Solar, battery, grid, home, car, heat pump and Predbat each have a switch too.
- **Predbat**: if Predbat is installed, a row under the picture with its status, the price now, the export price, the
  cost so far today, how long the battery will last, and when it next charges the battery. With the Octopus Energy
  integration it also shows the next cheap slot (or how long the cheap rate lasts) and any bonus slots Intelligent
  Octopus adds for car charging outside the usual 23:30 to 05:30 night rate.

Moonlight finds the sensors itself, starting with the ones in Home Assistant's Energy dashboard (Settings > Dashboards >
Energy), then by name (for example a myenergi zappi's plug status, or a heat pump's "Operation" sensor). Settings >
Energy shows what it picked for each and lets you choose another sensor or None. A "today" sensor can be a meter that
just keeps counting up (a lifetime kWh total): Moonlight shows what it has added since midnight. Leave everything for a part on None
and it isn't drawn. If the battery or grid arrows point the wrong way, use the **Flip direction** switch there.

## Notifications and timers

With the Moonlight integration installed in Home Assistant, automations and scripts can put things on the screens:

- **`moonlight.show_notification`**: a message full screen or as a toast in the corner, with a title, text, an emoji
  and optionally a picture.
- **`moonlight.start_timer`**: a timer with a label and a description, for a duration or counting down to a date and
  time. At zero it chimes and says Time's up. With `count_up` (or `since`, a time already gone) it counts up
  instead, like how long since the kettle boiled.

`full_screen_for` shows either one full screen for a while, then as a card in the corner. On a screen, swipe a full
screen one up to make it small there, and swipe a corner card right to dismiss it everywhere.

Each goes to every screen or to chosen ones (`screens`: names from Settings > Screens, or `large`, `compact`, `phone`,
`app`), and stays for a set time or until someone taps it away (gone from every screen) or
`moonlight.clear_notifications` clears it. The iPhone, iPad and Apple TV apps show them too. A timer finishing and a
notification being dismissed fire the `moonlight_alert` event in Home Assistant. Settings > Display > **Test a
notification** shows one on that screen. Examples are in the integration's README.

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

Recipes are arranged by course (Breakfast & brunch, Starters, Light bites, Main meals, Sides, Desserts, Baking, Snacks,
Drinks, Sauces & extras) or by the cookbook they came from: choose in the sort menu. Each recipe's course, cookbook and
page are in its editor. Claude fills in the course and the printed page number when it reads a recipe, and a cookbook
scan asks for the book's name once for every recipe found.

Bring recipes in from a web page (most recipe sites mark out their recipes, so they come straight in), pasted text,
or photos. The iPhone app reads photos on the phone. To read photos on the wall screens and in the browser, or to
let Claude read handwriting and pages without a recipe layout, add an Anthropic API key in Settings > Recipes (from
console.anthropic.com; the photos and text are then sent to Anthropic). Pictures are kept in Moonlight's database.

To bring in a whole cookbook, choose Add > A whole cookbook (or Scan a whole cookbook on the iPhone) and scan or
choose every page, in order, up to 200 at a time. Claude reads them a few at a time while you carry on, joining
recipes that run over two pages, and the recipes found wait at the top of Recipes: check each one in the editor, or
Save all. Pages that couldn't be read can be tried again. Each page is one request to Anthropic. Turn on **Cheaper,
slower** to pay half: Anthropic then reads the pages when it has room (usually within the hour, at most a day) and
the recipes all turn up together.

On the iPhone the scan starts with the camera looking for the barcode on the back of the book (or type its ISBN).
Moonlight looks the book up in Open Library, then Google Books, for its title, author and cover, then the camera
moves on to the pages. Every recipe found is filed under that book, and By cookbook in the sort menu shows its cover.

On a wall screen, tablet or in the browser, Which cookbook? does the same: **Scan the book's barcode** opens the
camera when the device has one. Live video needs a secure page (Moonlight opened through Home Assistant, or its
https address); on a plain http address the button becomes **Take a photo of the barcode** instead. A screen with no
camera shows just the ISBN box, and a USB or Bluetooth barcode reader connected to it types the number in.

To move recipes to or from another app, use Settings > Recipes on a wall screen or in the browser (or the sort menu
and + on the iPhone's Recipes). Send to another app makes a file of the whole recipe box, pictures included, for Mela,
Paprika or any app that reads schema.org recipes. Bring in from another app takes a Mela, Paprika or schema.org file
(or a saved recipe web page), works out which it is, and adds every recipe not already in the box.

## Photo screensaver

The screensaver shows photos from Immich. In Moonlight go to Settings > Photo screensaver > Connect Immich, enter
Immich's address (e.g. `http://192.168.1.10:2283`, using your server's IP address: `.local` names often don't work from inside an add-on, and a reverse-proxy address only works if that proxy can reach Immich) and an API key made in Immich (Account Settings > API Keys;
permissions `album.read`, `asset.read`, `asset.view`, plus `memory.read` for "on this day"), test the connection and
choose albums, or choose All albums and tap the ones to leave out. Albums with Christmas, Xmas, festive, Yule,
Advent, Santa, nativity, carol or Boxing Day in their name only show in December, when only they and winter albums
(winter, snow, frost, skiing...) are shown; turn off "Christmas albums only in December" to stop that. The screens get the photos through Moonlight and never see the key. Without Immich the screensaver shows
painted landscapes.

Swipe left on a photo for the next one and right to go back (a tap still wakes the screen); on the Apple TV
slideshow use left and right on the remote.

To stop a photo coming up again, tap the crossed-out eye under the photo's details at the top right of the screensaver (on the Apple TV, press
the remote during a slideshow) and confirm. Moonlight takes it out of every Immich album it is in and never shows it
again. Removing photos from albums needs two more API key permissions, `albumAsset.delete` (and
`albumAsset.create` to put one back); without them, or for a shared album you can only view, the photo is still
hidden from the screens but stays in the album. Settings > Photo screensaver shows how many are hidden; open the
list to see them a few at a time, each with Show again, which puts it back in its albums.

If Immich is itself a Home Assistant add-on, check its port (2283) is filled in under the add-on's Network settings; Immich opened only through the Home Assistant sidebar can't be reached by Moonlight. If Immich uses HTTPS, start the address with `https://`; when its certificate is self-signed or made for a domain name rather than the IP address, turn on Skip certificate check.

## Nursery updates (Tapestry)

If your nursery uses Tapestry, Moonlight can show its updates: a Nursery section on large screens and the Apple TV,
and a button with the number of new updates at the top of compact screens, phones and the iPhone app's Today. In
Moonlight go to Settings > Nursery > Connect and enter the email and password you use at tapestryjournal.com (and,
if your login has more than one nursery or school, its name). Moonlight signs in the way the website does, checks
every 30 minutes and keeps a copy of the newest 40 updates and their photos, so the screens never talk to Tapestry.
Tapestry has no official way to do this, so it may need an update if Tapestry changes its website. Logins that use
Google, Microsoft or a verification code can't be used. Videos show as a still; play them in the Tapestry app.

## Data

The database is `/data/moonlight.db` (including the Immich address and API key, and the Tapestry login), with copies of nursery photos in `/data/nursery`; it is part of the add-on's backups and
survives updates and restarts. Older versions kept uploaded photos in `/data/photos`; Moonlight no longer uses that
folder.
