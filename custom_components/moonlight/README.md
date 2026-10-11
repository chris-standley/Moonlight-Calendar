# Moonlight for Home Assistant

A custom integration that brings your [Moonlight](https://github.com/chris-standley/Moonlight-Calendar) family
wall calendar into Home Assistant: stars, chores, tonight's dinner, the next event, every list as a to-do
entity and a calendar per person, plus services to add and tick off chores, award stars and add list items.

It talks to Moonlight's local HTTP API (port 8091), polls every 60 seconds and also listens to Moonlight's
WebSocket, so a chore ticked off on the wall shows up in HA within a second or two.

## Install

1. HACS -> the three-dot menu -> **Custom repositories** -> add
   `https://github.com/chris-standley/Moonlight-Calendar`, category **Integration**.
2. Install **Moonlight** from HACS and restart Home Assistant.
3. **Settings -> Devices & services -> Add integration -> Moonlight**, then enter:
   - **Host**: where Moonlight runs. For the Moonlight add-on this is usually `local-moonlight` when the
     add-on was installed from a local add-on folder, `<repo-hash>-moonlight` when installed from an add-on
     repository (shown as *Hostname* on the add-on's Info page), or simply your Home Assistant host's IP address.
   - **Port**: `8091`.

   Setup checks `GET /api/health`. You can change host/port later with **Reconfigure**.
4. **Pairing.** The add-on's LAN port only answers paired clients (add-on option `require_pairing`, on by
   default), so Home Assistant pairs itself like a wall screen: the next step shows a 6-digit code. In Moonlight
   (HA sidebar or a paired screen) go to **Settings > Screens > Pair a new screen**, enter the code and the
   parent PIN, then select **Submit** in Home Assistant. The token is stored in the config entry and sent as
   `Authorization: Bearer` on every request and on the WebSocket. Home Assistant then shows in Moonlight's screen
   list as "Home Assistant" (Integration). If pairing is off, this step is skipped.

   If the token stops working (you revoked Home Assistant in Moonlight, or turned pairing on after setup), the
   integration asks you to **Reconfigure/Re-authenticate** from the notification and shows a new code. Reconfigure
   keeps the existing token if Moonlight still accepts it.

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

All four accept a person or list by **name or id** (case-insensitive; first name works if unique; emoji in
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

The `todo.*` entities also work with HA's own `todo.add_item`, `todo.update_item`, `todo.remove_item` and
with Assist ("add milk to my groceries").

## Example automations

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
