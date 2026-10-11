"""moonlight.add_chore, moonlight.complete_chore, moonlight.award_stars, moonlight.add_list_item."""
from __future__ import annotations

from datetime import date
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.util import dt as dt_util

from .api import MoonlightApiError, MoonlightError
from .const import (
    ATTR_CHORE, ATTR_CONFIG_ENTRY_ID, ATTR_DATE, ATTR_DUE, ATTR_EMOJI, ATTR_ITEM, ATTR_LIST, ATTR_PERSON, ATTR_PIN,
    ATTR_POINTS, ATTR_REASON, ATTR_STARS, ATTR_TIME_OF_DAY, ATTR_TITLE, DOMAIN, SERVICE_ADD_CHORE,
    SERVICE_ADD_LIST_ITEM, SERVICE_AWARD_STARS, SERVICE_COMPLETE_CHORE,
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

    hass.services.async_register(DOMAIN, SERVICE_ADD_CHORE, add_chore,
                                 schema=ADD_CHORE_SCHEMA, supports_response=SupportsResponse.OPTIONAL)
    hass.services.async_register(DOMAIN, SERVICE_COMPLETE_CHORE, complete_chore,
                                 schema=COMPLETE_CHORE_SCHEMA, supports_response=SupportsResponse.OPTIONAL)
    hass.services.async_register(DOMAIN, SERVICE_AWARD_STARS, award_stars,
                                 schema=AWARD_STARS_SCHEMA, supports_response=SupportsResponse.OPTIONAL)
    hass.services.async_register(DOMAIN, SERVICE_ADD_LIST_ITEM, add_list_item,
                                 schema=ADD_LIST_ITEM_SCHEMA, supports_response=SupportsResponse.OPTIONAL)
