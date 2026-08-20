# Developer handoff: Scripture import pipeline

Date: 2026-08-20

## Project context (carried over from the Claude Code sessions that did Phases 1-3)

This section summarizes what the earlier Claude Code work (`docs/CLAUDE_CODE_HANDOVER.md`,
not committed to this repo — it lives in the original handover doc) established, so this
file is self-contained for whoever picks it up next.

**What Bridge is:** a local-first Bible translation QA workbench replacing a legacy Python
Tkinter tool. One window, one Python sidecar process, Tauri/Svelte desktop shell.

**Core principle** (see `docs/ARCHITECTURE.md`):
- Greek Room says: "This is objectively suspicious."
- AI says: "Here is what it may mean in this passage."
- Human says: "This is what the translation should be."
- Nothing auto-applies to project files without human approval.

**Tech stack:** Tauri v2 (Rust) shell, Svelte 4 + TypeScript + Tailwind frontend, Python 3.13
PyInstaller-bundled sidecar (`bridge-engine`), Greek Room (Wildebeest adapter, mock fallback
if the real package isn't installed) plus 29 pre-existing `tc_ai_bridge` business-logic
modules (alignment, Paratext, Logos, AI, now also import), JSON-over-stdio protocol, pytest.
Windows is the primary target (`x86_64-pc-windows-msvc`); macOS/Linux are planned.

**Repo layout skeleton:**

```
engine/
  bridge_service.py          ← the sidecar dispatcher, read this first
  main.py                    ← sidecar entrypoint (PyInstaller target)
  greek_room_engine/         ← QA adapter layer (engine.py, models/finding.py,
                                protocol.py, adapters/, transport/stdio_transport.py)
  tc_ai_bridge/               ← 29 existing business-logic modules, not rewritten
                                (now 30, with project_import.py added — see below)
  tests/                      ← pytest suite

src/
  App.svelte, lib/stores.ts, lib/api/bridgeClient.ts, lib/types/finding.ts,
  lib/components/{ImportScreen,TopBar,VerseList,ReviewPanel,SettingsModal,ExportModal}.svelte

src-tauri/
  src/{main.rs,sidecar.rs,commands.rs}
  tauri.conf.json, capabilities/default.json, binaries/, icons/

docs/
  ARCHITECTURE.md, DEVELOPER_HANDOFF.md (this file), IMPORTS.md
```

### Phases 1-3 (done, before this import work)

- **Phase 1 — Protocol & sidecar consolidation:** `BridgeEngine` composes
  `GreekRoomEngine` + `tc_ai_bridge` behind one JSON protocol (`ping`, `engine.info`,
  `project.open`, `project.scan`, `chapter.verses`, `chapter.verseData`, `verse.get`,
  `verse.runChecks`, `verse.decide`, `verse.edit`, `settings.get`, `settings.set`,
  `export.aligned`, `export.nonAligned`). 24/24 pytest passing against a real fixture
  project with verified real file writes.
- **Phase 2 — Svelte frontend wired to the real sidecar:** full single-window UI
  (ImportScreen, TopBar, VerseList with inline colored findings, ReviewPanel with live
  Greek Room re-check and Accept/Reject/Ignore/Edit). Windows UTF-8 stdout fix applied.
- **Phase 3 — Decision persistence, chapter switching, whole-book, Settings & Export:**
  stable finding ids so decisions survive re-runs, chapter switching, "Run whole book"
  automation, `SettingsModal` (any OpenAI-compatible provider/endpoint/model/key),
  `ExportModal` (aligned JSON + simplified USFM export).

**This import-pipeline work (below) is new ground, not the originally planned Phase 4.**
The original roadmap after Phase 3 was: Phase 4 = USFM structural checker
(`greek_room_engine/adapters/usfm_adapter.py`, still does not exist) + versification;
Phase 5 = names/transliteration (Uroman + SED); Phase 6 = alignment intelligence
(UAlign corpus stats); Phase 7 = Paratext/Logos connectors wired to the protocol + AI
explain + drag-and-drop import. None of Phases 4-7 have been started — this import work
was picked up instead because a working import pipeline blocks everything downstream
(you need real Scripture in the app before checks/alignment/names work matter). Whoever
picks this up next should decide explicitly whether to continue import work (see
"Recommended next work" below) or switch to Phase 4, rather than assuming the numbered
roadmap order still applies.

### Gotchas still in force (from Phases 1-3, verified still true in the current code)

1. `TranslationCoreProject.summary` is a `@property`, not a method — calling `summary()` crashes.
2. `TranslationCoreProject.__init__` creates its own `self.journal`. Never create a second one.
3. Finding ids are stable (`_stable_finding_id()` in `bridge_service.py`, a sha1 of
   `chapter:verse:engine:check_type:disambiguator`) so decisions persist across runs.
   Don't revert to random `uuid4()` ids.
4. `verse.runChecks` re-applies prior decisions from `qa_decisions_for_verse()` after
   running checks — this must stay in the check flow, not a separate call.
5. Windows stdout UTF-8 fix (`sys.stdout.reconfigure(encoding="utf-8")` in
   `stdio_transport.py`) is critical — without it, non-Latin verse text crashes the
   sidecar silently and the Rust side just sees a timeout. Never remove it.
6. `plugins.shell.sidecar` must NOT be in `tauri.conf.json` — not a valid field, causes
   a startup panic. Sidecar permission comes entirely from `capabilities/default.json`'s
   `shell:allow-execute` entry.
7. Store keys are composite `chapter:verse` (e.g. `"1:3"`) — use `verseKey()` from
   `stores.ts`, not verse-only keys (silently collides data across chapters).
8. `ai_client.py`'s `OpenAIResponsesClient` endpoint is configurable via `base_url`;
   don't reintroduce a hardcoded `ENDPOINT` constant.
9. The sidecar binary name must match the Rust target triple exactly
   (`bridge-engine-x86_64-pc-windows-msvc.exe` on Windows — get the triple from `rustc -vV`).
10. Don't use icon-font classes (`ti-settings` etc.) for icon-only controls with no
    fallback label — PyInstaller/offline builds can't reach CDN icon fonts and they
    render as empty boxes. Use Unicode characters or pair with a text label.

### Known gaps still open (from Phases 1-3, verified still true in the current code)

- **USFM edit round-trip is still a stub.** `edit_verse()` in `bridge_service.py`
  (around line 338) journals the transaction but the actual USFM verse-text replacement
  is a documented no-op comment, not implemented.
- **`export.nonAligned` is a simplified reconstruction**, not a lossless round trip
  (`\id`/`\c`/`\v` only — footnotes, section headers, poetry markup not preserved).
- **OWL repeated-word adapter doesn't exist yet** (`adapters/owl_adapter.py`).
- **Real Wildebeest package is still untested** — the adapter has a mock fallback
  (`_WILDEBEEST_AVAILABLE = False` branch) and real integration (`pip install greekroom`)
  hasn't been exercised.
- **Drag-and-drop import is still not wired** — no `onDragDropEvent` listener from
  `@tauri-apps/api` exists in `src/`; `ImportScreen` still requires the file picker.

## Objective

Continue building Bridge's import workflow so users can bring in individual
USFM/SFM files, whole-Bible folders, Paratext folders, and translationCore
projects, then use the normalized data for local QA, Greek Room,
translationNotes, translationWords, and word alignment.

The import foundation described below is implemented and verified. It has since
been committed as `9ed60cb feat(import): add translationCore-compatible Scripture
imports` — the working tree is currently clean. The "Working-tree warning" section
near the end of this document is kept for historical reference (it describes what
that commit touched) but no longer describes an uncommitted state.

## What is implemented

### Backend normalization

`engine/tc_ai_bridge/project_import.py` provides two public entry points:

- `inspect_import(source_path)`: read-only detection and metadata preview.
- `import_source(source_path, destination_root, metadata)`: staged,
  non-overwriting import and normalization.

Accepted input:

- `.usfm` and `.sfm` files.
- Marker-based `.txt` Scripture files.
- Folders containing one or many Scripture books.
- Paratext-style folders with `Settings.xml`.
- Existing translationCore project folders.
- `.tcore`, `.tstudio`, and ZIP project archives.

For raw Scripture, each book becomes a translationCore-compatible book project:

```text
<project>/
  manifest.json
  <book>.usfm
  <book>/headers.json
  <book>/<chapter>.json
  .apps/translationCore/alignmentData/<book>/<chapter>.json
  .apps/translationCore/index/translationNotes/<book>/
  .apps/translationCore/index/translationWords/<book>/
  .apps/translationCore/checkData/...
  .bridge/import.json
```

Important behavior:

- Original source bytes are preserved.
- `.bridge/import.json` records SHA-256 provenance and capability status.
- Existing translationCore indexes, decisions, comments, and alignments are
  copied intact.
- Older tC/tS projects with target chapter JSON but no alignment data receive
  unaligned target word banks so `TranslationCoreProject` can open them.
- Each unaligned target token is represented once in `wordBank`, with correct
  `occurrence` and `occurrences` values.
- Basic, non-nested USFM 3 `zaln`/`w` alignment milestones are converted into
  translationCore `topWords`/`bottomWords` groups.
- Unsupported or malformed nested alignment structures are not guessed; target
  words remain in `wordBank` for review.
- Multi-book folders produce one compatible project per book. The import result
  returns every path in `importedProjects` and opens the first project.
- ZIP entries are validated against path traversal before extraction.
- Imports use private staging and collision suffixes instead of deleting or
  overwriting existing projects.

### Sidecar protocol

`engine/bridge_service.py` adds:

- `project.inspectImport`
- `project.import`

The project response now also supplies confirmed `targetLanguageId`,
`targetLanguageDirection`, `projectName`, and `bibleName`.

Greek Room now receives the confirmed language identifier from
`manifest.target_language.id`, rather than the display-language name. Local QA
already gets its language context from the manifest via `PluginRegistry`.

USFM verse bridges/segments such as `3-4` and `3a` no longer crash local finding
conversion. Findings use the first numeric component as their numeric anchor,
while project navigation retains the exact verse string.

### Tauri and frontend

The Tauri layer adds:

- Native import-file picker with USFM/SFM/TXT/TCORE/TSTUDIO/ZIP filters.
- Thin commands for inspection and import.
- A five-minute sidecar timeout only for whole-Bible import; ordinary calls
  retain the 30-second timeout.

`src/lib/components/ImportScreen.svelte` now provides:

- Separate file import, folder import, and open-existing-project actions.
- Read-only preview before import.
- Detected-book list, verse counts, alignment status, and warnings.
- Required Language, Project name, Bible/translation name, and text direction.
- Offline searchable ISO 639-3 catalog using `iso-639-3@3.0.1`.
- Import is disabled until the required metadata is valid.

The complete catalog adds about 94 KB gzip to the production bundle and causes
Vite's non-fatal 500 KB chunk warning. It can be split later if startup size
becomes a concern.

## Critical design boundary: tN/tW are not fabricated

Raw USFM contains Scripture, not translationNotes or translationWords checks.
translationCore first imports Scripture and later materializes tool indexes from
installed, versioned checking resources. Bridge follows that boundary.

Current behavior:

- Imported existing translationCore projects immediately expose any real tN/tW
  indexes they already contain.
- Raw imports record `requires-resource-index` for translationNotes and
  translationWords.
- Compatible index directories are created, but no fake/empty check entries are
  generated.
- Local Scripture QA, Greek Room, and word-alignment preparation work now.

The next developer should not mark raw-import tN/tW as complete until resource
download/version selection and real index materialization are implemented.

## Recommended next work

### P0 — Resource acquisition and tN/tW index materialization

1. Define application-owned resource storage. Existing
   `TranslationHelpsKnowledgeBase` expects resources relative to the tC root,
   under `resources/en/translationHelps` and `resources/en/bibles`.
2. Add resource discovery/download with explicit versions and provenance.
3. Pin selected resource versions in the project manifest using the existing
   `tc_*_check_version_*` fields consumed by `knowledge_base.py`.
4. Materialize translationCore-compatible entries at:
   `.apps/translationCore/index/{translationNotes|translationWords}/<book>/<group>.json`.
5. Each entry must include a real `contextId` with `reference`, `tool`,
   `groupId`, and `checkId`, plus the resource evidence needed by the current
   `TranslationCoreProject.checks_for_verse()` and knowledge-base paths.
6. Add import progress and failure recovery. Never report tN/tW as available
   when resource indexing failed or is incomplete.
7. Add fixture-based tests using a small real TN/TW resource slice.

Acceptance criteria:

- A raw USFM import followed by resource preparation produces non-zero real
  tN/tW checks for known verses.
- `verse.runChecks` returns those items as translation-note/translation-word
  findings.
- Resource versions and hashes are visible in provenance.
- Re-running indexing is deterministic and does not erase human decisions.

### P0 — Multi-book collection navigation (done 2026-08-20)

`TopBar.svelte`'s book `<select>` was previously a dead placeholder — one
hardcoded option, no `on:change`. It now lists every sibling from
`ProjectInfo.importedProjects` and calls `project.open` on selection.

Implementation notes for whoever touches this next:

- `project.open` does **not** echo back `importedProjects` (only
  `project.import` does — see `bridge_service.py`'s `_project_info()` vs
  `import_project()`). The sibling list is therefore carried forward on the
  frontend across a switch (`App.svelte`'s `switchBook()`) rather than
  re-fetched from the backend. If the app is closed and reopened, or a book is
  opened individually via "Open an existing project," the sibling list is
  gone and the selector falls back to showing just that one book — this is
  accepted as in-session-only, matching the P0 scope (switching immediately
  after import).
- `stores.ts` gained `resetBookState()`, called before switching: chapter and
  verse numbers restart at 1 in every book, so `chapterVerseNums`,
  `verseTexts`, `findingsByVerse`, and `loadedChapters` must be cleared on
  switch or the new book would show the old book's data under matching
  chapter/verse keys — the same class of bug gotcha #7 was written to avoid,
  just at the book level instead of the chapter level.
- `App.svelte` factored the "land on first chapter, load it, select first
  verse" sequence out of `handleOpened()` into `enterCurrentProject()`, shared
  by both initial open and `switchBook()`.
- Verified: `npm run check` (0 errors), `npm run build` (succeeds, same
  pre-existing chunk-size warning as before). Not exercised in a running
  Tauri window in this session — no sidecar binary was built/available to
  launch `npm run tauri dev` end-to-end. Whoever picks this up next should
  do a real click-through (import a multi-book folder, switch between books,
  confirm chapter/verse state doesn't bleed across books) before treating
  this as fully verified.

### P1 — Full USFM parser and lossless editing/export

The current parser is conservative and the original source is always preserved,
but normalized extraction uses regular expressions. Replace or augment it with
a maintained USFM parser for full marker placement, verse bridges/segments,
nested milestones, tables, peripheral material, and project validation.

Do not remove source preservation. The existing `export.nonAligned` remains a
simplified reconstruction and is not a lossless USFM round trip.

### P1 — Direct Paratext import

Local Paratext folders are detected and `Settings.xml` is used for metadata.
Direct Scripture retrieval from Paratext/API is not wired. Keep that separate
from the existing note connector and require explicit project selection.

### P1 — Import reporting and recovery

Add an import-results screen showing all created project paths, warnings,
unaligned milestone counts, resource-index status, and a way to open any book.
For a multi-book failure, either make the whole collection atomic or clearly
report which book projects completed.

## Verification completed

From `engine/`:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
python -m pytest tests/ greek_room_engine/tests/ -q -p no:cacheprovider
Remove-Item Env:PYTHONDONTWRITEBYTECODE
```

Result: `32 passed`.

From the repository root:

```powershell
npm run check
npm run build
```

Results:

- Svelte check: 0 errors and 0 warnings.
- Production build: successful, with only the language-catalog chunk-size
  warning described above.

From `src-tauri/`:

```powershell
cargo check
```

Result: successful.

`git diff --check` also passes; only Windows LF-to-CRLF notices are printed.

`npm install` reports seven dependency advisories (six moderate and one high).
No automatic `npm audit fix --force` was run because it can introduce breaking
dependency changes. Audit and upgrade these separately.

## Tests added

`engine/tests/test_project_import.py` covers:

- Read-only USFM preview and missing-language detection.
- Raw SFM normalization and provenance.
- Multi-book folder import.
- Basic USFM 3 alignment preservation.
- Existing tC archive check-index preservation.
- ZIP path-traversal rejection.
- End-to-end sidecar import and automatic project opening.
- Verse-bridge import and checking.

## Upstream translationCore research

The implementation was compared against:

- https://github.com/unfoldingWord/translationCore/blob/develop/src/js/actions/Import/LocalImportWorkflowActions.js
- https://github.com/unfoldingWord/translationCore/blob/develop/src/js/helpers/FileConversionHelpers/UsfmFileConversionHelpers.js
- https://github.com/unfoldingWord/translationCore/blob/develop/src/js/helpers/FileConversionHelpers/ZipFileConversionHelpers.js
- https://github.com/unfoldingWord/translationCore/blob/develop/src/js/helpers/manifestHelpers.js
- https://github.com/unfoldingWord/translationCore/blob/develop/src/js/helpers/ProjectValidation/ProjectStructureValidationHelpers.js

Key upstream behavior confirmed:

- tC accepts USFM/SFM/TXT and TCORE/TSTUDIO files through its local file picker.
- USFM import generates a manifest, copies the source, and creates target chapter
  JSON.
- Alignment data is created when alignment milestones are present.
- Missing project/language details are handled during validation.
- Upstream translationCore rejects multiple-book projects; Bridge deliberately
  imports them as a collection of book-wise projects instead.

## Working-tree warning (historical — now committed as `9ed60cb`)

At the time this document was originally written the working tree was uncommitted;
it has since been committed. Files involved in this import work were:

- `engine/tc_ai_bridge/project_import.py` (new)
- `engine/tests/test_project_import.py` (new)
- `engine/bridge_service.py`
- `src/lib/components/ImportScreen.svelte`
- `src/lib/api/bridgeClient.ts`
- `src/lib/types/finding.ts`
- `src-tauri/src/commands.rs`
- `src-tauri/src/main.rs`
- `src-tauri/src/sidecar.rs`
- `package.json`
- `package-lock.json`
- `docs/IMPORTS.md` (new)
- `README.md`

`src-tauri/Cargo.toml` and `vite.config.ts` were also modified in the broader
working session and are part of the same commit.

