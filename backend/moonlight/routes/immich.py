"""Photo screensaver: Immich connection settings, the chosen photos and the preview proxy. See immich.py."""
from __future__ import annotations

import re

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask

from .. import db, immich
from ..common import as_int, bad, body_dict, hub, layout_name, not_found, require_pin

router = APIRouter(prefix="/api")

UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
PREVIEW_CACHE = "private, max-age=86400"  # a day: an asset edited in Immich gets a new preview


# ---------------------------------------------------------------- settings hook

def apply_settings(c, body: dict) -> None:
    """Called from PATCH /api/settings for the screensaver keys."""
    if "photo_details" in body:
        if not isinstance(body["photo_details"], bool):
            raise bad("photo_details must be a boolean")
        db.set_setting(c, "photo_details", body["photo_details"])
    if "screensaver_seconds" in body:
        secs = as_int(body["screensaver_seconds"], "screensaver_seconds")
        if not 3 <= secs <= 3600:
            raise bad("screensaver_seconds must be between 3 and 3600")
        db.set_setting(c, "screensaver_seconds", secs)
    if "idle_minutes" in body:
        val = body["idle_minutes"]
        cur = dict(db.get_setting(c, "idle_minutes", db.DEFAULT_SETTINGS["idle_minutes"]))
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            val = {k: val for k in ("large", "compact")}  # one number: both wall screen styles
        if not isinstance(val, dict):
            raise bad("idle_minutes must be a number or {large, compact, phone}")
        for k, v in val.items():
            k = layout_name(k, "idle_minutes keys")
            v = as_int(v, f"idle_minutes.{k}")
            if not 0 <= v <= 1440:
                raise bad("idle_minutes must be between 0 (never) and 1440")
            cur[k] = v
        db.set_setting(c, "idle_minutes", cur)


# ---------------------------------------------------------------- helpers

def config_out(cfg: dict | None, cache: immich.Cache | None = None) -> dict:
    """Never includes the API key."""
    cache = cache or immich.cache
    fresh = cache.key is not None and cache.key == immich.Cache.config_key(cfg)
    if not cfg:
        return {"configured": False, "server_url": "", "key_set": False, "album_ids": [], "favorites": False,
                "memories": False, "skip_cert_check": False, "status": "unconfigured", "last_error": None, "last_refresh": None,
                "photo_count": 0, "version": None}
    return {
        "configured": True, "server_url": cfg["server_url"], "key_set": bool(cfg["api_key"]),
        "album_ids": cfg["album_ids"], "favorites": cfg["favorites"], "memories": cfg["memories"],
        "skip_cert_check": cfg.get("skip_cert_check", False),
        "status": cache.status if fresh else "pending", "last_error": cache.error if fresh else None,
        "last_refresh": cache.last_refresh if fresh else None, "photo_count": len(cache.photos) if fresh else 0,
        "version": cache.version if fresh else None,
    }


def _url(body: dict) -> str:
    raw = body.get("server_url")
    if not isinstance(raw, str) or not raw.strip():
        raise bad("server_url is required")
    url = immich.normalize_url(raw)
    if not re.match(r"^https?://[^/\s?#]+", url) or any(ch in url for ch in "?#") or "@" in url.split("/")[2]:
        raise bad("server_url must look like http://192.168.1.10:2283")
    return url


def _key(body: dict) -> str:
    key = body.get("api_key")
    if not isinstance(key, str) or not key.strip():
        raise bad("api_key is required")
    key = key.strip()
    if len(key) > 200 or not key.isprintable() or " " in key:
        raise bad("api_key doesn't look like an Immich API key")
    return key


def _album_ids(body: dict) -> list[str]:
    ids = body.get("album_ids")
    if not isinstance(ids, list) or not all(isinstance(i, str) and UUID.match(i) for i in ids):
        raise bad("album_ids must be a list of Immich album ids")
    if len(ids) > 50:
        raise bad("Choose at most 50 albums")
    return list(dict.fromkeys(ids))


def _bool(body: dict, key: str) -> bool:
    if not isinstance(body[key], bool):
        raise bad(f"{key} must be a boolean")
    return body[key]


def _error(e: immich.ImmichError) -> HTTPException:
    return HTTPException(status_code=400 if isinstance(e, immich.AuthFailed) else 502, detail=str(e))


# ---------------------------------------------------------------- endpoints

@router.get("/immich")
async def get_immich():
    cache = await immich.cache.get()
    with db.connect() as c:
        return config_out(immich.load_config(c), cache)


@router.put("/immich")
async def save_immich(body: dict = Body(...)):
    """Connect or change: {pin, server_url, api_key (optional once saved), album_ids, favorites, memories, skip_cert_check}.
    A new URL or key is checked against Immich before it is saved."""
    body = body_dict(body)
    with db.connect() as c:
        require_pin(c, body.get("pin"))
        cur = immich.load_config(c)
    cfg = dict(cur) if cur else {"server_url": "", "api_key": "", "album_ids": [], "favorites": False, "memories": False,
                                 "skip_cert_check": False}
    if "server_url" in body or not cur:
        cfg["server_url"] = _url(body)
    if body.get("api_key") not in (None, "") or not cur:
        cfg["api_key"] = _key(body)
    if "album_ids" in body:
        cfg["album_ids"] = _album_ids(body)
    for k in ("favorites", "memories", "skip_cert_check"):
        if k in body:
            cfg[k] = _bool(body, k)
    if not cur or any(cfg[k] != cur.get(k) for k in ("server_url", "api_key", "skip_cert_check")):
        try:
            await immich.Client(cfg["server_url"], cfg["api_key"], cfg["skip_cert_check"]).albums()
        except immich.ImmichError as e:
            raise _error(e)
    with db.connect() as c:
        immich.save_config(c, cfg)
    cache = await immich.cache.get(force=True)
    await hub.broadcast("photos")
    return config_out(cfg, cache)


@router.delete("/immich")
async def delete_immich(body: dict | None = Body(None)):
    """Disconnect: forget the URL, key and albums (nothing changes in Immich)."""
    body = body_dict(body)
    with db.connect() as c:
        require_pin(c, body.get("pin"))
        immich.delete_config(c)
    immich.cache.reset()
    await hub.broadcast("photos")
    return {"ok": True}


@router.post("/immich/test")
async def test_immich(body: dict = Body(...)):
    """Check a URL + key (or the saved ones) without saving: -> {ok, version, albums}. 400 key rejected, 502 unreachable."""
    body = body_dict(body)
    with db.connect() as c:
        require_pin(c, body.get("pin"))
        cur = immich.load_config(c)
    url = _url(body) if body.get("server_url") else (cur or {}).get("server_url")
    key = _key(body) if body.get("api_key") else (cur or {}).get("api_key")
    if not url or not key:
        raise bad("Enter the Immich address and an API key")
    skip = _bool(body, "skip_cert_check") if "skip_cert_check" in body else bool((cur or {}).get("skip_cert_check"))
    try:
        return await immich.Client(url, key, skip).test()
    except immich.ImmichError as e:
        raise _error(e)


@router.get("/immich/albums")
async def immich_albums():
    """The saved account's albums, live from Immich (for choosing which ones the screensaver shows)."""
    with db.connect() as c:
        cfg = immich.load_config(c)
    if not cfg:
        raise not_found("Immich isn't connected")
    try:
        return await immich.Client(cfg["server_url"], cfg["api_key"], cfg["skip_cert_check"]).albums()
    except immich.ImmichError as e:
        raise _error(e)


@router.get("/screensaver/photos")
async def screensaver_photos():
    """The photos to show: {source: "immich"|"none", status, photos: [{id, width, height, taken_at, place, url}]}.
    Empty `photos` = show the built-in scenes (not set up, nothing chosen, or Immich down with nothing cached)."""
    cache = await immich.cache.get()
    if cache.status == "unconfigured":
        return {"source": "none", "status": "unconfigured", "photos": []}
    return {"source": "immich", "status": cache.status, "photos": cache.photos}


@router.get("/immich/assets/{asset_id}/preview")
async def immich_preview(asset_id: str):
    """Proxy one preview image. Only assets in the chosen albums/favourites/memories are served."""
    cache = await immich.cache.get()
    if not UUID.match(asset_id) or asset_id not in cache.ids:
        raise not_found("Photo not found")
    with db.connect() as c:
        cfg = immich.load_config(c)
    if not cfg:
        raise not_found("Photo not found")
    try:
        http, r = await immich.Client(cfg["server_url"], cfg["api_key"], cfg["skip_cert_check"]).preview(asset_id)
    except immich.ImmichError as e:
        cache.mark_failed(e)
        raise HTTPException(status_code=502, detail=str(e))
    ctype = r.headers.get("content-type", "image/jpeg")
    if not ctype.startswith("image/"):
        await r.aclose()
        await http.aclose()
        raise HTTPException(status_code=502, detail="Immich didn't send an image")
    headers = {"Cache-Control": PREVIEW_CACHE, "X-Content-Type-Options": "nosniff"}
    for h in ("content-length", "etag", "last-modified"):
        if h in r.headers and not (h == "content-length" and "content-encoding" in r.headers):
            headers[h] = r.headers[h]

    async def close():
        await r.aclose()
        await http.aclose()

    return StreamingResponse(r.aiter_bytes(), media_type=ctype.split(";")[0], headers=headers,
                             background=BackgroundTask(close))
