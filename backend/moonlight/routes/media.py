"""Now playing / speaker control for the media player configured per screen layout (see media.py)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import Response

from .. import media
from ..common import bad, body_dict

router = APIRouter(prefix="/api/media")


def _svc() -> media.MediaService:
    svc = media.service()
    if svc is None:
        raise HTTPException(status_code=409, detail="Moonlight isn't connected to Home Assistant")
    return svc


def _entity(layout: Any) -> str:
    entity = media.entity_for(str(layout or "kitchen"))
    if not entity:
        raise HTTPException(status_code=409, detail=f"No media player is set for the {layout} screen")
    return entity


def _fail(e: media.MediaError) -> HTTPException:
    return HTTPException(status_code=e.status, detail=str(e))


@router.get("/players")
async def players():
    """Home Assistant's media_player entities (for the Settings picker); Music Assistant players first."""
    try:
        return await _svc().players()
    except media.MediaError as e:
        raise _fail(e)


@router.get("/now-playing")
async def now_playing(layout: str = "kitchen"):
    entity = media.entity_for(layout)
    svc = media.service()
    if not entity:
        return media.now_playing(layout, "", None)
    if svc is None:
        return media.empty(layout, entity, True, "unavailable", "Moonlight isn't connected to Home Assistant")
    state, error = await svc.get_state(entity)
    return media.now_playing(layout, entity, state, error)


@router.get("/art")
async def art(layout: str = "kitchen", v: str = ""):
    entity = media.entity_for(layout)
    svc = media.service()
    got = await svc.art(entity, v) if (svc and entity and v) else None
    if got is None:
        return Response(status_code=404)
    data, ctype = got
    # The URL changes with the picture (v = hash of HA's picture URL), so it can be cached for good.
    return Response(data, media_type=ctype, headers={"Cache-Control": "private, max-age=86400, immutable"})


@router.post("/command")
async def command(body: dict = Body(...)):
    body = body_dict(body)
    action = body.get("action")
    if not isinstance(action, str):
        raise bad("action is required")
    layout = body.get("layout") or "kitchen"
    entity = _entity(layout)
    svc = _svc()
    try:
        await svc.command(entity, action, body.get("value"))
    except media.MediaError as e:
        raise _fail(e)
    state, error = await svc.get_state(entity)
    return media.now_playing(layout, entity, state, error)


@router.get("/favourites")
async def favourites(layout: str = "kitchen"):
    """Music Assistant favourite playlists and radio stations (empty for other players or on any error)."""
    entity = media.entity_for(layout)
    svc = media.service()
    if not entity or svc is None:
        return []
    return await svc.favourites(entity)


@router.post("/play")
async def play(body: dict = Body(...)):
    body = body_dict(body)
    uri = body.get("uri")
    if not isinstance(uri, str) or not uri:
        raise bad("uri is required")
    layout = body.get("layout") or "kitchen"
    entity = _entity(layout)
    svc = _svc()
    try:
        await svc.play_favourite(entity, uri)
    except media.MediaError as e:
        raise _fail(e)
    state, error = await svc.get_state(entity)
    return media.now_playing(layout, entity, state, error)
