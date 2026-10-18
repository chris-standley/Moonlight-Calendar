"""Recipe collections to and from other apps: Mela (.melarecipes), Paprika (.paprikarecipes) and schema.org Recipe
JSON (what recipe web pages use, read by many apps).

Exports carry the pictures inside the file. Imports work out the kind of file from what's in it, not its name: a zip
of recipes, a single (gzipped) recipe, a JSON file or a saved web page."""
from __future__ import annotations

import base64
import binascii
import gzip
import hashlib
import io
import json
import re
import uuid
import zipfile
from datetime import datetime

from . import recipe_import, recipe_text

FORMATS = {
    "mela": ("melarecipes", "application/zip"),
    "paprika": ("paprikarecipes", "application/zip"),
    "schema": ("json", "application/ld+json"),
}
MAX_RECIPES = 5000


class UnknownFile(recipe_import.ImportError_):
    pass


# ---------------------------------------------------------------- export

def export(recipes: list[dict], pictures: dict[str, tuple[str, bytes]], fmt: str) -> tuple[bytes, str, str]:
    """`recipes` as the API shows them (recipe_out); `pictures` by image id. -> (file, file name, content type)."""
    ext, mime = FORMATS[fmt]
    name = f"Moonlight recipes.{ext}"
    if fmt == "schema":
        nodes = [_schema_node(r, pictures) for r in recipes]
        return json.dumps(nodes, ensure_ascii=False, indent=1).encode(), name, mime
    buf = io.BytesIO()
    used: set[str] = set()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for r in recipes:
            base = _file_name(r["title"], used)
            if fmt == "mela":
                z.writestr(f"{base}.melarecipe", json.dumps(_mela(r, pictures), ensure_ascii=False))
            else:
                z.writestr(f"{base}.paprikarecipe", gzip.compress(json.dumps(_paprika(r, pictures)).encode()))
    return buf.getvalue(), name, mime


def _file_name(title: str, used: set[str]) -> str:
    base = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "", title).strip()[:80] or "Recipe"
    name, n = base, 2
    while name.lower() in used:
        name, n = f"{base} {n}", n + 1
    used.add(name.lower())
    return name


def _duration(minutes: int | None) -> str:
    if not minutes:
        return ""
    h, m = divmod(int(minutes), 60)
    return " ".join(p for p in (f"{h} hr" if h else "", f"{m} min" if m else ""))


def _iso(minutes: int | None) -> str | None:
    if not minutes:
        return None
    h, m = divmod(int(minutes), 60)
    return "PT" + (f"{h}H" if h else "") + (f"{m}M" if m or not h else "")


def _ingredient_lines(r: dict, heading: str) -> list[str]:
    """Headings ("For the sauce:") written the way the other app marks them."""
    return [heading + i["text"].rstrip().rstrip(":") if i["heading"] and heading else i["text"] for i in r["ingredients"]]


def _b64(pictures: dict, iid: str | None) -> str | None:
    p = pictures.get(iid) if iid else None
    return base64.b64encode(p[1]).decode() if p else None


def _mela(r: dict, pictures: dict) -> dict:
    out = {
        "id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"moonlight:{r['id']}")).upper(),
        "title": r["title"], "text": r["description"], "link": r["url"] or "",
        "yield": str(r["servings"] or ""),
        "prepTime": _duration(r["prep_minutes"]), "cookTime": _duration(r["cook_minutes"]),
        "totalTime": _duration(r["minutes"]),
        "ingredients": "\n".join(_ingredient_lines(r, "# ")),
        "instructions": "\n".join(s["text"] for s in r["steps"] if s["text"]),
        "notes": r["notes"], "nutrition": "",
        "categories": [t.replace(",", " ") for t in r["tags"]],
        "favorite": r["favourite"],
        "images": [b for b in [_b64(pictures, r["photo"])] if b],
    }
    return out


def _paprika(r: dict, pictures: dict) -> dict:
    photo = _b64(pictures, r["photo"])
    created = (r.get("created_at") or datetime.now().isoformat())[:19].replace("T", " ")
    out = {
        "uid": str(uuid.uuid5(uuid.NAMESPACE_URL, f"moonlight:{r['id']}")).upper(),
        "name": r["title"], "description": r["description"],
        "ingredients": "\n".join(_ingredient_lines(r, "")),
        "directions": "\n\n".join(s["text"] for s in r["steps"] if s["text"]),
        "notes": r["notes"], "nutritional_info": "",
        "servings": str(r["servings"] or ""),
        "prep_time": _duration(r["prep_minutes"]), "cook_time": _duration(r["cook_minutes"]),
        "total_time": _duration(r["minutes"]),
        "source": "", "source_url": r["url"] or "", "image_url": "",
        "categories": r["tags"], "rating": r["rating"], "difficulty": "",
        "created": created, "photo": "1.jpg" if photo else "", "photo_data": photo, "photos": [],
        "photo_hash": hashlib.sha256(photo.encode()).hexdigest() if photo else "",
    }
    out["hash"] = hashlib.sha256(json.dumps(out, sort_keys=True).encode()).hexdigest()
    return out


def _data_uri(pictures: dict, iid: str | None) -> str | None:
    p = pictures.get(iid) if iid else None
    return f"data:{p[0]};base64,{base64.b64encode(p[1]).decode()}" if p else None


def _schema_node(r: dict, pictures: dict) -> dict:
    node: dict = {
        "@context": "https://schema.org", "@type": "Recipe", "name": r["title"],
        "description": r["description"] or None,
        "image": _data_uri(pictures, r["photo"]),
        "recipeYield": str(r["servings"]) if r["servings"] else None,
        "prepTime": _iso(r["prep_minutes"]), "cookTime": _iso(r["cook_minutes"]), "totalTime": _iso(r["minutes"]),
        "recipeIngredient": [i["text"] for i in r["ingredients"]],
        "recipeInstructions": [{k: v for k, v in {"@type": "HowToStep", "text": s["text"],
                                                  "image": _data_uri(pictures, s["photo"])}.items() if v}
                               for s in r["steps"] if s["text"]],
        "keywords": ", ".join(r["tags"]) or None,
        "url": r["url"],
        "comment": {"@type": "Comment", "text": r["notes"]} if r["notes"] else None,
        "aggregateRating": {"@type": "AggregateRating", "ratingValue": r["rating"], "ratingCount": 1}
        if r["rating"] else None,
    }
    return {k: v for k, v in node.items() if v not in (None, "", [])}


# ---------------------------------------------------------------- import

def parse(data: bytes) -> list[dict]:
    """Every recipe in the file, as drafts: recipe fields plus `photo` and step `photo` as (mime, bytes) or a URL."""
    found = _parse(data, depth=0)
    if not found:
        raise UnknownFile("Moonlight couldn't find any recipes in that file. It reads Mela, Paprika and schema.org "
                          "recipe files, and saved recipe web pages.")
    return found[:MAX_RECIPES]


def _parse(data: bytes, depth: int) -> list[dict]:
    if depth > 3 or not data:
        return []
    if data[:4] == b"PK\x03\x04":  # a zip: Mela or Paprika collection, or a zip of recipe files
        out: list[dict] = []
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                for info in z.infolist():
                    if info.is_dir() or info.filename.startswith("__MACOSX/") or info.file_size > 50_000_000:
                        continue
                    out += _parse(z.read(info), depth + 1)
        except zipfile.BadZipFile:
            return []
        return out
    if data[:2] == b"\x1f\x8b":  # gzip: one Paprika recipe
        try:
            return _parse(gzip.decompress(data), depth + 1)
        except (OSError, EOFError):
            return []
    text = data.decode("utf-8-sig", "replace").strip()
    if text[:1] in "[{":
        try:
            return _from_json(json.loads(text))
        except ValueError:
            return []
    if "<" in text[:2000]:  # a saved web page
        draft, _ = recipe_import.read_page(text, "")
        if draft:
            draft["url"] = draft.get("url") or None
            return [_finish(draft)]
    return []


def _from_json(value) -> list[dict]:
    items = value if isinstance(value, list) else [value]
    out: list[dict] = []
    for v in items:
        if not isinstance(v, dict):
            continue
        if any(k in v for k in ("@type", "@graph", "@context")):
            out += [_finish(recipe_import.from_schema(n, n.get("url") or "") | _schema_extras(n))
                    for n in recipe_import._walk(v) if recipe_import._is_recipe(n)]
        elif isinstance(v.get("title"), str) and ("instructions" in v or "ingredients" in v):
            out.append(_from_mela(v))
        elif isinstance(v.get("name"), str) and ("directions" in v or "ingredients" in v):
            out.append(_from_paprika(v))
        elif isinstance(v.get("recipes"), list):
            out += _from_json(v["recipes"])
    return out


def _schema_extras(n: dict) -> dict:
    rating = n.get("aggregateRating")
    comment = n.get("comment")
    return {
        "rating": _rating(rating.get("ratingValue")) if isinstance(rating, dict) else 0,
        "notes": comment.get("text", "") if isinstance(comment, dict) else "",
    }


def _lines(v) -> list[str]:
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    return [ln.strip() for ln in str(v or "").splitlines() if ln.strip()]


def _ingredients(v) -> list[str]:
    """"# For the sauce" (Mela's headings) -> "For the sauce:", Moonlight's way."""
    out = []
    for ln in _lines(v):
        if ln.startswith("#"):
            ln = ln.lstrip("#").strip().rstrip(":") + ":"
        out.append(ln)
    return out


STEP_NUMBER_RE = re.compile(r"^\s*(?:step\s*)?\d+\s*[.):]\s+", re.IGNORECASE)


def _steps(v) -> list[dict]:
    return [{"text": STEP_NUMBER_RE.sub("", ln.lstrip("#*").strip()), "minutes": None}
            for ln in _lines(v) if ln.lstrip("#*").strip()]


DURATION_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(days?|d|hours?|hrs?|h|minutes?|mins?|m)(?![a-z])", re.IGNORECASE)


def minutes(v) -> int | None:
    """"1 hr 30 mins", "1h30m", "45 minutes", "PT1H30M", "1:30", "20" -> minutes."""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return int(v) or None
    s = str(v or "").strip()
    if not s:
        return None
    if s.upper().startswith("P"):
        return recipe_text.iso_minutes(s)
    if m := re.fullmatch(r"(\d+):(\d{2})", s):
        return int(m.group(1)) * 60 + int(m.group(2)) or None
    if s.isdigit():
        return int(s) or None
    total = 0.0
    for n, unit in DURATION_RE.findall(s.replace(" and ", " ")):
        u = unit[0].lower()
        total += float(n) * (1440 if u == "d" else 60 if u == "h" else 1)
    return int(round(total)) or None


def _rating(v) -> int:
    try:
        return max(0, min(5, int(round(float(v)))))
    except (TypeError, ValueError):
        return 0


def _image(b64) -> tuple[str, bytes] | None:
    if not isinstance(b64, str) or not b64:
        return None
    if b64.startswith("data:"):
        b64 = b64.split(",", 1)[-1]
    try:
        data = base64.b64decode(b64, validate=False)
    except (binascii.Error, ValueError):
        return None
    from .routes.recipes import sniff  # the same picture check as uploads

    mime = sniff(data)
    return (mime, data) if mime else None


def _tags(v) -> list[str]:
    vals = v if isinstance(v, list) else str(v or "").split(",")
    return [str(t).strip().lower()[:30] for t in vals if str(t).strip()]


def _from_mela(v: dict) -> dict:
    images = v.get("images") if isinstance(v.get("images"), list) else []
    return _finish({
        "title": str(v.get("title") or ""), "description": str(v.get("text") or ""),
        "servings": recipe_import._servings(v.get("yield")),
        "prep_minutes": minutes(v.get("prepTime")), "cook_minutes": minutes(v.get("cookTime")),
        "minutes": minutes(v.get("totalTime")),
        "ingredients": _ingredients(v.get("ingredients")), "steps": _steps(v.get("instructions")),
        "tags": _tags(v.get("categories")),
        "notes": "\n\n".join(x for x in (str(v.get("notes") or "").strip(), str(v.get("nutrition") or "").strip()) if x),
        "url": str(v.get("link") or "") or None,
        "favourite": bool(v.get("favorite")),
        "photo": next((p for p in (_image(i) for i in images) if p), None),
    })


def _from_paprika(v: dict) -> dict:
    photo = _image(v.get("photo_data"))
    if not photo:
        for p in v.get("photos") or []:
            if isinstance(p, dict) and (photo := _image(p.get("data"))):
                break
    return _finish({
        "title": str(v.get("name") or ""), "description": str(v.get("description") or ""),
        "servings": recipe_import._servings(v.get("servings")),
        "prep_minutes": minutes(v.get("prep_time")), "cook_minutes": minutes(v.get("cook_time")),
        "minutes": minutes(v.get("total_time")),
        "ingredients": _ingredients(v.get("ingredients")), "steps": _steps(v.get("directions")),
        "tags": _tags(v.get("categories")),
        "notes": "\n\n".join(x for x in (str(v.get("notes") or "").strip(),
                                         str(v.get("nutritional_info") or "").strip()) if x),
        "url": str(v.get("source_url") or "") or None,
        "rating": _rating(v.get("rating")),
        "photo": photo or (v.get("image_url") or None),
    })


def _finish(d: dict) -> dict:
    """Fill the gaps so the draft passes the usual recipe checks."""
    photo = d.pop("image_url", None)
    if d.get("photo") is None and photo:
        d["photo"] = _image(photo) if str(photo).startswith("data:") else photo
    steps = []
    for s in d.get("steps") or []:
        img = s.pop("image_url", None)
        steps.append({**s, "photo": _image(img) if img and img.startswith("data:") else img})
    d["steps"] = steps
    d["title"] = (d.get("title") or "").strip()[:120] or "Untitled recipe"
    d.setdefault("rating", 0)
    d.setdefault("favourite", False)
    d.setdefault("notes", "")
    return d
