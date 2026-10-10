"""Moonlight family calendar: people, chores, stars, lists, meals and events as Home Assistant entities."""
from __future__ import annotations

from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import MoonlightClient
from .const import CONF_TOKEN, DOMAIN
from .coordinator import MoonlightConfigEntry, MoonlightCoordinator
from .services import async_setup_services

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.CALENDAR,
    Platform.SENSOR,
    Platform.TODO,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the moonlight.* services once, independent of config entries."""
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: MoonlightConfigEntry) -> bool:
    session = async_get_clientsession(hass)
    client = MoonlightClient(session, entry.data[CONF_HOST], entry.data[CONF_PORT], entry.data.get(CONF_TOKEN))
    coordinator = MoonlightCoordinator(hass, entry, client, session)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Cancelled automatically when the entry unloads.
    entry.async_create_background_task(hass, coordinator.async_listen(), f"{DOMAIN} websocket")
    return True


async def async_unload_entry(hass: HomeAssistant, entry: MoonlightConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
