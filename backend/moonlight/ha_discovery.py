"""Announce the add-on to Home Assistant, so the Moonlight integration is offered under Devices & services
("Discovered") and connects with one click instead of pairing with a code.

Inside the add-on (SUPERVISOR_TOKEN set, `discovery: [moonlight]` in config.yaml) startup POSTs
`{service: "moonlight", config: {host, port, token}}` to the Supervisor's /discovery. The host is the add-on's
hostname on HA's internal network, the port the add-on's own (8091), and the token a "service" display token
kept in the settings table (key `ha_discovery_token`, never returned by the API) and listed in Settings > Screens
under Connections as "Home Assistant". If that connection was removed, the next start makes a new token, so the
integration is offered again (it still needs the user's click). MOONLIGHT_HA_DISCOVERY=0 turns this off.
"""
from __future__ import annotations

import asyncio
import logging
import os
import socket

import httpx

from . import auth, db

log = logging.getLogger("moonlight.discovery")

SERVICE = "moonlight"
TOKEN_KEY = "ha_discovery_token"
DISPLAY_NAME = "Home Assistant"
SUPERVISOR = "http://supervisor"
RETRIES = 5

# Tests swap in an httpx.MockTransport and a no-op sleep.
_sleep = asyncio.sleep
transport: httpx.AsyncBaseTransport | None = None


def enabled() -> bool:
    return bool(os.environ.get("SUPERVISOR_TOKEN")) and os.environ.get("MOONLIGHT_HA_DISCOVERY", "1") != "0"


def service_token() -> str:
    """The integration's token: the saved one while its connection is still active, else a new one."""
    with db.connect() as c:
        token = db.get_setting(c, TOKEN_KEY)
        if token and db.row(c, "SELECT id FROM displays WHERE token_hash = ? AND revoked = 0",
                            (auth.hash_token(token),)):
            return token
        token = auth.new_token()
        c.execute("INSERT INTO displays(id, name, layout, token_hash, created_at, last_seen, revoked) "
                  "VALUES(?, ?, 'service', ?, ?, NULL, 0)",
                  (db.new_id("ds"), DISPLAY_NAME, auth.hash_token(token), db.now_iso()))
        db.set_setting(c, TOKEN_KEY, token)
    return token


async def _hostname(client: httpx.AsyncClient) -> str:
    try:
        r = await client.get("/addons/self/info")
        r.raise_for_status()
        host = (r.json().get("data") or {}).get("hostname")
        if host:
            return str(host)
    except (httpx.HTTPError, ValueError):
        log.debug("Couldn't read the add-on's hostname from the Supervisor; using the container's")
    return socket.gethostname()


async def announce(port: int | None = None) -> bool:
    """Tell the Supervisor how to reach Moonlight. Retries while Home Assistant is still starting."""
    if not enabled():
        return False
    port = port or int(os.environ.get("MOONLIGHT_PORT", "8091"))
    headers = {"Authorization": f"Bearer {os.environ['SUPERVISOR_TOKEN']}"}
    async with httpx.AsyncClient(base_url=SUPERVISOR, headers=headers, transport=transport, timeout=15) as client:
        for attempt in range(RETRIES):
            try:
                host = await _hostname(client)
                body = {"service": SERVICE, "config": {"host": host, "port": port, "token": service_token()}}
                r = await client.post("/discovery", json=body)
                r.raise_for_status()
                log.info("Offered Moonlight to Home Assistant at %s:%s", host, port)
                return True
            except httpx.HTTPError as e:
                log.warning("Couldn't announce Moonlight to Home Assistant (%s)", e.__class__.__name__)
            await _sleep(min(60, 5 * 2 ** attempt))
    return False
