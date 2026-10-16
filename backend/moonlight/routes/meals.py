"""Meals and weather (recipes are in recipes.py)."""
from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException

from .. import db, ha_client
from ..common import as_date, bad, body_dict, choice, hub, not_found, opt_str, req_str

router = APIRouter(prefix="/api")

SLOTS = ("breakfast", "lunch", "dinner", "snack")
SLOT_ORDER = {s: i for i, s in enumerate(SLOTS)}


def meal_out(r: dict) -> dict:
    return {k: r[k] for k in ("id", "date", "slot", "title", "notes", "recipe_id")}


def _recipe_id(c, rid) -> str | None:
    if rid in (None, ""):
        return None
    if not isinstance(rid, str) or not c.execute("SELECT 1 FROM recipes WHERE id = ?", (rid,)).fetchone():
        raise bad("recipe_id must be an existing recipe or null")
    return rid


@router.get("/meals")
def list_meals(start: str, end: str):
    s, e = as_date(start, "start"), as_date(end, "end")
    with db.connect() as c:
        rs = db.rows(c, "SELECT * FROM meals WHERE date >= ? AND date < ?", (s, e))
    rs.sort(key=lambda r: (r["date"], SLOT_ORDER.get(r["slot"], 9), r["title"]))
    return [meal_out(r) for r in rs]


@router.post("/meals")
async def create_meal(body: dict = Body(...)):
    body = body_dict(body)
    with db.connect() as c:
        m = {"id": db.new_id("m"), "date": as_date(body.get("date"), "date"),
             "slot": choice(body.get("slot", "dinner"), "slot", SLOTS),
             "title": req_str(body, "title"), "notes": opt_str(body, "notes"),
             "recipe_id": _recipe_id(c, body.get("recipe_id"))}
        c.execute("INSERT INTO meals(id, date, slot, title, notes, recipe_id) "
                  "VALUES(:id, :date, :slot, :title, :notes, :recipe_id)", m)
    await hub.broadcast("meals")
    return m


@router.patch("/meals/{meal_id}")
async def update_meal(meal_id: str, body: dict = Body(...)):
    body = body_dict(body)
    with db.connect() as c:
        m = db.row(c, "SELECT * FROM meals WHERE id = ?", (meal_id,))
        if not m:
            raise not_found("Meal not found")
        if "date" in body:
            m["date"] = as_date(body["date"], "date")
        if "slot" in body:
            m["slot"] = choice(body["slot"], "slot", SLOTS)
        if "title" in body:
            m["title"] = req_str(body, "title")
        if "notes" in body:
            m["notes"] = opt_str(body, "notes")
        if "recipe_id" in body:
            m["recipe_id"] = _recipe_id(c, body["recipe_id"])
        c.execute("UPDATE meals SET date=:date, slot=:slot, title=:title, notes=:notes, recipe_id=:recipe_id "
                  "WHERE id=:id", m)
    await hub.broadcast("meals")
    return meal_out(m)


@router.delete("/meals/{meal_id}")
async def delete_meal(meal_id: str):
    with db.connect() as c:
        if c.execute("DELETE FROM meals WHERE id = ?", (meal_id,)).rowcount == 0:
            raise not_found("Meal not found")
    await hub.broadcast("meals")
    return {"ok": True}


# ---------------------------------------------------------------- weather

@router.get("/weather")
async def get_weather():
    with db.connect() as c:
        unit = db.get_setting(c, "temp_unit", db.DEFAULT_SETTINGS["temp_unit"])
        entity = db.get_setting(c, "weather_entity", None)  # None: never chosen, use MOONLIGHT_WEATHER_ENTITY
    return await ha_client.get_weather(unit, entity)


@router.get("/weather/entities")
async def weather_entities():
    """Home Assistant's weather entities and their current conditions, for Settings > Weather."""
    if ha_client.connection() is None:
        raise HTTPException(status_code=409, detail="Moonlight isn't connected to Home Assistant")
    try:
        return await ha_client.list_entities()
    except ha_client.HAError as e:
        raise HTTPException(status_code=502, detail=str(e))
