# Bridge — Passage-Aware Semantic Alignment & Translation QA Requirements

**Repository path:** `docs/passage-aware-semantic-alignment.md`  
**Status:** Implementation requirements / architecture specification  
**Target application:** Bridge — Scripture Translation Quality Workbench  
**Revision:** 2.0  
**Primary purpose:** Define a safe, language-independent system for aligning Biblical Hebrew/Aramaic/Greek source meaning to any imported target-language Bible and using that alignment as evidence for detecting additions, omissions, undertranslation, overtranslation, and other meaning problems.

---

# 1. Primary Goal

Bridge is not building alignment merely to show Hebrew/Aramaic/Greek words connected to target-language words.

The primary QA goal is:

> **Establish bidirectional semantic coverage between the Biblical source text and the imported target translation so that Bridge can identify possible omissions, additions, and meaning changes with as few false positives as possible.**

Bridge must perform two complementary audits.

## 1.1 Source Coverage Audit

For every meaningful source semantic unit, Bridge asks:

> **Where and how is this source meaning represented in the target passage?**

If the meaning is not adequately represented after all legitimate translation mechanisms are considered, Bridge should flag a possible omission or undertranslation.

```text
SOURCE MEANING
      ↓
Find target realization
      ↓
Lexical?
Grammatical?
Pronominal?
Implicit?
Merged?
Split?
Cross-verse?
Explicitly restructured?
      ↓
Check tN / tW / TWL / context
      ↓
Still unsupported?
      ↓
⚠ POSSIBLE OMISSION
```

---

## 1.2 Target Support Audit

For every meaningful target semantic unit, Bridge asks:

> **What source meaning, grammatical requirement, contextual inference, or legitimate translation transformation supports this target meaning?**

If a significant target meaning cannot be licensed after all legitimate explanations are considered, Bridge should flag a possible addition or overtranslation.

```text
TARGET MEANING
      ↓
Find source support
      ↓
Direct source meaning?
Required target grammar?
Legitimate explicitation?
Discourse requirement?
Contextually licensed?
tN / tW / TWL supported?
      ↓
Still unsupported?
      ↓
⚠ POSSIBLE ADDITION
```

---

## 1.3 Detection is not automatic correction

Bridge may:

- detect;
- classify;
- explain;
- show evidence;
- propose a correction.

Bridge must **not silently rewrite Scripture**.

Required workflow:

```text
DETECT
  ↓
EXPLAIN
  ↓
PROPOSE CORRECTION
  ↓
HUMAN REVIEW
  ↓
APPLY / EDIT / REJECT
  ↓
INVALIDATE AFFECTED ALIGNMENTS
  ↓
REALIGN
  ↓
RE-RUN QA
```

All target-text changes require explicit human action.

---

# 2. Core Alignment Principle

Traditional word alignment often assumes:

```text
Source verse N → Target verse N
```

and:

```text
Source word → Target word
```

Bridge must not make either assumption mandatory.

The governing principle is:

> **Bridge aligns semantic realization first and lexical tokens second.**

The central question is not:

> “Which target word corresponds to this Hebrew/Aramaic/Greek word?”

It is:

> **“Where, and by what linguistic mechanism, is this source-language meaning represented in the target passage?”**

This allows Bridge to handle natural translation behavior without creating false omission/addition warnings.

---

# 3. Passage-Aware Rather Than Verse-Locked

Verse numbers are important for:

- navigation;
- export;
- display;
- provenance;
- external-tool interoperability.

But verse numbers are **not semantic boundaries**.

A source meaning may be realized:

- in the same target verse;
- in an adjacent verse;
- several verses away inside the same discourse unit;
- across multiple target verses;
- in a reordered target clause;
- across a chapter boundary when the discourse requires it.

Bridge therefore needs bounded passage-aware search.

---

# 4. Alignment Architecture

Bridge should maintain two related but distinct layers.

```text
                 BRIDGE ALIGNMENT GRAPH
                          │
             ┌────────────┴────────────┐
             │                         │
      SEMANTIC LAYER             LEXICAL LAYER
             │                         │
 may overlap / nest             exclusive token
 semantic units                membership per active
 passage relationships          alignment solution
 meaning QA
 implicit/grammar              1:1 / 1:N / N:1 / N:N
 discourse structure           source→null / null→target
             │                         │
             └────────────┬────────────┘
                          │
                    EXPORT LAYER
```

## 4.1 Semantic layer

The semantic layer may:

- span multiple lexical groups;
- overlap lexical groups;
- represent clauses, propositions, participants, relations, idioms, discourse functions, and implicit meanings;
- cross verses;
- cross chapter boundaries if necessary;
- represent meaning without direct lexical counterparts.

## 4.2 Lexical layer

The lexical layer represents concrete source-token ↔ target-token grouping.

This layer has a strict **exclusive token membership invariant**.

---

# 5. Exclusive Token Membership — HARD INVARIANT

Within one active lexical alignment solution:

> **Each source token may belong to at most one lexical alignment group.**

> **Each target token may belong to at most one lexical alignment group.**

This does **not** prohibit one-to-many, many-to-one, or many-to-many alignment.

Those relationships must exist as **one composite alignment group**, not as overlapping groups.

## 5.1 Valid

```text
GROUP A

SOURCE
[S1 S2 S3]

       ↕

TARGET
[T4 T5]

Cardinality:
MANY_TO_MANY
```

All five tokens belong to one group.

---

## 5.2 Invalid target-token reuse

```text
GROUP A:
S1 S2 ↔ T5

GROUP B:
S3 ↔ T5      ❌ INVALID
```

`T5` has been reused across groups.

---

## 5.3 Invalid source-token reuse

```text
GROUP A:
S1 ↔ T5

GROUP B:
S1 ↔ T6      ❌ INVALID
```

`S1` has been reused across groups.

---

## 5.4 Required engine invariant

Conceptually:

```text
count(activeLexicalGroupsContaining(sourceTokenId)) <= 1

count(activeLexicalGroupsContaining(targetTokenId)) <= 1
```

The database/API should reject an active alignment solution that violates this rule.

---

## 5.5 Semantic annotations are different

Exclusive token ownership applies to **lexical alignment groups**, not to all semantic annotations.

Example:

```text
SEMANTIC UNIT: an idiom
        │
        ├── lexical group A
        ├── lexical group B
        └── lexical group C
```

A semantic annotation may refer to multiple lexical groups.

This is valid.

---

# 6. Supported Lexical Alignment Cardinalities

Bridge must support:

```text
ONE_TO_ONE
ONE_TO_MANY
MANY_TO_ONE
MANY_TO_MANY
SOURCE_TO_NULL
NULL_TO_TARGET
```

## 6.1 ONE_TO_ONE

```text
S1 ↔ T1
```

## 6.2 ONE_TO_MANY

```text
S1 ↔ [T1 T2 T3]
```

## 6.3 MANY_TO_ONE

```text
[S1 S2 S3] ↔ T1
```

## 6.4 MANY_TO_MANY

```text
[S1 S2] ↔ [T1 T2 T3]
```

## 6.5 SOURCE_TO_NULL

```text
S1 → Ø
```

No direct target lexical counterpart has been assigned.

## 6.6 NULL_TO_TARGET

```text
Ø → T1
```

No direct source lexical counterpart has been assigned.

---

# 7. Null Alignment — REQUIRED

Null alignment is required because Bridge must distinguish:

```text
UNALIGNED
```

from:

```text
intentionally no direct lexical counterpart
```

These are not the same.

## 7.1 Required distinction

```text
UNALIGNED
≠ NULL_ALIGNED
≠ NOT_LOCATED
≠ MISSING
```

### `UNALIGNED`

No alignment decision has yet been completed.

### `NULL_ALIGNED`

Bridge or a human deliberately determined that there is no direct lexical counterpart.

### `NOT_LOCATED`

Bridge expected some realization but could not reliably locate it.

### `MISSING`

After semantic, grammatical, contextual, passage, and resource checks, the source meaning appears genuinely absent from the target.

---

## 7.2 Source-to-null does not automatically mean omission

Example:

```text
SOURCE TOKEN
     ↓
     Ø

Lexical status:
NULL_ALIGNED

Realization:
GRAMMATICALLY_REALIZED

Coverage:
COVERED

QA:
NO ISSUE
```

---

## 7.3 Source-to-null may become omission

```text
SOURCE TOKEN
     ↓
     Ø

Lexical status:
NULL_ALIGNED

Realization:
NOT_LOCATED

Coverage:
MISSING

QA:
POSSIBLE_OMISSION / OMISSION
```

---

## 7.4 Null-to-target does not automatically mean addition

Example:

```text
Ø
↓
TARGET TOKEN

Property:
GRAMMATICAL_REQUIREMENT

Target support:
SOURCE_SUPPORTED / GRAMMATICALLY_REQUIRED

QA:
NO ISSUE
```

Or:

```text
Ø
↓
TARGET TOKEN

Property:
EXPLICITATED

Target support:
CONTEXT_SUPPORTED

QA:
NO ISSUE
```

---

## 7.5 Null-to-target may become addition

```text
Ø
↓
TARGET TOKEN

Target support:
UNSUPPORTED

QA:
POSSIBLE_ADDITION / ADDITION
```

---

## 7.6 Null groups consume token ownership

If:

```text
GROUP A:
S1 → Ø
```

then `S1` cannot simultaneously appear in another active lexical group.

Likewise:

```text
GROUP B:
Ø → T1
```

means `T1` cannot simultaneously appear in another active lexical group.

A null decision may be replaced, but it must be an explicit update with history preserved.

---

# 8. Semantic Realization States

Bridge must support at least:

```text
LEXICALLY_REALIZED
GRAMMATICALLY_REALIZED
PRONOMINALIZED
IMPLICIT
SPLIT
MERGED
CROSS_VERSE
NOT_LOCATED
UNCERTAIN
```

These states are not all mutually exclusive.

Prefer:

```json
{
  "realization": "LEXICALLY_REALIZED",
  "properties": [
    "CROSS_VERSE",
    "SPLIT"
  ]
}
```

---

## 8.1 `LEXICALLY_REALIZED`

Source meaning is overtly expressed by target lexical material.

---

## 8.2 `GRAMMATICALLY_REALIZED`

Source meaning is represented by target grammar rather than a direct lexical counterpart.

Examples:

- tense;
- aspect;
- agreement;
- possession;
- case;
- complement structure;
- morphology;
- syntactic relation;
- word order.

---

## 8.3 `PRONOMINALIZED`

A fuller source participant/expression is represented by:

- a pronoun;
- clitic;
- agreement marker;
- reduced referential expression.

Pronoun antecedent resolution must carry its own confidence.

If the antecedent is ambiguous, use `UNCERTAIN`.

---

## 8.4 `IMPLICIT`

Meaning is not overtly lexicalized but is reasonably recoverable from the target context or structure.

Use conservatively.

`IMPLICIT` must never become a generic excuse for a missing source meaning.

---

## 8.5 `SPLIT`

One source semantic unit is realized in multiple target spans.

The spans may be non-contiguous and may occur in different verses.

---

## 8.6 `MERGED`

Multiple source semantic units are jointly realized by one target expression.

At the lexical level this should be represented as one composite alignment group where applicable.

---

## 8.7 `CROSS_VERSE`

The semantic realization occurs outside the nominal source verse after versification normalization.

This is usually a valid property, not an error.

---

## 8.8 `NOT_LOCATED`

Bridge could not reliably find the realization.

This is a machine-location conclusion, not automatically a translation error.

---

## 8.9 `UNCERTAIN`

Evidence is insufficient or ambiguous.

Bridge should abstain rather than force a mapping.

---

# 9. Additional Transformation Properties

Useful non-error properties include:

```text
EXPLICITATED
NOMINAL_TO_VERBAL
VERBAL_TO_NOMINAL
REORDERED
DISCONTIGUOUS
CLAUSE_RESTRUCTURED
PARTICIPANT_EXPLICITATED
PARTICIPANT_PRONOMINALIZED
IDIOMATIC_REALIZATION
```

These describe translation behavior without automatically judging it as correct or incorrect.

---

# 10. Passage-Level Properties

Some relationships belong to an entire passage.

Required initial passage-level property:

```text
REORDERED
```

Example:

```text
SOURCE ORDER:
3 → 4 → 5 → 6

TARGET ORDER:
5 → 4 → 6 → 3
```

Bridge must not flag moved material as missing merely because its verse number changed.

---

# 11. Three Independent Judgments

Bridge must keep these separate.

## 11.1 Location confidence

> **Did Bridge probably find the corresponding target realization?**

Example:

```text
0.97
```

---

## 11.2 Realization mechanism

> **How is the source meaning represented?**

Example:

```text
LEXICALLY_REALIZED
+ CROSS_VERSE
```

---

## 11.3 Meaning status

> **Does the target realization preserve the intended source meaning?**

A high location score does not imply correct meaning.

Example:

```text
Location confidence: 0.98
Meaning status: PARTIAL
```

Meaning:

> We are very likely looking at the correct target expression, but an important source component may be missing.

---

# 12. Meaning Status

Bridge should support:

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

## 12.1 `PRESERVED`

Meaning appears adequately preserved.

## 12.2 `PRESERVED_WITH_RESTRUCTURING`

Meaning appears preserved through significant restructuring.

## 12.3 `PARTIAL`

The correct target location was likely found, but only part of the source meaning appears preserved.

## 12.4 `OVERTRANSLATED`

Target appears to add semantic specificity or content not adequately licensed.

## 12.5 `UNDERTRANSLATED`

Target appears to weaken or omit a significant source component.

## 12.6 `MEANING_SHIFT`

Target expression corresponds to the source but appears to change the intended meaning.

## 12.7 `CONTRADICTED`

Target expresses meaning incompatible with the source.

## 12.8 `UNVERIFIABLE`

Evidence is insufficient to judge meaning preservation.

---

# 13. Source Coverage Status

For source → target omission audit:

```text
COVERED
COVERED_BY_RESTRUCTURING
POSSIBLY_MISSING
MISSING
UNCERTAIN
```

## 13.1 Example: true lexical coverage

```text
Alignment:
ONE_TO_MANY

Realization:
LEXICALLY_REALIZED

Coverage:
COVERED
```

## 13.2 Example: non-lexical coverage

```text
Alignment:
SOURCE_TO_NULL

Realization:
GRAMMATICALLY_REALIZED

Coverage:
COVERED_BY_RESTRUCTURING
```

## 13.3 Example: possible omission

```text
Alignment:
SOURCE_TO_NULL

Realization:
NOT_LOCATED

Coverage:
POSSIBLY_MISSING
```

## 13.4 Example: confirmed omission

```text
Coverage:
MISSING

QA:
OMISSION
```

Confirmation should normally require high-confidence evidence and/or human review.

---

# 14. Target Support Status

For target → source addition audit:

```text
SOURCE_SUPPORTED
CONTEXT_SUPPORTED
GRAMMATICALLY_REQUIRED
EXPLICITATION_SUPPORTED
POSSIBLY_UNSUPPORTED
UNSUPPORTED
UNCERTAIN
```

Example:

```text
Target token:
T19

Lexical alignment:
NULL_TO_TARGET

Property:
EXPLICITATED

Support:
CONTEXT_SUPPORTED

QA:
NO ISSUE
```

Versus:

```text
Target token:
T27

Lexical alignment:
NULL_TO_TARGET

Support:
UNSUPPORTED

QA:
POSSIBLE_ADDITION
```

---

# 15. QA Finding Types

Bridge should initially support at least:

```text
POSSIBLE_OMISSION
OMISSION

POSSIBLE_ADDITION
ADDITION

POSSIBLE_UNDERTRANSLATION
UNDERTRANSLATION

POSSIBLE_OVERTRANSLATION
OVERTRANSLATION

MEANING_SHIFT
CONTRADICTION
REFERENT_PROBLEM
NEGATION_PROBLEM
QUANTITY_PROBLEM
TEMPORAL_PROBLEM
PARTICIPANT_PROBLEM
RESOURCE_CONFLICT
SOURCE_VARIANT_REVIEW
```

A finding should never be created solely because two strings fail to align lexically.

---

# 16. Addition/Omission Decision Process

## 16.1 Omission audit

```text
SOURCE SEMANTIC UNIT
      ↓
lexical mapping?
      ↓ no
grammar?
      ↓ no
pronoun/referent?
      ↓ no
implicit target realization?
      ↓ no
merged/split?
      ↓ no
cross-verse?
      ↓ no
passage reorder?
      ↓ no
tN/tW/TWL/context support?
      ↓ no
source variant?
      ↓ no
UNCERTAIN vs MISSING
      ↓
POSSIBLE OMISSION
```

---

## 16.2 Addition audit

```text
TARGET SEMANTIC UNIT
      ↓
direct source support?
      ↓ no
target grammatical requirement?
      ↓ no
legitimate explicitation?
      ↓ no
implicit source meaning?
      ↓ no
discourse requirement?
      ↓ no
tN/tW/TWL/context support?
      ↓ no
source variant?
      ↓ no
UNCERTAIN vs UNSUPPORTED
      ↓
POSSIBLE ADDITION
```

---

# 17. Evidence Model

No single model score should decide an alignment or QA finding.

Evidence should include as available:

```text
Original-language surface form
Lemma
Morphology
Syntax
Clause structure
Semantic roles
Discourse structure
Named entities
Participant tracking
Negation
Quantification
Temporal relations
Spatial relations
Coreference
Passage context
Multilingual semantic similarity
Approved local equivalents
Target morphology
Target syntax
tN
tW
TWL
Human-approved mappings
Source textual/version information
```

Each finding must retain evidence provenance.

---

# 18. tN / tW / TWL Role

## 18.1 translationWords (tW)

Use tW as concept-level semantic evidence.

Do not treat lexical resemblance alone as proof of equivalence.

---

## 18.2 translationWords Links (TWL)

Use TWL to connect a source occurrence to the relevant translationWord concept.

This reduces polysemy-related false positives.

---

## 18.3 translationNotes (tN)

Use tN as passage-specific evidence for:

- idioms;
- metaphors;
- figures of speech;
- implicit information;
- explicit information;
- grammar;
- discourse;
- referents;
- alternative translation structures;
- contextual meaning.

---

## 18.4 Resource disagreement

If tN/tW/TWL conflict with:

- each other;
- the source analysis;
- the semantic candidate;

Bridge should create:

```text
RESOURCE_CONFLICT
```

or lower confidence.

Do not force an answer.

---

# 19. False-Positive Prevention — REQUIRED

Bridge should optimize for precision before recall.

## 19.1 Abstention

If evidence is insufficient:

```text
UNCERTAIN
```

is preferable to a forced mapping.

---

## 19.2 Candidate margin

Example:

```text
A = 0.87
B = 0.85
```

Normally:

```text
UNCERTAIN
```

Example:

```text
A = 0.91
B = 0.44
```

A is substantially stronger.

Thresholds must be calibratable rather than hardcoded forever.

---

## 19.3 Contradiction checks

Semantic similarity can be high for incompatible expressions.

Explicitly test:

```text
affirmation ↔ negation
all ↔ some
one ↔ many
before ↔ after
come ↔ go
give ↔ receive
father ↔ son
include ↔ exclude
present ↔ absent
possible ↔ impossible
```

---

## 19.4 Semantic component coverage

Example:

```text
SOURCE:
"all the brothers"

TARGET:
"the brothers"
```

Bridge may locate “brothers” with 99% confidence while still finding:

```text
ALL:
not located
```

Possible result:

```text
Location confidence: 0.99
Meaning status: PARTIAL
Coverage: POSSIBLY_MISSING
Finding: POSSIBLE_OMISSION
```

---

# 20. Stable Token Identity

Never rely only on visible word text.

Repeated words create ambiguity.

Every token should have stable identity using some combination of:

```text
project ID
resource version
book
chapter
verse
occurrence
token index
character span
normalized form
raw form
source token metadata
```

Bridge must be able to distinguish two identical surface forms in the same verse.

---

# 21. Raw Text vs Normalized Text

Preserve:

```text
raw text
```

separately from:

```text
normalized analysis form
```

Normalization may include:

- Unicode normalization;
- punctuation normalization;
- optional case handling;
- script-specific normalization.

Never rewrite the user's Scripture simply because analysis normalization differs.

---

# 22. No-Space and Morphologically Complex Languages

Bridge must not assume whitespace-delimited words are the only linguistic unit.

Support:

```text
character span
orthographic token
sub-token
morpheme, when available
semantic unit
```

This is important for:

- agglutinative languages;
- polysynthetic languages;
- clitic-heavy languages;
- languages without spaces;
- orthographies with compound joining.

A single target orthographic word may validly represent several source words inside **one MANY_TO_ONE group**.

---

# 23. Versification — FIRST-CLASS REQUIREMENT

Bridge must not treat displayed verse numbers as universally equivalent.

Different projects may use different versification systems.

Required conceptual layer:

```text
DISPLAY REFERENCE
      ↓
PROJECT VERSIFICATION
      ↓
NORMALIZED / CANONICAL PASSAGE IDENTITY
      ↓
SEMANTIC ALIGNMENT
```

Only after versification normalization should Bridge classify a relationship as `CROSS_VERSE`.

Support:

- verse bridges;
- omitted verse numbers;
- split verses;
- merged verses;
- chapter boundary differences;
- alternate versification schemes.

---

# 24. Verse Bridges

Example:

```usfm
\v 4-5 ...
```

must not cause token IDs or mappings to become ambiguous.

A Bridge passage reference should be able to identify:

```text
source range
target range
canonical range
display range
```

independently.

---

# 25. Passage Search Window

Bridge should progressively expand search.

```text
A. same normalized target verse
      ↓
B. adjacent normalized verses
      ↓
C. current sentence / clause group
      ↓
D. paragraph / discourse unit
      ↓
E. selected passage
      ↓
F. bounded larger context, only when justified
      ↓
UNCERTAIN / NOT_LOCATED
```

Do not search an entire book without strong constraints for every token.

Semantic similarity elsewhere in the book can create false matches.

---

# 26. Arbitrary Passage Length

Do not hardcode:

```text
four verses
```

or any fixed passage size.

Bridge must support:

```text
2 verses
4 verses
15 verses
30 verses
a paragraph
a discourse section
a passage crossing a chapter boundary
```

The engine should operate on a bounded passage object, not a four-column UI.

---

# 27. Textual Variants / Source Reading Differences

A target Bible may follow a source reading different from the currently loaded critical/source edition.

Do not automatically classify this as addition/omission.

Possible workflow:

```text
apparent mismatch
      ↓
known source-text variant?
      ↓
yes
      ↓
SOURCE_VARIANT_REVIEW
```

Bridge should preserve:

- source resource;
- source version;
- token metadata;
- variant note/evidence where available.

---

# 28. Source Resource Version Locking

Every project must know exactly which source resource it was aligned against.

Example:

```json
{
  "sourceResource": "UGNT",
  "sourceVersion": "...",
  "book": "PHP",
  "sourceTextHash": "...",
  "tokenizationVersion": "..."
}
```

Likewise for UHB.

If the source resource changes:

```text
unchanged token → retain
reindexed token → migrate carefully
changed token → STALE / REVIEW
deleted token → invalidate
new token → UNALIGNED
```

Never silently carry an old source alignment onto changed source text.

---

# 29. Target Edit Invalidation / STALE State

Add required state:

```text
STALE
```

If target Scripture is edited after alignment:

```text
human-approved mapping
      ↓
target text changed
      ↓
alignment cannot be assumed valid
      ↓
STALE
```

Bridge may propose a likely relocated alignment, but must not silently reattach it.

Required behavior:

```text
Old mapping:
preserved in history

New candidate:
AI_PROPOSED

Human decision:
required if previous mapping was human-approved
```

---

# 30. Review State / Provenance

At minimum:

```text
AI_PROPOSED
HUMAN_APPROVED
HUMAN_REJECTED
HUMAN_MODIFIED
STALE
SUPERSEDED
```

Store:

```text
who/what created it
timestamp
model/engine version
resource versions
evidence snapshot/reference
previous revision
human note
```

Human-approved work must never be silently overwritten.

---

# 31. Local Learning from Human Approval

Human-approved mappings may improve future ranking.

Do not turn them into unconditional dictionary rules.

Store context such as:

```json
{
  "sourceLemma": "...",
  "sourceSense": "...",
  "sourceConcept": "...",
  "targetExpression": "...",
  "approvedOccurrences": 17,
  "targetLanguage": "...",
  "projectScope": "...",
  "bookScope": "...",
  "provenance": "HUMAN_APPROVED"
}
```

Use as evidence only.

---

# 32. Suggested Semantic Relationship Model

```json
{
  "id": "PHP.1.5.SU003",

  "source": {
    "resource": "UGNT",
    "resourceVersion": "...",
    "language": "el-x-koine",
    "references": ["PHP 1:5"],
    "tokenIds": [],
    "spans": [],
    "surface": "",
    "lemmas": [],
    "semanticUnit": "",
    "conceptIds": [],
    "morphology": [],
    "syntax": {},
    "discourse": {}
  },

  "target": {
    "language": "ta",
    "references": ["PHP 1:3"],
    "tokenIds": [],
    "spans": [
      {
        "reference": "PHP 1:3",
        "start": 0,
        "end": 0,
        "tokenIds": []
      }
    ]
  },

  "mapping": {
    "realization": "LEXICALLY_REALIZED",
    "properties": [
      "CROSS_VERSE",
      "EXPLICITATED"
    ],
    "locationConfidence": 0.96,
    "meaningStatus": "PRESERVED_WITH_RESTRUCTURING",
    "meaningConfidence": 0.93,
    "sourceCoverage": "COVERED_BY_RESTRUCTURING",
    "targetSupport": "SOURCE_SUPPORTED"
  },

  "resourceValidation": {
    "tn": {
      "checked": true,
      "status": "CONSISTENT"
    },
    "tw": {
      "checked": true,
      "status": "CONSISTENT"
    },
    "twl": {
      "checked": true,
      "status": "CONSISTENT"
    }
  },

  "evidence": [],
  "alternatives": [],

  "review": {
    "status": "AI_PROPOSED",
    "humanDecision": null,
    "reviewerNote": null
  }
}
```

---

# 33. Suggested Lexical Group Model

```json
{
  "id": "PHP.1.5.LG008",
  "sourceTokenIds": ["s12", "s13"],
  "targetTokenIds": ["t41", "t42", "t43"],
  "cardinality": "MANY_TO_MANY",
  "lexicalStatus": "ALIGNED",
  "semanticRelationshipIds": ["PHP.1.5.SU003"],
  "review": {
    "status": "AI_PROPOSED"
  }
}
```

Null example:

```json
{
  "id": "PHP.1.5.LG009",
  "sourceTokenIds": ["s14"],
  "targetTokenIds": [],
  "cardinality": "SOURCE_TO_NULL",
  "lexicalStatus": "NULL_ALIGNED",
  "semanticRelationshipIds": ["PHP.1.5.SU004"]
}
```

Database validation must prevent token reuse across active lexical groups.

---

# 34. Passage Record

```json
{
  "sourceRange": "PHP 1:3-6",
  "targetRange": "PHP 1:3-6",
  "canonicalRange": "...",
  "properties": [
    "REORDERED"
  ],
  "semanticRelationshipIds": [],
  "lexicalGroupIds": [],
  "qaFindingIds": []
}
```

---

# 35. QA Finding Model

```json
{
  "id": "QA-PHP-1-6-004",
  "type": "POSSIBLE_OMISSION",
  "severity": "REVIEW",
  "sourceRelationshipId": "PHP.1.6.SU004",
  "targetReferences": ["PHP 1:5"],
  "locationConfidence": 0.98,
  "meaningConfidence": 0.72,
  "summary": "Possible missing completion component.",
  "evidence": [],
  "resourceChecks": {
    "tn": "REVIEW",
    "tw": "NOT_APPLICABLE",
    "twl": "NOT_APPLICABLE"
  },
  "review": {
    "status": "AI_PROPOSED"
  }
}
```

---

# 36. UI — Alignment Review

The existing Word Alignment popup should evolve into:

```text
ALIGNMENT REVIEW

[Word] [Semantic] [Passage] [QA]
```

Do not remove existing word-alignment functionality.

---

# 37. Word Mode

Use for conventional lexical alignment.

Must enforce:

- exclusive token membership;
- null groups;
- 1:1 / 1:N / N:1 / N:N;
- human approval protection.

---

# 38. Semantic Mode

Focus on one semantic relationship.

Display:

```text
SOURCE SEMANTIC UNIT
      ↓
source tokens / phrase
      ↓
TARGET REALIZATION
      ↓
target span(s)
```

Only draw connectors for the selected mapping to avoid a spaghetti graph.

---

# 39. Passage Mode

Support arbitrary passage length.

For small passages, compact mapping chips are acceptable:

```text
G 1:3 → T 1:6 ✓98%
G 1:4 → T 1:4 ✓99%
G 1:5 → T 1:3 ✓96%
G 1:6 → T 1:5 ⚠94%
```

For large passages use:

- virtualized relationship list;
- scrollable navigator;
- minimap/timeline;
- grouped status summary;
- filters.

Do not render one permanent card/column per verse.

---

# 40. QA Mode

This mode should surface only meaningful review findings.

Filters:

```text
All findings
Possible omissions
Possible additions
Meaning shifts
Resource conflicts
Uncertain
Human reviewed
Unreviewed
```

A translator should not have to inspect every successful alignment.

---

# 41. Target Passage Stream

In Passage/Semantic mode:

```text
▸ 1:3 target verse...
▸ 1:4 target verse...
▾ 1:5 target verse...
▸ 1:6 target verse...
...
```

Support:

- virtualization;
- search;
- collapse/expand;
- jump to link;
- show linked only;
- show uncertain only;
- show QA findings only.

---

# 42. Evidence Inspector

For the selected relationship show:

```text
LOCATION
96%

TARGET
Philippians 1:3

REALIZATION
LEXICALLY_REALIZED

PROPERTIES
CROSS_VERSE
EXPLICITATED

SOURCE COVERAGE
COVERED_BY_RESTRUCTURING

TARGET SUPPORT
SOURCE_SUPPORTED

MEANING
PRESERVED_WITH_RESTRUCTURING

MEANING CONFIDENCE
93%

EVIDENCE
✓ source context
✓ source morphology
✓ tN
✓ tW
✓ TWL

ACTIONS
[Accept Mapping]
[Reject Mapping]
[Mark Issue]
[Ignore Finding]
[Edit Target Text]
[Add Note]
```

---

# 43. Mapping Error vs Translation Error

The UI must distinguish these.

## 43.1 Mapping error

> Bridge selected the wrong target expression.

Action:

```text
Reject Mapping
```

## 43.2 Translation error

> Bridge likely found the correct target location, but the target meaning appears incomplete, added, or changed.

Action:

```text
Confirm Translation Issue
```

These are fundamentally different and must not share one generic “Reject” action.

---

# 44. Omission UI

Example:

```text
┌──────────────────────────────────────────────┐
│ ⚠ POSSIBLE OMISSION                         │
│                                              │
│ SOURCE COMPONENT                             │
│ [source phrase / semantic component]         │
│                                              │
│ TARGET LOCATION                              │
│ [target phrase]                              │
│                                              │
│ Location confidence: 98%                     │
│ Semantic coverage: PARTIAL                   │
│                                              │
│ Not found as:                                │
│ ✗ lexical                                   │
│ ✗ grammatical                               │
│ ✗ pronoun                                   │
│ ✗ implicit                                  │
│ ✗ split/merged                              │
│ ✗ cross-verse                               │
│                                              │
│ Resources checked                            │
│ ✓ tN                                        │
│ ✓ tW/TWL as applicable                      │
│                                              │
│ [Accept as Correct]                          │
│ [Confirm Omission]                           │
│ [Edit Target]                                │
│ [Ignore]                                     │
└──────────────────────────────────────────────┘
```

---

# 45. Addition UI

Example:

```text
┌──────────────────────────────────────────────┐
│ ⚠ POSSIBLE ADDITION                         │
│                                              │
│ TARGET EXPRESSION                            │
│ [highlighted target text]                    │
│                                              │
│ Direct source support                        │
│ None located                                 │
│                                              │
│ Checked                                      │
│ ✓ source lexical meaning                    │
│ ✓ grammar                                   │
│ ✓ context                                   │
│ ✓ explicitation                             │
│ ✓ tN                                        │
│ ✓ tW/TWL as applicable                      │
│                                              │
│ [Accept as Correct]                          │
│ [Confirm Addition]                           │
│ [Edit Target]                                │
│ [Ignore]                                     │
└──────────────────────────────────────────────┘
```

---

# 46. Correction Workflow

If a reviewer confirms a translation issue:

```text
Confirmed issue
      ↓
[Suggest Correction]
      ↓
Bridge proposes candidate target revision
      ↓
Show:
- current text
- suggested text
- source evidence
- tN/tW/TWL evidence
- semantic reason
      ↓
Human:
[Apply] [Edit Suggestion] [Reject]
```

After applying:

```text
affected alignments → STALE
affected QA findings → pending recheck
rerun semantic mapping
rerun source coverage
rerun target support
```

---

# 47. Export Architecture — IMPORTANT

The complete Bridge semantic model must **not** be forced into canonical USFM/SFM.

Bridge should maintain:

```text
                 BRIDGE INTERNAL MODEL
                         │
         ┌───────────────┼────────────────┐
         ▼               ▼                ▼
   CLEAN SCRIPTURE   tC/uW LEXICAL    RICH SEMANTIC
      USFM/SFM       ALIGNMENT VIEW      DATA
         │               │                │
      Paratext       translationCore    Bridge /
                                      Scripture Burrito
```

The Bridge model is the authoritative rich representation.

Exports are projections.

---

# 48. Clean USFM/SFM Export

For Paratext/general Scripture interchange, export valid Scripture USFM/SFM without Bridge-specific semantic metadata injected into the Scripture text.

Example:

```usfm
\p
\v 3 நற்செய்தி உங்களுக்கு அறிவிக்கப்பட்ட நாள் முதல் இதுவரைக்கும் நீங்கள் எங்களோடு ஊழியத்தில் ஐக்கியப்பட்டிருப்பதால்,
\v 4 நான் பண்ணுகிற ஒவ்வொரு விண்ணப்பத்திலும் உங்கள் அனைவருக்காகவும் எப்பொழுதும் மகிழ்ச்சியோடு ஜெபம் செய்து,
\v 5 உங்களில் நல்ல செயலைத் தொடங்கினவர் அதை இயேசு கிறிஸ்துவின் நாள் வரை நடத்தி வருவார் என்று நம்பி,
\v 6 நான் உங்களை நினைக்கும் போதெல்லாம் என் தேவனை ஸ்தோத்திரிக்கிறேன்.
```

Do not inject application concepts such as:

```text
CROSS_VERSE
LOCATION_CONFIDENCE
MEANING_STATUS
IMPLICIT
```

into the canonical Scripture text unless a formally supported interoperable extension is deliberately chosen.

---

# 49. translationCore / unfoldingWord Compatibility Projection

Bridge may export conventional lexical alignments using the ecosystem's aligned-USFM representation where the mapping can be represented truthfully.

Requirements:

- preserve 1:1;
- preserve 1:N;
- preserve N:1;
- preserve N:N;
- preserve original-language alignment metadata where supported;
- do not reuse source/target tokens across groups;
- do not fabricate same-verse relationships for cross-verse semantics.

---

# 50. Never Fake Cross-Verse Alignment for Export

Example:

```text
Greek 1:5 → Tamil 1:3
```

If an external aligned-USFM format assumes the source occurrence belongs to the same verse as the target, Bridge must **not pretend this is a normal same-verse lexical alignment**.

Instead:

```text
Semantic mapping:
VALID

translationCore-compatible lexical export:
NOT_DIRECTLY_REPRESENTABLE
```

or export only the portion that is truthfully representable.

The internal Bridge relationship must remain intact.

---

# 51. Semantic Validity vs Exportability

Every mapping should be capable of reporting:

```text
semanticValidity
exportability
```

separately.

Example:

```json
{
  "semanticValidity": "VALID",
  "exportability": {
    "bridge": "FULL",
    "cleanUSFM": "TEXT_ONLY",
    "translationCoreAlignedUSFM": "NOT_DIRECTLY_REPRESENTABLE",
    "scriptureBurrito": "FULL_OR_PARTIAL"
  }
}
```

A format limitation must not make a valid semantic mapping invalid.

---

# 52. Scripture Burrito Strategy

Where practical, Bridge should support packaging:

```text
Scripture text
+
lexical alignment data
+
Bridge semantic alignment/QA data
+
versification metadata
+
resource/version metadata
```

as separate ingredients/components rather than putting everything inside USFM.

Conceptual structure:

```text
BridgeProject/
│
├── wrapper / package metadata
│
├── scripture-text/
│   ├── *.usfm
│   └── versification metadata
│
├── lexical-alignment/
│   └── alignment data
│
└── bridge-semantic-alignment/
    ├── semantic relationships
    ├── QA findings
    ├── evidence
    └── human review history
```

If the standard Scripture Burrito Alignment flavor cannot represent a Bridge-specific semantic property, use Bridge's own supplemental/custom data rather than abusing standard fields.

---

# 53. USFM/SFM Round-Trip Safety

Required automated test:

```text
Import USFM
      ↓
parse
      ↓
no text edit
      ↓
export
      ↓
reparse
      ↓
Scripture content equivalent
```

Preserve semantically:

```text
Scripture characters
verse boundaries
paragraph structure
notes
cross-references
character markup
word markup
```

Formatting whitespace may vary if serialization requires it, but Scripture meaning/content must not change.

---

# 54. Existing Aligned-USFM Round-Trip Safety

For imported existing alignments:

```text
Import aligned USFM
      ↓
no alignment edit
      ↓
export aligned USFM
      ↓
reparse
      ↓
alignment semantics equivalent
```

Preserve:

```text
token identity
alignment group membership
source metadata
human review provenance
```

---

# 55. Non-Scripture Content

Do not align Scripture words against:

- headings;
- section titles;
- footnotes;
- cross-reference content;
- study notes;
- metadata.

These should live in separate content streams unless explicitly included by the user.

---

# 56. Punctuation

Punctuation may carry semantic/discourse information but should not automatically become a lexical alignment token.

Store it separately or classify appropriately.

Changes involving:

- quotation boundaries;
- question marks;
- punctuation-dependent discourse meaning;

may still produce QA evidence if semantically significant.

---

# 57. Repeated Expressions

Repeated phrases in the same passage can create high semantic similarity.

Use:

- occurrence;
- syntax;
- participant role;
- proximity;
- discourse structure;
- exclusive token ownership;

to prevent one target phrase from being incorrectly assigned to multiple source groups.

---

# 58. Pronoun / Coreference Edge Cases

A pronoun may represent:

- one explicit source noun phrase;
- an implicit participant;
- a discourse participant referenced several verses earlier.

Store:

```text
referentCandidate
referentConfidence
```

If multiple antecedents remain plausible:

```text
UNCERTAIN
```

Do not confidently assign the pronoun to the wrong participant.

---

# 59. Negation

Negation must be independently checked.

Examples:

```text
not
never
no one
nothing
without
```

A missing or added negation can reverse meaning even when the rest of the sentence aligns strongly.

Negation findings should receive high QA priority.

---

# 60. Quantity / Number

Check:

```text
all
some
many
few
one
two
each
every
none
singular/plural where semantically relevant
```

Do not assume morphological number differences are always errors; evaluate the semantic role.

---

# 61. Temporal / Aspectual Meaning

Check:

```text
before / after
already / not yet
continue / complete
begin / finish
past / ongoing / future
```

Target languages may realize these grammatically rather than lexically.

Therefore location and realization must be resolved before flagging omission.

---

# 62. Named Entities / Participants

Bridge should be careful with:

- names;
- titles;
- pronouns;
- kinship terms;
- honorifics;
- explicitating a referent.

An explicitly named participant may be a legitimate clarification rather than an addition.

---

# 63. Idioms and Figures of Speech

Do not require literal word coverage if a valid target idiom preserves the source meaning.

tN/context should strongly inform this.

Example conceptual result:

```text
surface lexical match: low
semantic preservation: high
realization: IDIOMATIC_REALIZATION
meaning: PRESERVED_WITH_RESTRUCTURING
```

---

# 64. Long-Distance Search Safety

Do not let an embedding model align a source semantic unit to a vaguely similar expression far away merely because it produces a high similarity score.

Use:

- bounded search;
- structural context;
- passage coherence;
- candidate margin;
- resource checks;
- local alignment consistency.

---

# 65. Concurrent Edits

If Bridge may eventually support multiple reviewers/processes:

- use revision IDs;
- detect stale writes;
- preserve history;
- never silently overwrite another reviewer's decision.

---

# 66. Engine Versioning

Every AI/algorithmic proposal should retain:

```text
engine version
model version
rule-set version
resource versions
timestamp
```

This allows reproducibility and comparison after engine upgrades.

---

# 67. Deterministic Validation Layer

Even when AI/embeddings propose mappings, hard invariants should be deterministic.

Examples:

```text
exclusive token membership
reference validity
span bounds
resource identity
token existence
null-group validity
review-lock protection
exportability rules
```

AI should never be allowed to override these invariants.

---

# 68. Pipeline

Recommended pipeline:

```text
IMPORT TARGET SCRIPTURE
        ↓
PRESERVE RAW TEXT / MARKUP
        ↓
NORMALIZE FOR ANALYSIS
        ↓
LOAD UHB / UGNT SOURCE
        ↓
PIN RESOURCE VERSIONS
        ↓
VERSIFICATION NORMALIZATION
        ↓
SOURCE SEMANTIC SEGMENTATION
        ↓
TARGET PASSAGE SEGMENTATION
        ↓
PASSAGE-AWARE CANDIDATE SEARCH
        ↓
SEMANTIC RELATIONSHIP PROPOSALS
        ↓
LEXICAL GROUP CONSTRUCTION
        ↓
EXCLUSIVE TOKEN OWNERSHIP CHECK
        ↓
NULL ALIGNMENT RESOLUTION
        ↓
SPLIT / MERGED / GRAMMAR /
PRONOUN / IMPLICIT / CROSS-VERSE
        ↓
tN / tW / TWL VALIDATION
        ↓
CONTRADICTION / NEGATION /
QUANTITY / PARTICIPANT CHECKS
        ↓
SOURCE COVERAGE AUDIT
        ↓
TARGET SUPPORT AUDIT
        ↓
ADDITION / OMISSION /
MEANING QA FINDINGS
        ↓
HUMAN REVIEW
        ↓
OPTIONAL CORRECTION
        ↓
REALIGN + RECHECK
```

---

# 69. Integration Test — IRVTam Philippians 1:3–6

Use this exact target passage as a regression/integration test.

```usfm
\p
\v 3 நற்செய்தி உங்களுக்கு அறிவிக்கப்பட்ட நாள் முதல் இதுவரைக்கும் நீங்கள் எங்களோடு ஊழியத்தில் ஐக்கியப்பட்டிருப்பதால்,
\v 4 நான் பண்ணுகிற ஒவ்வொரு விண்ணப்பத்திலும் உங்கள் அனைவருக்காகவும் எப்பொழுதும் மகிழ்ச்சியோடு ஜெபம் செய்து,
\v 5 உங்களில் நல்ல செயலைத் தொடங்கினவர் அதை இயேசு கிறிஸ்துவின் நாள் வரை நடத்தி வருவார் என்று நம்பி,
\v 6 நான் உங்களை நினைக்கும் போதெல்லாம் என் தேவனை ஸ்தோத்திரிக்கிறேன்.
```

Expected passage-level semantic ordering:

```text
Greek 1:3 → Tamil 1:6
Greek 1:4 → Tamil 1:4
Greek 1:5 → Tamil 1:3
Greek 1:6 → Tamil 1:5
```

Passage property:

```text
REORDERED
```

This is an integration-test expectation only.

Do **not** hardcode this mapping into the engine.

The engine must discover the relationship.

---

# 70. Philippians 1:3 → IRVTam 1:6

Target:

```text
நான் உங்களை நினைக்கும் போதெல்லாம் என் தேவனை ஸ்தோத்திரிக்கிறேன்.
```

Expected behavior:

```text
Source reference:
PHP 1:3

Target reference:
PHP 1:6

Realization:
LEXICALLY_REALIZED

Properties:
CROSS_VERSE
NOMINAL_TO_VERBAL

Location confidence:
HIGH

Meaning:
PRESERVED / review lexical nuance where necessary

Source coverage:
COVERED_BY_RESTRUCTURING
```

Bridge must not report Greek 1:3 as omitted merely because Tamil 1:3 contains different semantic material.

---

# 71. Philippians 1:4 → IRVTam 1:4

Target:

```text
நான் பண்ணுகிற ஒவ்வொரு விண்ணப்பத்திலும் உங்கள் அனைவருக்காகவும் எப்பொழுதும் மகிழ்ச்சியோடு ஜெபம் செய்து,
```

Expected strong semantic coverage for:

```text
always
every prayer/request
for all of you
with joy
praying/requesting
```

Likely:

```text
Location:
HIGH

Meaning:
PRESERVED
```

---

# 72. Philippians 1:5 → IRVTam 1:3

Target:

```text
நற்செய்தி உங்களுக்கு அறிவிக்கப்பட்ட நாள் முதல் இதுவரைக்கும் நீங்கள் எங்களோடு ஊழியத்தில் ஐக்கியப்பட்டிருப்பதால்,
```

Important relationships:

```text
gospel partnership
        ↓
நீங்கள் எங்களோடு ஊழியத்தில் ஐக்கியப்பட்டிருப்பதால்
```

```text
from the first day
        ↓
நற்செய்தி உங்களுக்கு அறிவிக்கப்பட்ட நாள் முதல்
```

```text
until now
        ↓
இதுவரைக்கும்
```

Possible:

```text
Realization:
LEXICALLY_REALIZED

Properties:
CROSS_VERSE
EXPLICITATED
CLAUSE_RESTRUCTURED

Meaning:
PRESERVED_WITH_RESTRUCTURING
```

Do not flag:

```text
எங்களோடு
ஊழியத்தில்
```

as additions merely because they lack simple one-word Greek counterparts.

First run the target-support audit using passage/context/tN/tW/TWL evidence.

---

# 73. Philippians 1:6 → IRVTam 1:5

Target:

```text
உங்களில் நல்ல செயலைத் தொடங்கினவர் அதை இயேசு கிறிஸ்துவின் நாள் வரை நடத்தி வருவார் என்று நம்பி,
```

Possible strong mappings:

```text
confidence → நம்பி
in you → உங்களில்
good work → நல்ல செயலை
the one who began → தொடங்கினவர்
until the day of Christ Jesus → இயேசு கிறிஸ்துவின் நாள் வரை
```

The component corresponding to completing/bringing the work to completion should be meaning-checked against:

```text
நடத்தி வருவார்
```

Possible QA result:

```text
Location confidence:
HIGH

Meaning confidence:
LOWER

Meaning:
PARTIAL / UNVERIFIABLE pending review

Finding:
POSSIBLE_UNDERTRANSLATION or no issue after human/contextual review
```

The important rule:

```text
LOCATION FOUND
≠
MEANING CONFIRMED
```

---

# 74. Philippians UI Example

```text
┌──────────────────────────────────────────────────────────────────────┐
│ ALIGNMENT REVIEW — Philippians 1:3–6                               │
│ [Word] [Semantic] [Passage] [QA]                                   │
├──────────────────────────────────────────────────────────────────────┤
│ ↔ REORDERING DETECTED                                               │
│                                                                      │
│ G1:3 → T1:6 ✓                                                       │
│ G1:4 → T1:4 ✓                                                       │
│ G1:5 → T1:3 ✓                                                       │
│ G1:6 → T1:5 ⚠                                                       │
├──────────────────────────────────────────────────────────────────────┤
│ SELECTED SOURCE UNIT                                                 │
│ Greek 1:6                                                            │
│ [source semantic unit]                                               │
│                         │                                            │
│                         ▼                                            │
│ TARGET REALIZATION                                                   │
│ Tamil 1:5                                                            │
│ [highlighted target span]                                            │
├───────────────────────────────────────────────┬──────────────────────┤
│ TARGET PASSAGE STREAM                         │ EVIDENCE / QA        │
│                                               │                      │
│ ▸ 1:3 நற்செய்தி ...                          │ Location: High       │
│ ▸ 1:4 நான் பண்ணுகிற ...                     │ Meaning: Review      │
│ ▾ 1:5 உங்களில் நல்ல ...                     │ Cross-verse ✓       │
│ ▸ 1:6 நான் உங்களை ...                       │ Possible omission ⚠ │
│                                               │                      │
│                                               │ [Accept]             │
│                                               │ [Confirm Issue]      │
└───────────────────────────────────────────────┴──────────────────────┘
```

---

# 75. Large Passage UX

Example summary:

```text
Passage: John 1:1–18

Semantic units: 74
Lexically covered: 41
Cross-verse: 8
Merged: 6
Split: 4
Implicit: 3
Null resolved: 5
Uncertain: 4
Possible omissions: 2
Possible additions: 1
Meaning review: 6
```

Reviewer can click:

```text
[Possible omissions: 2]
```

instead of reviewing all 74 mappings.

---

# 76. Required Tests

## 76.1 Exclusive token membership

- reject source-token reuse across active groups;
- reject target-token reuse across active groups;
- allow N:1 as one group;
- allow 1:N as one group;
- allow N:N as one group;
- null group consumes token ownership.

## 76.2 Null alignment

- distinguish `UNALIGNED` from `NULL_ALIGNED`;
- source→null + grammatical realization produces no omission;
- source→null + no realization may produce possible omission;
- null→target + grammatical requirement produces no addition;
- null→target + unsupported meaning may produce possible addition.

## 76.3 Cross-verse

- source semantic unit may map to another target verse;
- no same-verse false omission;
- export layer does not fabricate unsupported same-verse lexical metadata.

## 76.4 Reordering

- detect passage reorder;
- preserve coverage despite target order change.

## 76.5 Editing

- target edit marks affected mapping stale;
- human-approved mapping is not silently relocated;
- reanalysis creates a new proposal.

## 76.6 Source update

- source version change is detected;
- changed tokens are not silently reused.

## 76.7 Versification

- verse bridges;
- shifted verse boundaries;
- alternate versification;
- chapter-boundary mapping.

## 76.8 Additions

- target grammatical function word does not trigger false addition;
- legitimate explicitation does not trigger false addition;
- unsupported semantic content can trigger possible addition.

## 76.9 Omissions

- grammatical realization does not trigger false omission;
- pronoun realization does not trigger false omission;
- cross-verse realization does not trigger false omission;
- truly uncovered source component can trigger possible omission.

## 76.10 Contradiction

Test:

- negation;
- quantity;
- participant swap;
- temporal reversal;
- semantic antonymy.

---

# 77. Acceptance Criteria

## Alignment model

- [ ] ONE_TO_ONE supported.
- [ ] ONE_TO_MANY supported.
- [ ] MANY_TO_ONE supported.
- [ ] MANY_TO_MANY supported.
- [ ] SOURCE_TO_NULL supported.
- [ ] NULL_TO_TARGET supported.
- [ ] Source token cannot be reused across active lexical groups.
- [ ] Target token cannot be reused across active lexical groups.
- [ ] Semantic annotations may span multiple lexical groups.
- [ ] Split target spans supported.
- [ ] Merged source units supported.
- [ ] Cross-verse mappings supported.
- [ ] Grammatical realization supported.
- [ ] Pronoun realization supported.
- [ ] Implicit realization supported.
- [ ] Uncertainty/abstention supported.

## QA

- [ ] Source coverage audit exists.
- [ ] Target support audit exists.
- [ ] Possible omissions can be detected.
- [ ] Possible additions can be detected.
- [ ] Meaning status is independent from location confidence.
- [ ] tN/tW/TWL evidence is recorded.
- [ ] Contradiction checks exist.
- [ ] Negation checks exist.
- [ ] Quantity checks exist.
- [ ] Human reviewer can distinguish mapping error from translation error.
- [ ] Corrections require human approval.
- [ ] QA reruns after target edits.

## Passage behavior

- [ ] Same-numbered verses are not assumed.
- [ ] Reordered passage content is supported.
- [ ] Arbitrary passage length is supported.
- [ ] Passage may cross chapter boundary.
- [ ] Versification normalization occurs before cross-verse classification.

## Safety / provenance

- [ ] Source version pinned.
- [ ] Engine/model/rule version recorded.
- [ ] Target edits create `STALE` mappings.
- [ ] Human-approved work is protected.
- [ ] Revision history preserved.
- [ ] Raw Scripture text preserved separately from analysis normalization.

## UI

- [ ] Existing Word mode preserved.
- [ ] Semantic mode available.
- [ ] Passage mode available.
- [ ] QA mode available.
- [ ] Large passages virtualized/scrollable.
- [ ] Only focused mapping connectors shown by default.
- [ ] Target passage stream available.
- [ ] Additions/omissions filterable.
- [ ] Evidence visible.
- [ ] Human actions auditable.

## Export

- [ ] Clean USFM/SFM export remains available.
- [ ] Plain Scripture export contains no forced Bridge semantic metadata.
- [ ] Existing conventional lexical alignment can be projected where truthfully representable.
- [ ] Cross-verse semantic mappings are not falsified for translationCore export.
- [ ] Semantic validity is separate from exportability.
- [ ] Rich Bridge semantic data can be stored externally/sidecar/package.
- [ ] Scripture Burrito packaging strategy supported or planned.
- [ ] USFM round-trip tests pass.
- [ ] Existing aligned-USFM round-trip semantic tests pass.

---

# 78. Implementation Stages for the VS Code Coding Agent

## Stage 0 — Read this document completely

Do not modify code until the current repository has been inspected.

Treat this document as the architecture/requirements source for this feature.

If current implementation conflicts with this specification, report the conflict rather than silently choosing one side.

---

## Stage 1 — Repository Analysis ONLY

Inspect the existing Bridge repository and report:

1. current Word Alignment popup component(s);
2. alignment data types;
3. alignment stores/state management;
4. Python/Rust/TypeScript boundaries;
5. original-language source handling;
6. UHB/UGNT token identity;
7. target Scripture parser;
8. USFM/SFM parser;
9. aligned-USFM parser/exporter;
10. current contiguous-span validation;
11. tN access;
12. tW access;
13. TWL access;
14. persistence/database/project files;
15. human approval state;
16. target editing workflow;
17. source resource version handling;
18. current versification assumptions;
19. tests;
20. migration/backward-compatibility risks;
21. safest integration points.

**Do not implement anything during Stage 1.**

Return a concrete codebase-specific report with filenames, components, functions, and data flows.

---

## Stage 2 — Gap Analysis / Technical Design

Using the Stage 1 findings, propose:

- semantic relationship schema;
- lexical group schema;
- exclusive token-membership enforcement;
- null alignment representation;
- coverage status;
- target support status;
- QA finding schema;
- passage range/reference model;
- versification strategy;
- stable token IDs;
- stale/invalidation strategy;
- source-version locking;
- persistence;
- API boundaries;
- UI component hierarchy;
- export layer;
- compatibility adapters;
- migration plan;
- test plan.

Do not begin broad implementation until the design is approved.

---

## Stage 3 — Data Foundation

Implement first:

- lexical-group types;
- exclusive token membership;
- null alignment;
- semantic relationship types;
- QA finding types;
- provenance/review states;
- stale state;
- reference/range model;
- tests.

Do not yet redesign the entire UI.

---

## Stage 4 — Persistence and Migration

Add:

- backward-compatible persistence;
- project migration;
- existing alignment preservation;
- human-review preservation;
- resource/version metadata;
- regression tests.

---

## Stage 5 — Alignment Review UI

Implement:

```text
[Word] [Semantic] [Passage] [QA]
```

including:

- virtualized passage navigator;
- target passage stream;
- evidence inspector;
- addition/omission review;
- mapping-vs-translation-error distinction.

---

## Stage 6 — Passage-Aware Semantic Candidate Engine

Integrate:

- bounded passage search;
- semantic candidates;
- cardinality resolution;
- split/merged;
- cross-verse;
- grammatical realization;
- pronouns;
- implicit realization;
- candidate margin;
- abstention.

---

## Stage 7 — Resource Validation

Integrate:

- tN;
- tW;
- TWL;
- resource-conflict reporting.

---

## Stage 8 — Bidirectional QA

Implement:

```text
SOURCE COVERAGE AUDIT
TARGET SUPPORT AUDIT
```

Then:

- omission detection;
- addition detection;
- under/overtranslation;
- meaning shift;
- contradiction;
- negation;
- quantity;
- participants;
- temporal meaning.

---

## Stage 9 — Correction Workflow

Implement:

- correction proposal;
- human approval;
- edit;
- stale invalidation;
- rerun;
- audit history.

---

## Stage 10 — Export / Interoperability

Implement/test:

- clean USFM/SFM;
- existing translationCore-compatible lexical projection where valid;
- no fake cross-verse projection;
- semantic sidecar;
- Scripture Burrito packaging as appropriate;
- exportability status.

---

## Stage 11 — Full Regression

Test:

- fresh projects;
- partially worked projects;
- old Bridge projects;
- translationCore projects;
- human-approved alignments;
- null alignments;
- target edits;
- source version changes;
- different versifications;
- large passages;
- Philippians 1:3–6;
- OT Hebrew;
- OT Aramaic;
- NT Greek;
- multiple typologically different target languages.

---

# 79. Critical Constraints for the Coding Agent

Do **not**:

```text
hardcode Tamil
hardcode Philippians
hardcode four verses
assume same verse number = same semantic location
reuse a source token across active lexical groups
reuse a target token across active lexical groups
equate null alignment with omission/addition
equate unaligned with null-aligned
force a mapping when uncertain
treat embedding similarity as proof
treat tN/tW/TWL as infallible
silently overwrite human-approved work
silently relocate stale alignments
silently migrate changed source tokens
inject rich Bridge semantics into canonical Scripture USFM
fake cross-verse alignment to satisfy an external format
automatically rewrite Scripture after finding an issue
```

Do:

```text
align semantic realization before judging omission/addition
audit source→target and target→source
preserve exclusive lexical token ownership
support explicit null alignment
preserve raw Scripture
pin source versions
normalize versification
retain evidence/provenance
abstain when uncertain
protect human decisions
separate semantic validity from exportability
separate mapping errors from translation errors
require human approval for Scripture correction
rerun QA after edits
```

---

# 80. Governing Rules

The feature should be judged by these rules.

> **1. Align semantic realization first and lexical tokens second.**

> **2. Every source or target token may belong to at most one active lexical alignment group.**

> **3. One-to-many, many-to-one, and many-to-many are valid only as single composite groups, never by reusing tokens across groups.**

> **4. Null alignment is an explicit decision, not an error by itself.**

> **5. Absence of a lexical counterpart does not by itself constitute an omission.**

> **6. Presence of a target word without a lexical source counterpart does not by itself constitute an addition.**

> **7. Passage restructuring, grammar, pronouns, implicit meaning, split/merged expressions, cross-verse realization, and legitimate explicitation must be considered before flagging addition or omission.**

> **8. A confident location is not evidence that the meaning is correct.**

> **9. Bridge must audit both source coverage and target support.**

> **10. When evidence is insufficient, Bridge should say UNCERTAIN rather than manufacture certainty.**

> **11. Human-approved Scripture and alignment decisions must never be silently overwritten.**

> **12. Bridge's internal semantic model may be richer than USFM, translationCore aligned-USFM, or any other export format. Never falsify data merely to satisfy an external format.**

---

# 81. End-State Vision

The finished Bridge workflow should look conceptually like:

```text
HEBREW / ARAMAIC / GREEK
          ↓
ORIGINAL-LANGUAGE STRUCTURE
          ↓
SEMANTIC UNITS
          ↓
PASSAGE-AWARE TARGET SEARCH
          ↓
SEMANTIC REALIZATION GRAPH
          ↓
EXCLUSIVE LEXICAL ALIGNMENT GROUPS
          ↓
NULL RESOLUTION
          ↓
tN + tW + TWL + CONTEXT VALIDATION
          ↓
BIDIRECTIONAL COVERAGE
     ↙                ↘
SOURCE COVERAGE     TARGET SUPPORT
     ↓                ↓
OMISSION AUDIT      ADDITION AUDIT
       ↘              ↙
        MEANING QA
            ↓
      HUMAN REVIEW
            ↓
    CORRECT IF NEEDED
            ↓
       REALIGN
            ↓
        RECHECK
            ↓
       EXPORT SAFELY
```

The end goal is not “every word has a line.”

The end goal is:

> **Bridge can explain where source meaning went, why target meaning is present, what cannot be confidently accounted for, and where the human reviewer should investigate a possible translation error.**

