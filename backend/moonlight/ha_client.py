"""Weather from a Home Assistant weather entity (via the Supervisor proxy), with demo fallback.

Inside the add-on, `homeassistant_api: true` gives us SUPERVISOR_TOKEN and the Core API at
http://supervisor/core/api. Outside an add-on set MOONLIGHT_HA_URL (e.g. http://homeassistant.local:8123/api)
and MOONLIGHT_HA_TOKEN (a long-lived access token). The entity is chosen in Settings (`weather_entity`);
MOONLIGHT_WEATHER_ENTITY is the fallback when none is saved. No entity means demo weather.

`get_weather(temp_unit)` returns the /api/weather shape:
  {source: "homeassistant"|"demo", entity: str|null, unit: "C"|"F",
   current: {temp, condition}, daily: [{date, high, low, condition}]}
"""
from __future__ import annotations

import logging
import os
import re
import time
from datetime import date, datetime, tzinfo
from typing import Any, Callable

import httpx

from . import weather as demo_weather

log = logging.getLogger("moonlight.ha")

DEFAULT_URL = "http://supervisor/core/api"
CACHE_SECONDS = 600
RETRY_AFTER_ERROR_SECONDS = 60
DAYS = 10

# HA conditions the app has no icon for, mapped to the closest one it does.
CONDITION_MAP = {
    "snowy-rainy": "snowy",
    "hail": "snowy",
    "windy-variant": "windy",
    "exceptional": "cloudy",
}


class HAError(Exception):
    pass


def to_unit(value: float | None, src: str, dst: str) -> int | None:
    if value is None:
        return None
    v = float(value)
    if src == "F" and dst == "C":
        v = (v - 32) * 5 / 9
    elif src == "C" and dst == "F":
        v = v * 9 / 5 + 32
    return round(v)


def _unit(raw: Any) -> str:
    return "F" if isinstance(raw, str) and "F" in raw.upper() else "C"


def _condition(raw: Any) -> str:
    c = str(raw or "cloudy")
    return CONDITION_MAP.get(c, c)


def _local_date(raw: Any, tz: tzinfo | None) -> date | None:
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(tz)  # tz=None -> the system's local zone (the add-on gets HA's TZ)
    return dt.date()


def _num(v: Any) -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def parse_ha(state: dict, forecast_response: dict, entity: str, today: date,
             tz: tzinfo | None = None) -> dict:
    """Turn HA's state + get_forecasts response into a unit-tagged forecast in the entity's unit."""
    st = state.get("state")
    if st in (None, "unavailable", "unknown"):
        raise HAError(f"{entity} is {st}")
    attrs = state.get("attributes") or {}
    unit = _unit(attrs.get("temperature_unit"))
    temp = _num(attrs.get("temperature"))

    # REST returns {"changed_states": [...], "service_response": {entity: {"forecast": [...]}}}
    resp = forecast_response.get("service_response", forecast_response) or {}
    entries = (resp.get(entity) or {}).get("forecast") or []

    by_day: dict[date, dict] = {}
    for f in entries:
        d = _local_date(f.get("datetime"), tz)
        high = _num(f.get("temperature"))
        if d is None or high is None or d < today or d in by_day:
            continue
        low = _num(f.get("templow"))
        by_day[d] = {"date": d.isoformat(), "high": high, "low": high if low is None else low,
                     "condition": _condition(f.get("condition"))}
    daily = [by_day[d] for d in sorted(by_day)][:DAYS]
    if temp is None:
        temp = daily[0]["high"] if daily else None
    if temp is None:
        raise HAError(f"{entity} has no temperature")
    return {"unit": unit, "name": attrs.get("friendly_name") or entity,
            "current": {"temp": temp, "condition": _condition(st)}, "daily": daily}


def convert(fc: dict, dst: str) -> dict:
    src = fc["unit"]
    return {
        "unit": dst,
        "current": {"temp": to_unit(fc["current"]["temp"], src, dst), "condition": fc["current"]["condition"]},
        "daily": [{**d, "high": to_unit(d["high"], src, dst), "low": to_unit(d["low"], src, dst)}
                  for d in fc["daily"]],
    }


class HAWeather:
    """Fetches and caches one weather entity. All failures are swallowed into `None` (caller falls back)."""

    def __init__(self, entity: str, base_url: str, token: str, *, ttl: float = CACHE_SECONDS,
                 transport: httpx.AsyncBaseTransport | None = None,
                 clock: Callable[[], float] = time.monotonic,
                 today: Callable[[], date] = date.today, tz: tzinfo | None = None) -> None:
        self.entity = entity
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.ttl = ttl
        self.transport = transport
        self.clock = clock
        self.today = today
        self.tz = tz
        self._cached: dict | None = None
        self._cached_at = 0.0
        self._failed_at: float | None = None
        self._error_logged = False
        self.fetches = 0

    async def _fetch(self) -> dict:
        self.fetches += 1
        headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(base_url=self.base_url, headers=headers, timeout=10,
                                     transport=self.transport) as client:
            r = await client.get(f"/states/{self.entity}")
            r.raise_for_status()
            state = r.json()
            r = await client.post("/services/weather/get_forecasts?return_response",
                                  json={"entity_id": self.entity, "type": "daily"})
            r.raise_for_status()
            fc = r.json()
        if not isinstance(state, dict) or not isinstance(fc, dict):
            raise HAError("unexpected response from Home Assistant")
        return parse_ha(state, fc, self.entity, self.today(), self.tz)

    async def get(self) -> dict | None:
        now = self.clock()
        if self._cached is not None and now - self._cached_at < self.ttl:
            return self._cached
        if self._failed_at is not None and now - self._failed_at < RETRY_AFTER_ERROR_SECONDS:
            return self._stale()
        try:
            self._cached = await self._fetch()
            self._cached_at = now
            self._failed_at = None
            if self._error_logged:
                log.info("Weather from %s is working again", self.entity)
            self._error_logged = False
            return self._cached
        except Exception as e:  # network, HTTP status, bad JSON, unavailable entity...
            self._failed_at = now
            if not self._error_logged:
                log.warning("Couldn't read weather from Home Assistant (%s): %s; using demo weather",
                            self.entity, e)
                self._error_logged = True
            return self._stale()

    def _stale(self) -> dict | None:
        # A forecast up to an hour old beats switching to made-up weather during a short HA restart.
        if self._cached is not None and self.clock() - self._cached_at < 3600:
            return self._cached
        return None


ENTITY_RE = re.compile(r"^weather\.[a-z0-9_]+$")

_override: HAWeather | None = None
_overridden = False
_clients: dict[str, HAWeather] = {}
_transport: httpx.AsyncBaseTransport | None = None  # tests


def connection() -> tuple[str, str] | None:
    """(Core API URL, token) when Moonlight can reach Home Assistant, else None."""
    token = os.environ.get("MOONLIGHT_HA_TOKEN") or os.environ.get("SUPERVISOR_TOKEN") or ""
    if not token:
        return None
    return (os.environ.get("MOONLIGHT_HA_URL") or DEFAULT_URL), token


def env_entity() -> str:
    return os.environ.get("MOONLIGHT_WEATHER_ENTITY", "").strip()


def set_client(client: HAWeather | None) -> None:
    """Override the weather source (tests); None means demo weather."""
    global _override, _overridden
    _override, _overridden = client, True


def set_transport(transport: httpx.AsyncBaseTransport | None) -> None:
    """Send Home Assistant requests through `transport` (tests)."""
    global _transport
    _transport = transport
    _clients.clear()


def reset() -> None:
    """Forget any override and cached clients so the next call re-reads settings and the environment."""
    global _override, _overridden, _transport
    _override, _overridden, _transport = None, False, None
    _clients.clear()


def client(entity: str | None = None) -> HAWeather | None:
    """The source for `entity` (default: MOONLIGHT_WEATHER_ENTITY); None means demo weather."""
    if _overridden:
        return _override
    entity = (env_entity() if entity is None else entity).strip()
    if not entity:
        return None
    conn = connection()
    if conn is None:
        log.warning("Weather entity %s is set but there's no SUPERVISOR_TOKEN/MOONLIGHT_HA_TOKEN; using demo weather",
                    entity)
        return None
    if entity not in _clients:
        _clients[entity] = HAWeather(entity, *conn, transport=_transport)
    return _clients[entity]


async def list_entities() -> list[dict]:
    """Home Assistant's weather entities with their current conditions (for the Settings picker).

    Raises HAError when Home Assistant isn't configured or can't be reached."""
    conn = connection()
    if conn is None:
        raise HAError("Moonlight isn't connected to Home Assistant")
    url, token = conn
    try:
        async with httpx.AsyncClient(base_url=url.rstrip("/"), headers={"Authorization": f"Bearer {token}"},
                                     timeout=10, transport=_transport) as http:
            r = await http.get("/states")
        r.raise_for_status()
        states = r.json()
    except Exception as e:
        raise HAError(f"Couldn't list Home Assistant's weather entities ({e.__class__.__name__})")
    out = []
    for s in states if isinstance(states, list) else []:
        eid = s.get("entity_id", "") if isinstance(s, dict) else ""
        if not ENTITY_RE.match(eid):
            continue
        attrs = s.get("attributes") or {}
        st = s.get("state")
        available = st not in (None, "unavailable", "unknown")
        temp = _num(attrs.get("temperature"))
        out.append({"entity_id": eid, "name": attrs.get("friendly_name") or eid, "available": available,
                    "condition": _condition(st) if available else None,
                    "temperature": None if temp is None else round(temp, 1),
                    "unit": _unit(attrs.get("temperature_unit")),
                    "attribution": attrs.get("attribution")})
    out.sort(key=lambda w: (not w["available"], str(w["name"]).lower()))
    return out


def demo(temp_unit: str) -> dict:
    fc = demo_weather.forecast()
    out = convert({"unit": "C", **fc}, temp_unit)
    return {"source": "demo", "entity": None, **out}


async def get_weather(temp_unit: str = "C", entity: str | None = None) -> dict:
    c = client(entity)
    if c is not None:
        fc = await c.get()
        if fc is not None:
            return {"source": "homeassistant", "entity": c.entity, "name": fc.get("name") or c.entity,
                    **convert(fc, temp_unit)}
    return demo(temp_unit)
