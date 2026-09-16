# Bridge 0.11.0

Bridge 0.11.0 is a feature release on 0.10.3. It adds the **Cross-verse alignment
page** — a side-by-side view of several verses of a chapter where a source word can be
aligned within its verse as before, or recorded as *realized in another verse* — and
teaches the passage-aware QA pipeline to read those records as evidence. It also
completes the protocol simplification started in 0.10.3.

**One on-disk change to know about:** the per-project `bridge-workbench.sqlite3` moves
from schema v2 to v3 the first time 0.11.0 opens a project. The migration is automatic
and keeps a `backups/pre-workbench-v3-*` copy, but it is one-way: **0.10.x cannot open a
project that 0.11.0 has opened.** Nothing else on disk changes shape; the semantic
database stays at v16, the app-level workspace database at v2, and translationCore's own
`alignmentData/` is never written by the new feature.

## Cross-verse alignment (#116, #117, #118, #119)

translationCore alignment groups are verse-local, and Bridge never fakes a cross-verse
link inside them. Until now that meant a word realized in the next verse looked like an
omission here and an addition there, with nothing showing the two together.

- **The page** (#116). Open it from the editor toolbar ("Cross-verse alignment", beside
  "Alignment Review") or from the link inside Align Words. A range picker (from/to plus
  per-verse chips, default the selected verse ±1) drives two vertically scrolling columns:
  source tokens with lemma, lexicon tooltip and popup on the left, each verse's word bank
  on the right, and a gap overview across the top that filters both columns to one verse's
  gaps. Dragging a word onto a source cell of its own verse aligns it exactly as Align
  Words does and reruns that verse's local checks. No horizontal scrolling.
- **Cross-verse links** (#117). Dragging a word onto a source cell of *another* verse
  records a Bridge-private link in the workbench database, keyed by the two words'
  translationCore token signatures plus their verses. The source cell shows "realized in
  v.N", the word stays in its own verse's bank marked "↔ v.N", either side's × removes
  the link, and a text edit that removes the linked word marks the link invalid with the
  reason. A verse whose only remaining gaps are linked drops the "not fully aligned" flag
  and shows how many words are linked across verses. translationCore's own status
  (`partial` / `untouched`, `pending`) is unchanged on purpose: aligned USFM cannot
  express the link, so completion stays with translationCore. Links are refused when
  either word is already aligned within its own verse, or when both are in the same verse.
- **Finding the range** (#118). The page widens its default range with the verses the
  last chapter analysis marked as cross-verse realization, and says so. "Cross-verse
  alignment" is offered on possible-omission and possible-addition findings, in the QA
  queue's row menu and in the finding pane, opening the page on the finding's verses
  (switching chapter first if needed). In the verse list, Ctrl-click and Shift-click
  build a multi-selection that the toolbar button opens directly.
- **The pipeline reads the links** (#119). Stage 6B now treats an active cross-verse link
  as word-alignment evidence at the same weight as completed same-verse alignment, and a
  link change re-analyses what depended on it, so a passage a team has linked across
  verses raises fewer false omission and addition findings. No weight or threshold was
  tuned; the Stage 6B golden did not move. One measured limitation is recorded as #123.

## Protocol simplification (#115)

Every engine call now goes through one generic `engine_call` command; the 86 Rust
forwarders are gone and adding a protocol method is an engine handler plus one TypeScript
line. Verified in the app by the cross-verse work above, which exercised alignment,
lexicon, analysis-job and QA-review calls through it.

## Filed, not fixed

- **#122** — in Align Words, pressing "Undo last change" twice re-applies the change,
  because each undo restores the latest backup and writes a new one. Pre-existing.
- **#123** — a cross-verse link can tie with the split pseudo-span that pairs the linked
  word with its neighbour, leaving the relationship AMBIGUOUS instead of LOCATED.

## Unchanged

The correction ledger, both goldens, the confidence thresholds, the semantic database
schema (v16), the workspace database (v2), aligned USFM export and translationCore's
completion state are all as in 0.10.3. Offline operation is unchanged.

## Verification

Per issue: `npm run check` 0/0, `npm run test` (33 files, 419 tests at #118),
`npm run build`; `pytest -n auto -m "not slow"` (1030 passed at #119) plus the touched
test files and the Stage 6B golden by name; a real-app check at 1366×768 for #116, #117
and #118 with real pointer drags, recorded step by step in `docs/BUILD_LOG.md`
(2026-09-16 entries).
