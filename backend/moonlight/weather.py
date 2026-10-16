"""Deterministic demo weather (v0.1). Later: read an HA weather entity via the Supervisor API."""
from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta

# Weighted towards a UK autumn: lots of cloud and rain, occasional sun.
CONDITIONS = [
    ("partlycloudy", 26), ("cloudy", 24), ("rainy", 20), ("sunny", 12), ("pouring", 6),
    ("fog", 5), ("windy", 5), ("lightning-rainy", 2),
]
_TOTAL = sum(w for _, w in CONDITIONS)


def _rand(key: str) -> float:
    """Stable pseudo-random number in [0, 1) for a key."""
    h = hashlib.sha256(f"moonlight-weather:{key}".encode()).digest()
    return int.from_bytes(h[:8], "big") / 2 ** 64


def _condition(d: date) -> str:
    x = _rand(f"{d}:cond") * _TOTAL
    for name, w in CONDITIONS:
        if x < w:
            return name
        x -= w
    return "cloudy"


def day_forecast(d: date) -> dict:
    cond = _condition(d)
    high = 11 + round(_rand(f"{d}:high") * 7)          # 11..18 C
    if cond in ("sunny", "partlycloudy"):
        high += 1
    elif cond in ("pouring", "lightning-rainy", "fog"):
        high -= 1
    low = high - 4 - round(_rand(f"{d}:low") * 5)      # 4..9 below the high
    wet = {"rainy": (40, 40), "pouring": (70, 30), "lightning-rainy": (60, 30), "cloudy": (10, 25), "fog": (0, 20),
           "partlycloudy": (0, 20), "windy": (0, 25)}.get(cond, (0, 0))
    rain = round((wet[0] + _rand(f"{d}:rain") * wet[1]) / 5) * 5    # % chance of rain, in steps of 5
    return {"date": d.isoformat(), "high": high, "low": low, "condition": cond, "rain": rain}


def forecast(today: date | None = None, now: datetime | None = None, days: int = 10) -> dict:
    now = now or datetime.now()
    today = today or now.date()
    daily = [day_forecast(today + timedelta(days=i)) for i in range(days)]
    t = daily[0]
    # Simple diurnal curve: low around 05:00, high around 15:00.
    hour = now.hour + now.minute / 60
    frac = max(0.0, 1 - abs(hour - 15) / 10)
    temp = round(t["low"] + (t["high"] - t["low"]) * frac)
    cond = t["condition"]
    if (hour >= 19 or hour < 7) and cond in ("sunny", "partlycloudy"):
        cond = "clear-night"
    return {"current": {"temp": temp, "condition": cond}, "daily": daily}
