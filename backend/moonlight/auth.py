"""Who may use the API.

Three ways in:
- Home Assistant ingress: the Supervisor's ingress proxy (172.30.32.2) adds `X-Ingress-Path`; HA has
  already authenticated the user, so these requests are trusted.
- A paired wall screen: a long random display token, sent as the `moonlight_display` cookie,
  `Authorization: Bearer <token>`, or `?token=` (WebSocket, first TouchKio load).
- Auth off (`MOONLIGHT_AUTH=off`): everyone. This is the default outside the add-on (no
  `SUPERVISOR_TOKEN`), so local development and the tests need no pairing. Never on the HTTPS port.

The HTTPS port (see security.py) is the one meant for the internet: there auth is always on, ingress headers are
ignored and the cookie is `Secure`. While HTTPS is on, the plain port refuses addresses outside the home network.

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

from . import db, security

COOKIE = "moonlight_display"
COOKIE_MAX_AGE = 10 * 365 * 24 * 3600
DEFAULT_INGRESS_IPS = ("172.30.32.2",)
OPEN_PATHS = ("/api/health", "/api/auth/status")
OPEN_PREFIXES = ("/api/pair/", "/api/auth/ha/")
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


def cookie_header(token: str | None, secure: bool = False) -> str:
    """Set-Cookie value storing (or, with None, clearing) the display token. `secure` on the HTTPS port."""
    flags = "; HttpOnly; SameSite=Lax" + ("; Secure" if secure else "")
    if token is None:
        return f"{COOKIE}=; Path=/; Max-Age=0{flags}"
    return f"{COOKIE}={token}; Path=/; Max-Age={COOKIE_MAX_AGE}{flags}"


def is_secure(request_or_scope: Any) -> bool:
    scope = getattr(request_or_scope, "scope", request_or_scope)
    return scope.get("scheme") in ("https", "wss")


def current(request_or_scope: Any) -> dict:
    """Auth info for this request: {"via": "ingress"|"display"|"open"|None, "display": row|None, "user": str|None}."""
    scope = getattr(request_or_scope, "scope", request_or_scope)
    return scope.get(SCOPE_KEY) or {"via": None, "display": None, "user": None, "enabled": False}


def is_open_path(path: str) -> bool:
    return path in OPEN_PATHS or path.startswith(OPEN_PREFIXES)


class AuthMiddleware:
    """Pure ASGI middleware so it covers the WebSocket as well as HTTP."""

    def __init__(self, app, enabled: bool = False, ingress_ips: set[str] | None = None,
                 lan_only_http: bool = False) -> None:
        self.app = app
        self.enabled = enabled
        self.ingress_ips = set(ingress_ips or DEFAULT_INGRESS_IPS)
        self.lan_only_http = lan_only_http  # HTTPS is on: plain http is for the home network only

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)

        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        client_ip = (scope.get("client") or ("", 0))[0]
        security.CLIENT_IP.set(client_ip)
        secure = is_secure(scope)
        path = scope.get("path", "")
        if not secure and self.lan_only_http and not security.is_private(client_ip):
            return await self._refuse(scope, receive, send, 403, "Use Moonlight's https address from outside the home")
        if secure and path in security.HIDDEN_ON_HTTPS:
            return await self._refuse(scope, receive, send, 404, "Not found")
        ingress = not secure and "x-ingress-path" in headers and client_ip in self.ingress_ips
        enabled = self.enabled or secure

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
        elif not enabled:
            via = "open"
        else:
            via = None
        user = None
        if ingress:
            user = headers.get("x-remote-user-display-name") or headers.get("x-remote-user-name") or None
        scope[SCOPE_KEY] = {"via": via, "display": display, "user": user, "enabled": enabled}
        if display:
            touch(display["id"])

        is_api = path == "/api" or path.startswith("/api/")
        if via is None and is_api and not is_open_path(path):
            if scope["type"] == "websocket":
                await receive()  # websocket.connect
                await send({"type": "websocket.close", "code": 4401})
                return
            body = json.dumps({"detail": "This screen is not paired", "pairing": True}).encode()
            hdrs = [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]
            if cookie_token:
                hdrs.append((b"set-cookie", cookie_header(None, secure).encode()))
            if secure:
                hdrs.extend(security.SECURE_HEADERS)
            await send({"type": "http.response.start", "status": 401, "headers": hdrs})
            await send({"type": "http.response.body", "body": body})
            return

        # Keep the HttpOnly cookie in step: set it when a valid token came another way (?token= on the
        # first TouchKio load, or the localStorage copy as a Bearer header), clear it when it is stale.
        set_cookie = None
        if scope["type"] == "http":
            if display and cookie_token != token:
                set_cookie = cookie_header(token, secure)
            elif cookie_token and not display:
                set_cookie = cookie_header(None, secure)
        if set_cookie is None and not (secure and scope["type"] == "http"):
            return await self.app(scope, receive, send)

        async def send_with_cookie(message):
            if message["type"] == "http.response.start":
                hdrs = list(message.get("headers", []))
                route_sets_it = any(h[0].lower() == b"set-cookie" and h[1].startswith(COOKIE.encode() + b"=")
                                    for h in hdrs)
                if set_cookie and not route_sets_it:  # e.g. a freshly approved pairing hands out a new token
                    hdrs.append((b"set-cookie", set_cookie.encode()))
                if secure:
                    hdrs.extend(security.SECURE_HEADERS)
                message = {**message, "headers": hdrs}
            await send(message)

        return await self.app(scope, receive, send_with_cookie)

    @staticmethod
    async def _refuse(scope, receive, send, status: int, detail: str) -> None:
        if scope["type"] == "websocket":
            await receive()
            await send({"type": "websocket.close", "code": 4403 if status == 403 else 4404})
            return
        body = json.dumps({"detail": detail}).encode()
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})
