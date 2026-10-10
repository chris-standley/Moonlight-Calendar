"""Lists and list items."""
from __future__ import annotations

from fastapi import APIRouter, Body

from .. import db
from ..common import (
    as_int, bad, body_dict, choice, hub, next_sort, not_found, opt_date, opt_str,
    person_exists, req_str,
)

router = APIRouter(prefix="/api")

KINDS = ("grocery", "todo")


def item_out(r: dict) -> dict:
    return {
        "id": r["id"], "list_id": r["list_id"], "title": r["title"], "done": bool(r["done"]),
        "person_id": r["person_id"], "due": r["due"], "created_at": r["created_at"], "sort": r["sort"],
    }


LIST_SQL = (
    "SELECT l.*, "
    "(SELECT COUNT(*) FROM items i WHERE i.list_id = l.id AND i.done = 0) AS open_count, "
    "(SELECT COUNT(*) FROM items i WHERE i.list_id = l.id AND i.done = 1) AS done_count "
    "FROM lists l"
)


def _list_or_404(c, list_id: str) -> dict:
    r = db.row(c, LIST_SQL + " WHERE l.id = ?", (list_id,))
    if not r:
        raise not_found("List not found")
    return r


def insert_item(c, list_id: str, title: str, person_id: str | None = None, due: str | None = None,
                done: bool = False, created_at: str | None = None, done_at: str | None = None) -> dict:
    ts = created_at or db.now_iso()
    r = {
        "id": db.new_id("i"), "list_id": list_id, "title": title, "done": int(done),
        "person_id": person_id, "due": due, "created_at": ts,
        "done_at": (done_at or ts) if done else None,
        "sort": next_sort(c, "items", "list_id = ?", (list_id,)),
    }
    c.execute("INSERT INTO items(id, list_id, title, done, person_id, due, created_at, done_at, sort) "
              "VALUES(:id, :list_id, :title, :done, :person_id, :due, :created_at, :done_at, :sort)", r)
    return item_out(r)


@router.get("/lists")
def get_lists():
    with db.connect() as c:
        return db.rows(c, LIST_SQL + " ORDER BY l.sort, l.name")


@router.post("/lists")
async def create_list(body: dict = Body(...)):
    body = body_dict(body)
    with db.connect() as c:
        lid = db.new_id("l")
        c.execute("INSERT INTO lists(id, name, emoji, color, kind, sort) VALUES(?,?,?,?,?,?)",
                  (lid, req_str(body, "name"), opt_str(body, "emoji"), opt_str(body, "color"),
                   choice(body.get("kind", "todo"), "kind", KINDS), next_sort(c, "lists")))
        out = _list_or_404(c, lid)
    await hub.broadcast("lists")
    return out


@router.delete("/lists/{list_id}")
async def delete_list(list_id: str):
    with db.connect() as c:
        if c.execute("DELETE FROM lists WHERE id = ?", (list_id,)).rowcount == 0:
            raise not_found("List not found")
        c.execute("DELETE FROM items WHERE list_id = ?", (list_id,))
    await hub.broadcast("lists")
    return {"ok": True}


@router.get("/lists/{list_id}/items")
def get_items(list_id: str):
    with db.connect() as c:
        _list_or_404(c, list_id)
        rs = db.rows(c, "SELECT * FROM items WHERE list_id = ? "
                        "ORDER BY done, CASE WHEN done = 0 THEN sort END, done_at DESC, sort DESC",
                     (list_id,))
    return [item_out(r) for r in rs]


def _person_or_none(c, pid) -> str | None:
    if pid in (None, ""):
        return None
    if not isinstance(pid, str) or not person_exists(c, pid):
        raise bad("person_id must be an existing person or null")
    return pid


@router.post("/lists/{list_id}/items")
async def add_item(list_id: str, body: dict = Body(...)):
    body = body_dict(body)
    with db.connect() as c:
        _list_or_404(c, list_id)
        out = insert_item(c, list_id, req_str(body, "title"), _person_or_none(c, body.get("person_id")),
                          opt_date(body.get("due"), "due"))
    await hub.broadcast("lists")
    return out


@router.patch("/items/{item_id}")
async def update_item(item_id: str, body: dict = Body(...)):
    body = body_dict(body)
    with db.connect() as c:
        r = db.row(c, "SELECT * FROM items WHERE id = ?", (item_id,))
        if not r:
            raise not_found("Item not found")
        if "title" in body:
            r["title"] = req_str(body, "title")
        if "person_id" in body:
            r["person_id"] = _person_or_none(c, body["person_id"])
        if "due" in body:
            r["due"] = opt_date(body["due"], "due")
        if "sort" in body:
            r["sort"] = as_int(body["sort"], "sort")
        if "done" in body:
            done = bool(body["done"])
            if done and not r["done"]:
                r["done_at"] = db.now_precise()
            elif not done and r["done"]:
                r["done_at"] = None
                r["sort"] = next_sort(c, "items", "list_id = ?", (r["list_id"],))  # back to the bottom
            r["done"] = int(done)
        c.execute("UPDATE items SET title=:title, done=:done, person_id=:person_id, due=:due, "
                  "done_at=:done_at, sort=:sort WHERE id=:id", r)
    await hub.broadcast("lists")
    return item_out(r)


@router.delete("/items/{item_id}")
async def delete_item(item_id: str):
    with db.connect() as c:
        if c.execute("DELETE FROM items WHERE id = ?", (item_id,)).rowcount == 0:
            raise not_found("Item not found")
    await hub.broadcast("lists")
    return {"ok": True}


@router.post("/lists/{list_id}/clear-done")
async def clear_done(list_id: str):
    with db.connect() as c:
        _list_or_404(c, list_id)
        n = c.execute("DELETE FROM items WHERE list_id = ? AND done = 1", (list_id,)).rowcount
    await hub.broadcast("lists")
    return {"ok": True, "removed": n}
