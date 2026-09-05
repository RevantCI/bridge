import type { LifecycleStatus, ReviewStatus } from "./qaReview";
import type { CoverageDimension, PolicyBinding } from "./passageSemanticV1";

export type CorrectionEligibilityCode =
  | "ELIGIBLE"
  | "FINDING_NOT_FOUND"
  | "DISPOSITION_NOT_CONFIRMED"
  | "REVIEW_STATUS_NOT_HUMAN_APPROVED"
  | "LIFECYCLE_NOT_ACTIVE"
  | "FINDING_STALE"
  | "TARGET_TEXT_CHANGED"
  | "TARGET_REFERENCE_MISSING"
  | "SPAN_TEXT_MISMATCH"
  | "LOCATION_EVIDENCE_UNUSABLE"
  | "MAPPING_HUMAN_REJECTED"
  | "MEANING_OVERRIDDEN_PRESERVED"
  | "CONFLICTING_CORRECTION"
  | "RESOURCE_CONFLICT_REQUIRES_REVIEW";

export interface CorrectionEligibilityReason {
  code: CorrectionEligibilityCode;
  detail: string;
  entityType: string;
  entityId: string;
}

export interface CorrectionEligibility {
  findingId: string;
  eligible: boolean;
  reasons: CorrectionEligibilityReason[];
  findingRevision: number;
  currentTargetContentHash: string;
  displayedReferences: string[];
  engineVersion: string;
  existingProposalIds: string[];
}

export interface AffectedTargetSpan {
  displayedReference: string;
  canonicalReferences: string[];
  startCodePoint: number;
  endCodePoint: number;
  originalText: string;
  targetTextRevision: string;
  targetContentHash: string;
}

export interface CorrectionIntent {
  failedDimension: CoverageDimension;
  observedMeaning: string;
  requiredMeaning: string;
  affectedSourceSemanticUnitIds: string[];
  affectedTargetSpan: AffectedTargetSpan;
}

export type CorrectionCreationMode =
  | "MACHINE_SUGGESTED"
  | "MACHINE_SUGGESTED_HUMAN_EDITED"
  | "AI_GENERATED"
  | "HUMAN_AUTHORED"
  | "HUMAN_MODIFIED_AI"
  | "MIGRATED_LEGACY";

export type VerificationStatus = "NOT_RUN" | "PENDING" | "PASSED" | "FAILED" | "UNCERTAIN";

export interface CorrectionProviderMetadata {
  providerName: string;
  model: string;
  modelVersionId?: string;
  promptPolicyVersion?: string;
  responseFingerprint?: string;
}

export interface CorrectionWordingAlternative {
  proposedText: string;
  explanation: string;
  evidenceIds: string[];
  creationMode: CorrectionCreationMode;
  providerMetadata: CorrectionProviderMetadata | null;
}

export interface CorrectionProposal {
  id: string;
  proposalSchemaVersion: number;
  qaFindingId: string;
  projectId: string;
  intent: CorrectionIntent;
  affectedReferences: string[];
  currentText: string;
  proposedText: string;
  explanation: string;
  evidenceIds: string[];
  semanticRelationshipIds: string[];
  meaningAssessmentIds: string[];
  locationRelationshipIds: string[];
  createdBy: string;
  createdAt: string;
  creationMode: CorrectionCreationMode;
  policyBinding: PolicyBinding;
  reviewStatus: ReviewStatus;
  lifecycleStatus: LifecycleStatus;
  verificationStatus: VerificationStatus;
  verificationJobIds: string[];
  appliedTargetRevision: string | null;
  appliedBy: string | null;
  appliedAt: string | null;
  revision: number;
  alternatives: CorrectionWordingAlternative[];
  providerMetadata: CorrectionProviderMetadata | null;
  warnings: string[];
  originalSuggestedText: string | null;
  supersedesProposalId: string | null;
}

export type CorrectionEventType = "CREATED" | "SUGGESTED" | "EDITED" | "REJECTED" | "SUPERSEDED" | "STALE";

export interface CorrectionProposalEvent {
  id: string;
  proposalId: string;
  eventType: CorrectionEventType;
  actorType: "HUMAN" | "AI" | "SYSTEM" | "MIGRATION";
  actorId: string;
  createdAt: string;
  baseRevision: number;
  newRevision: number;
  note: string;
  reason: string;
  providerMetadata: CorrectionProviderMetadata | null;
  proposalSnapshot: CorrectionProposal;
}

export interface CorrectionCurrentTarget {
  displayedReference: string;
  canonicalReferences: string[];
  text: string;
  targetTextRevision: string;
  targetContentHash: string;
}

export interface CorrectionReviewContext {
  findingId: string;
  currentTargets: CorrectionCurrentTarget[];
  candidateSpans: AffectedTargetSpan[];
  suggestedIntent: Omit<CorrectionIntent, "affectedTargetSpan">;
  sourceEvidence: Array<Record<string, unknown>>;
  resources: Array<Record<string, unknown>>;
  location: Array<Record<string, unknown>>;
}
