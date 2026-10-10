"""HA-side tests. They need pytest-homeassistant-custom-component (which installs Home Assistant), so they are
skipped unless it is importable. Run in a venv that has it:

    python3 -m venv .venv-ha && .venv-ha/bin/pip install pytest-homeassistant-custom-component
    .venv-ha/bin/python -m pytest -q -p no:cacheprovider tests/ha

These tests talk to 127.0.0.1 over real sockets. A real Moonlight backend is started as a subprocess with the system `python3` (override with
MOONLIGHT_PYTHON), which needs fastapi + uvicorn installed.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

try:
    import pytest_homeassistant_custom_component  # noqa: F401
except ImportError:  # pragma: no cover
    collect_ignore_glob = ["test_*.py"]

ROOT = Path(__file__).resolve().parents[2]
try:
    # The plugin ships its own `custom_components` package (testing_config); add ours to its search path
    # so HA's loader finds custom_components/moonlight from this repo.
    import custom_components

    if str(ROOT / "custom_components") not in custom_components.__path__:
        custom_components.__path__.append(str(ROOT / "custom_components"))
except ImportError:  # pragma: no cover
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _run_moonlight(tmp_path, **extra_env):
    port = _free_port()
    env = {**os.environ, "MOONLIGHT_PORT": str(port), "MOONLIGHT_HOST": "127.0.0.1",
           "MOONLIGHT_DB": str(tmp_path / "moonlight.db"), "MOONLIGHT_DEMO": "1",
           "MOONLIGHT_STATIC": str(tmp_path / "no-dist"), "MOONLIGHT_LOG_LEVEL": "warning",
           "PYTHONDONTWRITEBYTECODE": "1", **extra_env}
    env.pop("MOONLIGHT_WEATHER_ENTITY", None)
    if "MOONLIGHT_AUTH" not in extra_env:
        env.pop("MOONLIGHT_AUTH", None)
    proc = subprocess.Popen([os.environ.get("MOONLIGHT_PYTHON", "/usr/bin/python3"), "-m", "moonlight"],
                            cwd=ROOT / "backend", env=env)
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1).read()
                break
            except OSError:
                time.sleep(0.1)
        else:
            raise RuntimeError("Moonlight did not start")
        yield port
    finally:
        proc.terminate()
        proc.wait(10)


@pytest.fixture
def moonlight_server(tmp_path, socket_enabled):
    """A real Moonlight with the demo family on 127.0.0.1:<port>. Yields the port."""
    yield from _run_moonlight(tmp_path)


@pytest.fixture
def moonlight_server_pairing(tmp_path, socket_enabled):
    """Like moonlight_server, but with pairing required. Requests from 127.0.0.1 with an `X-Ingress-Path` header
    count as HA ingress (so a test can approve codes); Home Assistant's own requests don't send it."""
    yield from _run_moonlight(tmp_path, MOONLIGHT_AUTH="on", MOONLIGHT_INGRESS_IPS="127.0.0.1")
