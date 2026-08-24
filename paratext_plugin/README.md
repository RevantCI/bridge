# translationCore AI Bridge - Paratext companion plugin

This closes the real blocker recorded in `docs/DEVELOPER_HANDOFF.md`'s Phase 7
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

**Not yet verified**: this plugin has never actually been loaded by a running
Paratext instance. Deploying it requires copying into
`C:\Program Files\Paratext 9\plugins\TranslationCoreAIBridgePlugin\` (a
protected system directory) - the build was completed and the compiled DLL
exists at `build/TranslationCoreAIBridgePlugin.dll`, but the actual copy step
was blocked by this session's own safety controls (writing into `Program
Files`) rather than run automatically. Whoever deploys it next should:

1. Close Paratext if it's running (Paratext's own plugin docs: "Paratext must
   not be running when doing these copies").
2. Run `build.ps1 -Deploy` from an elevated (Run as Administrator) PowerShell.
3. Launch Paratext and check `%LOCALAPPDATA%\Paratext95\ParatextLog.log` for
   this plugin loading (or a load failure) - the very first real signal about
   whether the interface assumptions above actually hold at runtime.
4. Only then trust `get_state`/`set_reference` actually work end to end - a
   real named-pipe round trip via `paratext_connector.py`'s own
   `ParatextConnectorClient` is the next real test, not assumed from this
   plugin compiling cleanly.

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
- The Python side (`bridge_service.py`) still has zero protocol methods
  calling `ParatextConnectorClient` - this plugin only unblocks that work,
  it doesn't complete it.
