# Logos COM automation helper

`logos_bridge.ps1` is the companion script `tc_ai_bridge/logos_connector.py`'s
`LogosConnectorClient` has always expected at
`logos_connector/logos_bridge.ps1` (see `_default_script_path()`), but which
did not exist anywhere in this repo before Phase 7 (see
`docs/BUILD_LOG.md`). It is now real and genuinely exercised by
`engine/tests/test_logos_connector.py`.

## What's verified and what isn't

The first draft was written without Logos installed. On 2026-09-03, a local
Logos installation exposed the registered `LogosBibleSoftware.Launcher` and
`.Launcher.1` COM classes, and the real helper returned a clean disconnected
state while Logos was closed. What **is** verified:

- The documented PowerShell ProgID is `LogosBibleSoftware.Launcher` (with
  versioned fallback `.Launcher.1`), not the generated interop namespace
  `Logos4Lib.LogosLauncher` guessed by the first draft.
- Current state uses the documented `GetActivePanel()` and
  `GetCurrentReferencesAndHeadwords()` calls, then reads the returned Bible
  reference's `Details.Book/Chapter/Verse`.
- `engine/tests/test_logos_connector.py` proves the real subprocess wiring:
  `LogosConnectorClient` genuinely spawns this script in `-STA` mode,
  exchanges newline-delimited JSON over stdin/stdout, and returns either a
  valid state or a clean `LogosConnectorError` rather than hanging or emitting
  malformed output. The script's own parser syntax was checked with
  `[System.Management.Automation.Language.Parser]::ParseFile()`.

Still pending: start Logos with a Bible panel open and verify both the returned
active Bible reference and `Navigate()` against the installed release. Bridge
does not launch Logos automatically; a closed application remains a normal,
non-error disconnected state.

## No live event push - deliberate, not a shortfall

This helper never tries to register for Logos's `PanelActivated`/
`PanelChanged` COM events. A plain PowerShell script with no WinForms/WPF
message loop cannot reliably pump COM callbacks, and
`tc_ai_bridge/navigation.py`'s `NavigationBroker` is already built around a
*polling* connector model (its echo-suppression and settling-window logic
exists specifically to make repeated polling safe) - so Bridge calling
`state` periodically is the intended integration shape, not a fallback.
