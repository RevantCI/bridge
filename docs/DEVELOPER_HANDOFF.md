# Developer handoff: Scripture import pipeline

Date: 2026-08-20

## Objective

Continue building Bridge's import workflow so users can bring in individual
USFM/SFM files, whole-Bible folders, Paratext folders, and translationCore
projects, then use the normalized data for local QA, Greek Room,
translationNotes, translationWords, and word alignment.

The import foundation described below is implemented and verified but is not
committed. Do not reset the working tree; it also contains earlier project
changes.

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

### P0 — Multi-book collection navigation

All books are imported, but the current editor opens only the first one. Add a
book/project selector using the returned `importedProjects` paths. Switching
books should call `project.open`, reset book-scoped frontend stores safely, and
start that book's background chapter checks.

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

## Working-tree warning

The current working tree is uncommitted. Files involved in this import work are:

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

`src-tauri/Cargo.toml` and `vite.config.ts` were already modified in the broader
working session and should not be reset casually. Review the complete diff and
preserve unrelated or earlier changes before committing.

