"""Now playing / speaker control for the media player set for this screen (see media.py).

`layout` is the asking screen's style; a paired screen's own speaker wins over its style's."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import Response

from .. import auth, media
from ..common import bad, body_dict, layout_name

router = APIRouter(prefix="/api/media")


def _svc() -> media.MediaService:
    svc = media.service()
    if svc is None:
        raise HTTPException(status_code=409, detail="Moonlight isn't connected to Home Assistant")
    return svc


def _layout(layout: Any) -> str:
    return layout_name(layout or "compact")


def _speaker(request: Request, layout: str) -> str:
    return media.entity_for(layout, auth.current(request)["display"])


def _entity(request: Request, layout: str) -> str:
    entity = _speaker(request, layout)
    if not entity:
        raise HTTPException(status_code=409, detail="No speaker is set for this screen")
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
async def now_playing(request: Request, layout: str = "compact"):
    layout = _layout(layout)
    entity = _speaker(request, layout)
    svc = media.service()
    if not entity:
        return media.now_playing(layout, "", None)
    if svc is None:
        return media.empty(layout, entity, True, "unavailable", "Moonlight isn't connected to Home Assistant")
    state, error = await svc.get_state(entity)
    return media.now_playing(layout, entity, state, error)


@router.get("/art")
async def art(request: Request, layout: str = "compact", v: str = ""):
    entity = _speaker(request, _layout(layout))
    svc = media.service()
    got = await svc.art(entity, v) if (svc and entity and v) else None
    if got is None:
        return Response(status_code=404)
    data, ctype = got
    # The URL changes with the picture (v = hash of HA's picture URL), so it can be cached for good.
    return Response(data, media_type=ctype, headers={"Cache-Control": "private, max-age=86400, immutable"})


@router.post("/command")
async def command(request: Request, body: dict = Body(...)):
    body = body_dict(body)
    action = body.get("action")
    if not isinstance(action, str):
        raise bad("action is required")
    layout = _layout(body.get("layout"))
    entity = _entity(request, layout)
    svc = _svc()
    try:
        await svc.command(entity, action, body.get("value"))
    except media.MediaError as e:
        raise _fail(e)
    state, error = await svc.get_state(entity)
    return media.now_playing(layout, entity, state, error)


@router.get("/favourites")
async def favourites(request: Request, layout: str = "compact"):
    """Music Assistant favourite playlists and radio stations (empty for other players or on any error)."""
    entity = _speaker(request, _layout(layout))
    svc = media.service()
    if not entity or svc is None:
        return []
    return await svc.favourites(entity)


@router.post("/play")
async def play(request: Request, body: dict = Body(...)):
    body = body_dict(body)
    uri = body.get("uri")
    if not isinstance(uri, str) or not uri:
        raise bad("uri is required")
    layout = _layout(body.get("layout"))
    entity = _entity(request, layout)
    svc = _svc()
    try:
        await svc.play_favourite(entity, uri)
    except media.MediaError as e:
        raise _fail(e)
    state, error = await svc.get_state(entity)
    return media.now_playing(layout, entity, state, error)
