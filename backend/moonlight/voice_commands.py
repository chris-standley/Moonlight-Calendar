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

from . import alerts, db

UNITS = {"hour": 3600, "hr": 3600, "minute": 60, "min": 60, "second": 1, "sec": 1}
WORDS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "ninety": 90, "couple of": 2, "few": 3,
}
NUM = r"(\d+(?:\.\d+)?|" + "|".join(sorted((re.escape(w) for w in WORDS), key=len, reverse=True)) + r")"
# "twenty five", "twenty-five"
COMPOUND = r"((?:twenty|thirty|forty|fifty)[ -](?:one|two|three|four|five|six|seven|eight|nine))"
AMOUNT = re.compile(rf"\b(?:{COMPOUND}|{NUM})(?:\s+and\s+a\s+half)?\s*[- ]?\s*(hours?|hrs?|minutes?|mins?|seconds?|secs?)\b"
                    r"(\s+and\s+a\s+half)?", re.I)
HALF_HOUR = re.compile(r"(?<!and a )\bhalf\s+(?:an?\s+)?hour\b", re.I)
TIMER = re.compile(r"\b(timer|countdown|count\s*down)\b", re.I)
FULL = re.compile(r"\b(full[- ]?screen|big|large)\b", re.I)
CANCEL = re.compile(r"\b(cancel|stop|clear|delete|remove|end|dismiss)\b", re.I)
LEFT = re.compile(r"\b(how\s+(?:long|much(?:\s+time)?)|time\s+left|remaining|left)\b", re.I)
LABEL_AFTER = re.compile(r"\bfor\s+(?:the\s+|my\s+|a\s+|an\s+)?([a-z][a-z' ]{1,40}?)\s*$", re.I)
LABEL_BEFORE = re.compile(r"\b(?:an?\s+|the\s+|my\s+)?([a-z][a-z']{1,20}(?:\s+[a-z][a-z']{1,20})?)\s+(?:timer|countdown)\b", re.I)
FILLER = {"set", "start", "make", "a", "an", "the", "my", "full", "screen", "fullscreen", "big", "large", "new", "please",
          "minute", "minutes", "hour", "hours", "second", "seconds", "one", "kitchen", "and", "for", "me", "can", "you"}


def _number(word: str) -> float:
    word = word.lower().replace("-", " ")
    if word in WORDS:
        return WORDS[word]
    if " " in word:
        tens, ones = word.split(" ", 1)
        return WORDS.get(tens, 0) + WORDS.get(ones, 0)
    return float(word)


def duration_of(text: str) -> int:
    """Seconds said in `text` ("1 hour and 15 minutes", "an hour and a half", "half an hour"), 0 if none."""
    total = 1800.0 * len(HALF_HOUR.findall(text))
    for m in AMOUNT.finditer(HALF_HOUR.sub(" ", text)):
        n = _number(m.group(1) or m.group(2))
        unit = UNITS[re.sub(r"s$", "", m.group(3).lower())]
        half = bool(m.group(4)) or "and a half" in m.group(0).lower()
        total += (n + (0.5 if half else 0)) * unit
    return int(round(total))


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
    """What Moonlight should do itself with `text`, or None to pass it to Home Assistant.
    {"do": "start", "seconds", "label", "full"} · {"do": "cancel"} · {"do": "left"}"""
    if not text or not TIMER.search(text):
        return None
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


async def run(cmd: dict, display: dict | None) -> str:
    """Do it; returns what to say."""
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
