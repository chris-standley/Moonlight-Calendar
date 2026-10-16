"""API tests: run from backend/ with `python -m pytest`."""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from moonlight.main import create_app  # noqa: E402
from moonlight import db  # noqa: E402

PIN = "4321"
SEED = Path(__file__).resolve().parents[2] / "seed" / "demo.json"


@pytest.fixture
def db_file(tmp_path):
    return str(tmp_path / "test.db")


@pytest.fixture
def client(db_file, tmp_path):
    app = create_app(db_path=db_file, demo=False, static_dir=tmp_path / "no-dist")
    with TestClient(app) as c:
        r = c.patch("/api/settings", json={"pin": PIN, "family_name": "Testers"})
        assert r.status_code == 200
        yield c


def person(c, name="Kid", role="child"):
    r = c.post("/api/people", json={"name": name, "color": "#123456", "role": role})
    assert r.status_code == 200, r.text
    return r.json()


def event(c, **kw):
    body = {"title": "E", "person_ids": [], "start": "2026-10-05T09:00", "end": "2026-10-05T10:00"}
    body.update(kw)
    r = c.post("/api/events", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def occ(c, start, end):
    r = c.get(f"/api/events?start={start}&end={end}")
    assert r.status_code == 200, r.text
    return r.json()


def starts(c, start, end, event_id=None):
    return [o["start"] for o in occ(c, start, end) if event_id in (None, o["id"])]


def chore(c, pid, **kw):
    body = {"title": "Tidy", "emoji": "🧹", "person_id": pid, "points": 5, "time_of_day": "morning",
            "schedule": {"type": "daily"}}
    body.update(kw)
    r = c.post("/api/chores", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def balance(c, pid):
    return {p["person_id"]: p["balance"] for p in c.get("/api/points").json()}[pid]


# ---------------------------------------------------------------- events / recurrence

def test_weekly_byday(client):
    # 2026-10-05 is a Monday.
    e = event(client, repeat={"freq": "weekly", "interval": 1, "byday": ["MO", "WE"]})
    assert e["repeat"] == {"freq": "weekly", "interval": 1, "byday": ["MO", "WE"], "until": None}
    o = occ(client, "2026-10-05", "2026-10-19")
    assert [x["start"] for x in o] == ["2026-10-05T09:00", "2026-10-07T09:00",
                                       "2026-10-12T09:00", "2026-10-14T09:00"]
    assert o[1]["end"] == "2026-10-07T10:00"
    assert o[1]["occurrence_id"] == f"{e['id']}@2026-10-07"
    assert all(x["recurring"] for x in o)
    # Nothing before the series starts.
    assert occ(client, "2026-09-01", "2026-10-05") == []


def test_weekly_without_byday_uses_start_weekday(client):
    e = event(client, start="2026-10-08T17:00", end="2026-10-08T18:00",  # Thursday
              repeat={"freq": "weekly", "interval": 1})
    assert starts(client, "2026-10-01", "2026-10-29", e["id"]) == [
        "2026-10-08T17:00", "2026-10-15T17:00", "2026-10-22T17:00"]


def test_weekly_interval_counts_weeks_from_start_week(client):
    # Starts Wednesday; Monday of the start week is before the start so isn't included.
    e = event(client, start="2026-10-07T08:00", end="2026-10-07T08:30",
              repeat={"freq": "weekly", "interval": 2, "byday": ["MO", "WE"]})
    assert starts(client, "2026-10-01", "2026-11-01", e["id"]) == [
        "2026-10-07T08:00", "2026-10-19T08:00", "2026-10-21T08:00"]


def test_daily_interval_and_until(client):
    e = event(client, start="2026-10-01T07:00", end="2026-10-01T07:30",
              repeat={"freq": "daily", "interval": 3, "until": "2026-10-13"})
    assert starts(client, "2026-10-05", "2026-11-01", e["id"]) == [
        "2026-10-07T07:00", "2026-10-10T07:00", "2026-10-13T07:00"]
    every_day = event(client, start="2026-10-01T06:00", end="2026-10-01T06:10",
                      repeat={"freq": "daily", "interval": 1})
    assert len(starts(client, "2026-10-10", "2026-10-17", every_day["id"])) == 7


def test_monthly_skips_short_months_and_interval(client):
    e = event(client, start="2026-01-31T12:00", end="2026-01-31T13:00", repeat={"freq": "monthly", "interval": 1})
    assert starts(client, "2026-01-01", "2026-06-01", e["id"]) == [
        "2026-01-31T12:00", "2026-03-31T12:00", "2026-05-31T12:00"]
    e2 = event(client, start="2026-01-15T12:00", end="2026-01-15T13:00",
               repeat={"freq": "monthly", "interval": 2, "until": "2026-07-15"})
    assert starts(client, "2026-01-01", "2027-01-01", e2["id"]) == [
        "2026-01-15T12:00", "2026-03-15T12:00", "2026-05-15T12:00", "2026-07-15T12:00"]


def test_multiday_all_day_overlap(client):
    e = event(client, title="Trip", all_day=True, start="2026-10-08T00:00", end="2026-10-11T00:00")
    assert (e["start"], e["end"], e["all_day"]) == ("2026-10-08T00:00", "2026-10-11T00:00", True)
    assert len(occ(client, "2026-10-10", "2026-10-11")) == 1   # last day
    assert len(occ(client, "2026-10-01", "2026-10-08")) == 0   # ends before
    assert len(occ(client, "2026-10-11", "2026-10-12")) == 0   # end is exclusive
    # Recurring multi-day event that starts before the window still shows up.
    r = event(client, title="Weekend away", all_day=True, start="2026-10-03T00:00", end="2026-10-05T00:00",
              repeat={"freq": "weekly", "interval": 1})  # Sat+Sun every week
    o = [x for x in occ(client, "2026-10-11", "2026-10-12") if x["id"] == r["id"]]
    assert [x["occurrence_id"] for x in o] == [f"{r['id']}@2026-10-10"]


def test_event_patch_delete_and_sorting(client):
    p = person(client)
    a = event(client, title="Late", start="2026-10-05T15:00", end="2026-10-05T16:00", person_ids=[p["id"]])
    event(client, title="Early", start="2026-10-05T08:00", end="2026-10-05T09:00")
    o = occ(client, "2026-10-05", "2026-10-06")
    assert [x["title"] for x in o] == ["Early", "Late"]
    assert o[1]["recurring"] is False and o[1]["person_ids"] == [p["id"]]
    r = client.patch(f"/api/events/{a['id']}", json={"repeat": {"freq": "daily", "interval": 1}})
    assert r.status_code == 200 and r.json()["title"] == "Late"
    assert len(starts(client, "2026-10-05", "2026-10-08", a["id"])) == 3
    assert client.delete(f"/api/events/{a['id']}").json() == {"ok": True}
    assert client.delete(f"/api/events/{a['id']}").status_code == 404
    assert client.post("/api/events", json={"title": "x", "start": "nope", "end": "nope"}).status_code == 400
    assert client.post("/api/events", json={"title": "x", "start": "2026-10-05T09:00", "end": "2026-10-05T10:00",
                                             "repeat": {"freq": "weekly", "interval": 0}}).status_code == 400


def test_stale_person_ids_are_dropped(client, db_file):
    a, b = person(client, "Ann"), person(client, "Ben")
    ev = event(client, title="Swim", person_ids=[a["id"], b["id"]])
    # An id left behind by a person who no longer exists (e.g. removed sample data).
    with sqlite3.connect(db_file) as c:
        c.execute("UPDATE events SET person_ids = ? WHERE id = ?",
                  (json.dumps([a["id"], b["id"], "p_gone"]), ev["id"]))
    assert client.get(f"/api/events/{ev['id']}").json()["person_ids"] == [a["id"], b["id"]]
    assert occ(client, "2026-10-05", "2026-10-06")[0]["person_ids"] == [a["id"], b["id"]]
    # A screen still holding the stale id can take someone off the event.
    r = client.patch(f"/api/events/{ev['id']}", json={"person_ids": [a["id"], "p_gone"]})
    assert r.status_code == 200, r.text
    assert r.json()["person_ids"] == [a["id"]]
    r = client.post("/api/events", json={"title": "x", "person_ids": ["p_gone"], "start": "2026-10-05T09:00",
                                         "end": "2026-10-05T10:00"})
    assert r.status_code == 200 and r.json()["person_ids"] == []


# ---------------------------------------------------------------- chores

def test_chore_due_dates(client):
    p = person(client)
    daily = chore(client, p["id"], title="Daily")
    weekly = chore(client, p["id"], title="Weekly", schedule={"type": "weekly", "days": ["MO", "TH"]})
    once = chore(client, p["id"], title="Once", schedule={"type": "once", "date": "2026-10-07"})

    def due(d):
        return {x["id"] for x in client.get(f"/api/chores?date={d}").json()}

    assert due("2026-10-05") == {daily["id"], weekly["id"]}            # Monday
    assert due("2026-10-07") == {daily["id"], once["id"]}              # Wednesday
    assert due("2026-10-08") == {daily["id"], weekly["id"]}            # Thursday
    day = client.get("/api/chores?date=2026-10-05").json()[0]
    assert day["date"] == "2026-10-05" and day["completed"] is False and day["completed_at"] is None
    assert len(client.get("/api/chores/all").json()) == 3
    assert client.post("/api/chores", json={"title": "x", "person_id": p["id"],
                                             "schedule": {"type": "weekly", "days": []}}).status_code == 400


def test_streak_rule(client):
    p = person(client)
    ch = chore(client, p["id"])
    d = date(2026, 10, 10)

    def done(n):
        client.post(f"/api/chores/{ch['id']}/complete", json={"date": (d - timedelta(days=n)).isoformat()})

    def streak():
        return client.get(f"/api/chores?date={d}").json()[0]["streak"]

    for n in (1, 2, 3, 5):
        done(n)
    assert streak() == 3          # today not done: start yesterday, stop at the gap on day 4
    done(0)
    assert streak() == 4          # today counts once completed
    done(4)
    assert streak() == 6

    # Weekly chore: non-due days are skipped, not gaps.
    w = chore(client, p["id"], title="Plants", schedule={"type": "weekly", "days": ["MO", "TH"]})
    for day in ("2026-09-28", "2026-10-01", "2026-10-05"):
        client.post(f"/api/chores/{w['id']}/complete", json={"date": day})
    thu = [x for x in client.get("/api/chores?date=2026-10-08").json() if x["id"] == w["id"]][0]
    assert thu["streak"] == 3 and thu["completed"] is False


def test_complete_undo_idempotent_and_ledger(client):
    p = person(client)
    ch = chore(client, p["id"], title="Empty dishwasher", emoji="🧽", points=5)
    url = f"/api/chores/{ch['id']}/complete"
    assert client.post(url, json={"date": "2026-10-10"}).json() == {"completed": True, "balance": 5}
    assert client.post(url, json={"date": "2026-10-10"}).json() == {"completed": True, "balance": 5}
    row = client.get("/api/chores?date=2026-10-10").json()[0]
    assert row["completed"] is True and row["completed_at"]
    assert client.post(url, json={"date": "2026-10-11"}).json()["balance"] == 10
    assert client.delete(url + "?date=2026-10-10").json() == {"completed": False, "balance": 5}
    assert client.delete(url + "?date=2026-10-10").json() == {"completed": False, "balance": 5}
    assert balance(client, p["id"]) == 5
    ledger = client.get(f"/api/points/{p['id']}/ledger").json()
    assert [(x["change"], x["reason"]) for x in ledger] == [
        (-5, "Undo: Empty dishwasher"), (5, "🧽 Empty dishwasher"), (5, "🧽 Empty dishwasher")]
    assert set(ledger[0]) == {"id", "person_id", "change", "reason", "at"}
    assert sum(x["change"] for x in ledger) == balance(client, p["id"])


def test_points_adjust_requires_pin(client):
    p = person(client)
    assert client.post("/api/points/adjust", json={"person_id": p["id"], "change": 10, "reason": "x",
                                                    "pin": "0000"}).status_code == 403
    r = client.post("/api/points/adjust", json={"person_id": p["id"], "change": 10, "reason": "Bonus", "pin": PIN})
    assert r.json() == {"balance": 10}


# ---------------------------------------------------------------- rewards

def test_reward_redeem(client):
    kid = person(client)
    other = person(client, "Other")
    rw = client.post("/api/rewards", json={"title": "Ice cream", "emoji": "🍦", "cost": 25, "person_id": None}).json()
    assert rw["person_id"] is None and rw["cost"] == 25
    client.post("/api/points/adjust", json={"person_id": kid["id"], "change": 20, "reason": "seed", "pin": PIN})
    url = f"/api/rewards/{rw['id']}/redeem"
    r = client.post(url, json={"person_id": kid["id"], "pin": "9999"})
    assert r.status_code == 403 and "detail" in r.json()
    r = client.post(url, json={"person_id": kid["id"], "pin": PIN})
    assert r.status_code == 400 and r.json()["detail"]
    client.post("/api/points/adjust", json={"person_id": kid["id"], "change": 10, "reason": "more", "pin": PIN})
    assert client.post(url, json={"person_id": kid["id"], "pin": PIN}).json() == {"balance": 5}
    assert client.get(f"/api/points/{kid['id']}/ledger").json()[0]["reason"] == "🍦 Ice cream"
    personal = client.post("/api/rewards", json={"title": "Lego", "emoji": "🧱", "cost": 1,
                                                  "person_id": other["id"]}).json()
    assert client.post(f"/api/rewards/{personal['id']}/redeem",
                       json={"person_id": kid["id"], "pin": PIN}).status_code == 400
    assert client.delete(f"/api/rewards/{personal['id']}").json() == {"ok": True}
    assert [x["id"] for x in client.get("/api/rewards").json()] == [rw["id"]]


# ---------------------------------------------------------------- lists

def test_list_item_ordering(client):
    lst = client.post("/api/lists", json={"name": "Shop", "emoji": "🛒", "color": "#000", "kind": "grocery"}).json()
    assert (lst["open_count"], lst["done_count"], lst["kind"]) == (0, 0, "grocery")
    lid = lst["id"]
    ids = {t: client.post(f"/api/lists/{lid}/items", json={"title": t}).json()["id"] for t in "abcd"}
    client.patch(f"/api/items/{ids['b']}", json={"done": True})
    client.patch(f"/api/items/{ids['a']}", json={"done": True})

    def titles():
        return [(i["title"], i["done"]) for i in client.get(f"/api/lists/{lid}/items").json()]

    # Open by sort, then done by done-time newest first.
    assert titles() == [("c", False), ("d", False), ("a", True), ("b", True)]
    client.patch(f"/api/items/{ids['b']}", json={"done": False})   # un-done goes to the bottom of open
    assert titles() == [("c", False), ("d", False), ("b", False), ("a", True)]
    lst = [x for x in client.get("/api/lists").json() if x["id"] == lid][0]
    assert (lst["open_count"], lst["done_count"]) == (3, 1)
    client.post(f"/api/lists/{lid}/clear-done")
    assert titles() == [("c", False), ("d", False), ("b", False)]
    item = client.patch(f"/api/items/{ids['c']}", json={"title": "C!", "due": "2026-10-12"}).json()
    assert item["title"] == "C!" and item["due"] == "2026-10-12" and item["list_id"] == lid
    assert client.delete(f"/api/items/{ids['c']}").json() == {"ok": True}
    assert client.delete(f"/api/lists/{lid}").json() == {"ok": True}
    assert client.get(f"/api/lists/{lid}/items").status_code == 404


# ---------------------------------------------------------------- meals / recipes

def test_meals_range(client):
    for d, slot, t in [("2026-10-04", "dinner", "Before"), ("2026-10-05", "dinner", "Mon dinner"),
                       ("2026-10-05", "breakfast", "Mon bfast"), ("2026-10-11", "lunch", "Sun lunch"),
                       ("2026-10-12", "dinner", "After")]:
        assert client.post("/api/meals", json={"date": d, "slot": slot, "title": t}).status_code == 200
    meals = client.get("/api/meals?start=2026-10-05&end=2026-10-12").json()
    assert [m["title"] for m in meals] == ["Mon bfast", "Mon dinner", "Sun lunch"]
    assert set(meals[0]) == {"id", "date", "slot", "title", "notes", "recipe_id"}
    m = client.patch(f"/api/meals/{meals[0]['id']}", json={"date": "2026-10-12"}).json()
    assert m["date"] == "2026-10-12"
    assert len(client.get("/api/meals?start=2026-10-05&end=2026-10-12").json()) == 2
    assert client.post("/api/meals", json={"date": "2026-10-05", "slot": "brunch", "title": "x"}).status_code == 400


def test_recipe_edit_and_delete(client):
    rc = client.post("/api/recipes", json={"title": "Chilli", "emoji": "🌶️", "minutes": 40,
                                           "ingredients": ["Beans", " ", "Mince"]}).json()
    assert [i["text"] for i in rc["ingredients"]] == ["Beans", "Mince"]
    r = client.patch(f"/api/recipes/{rc['id']}", json={"title": "Veggie chilli", "ingredients": ["Beans", "Peppers"],
                                                      "minutes": None, "url": "https://example.com/chilli"})
    got = r.json()
    assert {k: got[k] for k in ("id", "title", "emoji", "minutes", "url")} == {
        "id": rc["id"], "title": "Veggie chilli", "emoji": "🌶️", "minutes": None, "url": "https://example.com/chilli"}
    assert [i["text"] for i in got["ingredients"]] == ["Beans", "Peppers"]
    assert client.patch(f"/api/recipes/{rc['id']}", json={"title": " "}).status_code == 400
    assert client.patch(f"/api/recipes/{rc['id']}", json={"minutes": -5}).status_code == 400
    assert client.patch("/api/recipes/nope", json={"title": "x"}).status_code == 404
    meal = client.post("/api/meals", json={"date": "2026-10-12", "slot": "dinner", "title": "Veggie chilli",
                                           "recipe_id": rc["id"]}).json()
    assert client.delete(f"/api/recipes/{rc['id']}").json() == {"ok": True}
    assert client.delete(f"/api/recipes/{rc['id']}").status_code == 404
    assert all(x["id"] != rc["id"] for x in client.get("/api/recipes").json())
    kept = [m for m in client.get("/api/meals?start=2026-10-12&end=2026-10-13").json() if m["id"] == meal["id"]][0]
    assert kept["title"] == "Veggie chilli" and kept["recipe_id"] is None


def test_recipe_to_list(client):
    rc = client.post("/api/recipes", json={"title": "Tacos", "emoji": "🌮", "minutes": 25,
                                           "ingredients": ["Tortillas", "Lime"], "url": None}).json()
    assert [i["text"] for i in rc["ingredients"]] == ["Tortillas", "Lime"]
    lid = client.post("/api/lists", json={"name": "Shop", "emoji": "", "color": "", "kind": "grocery"}).json()["id"]
    assert client.post(f"/api/recipes/{rc['id']}/to-list", json={"list_id": lid}).json() == {"added": 2}
    assert [i["title"] for i in client.get(f"/api/lists/{lid}/items").json()] == ["Tortillas", "Lime"]
    assert client.post(f"/api/recipes/{rc['id']}/to-list", json={"list_id": "nope"}).status_code == 404
    meal = client.post("/api/meals", json={"date": "2026-10-05", "slot": "dinner", "title": "Tacos",
                                           "recipe_id": rc["id"]}).json()
    assert meal["recipe_id"] == rc["id"]


# ---------------------------------------------------------------- settings / PIN

def test_change_pin(client):
    bad = client.patch("/api/settings", json={"pin": PIN, "new_pin": "12a4"})
    assert bad.status_code == 400 and "4 digits" in bad.json()["detail"]
    assert client.patch("/api/settings", json={"pin": "0000", "new_pin": "2468"}).status_code == 403
    assert client.post("/api/pin/verify", json={"pin": PIN}).json() == {"ok": True}  # unchanged so far
    assert client.patch("/api/settings", json={"pin": PIN, "new_pin": "2468"}).status_code == 200
    assert client.post("/api/pin/verify", json={"pin": "2468"}).json() == {"ok": True}
    assert client.post("/api/pin/verify", json={"pin": PIN}).json() == {"ok": False}
    assert client.patch("/api/settings", json={"week_start": "sunday", "pin": PIN}).status_code == 403


def test_settings_pin(client, db_file):
    s = client.get("/api/settings").json()
    s = {k: s[k] for k in ("family_name", "week_start", "temp_unit", "pin_set", "chore_approval", "timezone")}  # + feature keys
    assert s == {"family_name": "Testers", "week_start": "monday", "temp_unit": "C",
                 "pin_set": True, "chore_approval": False, "timezone": "Europe/London"}
    assert client.patch("/api/settings", json={"week_start": "sunday"}).status_code == 400
    assert client.patch("/api/settings", json={"week_start": "sunday", "pin": "0000"}).status_code == 403
    r = client.patch("/api/settings", json={"week_start": "sunday", "temp_unit": "F", "chore_approval": True,
                                            "pin": PIN})
    assert r.status_code == 200
    assert r.json()["week_start"] == "sunday" and r.json()["temp_unit"] == "F" and r.json()["chore_approval"] is True
    assert client.patch("/api/settings", json={"week_start": "friday", "pin": PIN}).status_code == 400
    assert client.post("/api/pin/verify", json={"pin": PIN}).json() == {"ok": True}
    assert client.post("/api/pin/verify", json={"pin": "1111"}).json() == {"ok": False}
    # Stored hashed, never in clear.
    raw = sqlite3.connect(db_file).execute("SELECT value FROM settings WHERE key='pin_hash'").fetchone()[0]
    assert PIN not in raw and "pbkdf2" in raw
    # Deleting a person needs the PIN.
    p = person(client)
    assert client.request("DELETE", f"/api/people/{p['id']}", json={"pin": "0"}).status_code == 403
    assert client.request("DELETE", f"/api/people/{p['id']}", json={"pin": PIN}).json() == {"ok": True}


def test_timezone_default_from_env(monkeypatch, tmp_path):
    # The add-on exports Home Assistant's zone as MOONLIGHT_TIMEZONE; it is the default until one is saved.
    monkeypatch.setenv("MOONLIGHT_TIMEZONE", "America/Chicago")
    app = create_app(db_path=str(tmp_path / "tz.db"), demo=False, static_dir=tmp_path / "no-dist")
    with TestClient(app) as c:
        assert c.get("/api/settings").json()["timezone"] == "America/Chicago"
        assert c.patch("/api/settings", json={"pin": PIN, "timezone": "Asia/Tokyo"}).status_code == 200
        assert c.get("/api/settings").json()["timezone"] == "Asia/Tokyo"
    # The demo seed stores the env zone too.
    app = create_app(db_path=str(tmp_path / "demo.db"), demo=True, seed_path=SEED, static_dir=tmp_path / "no-dist")
    with TestClient(app) as c:
        assert c.get("/api/settings").json()["timezone"] == "America/Chicago"
    # Invalid or empty values fall back to Europe/London.
    monkeypatch.setenv("MOONLIGHT_TIMEZONE", "Mars/Base")
    assert db.default_timezone() == "Europe/London"
    monkeypatch.setenv("MOONLIGHT_TIMEZONE", "")
    assert db.default_timezone() == "Europe/London"


def test_people(client):
    a = person(client, "Mary Jane", "adult")
    b = person(client, "leo")
    assert a["initials"] == "MJ" and b["initials"] == "L" and a["role"] == "adult"
    assert [p["name"] for p in client.get("/api/people").json()] == ["Mary Jane", "leo"]
    client.patch(f"/api/people/{a['id']}", json={"sort": 5})
    assert [p["name"] for p in client.get("/api/people").json()] == ["leo", "Mary Jane"]
    assert client.post("/api/people", json={"name": "X", "color": "#fff", "role": "pet"}).status_code == 400


def test_people_validation_and_edit(client):
    p = person(client, "Sam", "adult")
    bad_bodies = [
        {"name": "", "color": "#123456"},
        {"name": "   ", "color": "#123456"},
        {"name": "x" * 41, "color": "#123456"},
        {"name": "Sam", "color": "red"},
        {"name": "Sam", "color": "#ff"},
        {"name": "Sam", "color": "#12345G"},
        {"name": "Sam", "color": "123456"},
        {"name": "Sam"},
    ]
    for b in bad_bodies:
        assert client.post("/api/people", json=b).status_code == 400, b
    assert client.post("/api/people", json={"name": "No role", "color": "#abcdef"}).json()["role"] == "child"
    assert client.post("/api/people", json={"name": "Short", "color": "#f0a"}).json()["color"] == "#FF00AA"
    r = client.patch(f"/api/people/{p['id']}", json={"name": " Sam Smith ", "color": "#a1b2c3", "role": "child"})
    assert r.status_code == 200
    assert r.json() == {"id": p["id"], "name": "Sam Smith", "initials": "SS", "color": "#A1B2C3", "role": "child",
                        "sort": p["sort"]}
    assert client.patch(f"/api/people/{p['id']}", json={"color": "blue"}).status_code == 400
    assert client.patch(f"/api/people/{p['id']}", json={"name": ""}).status_code == 400
    assert client.patch(f"/api/people/{p['id']}", json={"role": "pet"}).status_code == 400
    assert client.patch("/api/people/nope", json={"name": "X"}).status_code == 404
    assert client.request("DELETE", "/api/people/nope", json={"pin": PIN}).status_code == 404
    # Create and edit need no PIN (like the rest of the family's content); only removing someone does.
    assert client.get("/api/people").json()[0]["name"] == "Sam Smith"


def test_delete_person_cascade(client):
    kid, other = person(client, "Mia"), person(client, "Leo")
    shared = event(client, person_ids=[kid["id"], other["id"]])
    own = event(client, person_ids=[kid["id"]])
    ch = chore(client, kid["id"])
    keep = chore(client, other["id"])
    client.post(f"/api/chores/{ch['id']}/complete", json={"date": "2026-10-05"})
    personal = client.post("/api/rewards", json={"title": "Lego", "emoji": "🧱", "cost": 1, "person_id": kid["id"]}).json()
    anyone = client.post("/api/rewards", json={"title": "Park", "emoji": "🛝", "cost": 1, "person_id": None}).json()
    lid = client.post("/api/lists", json={"name": "Jobs", "emoji": "", "color": "#000000", "kind": "todo"}).json()["id"]
    item = client.post(f"/api/lists/{lid}/items", json={"title": "Pack bag", "person_id": kid["id"]}).json()
    with client.websocket_connect("/api/ws") as ws:
        assert ws.receive_json()["type"] == "hello"
        assert client.request("DELETE", f"/api/people/{kid['id']}", json={"pin": PIN}).json() == {"ok": True}
        topics = [ws.receive_json()["topic"] for _ in range(7)]
    assert topics == ["people", "events", "chores", "points", "rewards", "lists", "accounts"]
    assert [p["id"] for p in client.get("/api/people").json()] == [other["id"]]
    evs = {o["id"]: o["person_ids"] for o in occ(client, "2026-10-05", "2026-10-06")}
    assert evs == {shared["id"]: [other["id"]], own["id"]: []}  # events stay, minus that person
    assert [c["id"] for c in client.get("/api/chores/all").json()] == [keep["id"]]
    assert {r["id"] for r in client.get("/api/rewards").json()} == {anyone["id"]}
    assert personal["id"] not in {r["id"] for r in client.get("/api/rewards").json()}
    assert [p["person_id"] for p in client.get("/api/points").json()] == [other["id"]]
    items = client.get(f"/api/lists/{lid}/items").json()
    assert [(i["id"], i["person_id"]) for i in items] == [(item["id"], None)]


def test_zero_people_views(client):
    # A fresh install with demo data off has nobody yet: every read endpoint still works.
    assert client.get("/api/people").json() == []
    assert client.get("/api/points").json() == []
    assert client.get("/api/chores?date=2026-10-05").json() == []
    assert client.get("/api/rewards").json() == []
    assert client.get("/api/summary").json()["people"] == []
    e = event(client, person_ids=[])
    assert [o["id"] for o in occ(client, "2026-10-05", "2026-10-06")] == [e["id"]]


# ---------------------------------------------------------------- websocket, weather, static, seed

def test_websocket_broadcast(client):
    with client.websocket_connect("/api/ws") as ws:
        assert ws.receive_json()["type"] == "hello"
        person(client)
        assert ws.receive_json() == {"type": "changed", "topic": "people"}


def test_weather_deterministic(client):
    w = client.get("/api/weather").json()
    assert len(w["daily"]) == 10 and w["daily"][0]["date"] == date.today().isoformat()
    assert w["daily"] == client.get("/api/weather").json()["daily"]
    ok = {"sunny", "partlycloudy", "cloudy", "rainy", "pouring", "snowy", "fog", "windy", "lightning-rainy",
          "clear-night"}
    assert all(d["condition"] in ok and d["low"] < d["high"] for d in w["daily"])
    assert w["current"]["condition"] in ok


def test_spa_fallback(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>moon</html>")
    (dist / "assets" / "app.js").write_text("console.log(1)")
    with TestClient(create_app(db_path=str(tmp_path / "x.db"), demo=False, static_dir=dist)) as c:
        assert c.get("/display/hallway").text == "<html>moon</html>"
        assert c.get("/").text == "<html>moon</html>"
        assert c.get("/assets/app.js").text == "console.log(1)"
        # relative asset URLs requested from a /display/<layout> page
        assert c.get("/display/assets/app.js").text == "console.log(1)"
        assert c.get("/api/unknown").status_code == 404


def test_demo_seed(tmp_path):
    today = date(2026, 10, 10)  # Saturday; Monday is 2026-10-05
    with TestClient(create_app(db_path=str(tmp_path / "d.db"), demo=True, seed_path=SEED, today=today)) as c:
        assert [p["id"] for p in c.get("/api/people").json()] == ["p_alex", "p_jordan", "p_mia", "p_leo"]
        assert c.post("/api/pin/verify", json={"pin": "1234"}).json() == {"ok": True}
        trip = [o for o in occ(c, "2026-10-14", "2026-10-15") if o["id"] == "e_conf"][0]
        assert (trip["start"], trip["end"]) == ("2026-10-13T00:00", "2026-10-16T00:00")
        school = [o for o in occ(c, "2026-10-05", "2026-10-12") if o["id"] == "e_school_mia"]
        assert len(school) == 5
        bed = [x for x in c.get("/api/chores?date=2026-10-10").json() if x["id"] == "c_mia_bed"][0]
        assert bed["completed"] is True and bed["streak"] == 9
        assert len(c.get("/api/meals?start=2026-10-05&end=2026-10-12").json()) == 19
        groc = c.get("/api/lists/l_grocery/items").json()
        assert [i["title"] for i in groc[-3:]] == ["Eggs", "Pasta", "Apples"]
        house = c.get("/api/lists/l_house/items").json()
        assert [i["due"] for i in house if i["title"] == "Fix the garden gate"] == ["2026-10-10"]
        assert balance(c, "p_alex") == 0 and balance(c, "p_mia") > 0
    # Re-opening a non-empty DB doesn't seed again.
    with TestClient(create_app(db_path=str(tmp_path / "d.db"), demo=True, seed_path=SEED, today=today)) as c:
        assert len(c.get("/api/people").json()) == 4


def test_remove_sample_data(tmp_path):
    from moonlight import seed as seed_mod
    app = create_app(db_path=str(tmp_path / "s.db"), demo=True, static_dir=tmp_path / "no-dist")
    with TestClient(app) as c:
        pin = json.load(open(seed_mod.default_seed_path()))["settings"]["pin"]
        total = c.get("/api/sample-data").json()["remaining"]
        assert total > 50
        # The family deleted the demo people already, added their own person, event and grocery item.
        for p in c.get("/api/people").json():
            assert c.request("DELETE", f"/api/people/{p['id']}", json={"pin": pin}).status_code == 200
        me = c.post("/api/people", json={"name": "Chris", "color": "#5B8DEF", "role": "adult", "pin": pin}).json()
        ev = c.post("/api/events", json={"title": "Dentist", "person_ids": [me["id"]], "start": "2026-10-14T09:00",
                                         "end": "2026-10-14T09:30"}).json()
        c.post("/api/lists/l_grocery/items", json={"title": "Coffee"})
        assert c.post("/api/sample-data/remove", json={"pin": "0000"}).status_code == 403
        assert c.post("/api/sample-data/remove", json={"pin": pin}).json()["removed"] > 40
        assert c.get("/api/sample-data").json() == {"remaining": 0}
        events = c.get("/api/events?start=2026-01-01&end=2027-12-31").json()
        assert [e["id"] for e in events if not e.get("calendar_id")] == [ev["id"]]
        assert [p["name"] for p in c.get("/api/people").json()] == ["Chris"]
        assert c.get("/api/chores").json() == [] and c.get("/api/recipes").json() == []
        lists = c.get("/api/lists").json()
        assert [l["id"] for l in lists] == ["l_grocery"]
        assert [i["title"] for i in c.get("/api/lists/l_grocery/items").json()] == ["Coffee"]


def test_list_and_reward_edit(client):
    lst = client.post("/api/lists", json={"name": "Jobs", "emoji": "🔧", "kind": "todo"}).json()
    r = client.patch(f"/api/lists/{lst['id']}", json={"name": "House jobs", "emoji": "🏠", "kind": "grocery"})
    assert r.status_code == 200, r.text
    assert (r.json()["name"], r.json()["emoji"], r.json()["kind"]) == ("House jobs", "🏠", "grocery")
    assert client.patch(f"/api/lists/{lst['id']}", json={"name": ""}).status_code == 400
    assert client.patch(f"/api/lists/{lst['id']}", json={"kind": "other"}).status_code == 400
    assert client.patch("/api/lists/nope", json={"name": "x"}).status_code == 404

    kid = person(client)["id"]
    rw = client.post("/api/rewards", json={"title": "Film night", "emoji": "🎬", "cost": 20, "person_id": None}).json()
    r = client.patch(f"/api/rewards/{rw['id']}", json={"title": "Cinema trip", "cost": 40, "person_id": kid})
    assert r.status_code == 200, r.text
    assert r.json() == {"id": rw["id"], "title": "Cinema trip", "emoji": "🎬", "cost": 40, "person_id": kid}
    assert client.get("/api/rewards").json()[0]["title"] == "Cinema trip"
    assert client.patch(f"/api/rewards/{rw['id']}", json={"cost": -1}).status_code == 400
    assert client.patch(f"/api/rewards/{rw['id']}", json={"person_id": "nobody"}).status_code == 400
    assert client.patch(f"/api/rewards/{rw['id']}", json={"person_id": None}).json()["person_id"] is None
    assert client.delete(f"/api/rewards/{rw['id']}").status_code == 200


def test_screen_sections_setting(client):
    s = client.get("/api/settings").json()["screens"]
    assert s["large"] == {"start": "calendar", "sections": ["calendar", "chores", "rewards", "meals", "lists"]}
    r = client.patch("/api/settings", json={"pin": PIN, "screens": {
        "kitchen": {"sections": ["lists", "today", "meals"], "start": "meals"}}})
    assert r.status_code == 200, r.text
    s = r.json()["screens"]
    assert s["compact"] == {"start": "meals", "sections": ["today", "meals", "lists"]}
    assert s["large"]["start"] == "calendar"  # untouched
    # Hiding the start section moves the start to the first one still shown.
    s = client.patch("/api/settings", json={"pin": PIN, "screens": {"kitchen": {"sections": ["lists", "today"]}}}).json()
    assert s["screens"]["compact"] == {"start": "today", "sections": ["today", "lists"]}
    for bad in ({"kitchen": {"sections": []}}, {"kitchen": {"sections": ["settings"]}}, {"tv": {}},
                {"kitchen": {"start": "rewards"}}, {"kitchen": {"start": "nope"}}, []):
        assert client.patch("/api/settings", json={"pin": PIN, "screens": bad}).status_code == 400, bad
    assert client.patch("/api/settings", json={"pin": "0000", "screens": {}}).status_code == 403


def test_public_holidays_and_skipping_them(client):
    s = client.get("/api/settings").json()
    assert s["holidays"] == {"country": "GB", "subdiv": "ENG"}  # Europe/London default
    hols = client.get("/api/holidays?start=2026-12-01&end=2027-01-05").json()
    assert [h["date"] for h in hols] == ["2026-12-25", "2026-12-26", "2026-12-28", "2027-01-01"]
    assert hols[0]["name"] == "Christmas Day"
    countries = {x["code"]: x for x in client.get("/api/holidays/countries").json()}
    assert countries["GB"]["name"] == "United Kingdom"
    assert {"code": "SCT", "name": "Scotland"} in countries["GB"]["subdivs"]
    assert "GBR" not in countries and "UK" not in countries
    preview = client.get("/api/holidays?start=2027-01-01&end=2027-01-05&country=GB&subdiv=SCT").json()
    assert [h["date"] for h in preview] == ["2027-01-01", "2027-01-02", "2027-01-04"]  # Scotland keeps 2 January
    assert client.get("/api/holidays?start=2027-01-01&end=2027-01-05&country=XX").status_code == 400

    # Chores on chosen days, skipping public holidays.
    kid = person(client)
    ch = chore(client, kid["id"], schedule={"type": "weekly", "days": ["MO", "FR"], "skip_holidays": True})
    assert ch["schedule"] == {"type": "weekly", "days": ["MO", "FR"], "skip_holidays": True}
    due = lambda d: any(x["id"] == ch["id"] for x in client.get(f"/api/chores?date={d}").json())  # noqa: E731
    assert due("2026-12-21") and not due("2026-12-22") and not due("2026-12-28") and due("2027-01-04")
    plain = chore(client, kid["id"], title="Feed fish", schedule={"type": "daily"})
    assert any(x["id"] == plain["id"] for x in client.get("/api/chores?date=2026-12-25").json())

    # Repeating events too.
    ev = event(client, title="Swim club", start="2026-12-21T17:00", end="2026-12-21T18:00",
               repeat={"freq": "daily", "skip_holidays": True})
    days = [o["start"][:10] for o in occ(client, "2026-12-24", "2026-12-29") if o["id"] == ev["id"]]
    assert days == ["2026-12-24", "2026-12-27"]

    # Another region; none at all.
    client.patch("/api/settings", json={"pin": PIN, "holidays": {"country": "GB", "subdiv": "SCT"}})
    assert "2027-01-04" in [h["date"] for h in client.get("/api/holidays?start=2027-01-01&end=2027-01-05").json()]
    assert not due("2027-01-04")
    client.patch("/api/settings", json={"pin": PIN, "holidays": {"country": ""}})
    assert client.get("/api/holidays?start=2026-12-01&end=2026-12-31").json() == []
    assert due("2026-12-28")
    for bad in ({"country": "XX"}, {"country": "GB", "subdiv": "XYZ"}, {"subdiv": "ENG"}, "GB"):
        assert client.patch("/api/settings", json={"pin": PIN, "holidays": bad}).status_code == 400, bad
    assert client.post("/api/chores", json={"title": "x", "person_id": kid["id"], "points": 1, "time_of_day": "morning",
                                            "schedule": {"type": "daily", "skip_holidays": "yes"}}).status_code == 400
