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
export type SemanticUnitProvenance = "CANONICAL_RESOURCE" | "DETERMINISTIC_RULE" | "LANGUAGE_ANALYZER" | "RESOURCE_ENRICHED" | "AI_PROPOSED" | "HUMAN_DEFINED" | "IMPORTED_TC" | "IMPORTED_STAGE3" | "MIGRATION";
export type AuditEligibility = "ELIGIBLE" | "CONDITIONAL" | "AGGREGATE_ONLY" | "EXCLUDED" | "REVIEW_ONLY";
export type SemanticObligationStrength = "REQUIRED" | "CONTEXT_DEPENDENT" | "GRAMMATICAL" | "DERIVED" | "NON_OBLIGATORY" | "UNCERTAIN";
export type CoverageAccountingRole = "PRIMARY" | "COMPONENT" | "AGGREGATE" | "EVIDENCE_ONLY";
export type CoverageDimension = "LEXICAL_CONTENT" | "POLARITY" | "QUANTITY" | "PARTICIPANT" | "REFERENT" | "PREDICATION" | "TEMPORAL_ASPECTUAL" | "SPATIAL_RELATION" | "CLAUSE_RELATION" | "DISCOURSE_RELATION" | "OTHER";
export type AuditDirection = "SOURCE_COVERAGE" | "TARGET_SUPPORT";
export type ActorType = "HUMAN" | "AI" | "SYSTEM" | "MIGRATION";
export type ResourceValidationStatus = "NOT_CHECKED" | "CONSISTENT" | "SUPPORTING" | "CONFLICTING" | "NOT_APPLICABLE";
export type EvidenceKind = "SOURCE_TEXT" | "TARGET_TEXT" | "MORPHOLOGY" | "TRANSLATION_NOTE" | "TRANSLATION_WORD" | "TRANSLATION_WORD_LIST" | "VERSIFICATION" | "STRUCTURE" | "HUMAN_NOTE" | "AI_RATIONALE" | "SOURCE_VARIANT";
export type QaFindingKind = "POSSIBLY_MISSING" | "MISSING" | "POSSIBLY_UNSUPPORTED" | "UNSUPPORTED" | "RESOURCE_CONFLICT" | "NEEDS_PASSAGE_REVIEW" | "NEEDS_EXTENDED_PASSAGE_REVIEW" | "POSSIBLE_OMISSION" | "POSSIBLE_ADDITION" | "POSSIBLE_UNDERTRANSLATION" | "POSSIBLE_OVERTRANSLATION" | "MEANING_SHIFT" | "CONTRADICTION" | "NEGATION_PROBLEM" | "QUANTITY_PROBLEM" | "TEMPORAL_PROBLEM" | "PARTICIPANT_PROBLEM" | "REFERENT_PROBLEM" | "SOURCE_VARIANT_REVIEW";
export type QaFindingSeverity = "CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | "INFO";
export type QaRunStatus = "RUNNING" | "COMPLETE" | "FAILED";
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

// Stage 4 runtime envelopes. Canonical entity payloads above remain schema v1;
// these types describe the minimal project-lifecycle API around them.
export type PassageSemanticRuntimeState =
  | "NO_PROJECT"
  | "READY"
  | "UNAVAILABLE"
  | "RECOVERY_REQUIRED";

export type PassageReferenceMappingKind =
  | "SAME"
  | "MAPPED"
  | "MERGE"
  | "SPLIT"
  | "PSALM_TITLE"
  | "VERSE_BRIDGE"
  | "CHAPTER_SHIFT"
  | "AMBIGUOUS_SEGMENT";

export interface PassageReferenceMapping {
  displayedReference: string;
  projectVersification: string;
  canonicalReferences: string[];
  mappingKind: PassageReferenceMappingKind;
  ordinal: number;
}

export interface PassageSemanticRecoveryStatus {
  ok: boolean;
  readOnly: boolean;
  problems: string[];
  schemaVersion: number;
}

export interface PassageSemanticRuntimeStatus {
  state: PassageSemanticRuntimeState;
  available: boolean;
  readOnly: boolean;
  databaseSchemaVersion?: number;
  databasePath?: string;
  projectId?: string;
  book?: string;
  replayedInvalidations?: number;
  recovery?: PassageSemanticRecoveryStatus;
  error?: string;
}

export interface PassageSemanticProjectMetadata {
  projectId: string;
  identityFingerprint: string;
  book: string;
  targetLanguageId: string;
  resourceId: string;
  pathHistory: string[];
  createdAt: string;
  updatedAt: string;
  lifecycleStatus: LifecycleStatus;
  revision: number;
  sourceLock: {
    projectId: string;
    book: string;
    resourceId: string;
    resourceVersion: string;
    resourceHash: string;
    lifecycleStatus: LifecycleStatus;
    revision: number;
    updatedAt: string;
  } | null;
}

export interface CurrentPassageSnapshot extends PassageRecord {
  referenceMappings: PassageReferenceMapping[];
  targetTokenInstanceIds: string[];
  structureStatus: "CURRENT" | "STRUCTURE_TEXT_MISMATCH";
  structureDiagnostics: Array<{
    code: "STRUCTURE_TEXT_MISMATCH";
    reference?: string;
    detail: string;
  }>;
  tokenizerProfile: "bridge-unicode-word-v1" | "tc-whitespace-v1";
}

export interface PassageSemanticStaleSummary {
  counts: {
    passages: number;
    tokens: number;
    semanticUnits: number;
    semanticRelationships: number;
    coverageAccounts: number;
    qaFindings: number;
    lexicalSolutions: number;
    correctionProposals: number;
    evidence: number;
    exportability: number;
  };
  pendingInvalidations: number;
  quarantined: number;
}

export interface PassageSemanticMigrationRun {
  id: string;
  sourcePath: string;
  sourceHash: string;
  sourceSchema: string;
  status: "IMPORTED" | "QUARANTINED" | "SKIPPED" | "FAILED";
  startedAt: string;
  completedAt: string;
  report: Record<string, unknown>;
}

export interface PassageSemanticMigrationReport {
  runs: PassageSemanticMigrationRun[];
  quarantineByReason: Record<string, number>;
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
  /** A SourceCoverage value when direction=SOURCE_COVERAGE, or a TargetSupport value when direction=TARGET_SUPPORT. */
  coverageStatus: string;
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
  severity: QaFindingSeverity;
  meaningAssessmentIds: string[];
  coverageAccountIds: string[];
  locationOutcomeSnapshot: string;
  meaningStatusSnapshot: string;
  supportingEvidenceIds: string[];
  conflictingEvidenceIds: string[];
  resourceEvidenceIds: string[];
  targetContentHashes: string[];
  sourceResourceHashes: string[];
  qaEngineVersion: string;
  qaPolicyVersion: string;
  fingerprint: string;
  /** Denormalized so the review queue can order by canonical position. */
  displayedReferences: string[];
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

export interface SourceInventoryToken extends TokenInstance {
  languageId: "hbo" | "arc" | "el-x-koine";
  upstreamIdentity: string;
  translationWordConceptIds?: string[];
}

export interface SourceInventoryCoverageAccount {
  id: string;
  auditOwnerUnitId: string;
  memberUnitIds: string[];
  coverageDimension: CoverageDimension;
  semanticFingerprint: string;
  excludedDuplicateUnitIds: string[];
}

export interface SourceInventoryDiagnostics {
  sourceTokenInstances: number;
  sourceTokensRepresented: number;
  requiredSemanticObligations: number;
  conditionalObligations: number;
  grammaticalObligations: number;
  derivedAggregateUnits: number;
  excludedUnits: number;
  reviewOnlyUnits: number;
  resourceEnrichedUnits: number;
  resourceConflicts: number;
}

export interface SourceSemanticInventory {
  id: string;
  book: string;
  rangeKey: string;
  canonicalReferences: string[];
  fingerprint: string;
  sourceSemanticFingerprint: string;
  sourceResource: {
    languageId: "hbo" | "el-x-koine";
    resourceId: "uhb" | "ugnt";
    version: string;
    owner: string;
    commit: string;
    release: string;
    license: "CC BY-SA 4.0";
    provenanceSha256: string;
    licenseSha256: string;
  };
  inventoryEngineVersion: string;
  sourceTokenizationVersion: string;
  policyBinding: PolicyBinding;
  tokens: SourceInventoryToken[];
  units: SemanticUnit[];
  coverageAccounts: SourceInventoryCoverageAccount[];
  evidence: EvidenceRecord[];
  diagnostics: SourceInventoryDiagnostics;
  cacheStatus: "MISS" | "HIT";
}

export type CapabilityAvailability = "AVAILABLE" | "UNAVAILABLE" | "FALLBACK" | "STRUCTURAL_FALLBACK";
export type TargetSpanKind = "TOKEN" | "SUBTOKEN" | "PHRASE" | "STRUCTURAL_SEGMENT" | "CLAUSE" | "SENTENCE";
export type TargetNeighborhoodScope = "NORMALIZED_VERSE" | "STRUCTURAL_SENTENCE" | "PARAGRAPH" | "ADJACENT_STRUCTURAL_SEGMENT" | "SELECTED_PASSAGE" | "CHAPTER_BOUNDARY_CONTINUATION";

export interface TargetLanguageCapabilities {
  languageTag: string;
  script: string;
  direction: "LTR" | "RTL";
  tokenization: "AVAILABLE" | "FALLBACK";
  morphology: "AVAILABLE" | "UNAVAILABLE";
  pos: "AVAILABLE" | "UNAVAILABLE";
  dependencySyntax: "AVAILABLE" | "UNAVAILABLE";
  sentenceBoundary: "AVAILABLE" | "STRUCTURAL_FALLBACK";
  coreference: "AVAILABLE" | "UNAVAILABLE";
  semanticRoles: "AVAILABLE" | "UNAVAILABLE";
  tokenizerProfile: string;
  normalizationProfile: string;
  providers: Array<{ id: string; version: string }>;
}

export interface TargetSearchSpan {
  id: string;
  kind: TargetSpanKind;
  displayedReference: string;
  tokenInstanceIds: string[];
  startCodePoint: number;
  endCodePoint: number;
  quote: string;
  quoteSha256: string;
  targetRevision: string;
  spanPolicyVersion: string;
  analysis?: string;
  providerId?: string;
  providerVersion?: string;
}

export interface TargetSearchNeighborhood {
  id: string;
  scopeKind: TargetNeighborhoodScope;
  displayedReferences: string[];
}

export interface TargetInventoryDiagnostics {
  targetCharacters: number;
  graphemeClusters: number;
  orthographicTokens: number;
  subtokensMorphemes: number;
  targetSemanticUnits: number;
  lexicalUnits: number;
  grammaticalUnits: number;
  negationUnits: number;
  quantifierUnits: number;
  participantUnits: number;
  predicateUnits: number;
  clauses: number;
  analyzerDerivedUnits: number;
  reviewOnlyUnits: number;
  unknownUnsegmentedSpans: number;
  searchSpans: number;
  searchNeighborhoods: number;
}

export interface TargetSemanticInventory {
  id: string;
  book: string;
  rangeKey: string;
  canonicalReferences: string[];
  fingerprint: string;
  targetSemanticFingerprint: string;
  targetRevision: string;
  targetContentHash: string;
  targetInventoryEngineVersion: string;
  spanPolicyVersion: string;
  capabilities: TargetLanguageCapabilities;
  tokens: TokenInstance[];
  units: SemanticUnit[];
  searchSpans: TargetSearchSpan[];
  searchNeighborhoods: TargetSearchNeighborhood[];
  structureMarkers: PassageStructureMarker[];
  diagnostics: TargetInventoryDiagnostics;
  cacheStatus: "MISS" | "HIT";
}

export type LocationOutcome = "LOCATED" | "AMBIGUOUS" | "NOT_LOCATED" | "SEARCH_INCOMPLETE" | "UNSUPPORTED_ANALYSIS";
export type LocationRunStatus = "RUNNING" | "COMPLETE" | "FAILED";
export type LocationCalibrationStatus = "CALIBRATED" | "UNCALIBRATED_INTERNAL";
export type LocationEvidenceKind = "SEMANTIC_SIMILARITY" | "LEXICAL" | "CONCEPT" | "MORPHOLOGY" | "STRUCTURAL_PROXIMITY" | "PASSAGE_COHERENCE" | "PARTICIPANT" | "HUMAN_PRECEDENT" | "RESOURCE" | "EXACT_SPAN" | "CANDIDATE_COMPETITION";

export interface SemanticEmbeddingDescriptor {
  providerId: string;
  providerVersion: string;
  modelId: string;
  modelHash: string;
  dimensions: number;
  normalization: string;
  languageCapabilities: string[];
  offline: boolean;
  available: boolean;
  role: "CANDIDATE_RETRIEVAL_ONLY";
}

export interface LocationEvidenceComponent {
  kind: LocationEvidenceKind;
  rawScore: number;
  weight: number;
  weightedScore: number;
  provenance: string;
}

export interface SemanticLocationCandidate {
  id: string;
  sourceOwnerUnitId: string;
  sourceSemanticUnitIds: string[];
  targetSemanticUnitIds: string[];
  targetSpanIds: string[];
  targetTokenInstanceIds: string[];
  targetDisplayedReferences: string[];
  targetCanonicalReferences: string[];
  quotes: Array<{ spanId: string; quote: string; quoteSha256: string }>;
  realization: Realization;
  properties: RelationshipProperty[];
  rawScore: number;
  evidenceComponents: LocationEvidenceComponent[];
  rank: number;
}

export interface SemanticLocationRelationship {
  id: string;
  sourceOwnerUnitId: string;
  sourceSemanticUnitIds: string[];
  targetSemanticUnitIds: string[];
  targetSpanIds: string[];
  targetTokenInstanceIds: string[];
  locationOutcome: LocationOutcome;
  realization: Realization;
  properties: RelationshipProperty[];
  locationConfidence: LocationConfidence;
  selectedCandidateId: string | null;
  alternativeCandidateIds: string[];
  reviewStatus: ReviewStatus;
  lifecycleStatus: LifecycleStatus;
  revision: number;
}

export interface LocationConfidence {
  rawScore: number | null;
  calibratedValue: number;
  confidencePolicyVersion: string;
  calibrationVersion: string;
  calibrationStatus: LocationCalibrationStatus;
}

export interface SemanticLocationDiagnostics {
  sourcePrimaryObligations: number;
  locationsFound: number;
  ambiguous: number;
  notLocated: number;
  searchIncomplete: number;
  unsupportedAnalysis: number;
  sameVerse: number;
  crossVerse: number;
  split: number;
  merged: number;
  reordered: boolean;
  grammatical: number;
  pronominalized: number;
  implicit: number;
  averageCandidateCount: number;
  candidateEvaluations: number;
  candidateBudget: number;
  progressiveSearchScopeEvaluations: Record<string, number>;
  contextualSupportEdges: number;
  retrievalSeconds: number;
  rankingSeconds: number;
  embeddingSeconds: number;
  embeddingCacheHits: number;
  embeddingCacheMisses: number;
  embeddingFailure: string | null;
  embeddingCacheHitRate: number;
}

export interface SemanticLocationRun {
  id: string;
  book: string;
  rangeKey: string;
  fingerprint: string;
  sourceInventoryId: string;
  sourceInventoryFingerprint: string;
  targetInventoryId: string;
  targetInventoryFingerprint: string;
  passageFingerprint: string;
  locationEngineVersion: string;
  embeddingProvider: SemanticEmbeddingDescriptor;
  confidencePolicyVersion: string;
  calibrationVersion: string;
  searchPolicyVersion: string;
  runStatus: LocationRunStatus;
  relationships: SemanticLocationRelationship[];
  candidates: SemanticLocationCandidate[];
  diagnostics: SemanticLocationDiagnostics;
  elapsedSeconds: number;
  cacheStatus: "MISS" | "HIT";
}

export type MeaningComponentStatus = "PRESERVED" | "PARTIALLY_PRESERVED" | "ALTERED" | "CONTRADICTED" | "TARGET_ADDS_SPECIFICITY" | "TARGET_WEAKENS_SPECIFICITY" | "NOT_EXPLICIT_BUT_RECOVERABLE" | "NOT_DETERMINABLE" | "NOT_APPLICABLE";
export type MeaningRunStatus = "RUNNING" | "COMPLETE" | "FAILED";
export type MeaningAssessmentReason = "ASSESSED" | "NO_LOCATED_REALIZATION" | "AMBIGUOUS_LOCATION" | "SEARCH_INCOMPLETE" | "UNSUPPORTED_ANALYSIS" | "LOCATION_REVIEW_REQUIRED";
export type MeaningEvidenceKind = "LEXICAL_CONCEPT" | "POLARITY" | "QUANTITY" | "PARTICIPANT" | "SEMANTIC_ROLE" | "TEMPORAL" | "COMPLETION" | "MODALITY" | "GRAMMATICAL" | "CONTEXTUAL" | "RESOURCE" | "DETERMINISTIC_CONTRADICTION";

export interface MeaningComponentAssessment {
  id: string;
  coverageDimension: CoverageDimension;
  sourceSemanticUnitIds: string[];
  targetSemanticUnitIds: string[];
  targetSpanIds: string[];
  status: MeaningComponentStatus;
  confidence: LocationConfidence;
  evidence: { id: string; kind: MeaningEvidenceKind; resourceStatus: ResourceValidationStatus; resourceEvidenceIds: string[] };
  explanation: string;
}

export interface MeaningAssessment {
  id: string;
  semanticLocationRelationshipId: string;
  sourceSemanticUnitIds: string[];
  targetSemanticUnitIds: string[];
  meaningStatus: MeaningStatus;
  meaningConfidence: LocationConfidence;
  componentAssessments: MeaningComponentAssessment[];
  supportingEvidenceIds: string[];
  conflictingEvidenceIds: string[];
  locationOutcomeSnapshot: LocationOutcome;
  locationConfidenceSnapshot: LocationConfidence;
  locationReviewRequired: boolean;
  reason: MeaningAssessmentReason;
  explanation: string;
  sourceInventoryFingerprint: string;
  targetInventoryFingerprint: string;
  targetRevisionHashes: string[];
  sourceResourceHashes: string[];
  policyBinding: PolicyBinding;
  engineVersion: string;
  modelVersion: string;
  reviewStatus: ReviewStatus;
  lifecycleStatus: LifecycleStatus;
  revision: number;
}

export interface MeaningAnalysisDiagnostics {
  locatedRelationshipsAssessed: number;
  preserved: number;
  preservedWithRestructuring: number;
  partial: number;
  undertranslated: number;
  overtranslated: number;
  meaningShift: number;
  contradicted: number;
  unverifiable: number;
  locationReviewRequired: number;
  resourceConflict: number;
  averageComponentCount: number;
  deterministicContradictionCount: number;
  analyzerLimitedAssessments: number;
}

export interface MeaningAnalysisRun {
  id: string;
  book: string;
  rangeKey: string;
  fingerprint: string;
  locationRunId: string;
  locationRunFingerprint: string;
  sourceInventoryFingerprint: string;
  targetInventoryFingerprint: string;
  meaningEngineVersion: string;
  meaningPolicyVersion: string;
  modelVersion: string;
  calibrationVersion: string;
  runStatus: MeaningRunStatus;
  assessments: MeaningAssessment[];
  diagnostics: MeaningAnalysisDiagnostics;
  elapsedSeconds: number;
  cacheStatus: "MISS" | "HIT";
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
