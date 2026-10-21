"""Polls GET /api/summary every 60 s and refreshes at once when Moonlight's WebSocket says something changed."""
from __future__ import annotations

import asyncio

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import MoonlightApiError, MoonlightClient, MoonlightError
from .const import DOMAIN, EVENT_ALERT, LOGGER, SCAN_INTERVAL
from .model import Summary, backoff, is_change_message, parse_alert_event, parse_summary

type MoonlightConfigEntry = ConfigEntry[MoonlightCoordinator]


class MoonlightCoordinator(DataUpdateCoordinator[Summary]):
    config_entry: MoonlightConfigEntry

    def __init__(self, hass: HomeAssistant, entry: MoonlightConfigEntry, client: MoonlightClient,
                 session: aiohttp.ClientSession) -> None:
        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
            # A burst of WebSocket "changed" messages (e.g. completing a chore = chores + points) -> one fetch.
            request_refresh_debouncer=Debouncer(hass, LOGGER, cooldown=1.0, immediate=True),
        )
        self.client = client
        self._session = session
        self.ws_connected = False

    async def _async_update_data(self) -> Summary:
        try:
            raw = await self.client.summary()
        except MoonlightApiError as err:
            if err.status == 401:
                # Pairing is on and our token is missing or was revoked: HA starts a reauth flow (re-pair).
                raise ConfigEntryAuthFailed("Moonlight needs Home Assistant to be paired (again)") from err
            raise UpdateFailed(f"Error talking to Moonlight: {err}") from err
        except MoonlightError as err:
            raise UpdateFailed(f"Error talking to Moonlight: {err}") from err
        try:
            return parse_summary(raw)
        except ValueError as err:
            raise UpdateFailed(str(err)) from err

    async def async_listen(self) -> None:
        """Run forever (cancelled on unload): follow /api/ws, reconnecting with exponential back-off."""
        attempt = 0
        while True:
            try:
                async with self._session.ws_connect(self.client.ws_url, heartbeat=30,
                                                    headers=self.client.headers) as ws:
                    if attempt:
                        LOGGER.info("Reconnected to Moonlight WebSocket")
                        await self.async_request_refresh()  # catch up on anything missed while away
                    attempt = 0
                    self.ws_connected = True
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            if is_change_message(msg.data):
                                await self.async_request_refresh()
                            elif (event := parse_alert_event(msg.data)) is not None:
                                # A timer reached zero, or someone dismissed a notification on a screen.
                                self.hass.bus.async_fire(
                                    EVENT_ALERT, {**event, "config_entry_id": self.config_entry.entry_id})
                        elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                            break
            except asyncio.CancelledError:
                raise
            except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as err:
                LOGGER.debug("Moonlight WebSocket error: %s", err)
            self.ws_connected = False
            delay = backoff(attempt)
            if attempt == 0:
                LOGGER.debug("Moonlight WebSocket closed; retrying in %.0f s (polling continues)", delay)
            attempt += 1
            await asyncio.sleep(delay)
