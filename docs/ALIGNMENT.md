# Manual word alignment

Bridge v0.8.0-beta.13 provides a human-controlled, translationCore-compatible
word-alignment editor. For raw Scripture imports it initializes source slots
from pinned, bundled UHB/UGNT token packs; it never guesses tokens and never
changes Scripture text as a side effect of alignment work.

## Data and protocol

The source of truth remains:

```text
.apps/translationCore/alignmentData/<book>/<chapter>.json
```

Each token keeps its `word`, `occurrence`, and `occurrences` identity. Source
tokens also retain Strong's, lemma, and morphology attributes when available.
The sidecar exposes:

- `alignment.get` and `alignment.status`
- `alignment.realign`, `alignment.unalign`, and `alignment.save`
- `alignment.complete`
- `alignment.undo`, `alignment.backups`, and `alignment.restore`

`realign` supports 1:1, 1:many, many:1, and many:many groups. Every save must
contain exactly the token identities loaded by the editor. The
`expectedOriginal` snapshot provides optimistic concurrency: if another process
or editor changed the verse on disk, the stale save is rejected.

## Safety and history

Approved changes are atomic and journaled. Before changing a chapter, Bridge
creates a backup and records per-verse history under:

```text
.apps/translationCoreAI/alignmentHistory/<book>/<chapter>/<verse>/
```

History and chapter data are committed in the same transaction. Undo restores
only the selected verse from its backup, so unrelated verses in the chapter are
not rolled back. Completion uses translationCore's native word-alignment state
files and survives an application restart. Editing Scripture reconciles the
target tokens and marks the alignment invalid for review.

## Completion and status

Verse status is `untouched`, `partial`, `complete`, or `invalid`. The editor and
chapter toolbar expose these states. Completion is blocked when:

- original-language tokens are absent;
- a source or target token remains unaligned;
- a token is missing, duplicated, or no longer matches the target text;
- a target group is non-contiguous and cannot be represented safely in aligned
  USFM.

After every alignment mutation the UI immediately reruns local and Greek Room
checks for that verse.

## Aligned USFM

Aligned export writes USFM 3 and uses unfoldingWord's occurrence-aware `zaln`
and `w` user-extension convention. Nested source milestones represent
many-to-many relationships. The serializer preserves punctuation, inline
markers, footnotes, cross-references, headings, poetry, and custom markers by
using the retained imported USFM as its structural template.

USFM permits user-defined `z` markers and attributes; see the official
[USFM character attributes documentation](https://docs.usfm.bible/usfm/3.1.2/char/attributes.html).
`zaln` is an unfoldingWord interoperability convention layered on that extension
mechanism, not a native semantic alignment feature defined by the USFM standard.

## Bundled original-language source

Raw OT and NT imports receive blank source alignment groups from unfoldingWord
UHB v3.0.0 and UGNT v0.34 respectively. The packs preserve word, occurrence,
Strong's, lemma, and morphology fields using translationCore's pinned
`usfm-js`/`word-aligner` conversion path. Footnotes are excluded from the verse
body, so a Hebrew Ketiv in the body is retained while its Qere footnote is not
treated as a second alignable source token. Verse bridges combine canonical
verses and recalculate occurrence identities across the result.

This initialization is deliberately one-way and conservative:

- aligned USFM and native translationCore source groups remain authoritative;
- recovery fills only an exactly empty `alignments` array in a known Bridge raw
  import and leaves every non-empty verse unchanged;
- a project stamped with a different source-resource version/commit is not
  silently migrated;
- every pack is SHA-256 checked before use, and resource version, commit,
  attribution, license, and provenance are visible in Settings.

The exact upstream commits, file hashes, conversion dependencies, license, and
change statement are recorded beside each resource in
`engine/resources/{hbo,el-x-koine}/...`. Regenerate them only with
`npm run vendor:original-language -- --uhb <checkout> --ugnt <checkout>`;
the generator rejects checkouts that are not the pinned commits.

Optional AI gap-fill proposals remain human-triggered. Live original-language
downloads and live Paratext/Logos synchronization remain future work.
