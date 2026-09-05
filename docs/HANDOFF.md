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
(`pytest engine/tests/test_meaning_analysis_stage7.py -q`).

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
`engine/tests/test_qa_audit_stage8.py`. Full narrative:
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
`engine/tests/test_passage_semantic_foundation.py`).

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

`engine/tests/test_php_review_walkthrough_stage9a.py` drives the review APIs
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
- no correction-generation workflow
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

Tests: `engine/tests/test_correction_stage9b0.py`, 55 passing.

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
4. **Resource-conflict rule is coarse.** Any entry in
   `conflictingEvidenceIds` blocks eligibility. If some conflicts are
   acceptable to correct through, that policy needs deciding.
5. **The Stage 9A review UI still has not had a human click-through** on a
   populated queue (carried over from the previous §37).

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
Stage 6B-8 reruns unless separately approved. No Stage 9B.3b work has begun.

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
Stage 9 — HUMAN REVIEW AND CORRECTION                     ◐ 9A–9B.2 done
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
4. Check whether the Stage 8 working tree was committed before changing
   code (`git status`/`git log --oneline -5`).
5. The next major implementation task is **Stage 9 — Human Review and
   Correction Workflow** (§37).
6. Do not implement Stage 9's export/Scripture Burrito follow-on (§38)
   until Stage 9 itself is complete, tested, and reviewed.
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
