"""Small async client for the Moonlight HTTP API (aiohttp; no Home Assistant imports)."""
from __future__ import annotations

import asyncio
from typing import Any

import aiohttp

from .model import (PAIR_LAYOUT, PAIR_NAME, auth_headers, base_url, health_version, parse_pair_poll,
                    parse_pair_start, ws_url)

TIMEOUT = aiohttp.ClientTimeout(total=15)


class MoonlightError(Exception):
    """Base error."""


class MoonlightConnectionError(MoonlightError):
    """Moonlight could not be reached."""


class MoonlightApiError(MoonlightError):
    """Moonlight answered with an error status."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(f"{status}: {detail}")
        self.status = status
        self.detail = detail


class MoonlightClient:
    """`token` is the display token Moonlight handed out when Home Assistant was paired (None if not needed)."""

    def __init__(self, session: aiohttp.ClientSession, host: str, port: int, token: str | None = None) -> None:
        self._session = session
        self.base = base_url(host, port)
        self.ws_url = ws_url(self.base)
        self.token = token or None

    @property
    def headers(self) -> dict[str, str]:
        """Sent with every HTTP request and the WebSocket handshake."""
        return auth_headers(self.token)

    async def _req(self, method: str, path: str, *, json: Any = None, params: dict | list | None = None) -> Any:
        try:
            async with self._session.request(method, self.base + path, json=json, params=params,
                                             headers=self.headers, timeout=TIMEOUT) as resp:
                if resp.status >= 400:
                    try:
                        detail = (await resp.json(content_type=None)).get("detail") or resp.reason
                    except (ValueError, AttributeError, aiohttp.ContentTypeError):
                        detail = resp.reason or "error"
                    raise MoonlightApiError(resp.status, str(detail))
                return await resp.json(content_type=None)
        except MoonlightApiError:
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as err:
            raise MoonlightConnectionError(str(err) or type(err).__name__) from err

    async def health(self) -> str:
        try:
            return health_version(await self._req("GET", "/api/health"))
        except ValueError as err:
            raise MoonlightError(str(err)) from err

    async def auth_status(self) -> dict | None:
        """GET /api/auth/status, or None on a Moonlight from before pairing existed (404)."""
        try:
            raw = await self._req("GET", "/api/auth/status")
        except MoonlightApiError as err:
            if err.status == 404:
                return None
            raise
        return raw if isinstance(raw, dict) else None

    async def pair_start(self, name: str = PAIR_NAME) -> tuple[str, str]:
        """Ask Moonlight for a pairing code. Returns (pair_id, 6-digit code)."""
        try:
            return parse_pair_start(await self._req("POST", "/api/pair/start",
                                                    json={"layout": PAIR_LAYOUT, "name": name}))
        except ValueError as err:
            raise MoonlightError(str(err)) from err

    async def pair_poll(self, pair_id: str) -> tuple[str, str | None]:
        """("approved", token) once the code was entered in Moonlight, else ("pending"|"expired", None)."""
        try:
            return parse_pair_poll(await self._req("GET", f"/api/pair/{pair_id}"))
        except ValueError as err:
            raise MoonlightError(str(err)) from err

    async def summary(self) -> Any:
        return await self._req("GET", "/api/summary")

    async def people(self) -> list[dict]:
        return await self._req("GET", "/api/people")

    async def lists(self) -> list[dict]:
        return await self._req("GET", "/api/lists")

    async def events(self, start: str, end: str) -> list[dict]:
        return await self._req("GET", "/api/events", params={"start": start, "end": end})

    async def chores(self, day: str) -> list[dict]:
        return await self._req("GET", "/api/chores", params={"date": day})

    async def add_chore(self, chore: dict) -> dict:
        return await self._req("POST", "/api/chores", json=chore)

    async def complete_chore(self, chore_id: str, day: str) -> dict:
        return await self._req("POST", f"/api/chores/{chore_id}/complete", json={"date": day})

    async def adjust_points(self, person_id: str, change: int, reason: str, pin: str | None) -> dict:
        return await self._req("POST", "/api/points/adjust",
                               json={"person_id": person_id, "change": change, "reason": reason, "pin": pin})

    async def add_item(self, list_id: str, title: str, due: str | None = None) -> dict:
        return await self._req("POST", f"/api/lists/{list_id}/items", json={"title": title, "due": due})

    async def update_item(self, item_id: str, patch: dict) -> dict:
        return await self._req("PATCH", f"/api/items/{item_id}", json=patch)

    async def delete_item(self, item_id: str) -> None:
        await self._req("DELETE", f"/api/items/{item_id}")

    async def add_alert(self, alert: dict) -> dict:
        """A notification or timer on the screens (POST /api/alerts)."""
        return await self._req("POST", "/api/alerts", json=alert)

    async def clear_alert(self, alert_id: str) -> None:
        await self._req("DELETE", f"/api/alerts/{alert_id}")

    async def clear_alerts(self, screens: list[str] | None = None) -> list[str]:
        params = [("screens", s) for s in screens or []]
        return (await self._req("DELETE", "/api/alerts", params=params or None)).get("cleared", [])
