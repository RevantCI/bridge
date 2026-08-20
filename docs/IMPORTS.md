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

## Normalized project data

For each book, Bridge creates or preserves:

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

Every target token begins in `wordBank` unless a supported USFM 3 alignment
milestone assigns it to a `bottomWords` group. Source milestone attributes are
mapped to translationCore `topWords` fields. Nested or malformed milestones are
preserved in the original file but deliberately left unaligned for human review
rather than guessed.

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
  at import time. tN/tW are gateway-language checking helps applied to any
  target-language translation, so this runs regardless of the imported
  project's own target language.
- A handful of Old Testament books (Numbers, 1-2 Chronicles, Ecclesiastes,
  Isaiah, Jeremiah, Ezekiel, Daniel, Amos, Zechariah) are not currently
  released in the upstream English resource; those report capability
  `unavailable` rather than a fabricated `ready` with zero checks. See
  `docs/DEVELOPER_HANDOFF.md` for the full list and how to refresh the bundle.
- Only English is bundled today. A future non-English or refreshed-English
  resource still needs the online Door43-catalog path, not yet built.

## Differences from translationCore

The implementation follows translationCore's sequence—detect, convert, validate,
collect missing metadata, migrate, and open—but improves the import experience:

- Multi-book folders are accepted and become a collection of compatible
  book-wise projects; translationCore's validator rejects multi-book projects.
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

