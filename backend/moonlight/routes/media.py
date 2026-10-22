"""Now playing / speaker control for the media player set for this screen (see media.py).

`layout` is the asking screen's style; a paired screen's own speaker wins over its style's."""
from __future__ import annotations

import contextlib
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import Response

from .. import auth, db, media, music
from ..common import bad, body_dict, hub, layout_name, require_pin

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
    return await _np(svc, layout, entity)


async def _np(svc: media.MediaService, layout: str, entity: str) -> dict:
    eff, state, error, speaker = await media.resolve(svc, entity)
    return media.now_playing(layout, eff, state, error, speaker)


@router.get("/art")
async def art(request: Request, layout: str = "compact", v: str = ""):
    entity = _speaker(request, _layout(layout))
    svc = media.service()
    got = None
    if svc and entity and v:
        eff, *_ = await media.resolve(svc, entity)
        got = await svc.art(eff, v)
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
    eff, *_ = await media.resolve(svc, entity)
    try:
        await svc.command(eff, action, body.get("value"))
    except media.MediaError as e:
        raise _fail(e)
    return await _np(svc, layout, entity)


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
    """`{layout, uri}` plays a Music Assistant favourite (as before). `{layout, id, type, enqueue}` plays anything
    from the library or search: enqueue replace (play now, the default), next, or add (end of the queue)."""
    body = body_dict(body)
    layout = _layout(body.get("layout"))
    entity = _entity(request, layout)
    svc = _svc()
    media_id = body.get("id")
    try:
        if isinstance(media_id, str) and media_id:
            state, _ = await svc.get_state(entity)
            mtype = body.get("type") if isinstance(body.get("type"), str) else ""
            await music.for_service(svc).play(entity, state, media_id, mtype, str(body.get("enqueue") or "replace"))
        else:
            uri = body.get("uri")
            if not isinstance(uri, str) or not uri:
                raise bad("id (or uri) is required")
            await svc.play_favourite(entity, uri)
    except media.MediaError as e:
        raise _fail(e)
    return await _np(svc, layout, entity)


# ---------------------------------------------------------------- Music tab

@router.get("/queue")
async def queue(request: Request, layout: str = "compact"):
    """What's playing and what's next on this screen's speaker (see music.py for where it comes from)."""
    layout = _layout(layout)
    entity = _entity(request, layout)
    svc = _svc()
    eff, state, _, speaker = await media.resolve(svc, entity)
    art_url = media.now_playing(layout, eff, state, None, speaker)["art_url"]
    try:
        return await music.for_service(svc).queue(eff, state, art_url)
    except media.MediaError as e:
        raise _fail(e)


@router.post("/queue")
async def queue_action(request: Request, body: dict = Body(...)):
    """`{layout, action: play|remove|next, key}`: jump to, remove, or move up to play next, a track in the queue."""
    body = body_dict(body)
    layout = _layout(body.get("layout"))
    entity = _entity(request, layout)
    svc = _svc()
    eff, state, _, _ = await media.resolve(svc, entity)
    key = body.get("key")
    if not isinstance(key, (str, int)) or isinstance(key, bool) or str(key) == "":
        raise bad("key is required")
    try:
        await music.for_service(svc).queue_action(eff, state, str(body.get("action") or ""), str(key))
    except media.MediaError as e:
        raise _fail(e)
    await hub.broadcast("media")
    return {"ok": True}


@router.get("/browse")
async def browse(request: Request, layout: str = "compact", id: str | None = None, type: str | None = None):
    """The speaker's library through Home Assistant's media browser; no id = the top level."""
    entity = _entity(request, _layout(layout))
    try:
        return await music.for_service(_svc()).browse(entity, id, type)
    except media.MediaError as e:
        raise _fail(e)


@router.get("/search")
async def search(request: Request, layout: str = "compact", q: str = ""):
    entity = _entity(request, _layout(layout))
    q = q.strip()
    if not q:
        return []
    svc = _svc()
    state, _ = await svc.get_state(entity)
    try:
        return await music.for_service(svc).search(state, q[:100])
    except media.MediaError as e:
        raise _fail(e)


@router.get("/thumb")
async def thumb(k: str = ""):
    svc = media.service()
    got = await music.for_service(svc).thumb(k) if (svc and k) else None
    if got is None:
        return Response(status_code=404)
    data, ctype = got
    return Response(data, media_type=ctype, headers={"Cache-Control": "private, max-age=86400"})


@router.get("/rooms")
async def rooms(request: Request, layout: str = "compact"):
    """The speakers this one can be grouped with, which are in its group, and their volumes."""
    entity = _entity(request, _layout(layout))
    svc = _svc()
    state, _ = await svc.get_state(entity)
    try:
        return await music.for_service(svc).rooms(entity, state)
    except media.MediaError as e:
        raise _fail(e)


@router.post("/rooms")
async def room_action(request: Request, body: dict = Body(...)):
    """`{layout, room, action: join|unjoin|volume|mute, value?}` -> the rooms, as GET."""
    body = body_dict(body)
    entity = _entity(request, _layout(body.get("layout")))
    room = body.get("room")
    if not isinstance(room, str) or not media.ENTITY_RE.match(room):
        raise bad("room must be a media_player entity id")
    svc = _svc()
    m = music.for_service(svc)
    state, _ = await svc.get_state(entity)
    try:
        await m.room_action(entity, state, room, str(body.get("action") or ""), body.get("value"))
        state, _ = await svc.get_state(entity)
        out = await m.rooms(entity, state)
    except media.MediaError as e:
        raise _fail(e)
    await hub.broadcast("media")
    return out


# ---------------------------------------------------------------- Music Assistant connection (Settings > Music)

def _ma_out(c) -> dict:
    s = music.ma_settings(c)
    return {"url": s["url"], "detected_url": music._detected.get("url"), "token_set": bool(s["token"])}


@router.get("/music-assistant")
async def get_ma():
    with db.connect() as c:
        return _ma_out(c)


@router.put("/music-assistant")
async def save_ma(body: dict = Body(...)):
    """`{pin, url?, token?}`: url "" = the address Music Assistant gives Home Assistant; token kept if left out.
    Checked by asking Music Assistant for its players first: 400 if it refuses the token, 424 if unreachable."""
    body = body_dict(body)
    with db.connect() as c:
        require_pin(c, body.get("pin"))
        cur = music.ma_settings(c)
    url = body.get("url", cur["url"])
    token = body.get("token") or cur["token"]
    if not isinstance(url, str) or (url.strip() and not music.ma_url_ok(url.strip())):
        raise bad("url must be like http://homeassistant.local:8095, or empty")
    if not isinstance(token, str) or not token.strip():
        raise bad("token is required: make one in Music Assistant under Settings > Profile")
    url = url.strip().rstrip("/")
    svc = media.service()
    if not url and not music._detected.get("url") and svc is not None:
        with contextlib.suppress(Exception):  # learn MA's address from the images it gives HA
            await music.for_service(svc).browse_any_ma()
    target = url or music._detected.get("url") or ""
    if not target:
        raise HTTPException(status_code=400, detail="Couldn't work out Music Assistant's address: please enter it")
    try:
        await music.MAClient(target, token.strip(), music._ma_connect).run(("players/all", {}))
    except media.MediaError as e:
        raise HTTPException(status_code=400 if e.status == 400 else 424, detail=str(e))
    with db.connect() as c:
        db.set_setting(c, music.SETTINGS_KEY, {"url": url, "token": token.strip()})
        out = _ma_out(c)
    await hub.broadcast("media")
    return out


@router.delete("/music-assistant")
async def delete_ma(body: dict | None = Body(None)):
    with db.connect() as c:
        require_pin(c, (body or {}).get("pin"))
        db.set_setting(c, music.SETTINGS_KEY, {})
        out = _ma_out(c)
    await hub.broadcast("media")
    return out
