"""FastAPI app: JSON API under /api, WebSocket at /api/ws, SPA everywhere else."""
from __future__ import annotations

import logging
import os
from datetime import date
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__, auth, caldav_sync, db
from .common import hub, log
from .routes import accounts, calendar, chores, displays, lists, meals, photos
from .routes import summary as summary_routes
from .auth import AuthMiddleware
from .seed import default_seed_path, seed_file

BACKEND_DIR = Path(__file__).resolve().parent.parent

PLACEHOLDER = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Moonlight</title>
<style>body{font-family:system-ui,sans-serif;background:#0f1424;color:#e8ecf7;display:grid;place-items:center;
min-height:100vh;margin:0}main{max-width:32rem;padding:1rem}code{background:#1d2540;padding:.1rem .3rem;border-radius:4px}
a{color:#9bb7ff}</style></head>
<body><main><h1>Moonlight is running</h1>
<p>The API is up at <a href="api/people"><code>/api</code></a>, but the frontend has not been built.
Build it into <code>frontend/dist</code> (or set <code>MOONLIGHT_STATIC</code>) and restart.</p></main></body></html>
"""


def _env_flag(name: str, default: str) -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


def create_app(
    db_path: str | None = None,
    demo: bool | None = None,
    seed_path: str | Path | None = None,
    static_dir: str | Path | None = None,
    today: date | None = None,
    data_dir: str | Path | None = None,
    auth_enabled: bool | None = None,
    ingress_ips: set[str] | None = None,
    sync: bool = False,
) -> FastAPI:
    """`sync=True` starts the background calendar sync loop (off by default so tests stay offline)."""
    db.configure(db_path or os.environ.get("MOONLIGHT_DB", "./moonlight.db"))
    db.init_db()
    # Uploaded photos live in <data>/photos; default: next to the database (/data in the add-on).
    photos.configure(data_dir or os.environ.get("MOONLIGHT_DATA") or os.path.dirname(os.path.abspath(db.db_path())))
    if auth_enabled is None:
        auth_enabled = auth.auth_enabled_from_env()
    if demo is None:
        demo = _env_flag("MOONLIGHT_DEMO", "1")
    if demo and db.is_empty():
        path = Path(seed_path or os.environ.get("MOONLIGHT_SEED") or default_seed_path())
        if path.exists():
            seed_file(path, today)
            log.info("Seeded demo data from %s", path)
        else:
            log.warning("MOONLIGHT_DEMO set but seed file %s not found", path)

    app = FastAPI(title="Moonlight", version=__version__)
    # Paired screens / HA ingress only (see auth.py). Added before CORS so 401s still carry CORS headers.
    app.add_middleware(AuthMiddleware, enabled=auth_enabled, ingress_ips=ingress_ips or auth.ingress_ips_from_env())
    log.info("Screen pairing %s", "required on the LAN port" if auth_enabled else "off (MOONLIGHT_AUTH)")
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request, exc: RequestValidationError):
        msgs = []
        for e in exc.errors():
            loc = ".".join(str(x) for x in e.get("loc", ()) if x not in ("body", "query", "path"))
            msgs.append(f"{loc}: {e.get('msg')}" if loc else str(e.get("msg")))
        return JSONResponse({"detail": "; ".join(msgs) or "Invalid request"}, status_code=400)

    for module in (calendar, chores, lists, meals, displays, photos, accounts):
        app.include_router(module.router)
    app.include_router(summary_routes.router)

    if sync:
        async def start_sync():
            caldav_sync.manager = caldav_sync.SyncManager()
            caldav_sync.manager.start()

        async def stop_sync():
            if caldav_sync.manager:
                await caldav_sync.manager.stop()
                caldav_sync.manager = None

        app.router.on_startup.append(start_sync)
        app.router.on_shutdown.append(stop_sync)

    @app.get("/api/health")
    def health():
        return {"ok": True, "version": __version__}

    @app.websocket("/api/ws")
    async def ws_endpoint(ws: WebSocket):
        await ws.accept()
        hub.sockets.add(ws)
        try:
            await ws.send_json({"type": "hello", "version": __version__})
            while True:
                msg = await ws.receive_text()
                if msg == "ping":
                    await ws.send_json({"type": "pong"})
        except WebSocketDisconnect:
            pass
        finally:
            hub.sockets.discard(ws)

    # ------------------------------------------------------------ static / SPA
    static = Path(static_dir or os.environ.get("MOONLIGHT_STATIC") or BACKEND_DIR.parent / "frontend" / "dist")
    static = static.resolve()
    index = static / "index.html"
    if (static / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=static / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        if full_path == "api" or full_path.startswith("api/"):
            return JSONResponse({"detail": "Not found"}, status_code=404)
        if not index.is_file():
            return HTMLResponse(PLACEHOLDER)
        if full_path:
            # The build uses relative asset URLs, so /display/kitchen asks for /display/assets/...
            if "assets/" in full_path:
                full_path = "assets/" + full_path.split("assets/", 1)[1]
            candidate = (static / full_path).resolve()
            if candidate.is_file() and candidate.is_relative_to(static):
                return FileResponse(candidate)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})

    return app


_app: FastAPI | None = None


def __getattr__(name: str):
    """`moonlight.main:app` is built lazily so importing this module (e.g. in tests) has no side effects."""
    global _app
    if name == "app":
        if _app is None:
            logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
            _app = create_app(sync=_env_flag("MOONLIGHT_SYNC", "1"))
        return _app
    raise AttributeError(name)
