# Bridge

**A local-first Bible translation QA workbench.**

Bridge helps translation teams check, align, and export Bible translation
projects (translationCore-format) entirely offline — spelling and
consistency checks, translation-notes/translation-words review, word-level
alignment to the Hebrew/Greek source, and USFM structural/versification
checks, all in one desktop app with a human-in-the-loop review workflow.

It replaces an older Python/Tkinter tool with a faster, native-feeling
desktop app (Tauri + Svelte), while keeping the same QA engines
([Greek Room](https://github.com/BibleNLP/greek-room)) and translation
business logic underneath.

**Status:** `v0.8.0-beta.13` — the full import → check → review → align →
export loop works end to end. See [Current status](#current-status) below.

## Who this is for

- **Translators and checkers** using Bridge day to day → read the
  **[User Manual](docs/USER_MANUAL.md)**: what the app does, how to import a
  project, how to work through the review screens, what tN/tW/alignment/
  versification actually mean, and how Bridge compares to translationCore.
- **Developers and QA** setting up or extending Bridge → read
  **[Developer Setup](docs/DEVELOPER_SETUP.md)** to get a working dev
  environment and build the desktop app.
- **Developers** who want the technical background — architecture decisions,
  the phase roadmap and what's actually shipped, dependencies, and vendored/
  bundled data → read the **[Developer Guide](docs/DEVELOPER_GUIDE.md)**.

## Quick start (developers)

```powershell
# 1. Python engine
cd engine
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -c constraints-py312-windows.txt -e ".[dev,wildebeest]"
.venv\Scripts\python.exe -m pytest tests/ greek_room_engine/tests/ -v   # expect 261 passed

# 2. Full desktop app (needs Rust + MSVC build tools, see Developer Setup)
cd ..
npm install
npm run test:dev-start
npm run test:ui-state
.\scripts\build-sidecars.ps1
npm run tauri dev
```

## Run locally on Windows

If this checkout has already been set up, open PowerShell in the repository
root and run:

```powershell
npm run tauri dev
```

Tauri first builds the frontend and serves it from a local Vite preview,
compiles the Rust development shell when needed, launches the bundled Python
sidecars, and opens the Bridge desktop window. This deterministic preview path
avoids a Windows WebView/Vite on-demand Svelte compiler runaway that otherwise
produces a white window. Keep the terminal open while using Bridge; press
`Ctrl+C` in that terminal to stop the development app.

For a new checkout, complete the **Quick start** above first. Re-run
`.\scripts\build-sidecars.ps1` whenever Python engine code or bundled engine
resources change. Frontend-only Svelte/CSS changes do not require rebuilding
the sidecars, but they do require restarting `npm run tauri dev` so the local
frontend bundle is rebuilt.

If local startup fails, verify these files exist before retrying:

```text
engine/.venv/Scripts/python.exe
src-tauri/binaries/bridge-engine-x86_64-pc-windows-msvc.exe
src-tauri/binaries/bridge-usfm-checker-x86_64-pc-windows-msvc.exe
```

If the Tauri window opens blank, stop the development process and run
`npm run test:dev-start`. This smoke test performs the same production-style
frontend compile used by the local desktop launcher, starts an isolated preview
server, and verifies that both the index and application bundle are available.

Full prerequisites, platform notes, and troubleshooting:
**[docs/DEVELOPER_SETUP.md](docs/DEVELOPER_SETUP.md)**.

## Repo layout

```
engine/           BridgeEngine sidecar (GreekRoomEngine + tc_ai_bridge, one JSON protocol)
src/              Svelte frontend
src-tauri/        Rust shell (spawns + talks to the sidecar)
paratext_plugin/  Companion Paratext plugin (C#)
scripts/          Build and resource-vendoring scripts
docs/             User manual, developer setup, architecture, roadmap, import/alignment design, QA matrix
```

## Current status

The import → check → review → manual-align → export loop is implemented and
verified against real translationCore projects. Beta 11 installed acceptance
confirmed upgrade/project preservation, reference-scoped AI review state,
persisted tN/tW results, protected human/imported selections, stale-review
reruns, chapter/book processing, alignment, and export. A small amount of
Translation Helps navigation jitter remains as non-blocking UX follow-up work.

Beta 13 carries the completed Milestone 3B.4 workflow and fixes contradictory
AI proposals that cited exact target words while returning **Nothing to
Select**. Reviewers can turn a tN/tW finding into a
persisted issue-resolution record, attach exact target text, correction,
evidence and a reviewer note, and hand it off to a confirmed Paratext project.
The crash-safe, idempotent queue preserves queued and sent state across
restarts. Editing a resolved verse starts an automatic grounded recheck;
Advanced mode keeps uncertain results for a human decision and records the
result in an append-only lifecycle audit.
See:

- [`docs/USER_MANUAL.md`](docs/USER_MANUAL.md) for what's usable today, in
  plain language.
- [`docs/DEVELOPER_GUIDE.md`](docs/DEVELOPER_GUIDE.md) for the phase-by-phase
  roadmap and exactly what's done vs. deliberately deferred.
- [`docs/QA_TEST_MATRIX.md`](docs/QA_TEST_MATRIX.md) for the release gate.

## License

See [`LICENSE`](LICENSE) (GPL-3.0). Bundled Scripture/translation-helps data
and vendored third-party code carry their own licenses — see
[`docs/DEVELOPER_GUIDE.md#bundled-data--vendored-packages`](docs/DEVELOPER_GUIDE.md#bundled-data--vendored-packages).
