"""Everyday voice commands Moonlight does itself (voice_home.py), and the spoken days and times they read
(voice_when.py). Run from backend/ with `python -m pytest`."""
from __future__ import annotations

import asyncio
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from moonlight import media, voice_commands  # noqa: E402
from moonlight.main import create_app  # noqa: E402
from moonlight.voice_when import time_of, when_of  # noqa: E402
from test_media import KITCHEN, FakeHA, kitchen_state, make_service  # noqa: E402

THU = datetime(2026, 10, 29, 23, 0)  # a Thursday evening


@pytest.fixture
def fake():
    return FakeHA()


@pytest.fixture
def client(tmp_path, fake, monkeypatch):
    monkeypatch.setenv("MOONLIGHT_MEDIA_ENTITY", KITCHEN)
    media.reset()
    media.set_service(make_service(fake))
    app = create_app(db_path=str(tmp_path / "t.db"), demo=False, auth_enabled=False)
    with TestClient(app) as c:
        c.patch("/api/settings", json={"pin": "1234"})
        yield c
    media.reset()


def say(text: str, layout: str = "compact") -> dict | None:
    """What Moonlight does with `text` on an unpaired screen (None: it goes on to Home Assistant)."""
    cmd = voice_commands.parse(text)
    if cmd is None:
        return None
    return asyncio.run(voice_commands.run(cmd, {"display": None, "layout": layout}))


def person(c, name):
    return c.post("/api/people", json={"name": name, "color": "#123456", "role": "child"}).json()


# ---------------------------------------------------------------- days and times

@pytest.mark.parametrize("said,day,start,end,rest", [
    ("dentist tomorrow at half past 3", date(2026, 10, 30), (15, 30), None, "dentist"),
    ("football on Saturday at 10", date(2026, 10, 31), (10, 0), None, "football"),
    ("swimming next Tuesday from 5 to 6pm", date(2026, 11, 3), (17, 0), (18, 0), "swimming"),
    ("Tom's party on the 5th of December at 2pm", date(2026, 12, 5), (14, 0), None, "Tom's party"),
    ("parents evening on 12 November at 6:30 p.m.", date(2026, 11, 12), (18, 30), None, "parents evening"),
    ("haircut the day after tomorrow at quarter to 11", date(2026, 10, 31), (10, 45), None, "haircut"),
    ("cinema on Friday at 7 in the evening", date(2026, 10, 30), (19, 0), None, "cinema"),
    ("book club on the 3rd", date(2026, 11, 3), None, None, "book club"),
    ("bins tonight", date(2026, 10, 29), (19, 0), None, "bins"),
    ("pick up Tom at three thirty", None, (15, 30), None, "pick up Tom"),
    ("trip on March the 2nd", date(2027, 3, 2), None, None, "trip"),
])
def test_when_of(said, day, start, end, rest):
    w = when_of(said, THU)
    assert (w.day, w.start, w.end, w.rest) == (day, start, end, rest)


def test_times():
    assert time_of("3") == (15, 0) and time_of("9") == (9, 0) and time_of("9", "evening") == (21, 0)
    assert time_of("12") == (12, 0) and time_of("noon") == (12, 0) and time_of("midnight") == (0, 0)
    assert time_of("10 a.m.") == (10, 0) and time_of("4 PM") == (16, 0) and time_of("15:45") == (15, 45)
    assert time_of("quarter to seven") == (18, 45) and time_of("twenty past 8") == (8, 20)
    assert time_of("the park") is None
    assert when_of("call mum at 8 pm for half an hour", THU).minutes == 30


# ---------------------------------------------------------------- what stays with Home Assistant

@pytest.mark.parametrize("said", [
    "turn on the kitchen lights", "what's the weather tomorrow?", "show me the weather", "tell me a joke",
    "play music in the lounge", "add a reminder to call mum", "what's on the radio", "the washing has finished",
])
def test_left_to_home_assistant(client, said):
    assert say(said) is None


# ---------------------------------------------------------------- screens

@pytest.mark.parametrize("said,tab", [
    ("show the calendar", "calendar"), ("go to music", "music"), ("open the shopping list", "lists"),
    ("switch to chores please", "chores"), ("show me the cameras", "security"), ("take me home", None),
])
def test_go_to_a_section(client, said, tab):
    done = say(said)
    assert (done or {}).get("go") == tab


# ---------------------------------------------------------------- music

def test_music_controls(client, fake):
    assert say("pause the music") == {"say": "Paused."}
    assert fake.calls[-1][:2] == ("media_player", "media_pause")
    fake.states[KITCHEN]["state"] = "paused"
    asyncio.run(media.service().refresh(KITCHEN))
    assert say("play") == {"say": "Playing."} and fake.calls[-1][1] == "media_play"
    fake.states[KITCHEN]["state"] = "playing"
    asyncio.run(media.service().refresh(KITCHEN))
    assert say("skip this song") == {"say": "Skipped."} and fake.calls[-1][1] == "media_next_track"
    assert say("previous track")["say"] == "Going back."
    assert say("turn it up") == {"say": "Volume 4."}  # from 0.35
    assert fake.calls[-1][2]["volume_level"] == 0.45
    assert say("volume to 2")["say"] == "Volume 2." and fake.calls[-1][2]["volume_level"] == 0.2
    assert say("what's playing?")["say"] == "This is Next Song by The Paper Kites."
    assert say("stop") == {"say": "Paused."}


def test_play_starts_a_favourite_when_nothing_is_queued(client, fake):
    fake.states[KITCHEN] = kitchen_state(state="idle", media_title=None, media_artist=None)
    assert say("start the music") == {"say": "Playing Sunday Kitchen."}
    assert fake.calls[-1][:2] == ("music_assistant", "play_media")


def test_no_speaker_on_this_screen(client, monkeypatch):
    monkeypatch.setenv("MOONLIGHT_MEDIA_ENTITY", "")
    media.reset()
    media.set_service(make_service(FakeHA()))
    assert "speaker" in say("pause")["say"]


# ---------------------------------------------------------------- chores and lists

def test_tick_off_a_chore(client):
    tom, amy = person(client, "Tom"), person(client, "Amy")
    for p in (tom, amy):
        client.post("/api/chores", json={"title": "Brush teeth", "emoji": "🪥", "person_id": p["id"], "points": 2,
                                         "schedule": {"type": "daily"}})
    client.post("/api/chores", json={"title": "Make bed", "person_id": amy["id"], "points": 1,
                                     "schedule": {"type": "daily"}})
    assert say("tick off the teeth")["say"].startswith("Whose brush teeth")  # both have one
    assert say("tick off Tom's teeth") == {"say": "Ticked off Tom's brush teeth. Tom has 2 points."}
    assert say("tick off Tom's teeth")["say"] == "Tom's brush teeth is already ticked off."
    assert say("Amy has done her bed") == {"say": "Ticked off Amy's make bed. Amy has 1 point."}
    done = {c["title"] + c["person_id"]: c["completed"] for c in client.get("/api/chores").json()}
    assert done == {"Brush teeth" + tom["id"]: True, "Brush teeth" + amy["id"]: False, "Make bed" + amy["id"]: True}
    assert "couldn't find" in say("mark the hoovering as done")["say"]


def test_lists(client):
    shop = client.post("/api/lists", json={"name": "Shopping", "emoji": "🛒", "color": "", "kind": "grocery"}).json()
    jobs = client.post("/api/lists", json={"name": "House jobs", "emoji": "", "color": "", "kind": "todo"}).json()
    assert say("add milk to the shopping list") == {"say": "Added Milk to Shopping."}
    assert say("put eggs, bread on the list") == {"say": "Added Eggs and Bread to Shopping."}
    assert say("add milk to shopping")["say"] == "Milk is already on Shopping."
    assert say("add fix the gate to house jobs") == {"say": "Added Fix the gate to House jobs."}
    assert [i["title"] for i in client.get(f"/api/lists/{shop['id']}/items").json()] == ["Milk", "Eggs", "Bread"]
    assert [i["title"] for i in client.get(f"/api/lists/{jobs['id']}/items").json()] == ["Fix the gate"]
    assert say("tick off the bread") == {"say": "Ticked off Bread on Shopping."}
    assert say("add milk to the garden centre list") is None  # not one of Moonlight's: maybe Home Assistant's


# ---------------------------------------------------------------- calendar

def test_add_an_event_and_hear_whats_on(client):
    tom = person(client, "Tom")
    done = say("add dentist to the calendar tomorrow at half past 3 for Tom")
    tomorrow = date.today() + timedelta(days=1)
    assert done == {"say": "Added Dentist for Tom tomorrow at 3:30pm."}
    evs = client.get(f"/api/events?start={tomorrow}&end={tomorrow + timedelta(days=1)}").json()
    assert [(e["title"], e["start"], e["end"], e["person_ids"]) for e in evs] == [
        ("Dentist", f"{tomorrow}T15:30", f"{tomorrow}T16:30", [tom["id"]])]
    assert say("create an event called bin day tomorrow")["say"] == "Added Bin day tomorrow."
    assert say("what's on tomorrow?") == {"say": "Tomorrow: Bin day and Dentist at 3:30pm."}
    assert say("what's on today")["say"] == "Nothing's on today."
    assert say("add football to the calendar")["say"].startswith("When is football?")
