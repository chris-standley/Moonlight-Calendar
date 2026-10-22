"""moonlight.add_chore, complete_chore, award_stars, add_list_item, and notifications and timers on the screens:
show_notification, start_timer, clear_notifications."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.util import dt as dt_util

from .api import MoonlightApiError, MoonlightError
from .const import (
    ATTR_CHIME, ATTR_CHORE, ATTR_CONFIG_ENTRY_ID, ATTR_COUNT_UP, ATTR_DATE, ATTR_DESCRIPTION, ATTR_DISMISSIBLE, ATTR_DUE,
    ATTR_DURATION, ATTR_EMOJI, ATTR_FINISHED_FOR, ATTR_ICON, ATTR_ID, ATTR_IMAGE, ATTR_ITEM, ATTR_LABEL, ATTR_LIST,
    ATTR_MESSAGE, ATTR_PERSON, ATTR_PIN, ATTR_POINTS, ATTR_REASON, ATTR_SCREENS, ATTR_SINCE, ATTR_STARS, ATTR_STYLE,
    ATTR_TIME_OF_DAY, ATTR_TITLE, ATTR_UNTIL, DOMAIN, SERVICE_ADD_CHORE, SERVICE_ADD_LIST_ITEM, SERVICE_AWARD_STARS,
    SERVICE_CLEAR_NOTIFICATIONS, SERVICE_COMPLETE_CHORE, SERVICE_SHOW_NOTIFICATION, SERVICE_START_TIMER,
)
from .coordinator import MoonlightCoordinator
from .model import due_param, open_once_chore, resolve_chore, resolve_list, resolve_person

BASE = {vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string}

ADD_CHORE_SCHEMA = vol.Schema({
    **BASE,
    vol.Required(ATTR_PERSON): vol.All(cv.ensure_list, [cv.string]),
    vol.Required(ATTR_TITLE): cv.string,
    vol.Optional(ATTR_EMOJI, default=""): cv.string,
    vol.Optional(ATTR_POINTS, default=0): vol.All(vol.Coerce(int), vol.Range(min=0, max=100)),
    vol.Optional(ATTR_TIME_OF_DAY, default="anytime"): vol.In(["morning", "afternoon", "evening", "anytime"]),
    vol.Optional(ATTR_DATE): cv.date,
})
COMPLETE_CHORE_SCHEMA = vol.Schema({
    **BASE,
    vol.Required(ATTR_PERSON): cv.string,
    vol.Required(ATTR_CHORE): cv.string,
    vol.Optional(ATTR_DATE): cv.date,
})
AWARD_STARS_SCHEMA = vol.Schema({
    **BASE,
    vol.Required(ATTR_PERSON): cv.string,
    vol.Required(ATTR_STARS): vol.All(vol.Coerce(int), vol.NotIn([0], msg="stars must not be 0")),
    vol.Optional(ATTR_REASON, default="From Home Assistant"): cv.string,
    vol.Optional(ATTR_PIN): vol.Coerce(str),
})
ADD_LIST_ITEM_SCHEMA = vol.Schema({
    **BASE,
    vol.Required(ATTR_LIST): cv.string,
    vol.Required(ATTR_ITEM): cv.string,
    vol.Optional(ATTR_DUE): cv.date,
})
# Notifications and timers. `screens`: "all" (default), screen names, or styles (large, compact, phone, app).
SCREENS = vol.All(cv.ensure_list, [cv.string])
STYLE = vol.In(["fullscreen", "toast"])
SHOW_NOTIFICATION_SCHEMA = vol.Schema({
    **BASE,
    vol.Optional(ATTR_TITLE, default=""): cv.string,
    vol.Optional(ATTR_MESSAGE, default=""): cv.string,
    vol.Optional(ATTR_SCREENS): SCREENS,
    vol.Optional(ATTR_STYLE, default="fullscreen"): STYLE,
    vol.Optional(ATTR_DURATION): cv.time_period,  # left out: a toast goes after 10 s, full screen stays; 0 = stays
    vol.Optional(ATTR_ICON, default=""): cv.string,
    vol.Optional(ATTR_IMAGE): cv.string,
    vol.Optional(ATTR_DISMISSIBLE, default=True): cv.boolean,
    vol.Optional(ATTR_CHIME, default=False): cv.boolean,
    vol.Optional(ATTR_ID): cv.string,
})
# Counts down from `duration` or to `until`, or counts up (`count_up`, from `since` or now; then `duration` is how long
# after that it goes).
START_TIMER_SCHEMA = vol.Schema({
    **BASE,
    vol.Required(ATTR_LABEL): cv.string,
    vol.Optional(ATTR_DESCRIPTION, default=""): cv.string,
    vol.Optional(ATTR_DURATION): cv.positive_time_period,
    vol.Optional(ATTR_UNTIL): cv.datetime,
    vol.Optional(ATTR_COUNT_UP, default=False): cv.boolean,
    vol.Optional(ATTR_SINCE): cv.datetime,
    vol.Optional(ATTR_SCREENS): SCREENS,
    vol.Optional(ATTR_STYLE, default="toast"): STYLE,
    vol.Optional(ATTR_FINISHED_FOR): cv.time_period,  # left out or 0: "Time's up" stays until dismissed or cleared
    vol.Optional(ATTR_ICON, default=""): cv.string,
    vol.Optional(ATTR_DISMISSIBLE, default=True): cv.boolean,
    vol.Optional(ATTR_CHIME): cv.boolean,  # left out: on for counting down, off for counting up
    vol.Optional(ATTR_ID): cv.string,
})
CLEAR_NOTIFICATIONS_SCHEMA = vol.Schema({
    **BASE,
    vol.Optional(ATTR_ID): vol.All(cv.ensure_list, [cv.string]),
    vol.Optional(ATTR_SCREENS): SCREENS,
})


def _seconds(value: timedelta) -> int:
    return max(0, round(value.total_seconds()))


def _local(when: datetime) -> datetime:
    """A time without a zone is Home Assistant's local time."""
    return when if when.tzinfo else when.replace(tzinfo=dt_util.get_default_time_zone())


def _optional(data: dict, *keys: str) -> dict[str, Any]:
    return {k: data[k] for k in keys if data.get(k) not in (None, "")}


def _coordinator(hass: HomeAssistant, call: ServiceCall) -> MoonlightCoordinator:
    entries = [e for e in hass.config_entries.async_entries(DOMAIN) if e.state is ConfigEntryState.LOADED]
    wanted = call.data.get(ATTR_CONFIG_ENTRY_ID)
    if wanted:
        entries = [e for e in entries if e.entry_id == wanted]
    if not entries:
        raise ServiceValidationError("Moonlight is not set up (or that config entry is not loaded)")
    return entries[0].runtime_data


def _api_error(err: MoonlightError) -> HomeAssistantError:
    if isinstance(err, MoonlightApiError) and err.status == 403:
        return ServiceValidationError("Wrong Moonlight PIN")
    if isinstance(err, MoonlightApiError) and err.status in (400, 404):
        return ServiceValidationError(f"Moonlight said: {err.detail}")
    return HomeAssistantError(f"Couldn't reach Moonlight: {err}")


@callback
def async_setup_services(hass: HomeAssistant) -> None:

    async def add_chore(call: ServiceCall) -> ServiceResponse:
        """A one-off chore for a day (default today). An unfinished one with the same title is reused."""
        coordinator = _coordinator(hass, call)
        client = coordinator.client
        day: date = call.data.get(ATTR_DATE) or dt_util.now().date()
        added, kept = [], []
        try:
            people = await client.people()
            targets = [resolve_person(people, ref) for ref in call.data[ATTR_PERSON]]
            due = await client.chores(day.isoformat())
            for person in {p["id"]: p for p in targets}.values():
                if (same := open_once_chore(due, person["id"], call.data[ATTR_TITLE])):
                    kept.append(same)
                    continue
                added.append(await client.add_chore({
                    "title": call.data[ATTR_TITLE], "emoji": call.data[ATTR_EMOJI], "person_id": person["id"],
                    "points": call.data[ATTR_POINTS], "time_of_day": call.data[ATTR_TIME_OF_DAY],
                    "schedule": {"type": "once", "date": day.isoformat()}}))
        except LookupError as err:
            raise ServiceValidationError(str(err)) from err
        except MoonlightError as err:
            raise _api_error(err) from err
        await coordinator.async_request_refresh()
        if not call.return_response:
            return None
        names = {p["id"]: p["name"] for p in people}
        return {"date": day.isoformat(),
                "added": [{"id": c["id"], "person": names.get(c["person_id"])} for c in added],
                "already_there": [{"id": c["id"], "person": names.get(c["person_id"])} for c in kept]}

    async def complete_chore(call: ServiceCall) -> ServiceResponse:
        coordinator = _coordinator(hass, call)
        client = coordinator.client
        day: date = call.data.get(ATTR_DATE) or dt_util.now().date()
        try:
            person = resolve_person(await client.people(), call.data[ATTR_PERSON])
            chore = resolve_chore(await client.chores(day.isoformat()), person["id"], call.data[ATTR_CHORE])
            result = await client.complete_chore(chore["id"], day.isoformat())
        except LookupError as err:
            raise ServiceValidationError(str(err)) from err
        except MoonlightError as err:
            raise _api_error(err) from err
        await coordinator.async_request_refresh()
        if not call.return_response:
            return None
        return {"person": person["name"], "chore": chore["title"], "date": day.isoformat(),
                "balance": result.get("balance")}

    async def award_stars(call: ServiceCall) -> ServiceResponse:
        coordinator = _coordinator(hass, call)
        client = coordinator.client
        try:
            person = resolve_person(await client.people(), call.data[ATTR_PERSON])
            result = await client.adjust_points(person["id"], call.data[ATTR_STARS], call.data[ATTR_REASON],
                                                call.data.get(ATTR_PIN))
        except LookupError as err:
            raise ServiceValidationError(str(err)) from err
        except MoonlightError as err:
            raise _api_error(err) from err
        await coordinator.async_request_refresh()
        if not call.return_response:
            return None
        return {"person": person["name"], "balance": result.get("balance")}

    async def add_list_item(call: ServiceCall) -> ServiceResponse:
        coordinator = _coordinator(hass, call)
        client = coordinator.client
        try:
            lst = resolve_list(await client.lists(), call.data[ATTR_LIST])
            item: dict[str, Any] = await client.add_item(lst["id"], call.data[ATTR_ITEM],
                                                         due_param(call.data.get(ATTR_DUE)))
        except LookupError as err:
            raise ServiceValidationError(str(err)) from err
        except MoonlightError as err:
            raise _api_error(err) from err
        await coordinator.async_request_refresh()
        if not call.return_response:
            return None
        return {"list": lst["name"], "item": item}

    async def put_up(call: ServiceCall, alert: dict[str, Any]) -> ServiceResponse:
        coordinator = _coordinator(hass, call)
        try:
            made = await coordinator.client.add_alert(alert)
        except MoonlightError as err:
            raise _api_error(err) from err
        if not call.return_response:
            return None
        return {"id": made["id"], "screens": made["screens"], "expires_at": made.get("expires_at"),
                "ends_at": made.get("ends_at")}

    async def show_notification(call: ServiceCall) -> ServiceResponse:
        """Full screen or a toast, on every screen or chosen ones, for a while or until dismissed or cleared."""
        d = call.data
        if not d[ATTR_TITLE] and not d[ATTR_MESSAGE]:
            raise ServiceValidationError("Give the notification a title or a message")
        alert: dict[str, Any] = {
            "kind": "notification", "title": d[ATTR_TITLE], "message": d[ATTR_MESSAGE], "style": d[ATTR_STYLE],
            "icon": d[ATTR_ICON], "dismissible": d[ATTR_DISMISSIBLE], "chime": d[ATTR_CHIME],
            **_optional(d, ATTR_SCREENS, ATTR_IMAGE, ATTR_ID),
        }
        if ATTR_DURATION in d:
            alert["duration"] = _seconds(d[ATTR_DURATION])
        return await put_up(call, alert)

    async def start_timer(call: ServiceCall) -> ServiceResponse:
        """A timer for a duration, a countdown to a date and time, or one counting up from a moment (how long since
        the kettle boiled), with a label (and a description)."""
        d = call.data
        count_up = d[ATTR_COUNT_UP] or ATTR_SINCE in d
        if count_up and ATTR_UNTIL in d:
            raise ServiceValidationError("A timer counts down to until or up from since, not both")
        if not count_up and (ATTR_DURATION in d) == (ATTR_UNTIL in d):
            raise ServiceValidationError("Give the timer a duration or an until (or count up)")
        alert: dict[str, Any] = {
            "kind": "timer", "label": d[ATTR_LABEL], "description": d[ATTR_DESCRIPTION], "style": d[ATTR_STYLE],
            "icon": d[ATTR_ICON], "dismissible": d[ATTR_DISMISSIBLE],
            **_optional(d, ATTR_SCREENS, ATTR_ID),
        }
        # Counting up has nothing to get to, so it only chimes (when it appears) if asked.
        alert["chime"] = d[ATTR_CHIME] if ATTR_CHIME in d else not count_up
        if count_up:
            alert["since"] = _local(d[ATTR_SINCE]).isoformat() if ATTR_SINCE in d else "now"
        if ATTR_DURATION in d:
            alert["duration"] = _seconds(d[ATTR_DURATION])
        elif not count_up:
            alert["until"] = _local(d[ATTR_UNTIL]).isoformat()
        if ATTR_FINISHED_FOR in d:
            alert["finished_for"] = _seconds(d[ATTR_FINISHED_FOR])
        return await put_up(call, alert)

    async def clear_notifications(call: ServiceCall) -> ServiceResponse:
        """By id, or everything shown on some screens, or (with neither) everything."""
        client = _coordinator(hass, call).client
        cleared: list[str] = []
        try:
            if call.data.get(ATTR_ID):
                for alert_id in call.data[ATTR_ID]:
                    try:
                        await client.clear_alert(alert_id)
                        cleared.append(alert_id)
                    except MoonlightApiError as err:
                        if err.status != 404:  # already gone (dismissed, or its time was up) is fine
                            raise
            else:
                cleared = await client.clear_alerts(call.data.get(ATTR_SCREENS))
        except MoonlightError as err:
            raise _api_error(err) from err
        return {"cleared": cleared} if call.return_response else None

    hass.services.async_register(DOMAIN, SERVICE_SHOW_NOTIFICATION, show_notification,
                                 schema=SHOW_NOTIFICATION_SCHEMA, supports_response=SupportsResponse.OPTIONAL)
    hass.services.async_register(DOMAIN, SERVICE_START_TIMER, start_timer,
                                 schema=START_TIMER_SCHEMA, supports_response=SupportsResponse.OPTIONAL)
    hass.services.async_register(DOMAIN, SERVICE_CLEAR_NOTIFICATIONS, clear_notifications,
                                 schema=CLEAR_NOTIFICATIONS_SCHEMA, supports_response=SupportsResponse.OPTIONAL)
    hass.services.async_register(DOMAIN, SERVICE_ADD_CHORE, add_chore,
                                 schema=ADD_CHORE_SCHEMA, supports_response=SupportsResponse.OPTIONAL)
    hass.services.async_register(DOMAIN, SERVICE_COMPLETE_CHORE, complete_chore,
                                 schema=COMPLETE_CHORE_SCHEMA, supports_response=SupportsResponse.OPTIONAL)
    hass.services.async_register(DOMAIN, SERVICE_AWARD_STARS, award_stars,
                                 schema=AWARD_STARS_SCHEMA, supports_response=SupportsResponse.OPTIONAL)
    hass.services.async_register(DOMAIN, SERVICE_ADD_LIST_ITEM, add_list_item,
                                 schema=ADD_LIST_ITEM_SCHEMA, supports_response=SupportsResponse.OPTIONAL)
