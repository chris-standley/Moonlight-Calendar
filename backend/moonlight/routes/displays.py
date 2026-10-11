"""Wall screens: pairing (TV-app style 6-digit code), the list of paired screens, revoking.

Non-screen clients (the Home Assistant integration) pair the same way with `layout: "service"`; they are listed
with the screens so they can be revoked, but approving can't turn a screen into a service or vice versa.
"""
from __future__ import annotations

import secrets
import threading
import time

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import JSONResponse

from .. import auth, db
from ..common import bad, body_dict, choice, hub, not_found, opt_str, req_str, require_pin

router = APIRouter(prefix="/api")

LAYOUTS = ("hallway", "kitchen", "phone")
SECTIONS = ("today", "calendar", "chores", "rewards", "meals", "lists")  # Settings is always shown
SERVICE = "service"  # a non-screen client, e.g. the Home Assistant integration
PAIR_TTL = 600  # seconds a pairing code stays valid
MAX_PENDING = 50
_pairings: dict[str, dict] = {}  # pair_id -> {code, layout, name, expires, token, display}
_lock = threading.Lock()


def _purge(now: float) -> None:
    for pid in [p for p, e in _pairings.items() if e["expires"] < now]:
        del _pairings[pid]


def display_out(d: dict, current_id: str | None = None) -> dict:
    return {
        "id": d["id"], "name": d["name"], "layout": d["layout"], "created_at": d["created_at"],
        "last_seen": d["last_seen"], "revoked": bool(d["revoked"]), "current": d["id"] == current_id,
    }


@router.get("/auth/status")
def auth_status(request: Request):
    a = auth.current(request)
    return {
        "required": a["enabled"],
        "authorised": a["via"] is not None,
        "via": a["via"],
        "display": display_out(a["display"], a["display"]["id"]) if a["display"] else None,
    }


@router.post("/pair/start")
def pair_start(body: dict | None = Body(None)):
    body = body_dict(body)
    layout = body.get("layout") or "kitchen"
    choice(layout, "layout", LAYOUTS + (SERVICE,))
    name = opt_str(body, "name").strip()[:60]  # suggested name, used if the approver leaves it blank
    now = time.time()
    with _lock:
        _purge(now)
        if len(_pairings) >= MAX_PENDING:
            raise HTTPException(status_code=429, detail="Too many screens waiting to pair; try again later")
        codes = {e["code"] for e in _pairings.values()}
        code = f"{secrets.randbelow(1_000_000):06d}"
        while code in codes:
            code = f"{secrets.randbelow(1_000_000):06d}"
        pair_id = secrets.token_urlsafe(24)
        _pairings[pair_id] = {"code": code, "layout": layout, "name": name, "expires": now + PAIR_TTL, "token": None, "display": None}
    return {"pair_id": pair_id, "code": code, "layout": layout, "expires_in": PAIR_TTL}


@router.get("/pair/{pair_id}")
def pair_poll(pair_id: str):
    now = time.time()
    with _lock:
        _purge(now)
        entry = _pairings.get(pair_id)
        if entry is None:
            return {"status": "expired"}
        if entry["token"] is None:
            return {"status": "pending", "expires_in": int(entry["expires"] - now)}
        del _pairings[pair_id]  # the token is handed out exactly once
    token = entry["token"]
    resp = JSONResponse({"status": "approved", "token": token, "display": entry["display"]})
    resp.headers.append("set-cookie", auth.cookie_header(token))
    return resp


@router.get("/displays")
def list_displays(request: Request):
    me = auth.current(request)["display"]
    with db.connect() as c:
        ds = db.rows(c, "SELECT * FROM displays WHERE revoked = 0 ORDER BY created_at")
    return [display_out(d, me["id"] if me else None) for d in ds]


@router.post("/displays/approve")
async def approve(body: dict = Body(...)):
    body = body_dict(body)
    code = str(body.get("code") or "").strip().replace(" ", "")
    if not (len(code) == 6 and code.isdigit()):
        raise HTTPException(status_code=400, detail="Enter the 6-digit code shown on the screen")
    with db.connect() as c:
        require_pin(c, body.get("pin"))
    now = time.time()
    with _lock:
        _purge(now)
        found = next(((pid, e) for pid, e in _pairings.items() if e["code"] == code and e["token"] is None), None)
        if found is None:
            raise not_found("No screen is waiting with that code (codes expire after 10 minutes)")
        pid, entry = found
        if entry["layout"] == SERVICE:
            layout = SERVICE  # a service has no screen layout; ignore what the approver picked
        else:
            layout = body.get("layout") or entry["layout"]
            choice(layout, "layout", LAYOUTS)
        name = (opt_str(body, "name").strip()[:60] or entry.get("name")
                or ("Service" if layout == SERVICE else f"{layout.capitalize()} screen"))
        token = auth.new_token()
        d = {"id": db.new_id("ds"), "name": name, "layout": layout, "token_hash": auth.hash_token(token),
             "created_at": db.now_iso(), "last_seen": None, "revoked": 0}
        with db.connect() as c:
            c.execute(
                "INSERT INTO displays(id, name, layout, token_hash, created_at, last_seen, revoked) "
                "VALUES(:id, :name, :layout, :token_hash, :created_at, :last_seen, :revoked)", d)
        entry["token"] = token
        entry["display"] = display_out(d, d["id"])
        entry["expires"] = now + 120  # the waiting screen polls every few seconds
    await hub.broadcast("displays")
    return display_out(d)


@router.patch("/displays/{display_id}")
async def rename(display_id: str, body: dict = Body(...)):
    """Rename a paired screen (or connection): `{name, pin}`."""
    body = body_dict(body)
    name = req_str(body, "name").strip()[:60]
    if not name:
        raise bad("name is required")
    with db.connect() as c:
        require_pin(c, body.get("pin"))
        d = db.row(c, "SELECT * FROM displays WHERE id = ? AND revoked = 0", (display_id,))
        if not d:
            raise not_found("Screen not found")
        c.execute("UPDATE displays SET name = ? WHERE id = ?", (name, display_id))
        d["name"] = name
    await hub.broadcast("displays")
    return display_out(d)


def apply_settings(c, body: dict) -> None:
    """PATCH /api/settings `screens`: {layout: {start?, sections?}}; layouts not sent are kept."""
    if "screens" not in body:
        return
    val = body["screens"]
    if not isinstance(val, dict):
        raise bad("screens must be an object like {\"kitchen\": {\"start\": \"today\"}}")
    cur = {k: dict(v) for k, v in db.get_setting(c, "screens", db.DEFAULT_SETTINGS["screens"]).items()}
    for layout, conf in val.items():
        if layout not in LAYOUTS or not isinstance(conf, dict):
            raise bad("screens keys are hallway, kitchen, phone, each an object")
        s = {**db.DEFAULT_SETTINGS["screens"][layout], **cur.get(layout, {})}
        if "sections" in conf:
            secs = conf["sections"]
            if not isinstance(secs, list) or not secs or any(x not in SECTIONS for x in secs):
                raise bad(f"screens.{layout}.sections must be a non-empty list of " + ", ".join(SECTIONS))
            s["sections"] = [x for x in SECTIONS if x in secs]
        if "start" in conf:
            s["start"] = choice(conf["start"], f"screens.{layout}.start", SECTIONS)
        if s["start"] not in s["sections"]:
            if "start" in conf:
                raise bad(f"screens.{layout}.start must be one of its sections")
            s["start"] = s["sections"][0]
        cur[layout] = s
    db.set_setting(c, "screens", cur)


@router.delete("/displays/{display_id}")
async def revoke(display_id: str, body: dict | None = Body(None)):
    body = body_dict(body)
    with db.connect() as c:
        require_pin(c, body.get("pin"))
        if not db.row(c, "SELECT id FROM displays WHERE id = ? AND revoked = 0", (display_id,)):
            raise not_found("Screen not found")
        c.execute("UPDATE displays SET revoked = 1 WHERE id = ?", (display_id,))
    auth.forget_seen(display_id)
    await hub.broadcast("displays")
    return {"ok": True}
