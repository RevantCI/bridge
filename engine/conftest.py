"""Global pytest isolation for Bridge's persistent application state."""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolate_bridge_app_data(tmp_path, monkeypatch):
    """Never let a default AppSettings()/BridgeEngine() touch real user data."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "app-data"))
