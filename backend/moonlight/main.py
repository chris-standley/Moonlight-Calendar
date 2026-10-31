"""FastAPI app: JSON API under /api, WebSocket at /api/ws, SPA everywhere else."""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import date
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__, alerts, auth, caldav_sync, db, energy, ha_discovery, home_security, media, recipe_batch, security, tapestry
from . import immich as immich_source
from .common import hub, log
from .routes import accounts, alerts as alert_routes, calendar, chores, countdowns, displays, ha_login, immich, lists, meals, nursery, recipes
from .routes import energy as energy_routes
from .routes import home_security as security_routes
from .routes import media as media_routes
from .routes import voice as voice_routes
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
    auth_enabled: bool | None = None,
    ingress_ips: set[str] | None = None,
    sync: bool = False,
) -> FastAPI:
    """`sync=True` starts the background calendar sync loop (off by default so tests stay offline)."""
    db.configure(db_path or os.environ.get("MOONLIGHT_DB", "./moonlight.db"))
    db.init_db()
    immich_source.cache.reset()  # the cached photo list belongs to the previous database's settings
    tapestry.forget_session()
    alerts.load()
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
    security.pin_failures.reset()
    security.pair_starts.reset()
    https = security.https_enabled()
    # Paired screens / HA ingress only (see auth.py). Added before CORS so 401s still carry CORS headers.
    app.add_middleware(AuthMiddleware, enabled=auth_enabled, ingress_ips=ingress_ips or auth.ingress_ips_from_env(),
                       lan_only_http=https)
    log.info("Screen pairing %s", "required on the LAN port" if auth_enabled else "off on the LAN port (MOONLIGHT_AUTH)")
    if https:
        log.info("HTTPS on: pairing always required there; plain http answers the home network only")
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request, exc: RequestValidationError):
        msgs = []
        for e in exc.errors():
            loc = ".".join(str(x) for x in e.get("loc", ()) if x not in ("body", "query", "path"))
            msgs.append(f"{loc}: {e.get('msg')}" if loc else str(e.get("msg")))
        return JSONResponse({"detail": "; ".join(msgs) or "Invalid request"}, status_code=400)

    @app.exception_handler(Exception)
    async def unexpected_error(_request, exc: Exception):
        # A JSON detail, so screens show a message instead of an empty toast (the traceback goes to the log).
        log.error("Unexpected error", exc_info=exc)
        return JSONResponse({"detail": f"Something went wrong ({exc.__class__.__name__}). The add-on log has the "
                                       "details."}, status_code=500)

    for module in (calendar, chores, countdowns, lists, meals, recipes, displays, ha_login, immich, accounts, nursery):
        app.include_router(module.router)
    app.include_router(summary_routes.router)
    app.include_router(media_routes.router)
    app.include_router(security_routes.router)
    app.include_router(energy_routes.router)
    app.include_router(alert_routes.router)
    app.include_router(voice_routes.router)

    # Follow the configured media players over Home Assistant's WebSocket (only when HA is reachable at all).
    async def start_media():
        svc = media.service()
        if svc is not None:
            svc.set_watched(media.watched_entities())
            svc.start()

    async def stop_media():
        svc = media.service()
        if svc is not None:
            await svc.stop()

    app.router.on_startup.append(start_media)
    app.router.on_shutdown.append(stop_media)
    # Follow the alarm, its sensors and the cameras' person sensors the same way.
    app.router.on_startup.append(home_security.start)
    app.router.on_shutdown.append(home_security.stop)
    # And the solar, battery, grid, car and heat pump sensors for Energy.
    app.router.on_startup.append(energy.start)
    app.router.on_shutdown.append(energy.stop)

    # Notifications and timers from Home Assistant: timers reaching zero, shown-for-a-while ones going.
    app.router.on_startup.append(alerts.start)
    app.router.on_shutdown.append(alerts.stop)

    # Inside the add-on: offer the Moonlight integration in Home Assistant (Devices & services > Discovered).
    async def start_discovery():
        if ha_discovery.enabled():
            app.state.discovery = asyncio.get_running_loop().create_task(ha_discovery.announce())

    async def stop_discovery():
        task = getattr(app.state, "discovery", None)
        if task:
            task.cancel()

    app.router.on_startup.append(start_discovery)
    app.router.on_shutdown.append(stop_discovery)

    # Cookbook scans left part-read by a restart carry on.
    async def start_batches():
        recipe_batch.resume_all()

    app.router.on_startup.append(start_batches)
    app.router.on_shutdown.append(recipe_batch.stop_all)

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

        # Nursery updates from Tapestry, when a login is saved (see tapestry.py).
        async def start_tapestry():
            tapestry.syncer = tapestry.Syncer()
            tapestry.syncer.start()

        async def stop_tapestry():
            if tapestry.syncer:
                await tapestry.syncer.stop()
                tapestry.syncer = None

        app.router.on_startup.append(start_tapestry)
        app.router.on_shutdown.append(stop_tapestry)

    @app.get("/api/health")
    async def health():
        # external_url: where the apps go when the home address doesn't answer; ha_login: offer "Sign in with HA".
        return {"ok": True, "version": __version__, "instance": db.instance_id(), "external_url": security.external_url(),
                "ha_login": bool(await ha_login.ha_login_url())}

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
            # httpx logs every request URL at INFO; album art URLs carry Home Assistant's proxy token.
            logging.getLogger("httpx").setLevel(logging.WARNING)
            _app = create_app(sync=_env_flag("MOONLIGHT_SYNC", "1"))
        return _app
    raise AttributeError(name)
