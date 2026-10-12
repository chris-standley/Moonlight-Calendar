"""Meals, recipes and weather."""
from __future__ import annotations

import json

from fastapi import APIRouter, Body, HTTPException

from .. import db, ha_client
from ..common import as_date, as_int, bad, body_dict, choice, hub, not_found, opt_str, req_str
from .lists import insert_item

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


# ---------------------------------------------------------------- recipes

def recipe_out(r: dict) -> dict:
    return {"id": r["id"], "title": r["title"], "emoji": r["emoji"], "minutes": r["minutes"],
            "ingredients": json.loads(r["ingredients"]), "url": r["url"]}


@router.get("/recipes")
def list_recipes():
    with db.connect() as c:
        return [recipe_out(r) for r in db.rows(c, "SELECT * FROM recipes ORDER BY title")]


def recipe_fields(body: dict, partial: bool) -> dict:
    """Validated recipe columns from a POST (all) or PATCH (only those present) body."""
    out: dict = {}
    if not partial or "title" in body:
        out["title"] = req_str(body, "title")
    if not partial or "emoji" in body:
        out["emoji"] = opt_str(body, "emoji")
    if not partial or "minutes" in body:
        minutes = body.get("minutes")
        out["minutes"] = None if minutes in (None, "") else as_int(minutes, "minutes")
        if out["minutes"] is not None and out["minutes"] < 0:
            raise bad("minutes can't be negative")
    if not partial or "ingredients" in body:
        ingredients = body.get("ingredients") or []
        if not isinstance(ingredients, list) or not all(isinstance(i, str) for i in ingredients):
            raise bad("ingredients must be a list of strings")
        out["ingredients"] = [i.strip() for i in ingredients if i.strip()]
    if not partial or "url" in body:
        out["url"] = opt_str(body, "url") or None
    return out


@router.post("/recipes")
async def create_recipe(body: dict = Body(...)):
    r = {"id": db.new_id("rc"), **recipe_fields(body_dict(body), partial=False)}
    with db.connect() as c:
        c.execute("INSERT INTO recipes(id, title, emoji, minutes, ingredients, url) VALUES(?,?,?,?,?,?)",
                  (r["id"], r["title"], r["emoji"], r["minutes"], json.dumps(r["ingredients"]), r["url"]))
    await hub.broadcast("recipes")
    return r


@router.patch("/recipes/{recipe_id}")
async def update_recipe(recipe_id: str, body: dict = Body(...)):
    fields = recipe_fields(body_dict(body), partial=True)
    if "ingredients" in fields:
        fields["ingredients"] = json.dumps(fields["ingredients"])
    with db.connect() as c:
        if not db.row(c, "SELECT 1 FROM recipes WHERE id = ?", (recipe_id,)):
            raise not_found("Recipe not found")
        if fields:
            sets = ", ".join(f"{k} = ?" for k in fields)
            c.execute(f"UPDATE recipes SET {sets} WHERE id = ?", (*fields.values(), recipe_id))
        out = recipe_out(db.row(c, "SELECT * FROM recipes WHERE id = ?", (recipe_id,)))
    await hub.broadcast("recipes")
    return out


@router.delete("/recipes/{recipe_id}")
async def delete_recipe(recipe_id: str):
    """Deletes the recipe; planned meals that used it keep their title but lose the link."""
    with db.connect() as c:
        if c.execute("DELETE FROM recipes WHERE id = ?", (recipe_id,)).rowcount == 0:
            raise not_found("Recipe not found")
        unlinked = c.execute("UPDATE meals SET recipe_id = NULL WHERE recipe_id = ?", (recipe_id,)).rowcount
    await hub.broadcast("recipes")
    if unlinked:
        await hub.broadcast("meals")
    return {"ok": True}


@router.post("/recipes/{recipe_id}/to-list")
async def recipe_to_list(recipe_id: str, body: dict = Body(...)):
    body = body_dict(body)
    with db.connect() as c:
        r = db.row(c, "SELECT * FROM recipes WHERE id = ?", (recipe_id,))
        if not r:
            raise not_found("Recipe not found")
        list_id = body.get("list_id")
        if not isinstance(list_id, str) or not c.execute("SELECT 1 FROM lists WHERE id = ?", (list_id,)).fetchone():
            raise not_found("List not found")
        ingredients = json.loads(r["ingredients"])
        for ing in ingredients:
            insert_item(c, list_id, ing)
    await hub.broadcast("lists")
    return {"added": len(ingredients)}


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
