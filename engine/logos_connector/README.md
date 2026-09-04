# Logos COM automation helper

`logos_bridge.ps1` is the companion script `tc_ai_bridge/logos_connector.py`'s
`LogosConnectorClient` has always expected at
`logos_connector/logos_bridge.ps1` (see `_default_script_path()`), but which
did not exist anywhere in this repo before Phase 7 (see
`docs/BUILD_LOG.md`). It is now real and genuinely exercised by
`engine/tests/test_logos_connector.py`.

## What's verified

The first draft was written without Logos installed. On 2026-09-04, the full
connector was verified against Logos 53.1 with an ESV Bible panel open:

- The documented PowerShell ProgID is `LogosBibleSoftware.Launcher` (with
  versioned fallback `.Launcher.1`), not the generated interop namespace
  `Logos4Lib.LogosLauncher` guessed by the first draft.
- Current state uses the documented `GetActivePanel()` and
  `GetCurrentReferencesAndHeadwords()` calls, then reads the returned Bible
  reference's `Details.Book/Chapter/Verse`.
- PowerShell's .NET COM wrapper failed on Logos's typed return values with
  HRESULT `0x80131165` even though the type library was registered. The small
  bundled `logos_com.vbs` shim uses native `IDispatch`, avoiding that wrapper;
  live state read `PHP 1:5` from the ESV panel and live outbound navigation to
  the same reference succeeded.
- `engine/tests/test_logos_connector.py` proves the real subprocess wiring:
  `LogosConnectorClient` genuinely spawns this script, exchanges
  newline-delimited JSON over stdin/stdout, and returns either a valid state or
  a clean `LogosConnectorError` rather than hanging or emitting malformed
  output. A closed application remains a normal, non-error disconnected state.

## The shim's error handling is per-procedure, on purpose

`logos_com.vbs` sets `On Error Resume Next` **twice**: once at file scope and
again as the first statement of `Sub EmitState`. That is not redundant.
VBScript scopes `On Error Resume Next` to the procedure that executes it, so
the file-scope handler does not cover the Sub. Without its own, the first COM
error inside `EmitState` (a non-Bible panel is active, Logos will not hand the
panel over, a build without `LogosPanel.Kind`) aborts the whole Sub, execution
resumes in the caller at `WScript.Quit 0`, and the helper exits **0 having
printed nothing** - which `logos_bridge.ps1` reports as `Native Logos COM shim
returned no response` while Logos is in fact running and connected. The same
path runs after a *successful* `ExecuteUri`, so a navigation that worked could
be reported as a failure.

Do not remove either one, and add `On Error Resume Next` to any new procedure
that touches a COM object. The regression test is
`test_state_is_still_reported_when_the_active_panel_raises` in
`engine/tests/test_logos_connector.py`; it lifts the real `Sub EmitState` out of
this file rather than copying it, so it keeps tracking what ships.

## Still to verify against a live Logos

The panel-failure path above is proven by fault injection, not by a real
session. Switching Logos to a non-Bible panel (and running the frozen sidecar
via `scripts/smoke_sidecars.py` after `build-sidecars.ps1`) still needs a pass
on a machine with Logos installed.

## No live event push - deliberate, not a shortfall

This helper never tries to register for Logos's `PanelActivated`/
`PanelChanged` COM events. A plain PowerShell script with no WinForms/WPF
message loop cannot reliably pump COM callbacks, and
`tc_ai_bridge/navigation.py`'s `NavigationBroker` is already built around a
*polling* connector model (its echo-suppression and settling-window logic
exists specifically to make repeated polling safe) - so Bridge calling
`state` periodically is the intended integration shape, not a fallback.
