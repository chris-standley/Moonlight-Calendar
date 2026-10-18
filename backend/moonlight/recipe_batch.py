"""Scanning a whole cookbook: many page photos sent at once, each read by Claude on its own (a few at a time), with
the recipes found waiting in the recipe box for the family to check and save.

A recipe can run over two pages: Claude says when a recipe at the top of a page carries on from the page before, and
the two parts are joined. So a recipe is only offered once the page after it has been read too (or it's the last).
Reading carries on in the background, and after a restart, until every page is done.

A "cheaper" scan sends the pages as one Anthropic Message Batch instead: half the price, read when Anthropic has room
(usually within the hour, at most a day). Moonlight checks on it every few minutes and takes the results in one go."""
from __future__ import annotations

import asyncio
import json
import logging

from . import db, recipe_import
from .common import hub

log = logging.getLogger("moonlight.recipes")

MAX_PAGES = 200
AT_ONCE = 4          # pages read at the same time
RETRIES = 3          # tries per page when Anthropic is busy or out of reach
RETRY_WAIT = 20      # seconds, doubling
POLL_WAIT = 120      # seconds between checks on a cheaper scan

_tasks: set[asyncio.Task] = set()
_running: set[str] = set()
_gate: asyncio.Semaphore | None = None
_wait = asyncio.sleep  # tests replace this


def create(images: list[str], cheaper: bool = False) -> str:
    bid = db.new_id("rb")
    with db.connect() as c:
        c.execute("INSERT INTO recipe_batches(id, created_at, cheaper) VALUES(?, ?, ?)", (bid, db.now_iso(), int(cheaper)))
        c.executemany("INSERT INTO recipe_batch_pages(batch_id, page, image) VALUES(?, ?, ?)",
                      [(bid, i, iid) for i, iid in enumerate(images)])
    start(bid)
    return bid


def start(bid: str) -> None:
    if bid in _running:
        return
    _running.add(bid)
    task = asyncio.get_running_loop().create_task(_run(bid))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


def resume_all() -> None:
    """At startup: carry on reading scans left unfinished."""
    global _gate
    _gate = asyncio.Semaphore(AT_ONCE)  # one per event loop
    with db.connect() as c:
        # Pages with Anthropic in a cheaper scan stay there; anything else being read when Moonlight stopped starts over.
        c.execute("UPDATE recipe_batch_pages SET status = 'waiting' WHERE status = 'reading' AND batch_id NOT IN "
                  "(SELECT id FROM recipe_batches WHERE anthropic_id IS NOT NULL)")
        ids = [r["batch_id"] for r in c.execute(
            "SELECT DISTINCT batch_id FROM recipe_batch_pages WHERE status IN ('waiting', 'reading')")]
    for bid in ids:
        start(bid)


async def stop_all() -> None:
    for t in list(_tasks):
        t.cancel()
    await asyncio.gather(*_tasks, return_exceptions=True)


async def _run(bid: str) -> None:
    global _gate
    if _gate is None:
        _gate = asyncio.Semaphore(AT_ONCE)
    try:
        with db.connect() as c:
            b = db.row(c, "SELECT cheaper FROM recipe_batches WHERE id = ?", (bid,))
        if b and b["cheaper"]:
            return await _run_cheaper(bid)
        with db.connect() as c:
            pages = [r["page"] for r in c.execute(
                "SELECT page FROM recipe_batch_pages WHERE batch_id = ? AND status = 'waiting' ORDER BY page", (bid,))]
        await asyncio.gather(*(_read(bid, p) for p in pages))
    finally:
        _running.discard(bid)


async def _read(bid: str, page: int) -> None:
    async with _gate:  # type: ignore[union-attr]
        with db.connect() as c:
            r = db.row(c, "SELECT p.status, i.mime, i.data FROM recipe_batch_pages p LEFT JOIN images i ON i.id = p.image "
                          "WHERE p.batch_id = ? AND p.page = ?", (bid, page))
            key = db.get_setting(c, "recipe_reader_key")
            model = db.get_setting(c, "recipe_reader_model") or recipe_import.READER_MODEL
            if not r or r["status"] != "waiting":
                return  # the scan was cancelled
            c.execute("UPDATE recipe_batch_pages SET status = 'reading' WHERE batch_id = ? AND page = ?", (bid, page))
        result, error = None, None
        if not key:
            error = "Reading needs an Anthropic API key in Settings › Recipes."
        elif r["data"] is None:
            error = "The photo of this page went missing."
        else:
            for attempt in range(RETRIES):
                try:
                    result = await recipe_import.read_cookbook_page(key, model, (r["mime"], r["data"]))
                    break
                except recipe_import.Busy as e:
                    error = str(e)
                    if attempt < RETRIES - 1:
                        await _wait(RETRY_WAIT * 2 ** attempt)
                except recipe_import.ImportError_ as e:
                    error = str(e)
                    break
                except Exception:  # never leave a page stuck as "reading"
                    log.exception("Reading a cookbook page failed")
                    error = "Something went wrong reading this page."
                    break
        with db.connect() as c:
            if not db.row(c, "SELECT 1 FROM recipe_batches WHERE id = ?", (bid,)):
                return
            c.execute("UPDATE recipe_batch_pages SET status = ?, result = ?, error = ? WHERE batch_id = ? AND page = ?",
                      ("read" if result is not None else "failed", json.dumps(result) if result is not None else None,
                       None if result is not None else error, bid, page))
            settle(c, bid)
    await hub.broadcast("recipes")


async def _run_cheaper(bid: str) -> None:
    """Send the waiting pages as one Anthropic batch (unless one is out already), then check on it until it's done."""
    with db.connect() as c:
        key = db.get_setting(c, "recipe_reader_key")
        model = db.get_setting(c, "recipe_reader_model") or recipe_import.READER_MODEL
        b = db.row(c, "SELECT anthropic_id FROM recipe_batches WHERE id = ?", (bid,))
        aid = b["anthropic_id"] if b else None
        pages = db.rows(c, "SELECT p.page, i.mime, i.data FROM recipe_batch_pages p LEFT JOIN images i ON i.id = p.image "
                           "WHERE p.batch_id = ? AND p.status = 'waiting' ORDER BY p.page", (bid,))
    if not key:
        return await _fail(bid, [p["page"] for p in pages], "Reading needs an Anthropic API key in Settings › Recipes.")
    if not aid:
        missing = [p["page"] for p in pages if p["data"] is None]
        if missing:
            await _fail(bid, missing, "The photo of this page went missing.")
        pages = [p for p in pages if p["data"] is not None]
        if not pages:
            return
        error = None
        for attempt in range(RETRIES):
            try:
                aid = await recipe_import.submit_pages(key, model, [(p["page"], (p["mime"], p["data"])) for p in pages])
                break
            except recipe_import.Busy as e:
                error = str(e)
                if attempt < RETRIES - 1:
                    await _wait(RETRY_WAIT * 2 ** attempt)
            except recipe_import.ImportError_ as e:
                error = str(e)
                break
            except Exception:
                log.exception("Sending a cookbook to Anthropic failed")
                error = "Something went wrong sending the pages to Anthropic."
                break
        if not aid:
            return await _fail(bid, [p["page"] for p in pages], error or "")
        with db.connect() as c:
            if not db.row(c, "SELECT 1 FROM recipe_batches WHERE id = ?", (bid,)):
                return await recipe_import.cancel_batch(key, aid)  # cleared while sending
            c.execute("UPDATE recipe_batches SET anthropic_id = ? WHERE id = ?", (aid, bid))
            c.executemany("UPDATE recipe_batch_pages SET status = 'reading' WHERE batch_id = ? AND page = ?",
                          [(bid, p["page"]) for p in pages])
        await hub.broadcast("recipes")
    while True:
        await _wait(POLL_WAIT)
        with db.connect() as c:
            if not db.row(c, "SELECT 1 FROM recipe_batches WHERE id = ?", (bid,)):
                return
        try:
            results = await recipe_import.batch_results(key, aid)
        except recipe_import.Busy:
            continue  # out of reach for now: check again later
        except recipe_import.ImportError_ as e:
            results = {}
            failed = str(e)
        except Exception:
            log.exception("Checking on a cookbook batch failed")
            continue
        else:
            failed = "Anthropic didn't send this page back. Try again."
        if results is None:
            continue
        with db.connect() as c:
            if not db.row(c, "SELECT 1 FROM recipe_batches WHERE id = ?", (bid,)):
                return
            for p in db.rows(c, "SELECT page FROM recipe_batch_pages WHERE batch_id = ? AND status = 'reading'", (bid,)):
                drafts, error = results.get(p["page"], (None, failed))
                c.execute("UPDATE recipe_batch_pages SET status = ?, result = ?, error = ? WHERE batch_id = ? AND page = ?",
                          ("read" if drafts is not None else "failed", json.dumps(drafts) if drafts is not None else None,
                           error, bid, p["page"]))
            c.execute("UPDATE recipe_batches SET anthropic_id = NULL WHERE id = ?", (bid,))
            settle(c, bid)
            more = c.execute("SELECT 1 FROM recipe_batch_pages WHERE batch_id = ? AND status = 'waiting'", (bid,)).fetchone()
        await hub.broadcast("recipes")
        if more:  # failed pages put back while Anthropic was reading the rest
            await _run_cheaper(bid)
        return


async def _fail(bid: str, pages: list[int], error: str) -> None:
    with db.connect() as c:
        c.executemany("UPDATE recipe_batch_pages SET status = 'failed', error = ? WHERE batch_id = ? AND page = ?",
                      [(error, bid, p) for p in pages])
        settle(c, bid)
    await hub.broadcast("recipes")


def settle(c, bid: str) -> None:
    """Turn the pages read so far, in order, into recipes to check. Stops at the first page not read yet; a recipe is
    offered once the page after it is read (it might carry on there) or it's on the last page."""
    pages = db.rows(c, "SELECT page, status, result FROM recipe_batch_pages WHERE batch_id = ? ORDER BY page", (bid,))
    groups: list[dict] = []
    current: dict | None = None
    done_to = -1  # last page of the unbroken run of finished pages
    for p in pages:
        if p["status"] not in ("read", "failed"):
            break
        done_to = p["page"]
        if p["status"] == "failed":
            current = None
            continue
        for j, piece in enumerate(json.loads(p["result"] or "[]")):
            if j == 0 and piece.get("continues") and current is not None:
                _join(current["draft"], piece)
                current["pages"].append(p["page"])
            else:
                current = {"piece": f"{p['page']}.{j}", "pages": [p["page"]], "draft": piece}
                groups.append(current)
    last = pages[-1]["page"] if pages else -1
    for g in groups:
        if g["pages"][-1] < done_to or done_to == last:
            draft = {k: v for k, v in g["draft"].items() if k != "continues"}
            c.execute("INSERT OR IGNORE INTO recipe_drafts(id, batch_id, piece, pages, draft) VALUES(?,?,?,?,?)",
                      (db.new_id("rd"), bid, g["piece"], json.dumps(g["pages"]), json.dumps(draft)))


def _join(into: dict, more: dict) -> None:
    for k in ("ingredients", "steps", "tags"):
        into[k] = (into.get(k) or []) + [x for x in more.get(k) or [] if k != "tags" or x not in (into.get(k) or [])]
    for k in ("title", "description", "servings", "prep_minutes", "cook_minutes"):
        if not into.get(k) and more.get(k):
            into[k] = more[k]
    into["notes"] = "\n\n".join(n for n in (into.get("notes"), more.get("notes")) if n)


def finished(c, bid: str) -> bool:
    """Every page read (none left failed) and every recipe found saved or put aside: the scan can go."""
    left = c.execute("SELECT (SELECT COUNT(*) FROM recipe_batch_pages WHERE batch_id = ? AND status != 'read')"
                     " + (SELECT COUNT(*) FROM recipe_drafts WHERE batch_id = ? AND status = 'ready')", (bid, bid)).fetchone()[0]
    return left == 0


def remove(c, bid: str) -> None:
    b = db.row(c, "SELECT anthropic_id FROM recipe_batches WHERE id = ?", (bid,))
    key = db.get_setting(c, "recipe_reader_key")
    if b and b["anthropic_id"] and key:  # stop Anthropic reading (and charging for) pages nobody wants now
        try:
            task = asyncio.get_running_loop().create_task(recipe_import.cancel_batch(key, b["anthropic_id"]))
        except RuntimeError:
            return  # no event loop here: Anthropic ends it within a day anyway
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)
    c.execute("DELETE FROM recipe_drafts WHERE batch_id = ?", (bid,))
    c.execute("DELETE FROM recipe_batch_pages WHERE batch_id = ?", (bid,))
    c.execute("DELETE FROM recipe_batches WHERE id = ?", (bid,))
