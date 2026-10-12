"""Chores, points ledger and rewards."""
from __future__ import annotations

import json
from datetime import date, timedelta

from fastapi import APIRouter, Body

from .. import db, public_holidays
from ..common import (
    as_date, as_int, bad, body_dict, choice, hub, next_sort, not_found, opt_str,
    person_exists, req_str, require_pin,
)
from ..recurrence import chore_due, normalize_schedule, streak

router = APIRouter(prefix="/api")

TIMES = ("morning", "afternoon", "evening", "anytime")
STREAK_LOOKBACK = 60


def chore_out(r: dict) -> dict:
    return {
        "id": r["id"], "title": r["title"], "emoji": r["emoji"], "person_id": r["person_id"],
        "points": r["points"], "time_of_day": r["time_of_day"],
        "schedule": json.loads(r["schedule"]), "sort": r["sort"],
    }


def _get_chore(c, chore_id: str) -> dict:
    r = db.row(c, "SELECT * FROM chores WHERE id = ?", (chore_id,))
    if not r:
        raise not_found("Chore not found")
    return chore_out(r)


def _date_param(value: str | None, key: str = "date") -> str:
    return date.today().isoformat() if value in (None, "") else as_date(value, key)


# ---------------------------------------------------------------- chores

@router.get("/chores/all")
def all_chores():
    with db.connect() as c:
        return [chore_out(r) for r in db.rows(c, "SELECT * FROM chores ORDER BY sort, title")]


@router.get("/chores")
def chores_for_day(date: str | None = None):  # noqa: A002 - query param name is part of the API
    day_s = _date_param(date)
    day = _parse(day_s)
    lo = (day - timedelta(days=STREAK_LOOKBACK)).isoformat()
    with db.connect() as c:
        chores = [chore_out(r) for r in db.rows(c, "SELECT * FROM chores ORDER BY sort, title")]
        is_holiday = public_holidays.checker(c)
        comps: dict[str, dict[str, str]] = {}
        for r in db.rows(c, "SELECT chore_id, date, completed_at FROM completions WHERE date BETWEEN ? AND ?",
                         (lo, day_s)):
            comps.setdefault(r["chore_id"], {})[r["date"]] = r["completed_at"]
    out = []
    for ch in chores:
        if not chore_due(ch["schedule"], day, is_holiday):
            continue
        done = comps.get(ch["id"], {})
        out.append({
            **ch,
            "date": day_s,
            "completed": day_s in done,
            "completed_at": done.get(day_s),
            "streak": streak(ch["schedule"], day, set(done), STREAK_LOOKBACK, is_holiday),
        })
    return out


def _parse(s: str) -> date:
    return date.fromisoformat(s)


def _apply_chore(c, ch: dict, body: dict, creating: bool) -> dict:
    if creating or "title" in body:
        ch["title"] = req_str(body, "title")
    if creating or "emoji" in body:
        ch["emoji"] = opt_str(body, "emoji")
    if creating or "person_id" in body:
        pid = body.get("person_id")
        if not isinstance(pid, str) or not person_exists(c, pid):
            raise bad("person_id must be an existing person")
        ch["person_id"] = pid
    if creating or "points" in body:
        ch["points"] = as_int(body.get("points", 0), "points")
        if ch["points"] < 0:
            raise bad("points must be >= 0")
    if creating or "time_of_day" in body:
        ch["time_of_day"] = choice(body.get("time_of_day", "anytime"), "time_of_day", TIMES)
    if creating or "schedule" in body:
        try:
            ch["schedule"] = normalize_schedule(body.get("schedule") or {"type": "daily"})
        except ValueError as e:
            raise bad(str(e))
    if "sort" in body:
        ch["sort"] = as_int(body["sort"], "sort")
    elif creating:
        ch["sort"] = next_sort(c, "chores")
    return ch


@router.post("/chores")
async def create_chore(body: dict = Body(...)):
    body = body_dict(body)
    with db.connect() as c:
        ch = _apply_chore(c, {"id": db.new_id("c")}, body, creating=True)
        c.execute("INSERT INTO chores(id, title, emoji, person_id, points, time_of_day, schedule, sort) "
                  "VALUES(?,?,?,?,?,?,?,?)",
                  (ch["id"], ch["title"], ch["emoji"], ch["person_id"], ch["points"], ch["time_of_day"],
                   json.dumps(ch["schedule"]), ch["sort"]))
    await hub.broadcast("chores")
    return ch


@router.patch("/chores/{chore_id}")
async def update_chore(chore_id: str, body: dict = Body(...)):
    body = body_dict(body)
    with db.connect() as c:
        ch = _apply_chore(c, _get_chore(c, chore_id), body, creating=False)
        c.execute("UPDATE chores SET title=?, emoji=?, person_id=?, points=?, time_of_day=?, schedule=?, sort=? "
                  "WHERE id=?",
                  (ch["title"], ch["emoji"], ch["person_id"], ch["points"], ch["time_of_day"],
                   json.dumps(ch["schedule"]), ch["sort"], chore_id))
    await hub.broadcast("chores")
    return ch


@router.delete("/chores/{chore_id}")
async def delete_chore(chore_id: str):
    with db.connect() as c:
        if c.execute("DELETE FROM chores WHERE id = ?", (chore_id,)).rowcount == 0:
            raise not_found("Chore not found")
        c.execute("DELETE FROM completions WHERE chore_id = ?", (chore_id,))
    await hub.broadcast("chores")
    return {"ok": True}


@router.post("/chores/{chore_id}/complete")
async def complete_chore(chore_id: str, body: dict | None = Body(None)):
    body = body_dict(body)
    day = _date_param(body.get("date"))
    with db.connect() as c:
        ch = _get_chore(c, chore_id)
        already = c.execute("SELECT 1 FROM completions WHERE chore_id = ? AND date = ?",
                            (chore_id, day)).fetchone()
        if not already:
            c.execute("INSERT INTO completions(chore_id, date, completed_at) VALUES(?,?,?)",
                      (chore_id, day, db.now_iso()))
            if ch["points"]:
                db.add_ledger(c, ch["person_id"], ch["points"], f"{ch['emoji']} {ch['title']}".strip())
        bal = db.balance(c, ch["person_id"])
    if not already:
        await hub.broadcast("chores", "points")
    return {"completed": True, "balance": bal}


@router.delete("/chores/{chore_id}/complete")
async def undo_chore(chore_id: str, date: str | None = None):  # noqa: A002
    day = _date_param(date)
    with db.connect() as c:
        ch = _get_chore(c, chore_id)
        removed = c.execute("DELETE FROM completions WHERE chore_id = ? AND date = ?",
                            (chore_id, day)).rowcount
        if removed and ch["points"]:
            db.add_ledger(c, ch["person_id"], -ch["points"], f"Undo: {ch['title']}")
        bal = db.balance(c, ch["person_id"])
    if removed:
        await hub.broadcast("chores", "points")
    return {"completed": False, "balance": bal}


# ---------------------------------------------------------------- points

@router.get("/points")
def points():
    with db.connect() as c:
        return db.rows(
            c,
            "SELECT p.id AS person_id, COALESCE(SUM(l.change), 0) AS balance FROM people p "
            "LEFT JOIN ledger l ON l.person_id = p.id GROUP BY p.id ORDER BY p.sort, p.name",
        )


@router.get("/points/{person_id}/ledger")
def ledger(person_id: str):
    with db.connect() as c:
        if not person_exists(c, person_id):
            raise not_found("Person not found")
        return db.rows(
            c,
            "SELECT id, person_id, change, reason, at FROM ledger WHERE person_id = ? "
            "ORDER BY at DESC, seq DESC LIMIT 100",
            (person_id,),
        )


@router.post("/points/adjust")
async def adjust_points(body: dict = Body(...)):
    body = body_dict(body)
    with db.connect() as c:
        require_pin(c, body.get("pin"))
        pid = body.get("person_id")
        if not isinstance(pid, str) or not person_exists(c, pid):
            raise not_found("Person not found")
        change = as_int(body.get("change"), "change")
        if change == 0:
            raise bad("change must not be 0")
        db.add_ledger(c, pid, change, opt_str(body, "reason") or "Adjustment")
        bal = db.balance(c, pid)
    await hub.broadcast("points")
    return {"balance": bal}


# ---------------------------------------------------------------- rewards

def reward_out(r: dict) -> dict:
    return {k: r[k] for k in ("id", "title", "emoji", "cost", "person_id")}


@router.get("/rewards")
def list_rewards():
    with db.connect() as c:
        return [reward_out(r) for r in db.rows(c, "SELECT * FROM rewards ORDER BY cost, title")]


def _apply_reward(c, rw: dict, body: dict, creating: bool) -> dict:
    if creating or "person_id" in body:
        pid = body.get("person_id")
        if pid is not None and (not isinstance(pid, str) or not person_exists(c, pid)):
            raise bad("person_id must be an existing person or null")
        rw["person_id"] = pid
    if creating or "cost" in body:
        rw["cost"] = as_int(body.get("cost"), "cost")
        if rw["cost"] < 0:
            raise bad("cost must be >= 0")
    if creating or "title" in body:
        rw["title"] = req_str(body, "title")
    if creating or "emoji" in body:
        rw["emoji"] = opt_str(body, "emoji")
    return rw


@router.post("/rewards")
async def create_reward(body: dict = Body(...)):
    body = body_dict(body)
    with db.connect() as c:
        rw = _apply_reward(c, {"id": db.new_id("r")}, body, creating=True)
        c.execute("INSERT INTO rewards(id, title, emoji, cost, person_id) VALUES(?,?,?,?,?)",
                  (rw["id"], rw["title"], rw["emoji"], rw["cost"], rw["person_id"]))
    await hub.broadcast("rewards")
    return reward_out(rw)


@router.patch("/rewards/{reward_id}")
async def update_reward(reward_id: str, body: dict = Body(...)):
    """Any of title, emoji, cost, person_id (null = any child)."""
    body = body_dict(body)
    with db.connect() as c:
        r = db.row(c, "SELECT * FROM rewards WHERE id = ?", (reward_id,))
        if not r:
            raise not_found("Reward not found")
        rw = _apply_reward(c, reward_out(r), body, creating=False)
        c.execute("UPDATE rewards SET title=?, emoji=?, cost=?, person_id=? WHERE id=?",
                  (rw["title"], rw["emoji"], rw["cost"], rw["person_id"], reward_id))
    await hub.broadcast("rewards")
    return rw


@router.delete("/rewards/{reward_id}")
async def delete_reward(reward_id: str):
    with db.connect() as c:
        if c.execute("DELETE FROM rewards WHERE id = ?", (reward_id,)).rowcount == 0:
            raise not_found("Reward not found")
    await hub.broadcast("rewards")
    return {"ok": True}


@router.post("/rewards/{reward_id}/redeem")
async def redeem_reward(reward_id: str, body: dict = Body(...)):
    body = body_dict(body)
    with db.connect() as c:
        require_pin(c, body.get("pin"))
        r = db.row(c, "SELECT * FROM rewards WHERE id = ?", (reward_id,))
        if not r:
            raise not_found("Reward not found")
        pid = body.get("person_id")
        if not isinstance(pid, str) or not person_exists(c, pid):
            raise not_found("Person not found")
        if r["person_id"] and r["person_id"] != pid:
            raise bad("This reward belongs to someone else")
        if db.balance(c, pid) < r["cost"]:
            raise bad("Not enough points")
        db.add_ledger(c, pid, -r["cost"], f"{r['emoji']} {r['title']}".strip())
        bal = db.balance(c, pid)
    await hub.broadcast("points")
    return {"balance": bal}
