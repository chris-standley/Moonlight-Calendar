"""Calendar accounts (iCloud / CalDAV / published ICS links / Home Assistant calendars), their calendars and
sync status. See caldav_sync.py, ics_feed.py and ha_calendar.py."""
from __future__ import annotations

import asyncio
import json
import re
from urllib.parse import urlparse

from fastapi import APIRouter, Body, HTTPException

from .. import caldav_sync, db, ha_calendar, ics_feed
from ..common import bad, body_dict, hub, not_found, opt_str, person_exists, req_str, require_pin

router = APIRouter(prefix="/api")

KINDS = ("icloud", "caldav", "ics", "ha")
SINGLE = ("ics", "ha")  # kinds holding one read-only calendar named after the account


def account_out(c, r: dict) -> dict:
    """Never includes the password (nor, for an ICS link, the full URL: server_url is masked)."""
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
        "busy_blocks": bool(r["busy_blocks"] if r.get("busy_blocks") is not None else r.get("busy_auto")),
        "busy_blocks_auto": bool(r.get("busy_auto")), "busy_blocks_set": r.get("busy_blocks") is not None,
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


def _feed_url(body: dict) -> str:
    try:
        return ics_feed.normalize_url(req_str(body, "url"))
    except ValueError as e:
        raise bad(str(e))


async def _preview(url: str) -> dict:
    try:
        return await asyncio.to_thread(ics_feed.preview, url)
    except ValueError as e:
        raise bad(str(e))
    except caldav_sync.SyncError as e:
        raise HTTPException(status_code=502, detail=str(e))


def _person_ids(c, body: dict) -> list[str]:
    ids = body.get("person_ids", [])
    if not isinstance(ids, list) or not all(isinstance(i, str) and person_exists(c, i) for i in ids):
        raise bad("person_ids must be a list of person ids")
    return list(dict.fromkeys(ids))


def _color(body: dict, default: str) -> str:
    if body.get("color") in (None, ""):
        return default
    color = req_str(body, "color")
    if not (len(color) == 7 and color.startswith("#")):
        raise bad("color must look like #RRGGBB")
    return color.upper()


@router.post("/accounts/feed-preview")
async def feed_preview(body: dict = Body(...)):
    """Test a calendar link: how many events (inside the kept window) it has. Nothing is saved."""
    p = await _preview(_feed_url(body_dict(body)))
    return {k: p[k] for k in ("event_count", "name", "busy_only", "masked_url")}


async def _create_feed(body: dict) -> dict:
    url = _feed_url(body)
    with db.connect() as c:
        require_pin(c, body.get("pin"))
        person_ids = _person_ids(c, body)
        if db.row(c, "SELECT id FROM accounts WHERE kind = 'ics' AND password = ?", (url,)):
            raise bad("That calendar link is already added")
        first = db.row(c, "SELECT color FROM people WHERE id = ?", (person_ids[0],)) if person_ids else None
    color = _color(body, first["color"].upper() if first else "#8A94A6")
    p = await _preview(url)
    label = opt_str(body, "label").strip() or p["name"] or "Calendar link"
    with db.connect() as c:
        aid = db.new_id("acct")
        c.execute("INSERT INTO accounts(id, kind, label, username, password, server_url, status, created_at) "
                  "VALUES(?, 'ics', ?, '', ?, ?, 'ok', ?)", (aid, label, url, p["masked_url"], db.now_iso()))
        cid = db.new_id("cal")
        c.execute("INSERT INTO calendars(id, account_id, url, name, color, person_ids, visible, read_only, busy_auto) "
                  "VALUES(?,?,?,?,?,?,1,1,?)", (cid, aid, ics_feed.FEED_CALENDAR_URL, label, color,
                                                json.dumps(person_ids), int(p["busy_only"])))
    await asyncio.to_thread(ics_feed.store, cid, p["fetched"])
    with db.connect() as c:
        c.execute("UPDATE accounts SET last_sync = ? WHERE id = ?", (db.now_iso(), aid))
        out = account_out(c, db.row(c, "SELECT * FROM accounts WHERE id = ?", (aid,)))
    caldav_sync.mark_synced(aid)
    await hub.broadcast("accounts", "events")
    return out


async def _ha(fn, *args):
    try:
        return await asyncio.to_thread(fn, *args)
    except ha_calendar.NotConnected as e:
        raise HTTPException(status_code=409, detail=str(e))
    except caldav_sync.SyncError as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/ha/calendars")
async def ha_calendars():
    """Home Assistant's calendar entities that can be added (409 when not connected to HA)."""
    return await _ha(ha_calendar.list_calendars)


async def _create_ha(body: dict) -> dict:
    entity = req_str(body, "entity_id").strip()
    if not re.fullmatch(r"calendar\.[a-z0-9_]+", entity):
        raise bad("entity_id must be a calendar entity like calendar.bins")
    with db.connect() as c:
        require_pin(c, body.get("pin"))
        person_ids = _person_ids(c, body)
        if db.row(c, "SELECT id FROM accounts WHERE kind = 'ha' AND username = ?", (entity,)):
            raise bad("That calendar is already added")
        first = db.row(c, "SELECT color FROM people WHERE id = ?", (person_ids[0],)) if person_ids else None
    color = _color(body, first["color"].upper() if first else "#8A94A6")
    found = {e["entity_id"]: e for e in await _ha(ha_calendar.list_calendars)}
    if entity not in found:
        raise bad("Home Assistant has no calendar called " + entity)
    fetched = await _ha(ha_calendar.fetch, entity)
    label = opt_str(body, "label").strip() or found[entity]["name"]
    with db.connect() as c:
        aid = db.new_id("acct")
        c.execute("INSERT INTO accounts(id, kind, label, username, password, server_url, status, created_at) "
                  "VALUES(?, 'ha', ?, ?, '', ?, 'ok', ?)", (aid, label, entity, entity, db.now_iso()))
        cid = db.new_id("cal")
        c.execute("INSERT INTO calendars(id, account_id, url, name, color, person_ids, visible, read_only, busy_auto) "
                  "VALUES(?,?,?,?,?,?,1,1,0)", (cid, aid, ics_feed.FEED_CALENDAR_URL, label, color,
                                                json.dumps(person_ids)))
    await asyncio.to_thread(ics_feed.store, cid, fetched)
    with db.connect() as c:
        c.execute("UPDATE accounts SET last_sync = ? WHERE id = ?", (db.now_iso(), aid))
        out = account_out(c, db.row(c, "SELECT * FROM accounts WHERE id = ?", (aid,)))
    caldav_sync.mark_synced(aid)
    await hub.broadcast("accounts", "events")
    return out


@router.post("/accounts")
async def create_account(body: dict = Body(...)):
    body = body_dict(body)
    kind = body.get("kind", "icloud")
    if kind not in KINDS:
        raise bad("kind must be icloud, caldav, ics or ha")
    if kind == "ics":
        return await _create_feed(body)
    if kind == "ha":
        return await _create_ha(body)
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
    """Rename, or reconnect with new credentials / a new calendar link (verified before they are saved)."""
    body = body_dict(body)
    with db.connect() as c:
        require_pin(c, body.get("pin"))
        r = db.row(c, "SELECT * FROM accounts WHERE id = ?", (account_id,))
        if not r:
            raise not_found("Account not found")
    if r["kind"] == "ics" and "url" in body:
        url = _feed_url(body)
        p = await _preview(url)
        with db.connect() as c:
            c.execute("UPDATE accounts SET password=?, server_url=?, status='ok', last_error=NULL, last_sync=? "
                      "WHERE id=?", (url, p["masked_url"], db.now_iso(), account_id))
            cal = ics_feed.feed_calendar(c, account_id)
            c.execute("UPDATE calendars SET ctag = NULL WHERE id = ?", (cal["id"],))
        await asyncio.to_thread(ics_feed.store, cal["id"], p["fetched"])
        caldav_sync.mark_synced(account_id)
        await hub.broadcast("events")
    elif r["kind"] not in SINGLE and ("password" in body or "username" in body):
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
            if r["kind"] in SINGLE:  # a link's single calendar carries its name
                c.execute("UPDATE calendars SET name = ? WHERE account_id = ?", (req_str(body, "label"), account_id))
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
async def sync_account(account_id: str, body: dict | None = Body(None)):
    with db.connect() as c:
        if not db.row(c, "SELECT id FROM accounts WHERE id = ?", (account_id,)):
            raise not_found("Account not found")
    await caldav_sync.sync_now(account_id, force=bool(body_dict(body).get("force")))
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
        if "busy_blocks" in body:  # true / false, or null to follow the automatic guess
            if body["busy_blocks"] is not None and not isinstance(body["busy_blocks"], bool):
                raise bad("busy_blocks must be true, false or null")
            r["busy_blocks"] = None if body["busy_blocks"] is None else int(body["busy_blocks"])
        c.execute("UPDATE calendars SET person_ids = ?, visible = ?, color = ?, busy_blocks = ? WHERE id = ?",
                  (r["person_ids"], r["visible"], r["color"], r.get("busy_blocks"), calendar_id))
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
