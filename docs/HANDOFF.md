# Bridge — Passage-Aware Semantic Alignment & Translation QA: Continuation Handoff

This file is the **stage-by-stage status and continuation-prompt record** for
Bridge's passage-aware semantic alignment and Scripture translation-QA
effort. It is checked into the repo (`docs/HANDOFF.md`) and updated in place
as each stage lands — unlike a one-off dated snapshot, treat this as living
documentation, alongside [`BUILD_LOG.md`](BUILD_LOG.md) (granular engineering
narrative) and [`passage-aware-semantic-alignment.md`](passage-aware-semantic-alignment.md)
(the underlying requirements/invariants spec, mostly static).

**Use this file as the continuation prompt in a new conversation** (Claude
Code, ChatGPT, or otherwise) when resuming this effort. Sections 1–41 are the
governing principles and data-model invariants — read them first and treat
them as binding. Sections 42 onward track what is actually done, what
remains, and the immediate next task.

Repository: this file travels with the repo it describes — resolve paths
relative to wherever it's checked out, not a hardcoded machine path.

---

## Where to pick up — 2026-09-11 (persistence / identity / team direction, #44–#47)

A second, separate thread of work now runs alongside the semantic stages this file
tracks. Its design record is [`TEAM_ARCHITECTURE.md`](TEAM_ARCHITECTURE.md); its
decisions are the three 2026-09-11 entries in [`DECISIONS.md`](DECISIONS.md); its
steps are GitHub issues **#74–#81**, in that order, plus findings **#82** and **#83**.
Nothing in it changes the invariants below: the translationCore on-disk files, the
v14 semantic DB, the append-only ledger and offline-first all stay as they are.

State as of 2026-09-11 (Benz's session, picking this up same day):

- Done and pushed: `TEAM_ARCHITECTURE.md`; #74 steps 1–2 (engine tests packaged by
  area under `engine/tests/<area>/`, pytest config + markers in `engine/pyproject.toml`,
  `pytest-xdist` pinned; `pytest -n auto -m "not slow"` from `engine/` is the inner
  loop). Measurements in `BUILD_LOG.md`'s #74 section. CI stays serial — parallel was
  measured slower on the 4-vCPU runner.
- #82 landed differently than first proposed: profiling showed the ~60 s/test cost was
  mostly the repository's SQLite connect/close/fsync overhead, not the pipeline rebuild,
  so `369f648`/`cc1ff33` opt out of fsync/WAL in tests instead of module-scoping the
  fixture. Local suite 18:56 → 3:17, CI serial 35:18 → 14:50. The issue stays open but is
  now second-order — module-scoping the read-only cases still waits for #74 step 4.
- #83 fixed (`9bf8857`): `cancel-in-progress` scoped to `pull_request` only, since on
  `push` the concurrency group was the same for every commit to `main` and a new push
  cancelled the previous commit's still-running gate.
- Not started: #75–#81 (the workbench SQLite, identity, engine session model, hub,
  dashboard). No persistence or identity code exists yet.
- **Next task:** #75 (workbench SQLite repository skeleton — `TEAM_ARCHITECTURE.md` §3).

---

# 1. Project

You are continuing development of:

> **Bridge — A Scripture Translation Quality Workbench**

Bridge is a Svelte/TypeScript + Tauri/Rust + Python application that works
with translationCore projects, USFM/SFM Scripture, UHB/UGNT
original-language resources, and unfoldingWord resources such as tN, tW,
TWL, and Translation Academy.

The architecture being built is a **language-independent, passage-aware
semantic alignment and Scripture translation QA system** from Biblical
Hebrew/Aramaic/Greek to any imported target-language Bible.

Do not reduce this project to ordinary word alignment.

---

# 2. End Goal

The primary goal is to detect translation problems such as:

- omissions
- additions
- undertranslation
- overtranslation
- meaning shift
- contradiction
- participant/referent errors
- negation errors
- quantity errors
- temporal errors
- role reversal

The workflow should eventually be:

```text
DETECT
  ↓
EXPLAIN
  ↓
SHOW EVIDENCE
  ↓
PROPOSE CORRECTION
  ↓
HUMAN REVIEW
  ↓
APPLY / EDIT / REJECT
  ↓
REALIGN
  ↓
RE-RUN QA
```

Bridge must **never silently rewrite Scripture**. Scripture corrections
require explicit human approval.

---

# 3. Governing Principle

> **Bridge aligns semantic realization first and lexical tokens second.**

Do not ask only:

> Which target word corresponds to this Hebrew/Aramaic/Greek word?

Ask:

> **Where, and by what linguistic mechanism, is this source-language meaning
> represented in the target passage?**

Translations may legitimately:

- reorder clauses
- move material across verse boundaries
- merge or split expressions
- use pronouns instead of nouns
- express source lexical meaning grammatically
- express meaning implicitly
- explicitate information
- use idioms
- convert nouns to verbs or verbs to nouns
- restructure clauses

Verse numbers are navigation/reference boundaries, not hard semantic
boundaries.

---

# 4. Passage Awareness

Never assume:

```text
Source verse N → Target verse N
```

A source semantic unit may map to:

- the same target verse
- another target verse
- several target verses
- a reordered passage
- a passage across a chapter boundary

Search should expand structurally:

```text
same canonical verse
→ structural sentence/segment
→ paragraph
→ adjacent segment
→ selected passage
→ chapter-boundary continuation
→ bounded extended passage
```

Same-verse is a prior, not a rule.

---

# 5. Semantic Layer vs Lexical Layer

Bridge has two coordinated layers.

```text
SEMANTIC LAYER
- may overlap/nest
- clauses, concepts, grammar, implicit meaning, discourse
- may cross verses

LEXICAL LAYER
- concrete source-token → target-token groups
- hard exclusive token ownership
```

Semantic annotations may overlap lexical groups.

Lexical groups may not reuse a token in the same authoritative active
lexical solution/layer.

---

# 6. Hard Exclusive Token Membership

Within one authoritative active lexical solution/layer:

```text
Each source token instance belongs to at most one active lexical group.
Each target token instance belongs to at most one active lexical group.
```

Valid:

```text
[S1 S2] → [T1 T2 T3]
```

Invalid:

```text
Group A: S1 → T1
Group B: S1 → T2
```

Invalid:

```text
Group A: S1 → T1
Group B: S2 → T1
```

One-to-many, many-to-one, and many-to-many are represented as **one
composite group**, not overlapping pairwise groups.

Token layers include:

```text
ORTHOGRAPHIC
SUBTOKEN
MORPHEME
```

Parent/child refinements may coexist only through explicit
alignment-family/refinement rules.

Only one authoritative active lexical solution should exist for a given
scope/profile/layers. Alternatives remain proposed/inactive.

---

# 7. Lexical Cardinalities

Supported:

```text
ONE_TO_ONE
ONE_TO_MANY
MANY_TO_ONE
MANY_TO_MANY
SOURCE_TO_NULL
NULL_TO_TARGET
```

For null alignment, the absent side's token layer is null.

---

# 8. Null Alignment

Keep these distinct:

```text
UNALIGNED
≠  NULL_ALIGNED
≠  NOT_LOCATED
≠  MISSING
```

- `UNALIGNED`: no lexical decision completed.
- `NULL_ALIGNED`: explicit decision that no direct lexical counterpart
  exists.
- `NOT_LOCATED`: bounded semantic search completed but no reliable
  realization was found.
- `MISSING`: later QA conclusion that source meaning appears genuinely
  absent.

> **Null alignment initiates QA; it does not determine QA.**

Example:

```text
SOURCE → Ø
NULL_ALIGNED
GRAMMATICALLY_REALIZED
COVERED
NO ISSUE
```

versus:

```text
SOURCE → Ø
NULL_ALIGNED
NOT_LOCATED
MISSING
OMISSION
```

Null groups consume token ownership.

Legacy translationCore groups with empty `bottomWords` must never
automatically become null alignments.

---

# 9. Semantic Realization

Primary realization states:

```text
LEXICALLY_REALIZED
GRAMMATICALLY_REALIZED
PRONOMINALIZED
IMPLICIT
NOT_LOCATED
UNCERTAIN
```

Relationship properties may include:

```text
SPLIT
MERGED
CROSS_VERSE
REORDERED
DISCONTIGUOUS
EXPLICITATED
CLAUSE_RESTRUCTURED
IDIOMATIC_REALIZATION
VERSIFICATION_DIFFERENCE
```

---

# 10. Location and Meaning Are Independent

This is fundamental.

Stage 6B answers:

> **Where is the source meaning translated?**

Stage 7 answers:

> **Does that located target expression preserve the source meaning?**

A wrong translation may still have the correct location.

Example:

```text
Source: ALL
Located target: SOME

Location:
LOCATED, high confidence

Meaning:
wrong/altered
```

Do not search elsewhere for a semantically nicer phrase and hide the
mistranslation.

---

# 11. Meaning Status

Controlled statuses:

```text
PRESERVED
PRESERVED_WITH_RESTRUCTURING
PARTIAL
OVERTRANSLATED
UNDERTRANSLATED
MEANING_SHIFT
CONTRADICTED
UNVERIFIABLE
```

These are semantic assessments, not final QA findings.

---

# 12. Source Coverage and Target Support

Source coverage statuses:

```text
NOT_CHECKED
COVERED
COVERED_BY_RESTRUCTURING
POSSIBLY_MISSING
MISSING
UNCERTAIN
```

Target support statuses:

```text
NOT_CHECKED
SOURCE_SUPPORTED
CONTEXT_SUPPORTED
GRAMMATICALLY_REQUIRED
EXPLICITATION_SUPPORTED
POSSIBLY_UNSUPPORTED
UNSUPPORTED
UNCERTAIN
```

`MISSING` and `UNSUPPORTED` require explicit human confirmation — Stage 8's
automatic engine never promotes `POSSIBLY_MISSING → MISSING` or
`POSSIBLY_UNSUPPORTED → UNSUPPORTED` on its own.

---

# 13. QA Findings

Implemented (Stage 8) finding kinds:

```text
POSSIBLE_OMISSION
POSSIBLE_ADDITION
POSSIBLE_UNDERTRANSLATION
POSSIBLE_OVERTRANSLATION
MEANING_SHIFT
CONTRADICTION
NEGATION_PROBLEM
QUANTITY_PROBLEM
TEMPORAL_PROBLEM
PARTICIPANT_PROBLEM
REFERENT_PROBLEM
RESOURCE_CONFLICT
SOURCE_VARIANT_REVIEW
```

(Plus 7 earlier Stage-3-foundation kinds retained unchanged:
`POSSIBLY_MISSING`, `MISSING`, `POSSIBLY_UNSUPPORTED`, `UNSUPPORTED`,
`RESOURCE_CONFLICT`, `NEEDS_PASSAGE_REVIEW`, `NEEDS_EXTENDED_PASSAGE_REVIEW`.)

Never create a translation-error finding merely because strings failed to
align.

---

# 14. Bidirectional QA

Bridge runs:

```text
SOURCE COVERAGE AUDIT
```

Question:

> Did every required source meaning survive?

and:

```text
TARGET SUPPORT AUDIT
```

Question:

> Is every significant target meaning licensed by the source, grammar,
> context, or legitimate translation transformation?

Do not equate unmatched target tokens with additions.

Do not equate unmatched source tokens with omissions.

---

# 15. tN / tW / TWL

Use these as evidence/constraints, not unquestionable authorities.

- **tW**: concept-level semantic evidence.
- **TWL**: connects a specific source occurrence to a tW concept; important
  for polysemy.
- **tN**: passage-specific evidence for idioms, figures of speech, grammar,
  implicit information, referents, discourse, translation restructuring,
  etc.

Resource validation states:

```text
NOT_CHECKED
CONSISTENT
SUPPORTING
CONFLICTING
NOT_APPLICABLE
```

Resource conflict should lower confidence or trigger review, not force an
answer. Stage 8 surfaces material conflicts as `RESOURCE_CONFLICT` findings
rather than letting them silently produce a translation-error conclusion.

---

# 16. False-Positive Prevention

Bridge should optimize for precision.

Prefer:

```text
UNCERTAIN
```

over forced mapping.

Embedding similarity is not proof. Explicitly protect against errors
involving:

```text
all / some
before / after
come / go
give / receive
positive / negative
one / many
```

Candidate competition matters.

```text
A = 0.88
B = 0.86
```

should normally be:

```text
AMBIGUOUS
```

Search failure must never become a false absence.

Use:

```text
SEARCH_INCOMPLETE
```

for timeout/model/resource/budget failure.

---

# 17. Review vs Lifecycle

Independent `ReviewStatus`:

```text
UNREVIEWED
AI_PROPOSED
HUMAN_APPROVED
HUMAN_REJECTED
HUMAN_MODIFIED
NEEDS_DISCUSSION
```

Independent `LifecycleStatus`:

```text
ACTIVE
INACTIVE
STALE
SUPERSEDED
QUARANTINED
```

A target edit may change:

```text
HUMAN_APPROVED + ACTIVE
```

to:

```text
HUMAN_APPROVED + STALE
```

Never erase human review history.

---

# 18. QA Disposition

QA findings have an independent disposition:

```text
UNRESOLVED
CONFIRMED_TRANSLATION_ERROR
ACCEPTABLE_TRANSLATION
FALSE_POSITIVE
NEEDS_DISCUSSION
CORRECTED
```

This makes human decisions unambiguous. Promoted via
`FoundationRepository.update_qa_disposition(finding_id, disposition,
expected_revision, reviewer)` — implemented since Stage 3, exercised by
Stage 8's tests.

---

# 19. CorrectionProposal

The foundation includes a versioned correction object (`CorrectionProposal`
in `passage_semantic_models.py`, table `correction_proposals` since schema
v1) containing:

```text
findingId
baseTargetRevision (currentTargetRevision)
affectedReferences (targetDisplayedReferences)
currentText
proposedText
explanation
evidenceIds
sourceSemanticUnitIds
createdBy (appliedBy)
reviewStatus
lifecycleStatus
appliedRevision (appliedTargetRevision)
```

This model exists and is fully wire-compatible, but **no stage through
Stage 8 constructs an instance of it**. Correction generation is Stage 9+
work. Applying a correction must be an explicit human action and must
stale/re-run dependent analysis.

---

# 20. Stable Token Identity

Separate:

```text
TokenLineage
```

from:

```text
TokenInstance
```

Edits create new target token instances.

Lineage may suggest correspondence but must never silently relocate a
human-approved alignment.

Canonical identity includes versioned fields such as:

```text
resource/project
book
displayed reference
canonical reference
token layer
index
occurrence
raw form
normalized form
character span
tokenization version
resource/text revision
```

Temporary `H###` / `T###` IDs are UI aliases only.

---

# 21. Unicode Span Contract

Persist half-open Unicode code-point coordinates:

```text
[startCodePoint, endCodePoint)
```

against raw unnormalized text.

Cross-language rules:

- Python: Unicode code points
- Rust: `.chars()`, not byte indexing
- TypeScript: convert code-point ranges; native UTF-16 string indices are
  not canonical

Utilities convert among:

```text
code point
UTF-8
UTF-16
grapheme boundaries
```

Tests cover Tamil combining characters, Hebrew niqqud/cantillation, Greek
diacritics, and supplementary Unicode.

---

# 22. Versification

Versification is first-class.

```text
displayed reference
→ project versification
→ canonical reference(s)
→ semantic relationship
```

Normalize before `CROSS_VERSE`.

If displayed references differ but canonical identity is the same:

```text
VERSIFICATION_DIFFERENCE
```

not `CROSS_VERSE`.

Support verse bridges, split/merged verses, Psalm titles, chapter shifts,
lettered segments, and ambiguity.

---

# 23. Current Target Text Authority

This was a critical repository bug and has been fixed.

The authoritative current Scripture wording is:

```text
<project>/<book>/<chapter>.json
```

Preserved imported USFM supplies structure only.

Never analyze old imported USFM wording after a Bridge edit.

If current text and structure cannot be safely reconciled:

```text
STRUCTURE_TEXT_MISMATCH
```

Do not fall back to stale wording.

---

# 24. Source Resource Locking

Projects pin UHB/UGNT identity/version/hash.

If source resource hashes change:

```text
dependent semantic records → STALE
```

Do not silently migrate old source relationships to changed tokens.

---

# 25. Independent Source and Target Inventories

A major architectural rule:

```text
SOURCE INVENTORY
independent of target

TARGET INVENTORY
independent of source
```

Only after both exist independently does alignment occur.

This prevents circular reasoning. Verified by an explicit anti-leakage test
in Stage 6A: loading the Greek source inventory does not change the Tamil
target semantic fingerprint.

---

# 26. Source Semantic Inventory — Stage 5

Complete. Key file: `engine/tc_ai_bridge/source_semantic_inventory.py`.

Source semantic units may include justified cases of:

```text
LEXICAL
MORPHOLOGICAL
NEGATION
QUANTIFIER
PARTICIPANT
REFERENT
PREDICATE
SEMANTIC_ROLE
CLAUSE
CLAUSE_RELATION
DISCOURSE_RELATION
IMPLICIT_GRAMMATICAL
IDIOM
CONSTRUCTION
TEMPORAL
SPATIAL
```

Every canonical source token is inventoried, but not every token is an
independent omission obligation. Source language identity remains
token-level, including Biblical Hebrew, Biblical Aramaic, and Koine Greek.
Stage 5 also **pre-seeds one `SemanticCoverageAccount` per
`(auditOwnerUnitId, coverageDimension)`** for every `PRIMARY`-role unit,
with `findingId=None` placeholders — Stage 8 finalizes these same rows
rather than creating new ones.

---

# 27. Semantic Obligation and Coverage Accounting

Each source semantic unit has concepts such as:

```text
auditEligibility
semanticObligation
accountingRole
auditOwnerUnitId
coverageDimension
```

Obligation types:

```text
REQUIRED
CONTEXT_DEPENDENT
GRAMMATICAL
DERIVED
NON_OBLIGATORY
UNCERTAIN
```

Eligibility:

```text
ELIGIBLE
CONDITIONAL
AGGREGATE_ONLY
EXCLUDED
REVIEW_ONLY
```

Accounting roles:

```text
PRIMARY
COMPONENT
AGGREGATE
EVIDENCE_ONLY
```

Coverage dimensions include:

```text
LEXICAL_CONTENT
POLARITY
QUANTITY
PARTICIPANT
REFERENT
PREDICATION
TEMPORAL_ASPECTUAL
SPATIAL_RELATION
CLAUSE_RELATION
DISCOURSE_RELATION
OTHER
```

Coverage accounts prevent duplicate findings from overlapping semantic
units. Stage 8 only audits `PRIMARY`-role, non-`AGGREGATE_ONLY`/`EXCLUDED`/
`REVIEW_ONLY`-eligibility units directly — `COMPONENT`/`AGGREGATE`/
`EVIDENCE_ONLY` units are `NOT_CHECKED` (their parent owner is audited
instead), which is how deduplication is enforced.

---

# 28. Dependency DAG vs Relation Graph

Coverage roll-up uses an acyclic dependency graph.

Acyclic relations may include:

```text
CONTAINS
DEPENDS_ON
DERIVED_FROM
MODIFIES
NEGATES
QUANTIFIES
PARTICIPANT_OF
ARGUMENT_OF
REFINES
```

Symmetric/cyclic relations live separately:

```text
COREFERS_WITH
COEXTENSIVE_WITH
ALTERNATIVE_ANALYSIS
```

Never run coverage topological logic over unrestricted cyclic relations.

---

# 29. Target Semantic Inventory — Stage 6A

Complete. Key file: `engine/tc_ai_bridge/target_semantic_inventory.py`.

The target inventory is built from current target text without consulting
source semantic units. Language-independent baseline:

```text
raw Unicode
graphemes
character spans
orthographic/token candidates
punctuation
verse/paragraph structure
passage context
repeated-form statistics
```

Optional analyzers may add morphology, POS, syntax, coreference, or
semantic roles. Unavailable capabilities remain explicitly unavailable.

Target token layers:

```text
ORTHOGRAPHIC
SUBTOKEN
MORPHEME
```

TranslationCore compatibility tokenizer remains `tc-whitespace-v1`. No-space
fallback preserves larger spans rather than inventing uncertain
segmentation. Every `TargetSemanticUnit` already carries
`auditEligibility`/`accountingRole`/`auditOwnerUnitId`/`coverageDimension`
(same shape as the source side) — `PRIMARY`+`ELIGIBLE` units are exactly
Stage 8's target-support audit candidates; no separate Stage 6A structure
was needed for that.

---

# 30. Source→Target Location — Stage 6B

Complete. Key files: `engine/tc_ai_bridge/semantic_location.py`,
`semantic_location_benchmark.py`, `engine/tests/fixtures/stage6b-location-golden-v1.json`.

Location outcomes:

```text
LOCATED
AMBIGUOUS
NOT_LOCATED
SEARCH_INCOMPLETE
UNSUPPORTED_ANALYSIS
```

Implemented: progressive passage search, exact revision-bound target
anchoring, split, merged, cross-verse, reordered, grammatical realization,
pronominalized realization, alternative candidates, candidate competition,
non-circular contextual evidence, optional multilingual embedding provider
abstraction, content/model-addressed embedding cache, dependency
invalidation/stale propagation.

---

# 31. Embeddings

Embeddings are candidate-retrieval evidence, not truth. Provider metadata is
versioned. No production multilingual embedding model is currently bundled.
Bridge does not depend on an online API. Embedding similarity never
overrides deterministic contradiction evidence (enforced in both Stage 7's
`DeterministicMeaningComparator` and Stage 8's gate policy).

---

# 32. Meaning Preservation — Stage 7

**Complete.** Key file: `engine/tc_ai_bridge/meaning_analysis.py` (constants
`MEANING_ENGINE_VERSION = "bridge-meaning-analysis-v1"`,
`MEANING_POLICY_VERSION = "meaning-policy-v1"`).

Stage 7 consumes Stage 6B's frozen location output — it never re-searches.
For each `LOCATED` relationship it builds a `MeaningAssessment` (persisted
in `meaning_assessments`/`meaning_component_assessments`, schema v6) with:
overall `MeaningStatus`, per-dimension `componentAssessments` (each with a
`MeaningComponentStatus`, confidence, evidence kind, and explanation),
supporting/conflicting evidence ids, a location-outcome/confidence snapshot,
and a `reason` for non-`LOCATED` outcomes (`NO_LOCATED_REALIZATION`,
`AMBIGUOUS_LOCATION`, `SEARCH_INCOMPLETE`, `UNSUPPORTED_ANALYSIS`,
`LOCATION_REVIEW_REQUIRED`). Non-`LOCATED` outcomes always produce
`UNVERIFIABLE`, never a forced meaning judgment.

`DeterministicMeaningComparator.compare(source_text, target_text,
dimension, source_kind, realization, target_capabilities)` is the
component-level engine — small, controlled, versioned lexical lists per
dimension (`QUANTITY`, `TEMPORAL`, `COMPLETION`, `MODALITY`, `NEGATIVE`,
`PARTICIPANTS`, `LICENSED_IDIOMS`, `LICENSED_EXPLICITATIONS`,
`SPECIFICITY_MARKERS`), Hebrew-point-insensitive but script-preserving
normalization (`_comparison_norm`), and a resource-conflict downgrade path
(a `CONFLICTING` tN/tW/TWL evidence status forces `NOT_DETERMINABLE` even
when the deterministic rule would otherwise fire). `MeaningPolicy.aggregate`
is the versioned status-lattice reduction from component statuses to one
overall `MeaningStatus` (any `CONTRADICTED` wins; `ALTERED` →
`MEANING_SHIFT`; specificity mismatches → `UNDERTRANSLATED`/
`OVERTRANSLATED`; restructuring realizations → `PRESERVED_WITH_
RESTRUCTURING`).

Verified behavior includes: `all → some` remains `LOCATED` +
`CONTRADICTED` (location is never silently re-searched because the meaning
looks wrong); `AMBIGUOUS`/`SEARCH_INCOMPLETE` always yield `UNVERIFIABLE`,
never a forced judgment; split/merged/cross-verse relationship identity is
preserved through meaning analysis; Hebrew niqqud/cantillation and Aramaic
(Dan 2:4) don't hide polarity/quantity contradictions; no-space Japanese
and analyzer-unavailable targets stay conservative
(`NOT_DETERMINABLE`/`UNVERIFIABLE`) rather than guessing; human-approved
assessments survive a source-lock/target-edit staleness cascade with
`reviewStatus` untouched and `lifecycleStatus → STALE`.

No BUILD_LOG.md narrative or session-reported verification numbers exist
for this stage's original landing (see §43 — this is a real, pre-existing
documentation gap, not something Stage 8 introduced). Measured directly
during Stage 8 verification instead: **focused Stage 7 suite: 22 passed**
(`pytest engine/tests/semantic/test_meaning_analysis_stage7.py -q`).

---

# 33. Stage 7 Meaning Policy

`MeaningPolicy` (in `meaning_analysis.py`) is the single versioned
aggregation policy — `meaning-policy-v1`. Confidence values
(`MEANING_CONFIDENCE_POLICY_VERSION = "meaning-confidence-v1"`,
`MEANING_CALIBRATION_VERSION = "meaning-uncalibrated-v1"`) are explicitly
marked uncalibrated; raw score and calibrated value are kept as separate
fields even though they are currently equal. Do not claim production
calibration from the Stage 7 benchmark
(`engine/resources/meaning_analysis/benchmark-v1.json`, 19 cases,
`reviewStatus: "MACHINE_PROPOSED"`, guarded by `meaning_benchmark.py`
rejecting anything else).

---

# 34. Bidirectional QA — Stage 8

**Complete (2026-09-02).** Key files: `engine/tc_ai_bridge/qa_audit.py`,
`qa_benchmark.py`, `engine/resources/qa_audit/{omission,addition}-benchmark-v1.json`,
`engine/tests/semantic/test_qa_audit_stage8.py`. Full narrative:
`docs/BUILD_LOG.md`, entry "Stage 8 — Bidirectional Source Coverage, Target
Support, and Translation QA (2026-09-02)".

Stage 8 synthesizes Stage 5/6A/6B/7's already-persisted outputs — it never
re-runs location search or re-judges meaning. It is the first stage allowed
to produce translation-problem findings.

**A discovery that shrank the implementation**: the QA persistence
foundation was built in Stage 3 and simply never called —
`FoundationRepository.save_qa_finding(QaFinding)`,
`save_coverage_account(SemanticCoverageAccount)`, and
`update_qa_disposition(...)` (the human-confirmation-boundary transition)
were all fully functional, unused code. Stage 8 mostly *finishes*
pre-built plumbing: it finalizes Stage 5's pre-seeded source coverage
accounts in place (new `update_coverage_account_status`,
optimistic-concurrency, same pattern as `update_qa_disposition`) rather
than inserting duplicates, and constructs `SemanticCoverageAccount`
instances fresh for the target-support side (no Stage 6A seed existed for
that direction).

**Schema**: migration v6→v7 adds one table, `qa_audit_runs` (mirrors
`meaning_analysis_runs` exactly: id/fingerprint/`meaning_run_id`
FK/payload_json/`UNIQUE(project_id,book,range_key,fingerprint)`).
`qa_findings`/`coverage_accounts` needed no column changes (both existed
unused since schema v1). Run traceability goes through the existing
`record_dependencies` graph (`QA_RUN`→`MEANING_RUN`,
`COVERAGE_ACCOUNT`/`QA_FINDING`→`QA_RUN`), so staleness cascades from a
source-resource or target-text change all the way down to
`QaFinding.lifecycleStatus = STALE` via one new map entry.

**Model changes** (`passage_semantic_models.py`): `QaFindingKind` gained 12
values (§13); new `QaFindingSeverity` (`CRITICAL`/`HIGH`/`MEDIUM`/`LOW`/
`INFO`) and `QaRunStatus` enums; `EvidenceKind` gained `SOURCE_VARIANT`.
`QaFinding` gained 13 fields (severity, meaning-assessment/coverage-account
id links, location/meaning snapshots, supporting/conflicting/resource
evidence id lists, target/source hashes, engine/policy versions,
fingerprint) — all required, since every construction site is new Stage 8
code. `SemanticCoverageAccount` gained one field, `coverageStatus: str =
"NOT_CHECKED"` (a `SourceCoverage` value for `SOURCE_COVERAGE`-direction
accounts, `TargetSupport` for `TARGET_SUPPORT`-direction, validated against
`direction` in `__post_init__`; the default kept Stage 5's existing
construction site unmodified). Extending these tripped the repo's existing
canonical-schema parity tests — `schemas/bridge-passage-semantic-v1.schema.json`
and `src/lib/types/passageSemanticV1.ts` were updated to match (both are
treated as load-bearing contracts, not incidental docs — see
`engine/tests/persistence/test_passage_semantic_foundation.py`).

**`QaAuditPolicy`** (`qa-policy-v1`, one centralized versioned
gate/precedence/severity policy):
- `source_coverage_for(...)`: `NOT_LOCATED` only becomes `POSSIBLY_MISSING`
  when every relationship touching that obligation is genuinely
  `NOT_LOCATED` (never from `AMBIGUOUS`/`SEARCH_INCOMPLETE`/
  `UNSUPPORTED_ANALYSIS`, which gate to `UNCERTAIN` instead) and no
  documented source-variant evidence explains the absence (checked against
  the owner unit's real `EvidenceRecord`s for `kind == SOURCE_VARIANT`,
  falling back to `SOURCE_VARIANT_REVIEW` instead of `POSSIBLE_OMISSION`
  when one exists). A `LOCATED` relationship with a `PRESERVED`/
  `PRESERVED_WITH_RESTRUCTURING` Stage 7 assessment becomes `COVERED` or
  `COVERED_BY_RESTRUCTURING` depending on whether a `RelationshipProperty`
  is present or realization isn't `LEXICALLY_REALIZED`.
- `target_support_for(...)`: a target unit with no referencing relationship
  becomes `GRAMMATICALLY_REQUIRED` for a small controlled function-word
  list, `EXPLICITATION_SUPPORTED` for licensed explicitation targets
  (reusing Stage 7's `DeterministicMeaningComparator.LICENSED_EXPLICITATIONS`),
  `POSSIBLY_UNSUPPORTED` only for an unmatched specificity marker (reusing
  `SPECIFICITY_MARKERS`), else the conservative default `UNCERTAIN` —
  deliberately not `POSSIBLY_UNSUPPORTED`, since a v1 deterministic policy
  can't yet positively rule out every legitimate grammatical/explicitation
  reason for an unmatched word.
- `finding_kind_for(...)`: component-aware precedence — a `CONTRADICTED`/
  `ALTERED` component on `POLARITY`/`QUANTITY`/`TEMPORAL_ASPECTUAL`/
  `PARTICIPANT`/`REFERENT` wins over the generic `MEANING_SHIFT`/
  `CONTRADICTION`/`POSSIBLE_UNDERTRANSLATION`/`POSSIBLE_OVERTRANSLATION`
  fallback from the aggregate status; a `CONFLICTING` resource-evidence
  status on any component overrides everything to `RESOURCE_CONFLICT`. One
  finding per relationship, not per component.
- `severity_for(...)`: polarity/quantity/participant/temporal/referent
  reversal kinds and `CONTRADICTION` rank `CRITICAL`/`HIGH`;
  `MEANING_SHIFT` `HIGH`/`MEDIUM`; omission/addition `MEDIUM`; everything
  else `LOW`.

**A real architectural fork surfaced and deliberately left alone**: there
are two unrelated `QaFinding` classes in this repo —
`greek_room_engine.models.finding.QaFinding` (the one wired into the
visible ReviewPanel today, used by Wildebeest/USFM/names findings) and
`passage_semantic_models.QaFinding` (Stage 8's target — fully modeled,
persisted, but with no path to the UI yet). This was a deliberate choice
for this stage (confirmed with the user), matching the spec's "do not
build the final QA UI yet." **Wiring these together, or deciding they
should stay separate, is a Stage 9 decision.**

**Benchmarks**: `engine/resources/qa_audit/{omission,addition}-benchmark-v1.json`
(15 cases each, `reviewStatus: "MACHINE_PROPOSED"`, same guard convention
as Stage 7's). `qa_benchmark.py` drives `QaAuditPolicy.source_coverage_for`/
`target_support_for` directly from synthetic gate inputs (mirroring how
`meaning_benchmark.py` drives the comparator directly), plus
`false_positive_metrics()` reporting possible-omission/addition
precision/recall, false rates, legitimate-restructuring false-positive
count, and ambiguity/search-incomplete-to-error leakage separately — not
one generic accuracy number. Current deterministic-baseline self-check:
100% accuracy, zero leakage on both TEST splits.

**Philippians 1:3–6**: ran over the existing `REORDERED` Stage 6B
relationships (Greek 1:3→Tamil 1:6, 1:4→1:4, 1:5→1:3, 1:6→1:5). None of the
19 well-covered content lemmas (the `PHP_PAIRS` fixture used since Stage
6B/7) are falsely flagged `POSSIBLE_OMISSION` despite the cross-verse
reordering. Some genuinely-uncovered function words/particles in the real
UGNT text (not in the 19-pair fixture) do legitimately gate to
`POSSIBLY_MISSING` — correct behavior given the fixture's vocabulary
coverage, not a false positive. No dedicated finding was added for the
ἐπιτελέσει/நடத்தி வருவார் completion-vs-continuation case beyond what Stage 7
already scores (`TARGET_WEAKENS_SPECIFICITY` → `POSSIBLE_UNDERTRANSLATION`
via the generic precedence path) — the spec didn't request a dedicated
completion/continuation finding kind.

**Not implemented** (explicitly out of scope for Stage 8): automatic
Scripture correction, `CorrectionProposal` construction (§19 — untouched),
final QA UI, Scripture Burrito export, new translationCore projection
behavior, a dedicated Stage-8-only performance profiler (only the same
aggregate `elapsedSeconds`/cache-hit tracking every prior stage already
has).

---

# 35. Stage History and Verification

## Stage 1 — Repository analysis only
Found two partially connected alignment architectures and the critical
stale-imported-USFM issue (§23).

## Stage 2 — Technical design only
Chose native translationCore data as compatibility layer plus Bridge
companion semantic graph.

## Stage 2.1 — Design amendment
Added review/lifecycle separation, token lineage/instances, semantic
obligations, coverage accounts, layer-scoped ownership, Unicode contract,
canonical schema, QA disposition, `CorrectionProposal`, and SQLite
guarantees.

## Stage 3 — Data Foundation
Completed. Full Python 347 passed; Focused Stage 3 23 passed; Rust 5
passed; Svelte clean; production build passed.

## Stage 4 — Runtime Integration
Completed. Focused Stage 3/4 59 passed; Full Python 383 passed; Rust 5
passed; Svelte clean; production build passed; real
open→edit→rebuild→reopen fixture passed.

## Stage 5 — Source Inventory
Completed. Focused Stage 5 14 passed (re-measured during Stage 8
verification: **15 passed** — one test appears to have been added since
the original count); Combined Stage 3–5 72 passed; Full Python 397 passed;
Rust 5 passed; Svelte/build passed.

## Stage 6A — Target Inventory
Completed. Focused Stage 6A 12 passed; Full Python 410 passed; Rust 5
passed; cargo check passed; Svelte/build passed.

## Stage 6B — Location Engine
Completed. Full Python 428 passed; Focused Stage 6B 18 passed (re-measured:
**14 passed** — see note above); Rust 5 passed; cargo check passed; Svelte
0 errors/0 warnings; production build passed; `git diff --check` passed;
existing translationCore behavior unchanged. The Stage 6B report noted the
working tree was still uncommitted at the time — always check `git
status`/`git log` rather than assume.

## Stage 7 — Meaning Preservation
Completed — found already implemented and committed (`0289ae5`, "feat: add
semantic meaning preservation analysis") when this repo was checked out for
Stage 8. **No BUILD_LOG.md narrative or session-reported verification
numbers exist for this stage's original landing** — that gap predates
Stage 8 and was not created by it. Measured freshly during Stage 8
verification instead: focused Stage 7 suite **22 passed**. See §32 for the
architecture summary.

## Stage 8 — Bidirectional Source Coverage, Target Support, and Translation QA
Completed 2026-09-02. See §34 for the architecture summary; full narrative
in `docs/BUILD_LOG.md`.

```text
Focused Stage 8:        27 passed
Combined Stage 5–8:      90 passed  (15 + 12 + 14 + 22 + 27)
Full Python suite:      478 passed  (up from 428 at the end of Stage 6B)
Rust (cargo check):     passed
Svelte (npm run check): 0 errors / 0 warnings
Production build:       passed
git diff --check:       passed
```

Stage 6B golden locations and Stage 7 golden meaning statuses verified
unchanged (neither stage's own test file was modified; both suites still
pass as originally written). Existing translationCore behavior unchanged
(no `tc_project.py`/alignment/import code touched).

**Stage 8 has since been committed as `807353d`.** (The original report
left this staged; recorded here so the caveat is not read as still open.)

---

## Stage 9A — Human QA Review, Evidence Inspection, and Disposition
Completed 2026-09-03. Full narrative in `docs/BUILD_LOG.md` (entries 9A.0
through 9A.4, newest first). Earlier commits: `fbd4174`, `92d6c8a`,
`989c81b`, `cd973e2`, `f1529a2`.

Stage 9A makes Stage 5–8 output reviewable by a human. It classifies
findings only — no correction generation, no Scripture edits, no export
changes.

```text
Focused Stage 9A (Python):   45 passed  (34 storage/review + 11 PHP walkthrough)
Frontend (Vitest, new):      97 passed  (9 files)
Full Python suite:          560 passed  (up from 478 at the end of Stage 8)
Rust (cargo check):         passed
Svelte (npm run check):     0 errors / 0 warnings
Production build:           passed
git diff --check:           passed
```

Stage 6B golden locations and Stage 7 golden meaning statuses unchanged
(neither test file modified). Existing translationCore behavior unchanged.
`AlignmentModal.svelte` is mounted unmodified as Word mode; nothing converts
Bridge semantic relationships into native translationCore alignment groups.

### Stage 9A.4 analysis orchestration

Alignment Review QA mode now explicitly runs the existing Stage 5–8 engines
for a current passage, chapter, book, or selected range. Project open only
recovers/reads persisted state and never starts analysis. The durable schema
v9 job records real stage progress (not invented percentages), cache reuse,
run ids, provider capability, warnings/failures, cancellation, and stage/
Stage-8-phase timings. New protocol methods are `analysisJob.start/status/
cancel/getRecent/getScopeStatus`, wired through Python, Tauri and TypeScript.

Target edits make matching jobs stale by current-text fingerprint. Affected
reruns use structural passage boundaries and compose with unchanged cached
results. Normal runtime rejects fixture-only providers; the PHP fixture has
an explicit test-only opt-in. A missing production multilingual provider is
reported as limited capability and does not hide previously persisted
findings. `SEARCH_INCOMPLETE` remains non-omission evidence.

```text
Stage 9A.4 focused Python:    17 passed
PHP 1:3–6 walkthrough:       11 passed
Frontend (Vitest):          104 passed (11 files)
Full Python suite:          577 passed
Rust:                         5 passed; cargo check passed
Svelte/TypeScript:            0 errors / 0 warnings
Production frontend build:   passed
```

### Two defects found by running it, not by reading it

**1. A QA audit made its own project unopenable (Stage 8 defect, fixed).**
`recovery_check()` runs at `FoundationRepository` construction and sets
`read_only` on any integrity problem. Its `known_record_tables` map had no
`QA_RUN` entry, but Stage 8's `save_qa_audit_run` registers `QA_RUN`
dependency edges — so every edge Stage 8 wrote was reported as an unknown
dependency type, the database flipped read-only on the next open, and the
next write failed. Binding project metadata is a write, so **any project
that had run a QA audit could not be opened from its second open onward.**
Introduced by `807353d`; invisible to the suite because tests build a fresh
project per test. Fixed, with regressions covering every dependency type the
engine writes plus one asserting a genuinely unknown type is still reported.

**2. Stage 8 finding ids were not stable (fixed).** `_build_finding` hashed
the *run fingerprint* into every id, so any upstream change minted new ids
and orphaned every human decision recorded against the old ones — which made
"a stale human-confirmed issue is preserved and re-evaluated" unimplementable.
Ids are now keyed on kind + direction + coverage dimension + source unit ids
+ target anchors, excluding the run fingerprint and the engine/policy
versions. What is and is not stable was verified rather than assumed: source
unit ids hash content from a locked resource; target unit ids embed the
per-verse `targetRevision`, so target-support findings anchor on
reference + normalized surface + occurrence instead.

`save_qa_finding` is now an upsert that preserves `qaDisposition`,
`reviewStatus` and `revision` exactly as the reviewer left them, writes
nothing when the machine output is unchanged, and appends a SYSTEM
ReviewRecord when it refreshes an already-decided finding.

### What was added

Schema v8 lifts the queue's ordering/filtering columns out of
`qa_findings.payload_json`. `query_qa_findings()` pages by keyset, not
OFFSET. New `engine/tc_ai_bridge/qa_review.py` exposes
`qaReview.getQueue/getFinding/decideFinding/addNote`,
`semanticReview.decideLocation/decideMeaning` and
`reviewHistory.getEntityHistory`, kept separate from the read-only
`qaAudit.*` analysis methods. `FoundationConflict` surfaces as
`revision_conflict`. Stage 8 had shipped no Tauri commands at all; its seven
`qa_audit_*` commands were added alongside the seven review commands.

Frontend: `AlignmentReview.svelte` (Word/Semantic/Passage/QA tabs) as a new
top-level surface alongside ReviewPanel's per-verse modal, plus
`AlignmentQaMode`, `QaFindingList`, `QaFindingDetail`, `EvidenceInspector`,
`SemanticAlignmentMode`, `PassageAlignmentMode`, `VirtualPassageStream`.
Reviewer-facing wording is centralized in `reviewLabels.ts`: everything
reads as "Possible omission", never "Error"; severity is labelled review
priority; `AI_PROPOSED` renders as "Machine-proposed" because Stages 6B–8
are deterministic.

Stage 8 profiling (the gap the Stage 8 report flagged) is in place:
**Stage 8 is persistence-bound, not analysis-bound** — 81–92% of its runtime
is SQLite writes, because each save opens its own connection and commits
individually. Batching a run's writes would change Stage 8 persistence
semantics and was deliberately not done.

### Verified, and not verified

Verified against the **rebuilt frozen sidecar**, not just in source: queue,
layered evidence, decision, `revision_conflict` on a stale write, and
history all work through `bridge-engine.exe`.

**Not verified: the desktop click-through of the review UI.** The app
builds, launches and renders, the Alignment Review button is present and
correctly wired, and the components are confirmed in the shipped bundle —
but the UI has never been observed rendering a populated queue. jsdom does
not lay out or paint, so the viewport tests assert structure (the action bar
is a sibling of the scrolling region, a 400-row queue windows correctly,
long Tamil is not truncated) rather than measured pixels. **Real 1366×768
behaviour still needs a human pass.**

### Fixture

`scripts/seed_review_fixture.py` builds a real translationCore-compatible
IRV Tamil Philippians project and runs Stages 5–8 over it with a fixture
embedding provider (28 relationships, 12 cross-verse, 12 findings). It mints
the project identity through `ProjectRegistry` rather than hardcoding one —
without that, Bridge refuses the companion database as belonging to a
different project.

`engine/tests/review/test_php_review_walkthrough_stage9a.py` drives the review APIs
over the reordered passage (Greek 1:3→Tamil 1:6, 1:4→1:4, 1:5→1:3, 1:6→1:5)
and imports the seeder, so what a human opens is what the tests assert on.
The load-bearing assertion is that **no `POSSIBLE_OMISSION` is raised for a
source unit that was located** — a reordered translation must not read as a
missing one.

---

# 36. Current Limitations

At the end of Stage 9A:

- no production multilingual embedding model bundled
- Stage 6B location benchmark and Stage 7/8 benchmarks are all
  `MACHINE_PROPOSED` only — none are human-reviewed; do not claim
  production calibration from any of them
- requested passage range is currently a hard computational boundary; full
  automatic structural expansion beyond requested range remains future work
- paragraph/sentence precision depends on available structural metadata
- contextual evidence is stored but zero-weight until calibration supports
  it
- Stage 8's `QaFinding.severity` confidence thresholds (0.85/0.9 cutoffs)
  are uncalibrated, same caveat as every confidence value elsewhere in this
  pipeline
- Stage 8's target-support gate's function-word/explicitation/specificity
  lists are small, deliberately controlled fixtures (mirroring Stage 7's
  own comparator lists) — real-world coverage across languages is
  unvalidated beyond the English/Tamil/Hebrew/Aramaic cases actually tested
- `passage_semantic_models.QaFinding` (Stage 8's output) reaches the UI via
  Stage 9A's Alignment Review surface, *not* via ReviewPanel — it remains a
  deliberately separate model from `greek_room_engine.models.finding.QaFinding`
  (see §34), and the two are still unreconciled. The two review surfaces sit
  side by side; whether they should converge is an open product question
- ~~no correction-generation workflow~~ — built across Stage 9B.0–9B.4:
  wording, review, explicit apply, affected re-analysis, positive semantic
  verification and explicit `CORRECTED` acknowledgement (§37.6). Installed
  desktop acceptance of the verify → Mark corrected flow is not yet run
- Stage 7's `_comparison_norm` splits Indic text at every virama and vowel
  sign, so its whole-token POLARITY check reports a false `CONTRADICTED` on
  Tamil negation. Found during Stage 9B.4, pinned by a test, deliberately
  not fixed there (§37.6) — a fix must re-baseline the Stage 7/8 goldens
- ~~nothing in the app produces Stage 5-8 analysis~~ — resolved by Stage
  9A.4's explicit, persisted background orchestration. Whole-Bible scope is
  still deferred, and normal projects visibly use limited lexical/structural
  retrieval until a production multilingual embedding provider is configured
- the Stage 9A review UI has **never been observed rendering a populated
  queue in the desktop app**; jsdom cannot lay out or paint, so small-screen
  behaviour at 1366x768 is asserted structurally only
- reviewer identity is the single local string `"human"`; `TeamWorkflow` in
  `team.py` is not wired into semantic review records
- ~~no final Alignment Review UI~~ — built in Stage 9A (review only; see
  the unverified-click-through caveat in the Stage 9A record above)
- no Scripture Burrito export
- no new native translationCore projection behavior
- ~~no narrative for Stages 4 through 7~~ — retrospective entries added in
  Stage 9A.0, explicitly marked as reconstructed from commits, code and
  tests, and limited to what those verify

---

# 37. Stage 9B.0 Baseline for Correction Wording

**Stage 9B.0 (schema/API design and dependency repair) is DONE** as of
2026-09-04. It was explicitly scoped to the backend foundation and stopped
there. Stage 9B.1 was subsequently reviewed, explicitly approved, and completed;
see the Stage 9B.1 record below.

## What 9B.0 delivered

Full engineering narrative in [`BUILD_LOG.md`](BUILD_LOG.md) under "Stage 9B.0
— correction schema/API design and dependency repair". Summary:

- **Nothing in this stage can alter Scripture.**
  `test_stage_9b0_never_alters_scripture` hashes chapter JSON, preserved
  imported USFM and alignment data and asserts they are byte-identical after
  everything 9B.0 can do. No frontend file was touched; `[Create Correction
  Proposal]` is not exposed.
- **`CorrectionProposalV2`** (`proposalSchemaVersion` 2) alongside preserved
  v1, answering §37's old open question 2. Carries `CorrectionIntent`
  (`failedDimension` reusing `CoverageDimension`, observed vs required
  meaning, affected source units) and `AffectedTargetSpan` (exact half-open
  code-point span + `targetTextRevision`/`targetContentHash`). `proposedText`
  may be empty **by design** — 9B.0 records *what must change*, 9B.1 decides
  *how to say it*.
- **Schema v11.** Legacy v1 proposals stay readable with history intact,
  stamped schema v1 and `applicable=0`. Bridge does **not** infer spans
  retroactively; a legacy proposal must be explicitly recreated against
  current text before it can ever be applied.
- **`correction_eligibility.py`** — one authoritative
  `evaluate(finding_id)`. The frontend must never re-derive this. Returns
  structured reasons and accumulates every blocker rather than
  short-circuiting. `NOT_LOCATED` is deliberately *not* blocked: a confirmed
  genuine omission is exactly what a correction should be able to fix.
- **Current-text validation** now re-reads authoritative chapter JSON, not
  just the finding's snapshot (§37 old open question 4 is closed for the
  read path). Exact comparison only — no fuzzy matching anywhere.
- **Dependency graph repaired.** The record-type→table map was three
  hand-maintained copies; now one `RECORD_DEPENDENCY_TABLES` constant with a
  source-scanning invariant test. Added the missing `LOCATION_RELATIONSHIP →
  LOCATION_RUN` edge plus meaning/finding/proposal edges. The invariant test
  caught a latent crash in `_stale_generic_dependencies` (see BUILD_LOG).
- **`record_correction_applied` neutralized.** It used to flip a finding
  straight to `CORRECTED`. Renamed to
  `record_correction_application_metadata` (old name kept as an alias); it
  now records metadata, sets verification `PENDING`, marks the finding STALE,
  and leaves the human's disposition alone.
- **`VerificationStatus`** (NOT_RUN/PENDING/PASSED/FAILED/UNCERTAIN),
  independent of `QaDisposition`. Invariant: **applied ≠ corrected**.
  `CORRECTED` stays unreachable until a later stage supplies
  `verificationStatus == PASSED` *plus* explicit human acknowledgement.
- **`CorrectionApplicationIntent`** + `correction_application_intents` table —
  design/schema groundwork only, nothing writes Scripture through it.
  `APPLIED_SCRIPTURE` is deliberately distinct from `COMPLETED`.
- **API:** `correction.getEligibility`, `correction.getProposal`,
  `correction.listForFinding` — read-only. **`correction.applyProposal` does
  not exist and must not be added before 9B.3.**

Tests: `engine/tests/correction/test_correction_stage9b0.py`, 55 passing.

## Historical blockers recorded before Stage 9B.1

1. **Resolved in Stage 9B.1: Rust gates.** `cargo check` / `cargo test` could not
   run: a live `tauri dev` session held the sidecar binaries and
   `tauri_build::try_build` failed with `PermissionDenied`. Stage 9B.0 touched
   no `.rs` or `tauri.conf.json` file, so this is contention rather than a
   regression. Both are now green with no dev session active.
2. **`apply_scripture_edit()` has no strict mode.** It takes no
   `expected_target_revision`, `expected_target_content_hash` or
   `expected_old_text`, so it cannot fail closed on a concurrent edit.
   `test_apply_scripture_edit_still_lacks_the_strict_preconditions` pins this
   and will fail the moment those parameters land — that is 9B.3's signal to
   update it. **Required before 9B.3, not before 9B.1.**
3. **Resolved in Stage 9B.1: wording-generation contract.** The provider,
   provenance, alternatives, evidence, edit/reject/regenerate, CAS, and exact
   pre-persistence recheck contract is recorded below.
4. **Resolved 2026-09-08: the resource-conflict rule was reading the wrong
   field.** Any entry in `conflictingEvidenceIds` blocked eligibility, and
   Stage 7 files *meaning-failure* evidence there. Genuine resource
   disagreement now has its own field, `resourceConflictEvidenceIds`, and only
   that (plus a live CONFLICTING resource record) blocks. Details in
   BUILD_LOG, "Meaning failure is not resource disagreement".
5. **The Stage 9A review UI still has not had a human click-through** on a
   populated queue (carried over from the previous §37).

## Queued change that touches the §39 boundary — DECIDED 2026-09-09

Issue **#28** (tN/tW auto-apply above 85% confidence) is filed and approved in
principle, and carried one decision open: whether "confidence alone decides"
also removes the rule that AI never overwrites an imported or human-made
selection.

**The project owner settled this on 2026-09-09: the overwrite protection is
KEPT.** "Confidence alone decides" applies to **empty** selections only.

In scope for #28 — raise the bar to `> 0.85` and drop the four supporting
policy gates (evidence non-empty, Stage 3 `native_tc_apply_allowed`,
verdict/nothing-to-select coherence, contradictory-QA at >= 0.75).

Out of scope, and staying — AI never overwrites a tN/tW selection that was
imported or made by a human. `save_check_selection()` keeps that protection and
`test_basic_ai_never_overwrites_a_human_selection` stays as its regression
cover.

That rule is not an implementation detail. §39 lists *silently overwrite
human-approved work* in the hard do-not list and *protect human decisions* in
the do list. Dropping the evidence / Stage 3 mapping / contradictory-QA
**policy** gates does not conflict with §39. Dropping the **overwrite
protection** would have, which is why it needed an explicit call rather than
being settled while coding.

Resulting behaviour: a >85% proposal auto-applies where nothing has been
selected yet; where a human or the import already chose, the proposal still
requires the manual button regardless of confidence.

Implementation has **not** started. `engine/bridge_service.py:1869` still reads
`if float(review.confidence or 0.0) < 0.82:` inside
`_safe_ai_selection_reason()` (line 1856), with `native_tc_apply_allowed`
imported at line 105 and applied at line 1874. The project board wrongly showed
#28 as Done; it was moved back to Backlog on 2026-09-09. The decision is
recorded on the issue as well.

Note that #28 concerns the `tc_ai_bridge` AI review path (tN/tW selections),
not the Stage 5-9 passage-semantic pipeline — but it moves the same
human-versus-AI authority boundary this document governs, which is why it is
noted here.

## Scope reminder for 9B.1

9B.1 is **wording generation only**. Do not implement correction UI,
Scripture application, or post-correction rerun — those are 9B.2/9B.3/9B.4.
The exact-span contract (half-open Unicode code-point offsets, `[n, n)` valid
for insertion) is fixed; do not reinterpret it as UTF-16 or grapheme offsets.

The Stage 9B pipeline as a whole remains:

```text
confirmed issue
  ↓
suggest correction            ← 9B.1
  ↓
show current/proposed text + evidence   ← 9B.2
  ↓
human apply/edit/reject       ← 9B.3
  ↓
affected records STALE
  ↓
realign
  ↓
rerun meaning
  ↓
rerun QA                      ← 9B.4
```

Still-open questions carried forward from before 9B.0:

1. **QaFinding UI path.** Whether `passage_semantic_models.QaFinding` gets
   normalized into `greek_room_engine.models.finding.QaFinding` for
   ReviewPanel visibility, gets its own surface, or both stay separate. A
   real, deliberate fork (§34) — not an oversight to paper over.
2. **Human confirmation transitions.** `POSSIBLY_MISSING → MISSING` and
   `POSSIBLY_UNSUPPORTED → UNSUPPORTED` are reachable only via
   `update_qa_disposition`'s promotion path, not a dedicated status-promotion
   API. Decide whether Stage 9B needs one.
3. Preserve existing Scripture and translationCore behavior. Continue
   test-first and stop at stage boundaries.

If repository reality conflicts with this document, report the conflict
instead of silently changing assumptions (§39).

---

# 37.1 Stage 9B.1 — Correction Wording Generation (Complete, 2026-09-05)

Implemented against `main` at baseline `5df5c0d`; the Project QA Report merged
after the older Stage 9B.0 checkpoint was treated as frozen behavior. No
Project QA Report, frontend, Rust, Scripture, translationCore, analysis, or
export file was changed for Stage 9B.1.

The completed boundary is:

```text
confirmed QA issue
  -> backend eligibility
  -> exact CorrectionIntent
  -> human wording (offline) OR optional provider suggestion
  -> persisted proposal
  -> edit / reject / regenerate proposal data
```

Key implementation facts:

- `tc_ai_bridge/correction_wording.py` owns the wording service and narrow
  provider protocol. Implementations are `NoCorrectionSuggestionProvider`,
  deterministic `FixtureCorrectionSuggestionProvider`, and
  `ConfiguredCorrectionSuggestionProvider`, which adapts Bridge's existing
  Responses-compatible client without coupling persistence to OpenAI.
- Human-authored wording works with no API key, model, or network. If a
  suggestion is requested but the provider is unavailable, supplied human
  wording is saved with `PROVIDER_UNAVAILABLE`; an empty request fails closed.
- Provider context is limited to the correction intent, current exact target
  verse/span, relevant passage references, Stage 6B locations, Stage 7 meaning,
  Stage 8 QA/coverage, and relevant resource evidence. Credentials are never
  part of the context or persisted metadata. The existing privacy-manifest
  mechanism records the sent field classes and confirms no unrelated project
  files are included.
- Generation is constrained to repair the confirmed failed semantic dimension,
  preserve unaffected meaning and target-language naturalness, and make the
  smallest defensible change. Output remains a suggestion; it cannot approve
  itself, mutate alignment, change QA disposition, or change Scripture.
- Creation modes are independent of review/lifecycle/disposition/verification:
  `HUMAN_AUTHORED`, `MACHINE_SUGGESTED`, and
  `MACHINE_SUGGESTED_HUMAN_EDITED` (legacy values remain readable).
- A proposal contains one primary wording and zero or more alternatives. The
  alternatives inherit the proposal's one exact `CorrectionIntent`, target
  span, revision, and hash, and retain their own wording, explanation,
  evidence, creation mode, and provider metadata. A different span requires a
  different proposal/intent.
- Eligibility and exact current target text are checked before generation and
  again immediately before persistence, closing the provider-latency window.
  Repository insertion also rejects a competing ACTIVE/INACTIVE owner inside
  the same SQLite transaction. There is no fuzzy relocation.
- Editing requires exact proposal CAS and a current ACTIVE proposal. Editing a
  machine suggestion preserves `originalSuggestedText` and records the new
  creation mode. Rejection sets `HUMAN_REJECTED` + `INACTIVE` without deleting
  wording. Regeneration atomically marks the old proposal `SUPERSEDED` and
  inserts a new record with `supersedesProposalId`.
- Companion database schema is now **v12**. The append-only
  `correction_proposal_events` table records `CREATED`, `SUGGESTED`, `EDITED`,
  `REJECTED`, `SUPERSEDED`, and `STALE` with actor, timestamp, base/new
  revision, reason, provider metadata, and full proposal snapshot. Migration
  backs up first and adds a `MIGRATION`-actor creation snapshot for pre-v12
  proposals rather than inventing a human action.
- Python protocol additions: `correction.createProposal`,
  `correction.editProposal`, `correction.rejectProposal`,
  `correction.regenerateProposal`, and `correction.getProposalHistory`.
  Existing get/list/eligibility methods remain. **There is still no
  `correction.applyProposal`.**
- Exact spans remain half-open Unicode code-point coordinates
  `[startCodePoint,endCodePoint)`. A genuine omission remains a zero-length
  insertion `[n,n)` with empty `originalText`; Tamil combining sequences,
  Hebrew marks, Greek diacritics, and supplementary-plane text are covered.

Verification on 2026-09-05:

```text
Stage 9B.1 focused Python                 33 passed
Full Python (engine + Greek Room)        705 passed
Frontend Vitest (incl. Project report)   151 passed / 17 files
npm run check                            0 errors / 0 warnings
npm run build                            passed (existing chunk-size warning)
cargo test                               6 passed
cargo check                              passed
git diff --check                         passed (line-ending notices only)
```

The Stage 9B.0 Rust contention blocker is closed. Installed desktop acceptance
was not part of this backend-only stage. The pre-existing coarse resource
conflict policy remains deliberately conservative.

## Next boundary at the Stage 9B.1 checkpoint: Stage 9B.2 only

Stage 9B.2 may present current/proposed wording, alternatives, evidence,
provenance, history, and edit/reject/regenerate controls. It must not add an
Apply action, mutate Scripture/translationCore data, rerun Stages 6B–8, mark a
finding `CORRECTED`, or change export behavior. Stage 9B.2 requires explicit
approval before implementation. That approval was subsequently given and the
completed Stage 9B.2 boundary is recorded below.

---

# 37.2 Stage 9B.2 — Correction Review UI (Complete, 2026-09-05)

Stage 9B.2 connects the Stage 9B.1 proposal lifecycle to the authoritative
`Alignment Review -> QA -> finding detail` workflow. A reviewer can now confirm
a translation issue, create a human-authored correction offline or request an
optional configured-provider suggestion, and inspect/edit/reject/regenerate
proposal data without changing Scripture.

### Runtime/UI architecture

- `CorrectionReviewPanel.svelte` is embedded after the existing Stage 6B–8
  evidence/history in `QaFindingDetail.svelte`; it is not a disconnected
  correction application. Confirming a finding keeps it selected and its new
  finding revision forces a fresh backend eligibility check.
- Svelte calls `correction.getEligibility` as the sole eligibility authority.
  Ineligible findings show backend reason text (stale finding, ambiguous or
  rejected mapping, preserved-meaning override, resource conflict, and similar
  blockers) instead of silently hiding the workflow. Existing proposals remain
  visible history but become non-current when those blockers appear.
- A narrow read-only `correction.getReviewContext` boundary resolves Stage 6B
  span IDs through the persisted target inventory and then re-reads the current
  editable target text. It supplies per-reference current content hash/revision
  and exact half-open Unicode code-point coordinates. Recorded quote mismatch
  drops the candidate rather than fuzzy-relocating it. No imported-USFM wording
  is reintroduced.
- The Python protocol is wired through Rust/Tauri and typed TypeScript client
  methods for eligibility, review context, get/list, create, edit, reject,
  regenerate, and history. Provider-bearing create/regenerate calls have the
  existing AI network timeout class; read/edit/reject remain interactive.
- Manual proposal creation stays available without an API key. “Suggest
  wording” is shown only when a provider is configured, sends the exact reviewed
  intent/span through Stage 9B.1, and returns a proposal requiring human review.
- Existing proposal review shows current verse/context and highlighted exact
  span (or an explicit `[n,n)` insertion caret), proposed text, alternatives,
  reason, affected semantic dimension, source evidence, Stage 6B location,
  tN/tW/TWL resources, truthful machine/human provenance, supersession, and
  append-only event history.
- Editing uses proposal revision CAS. A conflict reloads the current record and
  tells the reviewer instead of retrying or overwriting. Rejection retains the
  proposal/evidence/note/history. Regeneration uses Stage 9B.1 supersession and
  keeps every prior proposal.
- `unicodeDiff.ts` converts persisted code-point coordinates safely and diffs
  grapheme clusters with `Intl.Segmenter` (code-point-safe fallback). Tests pin
  Tamil combining text, Hebrew points, Greek diacritics, supplementary Unicode,
  insertion, deletion, and replacement.
- The panel has independently scrolling evidence/proposal content and a sibling
  sticky action region. Controlled long-content fixtures exercise 1366 px and
  820 px widths, long Tamil, long evidence, many alternatives and long history;
  the existing QA list test keeps 1,000 rows virtualized.

### Safety boundary and compatibility

There is still no `correction.applyProposal`, `apply_scripture_edit()`,
Scripture or translationCore mutation, post-edit Stage 6B/7/8 run, `CORRECTED`
transition, or export change. UI regression tests assert that no functional
Apply/Save/Replace-Scripture control exists. The companion database remains
schema **v12**; Stage 9B.2 adds no migration. The Project QA Report Python,
Rust, Svelte and documentation behavior remains a frozen regression boundary
and no report implementation file was modified.

Controlled acceptance fixtures cover a confirmed quantity issue through
proposal/edit/history, a confirmed omission using a zero-length insertion, and
the PHP 1:3 source meaning grounded at one unambiguous PHP 1:6 target span. The
cross-verse case retains canonical semantic scope and never manufactures a
same-verse lexical alignment.

Verification on 2026-09-05:

```text
Stage 9B.2 focused frontend              68 passed / 6 files
Stage 9B.0 + 9B.1 focused Python        90 passed
Stage 5–9A.4 + Project Report backend   211 passed
Project Report focused frontend          19 passed
Full Python (engine + Greek Room)        707 passed
Full frontend Vitest                     176 passed / 19 files
npm run check                            0 errors / 0 warnings
npm run build                            passed (existing chunk-size warning)
cargo test                                7 passed
cargo check                              passed
git diff --check                         passed (line-ending notices only)
```

Installed/manual limitation: these acceptance paths were exercised with
controlled runtime/UI fixtures and production compilation, not in an installed
WebView2 build against a disposable real project. A real-window visual pass at
1366x768/narrow width and provider-backed suggestion should be performed before
release packaging.

## Next boundary: Stage 9B.3 only

Stage 9B.3 is the first possible explicit human Apply boundary. It must design
and test strict current-text/proposal CAS, durable crash recovery, deliberate
Scripture mutation, complete dependent-record staling, and rollback before any
Apply control is exposed. Do not add application, realignment, Stage 6B–8
reruns, `CORRECTED`, or export work without explicit approval.

---

# 37.3 Stage 9B.3a — Strict Persistence, Recovery, and Invalidation Foundation

Stage 9B.3a is complete on the Stage 9B.2 checkpoint `c0d0151`. It adds the
durable safety foundation for a future explicit correction Apply, but it still
does not expose Apply or write Scripture.

### Schema v13 and application ledger

The passage-semantic companion database is now schema **v13**. Migration v13
backs up the existing SQLite database, gives token instances explicit
`lifecycleStatus`/`revision`, adds target-token and target-semantic-unit
dependency edges, and rebuilds `correction_application_intents` around an exact
immutable mutation snapshot. Legacy design-only application rows are retained
as `RECOVERY_REQUIRED`; missing hashes or coordinates are never inferred.

Each application persists the proposal/finding revisions, target and canonical
references, separate source-provenance references, current target revision and
hash, half-open Unicode code-point span and original text, replacement
snapshot, intended final hash, prepared invalidation ID, translationCore
journal ID, explicit actor, timestamps, failure/recovery/result metadata, and
state revision. `UNIQUE(proposal_id, expected_proposal_revision)` makes retries
idempotent. Repository writes use `BEGIN IMMEDIATE`, foreign keys, and revision
CAS. The durable state machine is:

```text
PREPARED -> APPLYING -> APPLIED_SCRIPTURE -> INVALIDATED -> COMPLETED
    |           |               |                |
    +---------- FAILED          +----------------+-> RECOVERY_REQUIRED
```

Invalid transitions and stale state revisions fail explicitly. A duplicate
request in PREPARED, APPLYING, APPLIED_SCRIPTURE, or COMPLETED returns the same
application; it cannot create a second insertion opportunity.

### Startup and crash recovery

Project open now performs recovery in this order:

```text
construct TranslationCoreProject
-> recover incomplete translationCore filesystem journals
-> stop in RECOVERY_REQUIRED if rollback is incomplete
-> construct PassageSemanticRuntime
-> replay prepared target invalidations
-> synchronize current editable JSON text
-> reconcile incomplete correction applications
-> expose the project
```

Semantic initialization therefore never fingerprints a known partially written
chapter. A failed filesystem rollback leaves review/read paths available but
sets `correctionWritesBlocked=true` and does not construct the semantic runtime.

`CorrectionApplicationRecoveryCoordinator` is hash-exact and contains no
writer. Current hash equal to the before hash means no committed correction;
an interrupted PREPARED/APPLYING attempt becomes FAILED. Current hash equal to
the intended-after hash is never applied again: recovery only completes the
prepared semantic invalidation and idempotent proposal/finding bookkeeping.
Proposal verification becomes PENDING, the old finding remains historical,
and its QA disposition is not changed to CORRECTED. A hash matching neither
snapshot, a journal/hash contradiction, an unrecoverable invalidation, or
conflicting proposal finalization enters RECOVERY_REQUIRED. Successfully
committed Scripture is never automatically rolled back because later semantic
work failed.

The crash matrix covers no PREPARED record, after PREPARED, filesystem writing,
filesystem rollback, committed Scripture before invalidation, invalidation
before finalization, proposal metadata before ledger finalization, and
before/during affected analysis. Stage 9B.3a does not start affected analysis;
the completed attempt records `affectedAnalysisStarted=false`.

### Currentness, backups, and compatibility

Target token instances are immutable historical identities with explicit
ACTIVE/STALE lifecycle and revision. Target tokens depend on
`TARGET_REFERENCE`; target semantic units depend on `TARGET_INVENTORY`. A
target edit stales both children while source token history remains ACTIVE.
Rebuilding the exact same content-addressed inventory may reactivate its exact
instances without relocating human work. The shared dependency-type invariant
now scans every Python module that writes dependency edges and includes
`TOKEN_INSTANCE`.

The existing SQLite backup/integrity path can record a pre-mutation backup
path, SHA-256, timestamp, and application ID. The strict future writer context
is defined for Stage 9B.3b, including exact target revision/hash, original verse
and span, intended final verse, invalidation ID, and application ID. It is not
accepted by or passed to `apply_scripture_edit()` yet. The future implementation
must preserve the composed verse byte-for-byte and must not call `.strip()`.

No correction API, Rust command, or frontend Apply control was added. Existing
`apply_scripture_edit()`, translationCore alignment invalidation,
`bottomWords`/word-bank reconciliation, edit audit, imported USFM, and export
behavior are unchanged. The PHP regression retains source provenance PHP 1:3
and editable target PHP 1:6 without inventing a same-verse lexical alignment.
The full gate also exposed a Windows checkout defect in the independently
hash-verified Strong's provenance files: `.gitattributes` now preserves the
vendored Hebrew and Greek lexicon directories byte-for-byte, matching the
existing UHB/UGNT protection. No resource content changed.

Verification on 2026-09-05:

```text
Stage 9B.3a focused Python               34 passed
Stage 9B.0 + 9B.1 Python                 90 passed
foundation/runtime Python                61 passed
Stage 5-8 Python                         90 passed
Stage 9A.4 + Project QA Report Python   126 passed
frontend Vitest                         176 passed / 19 files
npm run check                            0 errors / 0 warnings
npm run build                            passed; existing >500 kB chunk warning
cargo test                                7 passed
cargo check                              passed
git diff --check                         passed; line-ending notices only
full Python + Greek Room                742 passed
```

Installed desktop acceptance is not part of this non-mutating foundation
checkpoint.

### Next boundary: Stage 9B.3b only

Stage 9B.3b may implement the explicit human application command and strict
mode on the one canonical `apply_scripture_edit()` path. It must re-run
eligibility immediately before mutation, verify every persisted snapshot and
the one-verse/one-span boundary, prepare the semantic invalidation and backup
before the edit, and retain the v13 recovery protocol. It must not silently
relocate spans, introduce a second Scripture writer, mark CORRECTED, or start
Stage 6B-8 reruns unless separately approved.

# 37.4 Stage 9B.3b — Strict Explicit-Human Correction Application

Stage 9B.3b is implemented on the schema-v13/`189b5d8` foundation. It adds the
first Scripture-changing correction action, but only behind an eligible,
ACTIVE, human-reviewed v2 proposal and a dedicated confirmation dialog.

The application service reloads proposal/finding state, re-runs backend
eligibility while ignoring only the proposal being applied, checks revisions,
and validates the exact target revision, SHA-256, Python code-point span and
original text. It atomically persists the application plus PREPARED
invalidation and a checksummed semantic DB backup before delegating the exact
composed verse to `BridgeEngine.edit_verse()` →
`TranslationCoreProject.apply_scripture_edit()`. Strict mode never strips,
fuzzy-matches, or relocates reviewed text and adds no second Scripture writer.

The canonical writer retains translationCore reconciliation, invalid marker,
completed-marker removal, word-bank movement, verse-edit audit, tN/tW
`verseEdits`, filesystem backup and journal rollback. The journal is linked to
the application/proposal and intended final hash. Application states advance
by CAS through PREPARED, APPLYING, APPLIED_SCRIPTURE, INVALIDATED and
COMPLETED. Duplicate/retried requests use proposal ID plus reviewed proposal
revision and cannot apply an insertion twice.

After commit, semantic invalidation stales dependent target and Stage 6B-8
records without deleting history. Verification remains PENDING; the finding
becomes STALE while retaining CONFIRMED_TRANSLATION_ERROR. No analysis starts,
no verification verdict is invented, and CORRECTED is never written.

The UI exposes `Review application` only for current eligible
HUMAN_MODIFIED/HUMAN_APPROVED wording. Its modal shows refs, exact target/span,
CURRENT, PROPOSED FINAL, Unicode-safe diff, and alignment/verification
warnings. Only `Apply correction` invokes the new API. Both approved APIs are
wired through Python, Rust/Tauri and TypeScript.

Focused tests cover Tamil, pointed Hebrew, decomposed Greek, supplementary
Unicode, replacement/insertion/deletion, retry idempotency, edit conflicts,
USFM/unrelated-verse preservation, alignment invalidation, stale finding state
and PENDING verification.

### Next boundary: installed Stage 9B.3b acceptance, then Stage 9B.3c only

Use a disposable project for confirmation, exact mutation, alignment state,
restart persistence and concurrent-edit rejection. Do not begin affected
analysis until this checkpoint is reviewed and explicitly approved.

# 37.5 Stage 9B.3c — Affected Re-analysis After Human Apply

Stage 9B.3c is implemented on baseline `4e5a94a` without a schema migration;
the semantic foundation remains at **v13**. It adds no automatic analysis to
`correction.applyProposal`. A reviewer must explicitly select **Re-analyze
affected passage** after a correction application is COMPLETED while semantic
verification is PENDING.

`CorrectionAffectedScopeResolver` reconstructs the minimum safe structural
scope from the durable application, proposal, original finding and source
semantic units. The frontend supplies only the application ID and actor. The
backend retains source and target provenance independently, normalizes display
references through the existing project versification, expands through
preserved structural markers, and always rebuilds analysis text from the
managed project's current editable chapter JSON. For the regression fixture,
source `PHP 1:3` and edited target `PHP 1:6` resolve to `PHP 1:3–1:6`; no
same-verse source relationship is manufactured.

`CorrectionAffectedAnalysisService` seals that range into the existing
Stage 9A.4 `AnalysisJobManager`. There is still one Stage 5–8 pipeline: the
source inventory can be reused when its fingerprint is current, while target
inventory, location, meaning and QA are content-addressed against corrected
target hashes. The application-to-job association is CAS-appended to existing
v13 result metadata with source refs, target refs, structural range, target
revision/hash and analysis fingerprint. Running/completed equivalent jobs are
idempotently rediscovered; failure, cancellation and incomplete search require
an explicit Retry. Existing job recovery and cancellation semantics apply.

The Correction panel displays three independent states: correction
application, semantic verification and affected analysis. It restores the
associated job after restart, uses truthful stage-level progress, refreshes the
current scoped QA data on completion, and does not replace the reviewer's
manually selected QA range. Where relationship evidence exists it shows source
and target references, grouped cardinality and movement properties. Null-side
relationships remain semantic endpoints (`NOT_LOCATED`, grammatical/context
support, and related states), never automatically an omission or addition.

Successful, failed, cancelled and incomplete re-analysis all leave the
application COMPLETED, verification PENDING, the original finding STALE with
CONFIRMED_TRANSLATION_ERROR, and Word Alignment invalid/reviewable. Historical
tokens, semantic units, relationships, assessments and findings are retained.
No Stage 9B.3c operation writes Scripture or sets CORRECTED.

```text
Stage 9B.3c focused Python                9 passed
Stage 9B.3b focused Python               13 passed
full Python + Greek Room                765 passed
frontend Vitest                         192 passed / 19 files
npm run check                            0 errors / 0 warnings
npm run build                            passed; existing >500 kB warning
cargo test                                7 passed
cargo check                              passed
git diff --check                         passed; line-ending notices only
```

**Acceptance-claim correction (see §37.7).** The Stage 9B.3b and 9B.3c
installed acceptances below used a controlled **pre-seeded** finding whose
`targetContentHashes` already matched the Stage 9B reader contract. They
validated the application transaction, exact Scripture mutation, invalidation,
affected re-analysis, cross-verse provenance and persistence/recovery -- but
they did not, and could not, prove that a finding naturally emitted by
production Stage 8 reaches Stage 9B. Do not describe them as fully production
end-to-end.

Installed acceptance must use a fresh disposable import that Bridge copies to
its managed runtime project directory. Complete an explicit Apply, confirm
Word Alignment is invalid and verification PENDING, run affected re-analysis,
observe Stage 6A/6B/7/8, confirm the PHP 1:3 → 1:6 provenance and scope, then
restart and verify the application/job/history persist. Installed acceptance
has not been claimed by the repository test suite. On the current development
workstation, the fresh source fixture is
`C:\Users\Benz\Bridge-Test-Projects\stage9b3c-affected`; import it into Bridge
before testing so the managed copy, not this source directory, is exercised.

## Stage 9B.3c completion note

Stage 9B.4 was subsequently approved and completed; see §37.6 below. The
version metadata in this section and in the Beta 15 note below is historical:
the repository is now at **0.9.1**, three releases past `0.8.0-beta.15`.

# 37.6 Stage 9B.4 — Positive Semantic Verification and Explicit CORRECTED

Stage 9B.4 is implemented on baseline `6631a07` (application version 0.9.1).
It closes the Stage 9B pipeline: an applied, re-analyzed correction can now be
positively verified against current evidence, and only an explicit human
acknowledgement of a PASSED verification may reach `CORRECTED`.

### The governing principle

A correction is **not** verified because a finding disappeared. Verification
asks one question:

```text
Is the original failed semantic obligation now positively satisfied by
CURRENT post-correction evidence?
```

Three rules follow, and all three are covered by tests:

- **Finding disappearance alone proves nothing.** A fixture whose current QA
  run emits no finding at all still verifies FAILED when the current meaning
  evidence still contradicts the required meaning.
- **Finding presence alone proves nothing.** A recurring finding — including
  the *same stable finding id* — never by itself produces FAILED.
- **Recurrence is matched on semantic identity**, not on the id: source
  semantic units plus coverage dimension. A finding that recurs on a
  *different* dimension does not decide this correction's verdict; one that
  recurs on the *same* obligation and dimension while the component evidence
  says preserved forces UNCERTAIN, because two current assessments disagree.

### Four states stay independent

`CorrectionApplicationState`, the affected-analysis state, `VerificationStatus`
and `QaDisposition` are separate fields, separate rows in the panel's status
list, and are never collapsed into one badge.

### Architecture

`tc_ai_bridge/correction_verification.py` owns the whole stage.
`CorrectionVerificationService` resolves everything it needs from durable
records — application, proposal intent (failed `CoverageDimension`, observed
and required meaning, affected source semantic unit ids, exact target span),
original finding, the associated affected-analysis job, and the Stage 6B/7/8
runs that job produced. It trusts no frontend-supplied conclusion; the UI
supplies only an application id and an actor.

Preconditions keep verification `PENDING` and record nothing:

```text
application != COMPLETED        -> APPLICATION_NOT_COMPLETED
correction recovery blocked     -> RECOVERY_REQUIRED
no associated analysis job      -> ANALYSIS_NOT_RUN
job QUEUED/RUNNING              -> ANALYSIS_RUNNING
job FAILED / CANCELLED          -> ANALYSIS_FAILED / ANALYSIS_CANCELLED
job target hash != current hash -> ANALYSIS_NOT_CURRENT
```

**Technical analysis failure is never semantic verification failure.** Every
run reader (`semantic_location_run`, `meaning_analysis_run`, `qa_audit_run`)
already refuses a non-ACTIVE run, so evidence superseded by a later edit can
never be presented as current.

`CorrectionVerificationPolicy` (`correction-verification-policy-v2`) is the one
versioned place deciding PASSED/FAILED/UNCERTAIN, per source obligation and
then aggregated (any FAILED wins; else any UNCERTAIN; else PASSED).

### Dimension-specific verification

Stage 7 scores a source unit only on *that unit's own* coverage dimension, but
the reviewer chooses the failed dimension when authoring the correction, so the
two need not match — a QUANTITY correction may be recorded against a
`LEXICAL_CONTENT` unit, and Stage 7 then holds no quantity component at all.
Verification therefore adds a **dimension-targeted recheck**: the *same*
versioned `DeterministicMeaningComparator` re-applied to the current located
source and target text for exactly the corrected dimension. This is not a
second meaning engine and it never overrides a persisted component —
disagreement between the two becomes UNCERTAIN
(`CONFLICTING_CURRENT_ASSESSMENT`), never a silent win for either.

Covered by a regression matrix: `LEXICAL_CONTENT`, `POLARITY`, `QUANTITY`,
`PARTICIPANT`, `REFERENT`, `TEMPORAL_ASPECTUAL`, `PREDICATION`.

### Null alignment and cardinality

`1 -> null` is not automatically failure: a `GRAMMATICALLY_REALIZED`,
`PRONOMINALIZED`, `IMPLICIT` or restructured realization with
`COVERED_BY_RESTRUCTURING` coverage passes. It becomes `COVERAGE_STILL_MISSING`
only when Stage 8 positively concluded the obligation is uncovered *and* the
search was not incomplete.

The pre-installed-acceptance gate on 2026-09-07 found the first release of this
stage did not honor that rule, and fixed it. `POSSIBLY_MISSING` had been grouped
with `MISSING` in one `_NEGATIVE_COVERAGE` set, so an *unresolved* candidate
omission could reach FAILED on its own — the `POSSIBLY_MISSING → MISSING`
auto-promotion §39 forbids and §36 reserves for human confirmation. Coverage is
now split three ways:

```text
COVERED / COVERED_BY_RESTRUCTURING  -> may support PASSED
MISSING                             -> may support FAILED  (positive absence)
POSSIBLY_MISSING / UNCERTAIN        -> always UNCERTAIN    (unresolved)
NOT_CHECKED                         -> no coverage claim; does not veto
```

`NOT_CHECKED` stays outside the unresolved set deliberately: it means Stage 8
made no coverage claim at all, which must not veto positive dimension evidence,
whereas `POSSIBLY_MISSING` and `UNCERTAIN` mean Stage 8 looked and could not
resolve. Two reason codes carry the distinction to the reviewer,
`COVERAGE_POSSIBLY_MISSING` and `COVERAGE_UNRESOLVED`.

The same gate found run-level `searchIncomplete` only ever downgraded a PASSED.
An absence-based FAILED — one whose reason codes are nothing but
`COVERAGE_STILL_MISSING` — is now downgraded to UNCERTAIN under an incomplete
search too, since the realization may lie in the passage the search never
reached. A located contradiction is unaffected, so a run mixing the two still
fails. The policy version moves to `correction-verification-policy-v2`, which
makes any verification recorded under the old rule non-current and
re-evaluatable rather than silently carrying a wrong verdict forward.

`null -> 1` is not automatically an unsupported addition: target units inside
the exact corrected span are checked against their current target-support
account, and `SOURCE_SUPPORTED` / `CONTEXT_SUPPORTED` /
`GRAMMATICALLY_REQUIRED` / `EXPLICITATION_SUPPORTED` are legitimate. Only an
unresolved support state downgrades to UNCERTAIN.

Post-correction cardinality need not match the original: the record stores the
observed cardinality per relationship rather than asserting one.

### COMPLETED_WITH_WARNINGS

Not mapped to UNCERTAIN automatically. `PROVIDER_LIMITED` (no production
multilingual embedding provider) lowers confidence and is always recorded, but
only downgrades a PASSED verdict when the deciding evidence is *not*
deterministic. Deterministic quantity/polarity/participant evidence still
passes under that warning. `SEARCH_INCOMPLETE` does downgrade any PASSED —
an incomplete search cannot license a positive claim — while a located
deterministic contradiction still fails, since search completeness does not
affect it.

### Cross-verse

The PHP regression is preserved end to end: source provenance stays `PHP 1:3`,
target realization stays `PHP 1:6`, and the verification record stores
`sourceReferences` and `targetReferences` as separate lists. No same-verse
source relationship is manufactured, and same-verse lexical realization is
never required.

### Schema v14 — and why it is not v13

The companion database is now **v14**, adding one table,
`correction_verifications`. This is not convenience. The invariant a JSON blob
on the application ledger cannot enforce is:

> At most one verification may exist for a given (application, analysis job,
> target content hash, verifier fingerprint), and a repeated request must
> return that same record.

Verification is reached by a button a reviewer can double-click while a
read-modify-write of `result_metadata_json` is in flight, so an append into
that blob can duplicate under exactly the concurrency a `UNIQUE` index rules
out — the same reasoning that gave applications
`UNIQUE(proposal_id, expected_proposal_revision)` in v13. Acknowledgement also
needs its own revision column so "mark corrected" fails closed against a
verification that went stale between render and click, and history must stay
queryable per application after the current record is superseded. Migration is
backward compatible and additive; existing v13 projects remain readable and no
existing row is rewritten. `CORRECTION_VERIFICATION` is registered in the
shared `RECORD_DEPENDENCY_TABLES` constant, and each record depends on its
proposal and on the exact target reference, so ordinary staleness propagation
reaches it.

### Idempotency, fingerprint and currentness

Repeated verification of the same (application, job, target hash, fingerprint)
returns the existing record — no duplicate rows, whoever clicks. The verifier
fingerprint hashes the verification engine and policy versions *plus* the
Stage 6B/7/8 engine and policy versions it consumes, so a change to how
location, meaning or QA works makes existing verifications non-current and
re-evaluatable rather than silently carrying an old verdict forward. A later
target edit makes a verification non-current by hash comparison; the record is
retained as history, never deleted.

### Explicit human acknowledgement

PASSED never sets `CORRECTED`. The panel exposes **Mark correction as
corrected** only for a current PASSED verification, behind a confirmation
dialog showing the original issue, the correction applied, the verification
result, the source semantic reference, the target realization, the affected
dimension and the current supporting evidence. Its buttons are **Mark
corrected** and **Cancel** — never a generic Save.

Acknowledgement re-checks every precondition server-side, requires
`actorType == HUMAN`, and takes CAS on both the verification revision and the
finding revision. It preserves the original `CONFIRMED_TRANSLATION_ERROR` in
the review history, records actor/timestamp/verificationId/applicationId/note,
and deletes nothing.

### CORRECTED does not immunize a finding

If the target is edited again, the verification becomes non-current and the
acknowledgement is reported as `current: false` while the historical CORRECTED
event is retained in full. The finding returns to the ordinary QA lifecycle
rather than being permanently closed, and no human decision is erased.

### Safety boundaries held

Verification and acknowledgement are read-only with respect to Scripture,
imported USFM and alignment data — asserted by hashing all three around the
whole flow. Neither calls `correction.applyProposal`, alters proposal wording,
starts analysis, nor approves Word Alignment: PHP 1:6 alignment stays
invalid/reviewable after a PASSED, acknowledged correction. The Project QA
Report duplicates no verification logic.

### API

`correction.verifyApplication`, `correction.getVerification` and
`correction.acknowledgeCorrected`, wired through Python, Rust/Tauri and typed
TypeScript. All three sit on the interactive sidecar timeout (a Rust test pins
this): they read persisted records and write one small CAS transaction, so a
long timeout would only delay reporting a dead sidecar.

`scripts/inspect_correction_application.py` reports `verificationId`,
`verificationStatus`, `verificationCurrent`, `verificationReasonCodes`,
`verificationAnalysisJobId`, `correctedAcknowledgement`, `correctedBy`,
`correctedAt` and the full verification history. It stays read-only (verified
by hashing the database around a run) and degrades cleanly on a v13 database
that has no verification table.

### Verification on 2026-09-07

```text
Stage 9B.4 focused Python                61 passed
Stage 9B.3b + 9B.3c focused Python       22 passed
Stage 9B.0/9B.1/9B.3a + 9A review       222 passed (re-run after the v14 bump)
full Python + Greek Room                927 passed
Correction Review frontend               51 passed (33 existing + 18 new)
Full frontend Vitest                    306 passed / 24 files
npm run check                             0 errors / 0 warnings
npm run build                            passed; existing >500 kB chunk warning
cargo test                               12 passed
cargo check                              passed
git diff --check                         passed; line-ending notices only
```

### A Stage 7 defect found and deliberately not fixed here

`_comparison_norm` in `meaning_analysis.py` runs
`re.findall(r"[^\W_]+")` over NFD-decomposed text. Indic combining marks are
not alphanumeric, so a Tamil word is **split at every virama and vowel sign**
and the marks are dropped: `இல்லை` normalizes to `இல ல`, two tokens. The
docstring's claim that "marks in unrelated scripts (including Tamil vowel
signs) must remain intact" does not hold.

`_category` uses substring matching, so the QUANTITY/TEMPORAL/PARTICIPANT
inventories still work. The POLARITY branch does not: it tests whole tokens
(`item in target.split()`), so it cannot see the negative in `இல்லை` and
reports `CONTRADICTED` against a Greek negative. That is a real false
contradiction on this project's primary target language.

Stage 9B.4 must not re-judge Stage 7 meaning, and fixing this changes Stage 7
and Stage 8 verdicts and would require re-baselining both goldens. So the
behavior is **pinned by a test**
(`test_tamil_negation_polarity_limit_is_pinned_not_worked_around`) rather than
worked around: verification faithfully reports the disagreement as UNCERTAIN.
When Stage 7's normalization is fixed, that test fails and must be updated
together with the Stage 7/8 goldens. **This should be scheduled — it is a
false-positive source in the language Bridge is primarily used for.**

### Remaining v1 stabilization work

- Installed desktop acceptance of the verify -> Mark corrected flow has **not**
  been performed; the repository test suite does not claim it. See the
  procedure below.
- Naturally emitted **meaning-failure** findings are still blocked from
  correction by `RESOURCE_CONFLICT_REQUIRES_REVIEW` -- an independent Stage
  9B.0 defect found during the §37.7 gate and deliberately not fixed there.
- The cross-verse graphical visualization is deliberately not started.
- The uncalibrated-confidence caveat from every prior stage applies to
  `confidence` on the verification record too.
- The Stage 7 Tamil polarity defect above.

### Installed acceptance procedure

Import a fresh disposable project so Bridge copies it into
`%LOCALAPPDATA%\Bridge\data\projects\`, and exercise the managed copy, not
the import source. Then:

```text
confirm a finding -> create and review a correction -> Apply
  -> Word Alignment shows invalid/reviewable, verification PENDING
  -> Re-analyze affected passage -> COMPLETED / COMPLETED_WITH_WARNINGS
  -> Verify correction
  -> inspect the positive evidence and reason codes
  -> verification PASSED, disposition still CONFIRMED_TRANSLATION_ERROR
  -> Mark correction as corrected -> confirm in the dialog
  -> disposition CORRECTED
  -> Word Alignment still invalid/reviewable
  -> restart Bridge: PASSED + CORRECTED + history persist, nothing re-runs
```

Also confirm a FAILED and an UNCERTAIN fixture offer no **Mark corrected**
control. Verify state on disk with
`python scripts/inspect_correction_application.py <source project> <findingId> <proposalId>`.

## Next boundary: post-9B.4 v1 stabilization, on explicit approval only

The cross-verse graphical visualization and the wider v1 UI pass are **not**
authorized. Do not begin them without explicit approval. The Stage 8 -> 9B
target-hash blocker fix in §37.7 came before this boundary; do not seed the
Stage 9B.4 A/B/C acceptance fixtures until that gate is reviewed.

## Stage 9B.3c installed-acceptance responsive fix (Beta 15)

Installed acceptance exposed a QA-detail layout defect: the complete **Your
decision** form was sticky at the bottom of the same pane that scrolled the
evidence, so its textarea, promotion checkbox, explanation, and buttons
covered evidence on short windows. Correction Review compounded the issue
with a capped nested scroller and its own sticky action region.

The QA detail now has one vertical scroll owner and normal document order:
Source/Location/Meaning/Coverage/Resources/What this means/History, then Your
decision, then Correction Review. Both complete action regions participate in
normal flow; the correction evidence and draft form no longer create capped
nested scroll areas. The application confirmation modal retains its bounded
modal scroll, which is independent and intentional. No QA, correction, or
Stage 9B.3c semantics changed.

Responsive regressions cover 1920×760, 1366×768, 1366×500, 1550×350, and
820×768 with long Tamil/source and resource evidence, section ordering,
history/correction/action reachability, keyboard traversal, one scroll owner,
and horizontal-overflow containment.

Beta 15 metadata is synchronized across npm, Cargo/Tauri, Python/Greek Room,
import metadata, API user-agent and frozen-sidecar checks. The installed app,
release executable, and NSIS installer report `0.8.0-beta.15`. The exact
installer is `src-tauri/target/release/bundle/nsis/Bridge_0.8.0-beta.15_x64-setup.exe`.
The responsive installed-acceptance workflow can resume; Stage 9B.4 remains
unauthorized.


# 37.7 Stage 8 → Stage 9B Target-Hash Contract Repair (blocker fix)

Found while preparing Stage 9B.4 installed acceptance, on baseline `34a8565`
(application version **0.9.2**, semantic schema **v14**, verification policy
`correction-verification-policy-v2`). No schema migration, no version bump, no
new feature.

## The blocker

Stage 8 wrote the **Stage 6A target-inventory range fingerprint** into
`qaFinding.targetContentHashes`. Stage 9B correction eligibility reads that
field as exact **per-verse** hashes and compares it with
`runtime.text_hash(current_verse_text)`. A SHA-256 over the canonical JSON of
the whole analyzed range can never equal a SHA-256 over one raw verse string,
so **every finding the production pipeline actually emitted failed eligibility
with `TARGET_TEXT_CHANGED`, on Scripture that had never been edited.**

The write side was fixed. Eligibility was **not** taught to compare range
fingerprints: that would make an edit to a neighbouring verse
indistinguishable from an edit to the verse a correction rewrites.

## The invariant now

```text
qaFinding.targetContentHashes[i]
    == canonical_text_hash(current authoritative text at target_references[i])

target_references = the displayed references of the finding's target semantic
                    units, deduplicated, order preserved; falling back to the
                    finding's displayedReferences only when it has no target
                    units at all (an omission has no separate target
                    realization).
```

Authoritative Scripture is `<project>/<book>/<chapter>.json`. Preserved
imported USFM is never hashed. `engine/tc_ai_bridge/qa_target_hash.py` holds
the hash **and** the reference resolution, and both Stage 8 and Stage 9B import
them, so the two sides cannot drift.

Canonical PHP cross-verse case — source semantics `PHP 1:3`, target
realization `PHP 1:6`, analysis range `PHP 1:3–1:6`:

```text
displayedReferences   ["PHP 1:3", "PHP 1:6"]      both sides, as before
targetContentHashes   [hash(current PHP 1:6)]     the target side only
```

No same-verse source provenance is manufactured.

## Separation of concerns, pinned by tests

```text
edit the exact target verse   -> TARGET_TEXT_CHANGED + FINDING_STALE
edit a neighbouring verse     -> no TARGET_TEXT_CHANGED; FINDING_STALE only
```

Correction-target CAS and semantic-analysis freshness are separate mechanisms;
neither impersonates the other.

## Findings written before this fix

Old range hashes are not reinterpreted and there is no heuristic hash-type
detection: such a finding blocks with `TARGET_TEXT_CHANGED` and **requires
re-analysis** before it can be corrected. Finding ids are stable and
`save_qa_finding` preserves the human decision, so re-analysis repairs the hash
without costing the reviewer their decision.

`QA_ENGINE_VERSION` was deliberately **not** bumped to force that re-analysis:
doing so makes the very first Stage 8 re-run against an unchanged target
inventory die with `FoundationConflict` on a duplicate `coverage_accounts`
row, because the coverage-account fingerprint hashes the *policy* version and
not the engine version. Verified, then reverted. Recorded in BUILD_LOG as a
separate open defect.

## Correction to the Stage 9B.3b / 9B.3c acceptance claim

Those installed acceptances used a **controlled pre-seeded finding** whose
`targetContentHashes` already conformed to the Stage 9B reader contract
(`tests/correction/test_correction_stage9b3b.py::_fixture` writes the row directly). They
genuinely validated the correction application transaction, exact Scripture
mutation, invalidation, affected re-analysis, cross-verse provenance and
persistence/recovery.

They did **not** prove that a finding naturally emitted by production Stage 8
could enter Stage 9B — it could not have. Do not describe the earlier
acceptance as fully production end-to-end.

## A second, independent production blocker (found here, fixed 2026-09-08)

Every naturally emitted **meaning-failure** finding was blocked by
`RESOURCE_CONFLICT_REQUIRES_REVIEW`: Stage 7 filed the very evidence that a
meaning failed into `conflictingEvidenceIds`, and Stage 9B.0 blocked on that
field for *resource* conflicts. Coverage findings (POSSIBLE_OMISSION,
POSSIBLE_ADDITION) were unaffected and reached `ELIGIBLE` cleanly. Unrelated to
the hash contract, and fixed in its own gate the next day — see §37.8 below and
BUILD_LOG, "Meaning failure is not resource disagreement".

## Verification on 2026-09-07

```text
Stage 8 -> 9B production integration      9 passed  (new file, run alone)
Stage 8 + 9B.0/9B.1/9B.3a/9B.3b/9B.3c/9B.4
  + 9A review + PHP walkthrough + new   292 passed
full Python + Greek Room                NOT COMPLETED -- the run was stopped
                                        part-way at the operator's request and
                                        must be re-run before this gate is
                                        treated as closed
frontend Vitest / npm check / npm build NOT RUN -- no frontend file touched
cargo test / cargo check                NOT RUN -- no Rust file touched
git diff --check                        clean; line-ending notices only
```

An earlier combined run of the focused set reported one failure,
`test_stale_proposal_cannot_be_edited_as_current`, and a second run reported
`test_all_stage9b1_operations_leave_scripture_and_alignment_byte_identical`.
Both are the pre-existing `correction_proposal_history(...)[-1]` ordering flake
documented in BUILD_LOG, reproduced with these changes reverted to `HEAD`, and
both passed on the clean 292-test run above.

Frontend and Rust gates were not re-run: no frontend, Rust or wire-shape file
was touched. `targetContentHashes` is still `string[]`, still positionally
ordered; only which references it is taken over changed.

## Next boundary

Do **not** seed the Stage 9B.4 A/B/C acceptance fixtures until this gate is
reviewed. The cross-verse graphical visualization and the Stage 7 Tamil
normalization defect remain unauthorized/unscheduled. The meaning-failure
eligibility blocker named above was fixed the next day in its own gate; see
§37.8.

---

# 37.8 Meaning-Failure Correction Eligibility Repair (blocker fix, 2026-09-08)

The second production blocker found during the §37.7 gate, fixed in its own
gate. Nothing was released; version stays **0.9.3**, companion schema stays
**v14**, verification policy stays `correction-verification-policy-v2`.

## What was wrong

Stage 7 and Stage 9B shared one field for two different concepts.

`meaning_analysis._assessment` files every component whose status is `ALTERED`,
`CONTRADICTED`, `PARTIALLY_PRESERVED`, `TARGET_ADDS_SPECIFICITY` or
`TARGET_WEAKENS_SPECIFICITY` into `conflictingEvidenceIds` — evidence that the
*target meaning differs from the source*. Stage 8 copied that onto the finding.
`CorrectionEligibilityService._check_resource_conflicts` then read the same
field as an unresolved **resource** conflict and raised
`RESOURCE_CONFLICT_REQUIRES_REVIEW` for every id in it.

So the evidence that a translation is wrong was the reason a correction was
refused. No meaning-failure finding the pipeline could emit — CONTRADICTION,
MEANING_SHIFT, POSSIBLE_UNDER/OVERTRANSLATION, NEGATION_PROBLEM,
QUANTITY_PROBLEM, TEMPORAL_PROBLEM, PARTICIPANT_PROBLEM, REFERENT_PROBLEM —
could reach correction review, however clean the Scripture was.

A second defect made the first one load-bearing: the same method's *other*
rule read `evidence.get("resourceValidationStatus")`, a key `EvidenceRecord`
has never serialized (it emits `validationStatus`). That branch had never
matched anything, so the overloaded meaning field was the only thing enforcing
resource protection at all. Deleting the overload without repairing the key
would have removed the protection rather than narrowing it.

## The contract

Two explicitly typed fields on both the Stage 7 assessment and the Stage 8
finding:

- `conflictingEvidenceIds` — meaning-failure evidence. Unchanged shape and
  unchanged content. Never blocks a correction.
- `resourceConflictEvidenceIds` — genuine resource disagreement only. Blocks
  until a human resolves it.

The new field is derived from what Stage 7 already computed and never
surfaced: each component's `evidence.resourceStatus`, taken from the
`validationStatus` of the resource records on the source unit.
`resource_conflict_evidence_ids(assessment)` reads the stored field and, when
the assessment predates it, *proves* the answer from the assessment's own
`componentAssessments` — so a Stage 8 re-run over a cached pre-split Stage 7
run still writes the correct value rather than an optimistic empty list.

Eligibility reads only that field plus the now-repaired live
`validationStatus` check on `resourceEvidenceIds`.

## Backward compatibility

A finding written before the split carries `conflictingEvidenceIds` and **no
`resourceConflictEvidenceIds` key**. Absence is the discriminator: eligibility
fails closed on such a record and says so in the reason detail. The ids are
*not* classified by prefix or any other heuristic — the same refusal to
reinterpret ambiguous stored data as in §37.7.

Re-analysis is the way out. Finding ids are stable and `save_qa_finding`
preserves `qaDisposition`/`reviewStatus` across a re-run, so a repaired finding
keeps the reviewer's decision. No engine, model, calibration or policy version
was bumped: each of those feeds the Stage 8 run fingerprint but not the
coverage-account fingerprint, so a bump reproduces the duplicate
`coverage_accounts` `FoundationConflict` recorded in BUILD_LOG. Existing
0.9.3 findings are therefore repaired the next time the run fingerprint
legitimately misses cache, and blocked rather than misread until then.

## Two pipeline limits found while proving this (pre-existing, not fixed)

1. Stage 6B only searches coverage-account **owner** units. REFERENT,
   PARTICIPANT and TEMPORAL_ASPECTUAL source units are created COMPONENT-role
   / CONDITIONAL-eligibility, so they are never located and cannot produce a
   meaning-failure finding at all today. Only LEXICAL_CONTENT, QUANTITY and
   POLARITY units are PRIMARY/ELIGIBLE.
2. `DeterministicMeaningComparator.compare` never returns `ALTERED` on any
   input path.

Those two are why the component/dimension matrix is covered in two layers: the
real pipeline where it reaches, and the real Stage 7 writer plus the real
eligibility rule where it cannot. Neither limit is a consequence of this
repair; both are recorded in BUILD_LOG as open observations.

## Verification on 2026-09-08

```text
new meaning-failure -> 9B production suite   76 passed  (new file, run alone)
Stage 7 + Stage 8 + 9B.0/9B.1/9B.3a/9B.3b/
  9B.3c/9B.4 + 9A review + foundation +
  Stage8->9B hash contract + new           405 passed
full Python + Greek Room                  1014 passed, 0 failed  (21m36s)
frontend Vitest                            307 passed (24 files)
npm run check                              0 errors, 0 warnings
npm run build                              built
cargo check                                clean
cargo test                                 12 passed
git diff --check                           clean
```

An earlier combined focused run reported one failure in the new file
(`test_confirmed_meaning_failure_can_have_a_correction_proposed`). That was a
wrong assertion in the test, not in the code: after a proposal exists,
eligibility legitimately reports `CONFLICTING_CORRECTION` naming that proposal,
which the review panel filters out for a proposal it already holds. The test
now asserts that shape, and re-evaluates with `ignore_proposal_ids` to confirm
nothing else blocks. The full 1014-test run above includes the corrected file.

The pre-existing `correction_proposal_history(...)[-1]` ordering flake
documented in BUILD_LOG did not reproduce in any run of this gate.

Installed desktop acceptance: **NOT RUN**, deliberately. Nothing released.

## Next boundary

Unchanged from §37.7 and still unauthorized: Stage 9B.4 installed acceptance
fixtures, the Stage 7 Tamil normalization defect, cross-verse graphical
visualization, and unrelated v1 UI work. Do not release.

---

# 37.9 Stage 9B.4 Installed-Acceptance Preparation (Bridge 0.9.4 candidate, 2026-09-08)

**Not released.** 0.9.4 is the installed-acceptance candidate. Companion schema
stays **v14**; verification policy stays `correction-verification-policy-v2`.

Driving the 9B.4 flow end to end outside its own unit fixtures for the first
time broke it in three places.

1. **The correction review UI could never offer a span.**
   `semantic_location_relationship()` selected `run_id`, validated the run with
   it, then returned only `payload_json`. `review_context` skips any location
   without a `runId`, so `candidateSpans` and the candidate `alternatives` list
   were always empty. Every 9B test builds its `CorrectionIntent` directly, so
   nothing caught it. Fixed in the reader.
2. **Every affected re-analysis died.** `save_coverage_account` was a bare
   `INSERT` against a content-addressed id that is deliberately stable across
   runs, so re-analysis over the affected range collided on the unchanged
   verses' accounts and Stage 8 failed with `FoundationConflict`. BUILD_LOG had
   this recorded as a version-bump-only problem; in fact **nothing but the
   Scripture edit was needed** to trigger it, so the ordinary post-correction
   path had never worked. Re-seeding an identical account is now a no-op that
   preserves the stored row's coverage status, finding link and review status;
   a genuine identity difference still conflicts. The target-support pass now
   reads the stored revision like the source-coverage pass already did.
3. **A cross-language PASSED is unreachable in 0.9.4** — an open product gap,
   not fixed. PASSED needs Stage 6B to positively re-locate the corrected
   obligation. No production embedding provider ships; the embedding cache is
   skipped when the provider is unavailable; and nothing in the running app
   ever writes `lexical_groups`, so the human-precedent signal is always empty.
   The remaining evidence sums to about 0.19 against a 0.36 threshold. The
   verifier correctly answers `UNCERTAIN` with `PROVIDER_LIMITED` rather than
   claiming a success it cannot demonstrate.

## The acceptance package

`python scripts/seed_correction_acceptance.py <dest>` builds three projects;
`docs/STAGE_9B4_ACCEPTANCE.md` is the click-by-click script.

```text
A  PASSED     controlled verification fixture   DIMENSION_PRESERVED, COVERAGE_COVERED
B  FAILED     controlled verification fixture   DIMENSION_CONTRADICTED
C  UNCERTAIN  REAL Stage 5->6A->6B->7->8        COVERAGE_POSSIBLY_MISSING, PROVIDER_LIMITED
```

Only C is production end-to-end and the document says so plainly. C is the
canonical cross-verse case: a naturally emitted `QUANTITY_PROBLEM` whose source
obligation is `pas` at PHP 1:3 and whose realization is "some" at PHP 1:6, left
`UNRESOLVED`/`AI_PROPOSED` for the tester. A and B reuse the Stage 9B.4 tests'
own controlled-evidence builders so fixture and test cannot drift.

`scripts/inspect_correction_application.py` gained a read-only Word Alignment
block so acceptance can show that verification neither approves nor rebuilds an
alignment.

## Known, pre-existing, not caused by this work

`scripts/smoke_sidecars.py` fails its duplicate-classification step
(`possibleDuplicate` where it expects `exactDuplicate`). `_source_fingerprint`
falls back to a whole-tree hash and compares it against the value stored at
registration, but opening a project writes into that tree. Reproduced from
source with the 0.9.4 generator-metadata line reverted to 0.9.3: byte-identical
behaviour, so this work is not implicated. Left unfixed; it is not on the
acceptance path.

## Next boundary

Do **not** release 0.9.4. The Tamil Stage 7 normalization defect,
REFERENT/PARTICIPANT/TEMPORAL pipeline coverage, correction-history timestamp
ordering, cross-verse visualization and broader v1 stabilization all remain
unauthorized. The PASSED product gap above needs its own scope.

---

# 37.10 Current Resume Handoff — Stage 9B.4 Installed Acceptance Pending (2026-09-08)

This is the current continuation point for the next developer. Treat it as the
short operational companion to §37.9 and
`docs/STAGE_9B4_ACCEPTANCE.md`; the architecture and hard constraints elsewhere
in this document remain authoritative.

## Repository and release state

```text
branch                          main
HEAD                            0e79c6e
origin/main                     0e79c6e
tracked worktree                clean when this handoff was prepared
application/build version       0.9.4
companion schema                v14
verification policy             correction-verification-policy-v2
installed Windows app           0.9.4
candidate installer             src-tauri/target/release/bundle/nsis/
                                Bridge_0.9.4_x64-setup.exe
release state                   CANDIDATE ONLY — NOT RELEASED
installed Stage 9B.4 acceptance NOT RUN
```

Stages 1–8 and the Stage 9A–9B.4 implementation are present. “Implemented” is
not the same as installed acceptance or release approval. Preserve the Project
QA Report, translationCore compatibility, existing human decisions, Scripture
history, Word Alignment invalidation, and all current correction safeguards.

## Frozen current behavior

The latest Stage 9B.4 preparation fixed two real end-to-end blockers:

1. semantic-location readers now retain `runId`, allowing Correction Review to
   offer the actual target candidate span;
2. identical content-addressed coverage accounts can be re-seeded safely during
   affected re-analysis without overwriting mutable review/coverage state.

Affected re-analysis continues through the single Stage 5→8 pipeline. It does
not rewrite Scripture, verify automatically, mark a finding `CORRECTED`, or
approve/rebuild Word Alignment. Verification and the explicit corrected
acknowledgement remain separate human-visible operations.

The last recorded regression gate is:

```text
full Python + Greek Room       1014 passed, 0 failed
frontend Vitest                 307 passed / 24 files
npm run check                   0 errors / 0 warnings
npm run build                   passed
cargo check                     passed
cargo test                      12 passed
git diff --check                passed
```

## Last read-only installed evidence

The existing managed Stage 9B.3c project
`C:\Users\Benz\AppData\Local\Bridge\data\projects\ta_irv_php-2` was inspected
without running analysis or changing project state:

```text
application                    27afe44f-3a05-42e4-a6c2-023b058473ab
application state              COMPLETED
affected job                   269096f5-8459-4b7a-81c0-d06cd69da359
affected job state             COMPLETED_WITH_WARNINGS
resolved source                PHP 1:3
resolved target                PHP 1:6
resolved structural range      PHP 1:3–1:6
semantic verification          PENDING
PHP 1:6 Word Alignment         INVALID / reviewable
```

All five affected-analysis stages completed or were safely reused. The warning
is `MULTILINGUAL_EMBEDDING_PROVIDER_NOT_CONFIGURED`. The pre-correction QA run
is retained as `STALE`. The same stable finding recurred in the new active QA
run, so the canonical finding row was reactivated while its human
`CONFIRMED_TRANSLATION_ERROR` decision was preserved in review history. Do not
mistake that stable-identity refresh for deletion of history.

## Exact next permitted work

On explicit approval to run installed acceptance:

1. Confirm `HEAD == origin/main == 0e79c6e` and a clean tracked worktree.
2. Use the existing 0.9.4 installer; do not call it a release.
3. Seed a fresh disposable package exactly as documented:

   ```powershell
   python scripts/seed_correction_acceptance.py C:\bridge-acceptance
   ```

4. Follow `docs/STAGE_9B4_ACCEPTANCE.md` without abbreviating the restart,
   idempotency, Scripture-preservation, history, or Word Alignment checks.
5. Run the read-only inspector after each case and retain its output with the
   acceptance report:

   ```powershell
   python scripts/inspect_correction_application.py <project> <findingId> <proposalId>
   ```

6. Report the three cases truthfully:

   ```text
   A  controlled evidence       PASSED
   B  controlled evidence       FAILED
   C  real production pipeline  UNCERTAIN + PROVIDER_LIMITED
   ```

Cases A and B are controlled verifier fixtures, not production end-to-end
proof. Case C is the real cross-language Stage 5→8 flow. In 0.9.4 it must not
be forced to `PASSED`: no production multilingual embedding provider ships and
no production path currently persists the human-approved lexical precedent
needed to reach the location threshold.

## Stop conditions and work still outside this handoff

Stop and report rather than weakening confidence, CAS, provenance, history, or
human-review boundaries. Do not release 0.9.4 merely because the controlled A
and B cases pass. Do not begin the following without a separately approved
scope:

```text
production multilingual provider / lexical-precedent integration
Tamil Stage 7 normalization changes
REFERENT / PARTICIPANT / TEMPORAL pipeline expansion
correction-history timestamp ordering changes
cross-verse visualization redesign
broader v1 stabilization
export / Scripture Burrito implementation
```

The known sidecar duplicate-classification smoke mismatch remains unrelated and
pre-existing; §37.9 records the evidence. Do not fold that defect into Stage
9B.4 acceptance unless separately authorized.

---

# 37.11 Bridge 0.9.4 Release Authorization (2026-09-08)

The project owner explicitly authorized publishing `v0.9.4` as the latest
non-prerelease GitHub release after completion of the recorded test gates. This
authorization supersedes the earlier candidate-only release hold in §37.9 and
§37.10; it does not weaken any semantic, correction, provenance, Scripture, or
translationCore invariant.

Release payload:

```text
tag                            v0.9.4
release name                   Bridge 0.9.4
release channel                latest stable / non-prerelease
Windows asset                  Bridge_0.9.4_x64-setup.exe
asset SHA-256                  6F3960A6AEB6BF03568267A9E421EB9B62C09EF893364126E56905A32D763951
asset size                     57,750,273 bytes
application version            0.9.4
companion schema               v14
verification policy            correction-verification-policy-v2
```

The release includes the Stage 9B.4 verification and explicit corrected
acknowledgement work, correction eligibility/resource-evidence repair,
end-to-end affected-analysis persistence fixes, controlled acceptance tooling,
and the script-aware multilingual font stack. The real cross-language
verification limitation remains explicit: without a configured production
multilingual provider or persisted human lexical precedent, Bridge must return
`UNCERTAIN`/`PROVIDER_LIMITED` rather than manufacture `PASSED`.

After publication, the next development boundary is post-Stage-9 v1
stabilization, and still requires a separately approved scope. Export and
Scripture Burrito work remain post-Stage-9 architecture, not part of 0.9.4.

---

# 37.12 Bridge 0.9.5 Release (2026-09-08)

The project owner authorized publishing `v0.9.5` as the latest non-prerelease
GitHub release, without a draft step. 0.9.5 is a maintenance release on top of
0.9.4.

**No product frontend, backend, or Rust behavior changed between 0.9.4 and
0.9.5.** The only functional change is the Stage 9B.4 acceptance-fixture
queue-visibility repair recorded in `docs/BUILD_LOG.md`: `_fixture()` in
`engine/tests/correction/test_correction_stage9b3b.py` now persists through
`repository.save_qa_finding()` rather than a minimal insert plus hand-patched
SQL, so the seeded A/B cases carry their denormalized Stage 9A queue columns
and `qa_finding_scope_references` rows and are actually visible in
Alignment Review → QA. `engine/tests/correction/test_correction_acceptance_queue_visibility.py`
locks that in against the real `qaReview.getQueue` API.

The installer was rebuilt only so the numbered build matches the version
fields; it carries no behavior change over `Bridge_0.9.4_x64-setup.exe`.

Release payload:

```text
tag                            v0.9.5
release name                   Bridge 0.9.5
release channel                latest stable / non-prerelease
Windows asset                  Bridge_0.9.5_x64-setup.exe
asset SHA-256                  58ABC03FAF19D6880F093A9AA7A722F94302FDBCB0B89339B6B335CEF4008F0C
asset size                     57,709,313 bytes
application version            0.9.5
companion schema               v14
verification policy            correction-verification-policy-v2
```

Stage 9B.4 verification semantics are unchanged. Subsequent installed
acceptance results and the real Case C blocker repair supersede the original
pending-A/B/C status here; see §37.13 for the current operational boundary.

---

# 37.13 Stage 9B.4 real Case C blocker repair (2026-09-09)

Installed acceptance completed Cases A and B. The first real production Case C
attempt correctly applied the cross-verse `some` to `all` edit at PHP 1:6 for
the PHP 1:3 source obligation, kept PHP 1:3 Scripture unchanged, invalidated
Word Alignment PHP 1:6, and resolved the affected range as PHP 1:3--1:6. Its
affected analysis then failed at Stage 5 with:

```text
FoundationValidationError:
Source semantic unit references missing resource evidence
```

## Proven root cause

This was an immutable-row identity collision during Stage 5 reconstruction,
not target-edit invalidation of source data:

- the seeded source inventory was `source-inventory-f358dd26f73280f455d8c75b0f5c5e90`
  with resource fingerprint `f358dd26f73280f455d8c75b0f5c5e90`;
- the installed bundled tN/tW/TWL snapshot produced resource fingerprint
  `506fdb42...`, so affected analysis correctly rebuilt rather than reusing the
  old source inventory;
- evidence identities include resource hashes, so all 35 resource-evidence IDs
  changed in the rebuilt payload;
- semantic unit identity did not include its evidence binding. `_save_unit()`
  therefore found 53 older same-ID immutable units and returned them with their
  old evidence IDs, while publishing only the new 35 evidence records;
- the validator then correctly rejected those units because their
  `evidenceIds` were excluded from the newly constructed inventory payload.

Representative offending records from the installed failure were:

```text
source-unit-92151cafc9cb8ea5b1d7ac9562b6c00f
  surface:       τῷ Θεῷ μου
  source ref:    PHP 1:3
  missing ID:    source-evidence-f36bef005fa48bbc8c8d0af333e50e4e

source-unit-4c236a128c6a25f6f8a556098a31b05e
  surface:       τῷ
  source ref:    PHP 1:3
  missing IDs:   source-evidence-1b23cbbc8511ecb95856b75bc8a10909
                 source-evidence-61189c1be59d8196910b4afb8619f06e
                 source-evidence-f36bef005fa48bbc8c8d0af333e50e4e
```

Every old evidence row still existed and was `ACTIVE`; none was `STALE` or
`SUPERSEDED`. They were absent only from the new Stage 5 payload because that
payload was built from a different resource revision. No correction or
invalidation dependency edge changed a source unit or source evidence
lifecycle. The relevant persisted edge remained `LOCATION_RUN ->
SOURCE_INVENTORY`; target-edit invalidation propagated only through target-side
dependencies. With one fixed source/resource snapshot, the Stage 5 fingerprint
is target-independent and is unchanged by the PHP 1:6 edit. The observed
fingerprint change came exclusively from the installed resource revision.

The initial Stage 5 run succeeded because its units and evidence were created
from one snapshot. The later rebuild exposed the identity collision because it
combined newly generated evidence with previously persisted immutable units.

## Repair

`SourceSemanticInventory._unit()` now keeps the stable
`semanticFingerprint` meaning-only, but derives the immutable persisted unit ID
from that fingerprint plus the exact sorted `evidenceIds` and embedded audit
owner identity. Evidence-free, self-owned canonical units keep their legacy
identity. Consequently a resource revision publishes a new, internally
self-consistent unit/evidence set instead of reusing an incompatible immutable
row. Child records also version when an evidence-bound audit owner versions.

The strict `unit.evidenceIds` subset validator remains unchanged. There is no
schema migration, application-version change, confidence-policy change,
verification-verdict-policy change, Tamil/PHP special case, or source/target
invalidation broadening.

The second installed defect was frontend state retention. After any affected
analysis terminal transition (`FAILED`, `CANCELLED`, `COMPLETED`, or
`COMPLETED_WITH_WARNINGS`), `CorrectionReviewPanel.svelte` now reloads the
backend-owned verification state. It does not infer failure/cancellation
reasons locally. An explicit cancel that returns a terminal job does the same.

Files changed for this blocker:

```text
engine/tc_ai_bridge/source_semantic_inventory.py
engine/tests/semantic/test_source_semantic_inventory_stage5.py
engine/tests/correction/test_correction_case_c_production.py
src/lib/components/CorrectionReviewPanel.svelte
src/lib/components/__tests__/CorrectionReviewPanel.test.ts
docs/HANDOFF.md
```

## Regression and gates

New regression coverage performs the genuine production sequence:

```text
Stage 5 -> 6A -> 6B -> 7 -> 8
-> natural cross-verse QUANTITY finding
-> human confirmation and human wording
-> canonical correction application at PHP 1:6
-> simulated changed help-resource revision
-> affected PHP 1:3--1:6 analysis
```

It proves Stage 5 publishes a self-consistent inventory, the affected job ends
`COMPLETED` or `COMPLETED_WITH_WARNINGS`, PHP 1:3 remains untouched, PHP 1:6 is
corrected, source/target provenance remains independent, Word Alignment PHP
1:6 remains invalid/reviewable, and the latest affected attempt is
authoritative while history is retained.

Completed gates:

```text
focused Stage 5/foundation/invalidation/Stage 9B.3a--9B.4/real Case C  159 passed
full Python + Greek Room                                                1026 passed
CorrectionReviewPanel Vitest                                            54 passed
full frontend Vitest                                                    310 passed
svelte-check                                                            0 errors, 0 warnings
Vite production build                                                   pass
Tauri/Rust release build + NSIS                                         pass
git diff --check                                                        pass
```

Rust command/wire behavior did not change, so a separate cargo test/check run
was not required; the Tauri release build compiled the Rust application
successfully. A sidecar smoke invocation was not counted as a gate: the current
script still hard-codes the prior 0.9.4 engine version and, when tested with a
temporary local adjustment, reaches a pre-existing duplicate-project
classification expectation that does not match current registry behavior.
Neither issue is part of this Stage 9B.4 runtime blocker.

## Installed candidate and next boundary

The repaired current-version installer was built and installed successfully:

```text
installer  C:\Users\Benz\projects\bridge\src-tauri\target\release\bundle\nsis\Bridge_0.9.5_x64-setup.exe
size       57,757,404 bytes
SHA-256    3E16250DBA671766C562549CD9191C938F2D123688E1369B41A9B2874397DB92
installed  0.9.5 (installed engine hash matches the packaged release engine)
```

A fresh, untouched acceptance package is ready at:

```text
C:\bridge-acceptance-stage9b4-fix
Case C: C:\bridge-acceptance-stage9b4-fix\C-uncertain-production
manifest: C:\bridge-acceptance-stage9b4-fix\acceptance-manifest.json
```

Resume only the real Case C installed acceptance using
`docs/STAGE_9B4_ACCEPTANCE.md`. The expected no-provider result remains
`UNCERTAIN`/`PROVIDER_LIMITED`; do not change verdict policy. The release hold
in this repair record was subsequently superseded by the owner's explicit safe
0.9.6 authorization in §37.14. The v1 stabilization hold remains.

---

# 37.14 Bridge 0.9.6 release (2026-09-10)

The project owner explicitly chose a safe new `v0.9.6` release rather than
rewriting the already-public `v0.9.5` tag or replacing its asset. 0.9.6
contains the Stage 9B.4 Case C source-inventory consistency repair and terminal
verification-state refresh recorded in §37.13.

Release payload:

```text
tag                            v0.9.6
release name                   Bridge 0.9.6
release channel                latest stable / non-prerelease
Windows asset                  Bridge_0.9.6_x64-setup.exe
asset SHA-256                  C7328D6C0BD48C570B0A24391630744D6F0449CF7FE6217ECF4F6EF0BC7D0C3D
asset size                     57,751,384 bytes
application version            0.9.6
companion schema               v14
verification policy            correction-verification-policy-v2
```

Version metadata is synchronized across package.json/package-lock.json,
Tauri/Cargo, the Python engine, Greek Room, API user-agent and import generator.
Active acceptance tooling and user-facing documentation name 0.9.6.
`docs/RELEASE_0.9.6.md` contains the public notes and exact gate results.

Installed Stage 9B.4 Cases A and B passed. The repaired Case C path is protected
by a real production regression and a fresh manual package at
`C:\bridge-acceptance-stage9b4-fix\C-uncertain-production`; the final installed
Case C click-through remains the next operational acceptance check. No
verification verdict policy, schema, Scripture or translationCore behavior was
weakened for this release.

---

# 38. Export Architecture (Planned, Post-Stage-9)

The rich Bridge model is authoritative. Do not force passage-aware semantic
data into canonical USFM.

Conceptual export:

```text
BRIDGE INTERNAL MODEL
        ├── clean USFM/SFM → Paratext/general interchange
        ├── truthful tC/uW lexical projection → translationCore
        └── rich semantic sidecar/package → Bridge/Scripture Burrito
```

Never fake cross-verse mappings as same-verse translationCore alignments.
Semantic validity and exportability are separate. The `Exportability`
model/table exist since Stage 3 (`ExportFormat`, `ExportabilityLevel`,
`ExportReason`) but no stage through Stage 8 constructs instances of it —
still fully open work, likely after Stage 9.

---

# 39. Hard Non-Negotiable Constraints

Do not:

```text
hardcode Tamil
hardcode Philippians
hardcode four verses
assume same verse number = same semantic location
reuse source tokens across active lexical groups
reuse target tokens across active lexical groups
equate null alignment with omission/addition
equate unaligned with null-aligned
force mapping when uncertain
treat embeddings as proof
treat tN/tW/TWL as infallible
silently overwrite human-approved work
silently relocate stale alignments
silently migrate changed source tokens
inject rich Bridge semantics into canonical USFM
fake cross-verse alignment for translationCore
automatically rewrite Scripture
use imported USFM wording after target edit
use target text to construct source inventory
use source expectations to construct target inventory
let computation failure become NOT_LOCATED/MISSING
let meaning mismatch silently change Stage 6B location
let Stage 8 re-run Stage 6B search or re-judge Stage 7 meaning
auto-promote POSSIBLY_MISSING/POSSIBLY_UNSUPPORTED without human action
```

Do:

```text
align semantic realization before judging errors
use passage-aware search
keep source and target inventories independent
audit source→target and target→source separately
preserve exclusive lexical ownership
support null explicitly
preserve raw Scripture
pin source versions
normalize versification
retain evidence/provenance
abstain under uncertainty
protect human decisions
separate semantic validity from exportability
separate mapping error from translation error
require human approval for corrections
rerun analysis after edits
verify repository reality against this document before relying on it
```

---

# 40. Development Sequence

The staged separation is deliberate:

```text
Stage 5 — WHAT SOURCE MEANINGS EXIST?                    ✅ done
        ↓
Stage 6A — WHAT TARGET MEANINGS/SPANS EXIST?              ✅ done
        ↓
Stage 6B — WHERE IS EACH SOURCE MEANING REALIZED?         ✅ done
        ↓
Stage 7 — DOES THE LOCATED TARGET EXPRESSION PRESERVE IT? ✅ done
        ↓
Stage 8 — IS ANY SOURCE MEANING MISSING?
          IS ANY TARGET MEANING UNSUPPORTED?              ✅ done
        ↓
Stage 9 — HUMAN REVIEW AND CORRECTION                     ✅ 9A–9B.4 done
```

Do not collapse these stages.

---

# 41. Instructions for the New Conversation

When this file is used to start a new conversation:

1. Treat it as the authoritative continuation context.
2. Do not restart the architecture from scratch. Stages 1–8 are done.
3. Verify repository reality when code access exists — this document was
   itself corrected once already (Stage 7 turned out to be already
   implemented when this repo was checked out for Stage 8 work; the
   original numbering assumed otherwise). Check `git log`, run the test
   suites, read the actual code before trusting any stage's status here as
   current truth.
4. Verify the current resume baseline from §37.10 with `git status` and
   `git log --oneline -5`; do not assume a dirty or divergent tree is safe.
5. Stages 1–8 and the Stage 9A–9B.4 implementation are present. Installed
   Stage 9B.4 Cases A and B passed. The real Case C blocker and terminal-state
   UI defect are repaired as recorded in §37.13; the immediate boundary is to
   rerun only Case C from the fresh package documented there, following
   `docs/STAGE_9B4_ACCEPTANCE.md`.
6. Do not start export/Scripture Burrito work (§38), the production-provider
   gap, or broader v1 stabilization until installed acceptance is reviewed and
   the next scope is explicitly approved.
7. Preserve existing Scripture and translationCore behavior.
8. Continue test-first and stop at stage boundaries.
9. If repository reality conflicts with this document, report the conflict
   instead of silently changing assumptions — then update this document to
   match reality.
10. Keep the final goal in view (§42).

---

# 42. Final Principle

The end goal is not:

> Every source word has a line to a target word.

The end goal is:

> **Bridge can explain where each required source meaning is represented,
> whether the located target expression preserves that meaning, what
> target meanings are unsupported, what remains uncertain, and exactly
> where a human reviewer should investigate a possible translation
> error — without silently changing Scripture or manufacturing
> certainty.**

---

# 43. V1.1 Unicode and Grapheme-Safe Semantic Comparison

V1.1 resolves the Stage 7 Tamil polarity defect recorded historically in
§37.6 without introducing a Tamil-specific branch. The old NFD plus
`[^\W_]+` path discarded Unicode Mark code points globally. Stage 7 now uses
the shared `unicode_comparison.py` transient comparison layer:

```text
raw authoritative Scripture (unchanged)
  -> canonical NFC + Unicode casefold + NFC
  -> extended grapheme clusters (`regex` \X)
  -> conservative L/N/M orthographic runs
  -> deterministic Stage 7 comparison
```

Punctuation/separators/symbols are boundaries. Attached combining marks and
internal format controls survive. Malformed standalone marks and controls do
not become semantic tokens. Compatibility normalization is not used. The UHB
controlled-category path has an explicit opt-in consonantal comparison key for
Hebrew points/cantillation; default normalization preserves those marks, and
no UHB token, source identity or evidence record changes.

The old `இல்லை -> இல ல` result is now `இல்லை -> இல்லை`. In the real
Stage 5–8 PHP 1:22 test path, Greek `οὐ` and NFD Tamil `இல்லை` produce a
PRESERVED POLARITY component and no false Stage 8 NEGATION_PROBLEM. Stage 9B.4
uses the same corrected comparator for its fresh direct recheck, while still
requiring positive current persisted evidence. Possible absence remains
UNCERTAIN; it never becomes FAILED merely because wording was not located.

Cache identity advances from meaning engine/model v1 to v2 and carries
`unicode-comparison-nfc-grapheme-v2` through analysis-job policy identity,
Stage 7 fingerprints, Stage 8's inherited Stage 7 fingerprint and Stage 9B.4
verification identity. Old broken judgments therefore cannot present as
current. Companion schema remains v14 and public app version remains 0.9.6.

Persistence and correction boundaries are unchanged:

- Scripture is never normalized on disk;
- translationCore alignment behavior is unchanged;
- spans remain `[startCodePoint,endCodePoint)` over raw text;
- Apply still checks exact reference/text/span/revision/hash with CAS;
- no fuzzy relocation exists;
- human review status survives Stage 8 status refresh.

The focused world-language matrix covers Tamil, Devanagari, Malayalam,
Telugu, Bengali, Kannada, Gujarati, Gurmukhi, Odia, Sinhala, Hebrew, Arabic,
Greek, Vietnamese, Latin, Thai, Khmer, Myanmar and Lao. NFC/NFD equivalence,
punctuation, format controls, emoji, supplementary-plane code points and
malformed mark-only input are also covered. Thai/Khmer/Lao/Myanmar text may
remain a whole no-space comparison run: grapheme safety is guaranteed, but
V1.1 does not claim universal lexical segmentation.

Focused semantic/cache/correction tests: **175 passed**. Full Python plus
Greek Room: **1069 passed / 0 failed**. Frontend: **310/310**, Svelte check:
**0/0**, production build: passed, Rust: **12/12** plus `cargo check`.

The next conversation must not start V1.2, cross-verse visualization, new
semantic dimensions/providers or a release without explicit approval. Start
from the V1.1 commit(s), verify the worktree and full gate, then wait for the
next approved stabilization boundary.

---

# 44. Master Project History and Resume Context

This section is the concise, current entry point for a new development
conversation. It reconciles the original seven-phase product roadmap, the
later passage-semantic stages, the correction-loop releases, and V1.1. Older
“next boundary” paragraphs remain valuable historical evidence but do not
override this section or repository reality.

## 44.1 Current repository baseline

Immediately before this history update the verified state was:

```text
repository                     RevantCI/bridge
working directory              C:\Users\Benz\projects\bridge
branch                         main
public release                 v0.9.6
public release commit          b0de092
origin/main                    b0de092
V1.1 implementation commit     5cc3ce7
V1.1 test commit               ef49e9e
V1.1 documentation commit      4444ea7
companion schema               v14
verification policy            correction-verification-policy-v2
application version            0.9.6
worktree                       clean before this documentation change
```

The three V1.1 commits are local descendants of v0.9.6 and had not been
pushed, packaged, versioned, or released. Do not reset them. Verify `git
status`, `git log --oneline -5`, and the local/remote relation at the start of
the next conversation.

## 44.2 The two roadmaps

Bridge has two numbering systems:

1. **Original product Phases 1–7**, covering the desktop application,
   analysis tools, alignment intelligence, AI assistance, and external
   integrations.
2. **Passage-semantic Stages 1–9**, covering the semantic foundation,
   inventories, location, meaning, QA, review, and correction loop.

They are not sequential parts of one numbering scheme. In particular,
original Phase 7 is not semantic Stage 7. Both roadmaps are implemented.

## 44.3 Original Phases 1–7

### Phase 1 — protocol and sidecar consolidation

`BridgeEngine` unified `GreekRoomEngine` and `tc_ai_bridge` behind one JSON
sidecar protocol. Project access, QA decisions, edits, and transaction journals
use the canonical services rather than parallel in-memory implementations.

### Phase 2 — real Svelte/Tauri desktop application

The Svelte frontend, Rust/Tauri command layer, and Python sidecar were wired
end to end. Bridge became a single-window Windows/WebView2 application using
real project, chapter, verse, finding, navigation, and engine state.

### Phase 3 — persistent project workflow

This phase delivered stable project identities and collections, safe import,
chapter/book workflows, persistent decisions and edits, settings, aligned and
non-aligned export, and cancellable/retryable background checks. Unplanned but
essential work included secure provider-secret storage, recovery behavior,
current/stale AI-review state, and lazy import normalization that reduced the
66-book path from minutes to seconds.

### Phase 4 — USFM structure and versification

Bridge integrated the Greek Room USFM structural checker and deterministic
versification detection, org-reference normalization, and back-versification
mapping. Displayed references are normalized before semantic cross-verse
classification; verse numbers are anchors rather than meaning boundaries.

### Phase 5 — names and transliteration

Whole-book spelling consistency combines Uroman, vendored Smart Edit Distance,
and bounded candidate search. Name/transliteration similarity is supporting
evidence and never independently proves a translation error.

### Phase 6 — alignment intelligence

The manual Word Alignment editor was built first because human-approved
alignments did not previously exist inside Bridge. Corpus statistics then used
Bridge's completed alignments for co-occurrence, translation probability, PMI,
and optional phonetic evidence. Native translationCore alignment remains the
truthful verse-local lexical projection.

### Phase 7 — AI assistance, import, Paratext, and Logos

Bridge added AI alignment proposals, evidence-grounded tN/tW explanation and
review, native drag-and-drop import, identity-gated/idempotent Paratext Project
Note handoff, and Paratext/Logos navigation. Advanced AI proposals require an
explicit Apply action, human/imported selections stay protected, and external
application state never overrides Bridge's project authority. Paratext handoff
and live Logos 53.1 inbound/outbound navigation were verified in later work.

## 44.4 Beta and semantic-validation bridge

The Beta 6–15 line added occurrence-aware translation-help cards, Basic and
Advanced modes, resumable verse/chapter/book AI jobs, clear cancellation and
retry, exact selection safeguards, saved resolution evidence, stale/recheck
lifecycle, Paratext sent-state persistence, and language-independent passage
mapping.

The generated IRVTam validation set contained 40 machine-proposed Luke and
Philippians mappings. Human review after restart recorded 38 confirmed, one
corrected, and one rejected decision with 95% combined agreement. Their
provenance remains machine/AI proposed until the separate human review record;
the artifact must never be rewritten as originally human-authored. The central
cross-verse regression is:

```text
source semantic reference      PHP 1:3
source wording                 τῷ Θεῷ μου
target realization reference   PHP 1:6
target wording                 என் தேவனை
relationship                   CROSS_VERSE_REORDERED
meaning status                 PRESERVED
```

This evidence proves one corpus relationship, not a Tamil-specific linguistic
rule.

## 44.5 Passage-semantic Stages 1–9

```text
Stage 1       repository analysis                         complete
Stage 2/2.1   technical design and mandatory amendments   complete
Stage 3       schemas, identities, SQLite foundation      complete
Stage 4       runtime/current-text integration            complete
Stage 5       comprehensive UHB/UGNT source inventory     complete
Stage 6A      independent target inventory                complete
Stage 6B      passage-aware location                      complete
Stage 7       meaning preservation                        complete
Stage 8       source coverage and target support QA       complete
Stage 9A      human QA review and scoped analysis         complete
Stage 9B      correction loop through 9B.4                complete
```

The semantic architecture deliberately coordinates with rather than replaces
translationCore. Rich meaning, cross-verse, implicit, split, merged, evidence,
review, lifecycle, and QA data live in companion SQLite storage.

Current editable chapter JSON is authoritative for wording. Preserved imported
USFM supplies paragraph, poetry, heading, note, cross-reference, bridge, and
other structure. Old imported wording must never re-enter semantic analysis or
clean export after a Bridge edit.

Source and target inventories are independent. UHB/UGNT define the complete
source audit base; tN/tW/TWL enrich or challenge units but do not define the
inventory and are not infallible. Location, meaning, coverage, target support,
resource validation, review status, lifecycle, and QA disposition remain
separate judgments.

## 44.6 Stage 9 human correction history

The completed correction loop is:

```text
confirmed QA issue
  -> eligibility and correction intent
  -> human wording or optional provider suggestion
  -> persisted proposal and review
  -> explicit human Apply
  -> transaction/application ledger and dependent invalidation
  -> affected structural-passage re-analysis
  -> positive verification against current Stage 6B/7/8 evidence
  -> separate explicit human CORRECTED acknowledgement
```

Stage 9B.0 defined eligibility and wording contracts; 9B.1 implemented wording
generation; 9B.2 added proposal review; 9B.3a added crash-safe persistence and
recovery; 9B.3b added the first explicit human Scripture mutation; 9B.3c added
affected re-analysis; and 9B.4 added positive verification and human
acknowledgement.

Acceptance exposed and fixed several production-only defects: analysis-scope
and QA-queue synchronization, cross-verse source/target provenance display,
WebView2 Review application activation, target verse-hash identity, resource
conflict versus meaning-failure evidence, Case C source-inventory consistency,
terminal verification refresh, and short-window QA detail overlap. Historical
findings and decisions remain persisted across scope changes.

A correction is never verified because a finding disappeared. The original
semantic obligation must be positively satisfied by current evidence from the
exact affected analysis job. `PASSED` never silently becomes `CORRECTED`.

## 44.7 Releases and current stabilization

- **v0.9.4** published the initial Stage 9B.4 acceptance boundary.
- **v0.9.5** repaired canonical acceptance-fixture seeding.
- **v0.9.6** published the Case C source-inventory consistency and terminal
  verification-refresh repairs. It remains the current public release.
- **V1.1** is committed locally after v0.9.6. It fixes the global Unicode Mark
  loss in Stage 7 comparison using NFC, Unicode casefolding, extended grapheme
  clusters, and conservative Letter/Number/Mark runs. It does not change
  Scripture, spans, schema, translationCore behavior, or the public version.

V1.1 advances the meaning engine/model from v1 to v2 and carries
`unicode-comparison-nfc-grapheme-v2` through analysis, Stage 7, inherited Stage
8, and Stage 9B.4 verification fingerprints. The old `இல்லை -> இல ல` failure
is now `இல்லை -> இல்லை`; Greek `οὐ` versus Tamil `இல்லை` preserves POLARITY
and does not create a false `NEGATION_PROBLEM`.

Verified V1.1 gates:

```text
focused semantic/cache/correction                    175 passed
full Python plus Greek Room                         1069 passed
frontend Vitest                                      310 passed / 24 files
Svelte check                                         0 errors / 0 warnings
frontend production build                            passed
Rust tests                                           12 passed
cargo check                                          passed
git diff --check                                     passed
```

## 44.8 Non-negotiable continuity rules

- Never hardcode Tamil, Philippians, or a fixed verse window.
- Verse numbers are reference anchors, not semantic boundaries.
- Never rewrite Scripture automatically or reuse stale imported wording.
- Never silently move, replace, or approve human work.
- Never equate unaligned, null-aligned, not-located, and missing.
- Never convert search/computation failure into omission/addition.
- Never treat embeddings or translation helps as proof.
- Never manufacture same-verse translationCore alignment for cross-verse
  meaning.
- Persistent spans remain half-open Unicode code-point offsets over raw text.
- Correction Apply requires exact reference, span, current text,
  revision/hash, CAS, and explicit human action; normalized text is never an
  edit coordinate.
- Keep dependency/coverage DAGs separate from cyclic semantic relation graphs.
- Preserve one authoritative active lexical solution per scope/profile/layers
  and exclusive membership within each lexical layer.
- Keep `ReviewStatus`, `LifecycleStatus`, and `QaDisposition` independent.
- Preserve clean USFM and native translationCore behavior.

## 44.9 Current next boundary (superseded — see 44.10)

The next safe operational sequence was:

1. verify the clean local V1.1 commit stack and remote relation; **done**;
2. push V1.1 to `origin/main` only with explicit authorization; **done
   2026-09-11**, see 44.10;
3. build an internal Windows acceptance installer without publishing a
   release; **done**, see 44.10;
4. test real Tamil and other available multilingual projects, including old
   semantic caches; **partially done** — a real-pipeline Tamil-negation
   fixture now exists (44.10), but the full installed, human-driven GUI
   walkthrough across Cases A-D in `docs/V1_1_UNICODE_ACCEPTANCE.md` is
   still pending;
5. confirm fresh fingerprints, preserved human decisions, byte-identical
   Scripture during analysis, exact Stage 9B correction safety, and unchanged
   translationCore behavior; **pending** (needs the same GUI walkthrough);
6. record installed-acceptance evidence; **pending**;
7. request an explicit V1.2 boundary; **not reached**.

Do not begin V1.2, cross-verse visualization, new semantic dimensions,
production providers, export/Scripture Burrito work, a version bump, or a
release without separate approval.

## 44.10 V1.1 installed-acceptance build, real Tamil-negation fixture, and
V11-001 verse-editor fix (2026-09-11)

**Local acceptance build.** `npm run tauri build` from V1.1 HEAD produced
`Bridge_V1.1-prerelease_x64-setup.exe` (sha256
`c961c640c60ba73485da2f4c840829b3da74266982bbe2a05a7acef30112b52c`, embedded
version still `0.9.6` — unchanged, no silent bump). The bundler always
writes `Bridge_0.9.6_x64-setup.exe`, the same filename as the published
release, so the original was backed up before the build and restored
byte-for-byte afterward (sha256
`c7328d6c0bd48c570b0a24391630744d6f0449cf7fe6217ecf4f6ef0bc7d0c3d`, verified
identical before/after). Full detail, all four acceptance cases, and the
pending human GUI checklist are in `docs/V1_1_UNICODE_ACCEPTANCE.md`.

**Real Tamil-negation acceptance fixture (V1.1 Case A).** The original
Case A/B/C acceptance fixtures (`scripts/seed_correction_acceptance.py`)
covered Stage 9B.4's correction loop but not the Unicode-comparison
regression itself. Added `seed_case_a_negation()` / destination folder
`D-tamil-negation`, restaging — verbatim, not invented — the exact
Greek `οὐ` / Tamil `இல்லை` pair from the `ef49e9e` unit tests
(`test_tamil_negation_preserves_polarity_with_combining_marks`,
`test_tamil_negative_preservation_does_not_emit_false_negation_problem`) at
the real reference **PHP 1:22**, whose bundled UGNT text genuinely ends
"...οὐ γνωρίζω". Runs the real Stage 5→6A→6B→7→8 pipeline via
`AnalysisJobManager` (the same pattern as `seed_case_c()`). Confirmed the
source token is genuinely bundled, not fabricated (`resourceId: "ugnt"`,
`resourceVersion: "0.34"`, `strong: "G3756"`), and the result: Stage 7
POLARITY `PRESERVED` (confidence 0.96, "Explicit negative polarity is
present on both sides"), Stage 8 zero `NEGATION_PROBLEM` findings (9
`POSSIBLE_OMISSION` findings, expected since only `οὐ` carries a matching
fixture embedding vector). Reproduced identically across independent runs.
Additive only — `seed_case_a/b/c` and their destination folders are
untouched.

**V11-001 fixed: verse editor did not refresh after a correction applied.**
Root cause: `CorrectionReviewPanel.svelte`'s `applyCorrection()` refreshed
eligibility/context/proposals on `COMPLETED` but never touched the shared
`verseTexts` store, so the editor pane kept showing pre-correction text
until a full project reload. Fix respects the Phase 2 invariant (frontend
mirrors persisted backend state, never computes it locally): the backend's
own application response already carries the authoritative new text at
`resultMetadata.canonicalEdit.newText` (confirmed against a real applied
record), so a new `refreshVerseTextFromApplication()` helper in
`verseEditor.ts` reads that — keyed off `targetDisplayedReference`, the
correction's target verse, never the finding's source verse — and updates
`verseTexts` plus `alignmentStatusByVerse` (marking the verse `invalid`,
since application invalidates Word Alignment). No backend/protocol change.
Test-first: two new Vitest cases in `CorrectionReviewPanel.test.ts`
confirmed failing pre-fix (55 passed/1 failed) and passing post-fix
(56/56), via a temporary `git stash` of just the two source files.

**Frontend gates after both changes:** Vitest 312 passed / 24 files
(baseline 310/24, delta is exactly the two new tests), `svelte-check` 0
errors/0 warnings, production build passed (same pre-existing >500 kB
chunk warning). Schema, verification policy, and app version all remain
unchanged (`v14`, `correction-verification-policy-v2`, `0.9.6`).

Not yet done: the human-driven installed GUI walkthrough of
`docs/V1_1_UNICODE_ACCEPTANCE.md`'s Cases A-D, and any V1.2 scoping.
