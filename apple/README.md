# Moonlight for iPhone, iPad and Apple TV

Native SwiftUI apps in one Xcode project (`Moonlight.xcodeproj`), in the same look as the wall screens.

| Target | Runs on | Scheme |
|---|---|---|
| `Moonlight` | iPhone and iPad (iOS/iPadOS 18+) | **Moonlight** |
| `MoonlightTV` | Apple TV (tvOS 18+) | **Moonlight TV** |
| `CookingWidget` | Inside the iPhone app: the cooking Live Activity and the Energy home screen widget | (built with **Moonlight**) |

Both share one bundle id, so a future App Store listing can be a single universal purchase.

## iPhone and iPad

The phone and tablet app is where you plan things: add and edit events, chores, rewards, meals, lists and items, give
bonus stars, and tick things off. Anything protected by the parent PIN asks for it.

It adapts to the space each screen actually has (its own width, not the device model), so it behaves the same on an
iPhone, a phone that unfolds, iPad Split View and Slide Over, Stage Manager windows and on rotation:

| Width | Layout |
|---|---|
| Narrow (< 600 pt: phones, folded, slide-over) | Tab bar. Calendar opens on Day with a week strip (swipe between days) or Schedule. Chores: pick a person or everyone, one list. Meals: a card per day. Lists: list, then items. |
| Medium (600–999 pt: unfolded phone, half an iPad) | Sidebar (can collapse to tabs). Today in two columns. Calendar adds the Week grid. Chores: two people side by side, swipe for more. Meals: week grid. Lists: lists beside items. |
| Wide (≥ 1000 pt: iPad full screen) | As medium, with three columns on Today and up to four people side by side. |

Text uses the system's text styles in the rounded design, so Dynamic Type works.

Once Tapestry is connected (Settings › Nursery on a wall screen), Today has a nursery button at the top left with
the number of new updates; it opens the updates with their photos.

### Recipes

The Recipes tab is the family recipe box: search, favourites, tags, and a page per recipe with its picture, rating,
times, ingredients scaled to the servings you pick (metric amounts shown beside cups, ounces and pounds), the method
with step pictures, and Start cooking / Add to list / Plan it. Planning a meal with a recipe offers its ingredients
for the shopping list, with everyday staples and things already on the list left unticked.

- **Adding recipes**: type one in, scan cookbook pages with the camera (the document scanner finds and flattens each
  page), choose photos, paste a link or paste text. Photos are read on the phone with Apple's Vision (two-column
  pages are read a column at a time) and sorted into a recipe by the add-on; with an Anthropic key set in the add-on
  (Settings › Recipes on a wall screen), "Read with Claude" sends the photos to Claude instead. Either way the recipe
  opens in the editor to check before it's saved.
- **Scanning a whole cookbook** (+ › Scan a whole cookbook, needs the Anthropic key): scan or choose up to 200 pages;
  they're sent to the add-on, where Claude reads them in the background. A Cookbook scan card at the top of Recipes
  shows progress and the recipes found: tap one to check it in the editor, tick to save it as read, or Save all.
  **Cheaper, slower** sends them as an Anthropic batch at half the price, back within a day (usually the hour).
- **Other recipe apps**: the sort menu's Send to another app shares the whole recipe box as a Mela, Paprika or
  schema.org file (open it in Mela or Paprika, or save it to Files); + › From another app's file brings any of those in.
- **Cook mode** shows one step at a time, large, with the amounts of the ingredients it mentions and its timer
  buttons; swipe or tap Next. The screen stays on. **Hands-free** (the microphone button) listens for "next",
  "back", "repeat", "start the timer", "stop" and "ingredients", recognised on the phone, and reads each step aloud.
- **Timers** go off with the app closed or the phone locked: each books a local notification with **+1 minute** and
  **Stop** buttons that work from the Lock Screen without opening the app.
- **Live Activity**: while cook mode is open the current step and the next timer's countdown show on the Lock Screen
  and in the Dynamic Island (the `CookingWidget` extension). It is started and updated by the app, so it needs no push
  server or paid developer account.

### Siri and Shortcuts

Say these (or find them in the Shortcuts app and Spotlight). They use the app's pairing and run without opening it.

| Say | Does |
|---|---|
| "What's on today in Moonlight" | Reads what's left on today's calendar |
| "What's for dinner in Moonlight" | Tonight's dinner from the meal plan (or tomorrow's) |
| "Add to the shopping list in Moonlight" | Asks what, then adds it; "milk, eggs and bread" adds three items. "Add to *list name* in Moonlight" picks a list |
| "How many stars does *name* have in Moonlight" | Their stars, and how many more for the next reward |
| "Tick off a chore in Moonlight" | Lists today's chores left; the one picked is ticked off and earns its stars |

### Reminders

Settings › Reminders: a notification a chosen time before each event (for everyone, or only chosen people), and an
evening "chores left" nudge. They are worked out on the phone from the calendar, rescheduled whenever anything
changes, and kept fresh by background app refresh, so no push server is needed.

### Energy widget

Add the **Energy** widget to the Home Screen (touch and hold the Home Screen › Edit › Add Widget › Moonlight). It
draws the same house as the Energy tab with the headline numbers: medium is the picture on its own, large (and extra
large on iPad) adds the car's charge target and the next cheap-rate slots under it. It asks Moonlight for fresh
readings about every 15 minutes and whenever the app is opened; tap it to open the app.

The widget reads the app's pairing from the Keychain it shares with the app (the `CookingWidget.entitlements`
keychain group), so it needs no app group and works with a free Apple ID. Open the app once after installing so it
copies its address over, and pair the app first if it isn't.

### Away from home

If the add-on has HTTPS and a public address (`external_url`, see the add-on's DOCS.md), the app learns it after
pairing and switches to it whenever the home address doesn't answer, and back again at home. Setup also accepts the
public address (e.g. `moonlight.example.com`), and offers **Sign in with Home Assistant** when the add-on knows Home
Assistant's address: Home Assistant's login page opens in a sign-in sheet and the phone is paired straight away.

## Apple TV

| Tab | What it shows | What you can do |
|---|---|---|
| Today | Coming up today and tomorrow, meals, each child's chore progress and stars, Now playing | Open an event; play/pause/skip on the speaker |
| Calendar | Week grid (weather, dinner per day) or a two-week schedule | Today / previous / next, show or hide each person |
| Chores | A column per person, chores by time of day, streaks | Select a chore to tick it off or undo it |
| Rewards | Each child's stars, rewards with progress, recent stars | Redeem a reward (parent PIN on a number pad) |
| Meals | The week's meal plan | Previous / next week |
| Lists | Shopping and to-do lists | Select an item to tick it off |
| Nursery | Nursery updates from Tapestry, once connected (Settings › Nursery on a wall screen) | Pick an update; open its photos full screen |
| Photos | The Immich screensaver photos | Full-screen slideshow with the clock |
| Settings | What this Apple TV is paired with | Forget it and pair again |

Everything works with the Siri Remote and there is no text entry. Play/Pause controls this screen's speaker from any
tab. If it's turned on (Settings › Security in Moonlight, pop up people on Apple TV; off by default), a camera that sees
a person pops up its full-resolution live video in the corner over any tab until 15 seconds after they've gone.

## Pairing (both apps)

1. The app finds Moonlight on the home network: Home Assistant announces itself over Bonjour (`_home-assistant._tcp`),
   and the add-on answers on the same host on port 8091 (the default) or 8099 (before 0.3.1); `homeassistant.local`
   is tried too. Otherwise enter the address: typed on the phone (`192.168.1.5`, `homeassistant.local:8091` or a full
   URL), or picked with the remote on the TV (IP and port, swipe up/down on each number).
2. The app shows a 6-digit code. On a wall screen or in the Home Assistant sidebar open Moonlight › Settings ›
   Screens › Pair and enter it. The TV pairs as a large screen. The iPhone and iPad app is listed apart from the screens, under Phones and tablets (it has no screen style or setup).
3. The token is kept in the device's Keychain. Deleting it in Settings › Screens sends the app back to pairing.

Live updates come over the same WebSocket the wall screens use, so a change anywhere shows everywhere straight away.
The apps talk to the add-on's LAN port, so away from home they need a VPN (or a reverse proxy URL typed on the phone).

## Build and run (on a Mac)

Needs Xcode 16 or newer. A free Apple ID is enough to run on your own devices (installs then expire after 7 days;
press Run again to renew). A paid developer account makes installs last a year and allows TestFlight.

1. `open apple/Moonlight.xcodeproj`
2. For each target (**Moonlight**, **MoonlightTV**) › Signing & Capabilities › Team: pick your Apple ID. If Xcode says
   the bundle id is taken, change `io.github.chris-standley.moonlight` to anything unique.
3. iPhone/iPad: plug it in (or use Wi-Fi after the first time), turn on Developer Mode when iOS asks
   (Settings › Privacy & Security), pick it as the run destination with the **Moonlight** scheme and press Run (⌘R).
4. Apple TV: on the TV open Settings › Remotes and Devices › Remote App and Devices; in Xcode, Window › Devices and
   Simulators, pair with the code it shows. Pick the **Moonlight TV** scheme and the Apple TV, then Run.

The simulators can reach Moonlight on your network too, which is handy for trying layouts (resize an iPad simulator
window with Stage Manager to see the breakpoints).

CI builds both apps for their simulators on every pull request (`.github/workflows/ci.yml`, job `apple`).

## Project layout

- `Shared/`: in both targets. `Core/` is the API client (mirrors `API.md`), live updates, Bonjour discovery, Keychain
  and household-timezone dates. `Components/` has the palette (from `frontend/src/styles.css`, light and dark),
  avatars, star badges, progress rings, event colours and the logo.
- `iOS/`: the iPhone/iPad screens (`Screens/`), the width-based layout helpers and editors (`Components/`), Siri
  (`Siri/`: App Intents and App Shortcuts), notifications (`Reminders/`), icon.
- `iOS/Recipes/`: the recipe box, recipe page, editor, importing and on-device text reading, cook mode, kitchen
  timers and their notifications.
- `Cooking/`: the Live Activity's data, in the app and the `CookingWidget` extension; `CookingWidget/` draws it.
- `TV/`: the Apple TV screens, focus styles, layered icon and Top Shelf images.
- Folders are synchronized groups, so new Swift files are picked up without editing the project.
- Icons are drawn by `tools/make_icons.py` (`python3 apple/tools/make_icons.py`, needs Pillow).
