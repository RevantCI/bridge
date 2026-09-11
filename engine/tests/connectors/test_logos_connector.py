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
import subprocess

import pytest

from tc_ai_bridge.logos_connector import (
    LogosConnectorClient,
    LogosConnectorError,
    bridge_to_logos_reference,
    bridge_to_logos_uri,
)


pytestmark = pytest.mark.skipif(
    not shutil.which("powershell.exe") and not shutil.which("powershell"),
    reason="Windows PowerShell is required to run the real logos_bridge.ps1 helper.",
)


def test_default_script_path_resolves_to_the_real_bundled_helper():
    client = LogosConnectorClient()
    assert client.script_path.name == "logos_bridge.ps1"
    assert client.script_path.is_file()
    helper = client.script_path.read_text(encoding="utf-8")
    shim = client.script_path.with_name("logos_com.vbs")
    assert shim.is_file()
    assert "logos_com.vbs" in helper
    assert 'CreateObject("LogosBibleSoftware.Launcher")' in shim.read_text(encoding="utf-8")
    assert "New-Object -ComObject 'Logos4Lib.LogosLauncher'" not in helper


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
    assert bridge_to_logos_uri("PHP 1:5") == "logosref:Bible.Php1.5"


def test_close_stops_the_helper_process():
    client = LogosConnectorClient(startup_timeout=15.0)
    try:
        client.get_state()
    except LogosConnectorError:
        pass
    assert client.running is True
    client.close()
    assert client.running is False


_FAKE_APP_HARNESS = '''Option Explicit

Sub Emit(name, value)
    WScript.Echo name & "=" & CStr(value)
End Sub

Class FakeApp
    ' An active panel Logos will not hand over: what a non-Bible panel or a
    ' window caught mid-transition actually produces.
    Public Function GetActivePanel()
        Err.Raise 5, "FakeApp", "Panel is unavailable"
    End Function
    Public Property Get ApiVersion
        ApiVersion = 3
    End Property
End Class

{emit_state}

On Error Resume Next
Dim app
Set app = New FakeApp
EmitState app
'''


def _emit_state_sub() -> str:
    """The real logos_com.vbs EmitState body, lifted for isolated execution."""
    shim = LogosConnectorClient().script_path.with_name("logos_com.vbs")
    text = shim.read_text(encoding="utf-8")
    start = text.index("Sub EmitState")
    end = text.index("End Sub", start) + len("End Sub")
    return text[start:end]


@pytest.mark.skipif(
    not shutil.which("cscript.exe") and not shutil.which("cscript"),
    reason="Windows Script Host is required to run the real logos_com.vbs shim.",
)
def test_state_is_still_reported_when_the_active_panel_raises(tmp_path):
    """
    VBScript scopes `On Error Resume Next` per procedure, so EmitState needs its
    own. Without it the first COM error - a non-Bible panel, a panel Logos will
    not hand over, a build without LogosPanel.Kind - aborts the whole Sub, the
    helper exits 0 having printed nothing, and the PowerShell transport reports
    "shim returned no response" while Logos is in fact running and connected.
    """
    harness = tmp_path / "emit_state_probe.vbs"
    harness.write_text(
        _FAKE_APP_HARNESS.format(emit_state=_emit_state_sub()), encoding="utf-8",
    )
    completed = subprocess.run(
        ["cscript", "//NoLogo", str(harness)],
        capture_output=True, text=True, timeout=60,
    )
    emitted = dict(
        line.split("=", 1) for line in completed.stdout.splitlines() if "=" in line
    )
    assert emitted.get("ok") == "1", f"EmitState went silent: {completed.stdout!r}"
    assert emitted.get("connected") == "1"
    assert emitted.get("api_version") == "3"
    # Connected, but with no Bible reference to report from that panel.
    assert emitted.get("book_abbrev") == ""
    assert emitted.get("verse") == ""

