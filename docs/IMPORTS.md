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
  invalidations, comments, and alignment state.
- Raw USFM/SFM imports create compatible index roots and record
  `requires-resource-index`; they do not fabricate empty check records.
- Resource acquisition/version selection and tN/tW index materialization are the
  next pipeline stage. Until it runs, local Scripture QA and alignment preparation
  work, but tN/tW results are not claimed as available.

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

