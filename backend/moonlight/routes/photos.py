"""Photo albums for the screensaver: uploads, resized display copies and thumbnails, served to screens."""
from __future__ import annotations

import io
import os
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Body, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from PIL import Image, ImageOps, UnidentifiedImageError

from .. import auth, db
from ..common import as_int, bad, body_dict, hub, log, not_found, req_str, require_pin

try:  # iPhone HEIC uploads; optional so a missing wheel never stops the add-on starting
    import pillow_heif

    pillow_heif.register_heif_opener()
    HEIF_SUPPORTED = True
except Exception:  # pragma: no cover - depends on the platform's wheels
    HEIF_SUPPORTED = False

router = APIRouter(prefix="/api")

MAX_BYTES = 25 * 1024 * 1024
MAX_FILES = 30
DISPLAY_EDGE = 2560
THUMB_SHORT = 400
THUMB_LONG = 800
Image.MAX_IMAGE_PIXELS = 120_000_000  # above this Pillow raises DecompressionBombError
CACHE = {"Cache-Control": "private, max-age=31536000, immutable"}  # a photo id's pixels never change
HEIC_BRANDS = {b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"mif1", b"msf1"}

_data_dir: Path = Path(".")


def configure(data_dir: str | Path) -> None:
    global _data_dir
    _data_dir = Path(data_dir)
    for sub in ("originals", "display", "thumbs"):
        (_data_dir / "photos" / sub).mkdir(parents=True, exist_ok=True)
    with db.connect() as c:
        ensure_default_album(c)


def _path(kind: str, photo_id: str, ext: str = ".jpg") -> Path:
    return _data_dir / "photos" / kind / f"{photo_id}{ext}"


def ensure_default_album(c) -> str:
    r = c.execute("SELECT id FROM albums ORDER BY created_at, rowid LIMIT 1").fetchone()
    if r:
        return r["id"]
    aid = db.new_id("al")
    c.execute("INSERT INTO albums(id, name, created_at) VALUES(?, ?, ?)", (aid, "Family", db.now_iso()))
    return aid


def photo_out(p: dict) -> dict:
    return {
        **{k: p[k] for k in ("id", "album_id", "filename", "width", "height", "taken_at", "uploaded_at", "uploaded_by")},
        "display_url": f"/api/photos/{p['id']}/display",
        "thumb_url": f"/api/photos/{p['id']}/thumb",
    }


def album_out(c, a: dict) -> dict:
    n = c.execute("SELECT COUNT(*) FROM photos WHERE album_id = ?", (a["id"],)).fetchone()[0]
    cover = c.execute(
        "SELECT id FROM photos WHERE album_id = ? ORDER BY uploaded_at DESC, rowid DESC LIMIT 1", (a["id"],)
    ).fetchone()
    return {"id": a["id"], "name": a["name"], "created_at": a["created_at"], "photo_count": n,
            "cover_photo_id": cover["id"] if cover else None}


# ---------------------------------------------------------------- settings hook

def apply_settings(c, body: dict) -> None:
    """Called from PATCH /api/settings for the screensaver keys."""
    if "screensaver_album" in body:
        aid = body["screensaver_album"]
        if aid is not None and not db.row(c, "SELECT id FROM albums WHERE id = ?", (aid,)):
            raise bad("screensaver_album must be an album id or null")
        db.set_setting(c, "screensaver_album", aid)
    if "screensaver_seconds" in body:
        secs = as_int(body["screensaver_seconds"], "screensaver_seconds")
        if not 3 <= secs <= 3600:
            raise bad("screensaver_seconds must be between 3 and 3600")
        db.set_setting(c, "screensaver_seconds", secs)
    if "idle_minutes" in body:
        val = body["idle_minutes"]
        cur = dict(db.get_setting(c, "idle_minutes", db.DEFAULT_SETTINGS["idle_minutes"]))
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            val = {k: val for k in ("hallway", "kitchen")}  # one number: both wall screens
        if not isinstance(val, dict):
            raise bad("idle_minutes must be a number or {hallway, kitchen, phone}")
        for k, v in val.items():
            if k not in ("hallway", "kitchen", "phone"):
                raise bad("idle_minutes keys are hallway, kitchen, phone")
            v = as_int(v, f"idle_minutes.{k}")
            if not 0 <= v <= 1440:
                raise bad("idle_minutes must be between 0 (never) and 1440")
            cur[k] = v
        db.set_setting(c, "idle_minutes", cur)


# ---------------------------------------------------------------- albums

@router.get("/albums")
def list_albums():
    with db.connect() as c:
        ensure_default_album(c)
        return [album_out(c, a) for a in db.rows(c, "SELECT * FROM albums ORDER BY created_at, rowid")]


@router.post("/albums")
async def create_album(body: dict = Body(...)):
    name = req_str(body_dict(body), "name")[:60]
    a = {"id": db.new_id("al"), "name": name, "created_at": db.now_iso()}
    with db.connect() as c:
        c.execute("INSERT INTO albums(id, name, created_at) VALUES(:id, :name, :created_at)", a)
        out = album_out(c, a)
    await hub.broadcast("photos")
    return out


@router.delete("/albums/{album_id}")
async def delete_album(album_id: str, body: dict | None = Body(None)):
    body = body_dict(body)
    with db.connect() as c:
        require_pin(c, body.get("pin"))
        if not db.row(c, "SELECT id FROM albums WHERE id = ?", (album_id,)):
            raise not_found("Album not found")
        ids = [r["id"] for r in db.rows(c, "SELECT id FROM photos WHERE album_id = ?", (album_id,))]
        c.execute("DELETE FROM photos WHERE album_id = ?", (album_id,))
        c.execute("DELETE FROM albums WHERE id = ?", (album_id,))
        if db.get_setting(c, "screensaver_album") == album_id:
            db.set_setting(c, "screensaver_album", None)
        ensure_default_album(c)
    for pid in ids:
        _remove_files(pid)
    await hub.broadcast("photos", "settings")
    return {"ok": True, "deleted_photos": len(ids)}


# ---------------------------------------------------------------- photos

@router.get("/photos")
def list_photos(album: str | None = None):
    sql = "SELECT * FROM photos"
    args: tuple = ()
    if album:
        sql += " WHERE album_id = ?"
        args = (album,)
    sql += " ORDER BY COALESCE(taken_at, uploaded_at) DESC, uploaded_at DESC, rowid DESC"
    with db.connect() as c:
        return [photo_out(p) for p in db.rows(c, sql, args)]


def _is_heic(head: bytes, filename: str) -> bool:
    return (len(head) >= 12 and head[4:8] == b"ftyp" and head[8:12] in HEIC_BRANDS) or \
        filename.lower().endswith((".heic", ".heif"))


def _taken_at(im: Image.Image) -> str | None:
    try:
        exif = im.getexif()
        raw = exif.get_ifd(0x8769).get(0x9003) or exif.get(0x0132)  # DateTimeOriginal, else DateTime
        if not raw:
            return None
        return datetime.strptime(str(raw).strip("\x00 ")[:19], "%Y:%m:%d %H:%M:%S").isoformat()
    except Exception:
        return None


def _to_rgb(im: Image.Image) -> Image.Image:
    if im.mode == "RGB":
        return im
    if im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info):
        rgba = im.convert("RGBA")
        bg = Image.new("RGB", rgba.size, (255, 255, 255))
        bg.paste(rgba, mask=rgba.getchannel("A"))
        return bg
    return im.convert("RGB")


def _save_jpeg(im: Image.Image, dest: Path) -> None:
    tmp = dest.with_suffix(".tmp")
    im.save(tmp, "JPEG", quality=85, optimize=True, progressive=True)
    os.replace(tmp, dest)


def process_and_store(data: bytes, filename: str, photo_id: str) -> dict:
    """Decode, orient, write original + display copy + thumbnail. Raises ValueError with a friendly message."""
    if _is_heic(data[:16], filename) and not HEIF_SUPPORTED:
        raise ValueError("HEIC photos aren't supported on this install; export as JPEG (or set the iPhone "
                         "camera to Most Compatible)")
    try:
        im = Image.open(io.BytesIO(data))
        im.load()
    except Image.DecompressionBombError:
        raise ValueError("Image has too many pixels")
    except (UnidentifiedImageError, OSError, SyntaxError):
        raise ValueError("Not an image Moonlight can read (use JPEG, PNG, WebP, GIF or HEIC)")
    taken = _taken_at(im)
    fmt = (im.format or "").lower()
    im = _to_rgb(ImageOps.exif_transpose(im))
    width, height = im.size

    disp = im.copy()
    disp.thumbnail((DISPLAY_EDGE, DISPLAY_EDGE), Image.LANCZOS)
    scale = min(THUMB_SHORT / min(width, height), THUMB_LONG / max(width, height), 1.0)
    thumb = im.resize((max(1, round(width * scale)), max(1, round(height * scale))), Image.LANCZOS) if scale < 1 else im.copy()

    ext = Path(filename).suffix.lower()
    if not ext or len(ext) > 6 or not ext[1:].isalnum():
        ext = "." + (fmt or "bin")
    _path("originals", photo_id, ext).write_bytes(data)
    _save_jpeg(disp, _path("display", photo_id))
    _save_jpeg(thumb, _path("thumbs", photo_id))
    return {"width": width, "height": height, "taken_at": taken}


def _remove_files(photo_id: str) -> None:
    for kind in ("display", "thumbs"):
        _path(kind, photo_id).unlink(missing_ok=True)
    for f in (_data_dir / "photos" / "originals").glob(f"{photo_id}.*"):
        f.unlink(missing_ok=True)


def _uploader(request: Request) -> str | None:
    a = auth.current(request)
    if a["display"]:
        return a["display"]["name"]
    if a["via"] == "ingress":
        return a["user"] or "Home Assistant"
    return None


@router.post("/photos")
async def upload_photos(request: Request, files: list[UploadFile] = File(...), album_id: str | None = Form(None)):
    if len(files) > MAX_FILES:
        raise bad(f"Upload at most {MAX_FILES} photos at a time")
    with db.connect() as c:
        if album_id:
            if not db.row(c, "SELECT id FROM albums WHERE id = ?", (album_id,)):
                raise not_found("Album not found")
        else:
            album_id = ensure_default_album(c)
    who = _uploader(request)
    uploaded: list[dict] = []
    errors: list[dict] = []
    too_big = 0
    for f in files:
        name = os.path.basename(f.filename or "photo")[:200] or "photo"
        data = await f.read(MAX_BYTES + 1)
        await f.close()
        if len(data) > MAX_BYTES:
            too_big += 1
            errors.append({"filename": name, "detail": f"{name} is larger than {MAX_BYTES // (1024 * 1024)} MB"})
            continue
        pid = db.new_id("ph")
        try:
            meta = await run_in_threadpool(process_and_store, data, name, pid)
        except ValueError as e:
            _remove_files(pid)
            errors.append({"filename": name, "detail": f"{name}: {e}"})
            continue
        except Exception:
            log.exception("Photo upload failed for %s", name)
            _remove_files(pid)
            errors.append({"filename": name, "detail": f"{name}: couldn't process this image"})
            continue
        p = {"id": pid, "album_id": album_id, "filename": name, **meta, "uploaded_at": db.now_iso(), "uploaded_by": who}
        with db.connect() as c:
            c.execute(
                "INSERT INTO photos(id, album_id, filename, width, height, taken_at, uploaded_at, uploaded_by) "
                "VALUES(:id, :album_id, :filename, :width, :height, :taken_at, :uploaded_at, :uploaded_by)", p)
        uploaded.append(photo_out(p))
    if not uploaded:
        status = 413 if too_big == len(files) else 400
        raise HTTPException(status_code=status, detail="; ".join(e["detail"] for e in errors) or "No photos")
    await hub.broadcast("photos")
    return {"uploaded": uploaded, "errors": errors}


@router.delete("/photos/{photo_id}")
async def delete_photo(photo_id: str, body: dict | None = Body(None)):
    body = body_dict(body)
    with db.connect() as c:
        require_pin(c, body.get("pin"))
        if not db.row(c, "SELECT id FROM photos WHERE id = ?", (photo_id,)):
            raise not_found("Photo not found")
        c.execute("DELETE FROM photos WHERE id = ?", (photo_id,))
    _remove_files(photo_id)
    await hub.broadcast("photos")
    return {"ok": True}


def _serve(kind: str, photo_id: str) -> FileResponse:
    if not photo_id.replace("_", "").isalnum():
        raise not_found("Photo not found")
    path = _path(kind, photo_id)
    if not path.is_file():
        raise not_found("Photo not found")
    return FileResponse(path, media_type="image/jpeg", headers=CACHE)


@router.get("/photos/{photo_id}/display")
def photo_display(photo_id: str):
    return _serve("display", photo_id)


@router.get("/photos/{photo_id}/thumb")
def photo_thumb(photo_id: str):
    return _serve("thumbs", photo_id)
