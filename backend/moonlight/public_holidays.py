"""Public holidays for the household's country (and region), used by "skip public holidays" on repeating events and
chores, and shown on the calendar.

Dates come from the `holidays` package (offline, ~200 countries with their regions, e.g. the UK's England, Scotland,
Wales and Northern Ireland). Settings `holidays` = {country, subdiv}; country "" = none. Until one is saved, a household
in Europe/London gets England's bank holidays and others get none (pick one in Settings > Display).
"""
from __future__ import annotations

import re
from datetime import date
from functools import lru_cache
from typing import Callable

import holidays

from . import db

KEY = "holidays"


def default_region() -> dict:
    return {"country": "GB", "subdiv": "ENG"} if db.default_timezone() == "Europe/London" else {"country": "", "subdiv": ""}


def region(c) -> dict:
    saved = db.get_setting(c, KEY)
    if isinstance(saved, dict) and isinstance(saved.get("country"), str):
        return {"country": saved["country"], "subdiv": saved.get("subdiv") or ""}
    return default_region()


@lru_cache(maxsize=64)
def _year(country: str, subdiv: str, year: int) -> dict[date, str]:
    if not country:
        return {}
    try:
        return dict(holidays.country_holidays(country, subdiv=subdiv or None, years=year))
    except (NotImplementedError, KeyError, ValueError):
        return {}


def name_on(r: dict, d: date) -> str | None:
    return _year(r["country"], r["subdiv"], d.year).get(d)


def checker(c) -> Callable[[date], bool]:
    """is_holiday(day) for the household's region (read once)."""
    r = region(c)
    return lambda d: name_on(r, d) is not None


def between(r: dict, lo: date, hi: date) -> list[dict]:
    """[{date, name}] in lo..hi inclusive."""
    out = []
    for y in range(lo.year, hi.year + 1):
        for d, name in _year(r["country"], r["subdiv"], y).items():
            if lo <= d <= hi:
                out.append({"date": d.isoformat(), "name": name})
    return sorted(out, key=lambda x: x["date"])


def _spaced(class_name: str) -> str:
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", class_name)


@lru_cache(maxsize=1)
def countries() -> list[dict]:
    """[{code, name, subdivs: [{code, name}]}] for the Settings picker."""
    names = {v[1]: _spaced(v[0]) for v in holidays.registry.COUNTRIES.values()}
    out = []
    for code, subdivs in holidays.list_supported_countries().items():
        if len(code) != 2 or code == "UK":  # the package also lists ISO alpha-3 codes and UK as aliases
            continue
        aliases: dict[str, str] = {}
        try:
            aliases = {v: k for k, v in getattr(holidays.country_holidays(code), "subdivisions_aliases", {}).items()}
        except Exception:
            pass
        out.append({"code": code, "name": names.get(code, code),
                    "subdivs": [{"code": s, "name": aliases.get(s, s)} for s in subdivs]})
    return sorted(out, key=lambda x: x["name"])


def validate(val) -> dict:
    from .common import bad

    if not isinstance(val, dict):
        raise bad("holidays must look like {\"country\": \"GB\", \"subdiv\": \"ENG\"}")
    country = val.get("country") or ""
    subdiv = val.get("subdiv") or ""
    if not isinstance(country, str) or not isinstance(subdiv, str):
        raise bad("holidays.country and holidays.subdiv must be text")
    if country:
        supported = holidays.list_supported_countries()
        if country not in supported:
            raise bad(f"No public holidays known for country {country}")
        if subdiv and subdiv not in supported[country]:
            raise bad(f"{subdiv} isn't a region of {country}")
    elif subdiv:
        raise bad("holidays.subdiv needs a country")
    return {"country": country, "subdiv": subdiv}
