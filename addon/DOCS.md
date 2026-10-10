# Moonlight

## Install

1. Settings > Add-ons > Add-on Store > ⋮ (top right) > Repositories, add
   `https://github.com/chris-standley/Moonlight-Calendar` and close the dialog.
2. Find **Moonlight** in the store (⋮ > Check for updates if it is not listed yet) and click **Install**.
   Home Assistant downloads the prebuilt image for your machine (amd64 or aarch64) from GitHub's container registry.
3. Set the options below, **Start**, and turn on **Show in sidebar**.

New versions show up as an update on the add-on page.

## Options

- `demo` (default `true`): seed the demo family (people, events, chores, lists, meals) into an **empty** database
  on first start. Turn it off before the first start for a blank household; it does nothing once data exists.
- `weather_entity` (optional, e.g. `weather.home`): show that Home Assistant weather entity and its daily forecast.
  Empty = a built-in demo forecast.
- `require_pairing` (default `true`): wall screens on port 8099 must be paired before they can use Moonlight.
  Moonlight in the Home Assistant sidebar is always signed in.

The household timezone defaults to Home Assistant's (Settings > System > General) and can be changed in
Moonlight's Settings.

## Wall screens

On the screen's browser open `http://<ha-host>:8099/display/hallway` (or `kitchen`, `phone`). It shows a 6-digit
code: in Moonlight (sidebar or phone) go to Settings > Screens > Pair a new screen and enter the code and the PIN.
The screen remembers its pairing; revoke it in the same place.

## Calendars

Settings > Calendars > Connect iCloud with an Apple ID and an app-specific password
(account.apple.com > Sign-In and Security > App-Specific Passwords), then choose which person each calendar
belongs to. Moonlight syncs every 2 minutes and writes changes made on the screens back to iCloud.

Settings > Calendars > Add calendar link shows a read-only published calendar (an ICS / webcal link), such
as a work calendar, school term dates or bin days, refreshed every 15 minutes. For an Outlook / Microsoft 365
work calendar: Outlook on the web > Settings > Calendar > Shared calendars > Publish a calendar, choose
"Can view when I'm busy" and copy the ICS link; its events show as "busy" blocks. Some workplaces block
publishing. Treat the link like a password.

## Data

The database is `/data/moonlight.db` and uploaded photos are in `/data/photos`; both are part of the add-on's
backups and survive updates and restarts.
