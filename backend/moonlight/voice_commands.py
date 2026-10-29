"""Things said to Assist that Moonlight answers itself, on the screen that was asked.

Home Assistant's own timers only work on a voice satellite device, and a screen isn't one, so "set a 30 minute
timer" would get "timers aren't supported on this device". Moonlight catches timer requests before they reach the
conversation agent and puts the timer on the asking screen instead (alerts.py), full screen when asked for:

    "set a 30 minute timer" · "full screen timer for 10 minutes" · "pasta timer for 1 hour and 15 minutes" ·
    "timer for an hour and a half for the cake" · "cancel the timer" · "how long is left on the timer?"
"""
from __future__ import annotations

import re
from typing import Any

from . import alerts, db, voice_home
from .voice_when import AMOUNT, HALF_HOUR, duration_of

TIMER = re.compile(r"\b(timer|countdown|count\s*down)\b", re.I)
FULL = re.compile(r"\b(full[- ]?screen|big|large)\b", re.I)
CANCEL = re.compile(r"\b(cancel|stop|clear|delete|remove|end|dismiss)\b", re.I)
LEFT = re.compile(r"\b(how\s+(?:long|much(?:\s+time)?)|time\s+left|remaining|left)\b", re.I)
LABEL_AFTER = re.compile(r"\bfor\s+(?:the\s+|my\s+|a\s+|an\s+)?([a-z][a-z' ]{1,40}?)\s*$", re.I)
LABEL_BEFORE = re.compile(r"\b(?:an?\s+|the\s+|my\s+)?([a-z][a-z']{1,20}(?:\s+[a-z][a-z']{1,20})?)\s+(?:timer|countdown)\b", re.I)
FILLER = {"set", "start", "make", "a", "an", "the", "my", "full", "screen", "fullscreen", "big", "large", "new", "please",
          "minute", "minutes", "hour", "hours", "second", "seconds", "one", "kitchen", "and", "for", "me", "can", "you"}


def spoken_duration(seconds: int) -> str:
    h, rest = divmod(max(0, int(seconds)), 3600)
    m, s = divmod(rest, 60)
    parts = []
    if h:
        parts.append(f"{h} hour" + ("s" if h != 1 else ""))
    if m:
        parts.append(f"{m} minute" + ("s" if m != 1 else ""))
    if s and not h:
        parts.append(f"{s} second" + ("s" if s != 1 else ""))
    if not parts:
        return "less than a second"
    return " and ".join(parts) if len(parts) <= 2 else f"{parts[0]}, {parts[1]} and {parts[2]}"


def _label(text: str) -> str:
    """What the timer is for: "pasta timer ...", "... timer for the cake". Empty when it's just a timer."""
    bare = AMOUNT.sub(" ", HALF_HOUR.sub(" ", text)).strip(" .?!")
    m = LABEL_AFTER.search(bare)
    cand = m.group(1) if m else ""
    if not cand or all(w in FILLER for w in cand.lower().split()):
        m = LABEL_BEFORE.search(bare)
        cand = m.group(1) if m else ""
    words = [w for w in cand.split() if w.lower() not in FILLER]
    return " ".join(words).strip().capitalize()[:40]


def parse(text: str) -> dict | None:
    """What Moonlight should do itself with `text`, or None to pass it to Home Assistant. Timers:
    {"do": "start", "seconds", "label", "full"} · {"do": "cancel"} · {"do": "left"}; the rest is voice_home.py's."""
    if not text:
        return None
    if not TIMER.search(text):
        return voice_home.parse(text)
    if CANCEL.search(text):
        return {"do": "cancel"}
    seconds = duration_of(text)
    if seconds:
        return {"do": "start", "seconds": min(seconds, alerts.MAX_SECONDS), "label": _label(text),
                "full": bool(FULL.search(text))}
    if LEFT.search(text):
        return {"do": "left"}
    return None


def _mine(display: dict | None) -> list[dict]:
    """Countdown timers this screen shows, newest first."""
    now = alerts.now_ms()
    shown = [a for a in alerts._alerts.values()
             if a["kind"] == "timer" and not a.get("count_up") and alerts.shown_on(a, display)
             and (a["expires_at"] is None or a["expires_at"] > now)]
    return sorted(shown, key=lambda a: a["created_at"], reverse=True)


async def run(cmd: dict, ctx: dict) -> dict | None:
    """Do it on the asking screen (ctx: display, layout): {"say": what to say, "go"?: a section to show}, or None
    when it isn't Moonlight's after all (the words then go on to Home Assistant)."""
    if cmd["do"] not in ("start", "cancel", "left"):
        return await voice_home.run(cmd, ctx)
    return {"say": await _timer(cmd, ctx.get("display"))}


async def _timer(cmd: dict, display: dict | None) -> str:
    if cmd["do"] == "start":
        body: dict[str, Any] = {"kind": "timer", "label": cmd["label"] or "Timer", "duration": cmd["seconds"],
                                "style": "fullscreen" if cmd["full"] else "toast",
                                "screens": [display["id"]] if display else "all"}
        with db.connect() as c:
            await alerts.add(c, body)
        what = f"{cmd['label']} timer" if cmd["label"] else "Timer"
        return f"{what} set for {spoken_duration(cmd['seconds'])}."
    timers = _mine(display)
    if cmd["do"] == "cancel":
        if not timers:
            return "There's no timer running."
        await alerts.remove([a["id"] for a in timers], "dismissed", display["name"] if display else None)
        return "Timer cancelled." if len(timers) == 1 else f"Cancelled {len(timers)} timers."
    if not timers:
        return "There's no timer running."
    now = alerts.now_ms()
    lines = []
    for a in timers[:3]:
        left = (a["ends_at"] - now) / 1000
        name = a["label"] if a["label"] and a["label"] != "Timer" else "The timer"
        lines.append(f"{name} has finished." if left <= 0 else f"{name} has {spoken_duration(int(left + 0.5))} left.")
    return " ".join(lines)
