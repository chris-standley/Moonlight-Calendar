"""Everyday things said to Assist that Moonlight does itself, so they're quick and never wait on the conversation
agent (voice_commands.py tries these after timers):

    screens   "show the calendar" · "go to music" · "open the shopping list"
    music     "pause" · "stop the music" · "play" · "skip" · "next song" · "previous track" · "turn it up" ·
              "volume to 4" · "what's playing?" · "play Fleetwood Mac"
    chores    "tick off Tom's teeth" · "mark reading as done" · "Amy has done her bed" (list items too: "tick off milk")
    lists     "add milk to the shopping list" · "put batteries on the to do list"
    calendar  "add dentist to the calendar tomorrow at half past 3" · "add an event football on Saturday at 10 for Tom"
              "what's on today?" · "what have we got on Friday?"

Each parse_* only reads the words; run() does it on the asking screen, or returns None when it turns out not to be
Moonlight's (no list by that name: Home Assistant may have one) so the words go on to Home Assistant after all.
"""
from __future__ import annotations

import difflib
import re
from datetime import date, datetime, timedelta
from typing import Any

from fastapi import HTTPException

from . import db, media, music
from .routes import calendar as cal_routes, chores as chore_routes, lists as list_routes
from .voice_when import spoken_day, spoken_time, when_of

PLEASE = r"^(?:(?:hey |ok |okay )?(?:please |can you |could you |would you |will you )*)"
END = r"(?:\s+please)?[.!?]*$"

# ---------------------------------------------------------------- screens

TABS = {  # words for each section (Settings stays behind its PIN, so it isn't one)
    "today": ["today", "home", "home screen", "dashboard", "overview"],
    "calendar": ["calendar", "calendars", "diary", "schedule", "week", "events", "agenda"],
    "chores": ["chores", "chore chart", "chore", "jobs", "tasks", "jobs list"],
    "rewards": ["rewards", "reward chart", "stars", "points"],
    "meals": ["meals", "meal plan", "meal planner", "dinners", "menu"],
    "recipes": ["recipes", "recipe", "cookbook", "cookbooks"],
    "lists": ["lists", "list", "shopping list", "shopping", "to do list", "to do", "todo list", "grocery list"],
    "music": ["music", "music player", "songs", "player", "sonos", "spotify"],
    "nursery": ["nursery", "tapestry"],
    "security": ["security", "cameras", "camera", "alarm", "cctv", "doorbell"],
    "energy": ["energy", "solar", "power", "electricity", "battery", "batteries"],
}
TAB_WORDS = {w: tab for tab, words in TABS.items() for w in words}
GO = re.compile(PLEASE + r"(?:show(?: me)?|open(?: up)?|go to|go back to|switch to|change to|take me to|bring up|display|"
                r"jump to|put on)\s+(?:the\s+|my\s+|our\s+)?(?P<what>[a-z' -]+?)(?:\s+(?:page|screen|tab|view|section))?"
                + END, re.I)

# ---------------------------------------------------------------- music

MUSIC_NOUN = r"(?:\s+(?:the\s+)?(?:music|song|songs|track|playback|playing|it|audio|radio|tune|tunes))?"
PAUSE = re.compile(PLEASE + r"(?:pause|stop|halt)" + MUSIC_NOUN + END, re.I)
RESUME = re.compile(PLEASE + r"(?:play|resume|start|unpause|continue|carry on)" + MUSIC_NOUN + r"(?:\s+again)?(?:\s+playing)?" + END, re.I)
NEXT = re.compile(PLEASE + r"(?:skip(?:\s+(?:this|the))?(?:\s+(?:song|track|one|it))?|next(?:\s+(?:song|track|one))?|"
                  r"play\s+the\s+next\s+(?:song|track|one))" + END, re.I)
PREVIOUS = re.compile(PLEASE + r"(?:previous(?:\s+(?:song|track|one))?|go\s+back(?:\s+a\s+(?:song|track))?|"
                      r"(?:play\s+)?(?:the\s+)?last\s+(?:song|track)(?:\s+again)?|back\s+a\s+(?:song|track))" + END, re.I)
LOUDER = re.compile(PLEASE + r"(?:turn\s+(?:it|the\s+(?:music|volume))\s+up|volume\s+up|louder|turn\s+up\s+the\s+"
                    r"(?:music|volume)|(?:make\s+it\s+)?louder|increase\s+the\s+volume)" + END, re.I)
QUIETER = re.compile(PLEASE + r"(?:turn\s+(?:it|the\s+(?:music|volume))\s+down|volume\s+down|quieter|turn\s+down\s+the\s+"
                     r"(?:music|volume)|(?:make\s+it\s+)?quieter|decrease\s+the\s+volume|lower\s+the\s+volume)" + END, re.I)
VOLUME_TO = re.compile(PLEASE + r"(?:set\s+(?:the\s+)?)?volume\s+(?:to\s+)?(?P<n>\d{1,3})(?:\s*(?:%|percent))?" + END, re.I)
WHATS_PLAYING = re.compile(PLEASE + r"(?:what(?:'s| is)\s+(?:this\s+song|playing|this|the\s+song|on)(?:\s+now)?|"
                           r"what\s+song\s+is\s+(?:this|playing)|who\s+(?:is\s+this|sings\s+this))" + END, re.I)
PLAY_THING = re.compile(PLEASE + r"(?:play|put\s+on)\s+(?:some\s+)?(?P<what>.+?)" + END, re.I)
ELSEWHERE = re.compile(r"\s+(?:in|on)\s+(?:the\s+)?[a-z' ]+(?:speaker|room)?$|\s+everywhere$", re.I)

# ---------------------------------------------------------------- chores and list items

DONE = r"(?:done|complete|completed|finished)"
TICK = [
    (re.compile(PLEASE + r"(?:tick|check|cross|mark)\s+off\s+(?P<what>.+?)" + END, re.I), True),
    (re.compile(PLEASE + r"(?:tick|check|cross|mark)\s+(?P<what>.+?)\s+off" + END, re.I), True),
    (re.compile(PLEASE + r"mark\s+(?P<what>.+?)\s+(?:as\s+)?" + DONE + END, re.I), True),
    (re.compile(PLEASE + r"(?:complete|finish)\s+(?P<what>.+?)" + END, re.I), False),
    (re.compile(r"^(?P<who>i|we|[a-z]+)(?:'ve|\s+has|\s+have)\s+(?:just\s+)?" + DONE + r"\s+(?P<what>.+?)" + END, re.I), False),
    (re.compile(r"^(?P<what>.+?)\s+(?:is|are|has\s+been|have\s+been)\s+(?:all\s+)?" + DONE + END, re.I), False),
]
CHORE_FILLER = {"the", "my", "his", "her", "their", "our", "your", "a", "an", "chore", "job", "task", "for", "of", "s",
                "today", "todays", "all", "please", "as", "item"}

# ---------------------------------------------------------------- lists

CAL_WORDS = r"(?:family\s+)?(?:calendar|diary|schedule|agenda)"
ADD_ITEM = re.compile(PLEASE + r"(?:add|put|pop|stick|write)\s+(?P<item>.+?)\s+(?:to|on|onto|in|into)\s+"
                      r"(?:the\s+|my\s+|our\s+|a\s+)?(?P<list>.+?)" + END, re.I)

# ---------------------------------------------------------------- calendar

ADD_EVENT = [
    re.compile(PLEASE + r"(?:add|put|pop|stick|write|schedule|book|create|make)\s+(?:an?\s+)?(?:event\s+|appointment\s+|"
               r"entry\s+)?(?:called\s+|for\s+)?(?P<body>.+?)\s+(?:in|on|to|into)\s+(?:the\s+|my\s+|our\s+)?"
               + CAL_WORDS + r"(?P<after>.*?)" + END, re.I),
    re.compile(PLEASE + r"(?:add|create|make|new|book|set\s+up)\s+(?:an?\s+|another\s+)?(?:new\s+)?(?:calendar\s+)?"
               r"(?:event|appointment|entry)\b(?:\s+(?:called|for|named))?(?P<body>.*?)" + END, re.I),
    re.compile(PLEASE + r"schedule\s+(?P<body>.+?)" + END, re.I),
]
WHATS_ON = re.compile(PLEASE + r"(?:what(?:'s| is)\s+(?:on|happening|planned|in\s+the\s+calendar|on\s+the\s+calendar)|"
                      r"what\s+(?:have|has)\s+(?:we|i)\s+got(?:\s+on)?|what\s+(?:are|do)\s+(?:we|i)\s+(?:doing|have(?:\s+on)?)|"
                      r"(?:is\s+there\s+)?anything\s+on|what's\s+the\s+plan)(?P<when>.*?)" + END, re.I)


DAY_FILLER = {"for", "us", "me", "the", "calendar", "diary", "in", "on", "this", "we", "have", "got", "planned", "then"}


def _only_a_day(said: str) -> bool:
    """ "what's on" + a day ("tomorrow", "on Friday"), not "what's on the radio"."""
    return all(w in DAY_FILLER for w in _words(when_of(said, datetime.now()).rest))


def parse(text: str) -> dict | None:
    t = re.sub(r"\s+", " ", text or "").strip()
    if not t:
        return None
    if (m := WHATS_ON.match(t)) and _only_a_day(m.group("when")):
        return {"do": "whats_on", "when": m.group("when").strip()}
    for rx in ADD_EVENT:
        if m := rx.match(t):
            body = " ".join(x for x in (m.group("body"), m.groupdict().get("after") or "") if x).strip()
            if rx is ADD_EVENT[2] and not when_of(body, datetime.now()).day:
                continue  # "schedule" without a day isn't clearly an event
            return {"do": "add_event", "text": body}
    if (m := ADD_ITEM.match(t)) and not re.fullmatch(CAL_WORDS, m.group("list"), re.I):
        return {"do": "add_item", "item": m.group("item"), "list": m.group("list")}
    for rx, strict in TICK:
        if m := rx.match(t):
            return {"do": "tick", "what": m.group("what"), "who": m.groupdict().get("who"), "strict": strict}
    if m := GO.match(t):
        what = m.group("what").lower().strip()
        if what in TAB_WORDS:
            return {"do": "go", "tab": TAB_WORDS[what]}
    for rx, action in ((PAUSE, "pause"), (RESUME, "play"), (NEXT, "next"), (PREVIOUS, "previous"),
                       (LOUDER, "louder"), (QUIETER, "quieter"), (WHATS_PLAYING, "whats_playing")):
        if rx.match(t):
            return {"do": "music", "action": action}
    if m := VOLUME_TO.match(t):
        return {"do": "music", "action": "volume", "value": int(m.group("n"))}
    if (m := PLAY_THING.match(t)) and not ELSEWHERE.search(m.group("what")):
        what = m.group("what").lower()
        if re.fullmatch(r"(?:the\s+)?(?:music|something|anything|a\s+song|songs|tunes|my\s+music)", what):
            return {"do": "music", "action": "play"}
        return {"do": "music", "action": "search", "query": m.group("what")}
    return None


async def run(cmd: dict, ctx: dict) -> dict | None:
    """Do it on the asking screen (ctx: display, layout): {"say", "go"?}, or None to leave it to Home Assistant."""
    try:
        if cmd["do"] == "go":
            return {"say": f"Here's {_tab_name(cmd['tab'])}.", "go": cmd["tab"]}
        if cmd["do"] == "music":
            return await _music(cmd, ctx)
        if cmd["do"] == "tick":
            return await _tick(cmd)
        if cmd["do"] == "add_item":
            return await _add_item(cmd)
        if cmd["do"] == "add_event":
            return await _add_event(cmd)
        if cmd["do"] == "whats_on":
            return _whats_on(cmd)
    except HTTPException as e:
        return {"say": f"Sorry, I couldn't: {e.detail}." if isinstance(e.detail, str) else "Sorry, I couldn't do that."}
    except media.MediaError as e:
        return {"say": f"Sorry, the speaker didn't answer: {e}."}
    return None


def _tab_name(tab: str) -> str:
    return {"today": "today", "lists": "your lists", "music": "the music", "security": "security",
            "energy": "the energy", "nursery": "the nursery"}.get(tab, f"the {tab}")


# ---------------------------------------------------------------- music

async def _music(cmd: dict, ctx: dict) -> dict:
    svc = media.service()
    if svc is None:
        return {"say": "Moonlight isn't connected to Home Assistant."}
    entity = media.entity_for(ctx.get("layout") or "compact", ctx.get("display"))
    if not entity:
        return {"say": "This screen hasn't got a speaker. Choose one in Settings, Screens."}
    eff, state, _err, _ = await media.resolve(svc, entity)
    attrs = (state or {}).get("attributes") or {}
    playing = str((state or {}).get("state")) == "playing"
    action = cmd["action"]
    if action == "pause":
        if not playing:
            return {"say": "Nothing's playing."}
        await svc.command(eff, "pause")
        return {"say": "Paused."}
    if action == "play":
        if playing:
            return {"say": "It's already playing."}
        if attrs.get("media_title"):
            await svc.command(eff, "play")
            return {"say": "Playing."}
        favs = await svc.favourites(entity)
        if favs:
            await svc.play_favourite(entity, favs[0]["uri"])
            return {"say": f"Playing {favs[0]['name']}."}
        return {"say": "There's nothing queued. Try saying play, then an artist or a playlist."}
    if action in ("next", "previous"):
        if not attrs.get("media_title"):
            return {"say": "Nothing's playing."}
        await svc.command(eff, action)
        return {"say": "Skipped." if action == "next" else "Going back."}
    if action in ("louder", "quieter", "volume"):
        now = attrs.get("volume_level")
        if action == "volume":
            n = cmd["value"]
            level = n / 10 if n <= 10 else n / 100
        else:
            level = (now if isinstance(now, (int, float)) else 0.3) + (0.1 if action == "louder" else -0.1)
        level = round(min(1.0, max(0.0, level)), 2)
        await svc.command(eff, "volume_set", level)
        return {"say": f"Volume {round(level * 10)}."}
    if action == "whats_playing":
        title = attrs.get("media_title")
        if not title:
            return {"say": "Nothing's playing."}
        artist = attrs.get("media_artist")
        return {"say": f"This is {title} by {artist}." if artist else f"This is {title}."}
    # play <something>: the best match in Music Assistant's library and providers
    query = cmd["query"].strip()
    lib = music.for_service(svc)
    sstate, _ = await svc.get_state(entity)
    try:
        found = await lib.search(sstate, query)
    except media.MediaError:
        return {"say": "I can only find music on a Music Assistant speaker."}
    if not found:
        return {"say": f"I couldn't find {query}."}
    best = _best_match(query, found)
    await lib.play(entity, sstate, best["id"], best["type"], "replace")
    by = f" by {best['subtitle']}" if best.get("subtitle") and best["type"] in ("album", "track") else ""
    return {"say": f"Playing {best['title']}{by}."}


def _best_match(query: str, found: list[dict]) -> dict:
    """An exact name first; otherwise artists, then playlists, albums and tracks (Music Assistant's own order)."""
    q = query.lower()
    rank = {"artist": 0, "playlist": 1, "radio": 2, "album": 3, "track": 4}

    def score(it: dict) -> tuple:
        title = it["title"].lower()
        return (0 if title == q else 1 if q in title else 2, rank.get(it["type"], 5))
    return min(found, key=score)


# ---------------------------------------------------------------- chores and list items

def _people(c) -> list[dict]:
    return db.rows(c, "SELECT id, name FROM people ORDER BY sort, name")


def _words(s: str) -> list[str]:
    s = re.sub(r"[^\w' ]", " ", s.lower())
    s = re.sub(r"'s\b|s'\b", " ", s)
    return [w for w in s.replace("'", "").split() if w]


def _who(text: str, people: list[dict]) -> tuple[str | None, str]:
    """The person named in `text` ("Tom's teeth", "teeth for Tom") and the text without them."""
    for p in people:
        name = re.escape(p["name"].split()[0])
        rx = re.compile(rf"\b{name}(?:'s|s'|s)?\b|\bfor\s+{name}\b", re.I)
        if rx.search(text):
            return p["id"], rx.sub(" ", text)
    return None, text


def _similar(said: list[str], title: str) -> float:
    """How well the words said name `title`: all of them in it ("bed" for "Make bed") counts most."""
    words = [w for w in _words(title) if w not in CHORE_FILLER]
    if not words or not said:
        return 0.0
    hits = sum(1 for w in said if any(w == x or (len(w) > 3 and (x.startswith(w) or w.startswith(x))) for x in words))
    ratio = difflib.SequenceMatcher(None, " ".join(said), " ".join(words)).ratio()  # misheard words
    return max(0.8 * hits / len(said) + 0.2 * hits / len(words), ratio)


async def _tick(cmd: dict) -> dict | None:
    with db.connect() as c:
        people = _people(c)
    who = None
    named = (cmd.get("who") or "").lower()
    if named and named not in ("i", "we"):
        who = next((p["id"] for p in people if p["name"].split()[0].lower() == named), None)
        if who is None:
            return None  # "the washing has finished": not about a chore
    pid, rest = _who(cmd["what"], people)
    who = who or pid
    said = [w for w in _words(rest) if w not in CHORE_FILLER]
    names = {p["id"]: p["name"].split()[0] for p in people}
    today = chore_routes.chores_for_day()
    scored = sorted(((_similar(said, ch["title"]), ch) for ch in today if who is None or ch["person_id"] == who),
                    key=lambda x: -x[0])
    good = [(s, ch) for s, ch in scored if s >= 0.6]
    if good:
        top = [ch for s, ch in good if s >= good[0][0] - 0.05]
        open_ = [ch for ch in top if not ch["completed"]] or top
        if len({ch["person_id"] for ch in open_}) > 1:
            who_list = " or ".join(names.get(ch["person_id"], "?") for ch in open_[:3])
            return {"say": f"Whose {open_[0]['title'].lower()}: {who_list}? Say it again with their name."}
        ch = open_[0]
        name = names.get(ch["person_id"], "")
        if ch["completed"]:
            return {"say": f"{name}'s {ch['title'].lower()} is already ticked off."}
        out = await chore_routes.complete_chore(ch["id"], {})
        bal = out["balance"]
        stars = f" {name} has {bal} point{'' if bal == 1 else 's'}." if ch["points"] else ""
        return {"say": f"Ticked off {name}'s {ch['title'].lower()}.{stars}"}
    # Not a chore: an item on a list ("tick off milk")?
    with db.connect() as c:
        items = db.rows(c, "SELECT i.id, i.title, l.name AS list FROM items i JOIN lists l ON l.id = i.list_id "
                           "WHERE i.done = 0")
    words = _words(cmd["what"])
    hits = sorted(((_similar([w for w in words if w not in CHORE_FILLER], it["title"]), it) for it in items),
                  key=lambda x: -x[0])
    if hits and hits[0][0] >= 0.75:
        it = hits[0][1]
        await list_routes.update_item(it["id"], {"done": True})
        return {"say": f"Ticked off {it['title']} on {it['list']}."}
    if not cmd["strict"]:
        return None
    return {"say": f"I couldn't find {cmd['what']} in today's chores or on a list."}


# ---------------------------------------------------------------- lists

def _list_for(c, said: str) -> dict | None:
    name = re.sub(r"\s+list$", "", said.lower().strip()).strip()
    lists = db.rows(c, "SELECT * FROM lists ORDER BY sort, name")

    def plain(s: str) -> str:
        return re.sub(r"\s+list$", "", re.sub(r"[^\w ]", "", s.lower())).strip()
    for lst in lists:
        if plain(lst["name"]) == name:
            return lst
    for lst in lists:
        if name and (name in plain(lst["name"]) or plain(lst["name"]) in name):
            return lst
    kinds = {"grocery": r"shopping|groceries|grocery|food|supermarket|tesco|shop|list|the list",
             "todo": r"to ?do|todo|to-do|jobs|tasks|things to do"}
    for kind, rx in kinds.items():
        if re.fullmatch(rx, name):
            return next((lst for lst in lists if lst["kind"] == kind), None)
    return None


async def _add_item(cmd: dict) -> dict | None:
    with db.connect() as c:
        lst = _list_for(c, cmd["list"])
        if lst is None:
            return None  # maybe one of Home Assistant's to-do lists
        open_titles = {r["title"].lower() for r in db.rows(c, "SELECT title FROM items WHERE list_id = ? AND done = 0",
                                                           (lst["id"],))}
    items = [re.sub(r"^(?:some|a|an)\s+", "", x.strip(" .")).strip() for x in re.split(r",|\s+and then\s+", cmd["item"])]
    items = [x[:1].upper() + x[1:] for x in items if x]
    added, already = [], []
    for title in items:
        if title.lower() in open_titles:
            already.append(title)
            continue
        await list_routes.add_item(lst["id"], {"title": title})
        added.append(title)
    parts = []
    if added:
        parts.append(f"Added {_and(added)} to {lst['name']}.")
    if already:
        parts.append(f"{_and(already)} {'is' if len(already) == 1 else 'are'} already on {lst['name']}.")
    return {"say": " ".join(parts) or "There was nothing to add."}


def _and(xs: list[str]) -> str:
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " and " + xs[-1]


# ---------------------------------------------------------------- calendar

async def _add_event(cmd: dict) -> dict:
    now = datetime.now()
    w = when_of(cmd["text"], now)
    with db.connect() as c:
        people = _people(c)
    person_ids: list[str] = []
    title = w.rest
    while True:  # "for Tom", "Tom's", "for Tom and Amy"
        pid, rest = _who(title, people)
        if pid is None or pid in person_ids:
            break
        person_ids.append(pid)
        title = rest
    title = re.sub(r"\s+", " ", re.sub(r"^\s*(?:and|for|on|at|called|named)\s+|\s+(?:and|for|on|at)\s*$", " ", title)).strip(" ,.")
    title = re.sub(r"^(?:an?|the)\s+", "", title, flags=re.I)
    if not title:
        return {"say": "What's it called? Try: add dentist to the calendar tomorrow at 3."}
    if w.day is None and w.start is None:
        return {"say": f"When is {title}? Try: add {title} to the calendar tomorrow at 3."}
    day = w.day
    if day is None:  # a time with no day: today, or tomorrow when that time has gone
        day = now.date() if w.start > (now.hour, now.minute) else now.date() + timedelta(days=1)
    body: dict[str, Any] = {"title": title[:1].upper() + title[1:], "person_ids": person_ids}
    if w.start is None:
        body.update(all_day=True, start=f"{day.isoformat()}T00:00", end=f"{(day + timedelta(days=1)).isoformat()}T00:00")
    else:
        start = datetime.combine(day, datetime.min.time()).replace(hour=w.start[0], minute=w.start[1])
        if w.end:
            end = start.replace(hour=w.end[0], minute=w.end[1])
            if end <= start:
                end += timedelta(days=1)
        else:
            end = start + timedelta(minutes=w.minutes or 60)
        body.update(all_day=False, start=start.strftime("%Y-%m-%dT%H:%M"), end=end.strftime("%Y-%m-%dT%H:%M"))
    ev = await cal_routes.create_event(body)
    when = spoken_day(day, now.date())
    at = f" at {spoken_time(*w.start)}" if w.start else ""
    names = [p["name"].split()[0] for p in people if p["id"] in person_ids]
    whose = f" for {_and(names)}" if names else ""
    return {"say": f"Added {ev['title']}{whose} {when}{at}."}


def _whats_on(cmd: dict) -> dict:
    now = datetime.now()
    w = when_of(cmd.get("when") or "", now)
    day: date = w.day or now.date()
    events = cal_routes.list_events(day.isoformat(), (day + timedelta(days=1)).isoformat())
    when = spoken_day(day, now.date())
    if not events:
        return {"say": f"Nothing's on {when}." if when != "today" else "Nothing's on today."}
    parts = []
    for ev in events[:6]:
        if ev["all_day"]:
            parts.append(ev["title"])
        else:
            t = datetime.fromisoformat(ev["start"])
            parts.append(f"{ev['title']} at {spoken_time(t.hour, t.minute)}")
    more = f", and {len(events) - 6} more" if len(events) > 6 else ""
    head = when[:1].upper() + when[1:]
    return {"say": f"{head}: {_and(parts)}{more}."}
