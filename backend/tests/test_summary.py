"""GET /api/summary (used by the Home Assistant integration)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from moonlight.main import create_app  # noqa: E402

DAY = "2026-10-10"


@pytest.fixture
def client(tmp_path):
    app = create_app(db_path=str(tmp_path / "s.db"), demo=False, static_dir=tmp_path / "none")
    with TestClient(app) as c:
        yield c


def post(c, path, body):
    r = c.post(path, json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_summary(client):
    kid = post(client, "/api/people", {"name": "Ada", "color": "#f00", "role": "child"})
    mum = post(client, "/api/people", {"name": "Mum", "color": "#0f0", "role": "adult"})
    teeth = post(client, "/api/chores", {"title": "Teeth", "emoji": "🪥", "person_id": kid["id"], "points": 2})
    post(client, "/api/chores", {"title": "Bed", "person_id": kid["id"], "points": 3})
    post(client, "/api/chores/" + teeth["id"] + "/complete", {"date": DAY})
    post(client, "/api/meals", {"date": DAY, "slot": "lunch", "title": "Soup"})
    post(client, "/api/meals", {"date": DAY, "slot": "dinner", "title": "Tacos"})
    post(client, "/api/events", {"title": "Past", "person_ids": [kid["id"]],
                                 "start": f"{DAY}T08:00", "end": f"{DAY}T09:00"})
    post(client, "/api/events", {"title": "Swim", "person_ids": [kid["id"]],
                                 "start": f"{DAY}T11:00", "end": f"{DAY}T12:00"})
    post(client, "/api/events", {"title": "Party", "person_ids": [mum["id"]],
                                 "start": f"{DAY}T18:00", "end": f"{DAY}T21:00"})
    lst = post(client, "/api/lists", {"name": "Groceries", "kind": "grocery"})
    post(client, f"/api/lists/{lst['id']}/items", {"title": "Milk"})

    s = client.get(f"/api/summary?date={DAY}&now={DAY}T11:30").json()
    assert s["date"] == DAY and s["now"] == f"{DAY}T11:30"
    ada, mum_s = s["people"]
    assert ada["balance"] == 2 and ada["chores_total"] == 2 and ada["chores_done"] == 1
    assert ada["chores_left"] == 1 and not ada["all_done"]
    assert [c["title"] for c in ada["chores"] if not c["completed"]] == ["Bed"]
    assert ada["event"]["title"] == "Swim"          # in progress counts for the person
    assert mum_s["all_done"] and mum_s["chores_total"] == 0 and mum_s["event"]["title"] == "Party"
    assert s["next_event"]["title"] == "Party"      # next one that hasn't started
    assert s["dinner"]["title"] == "Tacos"
    assert s["lists"][0]["name"] == "Groceries" and s["lists"][0]["items"][0]["title"] == "Milk"

    s = client.get(f"/api/summary?date=2026-10-11&now={DAY}T22:00").json()
    assert s["dinner"] is None and s["next_event"] is None
    assert client.get("/api/summary?now=nope").status_code == 400
    assert client.get("/api/summary").status_code == 200
