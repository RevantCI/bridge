# Scripture import design

Bridge imports Scripture into a translationCore-compatible, book-wise project
model. The original source is preserved; normalization creates derived data for
the editor, QA, checking resources, and word alignment.

## Supported inputs

- A `.usfm` or `.sfm` file.
- A marker-based `.txt` Scripture file.
- A folder containing one or many USFM/SFM books.
- A Paratext project folder containing `Settings.xml` and Scripture files.
- An existing translationCore project folder.
- A `.tcore`, `.tstudio`, or ZIP project archive containing a project manifest.

The preview is read-only. It lists detected books, verse counts, alignment
availability, inferred metadata, and warnings before the user approves an
import. Imported projects are written to application-owned storage. Name
collisions create a new suffixed project rather than overwriting an existing
one.

## Project Home, identity, and duplicate safety

Bridge keeps an atomic `project-registry.json` beside application settings and
discovers older projects already present in its managed `projects` directory.
Each managed project also receives `.bridge/project.json` with a stable UUID.
The Project Home lists recent projects (one card per multi-book collection), keeps missing entries visible, and lets
the user locate a moved folder or forget the registry entry. Forget never
deletes project files.

Import preview fingerprints every approved source book and compares it with the
registry. An exact existing import defaults to **Open existing project**. A new
copy is possible only through the explicit **Import as a separate copy** action;
Bridge does not silently merge or overwrite projects. A matching book/language/
Bible identity without an exact source hash is shown as a possible overlap for
human review.

Native file/folder drag-and-drop uses the same read-only preview and duplicate
decision flow as the pickers, including when another project is already open.
Managed-library discovery is cached for duplicate classification and does not
rehash every project's Scripture tree on each preview. Large-folder inspection
has a separate bounded desktop timeout from ordinary interactive commands.

## Normalized project data

For a single-book import and the first book of a collection, Bridge creates or
preserves immediately:

```text
<project>/
  manifest.json
  <book>.usfm                         original source bytes
  <book>/
    headers.json
    <chapter>.json                    verse-keyed target Scripture
  .apps/translationCore/
    alignmentData/<book>/<chapter>.json
    index/translationNotes/<book>/
    index/translationWords/<book>/
    checkData/...
  .bridge/import.json                 provenance and capability status
```

For a multi-book collection, every remaining source file is copied immediately
into its own lightweight project directory with `.bridge/lazy-import.json`.
That book is normalized into the structure above the first time the user opens
it. `.bridge/collection.json` in every sibling stores a stable collection UUID
and sibling directory names (not machine-specific absolute paths), restoring
the complete book list after restart or after the collection is moved. This keeps the approved source self-contained while
avoiding tens of thousands of synchronous JSON writes before the editor opens.

Every target token begins in `wordBank` unless a supported USFM 3 alignment
milestone assigns it to a `bottomWords` group. Source milestone attributes are
mapped to translationCore `topWords` fields. Nested `zaln`/`w` milestones are
combined into 1:1, 1:many, many:1 or many:many translationCore groups by their
shared target tokens. Malformed milestones are preserved in the original source
and left for human review rather than guessed.

`manifest.json` records the confirmed ISO 639-3 language, language name, text
direction, Bible/resource identity, book identity, and import provenance. That
language metadata is immediately used by language-aware local and Greek Room
checks.

## TranslationNotes and translationWords

Raw Scripture does not itself contain translationNotes or translationWords
checks. translationCore creates those tool indexes from separately installed,
versioned checking resources. Bridge follows the same boundary:

- Existing translationCore projects retain their real tN/tW indexes, selections,
  invalidations, comments, and alignment state — Bridge never overwrites them.
- Raw USFM/SFM/Paratext imports get real tN/tW indexes materialized from a
  pinned English (unfoldingWord, Door43 tag v90) tN/translationWordsLinks
  snapshot bundled with the app (`engine/resources/en/translationHelps/`),
  parsed into `.apps/translationCore/index/{translationNotes|translationWords}/<book>/<group>.json`
  when background checking begins for that book. tN/tW are gateway-language
  checking helps applied to any target-language translation, so this runs
  regardless of the imported project's own target language and does not block
  entry into the editor.
- A handful of Old Testament books (Numbers, 1-2 Chronicles, Ecclesiastes,
  Isaiah, Jeremiah, Ezekiel, Daniel, Amos, Zechariah) are not currently
  released in the upstream English resource; those report capability
  `unavailable` rather than a fabricated `ready` with zero checks. See
  `docs/DEVELOPER_HANDOFF.md` for the full list and how to refresh the bundle.
- Only English is bundled today. A future non-English or refreshed-English
  resource still needs the online Door43-catalog path, not yet built.

## Export behavior

- Aligned export writes USFM 3 with occurrence-aware `\zaln-s … \zaln-e\*`
  and `\w … \w*` milestones. It preserves the imported source file's headings,
  poetry, footnotes, cross-references, and custom markers as the structural
  template while replacing verse payloads with the current project text.
- Non-aligned export uses the same source-preserving template without alignment
  milestones.
- If a legacy project has no retained source USFM, both exporters say that they
  used the simplified `\id`/`\c`/`\v` fallback.
- An aligned verse must contain the exact current target-token inventory.
  Duplicate, missing, target-only, or non-contiguous target groups fail clearly
  instead of producing ambiguous alignment markup.

## Differences from translationCore

The implementation follows translationCore's sequence—detect, convert, validate,
collect missing metadata, migrate, and open—but improves the import experience:

- Multi-book folders are accepted and become a collection of compatible
  book-wise projects; translationCore's validator rejects multi-book projects.
- Whole-Bible imports copy all approved sources but eagerly normalize only the
  first book; other books are normalized on first open. A real 66-book,
  12.6 MB project measured 5.17 seconds from source and 6.21 seconds through
  the frozen packaged sidecar on the 2026-08-21 Windows test machine.
- The source is previewed before writes and the metadata is reviewed in one form.
- The language picker uses the complete offline ISO 639-3 catalog instead of
  requiring users to type both language code and name correctly.
- Imports use private staging, safe ZIP path validation, source SHA-256 provenance,
  and non-overwriting destination names.
- One failed import does not clear a shared global imports directory.

Relevant upstream implementation:

- [Local import workflow](https://github.com/unfoldingWord/translationCore/blob/develop/src/js/actions/Import/LocalImportWorkflowActions.js)
- [USFM conversion](https://github.com/unfoldingWord/translationCore/blob/develop/src/js/helpers/FileConversionHelpers/UsfmFileConversionHelpers.js)
- [Archive conversion](https://github.com/unfoldingWord/translationCore/blob/develop/src/js/helpers/FileConversionHelpers/ZipFileConversionHelpers.js)
- [Manifest generation](https://github.com/unfoldingWord/translationCore/blob/develop/src/js/helpers/manifestHelpers.js)
- [Project structure validation](https://github.com/unfoldingWord/translationCore/blob/develop/src/js/helpers/ProjectValidation/ProjectStructureValidationHelpers.js)

