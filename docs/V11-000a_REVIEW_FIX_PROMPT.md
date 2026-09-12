# V11-000a — review findings and fix prompt

Review of V11-000a as landed on `origin/main` at **`e3ff0de`**
(`feat(engine): Stage 6B consults completed Word Alignment as location
evidence`). The review was done against the pre-commit working tree; the
commit was pushed without the fixes, so F1–F3 below are now on `main` and
this is a follow-up fix commit, not part of the feature. Nothing is tagged
or released; app version is still 0.9.6. Finding 1 was confirmed by running
the code, not by reading it.

**Part A** is the evidence. **Part B** is the prompt to paste to the code
agent.

---

# Part A — findings

## F1. CONFIRMED — casefolding silently drops alignment evidence on bicameral-script targets

`word_alignment_evidence.py:39`:

```python
def _norm(value: str) -> str:
    return unicodedata.normalize("NFC", str(value or "")).casefold().strip()
```

But `tokenize_target_text` (`passage_semantic_runtime.py:475-500`) computes
`occurrence` / `occurrences` over **NFC without casefold**:

```python
normalized = [unicodedata.normalize("NFC", match.group(0)) for match in matches]
totals = Counter(normalized)
```

So two tokens differing only in case each carry `occurrence=1,
occurrences=1`. In `resolve_target_token_id:110-117` both satisfy the
casefolded word test, `len(exact) == 2`, and the group is dropped.

Run against the actual `tokenize_target_text` and `resolve_target_token_id`
from the working tree:

```
CONTROL caseless (Tamil)                  -> RESOLVED
CONTROL English, one case only            -> RESOLVED
English, same word two cases              -> dropped   "The LORD is my shepherd; the Lord provides."  (Lord 1/1)
English, article The/the                  -> dropped   "The lord is the shepherd"                     (The 1/1)
English, sentence-initial capital only     -> dropped   "Grace to you. He gave grace."                 (grace 1/1)

Same three cases with NFC-only comparison (no casefold):
  two cases / Lord   -> RESOLVED
  article The        -> RESOLVED
  grace              -> RESOLVED
```

Impact: for any bicameral target (English, Spanish, French, Portuguese,
Indonesian, Swahili, …) any verse in which a word appears sentence-initially
and again mid-verse yields **no** alignment evidence for that group. Fail-safe
— never a wrong location — but the feature quietly does far less than it
appears to. Indic/caseless targets are unaffected, which is why the Tamil
acceptance case passed and why the 21 new tests (all caseless or single-case
target fixtures) did not catch it.

Same root cause in `resolve_source_token_id:64` for Greek: a capitalized and
a lowercase form of one lexeme in one verse each carry `occurrence=1` in the
pack (tC's aligner counts by exact string), casefold-match, and tie on
lemma/Strong's/morph → `len(best) != 1` → dropped. Hebrew is unaffected.

The rest of the codebase already treats tC word identity as exact and
case-sensitive: `TokenRef.signature` (`models.py`) and
`_reconcile_alignment_after_target_edit` (`tc_project.py:1898-1917`) both
key on the verbatim `word`. Exact NFC is the consistent choice.

## F2. The `WORD_ALIGNMENT` dependency edge is written outside the publish transaction

`semantic_location.py` (end of `locate`):

```python
self.repository.save_semantic_location_run(run_id=run_id, ...)
# ... comment ...
self.repository.add_record_dependency(
    "LOCATION_RUN", run_id, "WORD_ALIGNMENT",
    self.repository.alignment_dependency_id(self.project_id, self.book),
)
```

`add_record_dependency` (`passage_semantic_repository.py:4319-4325`) opens
its own connection and commits independently. The other three edges are
registered inside the publish transaction (`:2762-2775`).

A crash between the two commits leaves an ACTIVE `LOCATION_RUN` with no
`WORD_ALIGNMENT` edge — permanently immune to `apply_alignment_invalidation`.
`get_scope_status` (`analysis_jobs.py:549-561`) does not catch it either: it
compares target hashes, source hash, provider and `policyVersions`, never the
location fingerprint. Narrow window; exact invariant this change exists to
protect. `run_id` is computed before the save, so the fix is small.

## F3. The verse-bridge exclusion is documented but not enforced

Module docstring: bridged verses "simply contribute no alignment evidence
rather than being split heuristically." Nothing implements that.
Confirmed: `_reference_chapter_verse("PHP 1:2-3")` returns `('1', '2-3')`,
and `alignment_precedents_for_range` proceeds to
`word_alignment_state('1', '2-3')` / `load_verse_alignment('1', '2-3')` /
`source_tokens_for_verse(book, '1', '2-3')`. Whether evidence comes out
depends on pack behaviour, and no test covers it either way.

## F4 (optional). No observability on drops

Every failure path in `alignment_precedents_for_range` is a bare `continue`
/ `return []` / `return None`. The reviewer who has been staring at
NOT_LOCATED gets no answer to "why didn't my completed alignment help?" —
and F1 would have surfaced in the first bicameral project anyone opened if a
counter existed. `except Exception` at `:191` and `:203` is also broad enough
to swallow genuine bugs.

## F5 (optional). Redundant I/O

`load_verse_alignment` re-reads and re-parses the whole chapter JSON per
verse (`tc_project.py:130-135` → `load_alignment_chapter`), and
`alignment_state_digest` re-reads every chapter file and every marker file.
For a book-range Stage 6B run that is O(verses) full-chapter parses.

## Verified as correct

- Seven-component blend intact; no weight or threshold moved.
- `LOCATION_ENGINE_VERSION` v1→v2; `ALIGNMENT_EVIDENCE_VERSION` threaded
  through run fingerprint, `policy_versions()`, and the 9B.4 verifier
  fingerprint — matches the V1.1 template exactly.
- `source_token_identity` / `target_token_identity` extractions: one hash
  formula each, NFD warning in the docstring. Better than the spec asked for.
- `alignment_state_digest` (content + markers) vs `alignment_directory_digest`
  (content only), with the legacy scan kept on the content-only key so the
  two memoizations do not degrade each other. Good call.
- Unconditional edge registration, with the right rationale.
- Schema stayed v14. `WORD_ALIGNMENT` present in all four enum surfaces
  (Python, JSON schema, TS, Rust `WordAlignment`), ordering consistent.
- Golden `stage6b-location-golden-v1.json` untouched, correctly — no fixture
  in it has completed alignment.
- Read-only guarantee holds: nothing in the new paths writes under
  `alignmentData/` or `tools/wordAlignment/`.

---

# Part B — prompt for the code agent

> Paste from here down. Start from `origin/main` at `e3ff0de` or later.

---

You are applying review fixes to **V11-000a** (commit `e3ff0de` on `main`:
Stage 6B consults completed Word Alignment) in the Bridge repository. Read
`docs/V11-000_STAGE6B_ALIGNMENT_SPIKE.md` and
`docs/V11-000a_REVIEW_FIX_PROMPT.md` Part A first; the constraints in the
spike doc's Part B still bind. Three required fixes, two optional. Nothing
here changes the design — the review found the design sound.

## Required

### R1. Match in the space the occurrence counts were computed in — exact NFC, no casefold

`engine/tc_ai_bridge/word_alignment_evidence.py`. Both resolvers currently
compare via `_norm`, which casefolds. Bridge's `tokenize_target_text` and
tC's aligner both count `occurrence`/`occurrences` over the **exact
NFC** string, so a casefolded comparison matches tokens that were counted
separately, produces spurious ties, and drops the group. Part A has the
reproduction.

Change:

- `resolve_target_token_id`: compare
  `token["normalized"] == unicodedata.normalize("NFC", ref.word)`.
  Keep the `occurrence` and `occurrences` equality tests exactly as they are.
- `resolve_source_token_id`: compare
  `unicodedata.normalize("NFC", raw["word"]) == unicodedata.normalize("NFC", ref.word)`.
  Keep the `occurrence` test and the lemma/Strong's/morph reinforcement as
  they are. `normalize_strong` stays.
- Retire `_norm` from the word comparisons. If it remains for lemma
  comparison, say so in a comment; do not reintroduce casefold into any
  comparison that feeds a `(word, occurrence)` join.
- **Do not add a casefold fallback.** A tC word whose case differs from the
  current text means the text changed under the alignment — that is the
  `ALIGN_TARGET_MISMATCH` situation (`local_checks.py:36-40`) and must stay
  `unresolved`. If you believe a fallback is needed, stop and report the
  concrete case rather than adding one.
- Do **not** change `tokenize_target_text`, the pack, or any occurrence
  semantics anywhere. The resolvers adapt to the counting rule; the rule
  does not move.

Tests first, in `engine/tests/semantic/test_word_alignment_evidence.py`,
each asserting a specific resolved ID (not just "not None") and that the two
cased forms resolve to **different** IDs:

1. `"Grace to you. He gave grace."` — `grace 1/1` resolves to the lowercase
   token; `Grace 1/1` resolves to the capitalized token.
2. `"The LORD is my shepherd; the Lord provides."` — `Lord 1/1` and
   `LORD 1/1` each resolve, to different IDs.
3. `"The lord is the shepherd"` — `The 1/1` resolves to the capitalized
   article; `the 1/1` to the lowercase one.
4. Source side: unit-test `resolve_source_token_id` with
   `source_tokens_for_verse` monkeypatched to return two pack tokens
   `Χάρις` (occ 1) and `χάρις` (occ 1) with identical lemma/strong/morph;
   `χάρις 1` resolves to the lowercase token and `Χάρις 1` to the
   capitalized one.
5. Source side, real data: scan the vendored UGNT pack for one verse in
   which the same lexeme appears both capitalized and lowercase (any book;
   pin the reference in the test with a comment saying how it was found),
   and assert the lowercase `topWord` resolves to the lowercase pack token.
   If the scan finds none, say so in the PR description and keep test 4.
6. Controls that must keep passing unchanged: the existing Tamil fixtures,
   `test_target_resolution_matches_a_plain_word`, and all six
   tokenization-disagreement tests.

### R2. Register the `WORD_ALIGNMENT` edge inside the publish transaction

`engine/tc_ai_bridge/semantic_location.py` end of `locate`, and
`engine/tc_ai_bridge/passage_semantic_repository.py`
`save_semantic_location_run` (~`:2717-2776`).

- Add a parameter to `save_semantic_location_run` (e.g.
  `alignment_dependency_id: str`) and write the
  `("LOCATION_RUN", run_id, "WORD_ALIGNMENT", alignment_dependency_id)` edge
  in the same `executemany` / same `BEGIN IMMEDIATE … COMMIT` as the
  `SOURCE_INVENTORY` / `TARGET_INVENTORY` / `LOCATION_RELATIONSHIP` edges.
- Remove the trailing `add_record_dependency` call in `semantic_location.py`;
  move its explanatory comment to the new call site.
- Do not touch `_stale_generic_dependencies`, `recovery_check`, or
  `RECORD_DEPENDENCY_TABLES`. If the change seems to need any of those,
  stop and report.

Tests, in `engine/tests/semantic/test_word_alignment_invalidation.py`:

1. Atomicity: force the dependency write to fail (e.g. patch the
   connection's `executemany`/`execute` to raise on the `record_dependencies`
   insert) and assert **no** `semantic_location_runs` row exists afterwards.
   A run row without its edge must be impossible.
2. `test_a_location_run_depends_on_the_book_alignment_anchor_even_with_no_evidence_yet`
   must still pass without modification.
3. `test_every_writable_dependency_type_is_registered` and
   `test_dependency_tables_all_exist_and_are_stale_propagatable`
   (`engine/tests/correction/test_correction_stage9b0.py:657,699`) must still
   pass.

### R3. Enforce the verse-bridge exclusion the docstring promises

`engine/tc_ai_bridge/word_alignment_evidence.py`,
`alignment_precedents_for_range`.

- First, confirm the actual displayed-reference form a bridged verse takes
  in `passage["targetTextByDisplayedReference"]` by running
  `rebuild_current_passage` on a fixture with a verse bridge. Do not assume
  `"PHP 1:2-3"`; check.
- Add an explicit guard in the loop — a bridged reference `continue`s with
  no attempt to load or resolve — and a one-line comment pointing at the
  module docstring's scope statement. Keep `_reference_chapter_verse`
  honest (it may still return `('1', '2-3')`); the guard is a policy
  decision and belongs where the policy is applied.
- Test: a project fixture with a **completed** alignment stored under a
  bridge key, whose passage includes that bridged reference, yields zero
  precedents and raises nothing. Also assert that
  `resolve_source_token_id` is never called for it (patch and count).

## Optional — do after R1–R3 pass, in separate commits

### O1. Drop diagnostics

Add a `wordAlignmentEvidence` block to the Stage 6B run payload's
diagnostics: `versesConsidered`, `versesCompleted`, `groupsSeen`,
`groupsResolved`, and `droppedByReason` keyed by
`NOT_COMPLETED | INVALID | BRIDGED_REFERENCE | NO_CURRENT_REVISION |
DUPLICATE_MEMBERSHIP | EMPTY_SIDE | SOURCE_UNRESOLVED | TARGET_UNRESOLVED |
LOAD_ERROR`. Narrow the two `except Exception` clauses to the exceptions
`rebuild_current_passage` and `load_verse_alignment` actually raise
(check: `ProjectError`, `FoundationValidationError`, `OSError`,
`json.JSONDecodeError`) and count those as `LOAD_ERROR`.

The payload is schema-checked with `additionalProperties: false`, so this
is another three-surface change (`schemas/bridge-passage-semantic-v1.schema.json`,
`src/lib/types/passageSemanticV1.ts`, `src-tauri/src/passage_semantic_wire.rs`)
plus whatever test pins the payload shape. If it turns out to need more than
that, stop and report before widening scope.

### O2. Chapter-level caching

Within one `alignment_precedents_for_range` call, load each chapter's
alignment JSON once (`load_alignment_chapter`) and slice verses from it,
instead of `load_verse_alignment` per verse. Pure refactor; no behaviour
change; existing tests must pass unchanged.

## Version handling — required

Bump `ALIGNMENT_EVIDENCE_VERSION` from `"tc-word-alignment-v1"` to
`"tc-word-alignment-v2"` in `word_alignment_evidence.py`. `v1` is now
public on `main` (`e3ff0de`), and R1 changes what the evidence finds: a
project analysed from that commit holds LOCATION_RUN fingerprints carrying
`v1`, and without a bump the post-fix engine would serve those
evidence-dropped runs as cache hits. This is the same rule
`correction_verification.py:421-426` states for Stage 6B changes generally.

The constant already flows through the run fingerprint,
`analysis_jobs.policy_versions()`, and the 9B.4 verifier fingerprint, so
the bump is one line plus whatever tests pin the literal string (grep for
`tc-word-alignment-v1` under `engine/tests/` and update them). No other
version moves — `LOCATION_ENGINE_VERSION` stays at `v2`, schema stays v14.

## Definition of done

- The three previously-dropped probe cases in Part A resolve; the two
  controls are unchanged.
- Source-side cased Greek resolves (R1 tests 4 and, if found, 5).
- Atomicity test passes; a location run row cannot exist without its
  `WORD_ALIGNMENT` edge.
- Bridged references produce zero precedents and no resolver call.
- All 21 existing V11-000a tests still pass without modification, except
  where R3 adds a bridge fixture.
- Full gate clean: engine + Greek Room `pytest` (expect ≥1132 + new tests),
  `svelte-check` 0/0, Vitest 335/335, `cargo test` 12/12, production build.
- `stage6b-location-golden-v1.json` still byte-identical.
- Schema still v14.
- `ALIGNMENT_EVIDENCE_VERSION == "tc-word-alignment-v2"`, and the literal
  appears in `policy_versions()` output and the verifier fingerprint inputs
  (assert it, the way `test_analysis_jobs_stage9a4.py:332-335` pins the
  Unicode comparison version).
- No path added or changed here writes under
  `.apps/translationCore/alignmentData/` or `tools/wordAlignment/`.
- `docs/BUILD_LOG.md` gets a short entry naming F1–F3 and what changed;
  `docs/HANDOFF.md` §44.12 gets one sentence noting the review fixes.

## Stop and report if

- Exact-NFC matching breaks any existing test other than by exposing a
  fixture that relied on casefolding — that would mean tC word strings can
  differ in case from the current text, which is a different problem.
- R2 needs changes to `_stale_generic_dependencies`, `recovery_check`, or
  any table definition.
- Bridged references come out of `rebuild_current_passage` in a form that
  makes a simple guard ambiguous.
- O1 needs more than the three-surface enum-style update.

## Do not

Change any weight or threshold; change `tokenize_target_text` or the pack;
re-baseline the golden; bump the app version; push — commit locally and
leave it for review.

---

## Commit shape

One fix commit on top of `e3ff0de`, containing R1–R3, the version bump, the
new tests, and the `BUILD_LOG.md` / `HANDOFF.md` §44.12 notes. Suggested
subject:

```
fix(engine): exact-NFC token matching, atomic WORD_ALIGNMENT edge, bridge guard (V11-000a review)
```

Body should name F1–F3 from this document and say that
`ALIGNMENT_EVIDENCE_VERSION` moved to `v2` and why. O1 / O2, if done, go in
separate commits after it. Commit this document (`docs/V11-000a_REVIEW_FIX_PROMPT.md`)
alongside so the history shows what the fix answers.

Leave the commit unpushed for review.

---

# Addendum — review of the fix commit `370be9c` (local, unpushed)

R1, R2, R3 and the `v2` bump are correct and were confirmed empirically:
all three previously-dropped probe cases resolve, cased pairs resolve to
distinct ids, the controls are unchanged, and a `bottomWord` whose case
differs from the current text stays dropped (no casefold fallback). The
atomicity test injects a real failure into the `record_dependencies` insert
and asserts no run row survives. The bridge guard is explicit. 1CO 2:11
(πνεῦμα / Πνεῦμα) is a genuine real-data cased pair.

**One blocker remains — do not push until it is addressed.**

## F6. BLOCKER — the `test_correction_stage9b4.py` edit hides a product bug (memo lag → spurious staling on reopen)

The fix commit added, after `_apply(application_service)`:

```python
runtime.synchronize_alignment_state()
```

with a comment saying the reopen "correctly" stales the hand-published run.
It does not. Sequence in the test, and in production:

1. `apply_scripture_edit` writes the word-alignment `invalid` marker
   (`tc_project.py:2091`) and reconciles `alignmentData` content.
   **The alignment memo (`migration_run` row keyed on
   `alignment_state_digest`) is not refreshed** — this path never calls
   `synchronize_alignment_state`.
2. A location run is published *after* that change (in the test, by hand;
   in production, by the post-correction re-analysis). Its fingerprint
   already encodes the new digest. It carries the `WORD_ALIGNMENT` edge.
3. Bridge is reopened → fresh `PassageSemanticRuntime` →
   `synchronize_alignment_state()` (`passage_semantic_runtime.py:1140`) →
   digest ≠ memo → `apply_alignment_invalidation` → **the run from step 2
   goes STALE**, along with everything downstream of it.

That is over-invalidation of a run computed against the *current* alignment
state, caused by the memo lagging the disk. Fail-safe, but it means: apply
correction → re-analyze → verify → close → reopen → the whole book's
analysis is stale again. This is the "restart persistence (close/reopen
Bridge) holds" row of `docs/V1_1_UNICODE_ACCEPTANCE.md` Case C, and it
would fail it.

`synchronize_alignment_state` has exactly two callers: runtime
construction and `bridge_service._finish_alignment_mutation` (`:1693`).
Two paths that change alignment state on disk do not call it:

| path | what it writes | reachable today |
|---|---|---|
| `tc_project.apply_scripture_edit` (`:2042-2103`) | `invalid` marker + reconciled `alignmentData` | **yes — editor edits and correction application (Case C)** |
| `bridge_service.complete_alignment` (`:1746-1758`) | `completed` marker | live RPC; no frontend caller in `src/` today |

The bug is also in `e3ff0de`: real `locate()` runs there already carried the
edge. It was invisible only because the 9B.4 test's hand-published fixture
bypassed `locate()` and had no edge. F2 made the fixture faithful and the
test did its job; the manual sync makes it unfaithful again in the other
direction.

### Required

1. **Revert** the `runtime.synchronize_alignment_state()` line in
   `test_correction_stage9b4.py`. Keep the `alignment_dependency_id=`
   kwarg in `_publish_evidence` — that is required by R2.
2. **Refresh the alignment memo on both unsynced paths.**
   - `apply_scripture_edit`: the hook must cover *both* the editor-edit
     route and the correction-application route. They diverge around
     `strict_context` (the correction path may not pass through
     `prepare_target_edit` / `complete_target_edit`), so place the call
     where both converge, after the marker write, guarded on
     `self.passage_semantic_runtime is not None`. Prove coverage of both
     routes by test, not by reading.
   - `complete_alignment`: add the same call after
     `mark_word_alignment_completed`.
   - The redundant staling after a target edit is harmless:
     `_stale_generic_dependencies` handles already-STALE records
     (`passage_semantic_repository.py:4545-4547`).
3. **Regression test, without any manual sync** (in
   `test_word_alignment_invalidation.py`): real
   `SemanticLocationEngine(runtime).run_range(...)` → ACTIVE →
   `tc_project.edit_verse(...)` on a verse in range → run Stage 6B again →
   new ACTIVE run → construct a **fresh** `PassageSemanticRuntime` on the
   same project, exactly as `project.open` does → assert the second run is
   **still ACTIVE** and the fresh runtime's `synchronize_alignment_state()`
   returns `changed: False`. This assertion fails on `370be9c`; it is the
   reproduction. Add the same shape for `complete_alignment`.
4. The reverted 9B.4 test must pass on its own.
5. Full gate again; `docs/BUILD_LOG.md` entry naming F6.

### Not required now — durable design, for a follow-up issue

Stale by comparing each run's *own* recorded alignment digest to the
current one, instead of trusting a single memo. Immune to any future
unsynced path. Needs the digest persisted per run (a payload field →
schema / TS / Rust triple update), so it is a separate change. File it.

### Commit shape

Either amend `370be9c` or add one commit on top of it before pushing —
your call. Both fine; what matters is that `main` never carries the manual
sync in the 9B.4 test.
