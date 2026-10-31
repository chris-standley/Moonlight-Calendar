"""Countdowns: the family's own days, well-known days, public holidays, calendar events and birthdays."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from moonlight import countdowns  # noqa: E402
from moonlight.main import create_app  # noqa: E402

TODAY = "2026-10-31"
GB = {"country": "GB", "subdiv": "ENG"}


@pytest.fixture
def client(tmp_path):
    app = create_app(db_path=str(tmp_path / "c.db"), demo=False, static_dir=tmp_path / "none")
    with TestClient(app) as c:
        yield c


def post(c, path, body, status=200):
    r = c.post(path, json=body)
    assert r.status_code == status, r.text
    return r.json()


def listed(c, today=TODAY):
    r = c.get(f"/api/countdowns?today={today}")
    assert r.status_code == 200, r.text
    return r.json()


def test_special_days():
    assert countdowns.special_date("easter", 2027, GB) == date(2027, 3, 28)
    assert countdowns.special_date("mothers_day", 2027, GB) == date(2027, 3, 7)  # Mothering Sunday
    assert countdowns.special_date("mothers_day", 2027, {"country": "US"}) == date(2027, 5, 9)
    assert countdowns.special_date("fathers_day", 2027, GB) == date(2027, 6, 20)
    assert countdowns.special_date("thanksgiving", 2026, {"country": "US"}) == date(2026, 11, 26)
    assert countdowns.special_date("pancake_day", 2027, GB) == date(2027, 2, 9)
    assert countdowns.next_special("halloween", date(2026, 11, 1), GB) == date(2027, 10, 31)
    assert countdowns.next_special("halloween", date(2026, 10, 31), GB) == date(2026, 10, 31)
    assert countdowns.next_special("holiday:Boxing Day", date(2026, 10, 31), GB) == date(2026, 12, 26)


def test_suggestions_skip_duplicates_and_other_countries():
    s = countdowns.suggestions(date(2026, 10, 31), GB, {"christmas"})
    keys = [x["special"] for x in s]
    assert "bonfire_night" in keys and "thanksgiving" not in keys
    assert "holiday:Christmas Day" not in keys  # the same day as "christmas"
    assert "holiday:Boxing Day" in keys
    assert next(x for x in s if x["special"] == "christmas")["taken"] is True
    assert [x["date"] for x in s] == sorted(x["date"] for x in s)


def test_birthdays_and_leap_days():
    out = countdowns.birthdays([
        {"id": "a", "name": "Mia", "birthday": "2018-11-23"},
        {"id": "b", "name": "Sam", "birthday": "02-29"},
        {"id": "c", "name": "Nobody", "birthday": None},
    ], date(2026, 10, 31))
    mia, sam = out
    assert (mia["date"], mia["days"], mia["turns"], mia["title"]) == ("2026-11-23", 23, 8, "Mia's birthday")
    assert sam["date"] == "2027-02-28" and sam["turns"] is None
    assert countdowns.normalize_birthday("--11-23") == "11-23"
    with pytest.raises(ValueError):
        countdowns.normalize_birthday("2018-13-01")


def test_countdowns_api(client):
    kid = post(client, "/api/people", {"name": "Mia", "color": "#f00", "role": "child", "birthday": "2018-11-23"})
    assert kid["birthday"] == "2018-11-23"
    assert client.post("/api/people", json={"name": "X", "color": "#f00", "birthday": "soon"}).status_code == 400

    xmas = post(client, "/api/countdowns", {"special": "christmas"})
    assert xmas["title"] == "Christmas" and xmas["emoji"] == "🎄" and xmas["kind"] == "special" and xmas["yearly"]
    trip = post(client, "/api/countdowns", {"title": "Holiday in Spain", "emoji": "🏖️", "date": "2027-04-02",
                                            "person_ids": [kid["id"], "gone"]})
    assert trip["person_ids"] == [kid["id"]] and trip["kind"] == "custom"
    anniv = post(client, "/api/countdowns", {"title": "Anniversary", "date": "2015-06-20", "yearly": True})
    post(client, "/api/countdowns", {"title": "Done already", "date": "2026-10-01"})
    post(client, "/api/countdowns", {"title": ""}, status=400)
    post(client, "/api/countdowns", {"special": "nonsense"}, status=400)

    out = listed(client)
    assert [o["title"] for o in out] == ["Mia's birthday", "Christmas", "Holiday in Spain", "Anniversary"]
    assert out[0]["turns"] == 8 and out[0]["days"] == 23
    assert out[1]["date"] == "2026-12-25" and out[1]["days"] == 55
    assert out[3]["date"] == "2027-06-20"
    # On the day itself it's still listed, with 0 days to go.
    assert listed(client, "2026-12-25")[0] == {**listed(client, "2026-12-25")[0], "title": "Christmas", "days": 0}

    r = client.patch(f"/api/countdowns/{trip['id']}", json={"title": "Spain!", "date": "2027-04-03"})
    assert r.status_code == 200 and r.json()["title"] == "Spain!" and r.json()["date"] == "2027-04-03"
    assert client.delete(f"/api/countdowns/{anniv['id']}").status_code == 200
    assert client.delete(f"/api/countdowns/{anniv['id']}").status_code == 404

    sugg = client.get(f"/api/countdowns/suggestions?today={TODAY}").json()
    assert next(s for s in sugg if s["special"] == "christmas")["taken"]

    # Clearing the birthday drops its countdown.
    client.patch(f"/api/people/{kid['id']}", json={"birthday": ""})
    assert all(o["kind"] != "birthday" for o in listed(client))
    assert "countdowns" in client.get(f"/api/summary?date={TODAY}&now={TODAY}T09:00").json()


def test_countdown_follows_its_event(client):
    ev = post(client, "/api/events", {"title": "Half term", "start": "2027-02-15T00:00", "end": "2027-02-20T00:00",
                                      "all_day": True})
    cd = post(client, "/api/countdowns", {"event_id": ev["id"], "emoji": "🏫"})
    assert cd["title"] == "Half term" and cd["kind"] == "event" and cd["date"] == "2027-02-15"
    client.patch(f"/api/events/{ev['id']}", json={"start": "2027-02-16T00:00", "end": "2027-02-21T00:00"})
    assert listed(client)[0]["date"] == "2027-02-16"

    weekly = post(client, "/api/events", {"title": "Swimming", "start": "2026-10-01T17:00", "end": "2026-10-01T18:00",
                                          "repeat": {"freq": "weekly"}})
    post(client, "/api/countdowns", {"event_id": weekly["id"]})
    swim = next(o for o in listed(client) if o["title"] == "Swimming")
    assert swim["date"] == "2026-11-05"  # the next Thursday

    # A deleted event's countdown keeps its last date.
    client.request("DELETE", f"/api/events/{ev['id']}", json={})
    half = next(o for o in listed(client) if o["title"] == "Half term")
    assert half["date"] == "2027-02-15"
