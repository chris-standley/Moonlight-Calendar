"""Notifications and timers on the screens (see alerts.py): Home Assistant puts them up and clears them, screens show
them and can dismiss them."""
from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException, Query, Request

from .. import alerts, auth, db
from ..common import body_dict, not_found

router = APIRouter(prefix="/api")


@router.get("/alerts")
def list_alerts(request: Request):
    """The ones this device shows, and the server's clock (epoch ms) to count down against."""
    return {"server_time": alerts.now_ms(), "alerts": alerts.for_device(auth.current(request)["display"])}


@router.post("/alerts")
async def create(body: dict = Body(...)):
    """`{kind?, style?, screens?, id?, ...}`; see API.md. The same `id` again replaces that one."""
    with db.connect() as c:
        return await alerts.add(c, body_dict(body))


@router.post("/alerts/{alert_id}/dismiss")
async def dismiss(alert_id: str, request: Request):
    """Tapped away on a screen: gone from every screen, and Home Assistant hears who dismissed it."""
    a = alerts.get(alert_id)
    if a is None:
        raise not_found("Already gone")
    if not a["dismissible"]:
        raise HTTPException(status_code=409, detail="This one can only be cleared from Home Assistant")
    display = auth.current(request)["display"]
    await alerts.remove([alert_id], "dismissed", display["name"] if display else None)
    return {"ok": True}


@router.delete("/alerts/{alert_id}")
async def clear(alert_id: str):
    """Cleared by Home Assistant (or whoever put it up)."""
    if not await alerts.remove([alert_id]):
        raise not_found("No notification or timer with that id")
    return {"ok": True}


@router.delete("/alerts")
async def clear_all(screens: list[str] | None = Query(None)):
    """Clear every one, or only those shown on `?screens=Kitchen&screens=large`."""
    with db.connect() as c:
        ids = alerts.matching(screens, c)
    return {"cleared": await alerts.remove(ids)}
