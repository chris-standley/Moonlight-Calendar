"""Energy: solar, battery, grid, car and heat pump from Home Assistant (see energy.py)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .. import db, energy, media

router = APIRouter(prefix="/api/energy")


@router.get("")
async def overview():
    svc = energy.service()
    if svc is None:
        return energy.not_connected("Moonlight isn't connected to Home Assistant")
    try:
        return await energy.overview(svc)
    except media.MediaError as e:
        return energy.not_connected(str(e)) | {"configured": True}


@router.get("/options")
async def options(refresh: bool = False):
    """For Settings > Energy: what each slot shows (and whether that's automatic), what automatic would pick, and
    Home Assistant's entities by kind to choose from."""
    svc = energy.service()
    if svc is None:
        raise HTTPException(status_code=409, detail="Moonlight isn't connected to Home Assistant")
    try:
        auto = await svc.find(force=refresh)
    except media.MediaError as e:
        raise HTTPException(status_code=e.status, detail=str(e))
    with db.connect() as c:
        eff = energy.effective(auto, svc.auto_flags, energy.saved(c))
    return {"slots": {slot: {"kind": kind, "group": group, "entities": eff["entities"][slot], "auto": eff["auto"][slot],
                             "suggested": auto.get(slot) or []}
                      for slot, (kind, group) in energy.SLOTS.items()},
            "battery_invert": eff["battery_invert"], "grid_invert": eff["grid_invert"],
            "hide": eff["hide"],
            "candidates": energy.candidates(svc.all)}
