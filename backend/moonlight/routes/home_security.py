"""Security: alarm, Alarmo's sensors and the cameras from Home Assistant (see home_security.py)."""
from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import Response, StreamingResponse

from .. import db, home_security, media
from ..common import bad, body_dict, require_pin

router = APIRouter(prefix="/api/security")


def _svc() -> home_security.SecurityService:
    svc = home_security.service()
    if svc is None:
        raise HTTPException(status_code=409, detail="Moonlight isn't connected to Home Assistant")
    return svc


def _fail(e: media.MediaError) -> HTTPException:
    return HTTPException(status_code=e.status, detail=str(e))


@router.get("")
async def overview():
    svc = home_security.service()
    if svc is None:
        return {"configured": False, "reachable": False, "error": "Moonlight isn't connected to Home Assistant",
                "sensors_source": "none", "alarm": None, "sensors": [], "cameras": [], "alerts": []}
    try:
        return await home_security.overview(svc)
    except media.MediaError as e:
        return {"configured": True, "reachable": False, "error": str(e), "sensors_source": "none", "alarm": None,
                "sensors": [], "cameras": [], "alerts": []}


@router.get("/alerts")
async def alerts():
    """Shown cameras with a person there right now (or a test): what the screens pop up in a corner."""
    svc = home_security.service()
    if svc is None:
        return []
    try:
        return await home_security.alerts(svc)
    except media.MediaError:
        return []


@router.get("/options")
async def options(refresh: bool = False):
    """For Settings > Security: the alarm panels, every camera with its person sensor, and the person sensors."""
    svc = _svc()
    try:
        found = await svc.discover(force=refresh)
    except media.MediaError as e:
        raise _fail(e)
    with db.connect() as c:
        eff = home_security.effective(found, home_security.saved(c))
        popup = home_security.popup_setting(c)
    return {"alarm_entity": eff["alarm_entity"], "panels": found["panels"], "cameras": eff["cameras"],
            "person_sensors": [{"entity_id": p["entity_id"], "name": p["name"]} for p in found["person_sensors"]],
            "sensors_source": svc.sensors_source, "sensor_count": len(eff["sensors"]), "popup": popup}


def _camera(entity: str, svc: home_security.SecurityService) -> dict:
    """Only a camera the household shows can be asked for: screens can't reach any other entity this way."""
    found = svc.found
    if found is None or not home_security.CAMERA_RE.match(entity):
        raise HTTPException(status_code=404, detail="No such camera")
    with db.connect() as c:
        eff = home_security.effective(found, home_security.saved(c))
    cam = next((c for c in eff["cameras"] if c["entity_id"] == entity and c["show"]), None)
    if cam is None:
        raise HTTPException(status_code=404, detail="No such camera")
    return {**cam, "eff": eff}


def _width(width: int | None) -> int | None:
    return None if width is None else max(160, min(1920, int(width)))


@router.get("/cameras/{entity}/snapshot")
async def snapshot(entity: str, width: int | None = None):
    svc = _svc()
    if svc.found is None:
        await svc.config()
    _camera(entity, svc)
    got = await svc.frame(entity, _width(width))
    if got is None:
        return Response(status_code=502)
    data, ctype = got
    return Response(data, media_type=ctype, headers={"Cache-Control": "no-store"})


@router.get("/cameras/{entity}/live")
async def live(entity: str, width: int | None = None):
    """MJPEG made from Home Assistant's snapshots (about two a second), for an <img>."""
    svc = _svc()
    if svc.found is None:
        await svc.config()
    _camera(entity, svc)
    if svc.streams >= home_security.MAX_STREAMS:
        raise HTTPException(status_code=503, detail="Too many live cameras open")
    return StreamingResponse(svc.mjpeg(entity, _width(width)), media_type="multipart/x-mixed-replace; boundary=frame",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


@router.get("/cameras/{entity}/hls/{path:path}")
async def hls(entity: str, path: str, request: Request):
    """Home Assistant's HLS video of the camera (playlists and segments), passed through without its token."""
    svc = _svc()
    if svc.found is None:
        await svc.config()
    cam = _camera(entity, svc)
    if not cam.get("stream") or not home_security.HLS_PATH_RE.match(path) or ".." in path:
        raise HTTPException(status_code=404, detail="No video")
    status, body, ctype = await svc.hls(cam["stream_entity"], path, request.url.query)
    if status != 200:
        return Response(status_code=404 if status == 404 else 502)
    return Response(body, media_type=ctype, headers={"Cache-Control": "no-cache"})


@router.post("/test-alert")
async def test_alert(body: dict = Body(...)):
    """Pop up a camera on the screens for a few seconds, as if someone were there (Settings > Security)."""
    body = body_dict(body)
    svc = _svc()
    with db.connect() as c:
        require_pin(c, body.get("pin"))
    camera = body.get("camera")
    if not isinstance(camera, str):
        raise bad("camera is required")
    if svc.found is None:
        await svc.config()
    svc.test_alert(camera, _camera(camera, svc)["eff"])
    return {"ok": True, "seconds": home_security.TEST_ALERT_SECONDS}
