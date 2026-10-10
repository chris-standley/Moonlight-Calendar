"""Config flow: enter Moonlight's host and port (checked with GET /api/health), then pair if Moonlight asks for it.

With the add-on's `require_pairing` on (the default), Moonlight's LAN port only answers paired clients. Home
Assistant then pairs itself like a wall screen: it asks for a 6-digit code (POST /api/pair/start), the user enters
it in Moonlight under Settings > Screens > Pair a new screen (with the parent PIN), and on submit the flow
collects the token (GET /api/pair/{id}) and stores it in the config entry. Reconfigure and reauth (started when
Moonlight answers 401, e.g. after the token was revoked) go through the same pairing step.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import SOURCE_REAUTH, SOURCE_RECONFIGURE, ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import MoonlightApiError, MoonlightClient, MoonlightConnectionError, MoonlightError
from .const import CONF_TOKEN, DEFAULT_HOST, DEFAULT_PORT, DOMAIN, LOGGER
from .model import format_code, needs_pairing

SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST, default=DEFAULT_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): vol.All(vol.Coerce(int), vol.Range(min=1, max=65535)),
    }
)


class MoonlightConfigFlow(ConfigFlow, domain=DOMAIN):
    """Manual setup. The add-on is usually reachable as `local-moonlight` (or the HA host's IP) on 8091."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}  # host + port being set up
        self._pair_id: str | None = None
        self._code: str | None = None

    def _client(self, token: str | None = None) -> MoonlightClient:
        return MoonlightClient(async_get_clientsession(self.hass), self._data[CONF_HOST], self._data[CONF_PORT],
                               token)

    async def _check(self, token: str | None = None) -> tuple[bool, dict[str, str]]:
        """Is self._data a Moonlight, and does it need pairing (given `token`)? Returns (needs_pairing, errors)."""
        client = self._client(token)
        try:
            await client.health()
            status = await client.auth_status()
        except MoonlightConnectionError:
            return False, {"base": "cannot_connect"}
        except MoonlightError:
            return False, {"base": "not_moonlight"}
        except Exception:  # noqa: BLE001 - config flows report unexpected errors as "unknown"
            LOGGER.exception("Unexpected error checking Moonlight")
            return False, {"base": "unknown"}
        return needs_pairing(status), {}

    async def _start_pairing(self) -> dict[str, str]:
        """Get a fresh pairing code; returns errors (empty on success)."""
        try:
            self._pair_id, self._code = await self._client().pair_start()
        except MoonlightConnectionError:
            return {"base": "cannot_connect"}
        except MoonlightApiError as err:
            return {"base": "pair_busy" if err.status == 429 else "pair_failed"}
        except MoonlightError:
            return {"base": "pair_failed"}
        except Exception:  # noqa: BLE001
            LOGGER.exception("Unexpected error starting Moonlight pairing")
            return {"base": "unknown"}
        return {}

    async def _finish(self, token: str | None = None) -> ConfigFlowResult:
        """Create the entry, or update the one being reconfigured / re-authenticated."""
        data = dict(self._data)
        if token:
            data[CONF_TOKEN] = token
        if self.source == SOURCE_REAUTH:
            return self.async_update_reload_and_abort(self._get_reauth_entry(), data_updates=data)
        if self.source == SOURCE_RECONFIGURE:
            return self.async_update_reload_and_abort(self._get_reconfigure_entry(), data_updates=data)
        return self.async_create_entry(title="Moonlight", data=data)

    async def _connect(self, user_input: dict[str, Any],
                       token: str | None = None) -> tuple[ConfigFlowResult | None, dict[str, str]]:
        """Shared by user and reconfigure: check host/port, then finish or go to the pairing step.

        Returns (result, {}) to move on, or (None, errors) to show the form again.
        """
        self._data = {CONF_HOST: str(user_input[CONF_HOST]).strip(), CONF_PORT: int(user_input[CONF_PORT])}
        pair, errors = await self._check(token)
        if errors:
            return None, errors
        if self.source != SOURCE_RECONFIGURE:
            self._async_abort_entries_match(self._data)
        if not pair:
            return await self._finish(), {}
        errors = await self._start_pairing()
        if errors:
            return None, errors
        return await self.async_step_pair(), {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            result, errors = await self._connect(user_input)
            if result is not None:
                return result
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(SCHEMA, user_input),
            errors=errors,
            description_placeholders={"addon_host": DEFAULT_HOST, "port": str(DEFAULT_PORT)},
        )

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            # Keep the existing token if Moonlight still accepts it; pair again only if it doesn't.
            result, errors = await self._connect(user_input, entry.data.get(CONF_TOKEN))
            if result is not None:
                return result
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(SCHEMA, user_input or entry.data),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """Moonlight answered 401: pairing was turned on, or Home Assistant's token was revoked."""
        self._data = {CONF_HOST: entry_data[CONF_HOST], CONF_PORT: entry_data[CONF_PORT]}
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            pair, errors = await self._check(self._get_reauth_entry().data.get(CONF_TOKEN))
            if not errors:
                if not pair:  # e.g. pairing was switched off again: nothing to do but reload
                    return await self._finish()
                errors = await self._start_pairing()
                if not errors:
                    return await self.async_step_pair()
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({}),
            errors=errors,
            description_placeholders={"host": self._data[CONF_HOST]},
        )

    async def async_step_pair(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show the code; on submit, collect the token if the code was approved in Moonlight."""
        errors: dict[str, str] = {}
        if user_input is not None and self._pair_id:
            try:
                status, token = await self._client().pair_poll(self._pair_id)
            except MoonlightConnectionError:
                errors["base"] = "cannot_connect"
            except MoonlightError:
                errors["base"] = "pair_failed"
            except Exception:  # noqa: BLE001
                LOGGER.exception("Unexpected error polling Moonlight pairing")
                errors["base"] = "unknown"
            else:
                if status == "approved":
                    return await self._finish(token)
                if status == "pending":
                    errors["base"] = "not_paired"
                else:  # the code expired (10 minutes): show a new one
                    errors = await self._start_pairing() or {"base": "pair_expired"}
        return self.async_show_form(
            step_id="pair",
            data_schema=vol.Schema({}),
            errors=errors,
            description_placeholders={"code": format_code(self._code or "")},
        )
