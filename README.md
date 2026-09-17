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

**Status:** `v0.11.0` — the full import → check → review → align →
export loop works end to end. See [Current status](#current-status) below.

## Who this is for

- **Translators and checkers** using Bridge day to day → read the
  **[User Manual](docs/USER_MANUAL.md)**: what the app does, how to import a
  project, how to work through the review screens, what tN/tW/alignment/
  versification actually mean, and how Bridge compares to translationCore.
- **Developers and QA** setting up or extending Bridge → read
  **[Developer Setup](docs/DEVELOPER_SETUP.md)** to get a working dev
  environment and build the desktop app.
- **Developers** who want the technical background → start with
  **[Architecture](docs/ARCHITECTURE.md)** (current state: process boundary, why
  the stack is what it is, the three databases, pipelines — and §9, the map of
  every other doc), then the **[Developer Guide](docs/DEVELOPER_GUIDE.md)** for
  the phase roadmap and what actually shipped.

## Running it

Everything about getting a dev environment working — prerequisites, the Python
engine, the frontend, the full desktop app, building the installer, and the
Windows problems worth knowing about — is in
**[docs/DEVELOPER_SETUP.md](docs/DEVELOPER_SETUP.md)**. In an already-set-up
checkout:

```powershell
npm run tauri dev
```

Re-run `.\scripts\build-sidecars.ps1` whenever Python engine code or bundled
engine resources change.

## Repo layout

```
engine/           BridgeEngine sidecar (GreekRoomEngine + tc_ai_bridge, one JSON protocol)
src/              Svelte frontend
src-tauri/        Rust shell (spawns + talks to the sidecar)
paratext_plugin/  Companion Paratext plugin (C#)
scripts/          Build and resource-vendoring scripts
docs/             Architecture (and the doc map, §9), user manual, setup, roadmap,
                  invariants, import/alignment design, QA matrix, release notes
```

## Current status

The import → check → review → align → export loop is implemented and verified
against real translationCore projects. Since 0.10.0 every Bridge-private record
(human decisions, check results, progress, alignment history) lives in a
per-project SQLite database rather than JSON files, with an app-level database
for the project registry; 0.11.0 added the **Cross-verse alignment** page, where
a source word can be recorded as realized in a neighbouring verse without
faking a translationCore alignment, and taught the semantic pipeline to read
those records as evidence.

Where to look next:

- [`docs/RELEASE_0.11.0.md`](docs/RELEASE_0.11.0.md) and its siblings —
  what changed in each version, including the one-way database migration.
- [`docs/USER_MANUAL.md`](docs/USER_MANUAL.md) — what's usable today, in plain
  language (written against 0.9.6; see the note at its top).
- [`docs/DEVELOPER_GUIDE.md`](docs/DEVELOPER_GUIDE.md) — the phase-by-phase
  roadmap and exactly what's done vs. deliberately deferred.
- [`docs/QA_TEST_MATRIX.md`](docs/QA_TEST_MATRIX.md) — the release gate.

## License

See [`LICENSE`](LICENSE) (GPL-3.0). Bundled Scripture/translation-helps data
and vendored third-party code carry their own licenses — see
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) §3.1 and each
`engine/vendor/*/NOTICE.md`.
