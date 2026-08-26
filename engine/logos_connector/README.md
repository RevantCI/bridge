# Logos COM automation helper

`logos_bridge.ps1` is the companion script `tc_ai_bridge/logos_connector.py`'s
`LogosConnectorClient` has always expected at
`logos_connector/logos_bridge.ps1` (see `_default_script_path()`), but which
did not exist anywhere in this repo before Phase 7 (see
`docs/BUILD_LOG.md`). It is now real and genuinely exercised by
`engine/tests/test_logos_connector.py`.

## What's verified and what isn't

Logos was not installed on the machine this was written on, so the actual
COM automation calls inside `Handle-State`/`Handle-Navigate` have never been
run against a real Logos instance. What **is** verified:

- The script's own file header cites the real, sourced API surface (COM
  ProgID/type-library GUID, method/property names) pulled directly from
  `LogosBible/Logos4ComApiDemo`'s actual `.cs`/`.csproj` source on GitHub,
  not from memory or docs alone.
- `engine/tests/test_logos_connector.py` proves the real subprocess wiring:
  `LogosConnectorClient` genuinely spawns this script in `-STA` mode,
  exchanges newline-delimited JSON over stdin/stdout, and a real "Logos
  isn't installed" failure round-trips as a clean `LogosConnectorError`
  rather than a hang or a malformed-response error. The script's own parser
  syntax was checked with
  `[System.Management.Automation.Language.Parser]::ParseFile()`.

Two things flagged inline in the script's own header as the most likely to
need a real fix once tested against a live Logos install:

1. The COM ProgID `"Logos4Lib.LogosLauncher"` follows the standard `tlbimp`
   naming convention but was never confirmed against a real registered
   class. `Get-LogosLauncher` searches the registry for a plausible
   alternative and reports it in its error message if the literal string
   fails.
2. Reading the *currently active panel's* Bible reference
   (`Get-CurrentReferenceInfo`) is a best-effort guess (`$app.ActivePanel`,
   then `.DataType.Details.Book/Chapter/Verse`) - the official demo project
   only shows *pushing* a reference via `Navigate()`, never reading one back,
   so this path has no real source to verify against. It's wrapped in
   defensive `try`/`catch` throughout so a wrong guess degrades to an empty
   reference (still a valid, non-crashing response) rather than breaking the
   helper.

Whoever tests this next against a real Logos install (per this session's
plan: installed by the user, verified by a colleague who already has it)
should run an interactive `-STA` PowerShell session, get a live `$app`
object the same way this script does, and run `$app | Get-Member` /
`$app.ActivePanel | Get-Member` to confirm or correct those two points -
then this note (and the corresponding one in the script header) should be
updated to say what was actually confirmed, per this project's own standing
practice of never leaving a doc's claim unverified once real testing is
possible.

## No live event push - deliberate, not a shortfall

This helper never tries to register for Logos's `PanelActivated`/
`PanelChanged` COM events. A plain PowerShell script with no WinForms/WPF
message loop cannot reliably pump COM callbacks, and
`tc_ai_bridge/navigation.py`'s `NavigationBroker` is already built around a
*polling* connector model (its echo-suppression and settling-window logic
exists specifically to make repeated polling safe) - so Bridge calling
`state` periodically is the intended integration shape, not a fallback.
