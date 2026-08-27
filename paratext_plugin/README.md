# translationCore AI Bridge - Paratext companion plugin

This directory contains the source for the connector verified with Paratext
9.5.110.1. It serves protocol-1 newline-delimited JSON on the local-only named
pipe `\\.\pipe\translationCoreAIBridge`.

The connector supports:

- active user, project, reference, selection, and sync-group state;
- two-way Scripture navigation; and
- safe Project Note creation through Paratext's own write-lock and `AddNote`
  APIs.

It deliberately contains no Scripture-writing (`PutUSFM`/`PutUSX`) operation.
Bridge verifies the active Paratext project ID before sending, uses the logged-in
Paratext user as author, and refuses ambiguous repeated-text anchors.

## Live verification

The v0.7.4 connector was already installed and working on the development
machine. On 2026-08-26 Bridge verified its `get_state` response and successfully
created a real Project Note. The matching source, previously held in the older
local Bridge repository, is now maintained here.

Only one connector may be installed: every version uses the same named pipe.
The earlier navigation-only v1.0 experiment is retained outside Paratext under
`disabled-TranslationCoreAIBridgePlugin-v1/` for recovery and is git-ignored.

## Build and deploy

The build uses the .NET Framework C# compiler bundled with Windows and the
plugin-interface DLLs from the installed Paratext 9 directory.

```powershell
powershell -ExecutionPolicy Bypass -File build.ps1
powershell -ExecutionPolicy Bypass -File build.ps1 -Deploy
```

Close Paratext before `-Deploy` and run the shell as Administrator because the
destination is `C:\Program Files\Paratext 9\plugins\translationCoreAIBridge`.
The script refuses deployment while Paratext is running.

After deployment, restart Paratext, open the intended Scripture project, and
verify connector state before testing a disposable Project Note. Bridge keeps a
Notes 1.1 outbox copy and retries failed live handoffs without duplicating the
resolution or message identity.

## Remaining integration boundary

The C# assembly compiles against the locally installed Paratext interfaces, but
automated CI cannot launch Paratext. Release acceptance therefore still needs a
manual live check for connection, project-identity refusal, exact/repeated text
anchoring, and one disposable note creation.
