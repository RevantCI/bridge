/** Checked-in wire types generated/validated against bridge-passage-semantic-v1.schema.json. */
export const PASSAGE_SEMANTIC_SCHEMA_ID = "https://bridge.local/schemas/bridge-passage-semantic-v1.schema.json" as const;
export const PASSAGE_SEMANTIC_SCHEMA_VERSION = 1 as const;

export const REVIEW_STATUSES = ["UNREVIEWED", "AI_PROPOSED", "HUMAN_APPROVED", "HUMAN_REJECTED", "HUMAN_MODIFIED", "NEEDS_DISCUSSION"] as const;
export type ReviewStatus = (typeof REVIEW_STATUSES)[number];
export const LIFECYCLE_STATUSES = ["ACTIVE", "INACTIVE", "STALE", "SUPERSEDED", "QUARANTINED"] as const;
export type LifecycleStatus = (typeof LIFECYCLE_STATUSES)[number];
export const QA_DISPOSITIONS = ["UNRESOLVED", "CONFIRMED_TRANSLATION_ERROR", "ACCEPTABLE_TRANSLATION", "FALSE_POSITIVE", "NEEDS_DISCUSSION", "CORRECTED"] as const;
export type QaDisposition = (typeof QA_DISPOSITIONS)[number];
export type TokenSide = "SOURCE" | "TARGET";
export type TokenLayer = "ORTHOGRAPHIC" | "SUBTOKEN" | "MORPHEME";
export type TokenKind = "WORD" | "CLITIC" | "MORPHEME" | "PUNCTUATION" | "SYMBOL" | "UNKNOWN";
export type Cardinality = "ONE_TO_ONE" | "ONE_TO_MANY" | "MANY_TO_ONE" | "MANY_TO_MANY" | "SOURCE_TO_NULL" | "NULL_TO_TARGET";
export type SemanticUnitKind = "LEXICAL" | "MORPHOLOGICAL" | "NEGATION" | "QUANTIFIER" | "PARTICIPANT" | "REFERENT" | "PREDICATE" | "SEMANTIC_ROLE" | "CLAUSE" | "CLAUSE_RELATION" | "DISCOURSE_RELATION" | "IMPLICIT_GRAMMATICAL" | "IDIOM" | "CONSTRUCTION" | "TEMPORAL" | "SPATIAL";
export type DependencyRelation = "CONTAINS" | "DEPENDS_ON" | "DERIVED_FROM" | "REFINES";
export type SemanticRelation = "COREFERS_WITH" | "COEXTENSIVE_WITH" | "MODIFIES" | "NEGATES" | "QUANTIFIES" | "PARTICIPANT_OF" | "ARGUMENT_OF" | "SEMANTICALLY_RELATED";
export type SemanticUnitProvenance = "CANONICAL_RESOURCE" | "DETERMINISTIC_RULE" | "RESOURCE_ENRICHED" | "AI_PROPOSED" | "HUMAN_DEFINED" | "IMPORTED_TC" | "IMPORTED_STAGE3" | "MIGRATION";
export type AuditEligibility = "ELIGIBLE" | "CONDITIONAL" | "AGGREGATE_ONLY" | "EXCLUDED" | "REVIEW_ONLY";
export type SemanticObligationStrength = "REQUIRED" | "CONTEXT_DEPENDENT" | "GRAMMATICAL" | "DERIVED" | "NON_OBLIGATORY" | "UNCERTAIN";
export type CoverageAccountingRole = "PRIMARY" | "COMPONENT" | "AGGREGATE" | "EVIDENCE_ONLY";
export type CoverageDimension = "LEXICAL_CONTENT" | "POLARITY" | "QUANTITY" | "PARTICIPANT" | "REFERENT" | "PREDICATION" | "TEMPORAL_ASPECTUAL" | "SPATIAL_RELATION" | "CLAUSE_RELATION" | "DISCOURSE_RELATION" | "OTHER";
export type AuditDirection = "SOURCE_COVERAGE" | "TARGET_SUPPORT";
export type ActorType = "HUMAN" | "AI" | "SYSTEM" | "MIGRATION";
export type ResourceValidationStatus = "NOT_CHECKED" | "CONSISTENT" | "SUPPORTING" | "CONFLICTING" | "NOT_APPLICABLE";
export type EvidenceKind = "SOURCE_TEXT" | "TARGET_TEXT" | "MORPHOLOGY" | "TRANSLATION_NOTE" | "TRANSLATION_WORD" | "TRANSLATION_WORD_LIST" | "VERSIFICATION" | "STRUCTURE" | "HUMAN_NOTE" | "AI_RATIONALE";
export type QaFindingKind = "POSSIBLY_MISSING" | "MISSING" | "POSSIBLY_UNSUPPORTED" | "UNSUPPORTED" | "RESOURCE_CONFLICT" | "NEEDS_PASSAGE_REVIEW" | "NEEDS_EXTENDED_PASSAGE_REVIEW";
export type PassageStructureKind = "CHAPTER" | "VERSE" | "VERSE_BRIDGE" | "PARAGRAPH" | "POETRY" | "HEADING" | "NOTE" | "CROSS_REFERENCE" | "INLINE_MARKUP";
export type ExportFormat = "BRIDGE" | "CLEAN_USFM" | "TRANSLATIONCORE_ALIGNED_USFM" | "SCRIPTURE_BURRITO";
export type ExportabilityLevel = "FULL" | "PARTIAL" | "NOT_REPRESENTABLE" | "TEXT_ONLY";
export type ExportReason = "NONE" | "CROSS_VERSE" | "NULL_ALIGNMENT" | "SEMANTIC_ONLY" | "PARTIAL_LEXICAL_COVERAGE" | "FORMAT_LIMITATION" | "TEXT_ONLY_REQUEST";
export type Realization = "LEXICALLY_REALIZED" | "GRAMMATICALLY_REALIZED" | "PRONOMINALIZED" | "IMPLICIT" | "NOT_LOCATED" | "UNCERTAIN";
export type RelationshipProperty = "SPLIT" | "MERGED" | "CROSS_VERSE" | "REORDERED" | "DISCONTIGUOUS" | "EXPLICITATED" | "CLAUSE_RESTRUCTURED" | "IDIOMATIC_REALIZATION" | "VERSIFICATION_DIFFERENCE";
export type MeaningStatus = "PRESERVED" | "PRESERVED_WITH_RESTRUCTURING" | "PARTIAL" | "OVERTRANSLATED" | "UNDERTRANSLATED" | "MEANING_SHIFT" | "CONTRADICTED" | "UNVERIFIABLE";
export type SourceCoverage = "NOT_CHECKED" | "COVERED" | "COVERED_BY_RESTRUCTURING" | "POSSIBLY_MISSING" | "MISSING" | "UNCERTAIN";
export type TargetSupport = "NOT_CHECKED" | "SOURCE_SUPPORTED" | "CONTEXT_SUPPORTED" | "GRAMMATICALLY_REQUIRED" | "EXPLICITATION_SUPPORTED" | "POSSIBLY_UNSUPPORTED" | "UNSUPPORTED" | "UNCERTAIN";

export interface PolicyBinding {
  confidencePolicyVersion: string;
  calibrationVersion: string;
  auditPolicyVersion: string;
}

export interface ConfidenceScore {
  rawScore: number | null;
  calibratedValue: number;
  confidencePolicyVersion: string;
  calibrationVersion: string;
}

export interface CharacterSpan {
  startCodePoint: number;
  endCodePoint: number;
  startGrapheme: number;
  endGrapheme: number;
  quote: string;
  quoteSha256: string;
  coordinateVersion: "unicode-code-point-v1";
  unicodeVersion: string;
  graphemeSegmentationVersion: string;
}

export interface TokenLineage {
  id: string;
  side: TokenSide;
  projectId: string | null;
  logicalResourceId: string;
  book: string;
  canonicalReferenceScope: string[];
  tokenLayer: TokenLayer;
  upstreamIdentity: string | null;
  createdAt: string;
  provenance: SemanticUnitProvenance;
  reviewStatus: ReviewStatus;
  lifecycleStatus: LifecycleStatus;
  revision: number;
}

export interface TokenInstance {
  id: string;
  lineageId: string;
  side: TokenSide;
  projectId: string | null;
  resourceId: string;
  resourceVersion: string | null;
  resourceHash: string;
  textRevision: string | null;
  book: string;
  displayedReference: string;
  canonicalReferences: string[];
  index: number;
  occurrence: number;
  occurrences: number;
  span: CharacterSpan | null;
  rawForm: string;
  normalizedForm: string;
  normalizationProfile: string;
  tokenizationVersion: string;
  tokenLayer: TokenLayer;
  tokenKind: TokenKind;
  parentInstanceId: string | null;
  instanceFingerprint: string;
  lemma: string | null;
  strong: string | null;
  morphology: string | null;
  morphologicalFeatures: Record<string, string>;
}

export interface SemanticUnit {
  id: string;
  side: TokenSide;
  projectId: string;
  book: string;
  kind: SemanticUnitKind;
  displayedReferences: string[];
  canonicalReferences: string[];
  tokenInstanceIds: string[];
  tokenLineageIds: string[];
  rawSurface: string;
  normalizedSurface: string;
  semanticFeatures: Record<string, string>;
  unitConfidence: ConfidenceScore;
  provenance: SemanticUnitProvenance;
  evidenceIds: string[];
  resourceValidationIds: string[];
  auditEligibility: AuditEligibility;
  semanticObligation: SemanticObligationStrength;
  accountingRole: CoverageAccountingRole;
  auditOwnerUnitId: string;
  coverageDimension: CoverageDimension;
  semanticFingerprint: string;
  policyBinding: PolicyBinding;
  reviewStatus: ReviewStatus;
  lifecycleStatus: LifecycleStatus;
  revision: number;
}

export type SourceSemanticUnit = SemanticUnit & { side: "SOURCE" };
export type TargetSemanticUnit = SemanticUnit & { side: "TARGET" };

export interface PassageStructureMarker {
  kind: PassageStructureKind;
  marker: string;
  displayedReference: string | null;
  startCodePoint: number | null;
  endCodePoint: number | null;
  sourceOrder: number;
}

export interface PassageRecord {
  id: string;
  projectId: string;
  book: string;
  displayedSourceReferences: string[];
  displayedTargetReferences: string[];
  canonicalReferences: string[];
  sourceResourceId: string;
  sourceResourceVersion: string | null;
  sourceResourceHash: string;
  targetRevision: string;
  targetContentHash: string;
  structureResourceId: string;
  structureResourceVersion: string | null;
  structureResourceHash: string;
  targetTextByDisplayedReference: Record<string, string>;
  structureMarkers: PassageStructureMarker[];
  policyBinding: PolicyBinding;
  lifecycleStatus: LifecycleStatus;
  revision: number;
}

export interface EvidenceRecord {
  id: string;
  projectId: string;
  book: string;
  kind: EvidenceKind;
  resourceId: string;
  resourceVersion: string | null;
  resourceHash: string;
  occurrenceId: string | null;
  displayedReferences: string[];
  canonicalReferences: string[];
  content: string;
  contentHash: string;
  validationStatus: ResourceValidationStatus;
  sourceSemanticUnitIds: string[];
  targetSemanticUnitIds: string[];
  policyBinding: PolicyBinding;
  reviewStatus: ReviewStatus;
  lifecycleStatus: LifecycleStatus;
  revision: number;
}

export interface SemanticRelationship {
  id: string;
  projectId: string;
  book: string;
  sourceSemanticUnitIds: string[];
  targetSemanticUnitIds: string[];
  lexicalGroupIds: string[];
  realization: Realization;
  properties: RelationshipProperty[];
  locationConfidence: ConfidenceScore;
  meaningStatus: MeaningStatus;
  meaningConfidence: ConfidenceScore;
  sourceCoverage: SourceCoverage;
  targetSupport: TargetSupport;
  evidenceIds: string[];
  policyBinding: PolicyBinding;
  reviewStatus: ReviewStatus;
  lifecycleStatus: LifecycleStatus;
  revision: number;
}

export interface SemanticUnitDependency {
  parentUnitId: string;
  childUnitId: string;
  relation: DependencyRelation;
  confidence: ConfidenceScore;
  provenance: SemanticUnitProvenance;
  evidenceIds: string[];
}

export interface SemanticUnitRelationEdge {
  leftUnitId: string;
  rightUnitId: string;
  relation: SemanticRelation;
  confidence: ConfidenceScore;
  provenance: SemanticUnitProvenance;
  evidenceIds: string[];
}

export interface SemanticCoverageAccount {
  id: string;
  projectId: string;
  passageId: string;
  direction: AuditDirection;
  auditOwnerUnitId: string;
  memberUnitIds: string[];
  coverageDimension: CoverageDimension;
  semanticFingerprint: string;
  coveredByRelationshipIds: string[];
  excludedDuplicateUnitIds: string[];
  findingId: string | null;
  policyBinding: PolicyBinding;
  reviewStatus: ReviewStatus;
  lifecycleStatus: LifecycleStatus;
  revision: number;
}

export interface LexicalSolution {
  id: string;
  projectId: string;
  scopeKey: string;
  profileId: string;
  sourceLayer: TokenLayer | null;
  targetLayer: TokenLayer | null;
  authoritative: boolean;
  policyBinding: PolicyBinding;
  reviewStatus: ReviewStatus;
  lifecycleStatus: LifecycleStatus;
  revision: number;
}

export interface LexicalAlignmentGroup {
  id: string;
  solutionId: string;
  cardinality: Cardinality;
  sourceLayer: TokenLayer | null;
  targetLayer: TokenLayer | null;
  sourceTokenInstanceIds: string[];
  targetTokenInstanceIds: string[];
  alignmentFamilyId: string;
  refinesGroupId: string | null;
  policyBinding: PolicyBinding;
  reviewStatus: ReviewStatus;
  lifecycleStatus: LifecycleStatus;
  revision: number;
}

export interface QaFinding {
  id: string;
  projectId: string;
  book: string;
  passageId: string;
  kind: QaFindingKind;
  direction: AuditDirection;
  sourceSemanticUnitIds: string[];
  targetSemanticUnitIds: string[];
  semanticRelationshipIds: string[];
  evidenceIds: string[];
  explanation: string;
  confidence: ConfidenceScore;
  currentTargetRevision: string;
  qaDisposition: QaDisposition;
  policyBinding: PolicyBinding;
  reviewStatus: ReviewStatus;
  lifecycleStatus: LifecycleStatus;
  revision: number;
}

export interface CorrectionProposal {
  id: string;
  projectId: string;
  qaFindingId: string;
  targetDisplayedReferences: string[];
  currentTargetRevision: string;
  currentText: string;
  proposedText: string;
  evidenceIds: string[];
  sourceSemanticUnitIds: string[];
  policyBinding: PolicyBinding;
  reviewStatus: ReviewStatus;
  lifecycleStatus: LifecycleStatus;
  appliedTargetRevision: string | null;
  appliedBy: string | null;
  appliedAt: string | null;
  revision: number;
}

export interface ReviewRecord {
  id: string;
  entityType: string;
  entityId: string;
  previousReviewStatus: ReviewStatus | null;
  newReviewStatus: ReviewStatus;
  previousLifecycleStatus: LifecycleStatus | null;
  newLifecycleStatus: LifecycleStatus;
  previousQaDisposition: QaDisposition | null;
  newQaDisposition: QaDisposition | null;
  actorType: ActorType;
  actorId: string;
  note: string;
  baseRevision: number;
  createdAt: string;
}

export interface Exportability {
  id: string;
  relationshipId: string;
  format: ExportFormat;
  level: ExportabilityLevel;
  reasons: ExportReason[];
  policyBinding: PolicyBinding;
  lifecycleStatus: LifecycleStatus;
  revision: number;
}

/** Convert canonical code-point offsets to the UTF-16 offsets used by DOM APIs. */
export function codePointToUtf16Offset(text: string, offset: number): number {
  const codePoints = Array.from(text);
  if (!Number.isInteger(offset) || offset < 0 || offset > codePoints.length) {
    throw new RangeError(`Invalid code-point offset ${offset}`);
  }
  return codePoints.slice(0, offset).join("").length;
}

export function codePointSpan(text: string, start: number, end: number): string {
  const codePoints = Array.from(text);
  if (!Number.isInteger(start) || !Number.isInteger(end) || start < 0 || end < start || end > codePoints.length) {
    throw new RangeError(`Invalid code-point range [${start}, ${end})`);
  }
  return codePoints.slice(start, end).join("");
}

export function utf16ToCodePointOffset(text: string, utf16Offset: number): number {
  if (!Number.isInteger(utf16Offset) || utf16Offset < 0 || utf16Offset > text.length) {
    throw new RangeError(`Invalid UTF-16 offset ${utf16Offset}`);
  }
  const prefix = text.slice(0, utf16Offset);
  if (prefix.length > 0) {
    const last = prefix.charCodeAt(prefix.length - 1);
    if (last >= 0xd800 && last <= 0xdbff) throw new RangeError("UTF-16 offset splits a surrogate pair");
  }
  return Array.from(prefix).length;
}
