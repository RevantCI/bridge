"""
Protocol-level tests for the Phase 7 paratext.*/logos.* methods added to
bridge_service.py. Neither a real Paratext plugin instance nor a real Logos
installation is available on this machine, so these confirm the wiring
(method dispatch, error-code mapping, the Logos persistent-subprocess
lifecycle) rather than real live-navigation behavior — see
paratext_plugin/README.md and engine/logos_connector/README.md for what
remains genuinely unverified end to end.
"""
import shutil

import pytest

from bridge_service import BridgeEngine
from greek_room_engine.protocol import EngineRequest


def call(engine, method, params=None):
    return engine.handle_request(EngineRequest(id="t", method=method, params=params or {})).to_dict()


def test_paratext_get_state_fails_cleanly_with_no_companion_plugin_running():
    engine = BridgeEngine()
    result = call(engine, "paratext.getState")
    assert result["success"] is False
    assert result["error"]["code"] == "paratext_connector_error"


def test_paratext_set_reference_fails_cleanly_with_no_companion_plugin_running():
    engine = BridgeEngine()
    result = call(engine, "paratext.setReference", {"reference": "TIT 1:1"})
    assert result["success"] is False
    assert result["error"]["code"] == "paratext_connector_error"


@pytest.mark.skipif(
    not shutil.which("powershell.exe") and not shutil.which("powershell"),
    reason="Windows PowerShell is required to run the real logos_bridge.ps1 helper.",
)
def test_logos_get_state_spawns_the_real_helper_and_fails_cleanly_without_logos_installed():
    engine = BridgeEngine()
    try:
        result = call(engine, "logos.getState")
        assert result["success"] is False
        assert result["error"]["code"] == "logos_connector_error"
        # The same BridgeEngine reuses one persistent helper process rather than
        # spawning a fresh one for every call — the real point of caching it.
        assert engine._logos_client is not None
        assert engine._logos_client.running is True
    finally:
        if engine._logos_client is not None:
            engine._logos_client.close()


@pytest.mark.skipif(
    not shutil.which("powershell.exe") and not shutil.which("powershell"),
    reason="Windows PowerShell is required to run the real logos_bridge.ps1 helper.",
)
def test_logos_set_reference_fails_cleanly_without_logos_installed():
    engine = BridgeEngine()
    try:
        result = call(engine, "logos.setReference", {"reference": "TIT 1:1"})
        assert result["success"] is False
        assert result["error"]["code"] == "logos_connector_error"
    finally:
        if engine._logos_client is not None:
            engine._logos_client.close()
