import asyncio
import logging
import os
import ssl

import uvicorn

log = logging.getLogger("moonlight.server")
CERT_CHECK_SECONDS = 3600  # Let's Encrypt renews well before expiry; pick the new files up within the hour


def _config(port: int, **kw) -> uvicorn.Config:
    return uvicorn.Config(
        "moonlight.main:app",
        host=os.environ.get("MOONLIGHT_HOST", "0.0.0.0"),
        port=port,
        log_level=os.environ.get("MOONLIGHT_LOG_LEVEL", "info"),
        **kw,
    )


async def _reload_certificate(server: uvicorn.Server, cert: str, key: str) -> None:
    """Load renewed certificate files into the running HTTPS listener (new connections get them)."""
    def stamp():
        return tuple(os.stat(p).st_mtime for p in (cert, key))

    seen = stamp()
    while True:
        await asyncio.sleep(CERT_CHECK_SECONDS)
        try:
            now = stamp()
            if now != seen and server.config.ssl is not None:
                server.config.ssl.load_cert_chain(cert, key)
                seen = now
                log.info("Loaded the renewed certificate %s", cert)
        except (OSError, ssl.SSLError) as e:
            log.warning("Could not load the renewed certificate (keeping the old one): %s", e)


async def _serve_both(cert: str, key: str) -> None:
    plain = uvicorn.Server(_config(int(os.environ.get("MOONLIGHT_PORT", "8091"))))
    # The app object is shared, so only the first server runs its startup/shutdown (sync loops, media).
    secure = uvicorn.Server(_config(int(os.environ.get("MOONLIGHT_HTTPS_PORT", "8443")), lifespan="off",
                                    ssl_certfile=cert, ssl_keyfile=key))
    reload = asyncio.create_task(_reload_certificate(secure, cert, key))
    tasks = [asyncio.create_task(plain.serve()), asyncio.create_task(secure.serve())]
    try:
        # Each server catches SIGTERM for itself (the last one wins), so when one stops, stop the other.
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        plain.should_exit = secure.should_exit = True
        await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        reload.cancel()


def main() -> None:
    cert = os.environ.get("MOONLIGHT_SSL_CERT")
    key = os.environ.get("MOONLIGHT_SSL_KEY")
    if cert and key:
        asyncio.run(_serve_both(cert, key))
    else:
        uvicorn.Server(_config(int(os.environ.get("MOONLIGHT_PORT", "8091")))).run()


if __name__ == "__main__":
    main()
