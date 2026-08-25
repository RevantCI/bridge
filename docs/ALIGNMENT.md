# Manual word alignment

Bridge v0.8.0-beta.4 provides a human-controlled, translationCore-compatible
word-alignment editor. It never invents original-language tokens and never
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

## Deliberate release boundary

Manual alignment requires source `topWords` already present in an imported
translationCore project or aligned USFM. This release gives actionable guidance
when they are unavailable. Optional AI gap-fill proposals are available in the
editor, and corpus statistics are available through the backend protocol.
Downloading original-language resources and live Paratext/Logos synchronization
remain future work.
