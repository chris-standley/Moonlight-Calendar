"""Calendar accounts (iCloud / CalDAV), their calendars and sync status. See caldav_sync.py."""
from __future__ import annotations

import asyncio
import json
from urllib.parse import urlparse

from fastapi import APIRouter, Body, HTTPException

from .. import caldav_sync, db
from ..common import bad, body_dict, hub, not_found, opt_str, person_exists, req_str, require_pin

router = APIRouter(prefix="/api")

KINDS = ("icloud", "caldav")


def account_out(c, r: dict) -> dict:
    """Never includes the password."""
    n = c.execute("SELECT COUNT(*) FROM calendars WHERE account_id = ?", (r["id"],)).fetchone()[0]
    return {
        "id": r["id"], "kind": r["kind"], "label": r["label"], "username": r["username"],
        "server_url": r["server_url"], "status": r["status"], "last_error": r["last_error"],
        "last_sync": r["last_sync"], "calendar_count": n,
    }


def calendar_out(r: dict) -> dict:
    return {
        "id": r["id"], "account_id": r["account_id"], "name": r["name"], "color": r["color"],
        "person_ids": json.loads(r["person_ids"]), "visible": bool(r["visible"]), "read_only": bool(r["read_only"]),
    }


async def _verify(server_url: str, username: str, password: str, kind: str):
    try:
        return await asyncio.to_thread(caldav_sync.discover, server_url, username, password)
    except caldav_sync.AuthFailed:
        if kind == "icloud":
            raise bad("iCloud didn't accept that Apple ID and app-specific password. Check both and try again "
                      "(use an app-specific password, not your normal Apple ID password).")
        raise bad("The server didn't accept that username and password.")
    except caldav_sync.SyncError as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/accounts")
def list_accounts():
    with db.connect() as c:
        return [account_out(c, r) for r in db.rows(c, "SELECT * FROM accounts ORDER BY created_at, id")]


@router.post("/accounts")
async def create_account(body: dict = Body(...)):
    body = body_dict(body)
    kind = body.get("kind", "icloud")
    if kind not in KINDS:
        raise bad("kind must be icloud or caldav")
    username = req_str(body, "username")
    password = req_str(body, "password", allow_empty=False)
    if kind == "icloud":
        server_url = caldav_sync.ICLOUD_URL
    else:
        server_url = req_str(body, "server_url")
        if not server_url.startswith(("http://", "https://")):
            raise bad("server_url must start with http:// or https://")
    host = urlparse(server_url).hostname or server_url
    label = opt_str(body, "label").strip() or (username if kind == "icloud" else f"{username} @ {host}")
    with db.connect() as c:
        require_pin(c, body.get("pin"))
        if db.row(c, "SELECT id FROM accounts WHERE kind = ? AND username = ? AND server_url = ?",
                  (kind, username, server_url)):
            raise bad("That account is already connected")
    home, found = await _verify(server_url, username, password, kind)
    with db.connect() as c:
        aid = db.new_id("acct")
        c.execute("INSERT INTO accounts(id, kind, label, username, password, server_url, home_url, status, created_at) "
                  "VALUES(?,?,?,?,?,?,?, 'ok', ?)", (aid, kind, label, username, password, server_url, home, db.now_iso()))
        caldav_sync.store_calendars(c, aid, found)
        out = account_out(c, db.row(c, "SELECT * FROM accounts WHERE id = ?", (aid,)))
    caldav_sync.poke(aid)
    await hub.broadcast("accounts")
    return out


@router.patch("/accounts/{account_id}")
async def update_account(account_id: str, body: dict = Body(...)):
    """Rename, or reconnect with new credentials (verified before they are saved)."""
    body = body_dict(body)
    with db.connect() as c:
        require_pin(c, body.get("pin"))
        r = db.row(c, "SELECT * FROM accounts WHERE id = ?", (account_id,))
        if not r:
            raise not_found("Account not found")
    if "password" in body or "username" in body:
        username = req_str(body, "username") if "username" in body else r["username"]
        password = req_str(body, "password") if "password" in body else r["password"]
        home, found = await _verify(r["server_url"], username, password, r["kind"])
        with db.connect() as c:
            c.execute("UPDATE accounts SET username=?, password=?, home_url=?, status='ok', last_error=NULL "
                      "WHERE id=?", (username, password, home, account_id))
            caldav_sync.store_calendars(c, account_id, found)
        caldav_sync.poke(account_id)
    with db.connect() as c:
        if "label" in body:
            c.execute("UPDATE accounts SET label = ? WHERE id = ?", (req_str(body, "label"), account_id))
        out = account_out(c, db.row(c, "SELECT * FROM accounts WHERE id = ?", (account_id,)))
    await hub.broadcast("accounts")
    return out


@router.delete("/accounts/{account_id}")
async def delete_account(account_id: str, body: dict | None = Body(None)):
    """Disconnect: forget the credentials and the cached events (nothing is deleted in iCloud)."""
    body = body_dict(body)
    with db.connect() as c:
        require_pin(c, body.get("pin"))
        if not db.row(c, "SELECT id FROM accounts WHERE id = ?", (account_id,)):
            raise not_found("Account not found")
        c.execute("DELETE FROM events WHERE calendar_id IN (SELECT id FROM calendars WHERE account_id = ?)",
                  (account_id,))
        c.execute("DELETE FROM calendars WHERE account_id = ?", (account_id,))
        c.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
    await hub.broadcast("accounts", "events")
    return {"ok": True}


@router.post("/accounts/{account_id}/sync")
async def sync_account(account_id: str):
    with db.connect() as c:
        if not db.row(c, "SELECT id FROM accounts WHERE id = ?", (account_id,)):
            raise not_found("Account not found")
    await caldav_sync.sync_now(account_id)
    with db.connect() as c:
        return account_out(c, db.row(c, "SELECT * FROM accounts WHERE id = ?", (account_id,)))


@router.get("/calendars")
def list_calendars():
    with db.connect() as c:
        return [calendar_out(r) for r in db.rows(
            c, "SELECT c.* FROM calendars c JOIN accounts a ON a.id = c.account_id ORDER BY a.created_at, a.id, c.name")]


@router.patch("/calendars/{calendar_id}")
async def update_calendar(calendar_id: str, body: dict = Body(...)):
    body = body_dict(body)
    with db.connect() as c:
        r = db.row(c, "SELECT * FROM calendars WHERE id = ?", (calendar_id,))
        if not r:
            raise not_found("Calendar not found")
        if "person_ids" in body:
            ids = body["person_ids"]
            if not isinstance(ids, list) or not all(isinstance(i, str) and person_exists(c, i) for i in ids):
                raise bad("person_ids must be a list of person ids")
            r["person_ids"] = json.dumps(list(dict.fromkeys(ids)))
        if "visible" in body:
            if not isinstance(body["visible"], bool):
                raise bad("visible must be a boolean")
            r["visible"] = int(body["visible"])
        if "color" in body:
            color = req_str(body, "color")
            if not (len(color) == 7 and color.startswith("#")):
                raise bad("color must look like #RRGGBB")
            r["color"] = color
        c.execute("UPDATE calendars SET person_ids = ?, visible = ?, color = ? WHERE id = ?",
                  (r["person_ids"], r["visible"], r["color"], calendar_id))
    await hub.broadcast("accounts", "events")
    return calendar_out(r)


@router.get("/sync/status")
def sync_status():
    with db.connect() as c:
        accts = db.rows(c, "SELECT id, label, kind, status, last_sync, last_error FROM accounts ORDER BY created_at")
    m = caldav_sync.manager
    return {
        "running": bool(m and m.running),
        "interval_seconds": int(m.interval if m else caldav_sync.SyncManager().interval),
        "needs_reconnect": any(a["status"] == "auth_failed" for a in accts),
        "accounts": accts,
    }
