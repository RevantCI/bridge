# Manual word alignment

Bridge provides a human-controlled, translationCore-compatible
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

## Cross-verse links (Bridge-private, #117)

translationCore alignment groups are verse-local: each verse's groups may only
contain that verse's own target tokens, and `_validate_alignment_identity`
enforces it on every save by comparing the token multisets before and after.
Bridge never fakes a cross-verse link inside them (`semantic_alignment_guard.py`,
`INVARIANTS.md` §39). A reviewer's judgement that a source token of one verse is
realized in another verse's target text is therefore recorded outside
`alignmentData/`, in `alignment_cross_verse_links` in the per-project
`bridge-workbench.sqlite3` (schema v3).

```text
alignment.getRange(chapter, verses[])    one context per verse, plus per-verse gap counts
alignment.crossVerse.link                {source: {chapter, verse, topId}, target: {chapter, verse, bottomId}}
alignment.crossVerse.unlink              {linkId}
```

- A link is keyed by the two translationCore **token signatures**
  (`word`, `occurrence`, `occurrences`) plus chapter and verse on both sides.
  The positional `H001`/`T001` ids are resolved per request and never stored:
  `make_inventory` regenerates them on every load.
- It is refused when either token is already aligned inside its own verse, when
  both ends are the same verse (that is `alignment.realign`), or when the target
  word is not in the current text.
- Each change writes three things: the row, a `change_log` domain event
  (`crossVerseLink` / `crossVerseUnlink` / `crossVerseInvalidate`), and an
  `alignment_history` row with **no** `backupPath` — nothing on disk changed, so
  it is in the history but never offered for restore.
- **Status:** a verse's alignment context reports `crossVerseLinks`,
  `crossVerseAccountedIds`, `crossVerseRealizedIds`, counts and `fullyAccounted`,
  and its `gaps` are net of active links. `status` and `completionState` are
  unchanged and keep telling the translationCore truth: a fully-accounted verse
  still reads `partial` or `untouched` and `pending`, and `canComplete` stays
  false, because aligned USFM cannot express the link.
- A target edit that removes a linked word marks the link `invalid` with a
  reason, inside the same journal transaction as the edit, rather than deleting
  it.
- Stage 6B reads active links as `WORD_ALIGNMENT` location evidence at the same
  weight as completed same-verse alignment, and a link change stales the
  downstream Stage 6B/7/8 records (#119).

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
