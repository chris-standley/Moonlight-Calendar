"""Nursery updates from Tapestry: the login, the updates and their photos. See tapestry.py."""
from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import FileResponse

from .. import db, tapestry
from ..common import as_int, bad, body_dict, hub, not_found, require_pin

router = APIRouter(prefix="/api")

PHOTO_CACHE = "private, max-age=604800, immutable"  # a changed update's photos get a new url (see `v`)


def _error(e: tapestry.TapestryError) -> HTTPException:
    return HTTPException(status_code=400 if isinstance(e, tapestry.AuthFailed) else 502, detail=str(e))


@router.get("/nursery")
def get_nursery():
    """{configured, email, school, school_name, status, last_error, last_sync, count}; never the password."""
    with db.connect() as c:
        return tapestry.config_out(c)


@router.put("/nursery")
async def save_nursery(body: dict = Body(...)):
    """Connect or change: {pin, email, password (optional once saved), school (optional)}. The login is tried on
    Tapestry first and the newest updates read straight away."""
    body = body_dict(body)
    with db.connect() as c:
        require_pin(c, body.get("pin"))
        cur = tapestry.load_config(c)
    email = body.get("email", cur["email"] if cur else None)
    if not isinstance(email, str) or "@" not in email or len(email) > 200:
        raise bad("Enter the email address you sign in to Tapestry with")
    password = body.get("password")
    if password in (None, "") and cur and email.strip() == cur["email"]:
        password = cur["password"]
    if not isinstance(password, str) or not password:
        raise bad("Enter your Tapestry password")
    school = body.get("school", cur["school"] if cur else "")
    if not isinstance(school, str) or len(school) > 100:
        raise bad("school must be the nursery's name (or part of it)")
    client = tapestry.Client(email, password, school)
    try:
        async with client.http() as http:
            await client.login(http)
    except tapestry.TapestryError as e:
        raise _error(e)
    with db.connect() as c:
        if cur and cur["email"].lower() != email.strip().lower():
            tapestry.forget_all(c)  # another family's account: don't keep the old one's updates
        tapestry.save_config(c, email.strip(), password, school.strip())
    try:
        await tapestry.sync_now(client)
    except tapestry.TapestryError:
        pass  # saved; the status says what went wrong and the regular check tries again
    if tapestry.syncer:
        tapestry.syncer.poke()
    with db.connect() as c:
        return tapestry.config_out(c)


@router.delete("/nursery")
async def delete_nursery(body: dict | None = Body(None)):
    """Disconnect: forget the login and the copied updates and photos (nothing changes on Tapestry)."""
    body = body_dict(body)
    with db.connect() as c:
        require_pin(c, body.get("pin"))
        tapestry.forget_all(c)
    await hub.broadcast("nursery")
    return {"ok": True}


@router.post("/nursery/sync")
async def sync_nursery():
    """Check Tapestry now -> the status as GET /api/nursery. 400 login rejected, 502 Tapestry unreachable."""
    with db.connect() as c:
        if not tapestry.load_config(c):
            raise not_found("Tapestry isn't connected")
    try:
        await tapestry.sync_now()
    except tapestry.TapestryError as e:
        raise _error(e)
    with db.connect() as c:
        return tapestry.config_out(c)


@router.get("/nursery/updates")
def nursery_updates(limit: int = 40):
    """Newest first: [{id, title, notes, author, date, children: [{name, person_id, color}], photos: [{url, video}],
    comments: [{author, date, text}], added_at}]."""
    limit = as_int(limit, "limit")
    if not 1 <= limit <= tapestry.KEEP:
        raise bad(f"limit must be between 1 and {tapestry.KEEP}")
    with db.connect() as c:
        return tapestry.updates_out(c, limit)


@router.get("/nursery/photos/{obs_id}/{n}")
def nursery_photo(obs_id: str, n: int):
    found = tapestry.photo_path(obs_id, n)
    if not found:
        raise not_found("Photo not found")
    path, mime = found
    return FileResponse(path, media_type=mime, headers={"Cache-Control": PHOTO_CACHE, "X-Content-Type-Options": "nosniff"})
