# Moonlight for Apple TV

A native tvOS app (SwiftUI) that shows the family calendar on the living-room TV, in the same look as the wall
screens. Everything works with the Siri Remote: there is no text entry anywhere.

| Tab | What it shows | What you can do |
|---|---|---|
| Today | Coming up today and tomorrow, today's meals and the week's dinners, each child's chore progress and stars, Now playing | Open an event; play/pause/skip on the speaker |
| Calendar | Week grid (weather, dinner per day) or a two-week schedule | Today / previous / next, show or hide each person, open an event |
| Chores | A column per person, chores by time of day, streaks | Select a chore to tick it off or undo it |
| Rewards | Each child's stars, rewards with progress, recent stars | Redeem a reward (parent PIN on a number pad) |
| Meals | The week's meal plan | Previous / next week |
| Lists | Shopping and to-do lists | Select an item to tick it off |
| Photos | The Immich screensaver photos | Full-screen slideshow with the clock (Play/Pause pauses, left/right skips) |
| Settings | What this Apple TV is paired with | Forget it and pair again |

The remote's Play/Pause button controls this screen's speaker from any tab (Settings › Music in Moonlight). Adding and
editing (events, chores, rewards, list items) stays on the wall screens and phone, where there's a keyboard.

## Pairing

1. Open the app. It finds Moonlight on the home network: Home Assistant announces itself over Bonjour
   (`_home-assistant._tcp`) and the add-on answers on the same host, on port 8091 (the default) or 8099 (before
   0.3.1); `homeassistant.local` is tried too. If nothing is found, or you moved the add-on to another host port
   (add-on › Configuration › Network), **Enter address** picks the IP and port with the remote (swipe up/down on each
   number; it starts from the Apple TV's own network so usually only the last number changes).
2. The TV shows a 6-digit code. On a phone or wall screen open Moonlight › Settings › Screens › Pair a new screen and
   enter it. The TV is paired as a hallway-style screen named "Apple TV" (rename it there if you like).
3. The token is kept in the Apple TV's Keychain. Deleting the screen in Settings › Screens sends the TV back to pairing.

Live updates come over the same WebSocket the wall screens use, so a chore ticked in the kitchen shows on the TV
straight away.

## Build and run (on a Mac)

Needs Xcode 16 or newer (tvOS 18 SDK) and an Apple ID; a free account is enough to run it on your own Apple TV
(the app then needs re-installing every 7 days; a paid developer account lasts a year).

1. `open appletv/Moonlight.xcodeproj`
2. Select the **Moonlight** target › Signing & Capabilities › Team: pick your Apple ID. If Xcode says the bundle id
   is taken, change `io.github.chris-standley.moonlight` to anything unique.
3. Pair the Apple TV with Xcode once: on the TV, Settings › Remotes and Devices › Remote App and Devices; in Xcode,
   Window › Devices and Simulators, select the Apple TV and pair with the code it shows (Mac and TV on the same network).
4. Pick the Apple TV (or an Apple TV simulator) as the run destination and press Run (⌘R).

The simulator can reach Moonlight on your network too, which is handy for trying the layout.

CI builds the app for the tvOS simulator on every pull request (`.github/workflows/ci.yml`, job `appletv`).

## Project layout

- `Moonlight.xcodeproj`: one app target; the `Moonlight/` folder is a synchronized group, so new Swift files are
  picked up without editing the project.
- `Moonlight/Core`: API client (mirrors `API.md`), live updates, Bonjour discovery, Keychain, household-timezone dates.
- `Moonlight/Views`: one file per tab plus setup/pairing. `Moonlight/Components`: theme (colours from
  `frontend/src/styles.css`, light and dark), cards, avatars, focus styles.
- `Moonlight/Assets.xcassets`: the layered app icon and Top Shelf images, drawn by `tools/make_icons.py`
  (`python3 appletv/tools/make_icons.py`, needs Pillow).
