"""Internet access: the HTTPS listener, the public URL, and the limits that make port forwarding safe.

Moonlight can listen twice:
- the home-network port (8091, plain http): wall screens, Home Assistant ingress, the HA integration, the TV app;
- an HTTPS port (`MOONLIGHT_HTTPS_PORT`, default 8443 inside the container) with the certificate Home Assistant's
  Let's Encrypt app keeps in /ssl (`MOONLIGHT_SSL_CERT`, `MOONLIGHT_SSL_KEY`). This is the one to port forward.

On the HTTPS port pairing (or "Sign in with Home Assistant") is always required, whatever `require_pairing` says,
ingress headers are never trusted, and responses carry HSTS. While HTTPS is on, the plain port only answers private
(home network) addresses, so forwarding it by mistake exposes nothing.

Brute-force limits, per client address: wrong parent PINs and new pairing codes.
"""
from __future__ import annotations

import contextvars
import ipaddress
import os
import threading
import time
from collections import deque
from urllib.parse import urlsplit

from fastapi import HTTPException

CLIENT_IP: contextvars.ContextVar[str] = contextvars.ContextVar("moonlight_client_ip", default="")

HSTS = "max-age=31536000"  # a year; no includeSubDomains, the wildcard certificate covers other services too
SECURE_HEADERS = (
    (b"strict-transport-security", HSTS.encode()),
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"same-origin"),
)
HIDDEN_ON_HTTPS = ("/docs", "/redoc", "/openapi.json")


def https_enabled() -> bool:
    return bool(os.environ.get("MOONLIGHT_SSL_CERT") and os.environ.get("MOONLIGHT_SSL_KEY"))


def external_url() -> str | None:
    """Moonlight's address from the internet, e.g. https://moonlight.example.com (add-on option `external_url`)."""
    raw = (os.environ.get("MOONLIGHT_EXTERNAL_URL") or "").strip().rstrip("/")
    if not raw:
        return None
    parts = urlsplit(raw if "://" in raw else "https://" + raw)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    return f"{parts.scheme}://{parts.netloc}"


def is_private(ip: str) -> bool:
    """True for addresses on the home network (or this machine / the add-on network)."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return ip in ("testclient", "testserver")  # Starlette's TestClient
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return addr.is_private or addr.is_loopback or addr.is_link_local


class Limiter:
    """At most `limit` events per `window` seconds per key (sliding window, in memory)."""

    def __init__(self, limit: int, window: float) -> None:
        self.limit = limit
        self.window = window
        self.events: dict[str, deque[float]] = {}
        self.lock = threading.Lock()

    def _trim(self, key: str, now: float) -> deque[float]:
        q = self.events.setdefault(key, deque())
        while q and q[0] <= now - self.window:
            q.popleft()
        return q

    def retry_after(self, key: str) -> int:
        """Seconds until `key` may try again (0 = now)."""
        now = time.monotonic()
        with self.lock:
            q = self._trim(key, now)
            if len(q) < self.limit:
                return 0
            return max(1, int(q[0] + self.window - now) + 1)

    def hit(self, key: str) -> None:
        now = time.monotonic()
        with self.lock:
            self._trim(key, now).append(now)
            if len(self.events) > 10_000:  # forget idle keys so the table can't grow without bound
                for k in [k for k, q in self.events.items() if not q or q[-1] <= now - self.window]:
                    del self.events[k]

    def reset(self) -> None:
        with self.lock:
            self.events.clear()


pin_failures = Limiter(limit=10, window=15 * 60)
pair_starts = Limiter(limit=10, window=10 * 60)


def _too_many(seconds: int, what: str) -> HTTPException:
    minutes = max(1, round(seconds / 60))
    return HTTPException(status_code=429, detail=f"{what} Try again in {minutes} minute{'s' if minutes != 1 else ''}.",
                         headers={"Retry-After": str(seconds)})


def check_pin(c, pin) -> bool:
    """`db.verify_pin`, refusing for a while after too many wrong PINs from the same address."""
    from . import db

    key = CLIENT_IP.get()
    wait = pin_failures.retry_after(key)
    if wait:
        raise _too_many(wait, "Too many wrong PINs.")
    ok = db.verify_pin(c, pin)
    if not ok:
        pin_failures.hit(key)
    return ok


def limit_pair_start() -> None:
    key = CLIENT_IP.get()
    wait = pair_starts.retry_after(key)
    if wait:
        raise _too_many(wait, "Too many pairing codes asked for.")
    pair_starts.hit(key)
