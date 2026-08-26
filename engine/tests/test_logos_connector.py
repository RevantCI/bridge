"""
Real (not mocked) integration test between tc_ai_bridge/logos_connector.py's
LogosConnectorClient and the actual logos_connector/logos_bridge.ps1 helper
script added in Phase 7 (see docs/BUILD_LOG.md) - the companion that
did not exist anywhere in this repo before this pass.

Logos itself is not installed on this machine (confirmed at the start of this
work), so this cannot verify the real COM automation path - only that
LogosConnectorClient can actually spawn the real script, that it starts in
-STA mode without crashing, and that the two sides speak the same
newline-delimited JSON protocol for real, including a real "Logos isn't
installed" error round-tripping cleanly rather than hanging or crashing the
helper. This is a floor, not a ceiling: it proves the wiring, not the COM
calls inside Handle-State/Handle-Navigate.
"""
import shutil

import pytest

from tc_ai_bridge.logos_connector import LogosConnectorClient, LogosConnectorError


pytestmark = pytest.mark.skipif(
    not shutil.which("powershell.exe") and not shutil.which("powershell"),
    reason="Windows PowerShell is required to run the real logos_bridge.ps1 helper.",
)


def test_default_script_path_resolves_to_the_real_bundled_helper():
    client = LogosConnectorClient()
    assert client.script_path.name == "logos_bridge.ps1"
    assert client.script_path.is_file()


def test_get_state_round_trips_through_the_real_helper_process():
    """Logos isn't installed here, so this must surface a clean
    LogosConnectorError (the helper's own real COM-object-creation failure),
    not a hang, a crash, or a malformed-response error - proving the actual
    subprocess/STA/stdin-stdout JSON protocol genuinely works end to end."""
    client = LogosConnectorClient(startup_timeout=15.0)
    with pytest.raises(LogosConnectorError) as excinfo:
        client.get_state()
    message = str(excinfo.value)
    assert "invalid connector response" not in message.lower()
    assert "did not respond within" not in message.lower()
    client.close()


def test_set_reference_also_round_trips_cleanly(tmp_path):
    client = LogosConnectorClient(startup_timeout=15.0)
    try:
        with pytest.raises(LogosConnectorError):
            client.set_reference("TIT 1:1")
    finally:
        client.close()


def test_close_stops_the_helper_process():
    client = LogosConnectorClient(startup_timeout=15.0)
    with pytest.raises(LogosConnectorError):
        client.get_state()
    assert client.running is True
    client.close()
    assert client.running is False
