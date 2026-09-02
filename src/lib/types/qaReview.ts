/**
 * Stage 9A human-review wire types.
 *
 * These mirror what `qaReview.*` / `semanticReview.*` / `reviewHistory.*`
 * return from the sidecar. The machine's analysis and the human's decision are
 * kept as separate fields throughout: a finding carries what the engine found
 * (`kind`, `severity`, `explanation`) alongside what a person concluded
 * (`qaDisposition`, `reviewStatus`), and the UI must never render the former
 * as though it were the latter.
 */

export type QaDisposition =
  | "UNRESOLVED"
  | "CONFIRMED_TRANSLATION_ERROR"
  | "ACCEPTABLE_TRANSLATION"
  | "FALSE_POSITIVE"
  | "NEEDS_DISCUSSION"
  | "CORRECTED";

/** The four conclusions a reviewer may reach. CORRECTED is Stage 9B's. */
export type ReviewerDecision = Exclude<QaDisposition, "UNRESOLVED" | "CORRECTED">;

export type ReviewStatus =
  | "UNREVIEWED"
  | "AI_PROPOSED"
  | "HUMAN_APPROVED"
  | "HUMAN_REJECTED"
  | "HUMAN_MODIFIED"
  | "NEEDS_DISCUSSION";

export type LifecycleStatus =
  | "ACTIVE"
  | "INACTIVE"
  | "STALE"
  | "SUPERSEDED"
  | "QUARANTINED";

export type QaFindingSeverity = "CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | "INFO";

export type LocationOutcome =
  | "LOCATED"
  | "AMBIGUOUS"
  | "NOT_LOCATED"
  | "SEARCH_INCOMPLETE"
  | "UNSUPPORTED_ANALYSIS";

export type MeaningStatus =
  | "PRESERVED"
  | "PRESERVED_WITH_RESTRUCTURING"
  | "PARTIAL"
  | "OVERTRANSLATED"
  | "UNDERTRANSLATED"
  | "MEANING_SHIFT"
  | "CONTRADICTED"
  | "UNVERIFIABLE";

export type ReviewQueueOrder = "CANONICAL" | "SEVERITY";

/** Entities a reviewer can decide on or annotate. */
export type ReviewEntityType =
  | "QA_FINDING"
  | "LOCATION_RELATIONSHIP"
  | "MEANING_ASSESSMENT"
  | "COVERAGE_ACCOUNT"
  | "SEMANTIC_RELATIONSHIP";

export interface ConfidenceScore {
  rawScore: number | null;
  calibratedValue: number;
  confidencePolicyVersion: string;
  calibrationVersion: string;
}

/** One row in the review queue: enough to triage, not the whole evidence graph. */
export interface QaFindingSummary {
  id: string;
  kind: string;
  direction: string;
  severity: QaFindingSeverity;
  book: string;
  displayedReferences: string[];
  explanation: string;
  qaDisposition: QaDisposition;
  reviewStatus: ReviewStatus;
  lifecycleStatus: LifecycleStatus;
  locationOutcomeSnapshot: string;
  meaningStatusSnapshot: string;
  confidence: ConfidenceScore;
  revision: number;
  /** True while the finding is only a possibility, never a confirmed error. */
  isPossible: boolean;
}

export interface ReviewQueuePage {
  findings: QaFindingSummary[];
  nextCursor: string;
  totalCount: number;
  order: ReviewQueueOrder;
}

export interface ReviewQueueFilters {
  book?: string;
  chapter?: number;
  kinds?: string[];
  severities?: QaFindingSeverity[];
  dispositions?: QaDisposition[];
  reviewStatuses?: ReviewStatus[];
  lifecycleStatuses?: LifecycleStatus[];
  order?: ReviewQueueOrder;
  limit?: number;
  cursor?: string;
}

export interface ReviewRecord {
  id: string;
  entityType: string;
  entityId: string;
  previousReviewStatus: string | null;
  newReviewStatus: ReviewStatus;
  previousLifecycleStatus: string | null;
  newLifecycleStatus: LifecycleStatus;
  previousQaDisposition: string | null;
  newQaDisposition: string | null;
  actorType: "HUMAN" | "AI" | "SYSTEM" | "MIGRATION";
  actorId: string;
  note: string;
  baseRevision: number;
  createdAt: string;
}

/**
 * Where a piece of evidence came from. Stage 7's per-component evidence lives
 * inline in the assessment rather than in the evidence-record store, and an id
 * that resolves to neither is shown as UNRESOLVED rather than hidden.
 */
export type EvidenceSource = "EVIDENCE_RECORD" | "MEANING_ASSESSMENT" | "UNRESOLVED";

export interface ResolvedEvidence extends Record<string, unknown> {
  id: string;
  evidenceSource: EvidenceSource;
}

export interface LocationSection {
  location: Record<string, unknown> & {
    id: string;
    locationOutcome: LocationOutcome;
    reviewStatus: ReviewStatus;
    revision: number;
    selectedCandidateId?: string | null;
  };
  /** Candidates the engine competed against; never imply there was only one. */
  alternatives: Array<Record<string, unknown>>;
}

export interface MeaningSection {
  assessment: Record<string, unknown> & {
    id: string;
    meaningStatus: MeaningStatus;
    reviewStatus: ReviewStatus;
    revision: number;
  };
  /** Per-dimension judgements, deliberately not collapsed into one score. */
  components: Array<Record<string, unknown>>;
}

/** A finding with its evidence in independently inspectable layers. */
export interface QaFindingDetail {
  finding: Record<string, unknown> & {
    id: string;
    kind: string;
    severity: QaFindingSeverity;
    explanation: string;
    qaDisposition: QaDisposition;
    reviewStatus: ReviewStatus;
    lifecycleStatus: LifecycleStatus;
    revision: number;
    displayedReferences: string[];
    targetContentHashes: string[];
  };
  source: Array<Record<string, unknown>>;
  target: Array<Record<string, unknown>>;
  location: LocationSection[];
  meaning: MeaningSection[];
  coverage: Array<Record<string, unknown>>;
  resources: ResolvedEvidence[];
  supportingEvidence: ResolvedEvidence[];
  conflictingEvidence: ResolvedEvidence[];
  history: ReviewRecord[];
  isStale: boolean;
  reviewEngineVersion: string;
}

export interface DecideFindingResult {
  finding: QaFindingDetail["finding"];
  /** Non-empty only when the reviewer explicitly asked to promote. */
  promotedCoverageAccountIds: string[];
  history: ReviewRecord[];
}

export interface DecideLocationResult {
  location: Record<string, unknown>;
  history: ReviewRecord[];
}

export interface DecideMeaningResult {
  meaning: Record<string, unknown>;
  history: ReviewRecord[];
}

export interface EntityHistory {
  entityType: string;
  entityId: string;
  records: ReviewRecord[];
}
