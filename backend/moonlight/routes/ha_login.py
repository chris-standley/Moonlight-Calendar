"""Sign in with Home Assistant: pair a browser or the iPhone app with a Home Assistant login instead of a code.

Home Assistant's own OAuth flow (the one its companion apps use, with the client's URL as client_id):
1. `GET /api/auth/ha/start?layout=phone|compact|large&name=iPhone[&app=1]` redirects to Home Assistant's login page
   (`<ha>/auth/authorize`), with Moonlight's address (the page's own origin) as `client_id` and
   `<origin>/api/auth/ha/callback` as `redirect_uri`. Home Assistant only redirects back to the client's own host.
2. After the person signs in (with Home Assistant's own MFA, if they use it), Home Assistant redirects to the
   callback with a one-time code. Moonlight swaps it for a token at `<ha>/auth/token`, reads who signed in over the
   WebSocket (`auth/current_user`), revokes that token straight away and pairs the device as a new screen named after
   them, which shows (and can be revoked) in Settings > Screens like any other.
3. Browsers are sent to `/display` with the screen cookie set; the app (`app=1`) to
   `moonlight://signed-in?token=...&server=<origin>`, which only the app's sign-in sheet receives.

Home Assistant's address for the login page: `MOONLIGHT_HA_LOGIN_URL` (add-on option `homeassistant_url`), else the
external URL set in Home Assistant (Settings > System > Network), read through the Supervisor.
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import threading
import time
from urllib.parse import urlencode, urlsplit

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from .. import auth, security
from .. import db
from ..common import LAYOUTS, hub
from .displays import create_display

log = logging.getLogger("moonlight.ha_login")
router = APIRouter(prefix="/api/auth/ha")

STATE_TTL = 600
INTERNAL_HA = "http://homeassistant:8123"  # Home Assistant from inside an add-on
APP_CALLBACK = "moonlight://signed-in"
_states: dict[str, dict] = {}
_lock = threading.Lock()
_ha_url_cache: dict[str, tuple[float, str | None]] = {}


async def ha_login_url() -> str | None:
    """Home Assistant's address as the person's browser reaches it, or None when unknown."""
    raw = (os.environ.get("MOONLIGHT_HA_LOGIN_URL") or "").strip().rstrip("/")
    if raw:
        return raw if "://" in raw else "https://" + raw
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        return None
    cached = _ha_url_cache.get("url")
    if cached and cached[0] > time.monotonic():
        return cached[1]
    url = None
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get("http://supervisor/core/api/config", headers={"Authorization": f"Bearer {token}"})
            r.raise_for_status()
            url = (r.json().get("external_url") or "").rstrip("/") or None
    except (httpx.HTTPError, ValueError) as e:
        log.warning("Could not read Home Assistant's external URL: %s", e)
    _ha_url_cache["url"] = (time.monotonic() + (300 if url else 60), url)
    return url


def token_bases(login_url: str) -> list[str]:
    """Where Moonlight itself can reach Home Assistant to swap the code: directly first, then its public address."""
    bases = [os.environ.get("MOONLIGHT_HA_INTERNAL_URL") or (INTERNAL_HA if os.environ.get("SUPERVISOR_TOKEN") else "")]
    bases.append(login_url)
    return [b.rstrip("/") for b in dict.fromkeys(bases) if b]


def client_origin(request: Request) -> str:
    """This page's origin: the configured public URL when the request came in on it, else what the browser used."""
    ext = security.external_url()
    host = request.headers.get("host", "")
    if ext and urlsplit(ext).netloc == host:
        return ext
    return f"{request.url.scheme}://{host}"


async def exchange_code(code: str, client_id: str, login_url: str) -> tuple[str, str, str | None]:
    """Swap the one-time code for Home Assistant tokens: (base url that worked, access token, refresh token)."""
    last: Exception | None = None
    for base in token_bases(login_url):
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.post(f"{base}/auth/token",
                                 data={"grant_type": "authorization_code", "code": code, "client_id": client_id})
            if r.status_code == 400:
                raise HTTPException(status_code=400, detail="Home Assistant didn't accept the sign-in. Try again.")
            r.raise_for_status()
            data = r.json()
            return base, data["access_token"], data.get("refresh_token")
        except HTTPException:
            raise
        except (httpx.HTTPError, ValueError, KeyError) as e:
            last = e
    raise HTTPException(status_code=502, detail=f"Moonlight couldn't reach Home Assistant to finish signing in ({last})")


async def current_user(base: str, access_token: str) -> dict:
    """`{id, name, is_admin, is_owner}` for the token, over Home Assistant's WebSocket API."""
    from websockets.asyncio.client import connect

    ws_url = ("wss://" if base.startswith("https://") else "ws://") + base.split("://", 1)[1] + "/api/websocket"
    async with connect(ws_url, open_timeout=10) as ws:
        json.loads(await ws.recv())  # auth_required
        await ws.send(json.dumps({"type": "auth", "access_token": access_token}))
        if json.loads(await ws.recv()).get("type") != "auth_ok":
            raise HTTPException(status_code=401, detail="Home Assistant rejected the sign-in")
        await ws.send(json.dumps({"id": 1, "type": "auth/current_user"}))
        while True:
            msg = json.loads(await ws.recv())
            if msg.get("id") == 1:
                if not msg.get("success"):
                    raise HTTPException(status_code=502, detail="Home Assistant didn't say who signed in")
                return msg["result"]


async def revoke(base: str, refresh_token: str | None) -> None:
    if not refresh_token:
        return
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            await c.post(f"{base}/auth/revoke", data={"token": refresh_token})
    except httpx.HTTPError as e:  # the token is useless to anyone else; it just stays listed in the HA profile
        log.info("Could not revoke the Home Assistant sign-in token: %s", e)


@router.get("/start")
async def start(request: Request, layout: str = "phone", name: str = "", app: int = 0):
    layout = db.OLD_LAYOUTS.get(layout, layout)
    if layout not in LAYOUTS:
        layout = "phone"
    login = await ha_login_url()
    if not login:
        raise HTTPException(status_code=404, detail="Sign in with Home Assistant needs Home Assistant's address "
                                                    "(add-on option homeassistant_url)")
    security.limit_pair_start()
    origin = client_origin(request)
    state = secrets.token_urlsafe(24)
    now = time.time()
    with _lock:
        for s in [s for s, e in _states.items() if e["expires"] < now]:
            del _states[s]
        if len(_states) > 200:
            raise HTTPException(status_code=429, detail="Too many sign-ins in progress; try again later")
        _states[state] = {"layout": layout, "name": name.strip()[:40], "app": bool(app), "origin": origin,
                          "expires": now + STATE_TTL}
    query = urlencode({"response_type": "code", "client_id": origin + "/", "state": state,
                       "redirect_uri": origin + "/api/auth/ha/callback"})
    return RedirectResponse(f"{login}/auth/authorize?{query}", status_code=302)


@router.get("/callback")
async def callback(request: Request, state: str = "", code: str = "", error: str = ""):
    with _lock:
        entry = _states.pop(state, None)
    if entry is None or entry["expires"] < time.time():
        return _page("That sign-in link has expired. Go back and try again.", 400)
    if error or not code:
        return _page("Signing in with Home Assistant was cancelled.", 400)
    login = await ha_login_url()
    if not login:
        return _page("Home Assistant's address isn't set up any more.", 400)
    try:
        base, access, refresh = await exchange_code(code, entry["origin"] + "/", login)
        try:
            user = await current_user(base, access)
        finally:
            await revoke(base, refresh)
    except HTTPException as e:
        return _page(str(e.detail), e.status_code)
    except Exception as e:  # noqa: BLE001 - a WebSocket hiccup: tell the person, keep the details in the log
        log.warning("Sign in with Home Assistant failed: %s", e)
        return _page("Moonlight couldn't finish signing in with Home Assistant. Try again.", 502)

    who = (user.get("name") or "Home Assistant user").strip()[:30]
    device = entry["name"] or {"phone": "phone", "compact": "screen", "large": "screen"}[entry["layout"]]
    token, d = create_display(f"{who}'s {device}", entry["layout"])
    log.info("%s signed in with Home Assistant as %s", d["name"], user.get("id"))
    await hub.broadcast("displays")
    if entry["app"]:
        return RedirectResponse(f"{APP_CALLBACK}?{urlencode({'token': token, 'server': entry['origin']})}", status_code=302)
    resp = RedirectResponse("/display", status_code=302)
    resp.headers.append("set-cookie", auth.cookie_header(token, auth.is_secure(request)))
    return resp


def _page(message: str, status: int) -> HTMLResponse:
    from html import escape

    return HTMLResponse(
        "<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
        "<title>Moonlight</title><style>body{font-family:system-ui,sans-serif;background:#0f1424;color:#e8ecf7;"
        "display:grid;place-items:center;min-height:100vh;margin:0}main{max-width:28rem;padding:1rem;text-align:center}"
        "a{color:#9bb7ff}</style>"
        f"<main><h1>Moonlight</h1><p>{escape(message)}</p><p><a href='/display'>Back</a></p></main>",
        status_code=status)
