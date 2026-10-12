import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from moonlight import caldav_sync  # noqa: E402


@pytest.fixture(autouse=True)
def no_retry_waits(monkeypatch):
    """Calendar syncs wait between retries after a network error; tests don't."""
    waits = []
    monkeypatch.setattr(caldav_sync, "_sleep", waits.append)
    return waits
