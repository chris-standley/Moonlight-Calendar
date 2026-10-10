"""Who may use the API.

Three ways in:
- Home Assistant ingress: the Supervisor's ingress proxy (172.30.32.2) adds `X-Ingress-Path`; HA has
  already authenticated the user, so these requests are trusted.
- A paired wall screen: a long random display token, sent as the `moonlight_display` cookie,
  `Authorization: Bearer <token>`, or `?token=` (WebSocket, first TouchKio load).
- Auth off (`MOONLIGHT_AUTH=off`): everyone. This is the default outside the add-on (no
  `SUPERVISOR_TOKEN`), so local development and the tests need no pairing.

Unauthenticated requests to `/api/*` get 401 (WebSocket: closed), except the endpoints a screen needs to
pair itself. HTML and assets are always served, so the pairing screen can load.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
from http.cookies import SimpleCookie
from typing import Any
from urllib.parse import parse_qs

from . import db

COOKIE = "moonlight_display"
COOKIE_MAX_AGE = 10 * 365 * 24 * 3600
DEFAULT_INGRESS_IPS = ("172.30.32.2",)
OPEN_PATHS = ("/api/health", "/api/auth/status")
OPEN_PREFIXES = ("/api/pair/",)
SCOPE_KEY = "moonlight.auth"
_LAST_SEEN_EVERY = 60.0  # seconds between last_seen writes per screen
_last_seen_written: dict[str, float] = {}


def auth_enabled_from_env() -> bool:
    raw = os.environ.get("MOONLIGHT_AUTH")
    if raw is None or raw.strip() == "":
        return bool(os.environ.get("SUPERVISOR_TOKEN"))  # on inside the add-on, off for local dev
    return raw.strip().lower() in ("1", "on", "true", "yes")


def ingress_ips_from_env() -> set[str]:
    raw = os.environ.get("MOONLIGHT_INGRESS_IPS", "")
    ips = {x.strip() for x in raw.split(",") if x.strip()}
    return ips or set(DEFAULT_INGRESS_IPS)


def new_token() -> str:
    return "mlt_" + secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    # Tokens are 256-bit random strings, so a plain SHA-256 is enough (no salt/stretching needed).
    return hashlib.sha256(token.encode()).hexdigest()


def display_for_token(token: str | None) -> dict | None:
    if not token or len(token) > 200:
        return None
    with db.connect() as c:
        return db.row(c, "SELECT * FROM displays WHERE token_hash = ? AND revoked = 0", (hash_token(token),))


def touch(display_id: str) -> None:
    now = time.monotonic()
    if now - _last_seen_written.get(display_id, -1e9) < _LAST_SEEN_EVERY:
        return
    _last_seen_written[display_id] = now
    with db.connect() as c:
        c.execute("UPDATE displays SET last_seen = ? WHERE id = ?", (db.now_iso(), display_id))


def forget_seen(display_id: str) -> None:
    _last_seen_written.pop(display_id, None)


def cookie_header(token: str | None) -> str:
    """Set-Cookie value storing (or, with None, clearing) the display token."""
    if token is None:
        return f"{COOKIE}=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax"
    return f"{COOKIE}={token}; Path=/; Max-Age={COOKIE_MAX_AGE}; HttpOnly; SameSite=Lax"


def current(request_or_scope: Any) -> dict:
    """Auth info for this request: {"via": "ingress"|"display"|"open"|None, "display": row|None, "user": str|None}."""
    scope = getattr(request_or_scope, "scope", request_or_scope)
    return scope.get(SCOPE_KEY) or {"via": None, "display": None, "user": None, "enabled": False}


def is_open_path(path: str) -> bool:
    return path in OPEN_PATHS or path.startswith(OPEN_PREFIXES)


class AuthMiddleware:
    """Pure ASGI middleware so it covers the WebSocket as well as HTTP."""

    def __init__(self, app, enabled: bool = False, ingress_ips: set[str] | None = None) -> None:
        self.app = app
        self.enabled = enabled
        self.ingress_ips = set(ingress_ips or DEFAULT_INGRESS_IPS)

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)

        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        client_ip = (scope.get("client") or ("", 0))[0]
        ingress = "x-ingress-path" in headers and client_ip in self.ingress_ips

        cookie_token = None
        if "cookie" in headers:
            jar = SimpleCookie()
            try:
                jar.load(headers["cookie"])
            except Exception:  # malformed cookie header
                jar = SimpleCookie()
            if COOKIE in jar:
                cookie_token = jar[COOKIE].value or None
        bearer = None
        authz = headers.get("authorization", "")
        if authz.lower().startswith("bearer "):
            bearer = authz[7:].strip() or None
        query_token = None
        qs = scope.get("query_string", b"").decode("latin-1")
        if "token=" in qs:
            query_token = (parse_qs(qs).get("token") or [None])[0]

        token = bearer or query_token or cookie_token
        display = display_for_token(token) if token else None
        if display is None and token is not cookie_token and cookie_token:
            display = display_for_token(cookie_token)  # stale bearer, good cookie
            token = cookie_token if display else token

        if ingress:
            via = "ingress"
        elif display:
            via = "display"
        elif not self.enabled:
            via = "open"
        else:
            via = None
        user = None
        if ingress:
            user = headers.get("x-remote-user-display-name") or headers.get("x-remote-user-name") or None
        scope[SCOPE_KEY] = {"via": via, "display": display, "user": user, "enabled": self.enabled}
        if display:
            touch(display["id"])

        path = scope.get("path", "")
        is_api = path == "/api" or path.startswith("/api/")
        if via is None and is_api and not is_open_path(path):
            if scope["type"] == "websocket":
                await receive()  # websocket.connect
                await send({"type": "websocket.close", "code": 4401})
                return
            body = json.dumps({"detail": "This screen is not paired", "pairing": True}).encode()
            hdrs = [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]
            if cookie_token:
                hdrs.append((b"set-cookie", cookie_header(None).encode()))
            await send({"type": "http.response.start", "status": 401, "headers": hdrs})
            await send({"type": "http.response.body", "body": body})
            return

        # Keep the HttpOnly cookie in step: set it when a valid token came another way (?token= on the
        # first TouchKio load, or the localStorage copy as a Bearer header), clear it when it is stale.
        set_cookie = None
        if scope["type"] == "http":
            if display and cookie_token != token:
                set_cookie = cookie_header(token)
            elif cookie_token and not display:
                set_cookie = cookie_header(None)
        if set_cookie is None:
            return await self.app(scope, receive, send)

        async def send_with_cookie(message):
            if message["type"] == "http.response.start":
                hdrs = list(message.get("headers", []))
                route_sets_it = any(h[0].lower() == b"set-cookie" and h[1].startswith(COOKIE.encode() + b"=")
                                    for h in hdrs)
                if not route_sets_it:  # e.g. a freshly approved pairing hands out a new token
                    hdrs.append((b"set-cookie", set_cookie.encode()))
                    message = {**message, "headers": hdrs}
            await send(message)

        return await self.app(scope, receive, send_with_cookie)
