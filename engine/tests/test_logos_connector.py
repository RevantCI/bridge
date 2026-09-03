"""
Real (not mocked) integration test between tc_ai_bridge/logos_connector.py's
LogosConnectorClient and the actual logos_connector/logos_bridge.ps1 helper
script added in Phase 7 (see docs/BUILD_LOG.md) - the companion that
did not exist anywhere in this repo before this pass.

The test is read-only and environment-independent: an installed Logos COM API
may return connected or disconnected state, while a machine without the API may
return a clean connector error. Tests never navigate a developer's live Logos
session.
"""
import shutil

import pytest

from tc_ai_bridge.logos_connector import (
    LogosConnectorClient,
    LogosConnectorError,
    bridge_to_logos_reference,
)


pytestmark = pytest.mark.skipif(
    not shutil.which("powershell.exe") and not shutil.which("powershell"),
    reason="Windows PowerShell is required to run the real logos_bridge.ps1 helper.",
)


def test_default_script_path_resolves_to_the_real_bundled_helper():
    client = LogosConnectorClient()
    assert client.script_path.name == "logos_bridge.ps1"
    assert client.script_path.is_file()


def test_get_state_round_trips_through_the_real_helper_process():
    """The real helper returns state when registered and a clean error otherwise."""
    client = LogosConnectorClient(startup_timeout=15.0)
    try:
        try:
            state = client.get_state()
            assert isinstance(state.connected, bool)
        except LogosConnectorError as exc:
            message = str(exc)
            assert "invalid connector response" not in message.lower()
            assert "did not respond within" not in message.lower()
    finally:
        client.close()


def test_bridge_reference_uses_the_logos_bible_parser_name():
    assert bridge_to_logos_reference("TIT 1:1") == "Titus 1:1"


def test_close_stops_the_helper_process():
    client = LogosConnectorClient(startup_timeout=15.0)
    try:
        client.get_state()
    except LogosConnectorError:
        pass
    assert client.running is True
    client.close()
    assert client.running is False
