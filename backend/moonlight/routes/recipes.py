"""Recipes: the recipe box, importing (link, text, photos), adding ingredients to a list, and uploaded pictures."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import Response

from .. import db, recipe_import, recipe_text
from ..common import as_date, as_int, bad, body_dict, hub, not_found, opt_str, req_str, require_pin
from .lists import insert_item

router = APIRouter(prefix="/api")

MAX_IMAGE_BYTES = 10_000_000
MAX_INGREDIENTS = 200
MAX_STEPS = 100
IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}


# ---------------------------------------------------------------- pictures

def sniff(data: bytes) -> str | None:
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:4] == b"GIF8":
        return "image/gif"
    return None


def store_image(c, data: bytes) -> dict:
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="That picture is too big (10 MB at most)")
    mime = sniff(data)
    if not mime:
        raise bad("Pictures must be JPEG, PNG, WebP or GIF")
    iid = db.new_id("img")
    c.execute("INSERT INTO images(id, mime, data, created_at) VALUES(?,?,?,?)", (iid, mime, data, db.now_iso()))
    return {"id": iid, "url": image_url(iid)}


def image_url(iid: str | None) -> str | None:
    return f"/api/images/{iid}" if iid else None


def _image_id(c, value, key: str) -> str | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str) or not c.execute("SELECT 1 FROM images WHERE id = ?", (value,)).fetchone():
        raise bad(f"{key} must be an uploaded picture (POST /api/images) or null")
    return value


def tidy_images(c) -> None:
    """Forget pictures nothing uses any more (a day's grace for ones uploaded to a recipe not saved yet)."""
    cutoff = (datetime.now() - timedelta(days=1)).replace(microsecond=0).isoformat()
    for (iid,) in c.execute("SELECT id FROM images WHERE created_at < ?", (cutoff,)).fetchall():
        used = c.execute("SELECT 1 FROM recipes WHERE photo = ? OR steps LIKE ? LIMIT 1", (iid, f'%"{iid}"%')).fetchone()
        if not used:
            c.execute("DELETE FROM images WHERE id = ?", (iid,))


@router.post("/images")
async def upload_image(request: Request):
    """Raw picture bytes in the body (any image Content-Type) -> {id, url}."""
    data = await request.body()
    if not data:
        raise bad("Send the picture as the request body")
    with db.connect() as c:
        return store_image(c, data)


@router.get("/images/{image_id}")
def get_image(image_id: str):
    with db.connect() as c:
        r = db.row(c, "SELECT mime, data FROM images WHERE id = ?", (image_id,))
    if not r:
        raise not_found("Picture not found")
    # Ids are never reused, so screens can keep a picture for good.
    return Response(content=r["data"], media_type=r["mime"], headers={"Cache-Control": "private, max-age=31536000, immutable"})


# ---------------------------------------------------------------- recipe shape

def _total(r: dict) -> int | None:
    if r.get("minutes") is not None:
        return r["minutes"]
    if r.get("prep_minutes") is None and r.get("cook_minutes") is None:
        return None
    return (r.get("prep_minutes") or 0) + (r.get("cook_minutes") or 0)


def step_out(s: dict) -> dict:
    text = s.get("text", "")
    return {"text": text, "minutes": s.get("minutes"), "photo": s.get("photo"), "photo_url": image_url(s.get("photo")),
            "timers": recipe_text.step_timers(text, s.get("minutes")), "metric_text": recipe_text.metric_note(text)}


def _lines(raw) -> list[str]:
    """Stored ingredients: lines of text (older versions stored the same)."""
    vals = json.loads(raw) if isinstance(raw, str) else raw or []
    return [v if isinstance(v, str) else str(v.get("text", "")) for v in vals]


def recipe_out(r: dict) -> dict:
    steps = json.loads(r["steps"]) if isinstance(r.get("steps"), str) else r.get("steps") or []
    tags = json.loads(r["tags"]) if isinstance(r.get("tags"), str) else r.get("tags") or []
    return {
        "id": r.get("id"), "title": r["title"], "emoji": r.get("emoji") or "", "description": r.get("description") or "",
        "photo": r.get("photo"), "photo_url": image_url(r.get("photo")),
        "rating": r.get("rating") or 0, "favourite": bool(r.get("favourite")),
        "servings": r.get("servings"), "prep_minutes": r.get("prep_minutes"), "cook_minutes": r.get("cook_minutes"),
        "minutes": _total(r),
        "ingredients": [recipe_text.parse_ingredient(t) for t in _lines(r.get("ingredients"))],
        "steps": [step_out(s) for s in steps],
        "tags": tags, "notes": r.get("notes") or "", "url": r.get("url"),
        "cooked_count": r.get("cooked_count") or 0, "last_cooked": r.get("last_cooked"),
        "created_at": r.get("created_at"), "updated_at": r.get("updated_at"),
    }


def _opt_int(body: dict, key: str, lo: int, hi: int) -> int | None:
    v = body.get(key)
    if v in (None, ""):
        return None
    n = as_int(v, key)
    if not lo <= n <= hi:
        raise bad(f"{key} must be between {lo} and {hi}")
    return n


def _text(v, key: str, limit: int) -> str:
    if not isinstance(v, str):
        raise bad(f"{key} must be text")
    v = v.strip()
    if len(v) > limit:
        raise bad(f"{key} is too long ({limit} characters at most)")
    return v


def recipe_fields(c, body: dict, partial: bool, check_images: bool = True) -> dict:
    """Validated recipe columns from a POST (all) or PATCH (only those present) body, ready to store."""
    out: dict = {}
    has = lambda k: not partial or k in body  # noqa: E731
    if has("title"):
        out["title"] = req_str(body, "title")[:120]
    if has("emoji"):
        out["emoji"] = opt_str(body, "emoji").strip()[:8]
    if has("description"):
        out["description"] = _text(body.get("description") or "", "description", 4000)
    if has("notes"):
        out["notes"] = _text(body.get("notes") or "", "notes", 8000)
    if has("url"):
        out["url"] = opt_str(body, "url").strip() or None
    if has("photo"):
        out["photo"] = _image_id(c, body.get("photo"), "photo") if check_images else (body.get("photo") or None)
    if has("rating"):
        out["rating"] = _opt_int(body, "rating", 0, 5) or 0
    if has("favourite"):
        if not isinstance(body.get("favourite", False), bool):
            raise bad("favourite must be true or false")
        out["favourite"] = int(body.get("favourite", False))
    if has("servings"):
        out["servings"] = _opt_int(body, "servings", 1, 100)
    for k in ("prep_minutes", "cook_minutes", "minutes"):
        if has(k):
            out[k] = _opt_int(body, k, 0, 10000)
    if has("ingredients"):
        ings = body.get("ingredients") or []
        if not isinstance(ings, list):
            raise bad("ingredients must be a list")
        lines = []
        for i in ings:
            t = i if isinstance(i, str) else i.get("text") if isinstance(i, dict) else None
            if not isinstance(t, str):
                raise bad("each ingredient must be text (or {text})")
            if t.strip():
                lines.append(_text(t, "ingredient", 300))
        if len(lines) > MAX_INGREDIENTS:
            raise bad(f"at most {MAX_INGREDIENTS} ingredients")
        out["ingredients"] = lines
    if has("steps"):
        steps = body.get("steps") or []
        if not isinstance(steps, list):
            raise bad("steps must be a list")
        clean = []
        for s in steps:
            s = {"text": s} if isinstance(s, str) else s
            if not isinstance(s, dict) or not isinstance(s.get("text"), str):
                raise bad("each step must be text (or {text, minutes, photo})")
            text = _text(s["text"], "step", 3000)
            photo = (_image_id(c, s.get("photo"), "step photo") if check_images else s.get("photo")) or None
            if not text and not photo:
                continue
            minutes = s.get("minutes")
            if minutes in (None, ""):
                minutes = None
            elif isinstance(minutes, bool) or not isinstance(minutes, (int, float)) or not 0 < minutes <= 1440:
                raise bad("step minutes must be a number from 0 to 1440, or null")
            clean.append({"text": text, "minutes": minutes, "photo": photo})
        if len(clean) > MAX_STEPS:
            raise bad(f"at most {MAX_STEPS} steps")
        out["steps"] = clean
    if has("tags"):
        tags = body.get("tags") or []
        if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
            raise bad("tags must be a list of words")
        out["tags"] = list(dict.fromkeys(t.strip().lower()[:30] for t in tags if t.strip()))[:20]
    return out


def _store(fields: dict) -> dict:
    """JSON-encode list columns for SQLite."""
    return {k: json.dumps(v) if k in ("ingredients", "steps", "tags") else v for k, v in fields.items()}


def _get(c, recipe_id: str) -> dict:
    r = db.row(c, "SELECT * FROM recipes WHERE id = ?", (recipe_id,))
    if not r:
        raise not_found("Recipe not found")
    return r


# ---------------------------------------------------------------- recipe box

@router.get("/recipes")
def list_recipes():
    with db.connect() as c:
        return [recipe_out(r) for r in db.rows(c, "SELECT * FROM recipes ORDER BY title COLLATE NOCASE")]


@router.get("/recipes/{recipe_id}")
def get_recipe(recipe_id: str):
    with db.connect() as c:
        return recipe_out(_get(c, recipe_id))


@router.post("/recipes")
async def create_recipe(body: dict = Body(...)):
    with db.connect() as c:
        fields = recipe_fields(c, body_dict(body), partial=False)
        now = db.now_iso()
        row = {"id": db.new_id("rc"), **_store(fields), "created_at": now, "updated_at": now}
        cols = ", ".join(row)
        c.execute(f"INSERT INTO recipes({cols}) VALUES({', '.join('?' * len(row))})", tuple(row.values()))
        out = recipe_out(_get(c, row["id"]))
        tidy_images(c)
    await hub.broadcast("recipes")
    return out


@router.patch("/recipes/{recipe_id}")
async def update_recipe(recipe_id: str, body: dict = Body(...)):
    with db.connect() as c:
        _get(c, recipe_id)
        fields = _store(recipe_fields(c, body_dict(body), partial=True))
        if fields:
            fields["updated_at"] = db.now_iso()
            sets = ", ".join(f"{k} = ?" for k in fields)
            c.execute(f"UPDATE recipes SET {sets} WHERE id = ?", (*fields.values(), recipe_id))
        out = recipe_out(_get(c, recipe_id))
        tidy_images(c)
    await hub.broadcast("recipes")
    return out


@router.delete("/recipes/{recipe_id}")
async def delete_recipe(recipe_id: str):
    """Deletes the recipe; planned meals that used it keep their title but lose the link."""
    with db.connect() as c:
        if c.execute("DELETE FROM recipes WHERE id = ?", (recipe_id,)).rowcount == 0:
            raise not_found("Recipe not found")
        unlinked = c.execute("UPDATE meals SET recipe_id = NULL WHERE recipe_id = ?", (recipe_id,)).rowcount
        tidy_images(c)
    await hub.broadcast("recipes")
    if unlinked:
        await hub.broadcast("meals")
    return {"ok": True}


@router.post("/recipes/{recipe_id}/cooked")
async def cooked(recipe_id: str, body: dict | None = Body(None)):
    """Made it: counts up, remembers the day (`date`, default today)."""
    body = body_dict(body)
    day = as_date(body["date"], "date") if body.get("date") else date.today().isoformat()
    with db.connect() as c:
        r = _get(c, recipe_id)
        last = max(filter(None, (r.get("last_cooked"), day)))
        c.execute("UPDATE recipes SET cooked_count = cooked_count + 1, last_cooked = ? WHERE id = ?", (last, recipe_id))
        out = recipe_out(_get(c, recipe_id))
    await hub.broadcast("recipes")
    return out


@router.post("/recipes/{recipe_id}/to-list")
async def recipe_to_list(recipe_id: str, body: dict = Body(...)):
    """{list_id, items?: [str]}: the chosen lines (already scaled by the screen), else every ingredient."""
    body = body_dict(body)
    with db.connect() as c:
        r = _get(c, recipe_id)
        list_id = body.get("list_id")
        if not isinstance(list_id, str) or not c.execute("SELECT 1 FROM lists WHERE id = ?", (list_id,)).fetchone():
            raise not_found("List not found")
        items = body.get("items")
        if items is None:
            items = [i["text"] for i in map(recipe_text.parse_ingredient, _lines(r["ingredients"])) if not i["heading"]]
        if not isinstance(items, list) or not all(isinstance(i, str) for i in items):
            raise bad("items must be a list of text")
        items = [i.strip()[:300] for i in items if i.strip()][:MAX_INGREDIENTS]
        for title in items:
            insert_item(c, list_id, title)
    await hub.broadcast("lists")
    return {"added": len(items)}


# ---------------------------------------------------------------- drafts and importing

@router.post("/recipes/preview")
def preview(body: dict = Body(...)):
    """A recipe body as it would read once saved (parsed ingredients, timers, metric), without saving it."""
    body = body_dict(body)
    with db.connect() as c:
        fields = recipe_fields(c, {"title": "-", **body}, partial=False, check_images=False)
    return recipe_out({"id": None, **fields})


def reader(c) -> tuple[str | None, str]:
    return db.get_setting(c, "recipe_reader_key"), db.get_setting(c, "recipe_reader_model") or recipe_import.READER_MODEL


NO_READER = ("Reading photos needs Claude: add an Anthropic API key in Settings › Recipes. "
             "The iPhone app can read photos on the phone without one.")


async def _download_image(url: str | None) -> dict | None:
    if not url or not url.startswith(("http://", "https://")):
        return None
    try:
        data, _ = await recipe_import.fetch(url, MAX_IMAGE_BYTES)
    except recipe_import.ImportError_:
        return None
    if not sniff(data):
        return None
    with db.connect() as c:
        return store_image(c, data)


@router.post("/recipes/import")
async def import_recipe(body: dict = Body(...)):
    """One of {url} (a recipe web page), {text} (typed, pasted or read from a photo on the phone) or {images: [ids]}
    (photos of a cookbook page, read by Claude). `use_reader: true` with text asks Claude instead of the built-in
    reading. Returns an unsaved draft, shaped like a Recipe with id null."""
    body = body_dict(body)
    with db.connect() as c:
        key, model = reader(c)
        photos = []
        for iid in body.get("images") or []:
            r = db.row(c, "SELECT mime, data FROM images WHERE id = ?", (iid,)) if isinstance(iid, str) else None
            if not r:
                raise bad("images must be uploaded pictures (POST /api/images)")
            photos.append((r["mime"], r["data"]))
    if len(photos) > 6:
        raise bad("at most 6 pages at a time")
    try:
        if body.get("url"):
            url = _text(body["url"], "url", 2000)
            page, _ = await recipe_import.fetch(url)
            draft, page_text = recipe_import.read_page(page.decode("utf-8", "replace"), url)
            if draft is None:
                if not key:
                    raise recipe_import.ImportError_(
                        "That page doesn't mark out its recipe, so Moonlight can't pick it out on its own. Copy the "
                        "recipe's text and paste it instead, or add an Anthropic API key in Settings › Recipes.")
                draft = await recipe_import.read_with_claude(key, model, text=page_text)
                draft["url"] = url
        elif photos:
            if not key:
                raise HTTPException(status_code=409, detail=NO_READER)
            draft = await recipe_import.read_with_claude(key, model, images=photos)
        elif isinstance(body.get("text"), str) and body["text"].strip():
            text = _text(body["text"], "text", 60_000)
            if body.get("use_reader") and key:
                draft = await recipe_import.read_with_claude(key, model, text=text)
            else:
                draft = recipe_text.parse_text(text)
                if not draft["ingredients"] and not draft["steps"]:
                    raise recipe_import.ImportError_("No recipe found in that text.")
        else:
            raise bad("Send a url, some text, or images")
    except recipe_import.ImportError_ as e:
        raise HTTPException(status_code=422, detail=str(e))
    # Pictures from the web page become the recipe's and the steps' photos.
    photo = await _download_image(draft.pop("image_url", None))
    steps = []
    for i, s in enumerate(draft.get("steps") or []):
        img = await _download_image(s.pop("image_url", None)) if i < 30 else None
        steps.append({**s, "photo": img["id"] if img else None})
    draft["steps"] = steps
    draft["photo"] = photo["id"] if photo else None
    draft.setdefault("title", "")
    with db.connect() as c:
        fields = recipe_fields(c, {**draft, "title": draft["title"] or "Untitled recipe"}, partial=False, check_images=False)
    return recipe_out({"id": None, **fields})


# ---------------------------------------------------------------- Claude, for reading photos (Settings › Recipes)

def reader_out(c) -> dict:
    key, model = reader(c)
    return {"configured": bool(key), "model": model, "key_hint": f"…{key[-4:]}" if key else None}


@router.get("/recipes-reader")
def get_reader():
    with db.connect() as c:
        return reader_out(c)


@router.put("/recipes-reader")
async def put_reader(body: dict = Body(...)):
    """{pin, api_key?, model?}: the Anthropic API key Moonlight uses to read recipe photos. Never returned."""
    body = body_dict(body)
    with db.connect() as c:
        require_pin(c, body.get("pin"))
        if "api_key" in body:
            k = body["api_key"]
            if not isinstance(k, str) or not k.strip().startswith("sk-ant-") or len(k.strip()) > 300 or " " in k.strip():
                raise bad("That doesn't look like an Anthropic API key (they start with sk-ant-)")
            db.set_setting(c, "recipe_reader_key", k.strip())
        if "model" in body:
            m = body["model"]
            if m not in (None, "") and (not isinstance(m, str) or not m.startswith("claude-") or len(m) > 60):
                raise bad("model must be a Claude model id such as claude-opus-5-5")
            db.set_setting(c, "recipe_reader_model", m or None)
        out = reader_out(c)
    await hub.broadcast("settings")
    return out


@router.delete("/recipes-reader")
async def delete_reader(body: dict | None = Body(None)):
    with db.connect() as c:
        require_pin(c, body_dict(body).get("pin"))
        c.execute("DELETE FROM settings WHERE key IN ('recipe_reader_key', 'recipe_reader_model')")
        out = reader_out(c)
    await hub.broadcast("settings")
    return out
