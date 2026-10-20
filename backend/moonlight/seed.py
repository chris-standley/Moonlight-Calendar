"""Load seed/demo.json into an empty database, resolving relative dates against `today`.

Conventions (see the file's `_about`): event/meal `day`, event `end_day` (inclusive last day of an
all-day event) and item `due_day` are offsets from Monday of the current week; `ago` and
`completions_ago` are days before today.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

from . import db
from .recurrence import chore_due, normalize_repeat, normalize_schedule

TIME_OF_DAY_CLOCK = {"morning": "08:00:00", "afternoon": "16:30:00", "evening": "19:00:00", "anytime": "12:00:00"}


def default_seed_path() -> Path:
    # backend/moonlight/seed.py -> moonlight/seed/demo.json
    return Path(__file__).resolve().parent.parent.parent / "seed" / "demo.json"


def seed(data: dict, today: date | None = None) -> None:
    today = today or date.today()
    monday = today - timedelta(days=today.weekday())
    now = datetime.now().replace(microsecond=0)

    def wd(offset: int) -> date:
        return monday + timedelta(days=offset)

    with db.connect() as c:
        s = data.get("settings", {})
        for key, default in db.default_settings().items():
            db.set_setting(c, key, s.get(key, default))
        if s.get("pin"):
            db.set_pin(c, str(s["pin"]))

        for i, p in enumerate(data.get("people", [])):
            c.execute("INSERT INTO people(id, name, color, role, sort) VALUES(?,?,?,?,?)",
                      (p["id"], p["name"], p["color"], p.get("role", "child"), p.get("sort", i)))

        for e in data.get("events", []):
            d = wd(e.get("day", 0))
            if e.get("all_day"):
                start = f"{d.isoformat()}T00:00"
                end = f"{(wd(e.get('end_day', e.get('day', 0))) + timedelta(days=1)).isoformat()}T00:00"
            else:
                start = f"{d.isoformat()}T{e['start']}"
                end = f"{d.isoformat()}T{e.get('end', e['start'])}"
            rep = normalize_repeat(e.get("repeat"))
            c.execute('INSERT INTO events(id, title, person_ids, start, "end", all_day, location, notes, repeat) '
                      "VALUES(?,?,?,?,?,?,?,?,?)",
                      (e["id"], e["title"], json.dumps(e.get("person_ids", [])), start, end,
                       int(bool(e.get("all_day"))), e.get("location") or "", e.get("notes") or "",
                       json.dumps(rep) if rep else None))

        chores = {}
        for i, ch in enumerate(data.get("chores", [])):
            sch = normalize_schedule(ch["schedule"])
            chores[ch["id"]] = {**ch, "schedule": sch}
            c.execute("INSERT INTO chores(id, title, emoji, person_id, points, time_of_day, schedule, sort) "
                      "VALUES(?,?,?,?,?,?,?,?)",
                      (ch["id"], ch["title"], ch.get("emoji", ""), ch["person_id"], ch.get("points", 0),
                       ch.get("time_of_day", "anytime"), json.dumps(sch), ch.get("sort", i)))

        for chore_id, agos in data.get("completions_ago", {}).items():
            ch = chores.get(chore_id)
            if not ch or not isinstance(agos, list):
                continue  # skips the "_note" key
            for ago in agos:
                d = today - timedelta(days=ago)
                if not chore_due(ch["schedule"], d):
                    continue
                at = f"{d.isoformat()}T{TIME_OF_DAY_CLOCK.get(ch.get('time_of_day'), '12:00:00')}"
                c.execute("INSERT OR IGNORE INTO completions(chore_id, date, completed_at) VALUES(?,?,?)",
                          (chore_id, d.isoformat(), at))
                if ch.get("points"):
                    db.add_ledger(c, ch["person_id"], ch["points"], f"{ch.get('emoji', '')} {ch['title']}".strip(), at)

        for b in data.get("bonus_points", []):
            at = f"{(today - timedelta(days=b.get('ago', 0))).isoformat()}T18:00:00"
            db.add_ledger(c, b["person_id"], b["change"], b.get("reason", ""), at)

        for r in data.get("rewards", []):
            c.execute("INSERT INTO rewards(id, title, emoji, cost, person_id) VALUES(?,?,?,?,?)",
                      (r["id"], r["title"], r.get("emoji", ""), r["cost"], r.get("person_id")))

        for li, lst in enumerate(data.get("lists", [])):
            c.execute("INSERT INTO lists(id, name, emoji, color, kind, sort) VALUES(?,?,?,?,?,?)",
                      (lst["id"], lst["name"], lst.get("emoji", ""), lst.get("color", ""),
                       lst.get("kind", "todo"), lst.get("sort", li)))
            n = len(lst.get("items", []))
            for ii, it in enumerate(lst.get("items", [])):
                created = (now - timedelta(hours=n - ii)).isoformat()
                done = bool(it.get("done"))
                due = wd(it["due_day"]).isoformat() if it.get("due_day") is not None else None
                # Earlier-listed done items count as more recently done.
                done_at = (now - timedelta(minutes=10 * (ii + 1))).isoformat() if done else None
                c.execute("INSERT INTO items(id, list_id, title, done, person_id, due, created_at, done_at, sort) "
                          "VALUES(?,?,?,?,?,?,?,?,?)",
                          (f"{lst['id']}_i{ii}", lst["id"], it["title"], int(done), it.get("person_id"),
                           due, created, done_at, ii))

        for r in data.get("recipes", []):
            c.execute("INSERT INTO recipes(id, title, emoji, minutes, ingredients, url, description, rating, favourite, "
                      "servings, prep_minutes, cook_minutes, steps, tags, created_at, updated_at, course) "
                      "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (r["id"], r["title"], r.get("emoji", ""), r.get("minutes"),
                       json.dumps(r.get("ingredients", [])), r.get("url"), r.get("description", ""),
                       r.get("rating", 0), int(bool(r.get("favourite"))), r.get("servings"), r.get("prep_minutes"),
                       r.get("cook_minutes"),
                       json.dumps([{"text": s["text"], "minutes": s.get("minutes"), "photo": None}
                                   for s in r.get("steps", [])]),
                       json.dumps(r.get("tags", [])), now.isoformat(timespec="seconds"),
                       now.isoformat(timespec="seconds"), r.get("course")))

        for i, m in enumerate(data.get("meals", [])):
            c.execute("INSERT INTO meals(id, date, slot, title, notes, recipe_id) VALUES(?,?,?,?,?,?)",
                      (f"m_{i}", wd(m.get("day", 0)).isoformat(), m.get("slot", "dinner"), m["title"],
                       m.get("notes") or "", m.get("recipe_id")))


def seed_file(path: str | Path, today: date | None = None) -> None:
    with open(path, encoding="utf-8") as f:
        seed(json.load(f), today)


def _sample_ids(data: dict) -> dict[str, list[str]]:
    """Ids `seed()` gives the demo family's rows, per table."""
    lists = data.get("lists", [])
    return {
        "people": [p["id"] for p in data.get("people", [])],
        "events": [e["id"] for e in data.get("events", [])],
        "chores": [ch["id"] for ch in data.get("chores", [])],
        "rewards": [r["id"] for r in data.get("rewards", [])],
        "items": [f"{lst['id']}_i{i}" for lst in lists for i in range(len(lst.get("items", [])))],
        "lists": [lst["id"] for lst in lists],
        "recipes": [r["id"] for r in data.get("recipes", [])],
        "meals": [f"m_{i}" for i in range(len(data.get("meals", [])))],
    }


def _marks(ids: list[str]) -> str:
    return ",".join("?" * len(ids)) or "NULL"


def count_sample(c, data: dict) -> int:
    """How many of the demo family's rows are still in the database."""
    total = 0
    all_ids = _sample_ids(data)
    for table, ids in all_ids.items():
        if not ids:
            continue
        sql = f"SELECT COUNT(*) FROM {table} WHERE id IN ({_marks(ids)})"
        args = list(ids)
        if table == "lists":  # a demo list the family put their own items on is theirs now
            items = all_ids["items"]
            sql += f" AND NOT EXISTS (SELECT 1 FROM items WHERE items.list_id = lists.id AND items.id NOT IN ({_marks(items)}))"
            args += items
        total += c.execute(sql, args).fetchone()[0]
    return total


def remove_sample(c, data: dict) -> int:
    """Delete what `seed()` added (people, events, chores, stars, rewards, list items, recipes, meals), leaving
    anything the family made themselves. A demo list is kept if the family added their own items to it.
    Settings (family name, PIN, ...) are left alone. Returns the number of rows removed."""
    ids = _sample_ids(data)
    removed = count_sample(c, data)
    people, chores = ids["people"], ids["chores"]
    if people:
        c.execute(f"DELETE FROM ledger WHERE person_id IN ({_marks(people)})", people)
        c.execute(f"UPDATE items SET person_id = NULL WHERE person_id IN ({_marks(people)})", people)
        for ev in db.rows(c, "SELECT id, person_ids FROM events"):
            kept = [p for p in json.loads(ev["person_ids"]) if p not in people]
            c.execute("UPDATE events SET person_ids = ? WHERE id = ?", (json.dumps(kept), ev["id"]))
        for cal in db.rows(c, "SELECT id, person_ids FROM calendars"):
            kept = [p for p in json.loads(cal["person_ids"]) if p not in people]
            c.execute("UPDATE calendars SET person_ids = ? WHERE id = ?", (json.dumps(kept), cal["id"]))
    if chores:
        c.execute(f"DELETE FROM completions WHERE chore_id IN ({_marks(chores)})", chores)
    if ids["recipes"]:
        c.execute(f"UPDATE meals SET recipe_id = NULL WHERE recipe_id IN ({_marks(ids['recipes'])})", ids["recipes"])
    for table in ("people", "events", "chores", "rewards", "items", "recipes", "meals"):
        if ids[table]:
            c.execute(f"DELETE FROM {table} WHERE id IN ({_marks(ids[table])})", ids[table])
    for list_id in ids["lists"]:
        if not c.execute("SELECT 1 FROM items WHERE list_id = ?", (list_id,)).fetchone():
            c.execute("DELETE FROM lists WHERE id = ?", (list_id,))
    return removed
