# Moonlight for Home Assistant

A custom integration that brings your [Moonlight](https://github.com/chris-standley/Moonlight-Calendar) family
wall calendar into Home Assistant: stars, chores, tonight's dinner, the next event, every list as a to-do
entity and a calendar per person, plus services to add and tick off chores, award stars, add list items, and put
notifications and timers on the screens.

It talks to Moonlight's local HTTP API (port 8091), polls every 60 seconds and also listens to Moonlight's
WebSocket, so a chore ticked off on the wall shows up in HA within a second or two.

## Install

1. HACS -> the three-dot menu -> **Custom repositories** -> add
   `https://github.com/chris-standley/Moonlight-Calendar`, category **Integration**.
2. Install **Moonlight** from HACS and restart Home Assistant.
3. **With the Moonlight add-on:** Settings -> Devices & services shows **Moonlight** under *Discovered*. Select
   **Configure** and submit. The add-on announced itself with its address and a token it made for Home Assistant,
   so there is no code to enter. It appears in Moonlight under **Settings > Screens > Connections**, where it can be
   disconnected; restarting the add-on afterwards offers it again.
4. **Without the add-on** (Moonlight running elsewhere): **Add integration -> Moonlight**, enter its host and port
   (`8091`). Setup checks `GET /api/health`. If Moonlight requires pairing, the next step shows a 6-digit code: enter
   it in Moonlight under **Settings > Screens > Pair** with the parent PIN, then select **Submit**. If the
   token stops working, the integration asks you to re-authenticate and shows a new code. You can change host/port
   later with **Reconfigure**. A manual entry for the add-on's own address is adopted when the add-on announces itself.

The add-on itself can also show HA weather on the displays: pick an entity in Moonlight's Settings > Display > Weather.

## Entities

All entities belong to one device, **Moonlight**. Entity ids below use the demo family (Mia and Leo are
children, Alex and Jordan adults); yours follow your people's and lists' names. New people and lists appear
automatically; deleted ones become unavailable.

| Entity | Per | State | Attributes |
|---|---|---|---|
| `sensor.moonlight_mia_stars` | child | Star balance (`state_class: measurement`, unit `stars`) | |
| `sensor.moonlight_mia_chores_left` | person | Chores still to do today | `remaining` (titles), `total`, `done` |
| `sensor.moonlight_mia_chores_done` | person | Chores done today | |
| `binary_sensor.moonlight_mia_all_chores_done` | child | `on` when every chore due today is done (also `on` if none are due) | `remaining`, `total`, `done` |
| `sensor.moonlight_tonight_s_dinner` | - | Tonight's dinner, or `Nothing planned` | `date`, `notes` |
| `sensor.moonlight_next_event` | - | Title of the next event to start | `start`, `end`, `all_day`, `people`, `location` |
| `todo.moonlight_groceries` | list | Open items | Add, rename, complete, set due date, delete |
| `calendar.moonlight_mia` | person | `on` during an event | Current or next event; full history/agenda via the calendar panel |

Calendar times are Moonlight's household-local times interpreted in Home Assistant's configured time zone.

## Services

These four accept a person or list by **name or id** (case-insensitive; first name works if unique; emoji in
list names can be left out) and an optional `config_entry_id` if you run more than one Moonlight. Each can
return a response (`response_variable`).

```yaml
# Add a one-off chore for today (or `date`). `person` can be a list; each gets their own. If the same chore is
# already waiting for that person that day (title compared without emoji or case), it isn't added again, so an
# automation that fires twice adds it once. Once it's done, a later call adds a new one.
action: moonlight.add_chore
data:
  person: Chris
  title: Empty the dishwasher
  emoji: "🍽️"            # optional
  points: 0               # optional stars, default 0
  time_of_day: anytime    # morning | afternoon | evening | anytime
  # date: "2026-10-10"   # optional, defaults to today

# Tick off a chore (stars are awarded as on the wall). If two chores share a title, e.g. morning and evening
# "Brush teeth", the next one not yet done is ticked.
action: moonlight.complete_chore
data:
  person: Mia
  chore: Make bed
  # date: "2026-10-10"   # optional, defaults to today

# Award (or with a negative number, take away) stars. `pin` is Moonlight's parent PIN, if one is set.
action: moonlight.award_stars
data:
  person: Leo
  stars: 5
  reason: Helped carry the shopping
  pin: !secret moonlight_pin

# Add to a list
action: moonlight.add_list_item
data:
  list: Groceries
  item: Oat milk
```

## Notifications and timers on the screens

`moonlight.show_notification` and `moonlight.start_timer` put something on Moonlight's screens and in the iPhone,
iPad and Apple TV apps. `screens` picks where: `all` (the default), screen names as in Moonlight's Settings > Screens
(any case), or a style: `large`, `compact`, `phone`, or `app` (the iPhone and iPad apps). A name Moonlight doesn't
know is an error that lists the screens it has. `style` is `fullscreen` or `toast` (a card in the top corner).

Each stays for its `duration` / `finished_for`, or with none until someone taps it away on a screen (gone from every
screen) or `moonlight.clear_notifications` clears it. `dismissible: false` leaves it to Home Assistant alone. Give it
an `id` to replace or clear it later; the response (`response_variable`) has the id either way.

```yaml
# Full screen on every screen until someone taps Dismiss (a full screen one stays unless given a duration).
action: moonlight.show_notification
data:
  title: Dinner's ready
  message: Come to the table, everyone
  icon: "🍝"
  chime: true

# A toast on the kitchen screen for 30 seconds (a toast with no duration goes after 10 seconds).
action: moonlight.show_notification
data:
  title: Washing machine finished
  icon: "🧺"
  screens: Kitchen
  style: toast
  duration: "00:00:30"

# Until Home Assistant clears it, and no one can tap it away; `image` is any picture the screens can open.
action: moonlight.show_notification
data:
  id: back_door
  title: Back door is open
  screens: [large, compact]
  dismissible: false

# A labelled timer: a toast that counts down, chimes at zero and says Time's up until it's dismissed.
action: moonlight.start_timer
data:
  label: Pizza
  description: Take it out of the oven
  icon: "🍕"
  duration: "00:12:00"
  screens: Kitchen

# A full screen countdown to a date and time (Home Assistant's time zone), on the hallway screen.
action: moonlight.start_timer
data:
  label: Holiday!
  description: Off to Cornwall
  until: "2027-07-24 08:00:00"
  style: fullscreen
  screens: Hallway

# Take one off, or everything on some screens, or (with neither) everything.
action: moonlight.clear_notifications
data:
  id: back_door
```

Starting a timer with the same `id` again restarts it. `finished_for` sets how long Time's up stays once a timer
gets to zero. A full screen timer has a Make small button that turns it into a corner card on that screen only.

Two things come back as the event `moonlight_alert`, with `event`, `id`, `kind` (`notification` or `timer`),
`title` (the title or label), `screen` and `config_entry_id`:

- `event: finished`: a timer got to zero.
- `event: dismissed`: someone tapped one away; `screen` is that screen's name.

The `todo.*` entities also work with HA's own `todo.add_item`, `todo.update_item`, `todo.remove_item` and
with Assist ("add milk to my groceries").

## Example automations

Tell everyone the back door is open, and take it away when it shuts:

```yaml
alias: Moonlight - back door open
triggers:
  - trigger: state
    entity_id: binary_sensor.back_door
    to: "on"
    for: "00:02:00"
    id: open
  - trigger: state
    entity_id: binary_sensor.back_door
    to: "off"
    id: closed
actions:
  - choose:
      - conditions:
          - condition: trigger
            id: open
        sequence:
          - action: moonlight.show_notification
            data:
              id: back_door
              title: The back door is open
              icon: "🚪"
              style: toast
              duration: 0
    default:
      - action: moonlight.clear_notifications
        data:
          id: back_door
```

Say it out loud when a timer finishes:

```yaml
alias: Moonlight - timer finished
triggers:
  - trigger: event
    event_type: moonlight_alert
    event_data:
      event: finished
actions:
  - action: tts.speak
    target:
      entity_id: tts.home_assistant_cloud
    data:
      media_player_entity_id: media_player.kitchen
      message: "{{ trigger.event.data.title }} timer is done"
```

Put the bins out the night before collection. Add the bin calendar to Moonlight first (Settings > Calendars >
Home Assistant, pick everyone) so collection day shows on the shared calendar; this adds the chore at 7pm the
evening before. A calendar trigger with a negative offset fires that long before each all-day event starts at
midnight. Use your own calendar entity:

```yaml
alias: Moonlight - bins out the night before
triggers:
  - trigger: calendar
    event: start
    entity_id: calendar.bins
    offset: "-5:00:00"
actions:
  - action: moonlight.add_chore
    data:
      person: Chris
      title: "Put the bins out: {{ trigger.calendar_event.summary }}"
      emoji: "🗑️"
      time_of_day: evening
```

Add a chore when the washing machine or dishwasher finishes. Use whichever entity and state your appliance
reports when it is done (a status sensor going to "finished", or a power-based binary sensor going "off"):

```yaml
alias: Moonlight - appliance finished
triggers:
  - trigger: state
    entity_id: sensor.washing_machine_status
    to: finished
    id: washer
  - trigger: state
    entity_id: sensor.dishwasher_status
    to: finished
    id: dishwasher
actions:
  - action: moonlight.add_chore
    data:
      person: Chris
      title: "{{ 'Hang out the washing' if trigger.id == 'washer' else 'Empty the dishwasher' }}"
      emoji: "{{ '🧺' if trigger.id == 'washer' else '🍽️' }}"

Announce when a child finishes all their chores:

```yaml
alias: Moonlight - chores done announcement
triggers:
  - trigger: state
    entity_id:
      - binary_sensor.moonlight_mia_all_chores_done
      - binary_sensor.moonlight_leo_all_chores_done
    from: "off"
    to: "on"
actions:
  - action: tts.speak
    target:
      entity_id: tts.home_assistant_cloud
    data:
      media_player_entity_id: media_player.kitchen_speaker
      message: >
        Well done {{ trigger.to_state.attributes.friendly_name.split(' ')[1] }},
        all your chores are done!
```

(`friendly_name` is e.g. "Moonlight Mia all chores done", so word 2 is the name.)

Nudge parents' phones at 6pm if chores remain:

```yaml
alias: Moonlight - chores reminder
triggers:
  - trigger: time
    at: "18:00:00"
conditions:
  - condition: template
    value_template: >
      {{ states('sensor.moonlight_mia_chores_left') | int(0) > 0
         or states('sensor.moonlight_leo_chores_left') | int(0) > 0 }}
actions:
  - action: notify.notify          # or notify.mobile_app_<your_phone>
    data:
      title: Chores left today
      message: >
        Mia: {{ state_attr('sensor.moonlight_mia_chores_left', 'remaining') | join(', ') or 'all done' }}.
        Leo: {{ state_attr('sensor.moonlight_leo_chores_left', 'remaining') | join(', ') or 'all done' }}.
```

Wake the TouchKio hallway display on motion (TouchKio publishes the screen to HA over MQTT as a light/switch
entity; use your own entity ids):

```yaml
alias: Moonlight - hallway display on with motion
mode: restart
triggers:
  - trigger: state
    entity_id: binary_sensor.hallway_motion
    to: "on"
actions:
  - action: homeassistant.turn_on
    target:
      entity_id: light.touchkio_hallway_display
  - wait_for_trigger:
      - trigger: state
        entity_id: binary_sensor.hallway_motion
        to: "off"
        for: "00:05:00"
  - action: homeassistant.turn_off
    target:
      entity_id: light.touchkio_hallway_display
```

## Development

- `model.py` has all parsing/mapping logic and no Home Assistant imports; its tests run anywhere:
  `python3 -m pytest -q -p no:cacheprovider tests` (repo root).
- `tests/ha/` runs the integration inside a real test Home Assistant against a real Moonlight backend
  (config flow, pairing and reauth, entities, WebSocket push, services, to-do and calendar):
  `python3 -m venv .venv-ha && .venv-ha/bin/pip install pytest-homeassistant-custom-component`, then
  `.venv-ha/bin/python -m pytest -q -p no:cacheprovider tests/ha` (the backend is started with the system
  `python3`, which needs `backend/requirements.txt` installed; override with `MOONLIGHT_PYTHON`).
