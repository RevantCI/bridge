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

**Status:** `v0.8.0-beta.8` — the full import → check → review → align →
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
.venv\Scripts\python.exe -m pytest tests/ greek_room_engine/tests/ -v   # expect 223 passed

# 2. Full desktop app (needs Rust + MSVC build tools, see Developer Setup)
cd ..
npm install
.\scripts\build-sidecars.ps1
npm run tauri dev
```

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
verified against real translationCore projects. See:

- [`docs/USER_MANUAL.md`](docs/USER_MANUAL.md) for what's usable today, in
  plain language.
- [`docs/DEVELOPER_GUIDE.md`](docs/DEVELOPER_GUIDE.md) for the phase-by-phase
  roadmap and exactly what's done vs. deliberately deferred.
- [`docs/QA_TEST_MATRIX.md`](docs/QA_TEST_MATRIX.md) for the release gate.

## License

See [`LICENSE`](LICENSE) (GPL-3.0). Bundled Scripture/translation-helps data
and vendored third-party code carry their own licenses — see
[`docs/DEVELOPER_GUIDE.md#bundled-data--vendored-packages`](docs/DEVELOPER_GUIDE.md#bundled-data--vendored-packages).
