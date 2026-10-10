"""Tests for custom_components/moonlight/model.py (no Home Assistant needed).

Run from the repo root: `python3 -m pytest -q -p no:cacheprovider tests`
"""
from __future__ import annotations

import importlib.util
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
# Load model.py directly: importing the package would import homeassistant.
_spec = importlib.util.spec_from_file_location("moonlight_model", ROOT / "custom_components" / "moonlight" / "model.py")
model = importlib.util.module_from_spec(_spec)
sys.modules["moonlight_model"] = model
_spec.loader.exec_module(model)

BST = timezone(timedelta(hours=1))

SUMMARY = {
    "version": "0.1.0", "family_name": "Testers", "date": "2026-10-10", "now": "2026-10-10T11:30",
    "people": [
        {"id": "p_ada", "name": "Ada Lovelace", "initials": "AL", "color": "#f00", "role": "child", "sort": 0,
         "balance": 12,
         "chores": [
             {"id": "c1", "title": "Make bed", "emoji": "🛏️", "points": 2, "time_of_day": "morning",
              "completed": True, "streak": 3},
             {"id": "c2", "title": "Feed cat", "emoji": "🐱", "points": 3, "time_of_day": "evening",
              "completed": False, "streak": 0},
         ],
         "chores_total": 2, "chores_done": 1, "chores_left": 1, "all_done": False,
         "event": {"id": "e1", "occurrence_id": "e1@2026-10-10", "title": "Swim", "person_ids": ["p_ada"],
                   "start": "2026-10-10T11:00", "end": "2026-10-10T12:00", "all_day": False, "location": "Pool"}},
        {"id": "p_mum", "name": "Mum", "initials": "M", "color": "#0f0", "role": "adult", "sort": 1,
         "balance": 0, "chores": [], "chores_total": 0, "chores_done": 0, "chores_left": 0, "all_done": True,
         "event": None},
    ],
    "dinner": {"id": "m1", "date": "2026-10-10", "slot": "dinner", "title": "Tacos", "notes": "", "recipe_id": None},
    "next_event": {"id": "e2", "occurrence_id": "e2", "title": "Party", "person_ids": ["p_mum", "p_ada"],
                   "start": "2026-10-10T18:00", "end": "2026-10-10T21:00", "all_day": False, "location": ""},
    "lists": [
        {"id": "l1", "name": "Groceries", "emoji": "🛒", "color": "", "kind": "grocery", "sort": 0,
         "open_count": 1, "done_count": 1,
         "items": [
             {"id": "i1", "list_id": "l1", "title": "Milk", "done": False, "person_id": None, "due": None,
              "created_at": "2026-10-09T10:00", "sort": 0},
             {"id": "i2", "list_id": "l1", "title": "Eggs", "done": True, "person_id": None, "due": "2026-10-11",
              "created_at": "2026-10-09T10:00", "sort": 1},
         ]},
    ],
}


def test_parse_summary():
    s = model.parse_summary(SUMMARY)
    ada, mum = s.people
    assert ada.is_child and not mum.is_child
    assert (ada.balance, ada.chores_done, ada.chores_left, ada.all_done) == (12, 1, 1, False)
    assert ada.remaining == ["Feed cat"] and mum.all_done
    assert ada.event.title == "Swim" and ada.event.start == datetime(2026, 10, 10, 11)
    assert s.person("p_mum") is mum and s.person("nope") is None
    assert s.todo_list("l1").open_count == 1 and s.todo_list("l1").items[1].due == date(2026, 10, 11)
    assert model.dinner_state(s) == "Tacos"
    assert model.chores_attributes(ada) == {"remaining": ["Feed cat"], "total": 2, "done": 1}
    assert model.event_attributes(s, s.next_event) == {
        "start": "2026-10-10T18:00", "end": "2026-10-10T21:00", "all_day": False,
        "people": ["Mum", "Ada Lovelace"], "location": ""}
    assert model.event_attributes(s, None) == {}


def test_parse_summary_empty_and_bad():
    s = model.parse_summary({**SUMMARY, "dinner": None, "next_event": None, "lists": []})
    assert model.dinner_state(s) == "Nothing planned" and s.next_event is None
    for bad in (None, [], {"people": "x"}, {**SUMMARY, "date": "soon"}, {**SUMMARY, "people": [{"name": "x"}]}):
        with pytest.raises(ValueError):
            model.parse_summary(bad)


def test_health_and_urls():
    assert model.health_version({"ok": True, "version": "0.1.0"}) == "0.1.0"
    with pytest.raises(ValueError):
        model.health_version({"detail": "Not found"})
    assert model.base_url("local-moonlight", 8099) == "http://local-moonlight:8099"
    assert model.base_url(" 192.168.1.5/ ", 8099) == "http://192.168.1.5:8099"
    assert model.base_url("fd00::5", 8099) == "http://[fd00::5]:8099"
    assert model.base_url("https://moon.example.com", 443) == "https://moon.example.com:443"
    assert model.base_url("http://moon:9000", 8099) == "http://moon:9000"
    assert model.ws_url("http://moon:8099") == "ws://moon:8099/api/ws"
    assert model.ws_url("https://moon:8099") == "wss://moon:8099/api/ws"


def test_ws_messages_and_backoff():
    assert model.is_change_message('{"type":"changed","topic":"chores"}')
    assert not model.is_change_message('{"type":"hello","version":"0.1.0"}')
    assert not model.is_change_message("pong") and not model.is_change_message("[1]")
    assert [model.backoff(i) for i in range(5)] == [1, 2, 4, 8, 16]
    assert model.backoff(50) == 300


def test_resolve_person():
    people = SUMMARY["people"]
    assert model.resolve_person(people, "p_mum")["name"] == "Mum"
    assert model.resolve_person(people, "  ada lovelace ")["id"] == "p_ada"
    assert model.resolve_person(people, "ada")["id"] == "p_ada"          # first name
    parsed = model.parse_summary(SUMMARY).people
    assert model.resolve_person(parsed, "MUM").id == "p_mum"
    with pytest.raises(LookupError):
        model.resolve_person(people, "Dad")
    with pytest.raises(LookupError, match="More than one"):
        model.resolve_person(people + [{**people[0], "id": "p_ada2"}], "Ada Lovelace")


def test_resolve_chore():
    chores = [
        {"id": "c1", "title": "Make bed", "emoji": "🛏️", "person_id": "p_ada"},
        {"id": "c2", "title": "Feed the cat", "emoji": "🐱", "person_id": "p_ada"},
        {"id": "c3", "title": "Make bed", "emoji": "🛏️", "person_id": "p_bob"},
    ]
    assert model.resolve_chore(chores, "p_ada", "make bed")["id"] == "c1"
    assert model.resolve_chore(chores, "p_bob", "Make Bed")["id"] == "c3"
    assert model.resolve_chore(chores, "p_ada", "🐱 Feed the cat")["id"] == "c2"
    assert model.resolve_chore(chores, "p_ada", "cat")["id"] == "c2"     # substring fallback
    assert model.resolve_chore(chores, "p_ada", "c1")["id"] == "c1"
    with pytest.raises(LookupError, match="someone else"):
        model.resolve_chore(chores, "p_ada", "c3")
    with pytest.raises(LookupError):
        model.resolve_chore(chores, "p_ada", "Hoover")
    twice = [{"id": "am", "title": "Brush teeth", "person_id": "p", "completed": True},
             {"id": "pm", "title": "Brush teeth", "person_id": "p", "completed": False}]
    assert model.resolve_chore(twice, "p", "brush teeth")["id"] == "pm"
    twice[1]["completed"] = True
    assert model.resolve_chore(twice, "p", "brush teeth")["id"] == "am"


def test_resolve_list():
    lists = [{"id": "l1", "name": "🛒 Groceries"}, {"id": "l2", "name": "To do"}]
    assert model.resolve_list(lists, "groceries")["id"] == "l1"
    assert model.resolve_list(lists, "TO DO")["id"] == "l2"
    assert model.resolve_list(lists, "l2")["id"] == "l2"
    assert model.resolve_list(model.parse_summary(SUMMARY).lists, "Groceries").id == "l1"
    with pytest.raises(LookupError):
        model.resolve_list(lists, "Hardware")


def test_event_times_and_ranges():
    timed = model.parse_event({"id": "e", "title": "T", "start": "2026-10-10T09:00", "end": "2026-10-10T10:30"})
    s, e = model.event_times(timed, BST)
    assert s == datetime(2026, 10, 10, 9, tzinfo=BST) and e.hour == 10 and e.minute == 30
    allday = model.parse_event({"id": "a", "title": "Trip", "start": "2026-10-10T00:00",
                                "end": "2026-10-12T00:00", "all_day": True})
    assert model.event_times(allday, BST) == (date(2026, 10, 10), date(2026, 10, 12))
    # HA asks for an aware UTC window; Moonlight wants local dates, end exclusive.
    start = datetime(2026, 10, 9, 23, 0, tzinfo=timezone.utc)   # = 10 Oct 00:00 BST
    end = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)    # = 11 Oct 13:00 BST
    assert model.query_range(start, end, BST) == ("2026-10-10", "2026-10-12")
    assert model.query_range(start, start + timedelta(days=1), BST) == ("2026-10-10", "2026-10-11")


def test_events_for_person():
    raw = [
        {"id": "e1", "title": "Swim", "person_ids": ["p_ada"], "start": "2026-10-10T09:00", "end": "2026-10-10T10:00"},
        {"id": "e2", "title": "Work", "person_ids": ["p_mum"], "start": "2026-10-10T09:00", "end": "2026-10-10T17:00"},
        {"id": "e3", "title": "Late", "person_ids": ["p_ada"], "start": "2026-10-10T20:00", "end": "2026-10-10T21:00",
         "recurring": True, "occurrence_id": "e3@2026-10-10"},
    ]
    start = datetime(2026, 10, 10, 9, 30, tzinfo=BST)
    end = datetime(2026, 10, 10, 19, 0, tzinfo=BST)
    assert [e.id for e in model.events_for_person(raw, "p_ada", start, end, BST)] == ["e1"]
    assert [e.id for e in model.events_for_person(raw, None, start, end, BST)] == ["e1", "e2"]
    late = model.events_for_person(raw, "p_ada", end, end + timedelta(hours=3), BST)
    assert late[0].recurring and late[0].occurrence_id == "e3@2026-10-10"


def test_item_patch():
    cur = model.parse_item({"id": "i", "title": "Milk", "done": False, "due": None})
    assert model.item_patch(cur, "Milk", False, None) == {}
    assert model.item_patch(cur, "Oat milk", True, None) == {"title": "Oat milk", "done": True}
    assert model.item_patch(cur, "Milk", False, datetime(2026, 10, 12, 9)) == {"due": "2026-10-12"}
    dated = model.parse_item({"id": "i", "title": "Milk", "done": True, "due": "2026-10-12"})
    assert model.item_patch(dated, "Milk", False, None) == {"done": False, "due": None}
    assert model.item_patch(dated, "  ", True, date(2026, 10, 12)) == {}
    assert model.due_param(None) is None and model.due_param(date(2026, 1, 2)) == "2026-01-02"


def test_contract_with_backend_summary(tmp_path):
    """Parse a real /api/summary from the backend (the two halves must agree)."""
    pytest.importorskip("fastapi")
    sys.path.insert(0, str(ROOT / "backend"))
    from fastapi.testclient import TestClient
    from moonlight.main import create_app

    app = create_app(db_path=str(tmp_path / "c.db"), demo=True, seed_path=ROOT / "seed" / "demo.json",
                     static_dir=tmp_path / "none")
    with TestClient(app) as c:
        raw = c.get("/api/summary").json()
        s = model.parse_summary(raw)
        assert len(s.people) == 4 and any(p.is_child for p in s.people) and s.lists
        assert all(p.chores_left == q["chores_left"] for p, q in zip(s.people, raw["people"]))
        lst = s.lists[0]
        assert model.resolve_list(c.get("/api/lists").json(), lst.name)["id"] == lst.id


def test_pairing_helpers():
    assert model.auth_headers(None) == {} and model.auth_headers("") == {}
    assert model.auth_headers("mlt_x") == {"Authorization": "Bearer mlt_x"}
    assert model.needs_pairing({"required": True, "authorised": False}) is True
    assert model.needs_pairing({"required": True, "authorised": True}) is False
    assert model.needs_pairing({"required": False, "authorised": True}) is False
    assert model.needs_pairing(None) is False  # Moonlight from before pairing (404)
    assert model.parse_pair_start({"pair_id": "p1", "code": "012345", "layout": "service"}) == ("p1", "012345")
    with pytest.raises(ValueError):
        model.parse_pair_start({"detail": "nope"})
    assert model.parse_pair_poll({"status": "approved", "token": "mlt_t"}) == ("approved", "mlt_t")
    assert model.parse_pair_poll({"status": "pending", "expires_in": 500}) == ("pending", None)
    assert model.parse_pair_poll({"status": "expired"}) == ("expired", None)
    with pytest.raises(ValueError):
        model.parse_pair_poll({"status": "approved"})
    assert model.format_code("012345") == "012 345"


def test_contract_with_backend_pairing(tmp_path):
    """The integration's pairing sequence against a real backend with pairing required."""
    pytest.importorskip("fastapi")
    sys.path.insert(0, str(ROOT / "backend"))
    from fastapi.testclient import TestClient
    from moonlight.main import create_app

    app = create_app(db_path=str(tmp_path / "p.db"), demo=False, static_dir=tmp_path / "none",
                     data_dir=tmp_path / "data", auth_enabled=True)
    ingress = TestClient(app, client=("172.30.32.2", 1), headers={"X-Ingress-Path": "/x"})
    assert ingress.patch("/api/settings", json={"pin": "1234"}).status_code == 200
    hass = TestClient(app, client=("192.168.1.9", 2))
    assert model.needs_pairing(hass.get("/api/auth/status").json())
    assert hass.get("/api/summary").status_code == 401
    pair_id, code = model.parse_pair_start(
        hass.post("/api/pair/start", json={"layout": model.PAIR_LAYOUT, "name": model.PAIR_NAME}).json())
    assert model.parse_pair_poll(hass.get(f"/api/pair/{pair_id}").json()) == ("pending", None)
    # What the user types in Settings > Screens (the dialog shows "123 456").
    d = ingress.post("/api/displays/approve", json={"code": model.format_code(code), "pin": "1234"}).json()
    assert d["name"] == "Home Assistant" and d["layout"] == "service"
    status, token = model.parse_pair_poll(hass.get(f"/api/pair/{pair_id}").json())
    assert status == "approved"
    paired = TestClient(app, client=("192.168.1.9", 2), headers=model.auth_headers(token))
    assert not model.needs_pairing(paired.get("/api/auth/status").json())
    model.parse_summary(paired.get("/api/summary").json())
