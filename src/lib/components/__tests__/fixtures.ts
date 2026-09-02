import type { QaFindingDetail, QaFindingSummary } from "../../types/qaReview";

/**
 * Controlled UI fixtures.
 *
 * Shaped to match what the engine actually returns, and chosen to cover the
 * cases the review UI has to get right: a possible omission, an addition that
 * is legitimately required by target grammar, a quantity contradiction, an
 * ambiguous location with real competing candidates, a search that never
 * finished, a conflicting resource, and a stale finding a human already
 * confirmed.
 */

export function summary(overrides: Partial<QaFindingSummary> = {}): QaFindingSummary {
  return {
    id: "qa-finding-0001",
    kind: "POSSIBLE_OMISSION",
    direction: "SOURCE_COVERAGE",
    severity: "MEDIUM",
    book: "PHP",
    displayedReferences: ["PHP 1:3"],
    explanation: "No target expression carries this source obligation.",
    qaDisposition: "UNRESOLVED",
    reviewStatus: "AI_PROPOSED",
    lifecycleStatus: "ACTIVE",
    locationOutcomeSnapshot: "NOT_LOCATED",
    meaningStatusSnapshot: "",
    confidence: {
      rawScore: 0.75,
      calibratedValue: 0.75,
      confidencePolicyVersion: "qa-confidence-v1",
      calibrationVersion: "qa-uncalibrated-v1",
    },
    revision: 1,
    isPossible: true,
    ...overrides,
  };
}

export function manyFindings(count: number): QaFindingSummary[] {
  return Array.from({ length: count }, (_unused, index) =>
    summary({
      id: `qa-finding-${String(index).padStart(4, "0")}`,
      displayedReferences: [`PHP ${Math.floor(index / 30) + 1}:${(index % 30) + 1}`],
      severity: index % 5 === 0 ? "HIGH" : "MEDIUM",
    }),
  );
}

export function detail(overrides: Partial<QaFindingDetail> = {}): QaFindingDetail {
  return {
    finding: {
      id: "qa-finding-0001",
      kind: "POSSIBLE_OMISSION",
      severity: "MEDIUM",
      explanation: "No target expression carries this source obligation.",
      qaDisposition: "UNRESOLVED",
      reviewStatus: "AI_PROPOSED",
      lifecycleStatus: "ACTIVE",
      revision: 1,
      displayedReferences: ["PHP 1:3"],
      targetContentHashes: ["hash-1"],
    },
    source: [{
      id: "source-unit-1",
      rawSurface: "εὐχαριστέω",
      normalizedSurface: "ευχαριστεω",
      displayedReferences: ["PHP 1:3"],
      kind: "LEXICAL",
      semanticObligation: "REQUIRED",
      coverageDimension: "LEXICAL_CONTENT",
      accountingRole: "PRIMARY",
      auditEligibility: "ELIGIBLE",
      provenance: "DETERMINISTIC_RULE",
    }],
    target: [],
    location: [],
    meaning: [],
    coverage: [{
      id: "source-coverage-1",
      direction: "SOURCE_COVERAGE",
      coverageDimension: "LEXICAL_CONTENT",
      coverageStatus: "POSSIBLY_MISSING",
      revision: 1,
    }],
    resources: [],
    supportingEvidence: [],
    conflictingEvidence: [],
    history: [],
    isStale: false,
    reviewEngineVersion: "bridge-qa-review-v1",
    ...overrides,
  };
}

/** A located finding whose meaning failed on the quantity dimension. */
export function quantityContradiction(): QaFindingDetail {
  return detail({
    finding: {
      ...detail().finding,
      id: "qa-finding-quantity",
      kind: "QUANTITY_PROBLEM",
      severity: "HIGH",
      explanation: "The target states a different quantity than the source.",
    },
    location: [{
      location: {
        id: "location-1",
        locationOutcome: "LOCATED",
        reviewStatus: "AI_PROPOSED",
        revision: 1,
        targetDisplayedReferences: ["PHP 1:5"],
        targetQuote: "மூன்று",
        realization: "LEXICALLY_REALIZED",
        properties: ["CROSS_VERSE"],
        selectedCandidateId: "candidate-1",
      },
      alternatives: [],
    }],
    meaning: [{
      assessment: {
        id: "assessment-1",
        meaningStatus: "CONTRADICTED",
        reviewStatus: "AI_PROPOSED",
        revision: 1,
      },
      components: [
        { id: "c1", coverageDimension: "LEXICAL_CONTENT", status: "PRESERVED" },
        { id: "c2", coverageDimension: "QUANTITY", status: "CONTRADICTED" },
      ],
    }],
    coverage: [],
  });
}

/** An ambiguous location where the engine kept several real candidates. */
export function ambiguousLocation(): QaFindingDetail {
  return detail({
    finding: { ...detail().finding, id: "qa-finding-ambiguous", kind: "NEEDS_PASSAGE_REVIEW" },
    location: [{
      location: {
        id: "location-ambiguous",
        locationOutcome: "AMBIGUOUS",
        reviewStatus: "AI_PROPOSED",
        revision: 1,
        properties: [],
      },
      alternatives: [
        { id: "candidate-a", targetQuote: "நாள்", targetDisplayedReferences: ["PHP 1:3"] },
        { id: "candidate-b", targetQuote: "நாளில்", targetDisplayedReferences: ["PHP 1:5"] },
      ],
    }],
  });
}

/** A search that never finished: absence here proves nothing. */
export function searchIncomplete(): QaFindingDetail {
  return detail({
    finding: { ...detail().finding, id: "qa-finding-incomplete" },
    location: [{
      location: {
        id: "location-incomplete",
        locationOutcome: "SEARCH_INCOMPLETE",
        reviewStatus: "AI_PROPOSED",
        revision: 1,
        properties: [],
      },
      alternatives: [],
    }],
  });
}

/** An extra target word that the target language actually requires. */
export function grammaticallyRequiredAddition(): QaFindingDetail {
  return detail({
    finding: {
      ...detail().finding,
      id: "qa-finding-addition",
      kind: "POSSIBLE_ADDITION",
      explanation: "This target word has no direct source counterpart.",
    },
    coverage: [{
      id: "target-coverage-1",
      direction: "TARGET_SUPPORT",
      coverageDimension: "LEXICAL_CONTENT",
      coverageStatus: "GRAMMATICALLY_REQUIRED",
      revision: 1,
    }],
  });
}

/** Resource evidence that disagrees, which must stay visible as disagreement. */
export function resourceConflict(): QaFindingDetail {
  return detail({
    finding: { ...detail().finding, id: "qa-finding-resource", kind: "RESOURCE_CONFLICT" },
    resources: [{
      id: "evidence-1",
      evidenceSource: "EVIDENCE_RECORD",
      kind: "TRANSLATION_NOTE",
      content: "This phrase should be rendered as a blessing, not a greeting.",
      resourceId: "tn",
      resourceVersion: "v86",
      validationStatus: "SUPPORTING",
    }],
    conflictingEvidence: [{
      id: "evidence-2",
      evidenceSource: "EVIDENCE_RECORD",
      kind: "TRANSLATION_WORD",
      content: "The word list treats this term as a greeting.",
      resourceId: "tw",
      resourceVersion: "v86",
      validationStatus: "CONFLICTING",
    }],
  });
}

/** A stale finding a human already confirmed: history, not a current verdict. */
export function staleConfirmed(): QaFindingDetail {
  return detail({
    finding: {
      ...detail().finding,
      id: "qa-finding-stale",
      qaDisposition: "CONFIRMED_TRANSLATION_ERROR",
      reviewStatus: "HUMAN_APPROVED",
      lifecycleStatus: "STALE",
      revision: 3,
    },
    isStale: true,
    history: [{
      id: "review-1",
      entityType: "QA_FINDING",
      entityId: "qa-finding-stale",
      previousReviewStatus: "AI_PROPOSED",
      newReviewStatus: "HUMAN_APPROVED",
      previousLifecycleStatus: "ACTIVE",
      newLifecycleStatus: "ACTIVE",
      previousQaDisposition: "UNRESOLVED",
      newQaDisposition: "CONFIRMED_TRANSLATION_ERROR",
      actorType: "HUMAN",
      actorId: "human",
      note: "Confirmed with the translation team.",
      baseRevision: 1,
      createdAt: "2026-09-02T10:00:00Z",
    }],
  });
}

/** Long Tamil target text, for overflow and wrapping checks. */
export const LONG_TAMIL =
  "நற்செய்தி உங்களுக்கு அறிவிக்கப்பட்ட நாள் முதல் இதுவரைக்கும் நீங்கள் "
  + "எங்களோடு ஊழியத்தில் ஐக்கியப்பட்டிருப்பதால், நான் பண்ணுகிற ஒவ்வொரு "
  + "விண்ணப்பத்திலும் உங்கள் அனைவருக்காகவும் எப்பொழுதும் மகிழ்ச்சியோடு ஜெபம் செய்கிறேன்.";
