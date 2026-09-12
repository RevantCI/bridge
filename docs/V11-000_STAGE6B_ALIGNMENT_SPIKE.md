# V11-000 / #54 — research spike: Stage 6B and completed Word Alignment

Read-only investigation against `d354b23` (`origin/main`). No code changed.
Every claim below carries a `file:line` citation; anything inferred rather
than read is marked **[inferred]**.

Two parts: **Part A** is the spike finding (suitable as a comment on #54),
**Part B** is the implementation prompt for the code agent.

---

# Part A — findings

## A0. The issue's premise is right, but its count is off by one

#54 lists four scoring paths and concludes "completed human-approved
alignment contributes no input to location." The conclusion holds. The count
does not: `_score_candidate` blends **seven** components
(`engine/tc_ai_bridge/semantic_location.py:276-288`), and one of them is
already a human channel:

```python
components = [
    (LocationEvidenceKind.SEMANTIC_SIMILARITY, semantic, 0.42, ...),
    (LocationEvidenceKind.LEXICAL,             lexical,   0.38, "bridge-lexical-v1"),
    (LocationEvidenceKind.CONCEPT,             concept,   0.15, "target-unit-kind-v1"),
    (LocationEvidenceKind.MORPHOLOGY,          morphology,0.12, "target-analyzer-v1"),
    (LocationEvidenceKind.STRUCTURAL_PROXIMITY,structural,0.05, ...),
    (LocationEvidenceKind.HUMAN_PRECEDENT,     human,     0.65, "project-local-human-v1"),
    (LocationEvidenceKind.EXACT_SPAN,          1.0,       0.01, "exact-current-span-v1"),
]
raw = min(1.0, sum(value * weight for _, value, weight, _ in components))
```

`human` is set at `semantic_location.py:267-274` from `precedents`, sourced at
`:596` via `repository.human_approved_lexical_precedents(project_id)`, which
reads (`passage_semantic_repository.py:3248-3257`):

```sql
SELECT g.payload_json FROM lexical_groups g
JOIN lexical_solutions s ON s.id=g.solution_id
WHERE s.project_id=? AND s.lifecycle_status='ACTIVE'
  AND g.lifecycle_status='ACTIVE' AND g.review_status='HUMAN_APPROVED'
```

Matching is on `sourceTokenInstanceIds` ∩ `targetTokenInstanceIds`
(`semantic_location.py:270-274`) — a set-intersection, binary 0.0/1.0.

**This reframes #54.** The architectural hole is not "Stage 6B has no human
evidence channel." It is "the existing human evidence channel is fed only by
Bridge's own `lexical_groups`, never by translationCore's `alignmentData`."
That is a narrower, better-shaped problem than "invest in automated
cross-language location."

## A1. The weights already work. No re-tuning is needed.

Thresholds (`semantic_location.py:52-60`): `located_minimum = 0.36`,
`credible_minimum = 0.20`, `ambiguity_margin = 0.07`. Outcome logic at
`:357-368`; a pre-retention prune at `:639` drops anything below
`credible_minimum / 2` = 0.10.

Arithmetic for the #54 repro (Greek `οὐ` → Tamil `தெரியாது`, disjoint
scripts, no embedding provider configured):

| component | value | weight | contribution |
|---|---|---|---|
| SEMANTIC_SIMILARITY | 0.0 — no provider bundled (`HANDOFF.md` §31) | 0.42 | 0.00 |
| LEXICAL | 0.0 — set overlap of disjoint scripts (`:173-183`) | 0.38 | 0.00 |
| CONCEPT | 0.95 *only if* Stage 6A independently tagged a target NEGATION unit (`:186-194`) | 0.15 | 0.1425 |
| MORPHOLOGY | 0.0 | 0.12 | 0.00 |
| STRUCTURAL_PROXIMITY | 0.8 when canonical refs intersect (`:196-200`) | 0.05 | 0.04 |
| HUMAN_PRECEDENT | 0.0 | 0.65 | 0.00 |
| EXACT_SPAN | 1.0, hardcoded | 0.01 | 0.01 |

- Best case, 6A *did* classify the negation: **0.1925** — below
  `credible_minimum` 0.20 by 0.0075. NOT_LOCATED.
- Typical case, 6A did not: **0.05** — below the 0.10 prune at `:639`, so no
  candidate is even retained.

Now add alignment-derived human evidence at value 1.0:

- **0.65 + 0.04 + 0.01 = 0.70** ≥ `located_minimum` 0.36 ✔
- margin over the next candidate (≤ 0.19) = ≥ 0.51 ≥ `ambiguity_margin` 0.07 ✔
- → **LOCATED**, Stage 7 runs, Cases A–D unblock.

The 0.65 weight was evidently chosen so a human decision dominates. Feeding
alignment into the same channel inherits that property for free. **Do not
touch the thresholds or weights.**

## A2. Scope correction: this fixes cross-*script*, not cross-*verse*

#54's title says "cross-language location," and the two failure shapes have
been running together:

- **Same-verse, cross-script** (PHP 1:22 `οὐ` → `தெரியாது`) — the actual #54
  repro. tC alignment is verse-local
  (`semantic_alignment_guard.py:1-8`), so it can express exactly this link.
  **Consulting alignment solves it.**
- **Cross-verse** (Case C: source PHP 1:3 → target PHP 1:6) — tC alignment
  *structurally cannot* represent this. **Consulting alignment does not
  solve it**; that genuinely needs the embedding-provider direction.

Worth splitting #54 so the tractable half isn't held hostage to the
research-scale half.

## A3. Source IDs are derivable. Target IDs are not.

**Source — deterministic, one lookup.** `source-token-*` hashes
(`source_semantic_inventory.py:185-200`) resource id/version/provenance hash,
book, `"BOOK ch:v"`, in-verse `index`, `occurrence`, layer, then
`word`/`lemma`/`strong`/`morph` + `SOURCE_TOKENIZATION_VERSION`. A tC
`topWord` carries `word`, `occurrence`, `occurrences`, `strong`, `lemma`,
`morph` (`models.py:10-60`) — everything except `index`, which is recovered
by looking the token up in `source_tokens_for_verse(...)` on `(word,
occurrence)`.

That join is sound **by construction**: the vendored token pack was generated
by translationCore's own aligner —
`scripts/vendor-original-language-resources.mjs:108-109` calls
`aligner.generateBlankAlignments(verseData)` and keeps `word, occurrence,
occurrences, strong, lemma, morph`. Same strings, same occurrence
convention, both sides.

**Target — not derivable.** `target-token-*` hashes `projectId`, book,
displayed reference, **`text_revision`**, tokenizer profile, **in-verse
`index`**, and the **raw** surface form
(`passage_semantic_runtime.py:840-846`). A `bottomWord` carries only `word`,
`occurrence`, `occurrences`. So `text_revision` and `index` must come from
re-tokenizing the *current* verse — and the two tokenizations disagree:

- tC `bottomWords`: whitespace split, edge punctuation trimmed
  (`usfm.py:20-32`, `project_import.py:138-152`).
- Bridge `bridge-unicode-word-v1`: Unicode-word regex, **punctuation emitted
  as its own token**, occurrence counted per NFC form
  (`passage_semantic_runtime.py:471-500`).

They agree for ordinary space-separated alphabetic words. They diverge on
`3:16` (one whitespace token, three Bridge tokens), on inline
brackets/quotes, and anywhere tC split at a hyphen or apostrophe that
Bridge's regex keeps *inside* a word. The other profile, `tc-whitespace-v1`
(`\S+`), is worse: it keeps punctuation attached, so `"தேவன்,"` never
string-matches the `bottomWord` `"தேவன்"`.

**Consequence:** a tC→Bridge target mapping is a **candidate bound to one
`text_revision`**, never an identity function. There is a house precedent for
exactly this policy —
`semantic_alignment_guard.alignment_top_ids_for_canonical_tokens`
(`:42-82`): exact NFC word + occurrence first, `lemma`/`strong`/`morph` as
reinforcement, and **ambiguity returned as `unresolved` rather than resolved
by ordinal**. Copy that policy.

No conversion code exists today. Grepping the two ID prefixes returns only
the two mint sites (`source_semantic_inventory.py:197`,
`passage_semantic_runtime.py:846`).

## A4. Nothing tells the semantic pipeline that an alignment changed

Verified absence, and the largest piece of real work in this issue:

- Every alignment mutation funnels through
  `BridgeService._finish_alignment_mutation` (`bridge_service.py:1669-1687`).
  Its entire invalidation footprint is two in-memory dict pops
  (`_corpus_stats_by_book`, `_consistency_findings_by_book`). No companion-DB
  write, no call into `passage_semantic_runtime`.
- The semantic staleness boundary is the **target text hash only**
  (`passage_semantic_runtime.synchronize_current_text`, `:561-601`).
  Regrouping an alignment changes no target byte, so it never fires.
- `RECORD_DEPENDENCY_ANCHOR_TYPES` has exactly two members —
  `{"TARGET_REFERENCE", "SOURCE_RESOURCE"}`
  (`passage_semantic_repository.py:85-91`). There is no alignment anchor.
- Alignment completion is **filesystem marker existence**, not a hash:
  `tc_project.word_alignment_state` (`:1836-1841`) checks for
  `tools/wordAlignment/completed/<ch>/<v>.json` vs `.../invalid/...`.
- The flow today is one-directional and the *wrong* way: a Scripture edit
  invalidates the alignment (`tc_project.py:2090-2091`), never the reverse.
  `scripts/inspect_correction_application.py:150-152` states this is
  deliberate — *"Semantic verification must never approve or rebuild an
  alignment."* Reading alignment as evidence does not violate that; writing
  to it would.

Without a new invalidation edge, a reviewer completes an alignment and
Stage 6B keeps serving its pre-alignment NOT_LOCATED result as current —
which `CLAUDE.md:213-227` calls out directly: *"A derived value that never
goes stale is worse than no derived value."*

## A5. `alignmentData` is read at startup today, but discarded

`passage_semantic_runtime._scan_native_alignment_compatibility`
(`:1100-1193`, `source_kind="translationCore.alignmentData"`) already walks
every chapter file at runtime attach. But its docstring is explicit —
*"Read-only scan; native tC groups are never imported or repaired here."* It
writes only `migration_runs` / `migration_quarantine` rows, and **no stage
reads them**. `semantic_location.py` contains zero occurrences of "align".

Two things are reusable from it: the directory-wide SHA-256 at `:1102-1110`
(a ready-made alignment content digest), and its four defect classes —
`MALFORMED_LEGACY_ALIGNMENT_FILE`, `LEGACY_EMPTY_BOTTOM_WORDS_AMBIGUOUS`,
`MALFORMED_LEGACY_TOKEN_IDENTITY`, `DUPLICATE_ACTIVE_TOKEN_MEMBERSHIP`.
**Quarantined groups must not become location evidence.**

## A6. Identity obligations, and the V1.1 precedent to copy

`correction_verification.py:421-426` names Stage 6B explicitly: *"a change to
how Stage 6B locates ... changes what this verdict means, so a verification
produced by older logic must not keep presenting itself as current."*

The V1.1 `unicode-comparison-nfc-grapheme-v2` change is the template. It
threaded one constant through four sites and bumped two owning versions.
The analogue here:

| # | change | site |
|---|---|---|
| 1 | `LOCATION_ENGINE_VERSION` v1 → v2 | `semantic_location.py:24` |
| 2 | new `ALIGNMENT_EVIDENCE_VERSION` constant | `semantic_location.py:24-27` |
| 3 | new constant **+ alignment content hash** into the run fingerprint | `semantic_location.py:542-553` |
| 4 | declare both in `policy_versions()` | `analysis_jobs.py:157-190` |
| 5 | add to the verifier fingerprint | `correction_verification.py:428-437` |

Stages 7/8/9A need **no** fingerprint edits — they inherit via
`locationRun`/`locationFingerprint` (`meaning_analysis.py:392-404`) and
`meaningRun`/`meaningFingerprint` (`qa_audit.py:347-352`), and via the
`MEANING_RUN → LOCATION_RUN` / `QA_RUN → MEANING_RUN` dependency edges
(`passage_semantic_repository.py:2872`, `:3016`).

Free bonus: `_same_policy` is exact dict equality
(`analysis_jobs.py:153-155`), and `get_scope_status` (`:549-561`) stales
every job in the project when `policyVersions` changes. Adding a key to
`policy_versions()` therefore auto-stales all existing analysis with no extra
code. That is what made V1.1 safe.

## A7. The gap list

| # | gap | size | blocks |
|---|---|---|---|
| G1 | No tC→Bridge **source** token ID resolver | small — deterministic `(word, occurrence)` lookup | everything |
| G2 | No tC→Bridge **target** token ID resolver; tokenizations disagree | **medium — the real correctness risk** | everything |
| G3 | No projection of alignment groups into the precedent shape | small once G1/G2 land | scoring |
| G4 | No alignment→semantic invalidation anchor, trigger, or crash replay | **medium-large — no precedent for a non-text input** | correctness of any cached result |
| G5 | Alignment completion is marker-file existence, not a content hash | small — reuse the digest at `:1102-1110` | fingerprinting |
| G6 | Quarantined/malformed groups must be excluded from evidence | small — already detected at `:1117-1187` | safety |
| G7 | Cross-verse location still unsolved | **out of scope — needs the provider direction** | Case C only |
| G8 | Stage 6B golden will move | must be its own commit (`CLAUDE.md:300-313`) | merge hygiene |

**Recommended split of #54:** G1–G6 + G8 as an implementable issue
("V11-000a: Stage 6B consults completed Word Alignment, same-verse"); G7
stays on #54 as the research spike it is labelled as.

---

# Part B — prompt for the code agent

> Paste from here down. It assumes a fresh session with the repo checked out
> at `d354b23` or later.

---

You are implementing **V11-000a** in the Bridge repository: make Stage 6B
consult completed translationCore Word Alignment as location evidence, for
same-verse source→target links only.

**Read first, and treat as binding:** `docs/HANDOFF.md` §§6, 20, 21, 30, 31,
39; `CLAUDE.md` (especially the staleness rule ~L213-227, the schema rule
~L229-241, and the golden rule ~L300-313); the module docstring at
`engine/tc_ai_bridge/correction_verification.py:421-426`.

## What is already true (verified — do not re-derive)

1. `_score_candidate` (`engine/tc_ai_bridge/semantic_location.py:276-288`)
   already has a `HUMAN_PRECEDENT` component at weight **0.65**, fed from
   `repository.human_approved_lexical_precedents()` (`:596`,
   `passage_semantic_repository.py:3248-3257`), matched by
   `sourceTokenInstanceIds`/`targetTokenInstanceIds` set-intersection
   (`:267-274`).
2. With `located_minimum = 0.36` and `ambiguity_margin = 0.07` (`:52-60`),
   an alignment-backed candidate scores ≈0.70 against ≤0.19 for the rest —
   comfortably LOCATED. **Do not change any weight or threshold.** If your
   change only works after re-tuning, you have the wrong design; stop and
   report.
3. tC `alignmentData` is already scanned read-only at runtime attach
   (`passage_semantic_runtime._scan_native_alignment_compatibility`,
   `:1100-1193`), producing a directory SHA-256 (`:1102-1110`) and four
   quarantine reason codes. Reuse both; do not duplicate the walk.
4. Nothing currently notifies the semantic pipeline when an alignment
   changes (`bridge_service._finish_alignment_mutation:1669-1687` pops two
   in-memory dicts and nothing else).

## Scope

**In:** same-verse source→target links from tC alignment groups, projected
into Stage 6B as location evidence; the identity and invalidation work that
makes the result honest.

**Out:** cross-verse location (tC alignment cannot express it — that stays on
#54); any embedding provider work; any change that **writes** to
`alignmentData` or to the `tools/wordAlignment/` markers; any weight or
threshold change; a version bump or release.

## Hard constraints

- **Never write to translationCore alignment from the semantic pipeline.**
  Read-only, in this direction, always.
  (`scripts/inspect_correction_application.py:150-152`.)
- **No fuzzy correction matching.** Ambiguous token resolution returns
  `unresolved`; it does not pick by ordinal. Follow
  `semantic_alignment_guard.alignment_top_ids_for_canonical_tokens:42-82`.
- **Scripture is never normalized on disk.** Normalization is for transient
  comparison keys only.
- **Spans stay `[startCodePoint, endCodePoint)` over raw text.**
- **Hash the pinned pack's `word` string, never the tC string** — the
  `source-token-*` hash uses the pack's bytes verbatim, so an NFD-normalized
  tC entry would produce a wrong ID if fed in directly.

## Work items

### 1. Source token resolver
Given `(book, chapter, verse, tC topWord)` → `source-token-*` ID. Look the
token up in `source_tokens_for_verse(...)`
(`original_language_resources.py:215-251`) on exact NFC `word` +
`occurrence`, reinforced by `strong`/`lemma`/`morph`; recover `index`; then
re-derive the ID exactly as `source_semantic_inventory._ensure_token:185-200`
does. Return `unresolved` on miss or ambiguity — never guess.
Handle: five-digit vs legacy Strongs (`G39720` / `G3972`); the
`strong`/`strongs` key alias (already handled in `models.py:10-60`); verse
bridges keyed `"2-3"` with occurrences renumbered across the span
(`original_language_resources.py:245-251`); and resource-version skew, which
must fail closed like `source_semantic_inventory.py:443-445`.

### 2. Target token resolver — the risky one
Given `(displayedReference, tC bottomWord, current verse text)` →
`target-token-*` ID. Tokenize the current verse with
`tokenize_target_text(text, profile)`, match on `(NFC-normalized form,
occurrence)`, take `index` + `raw`, and re-derive per
`passage_semantic_runtime._ensure_target_tokens:840-846`. Prefer resolving
against the existing DB rows for the current `text_revision` over
re-deriving.

The two tokenizations genuinely disagree (tC: whitespace + trimmed edge
punctuation; Bridge `bridge-unicode-word-v1`: Unicode-word regex with
punctuation as separate tokens, `passage_semantic_runtime.py:471-500`).
**Every mapping is a candidate bound to one `text_revision`, not an
identity.** On any ambiguity or count mismatch, return `unresolved` and drop
that group — a dropped group costs a NOT_LOCATED, which is the status quo; a
wrong group produces a confidently mislocated finding, which is worse than
the bug being fixed.

Write the disagreement tests first, explicitly: `3:16`; a word in inline
quotes/brackets; a hyphenated and an apostrophised word; a verse where the
same word occurs 3× with punctuation between; and a `bottomWord` that no
longer occurs in the current text (the `ALIGN_TARGET_MISMATCH` shape,
`local_checks.py:36-40`).

### 3. Alignment precedent projection
For each verse in scope, load the tC alignment (`tc_project.load_verse_alignment`),
keep only verses where `word_alignment_state(...) == 'completed'`
(`tc_project.py:1836-1841`), resolve both sides via (1) and (2), and emit
records in the same shape the precedent matcher already consumes:
`{"sourceTokenInstanceIds": [...], "targetTokenInstanceIds": [...]}`.

**Exclude** any group flagged by the compatibility scan —
`LEGACY_EMPTY_BOTTOM_WORDS_AMBIGUOUS`, `MALFORMED_LEGACY_TOKEN_IDENTITY`,
`DUPLICATE_ACTIVE_TOKEN_MEMBERSHIP`, `MALFORMED_LEGACY_ALIGNMENT_FILE`
(`passage_semantic_runtime.py:1117-1187`).

**Decide and justify in the PR description:** reuse
`LocationEvidenceKind.HUMAN_PRECEDENT` for these, or add a sibling
`WORD_ALIGNMENT` kind to `passage_semantic_models.py:197-209`. A separate
kind is probably right — the evidence payload is what a reviewer reads when
asking *why* a finding located where it did, and "human precedent" and
"translationCore alignment" are different provenances with different
staleness behaviour. If you add one, give it the same 0.65 weight and set
`provenance` to something like `"tc-word-alignment-v1"`.

### 4. Identity
- `LOCATION_ENGINE_VERSION` `"bridge-semantic-location-v1"` → `"-v2"`
  (`semantic_location.py:24`).
- New `ALIGNMENT_EVIDENCE_VERSION = "tc-word-alignment-v1"` alongside it.
- Both into the run fingerprint (`:542-553`), **plus** an alignment content
  digest — reuse the directory SHA-256 from
  `passage_semantic_runtime.py:1102-1110`.
- Both into `analysis_jobs.policy_versions()` (`:157-190`). This
  auto-stales every existing job via exact-dict comparison at `:153-155` /
  `:549-561` — verify that, don't assume it.
- `ALIGNMENT_EVIDENCE_VERSION` into the Stage 9B.4 verifier fingerprint
  (`correction_verification.py:428-437`).
- Stages 7 and 8 need no edit; they inherit. Confirm this by test rather
  than by reading.

### 5. Invalidation — the part with no precedent
Alignment must become a first-class upstream input:

- Add an anchor type to `RECORD_DEPENDENCY_ANCHOR_TYPES`
  (`passage_semantic_repository.py:85-91`) and a dependency-id minter beside
  `target_dependency_id` / `source_dependency_id` (`:2058-2064`).
- Register `LOCATION_RUN → <alignment anchor>` edges in the publish
  transaction (`:2762-2775`).
- Add a prepared-intent/CAS invalidation path mirroring
  `prepare_target_invalidation` / `apply_target_invalidation`
  (`:1322-1398`), called from `bridge_service._finish_alignment_mutation`
  (`:1669-1687`) and `complete_alignment` (`:1746-1758`).
- Add startup replay for the crash case, mirroring
  `replay_pending_invalidations` (`passage_semantic_runtime.py:624-665`,
  called at `:514`).
- If any of this needs storage: `DATABASE_SCHEMA_VERSION` 14 → 15
  (`passage_semantic_repository.py:53`), a `_MIGRATION_V15` rung, a backfill
  of alignment edges for existing projects (precedent:
  `_MIGRATION_V13:1002-1011`), an additive-migration test in the style of
  `test_correction_stage9b4.py:1448-1522`, a `docs/HANDOFF.md` note, and
  updates to the five tests asserting `== 14`.

**Prefer a design that does not need a schema bump.** If v15 turns out to be
unavoidable, stop and report before writing the migration.

### 6. Golden
A sixth evidence source will move
`engine/tests/fixtures/stage6b-location-golden-v1.json`. Per
`CLAUDE.md:300-313`, **re-baseline it in its own commit that does nothing
else**, with the reason in the message.

## Definition of done

- The PHP 1:22 `οὐ` → Tamil case reaches **LOCATED** with a completed
  alignment present, and Stage 7 runs.
- With the alignment marked `invalid` or absent, behaviour is byte-identical
  to today (no new evidence, same outcome).
- Completing an alignment marks affected Stage 6B/7/8 records STALE; the
  pre-alignment result cannot be served as current. Test this end-to-end,
  not just at the repository layer.
- Every existing analysis job in a project goes STALE on first open after
  the version bump.
- The tokenization-disagreement tests from (2) all pass, and every ambiguous
  case resolves to `unresolved`/dropped rather than to a guess.
- Full gate clean: `pytest` (engine + Greek Room, expect ~1112+),
  `svelte-check` 0/0, Vitest, `cargo test` 12/12.
- Schema stays v14 (or the v15 migration is separately approved, with its
  additive test).
- Golden re-baseline is its own commit.
- No file under `.apps/translationCore/alignmentData/` or
  `tools/wordAlignment/` is written by any semantic-pipeline path.

## Stop and report if

- The design requires changing a weight or threshold.
- Target token resolution cannot be made unambiguous for the acceptance
  fixtures without ordinal guessing.
- A schema bump to v15 proves unavoidable.
- Making alignment an invalidation anchor requires touching
  `tc_project.py`'s transaction journal or the project authority rules
  (`HANDOFF.md` §39).

## Do not

Start V1.2, touch cross-verse location, add or configure an embedding
provider, bump the app version, tag, or release. None of that is authorized
by this task.
