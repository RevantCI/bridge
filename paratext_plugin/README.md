# translationCore AI Bridge - Paratext companion plugin

This closes the real blocker recorded in `docs/BUILD_LOG.md`'s Phase 7
section: `engine/tc_ai_bridge/paratext_connector.py`'s `ParatextConnectorClient`
only ever talked to a companion plugin over a Windows named pipe
(`\\.\pipe\translationCoreAIBridge`) that did not exist anywhere in this repo.
This is that companion - a real, compiling `IParatextStartupAutomaticPlugin`.

## What this is (and isn't) verified against

Every Paratext interface used here (`IPluginHost`, `IVerseRef`,
`IParatextChildState`, `IProject`, `IVersification`,
`ParatextInternal.IParatextPlugin`, `ReferenceChangedHandler`,
`SyncReferenceGroup`, ...) was confirmed by reflecting into the real
`PluginInterfaces.dll` / `CorePluginInterfaces.dll` installed at
`C:\Program Files\Paratext 9` on the machine this was built on - not copied
from documentation, per this project's own standing practice of verifying
against real code. The named-pipe wire protocol (newline-delimited JSON,
`{"protocol":1,"id":...,"action":...,"payload":{...}}`, response echoes `id`
and carries `ok`/`error`) matches `paratext_connector.py`'s `_exchange()`
method exactly.

**Live verification update (2026-08-26):** this v1.0 plugin was loaded by
Paratext 9.5.110.1 and its named-pipe `get_state` response was verified. That
test also discovered a pre-existing, fuller v0.7.4 connector installed at
`plugins\translationCoreAIBridge\translationCoreAIBridge.ptxplg`. Both plugins
use the same named pipe and must never be installed together. The v1.0 plugin
was moved to a recoverable disabled backup and the full connector was retained.
`build.ps1 -Deploy` now refuses to deploy v1.0 while that connector exists.

On a machine without another Bridge connector, deployment requires copying to
`C:\Program Files\Paratext 9\plugins\TranslationCoreAIBridgePlugin\` (a
protected system directory). The operator should:

1. Close Paratext if it's running (Paratext's own plugin docs: "Paratext must
   not be running when doing these copies").
2. Run `build.ps1 -Deploy` from an elevated (Run as Administrator) PowerShell.
3. Launch Paratext and check `%LOCALAPPDATA%\Paratext95\ParatextLog.log` for
   this plugin loading (or a load failure) - the very first real signal about
   whether the interface assumptions above actually hold at runtime.
4. Verify `get_state`/`set_reference` end to end with
   `paratext_connector.py`'s own `ParatextConnectorClient`.

`create_note` is intentionally **not implemented** - it returns a clear
"not implemented" error over the pipe. Bridge already has a complete, working
Paratext Notes 1.1 XML writer (`engine/tc_ai_bridge/paratext_notes.py`) that
writes notes directly to disk without this plugin at all. A live `AddNote()`
call through the plugin would need an `IWriteLock`,
`IScriptureTextSelection`, and `CommentParagraph` objects this session had no
way to construct/verify against a real running Paratext instance - exactly
the kind of unverified integration this project's own practice warns
against. Revisit only if the XML-file path turns out to be insufficient.

## Build

No Visual Studio, modern .NET SDK, or NuGet required - `build.ps1` compiles
with the C# compiler bundled in Windows' own .NET Framework install
(`C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe`), referencing
Paratext's own installed plugin-interface DLLs directly plus
`System.Web.Extensions.dll` (bundled with .NET Framework, provides
`JavaScriptSerializer` for JSON with no external dependency) and
`netstandard.dll` (the plugin interfaces are themselves built against
netstandard2.0, confirmed by the compiler's own `CS0012` errors on the first
build attempt - not assumed).

```powershell
powershell -ExecutionPolicy Bypass -File build.ps1            # build only
powershell -ExecutionPolicy Bypass -File build.ps1 -Deploy    # build + deploy (elevated, Paratext closed)
```

## Known real gaps in this first pass

- `.pdb` is copied alongside the `.ptxplg` for debugging (per the official
  demo plugins wiki's "Debugging a Plugin" page), but real interactive
  debugging through Visual Studio was never attempted this session.
- No automated test exists for this project (nothing in `engine/tests/`
  exercises it - it's a separate .NET project outside the Python test
  suite). If it proves out against a real Paratext instance, a scripted
  pipe-client smoke test (analogous to `scripts/smoke_sidecars.py`) would be
  worth adding.
- The Python side now persists issue-resolution records and accepts both the
  newer `create_note` capability name and the full v0.7.4 connector's
  `project_notes` capability family. It still requires the active project to
  match the explicitly confirmed project ID. With this navigation-only v1.0
  companion, handoffs remain safely queued because note creation is
  intentionally unsupported; they are never reported as sent.
