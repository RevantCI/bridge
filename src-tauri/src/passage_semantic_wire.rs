//! Checked-in serde wire types validated against bridge-passage-semantic-v1.schema.json.
#![allow(dead_code)]

use serde::{Deserialize, Serialize};
use std::collections::HashMap;

pub const PASSAGE_SEMANTIC_SCHEMA_ID: &str =
    "https://bridge.local/schemas/bridge-passage-semantic-v1.schema.json";
pub const PASSAGE_SEMANTIC_SCHEMA_VERSION: u64 = 1;

macro_rules! wire_enum {
    ($name:ident { $($variant:ident),+ $(,)? }) => {
        #[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
        #[serde(rename_all = "SCREAMING_SNAKE_CASE")]
        pub enum $name { $($variant),+ }
    };
}

wire_enum!(ReviewStatus {
    Unreviewed,
    AiProposed,
    HumanApproved,
    HumanRejected,
    HumanModified,
    NeedsDiscussion
});
wire_enum!(LifecycleStatus {
    Active,
    Inactive,
    Stale,
    Superseded,
    Quarantined
});
wire_enum!(QaDisposition {
    Unresolved,
    ConfirmedTranslationError,
    AcceptableTranslation,
    FalsePositive,
    NeedsDiscussion,
    Corrected
});
wire_enum!(TokenSide { Source, Target });
wire_enum!(TokenLayer {
    Orthographic,
    Subtoken,
    Morpheme
});
wire_enum!(TokenKind {
    Word,
    Clitic,
    Morpheme,
    Punctuation,
    Symbol,
    Unknown
});
wire_enum!(Cardinality {
    OneToOne,
    OneToMany,
    ManyToOne,
    ManyToMany,
    SourceToNull,
    NullToTarget
});
wire_enum!(SemanticUnitKind {
    Lexical,
    Morphological,
    Negation,
    Quantifier,
    Participant,
    Referent,
    Predicate,
    SemanticRole,
    Clause,
    ClauseRelation,
    DiscourseRelation,
    ImplicitGrammatical,
    Idiom,
    Construction,
    Temporal,
    Spatial
});
wire_enum!(DependencyRelation {
    Contains,
    DependsOn,
    DerivedFrom,
    Refines
});
wire_enum!(SemanticRelation {
    CorefersWith,
    CoextensiveWith,
    Modifies,
    Negates,
    Quantifies,
    ParticipantOf,
    ArgumentOf,
    SemanticallyRelated
});
wire_enum!(SemanticUnitProvenance {
    CanonicalResource,
    DeterministicRule,
    LanguageAnalyzer,
    ResourceEnriched,
    AiProposed,
    HumanDefined,
    ImportedTc,
    ImportedStage3,
    Migration
});
wire_enum!(AuditEligibility {
    Eligible,
    Conditional,
    AggregateOnly,
    Excluded,
    ReviewOnly
});
wire_enum!(SemanticObligationStrength {
    Required,
    ContextDependent,
    Grammatical,
    Derived,
    NonObligatory,
    Uncertain
});
wire_enum!(CoverageAccountingRole {
    Primary,
    Component,
    Aggregate,
    EvidenceOnly
});
wire_enum!(CoverageDimension {
    LexicalContent,
    Polarity,
    Quantity,
    Participant,
    Referent,
    Predication,
    TemporalAspectual,
    SpatialRelation,
    ClauseRelation,
    DiscourseRelation,
    Other
});
wire_enum!(AuditDirection {
    SourceCoverage,
    TargetSupport
});
wire_enum!(ActorType {
    Human,
    Ai,
    System,
    Migration
});
wire_enum!(ResourceValidationStatus {
    NotChecked,
    Consistent,
    Supporting,
    Conflicting,
    NotApplicable
});
wire_enum!(EvidenceKind {
    SourceText,
    TargetText,
    Morphology,
    TranslationNote,
    TranslationWord,
    TranslationWordList,
    Versification,
    Structure,
    HumanNote,
    AiRationale
});
wire_enum!(QaFindingKind {
    PossiblyMissing,
    Missing,
    PossiblyUnsupported,
    Unsupported,
    ResourceConflict,
    NeedsPassageReview,
    NeedsExtendedPassageReview
});
wire_enum!(PassageStructureKind {
    Chapter,
    Verse,
    VerseBridge,
    Paragraph,
    Poetry,
    Heading,
    Note,
    CrossReference,
    InlineMarkup
});
wire_enum!(ExportFormat {
    Bridge,
    CleanUsfm,
    TranslationcoreAlignedUsfm,
    ScriptureBurrito
});
wire_enum!(ExportabilityLevel {
    Full,
    Partial,
    NotRepresentable,
    TextOnly
});
wire_enum!(ExportReason {
    None,
    CrossVerse,
    NullAlignment,
    SemanticOnly,
    PartialLexicalCoverage,
    FormatLimitation,
    TextOnlyRequest
});
wire_enum!(Realization {
    LexicallyRealized,
    GrammaticallyRealized,
    Pronominalized,
    Implicit,
    NotLocated,
    Uncertain
});
wire_enum!(RelationshipProperty {
    Split,
    Merged,
    CrossVerse,
    Reordered,
    Discontiguous,
    Explicitated,
    ClauseRestructured,
    IdiomaticRealization,
    VersificationDifference
});
wire_enum!(MeaningStatus {
    Preserved,
    PreservedWithRestructuring,
    Partial,
    Overtranslated,
    Undertranslated,
    MeaningShift,
    Contradicted,
    Unverifiable
});
wire_enum!(SourceCoverage {
    NotChecked,
    Covered,
    CoveredByRestructuring,
    PossiblyMissing,
    Missing,
    Uncertain
});
wire_enum!(TargetSupport {
    NotChecked,
    SourceSupported,
    ContextSupported,
    GrammaticallyRequired,
    ExplicitationSupported,
    PossiblyUnsupported,
    Unsupported,
    Uncertain
});

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct PolicyBinding {
    pub confidence_policy_version: String,
    pub calibration_version: String,
    pub audit_policy_version: String,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct ConfidenceScore {
    pub raw_score: Option<f64>,
    pub calibrated_value: f64,
    pub confidence_policy_version: String,
    pub calibration_version: String,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct CharacterSpan {
    pub start_code_point: usize,
    pub end_code_point: usize,
    pub start_grapheme: usize,
    pub end_grapheme: usize,
    pub quote: String,
    pub quote_sha256: String,
    pub coordinate_version: String,
    pub unicode_version: String,
    pub grapheme_segmentation_version: String,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct TokenLineage {
    pub id: String,
    pub side: TokenSide,
    pub project_id: Option<String>,
    pub logical_resource_id: String,
    pub book: String,
    pub canonical_reference_scope: Vec<String>,
    pub token_layer: TokenLayer,
    pub upstream_identity: Option<String>,
    pub created_at: String,
    pub provenance: SemanticUnitProvenance,
    pub review_status: ReviewStatus,
    pub lifecycle_status: LifecycleStatus,
    pub revision: u64,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct TokenInstance {
    pub id: String,
    pub lineage_id: String,
    pub side: TokenSide,
    pub project_id: Option<String>,
    pub resource_id: String,
    pub resource_version: Option<String>,
    pub resource_hash: String,
    pub text_revision: Option<String>,
    pub book: String,
    pub displayed_reference: String,
    pub canonical_references: Vec<String>,
    pub index: usize,
    pub occurrence: usize,
    pub occurrences: usize,
    pub span: Option<CharacterSpan>,
    pub raw_form: String,
    pub normalized_form: String,
    pub normalization_profile: String,
    pub tokenization_version: String,
    pub token_layer: TokenLayer,
    pub token_kind: TokenKind,
    pub parent_instance_id: Option<String>,
    pub instance_fingerprint: String,
    pub lemma: Option<String>,
    pub strong: Option<String>,
    pub morphology: Option<String>,
    pub morphological_features: HashMap<String, String>,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct SemanticUnit {
    pub id: String,
    pub side: TokenSide,
    pub project_id: String,
    pub book: String,
    pub kind: SemanticUnitKind,
    pub displayed_references: Vec<String>,
    pub canonical_references: Vec<String>,
    pub token_instance_ids: Vec<String>,
    pub token_lineage_ids: Vec<String>,
    pub raw_surface: String,
    pub normalized_surface: String,
    pub semantic_features: HashMap<String, String>,
    pub unit_confidence: ConfidenceScore,
    pub provenance: SemanticUnitProvenance,
    pub evidence_ids: Vec<String>,
    pub resource_validation_ids: Vec<String>,
    pub audit_eligibility: AuditEligibility,
    pub semantic_obligation: SemanticObligationStrength,
    pub accounting_role: CoverageAccountingRole,
    pub audit_owner_unit_id: String,
    pub coverage_dimension: CoverageDimension,
    pub semantic_fingerprint: String,
    pub policy_binding: PolicyBinding,
    pub review_status: ReviewStatus,
    pub lifecycle_status: LifecycleStatus,
    pub revision: u64,
}

#[derive(Clone, Debug, Serialize, PartialEq)]
#[serde(transparent)]
pub struct SourceSemanticUnit(SemanticUnit);

impl TryFrom<SemanticUnit> for SourceSemanticUnit {
    type Error = String;

    fn try_from(unit: SemanticUnit) -> Result<Self, Self::Error> {
        match &unit.side {
            TokenSide::Source => Ok(Self(unit)),
            TokenSide::Target => Err("SourceSemanticUnit.side must be SOURCE".into()),
        }
    }
}

impl<'de> Deserialize<'de> for SourceSemanticUnit {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: serde::Deserializer<'de>,
    {
        Self::try_from(SemanticUnit::deserialize(deserializer)?).map_err(serde::de::Error::custom)
    }
}

#[derive(Clone, Debug, Serialize, PartialEq)]
#[serde(transparent)]
pub struct TargetSemanticUnit(SemanticUnit);

impl TryFrom<SemanticUnit> for TargetSemanticUnit {
    type Error = String;

    fn try_from(unit: SemanticUnit) -> Result<Self, Self::Error> {
        match &unit.side {
            TokenSide::Target => Ok(Self(unit)),
            TokenSide::Source => Err("TargetSemanticUnit.side must be TARGET".into()),
        }
    }
}

impl<'de> Deserialize<'de> for TargetSemanticUnit {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: serde::Deserializer<'de>,
    {
        Self::try_from(SemanticUnit::deserialize(deserializer)?).map_err(serde::de::Error::custom)
    }
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct PassageStructureMarker {
    pub kind: PassageStructureKind,
    pub marker: String,
    pub displayed_reference: Option<String>,
    pub start_code_point: Option<usize>,
    pub end_code_point: Option<usize>,
    pub source_order: usize,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct PassageRecord {
    pub id: String,
    pub project_id: String,
    pub book: String,
    pub displayed_source_references: Vec<String>,
    pub displayed_target_references: Vec<String>,
    pub canonical_references: Vec<String>,
    pub source_resource_id: String,
    pub source_resource_version: Option<String>,
    pub source_resource_hash: String,
    pub target_revision: String,
    pub target_content_hash: String,
    pub structure_resource_id: String,
    pub structure_resource_version: Option<String>,
    pub structure_resource_hash: String,
    pub target_text_by_displayed_reference: HashMap<String, String>,
    pub structure_markers: Vec<PassageStructureMarker>,
    pub policy_binding: PolicyBinding,
    pub lifecycle_status: LifecycleStatus,
    pub revision: u64,
}

wire_enum!(PassageSemanticRuntimeState {
    NoProject,
    Ready,
    Unavailable,
    RecoveryRequired
});
wire_enum!(PassageReferenceMappingKind {
    Same,
    Mapped,
    Merge,
    Split,
    PsalmTitle,
    VerseBridge,
    ChapterShift,
    AmbiguousSegment
});
wire_enum!(StructureSnapshotStatus {
    Current,
    StructureTextMismatch
});
wire_enum!(MigrationRunStatus {
    Imported,
    Quarantined,
    Skipped,
    Failed
});

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
pub enum CompanionTokenizerProfile {
    #[serde(rename = "bridge-unicode-word-v1")]
    BridgeUnicodeWordV1,
    #[serde(rename = "tc-whitespace-v1")]
    TcWhitespaceV1,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct PassageReferenceMapping {
    pub displayed_reference: String,
    pub project_versification: String,
    pub canonical_references: Vec<String>,
    pub mapping_kind: PassageReferenceMappingKind,
    pub ordinal: usize,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct PassageSemanticRecoveryStatus {
    pub ok: bool,
    pub read_only: bool,
    pub problems: Vec<String>,
    pub schema_version: u64,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct PassageSemanticRuntimeStatus {
    pub state: PassageSemanticRuntimeState,
    pub available: bool,
    pub read_only: bool,
    pub database_schema_version: Option<u64>,
    pub database_path: Option<String>,
    pub project_id: Option<String>,
    pub book: Option<String>,
    pub replayed_invalidations: Option<u64>,
    pub recovery: Option<PassageSemanticRecoveryStatus>,
    pub error: Option<String>,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct StructureDiagnostic {
    pub code: StructureSnapshotStatus,
    pub reference: Option<String>,
    pub detail: String,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct CurrentPassageSnapshot {
    #[serde(flatten)]
    pub passage: PassageRecord,
    pub reference_mappings: Vec<PassageReferenceMapping>,
    pub target_token_instance_ids: Vec<String>,
    pub structure_status: StructureSnapshotStatus,
    pub structure_diagnostics: Vec<StructureDiagnostic>,
    pub tokenizer_profile: CompanionTokenizerProfile,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct SourceResourceLock {
    pub project_id: String,
    pub book: String,
    pub resource_id: String,
    pub resource_version: String,
    pub resource_hash: String,
    pub lifecycle_status: LifecycleStatus,
    pub revision: u64,
    pub updated_at: String,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct PassageSemanticProjectMetadata {
    pub project_id: String,
    pub identity_fingerprint: String,
    pub book: String,
    pub target_language_id: String,
    pub resource_id: String,
    pub path_history: Vec<String>,
    pub created_at: String,
    pub updated_at: String,
    pub lifecycle_status: LifecycleStatus,
    pub revision: u64,
    pub source_lock: Option<SourceResourceLock>,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct PassageSemanticStaleCounts {
    pub passages: u64,
    pub tokens: u64,
    pub semantic_units: u64,
    pub semantic_relationships: u64,
    pub coverage_accounts: u64,
    pub qa_findings: u64,
    pub lexical_solutions: u64,
    pub correction_proposals: u64,
    pub evidence: u64,
    pub exportability: u64,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct PassageSemanticStaleSummary {
    pub counts: PassageSemanticStaleCounts,
    pub pending_invalidations: u64,
    pub quarantined: u64,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct PassageSemanticMigrationRun {
    pub id: String,
    pub source_path: String,
    pub source_hash: String,
    pub source_schema: String,
    pub status: MigrationRunStatus,
    pub started_at: String,
    pub completed_at: String,
    pub report: serde_json::Value,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct PassageSemanticMigrationReport {
    pub runs: Vec<PassageSemanticMigrationRun>,
    pub quarantine_by_reason: HashMap<String, u64>,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct EvidenceRecord {
    pub id: String,
    pub project_id: String,
    pub book: String,
    pub kind: EvidenceKind,
    pub resource_id: String,
    pub resource_version: Option<String>,
    pub resource_hash: String,
    pub occurrence_id: Option<String>,
    pub displayed_references: Vec<String>,
    pub canonical_references: Vec<String>,
    pub content: String,
    pub content_hash: String,
    pub validation_status: ResourceValidationStatus,
    pub source_semantic_unit_ids: Vec<String>,
    pub target_semantic_unit_ids: Vec<String>,
    pub policy_binding: PolicyBinding,
    pub review_status: ReviewStatus,
    pub lifecycle_status: LifecycleStatus,
    pub revision: u64,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct SemanticRelationship {
    pub id: String,
    pub project_id: String,
    pub book: String,
    pub source_semantic_unit_ids: Vec<String>,
    pub target_semantic_unit_ids: Vec<String>,
    pub lexical_group_ids: Vec<String>,
    pub realization: Realization,
    pub properties: Vec<RelationshipProperty>,
    pub location_confidence: ConfidenceScore,
    pub meaning_status: MeaningStatus,
    pub meaning_confidence: ConfidenceScore,
    pub source_coverage: SourceCoverage,
    pub target_support: TargetSupport,
    pub evidence_ids: Vec<String>,
    pub policy_binding: PolicyBinding,
    pub review_status: ReviewStatus,
    pub lifecycle_status: LifecycleStatus,
    pub revision: u64,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct SemanticUnitDependency {
    pub parent_unit_id: String,
    pub child_unit_id: String,
    pub relation: DependencyRelation,
    pub confidence: ConfidenceScore,
    pub provenance: SemanticUnitProvenance,
    pub evidence_ids: Vec<String>,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct SemanticUnitRelationEdge {
    pub left_unit_id: String,
    pub right_unit_id: String,
    pub relation: SemanticRelation,
    pub confidence: ConfidenceScore,
    pub provenance: SemanticUnitProvenance,
    pub evidence_ids: Vec<String>,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct SemanticCoverageAccount {
    pub id: String,
    pub project_id: String,
    pub passage_id: String,
    pub direction: AuditDirection,
    pub audit_owner_unit_id: String,
    pub member_unit_ids: Vec<String>,
    pub coverage_dimension: CoverageDimension,
    pub semantic_fingerprint: String,
    pub covered_by_relationship_ids: Vec<String>,
    pub excluded_duplicate_unit_ids: Vec<String>,
    pub finding_id: Option<String>,
    pub policy_binding: PolicyBinding,
    pub review_status: ReviewStatus,
    pub lifecycle_status: LifecycleStatus,
    pub revision: u64,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct LexicalSolution {
    pub id: String,
    pub project_id: String,
    pub scope_key: String,
    pub profile_id: String,
    pub source_layer: Option<TokenLayer>,
    pub target_layer: Option<TokenLayer>,
    pub authoritative: bool,
    pub policy_binding: PolicyBinding,
    pub review_status: ReviewStatus,
    pub lifecycle_status: LifecycleStatus,
    pub revision: u64,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct LexicalAlignmentGroup {
    pub id: String,
    pub solution_id: String,
    pub cardinality: Cardinality,
    pub source_layer: Option<TokenLayer>,
    pub target_layer: Option<TokenLayer>,
    pub source_token_instance_ids: Vec<String>,
    pub target_token_instance_ids: Vec<String>,
    pub alignment_family_id: String,
    pub refines_group_id: Option<String>,
    pub policy_binding: PolicyBinding,
    pub review_status: ReviewStatus,
    pub lifecycle_status: LifecycleStatus,
    pub revision: u64,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct QaFinding {
    pub id: String,
    pub project_id: String,
    pub book: String,
    pub passage_id: String,
    pub kind: QaFindingKind,
    pub direction: AuditDirection,
    pub source_semantic_unit_ids: Vec<String>,
    pub target_semantic_unit_ids: Vec<String>,
    pub semantic_relationship_ids: Vec<String>,
    pub evidence_ids: Vec<String>,
    pub explanation: String,
    pub confidence: ConfidenceScore,
    pub current_target_revision: String,
    pub qa_disposition: QaDisposition,
    pub policy_binding: PolicyBinding,
    pub review_status: ReviewStatus,
    pub lifecycle_status: LifecycleStatus,
    pub revision: u64,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct CorrectionProposal {
    pub id: String,
    pub project_id: String,
    pub qa_finding_id: String,
    pub target_displayed_references: Vec<String>,
    pub current_target_revision: String,
    pub current_text: String,
    pub proposed_text: String,
    pub evidence_ids: Vec<String>,
    pub source_semantic_unit_ids: Vec<String>,
    pub policy_binding: PolicyBinding,
    pub review_status: ReviewStatus,
    pub lifecycle_status: LifecycleStatus,
    pub applied_target_revision: Option<String>,
    pub applied_by: Option<String>,
    pub applied_at: Option<String>,
    pub revision: u64,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct ReviewRecord {
    pub id: String,
    pub entity_type: String,
    pub entity_id: String,
    pub previous_review_status: Option<ReviewStatus>,
    pub new_review_status: ReviewStatus,
    pub previous_lifecycle_status: Option<LifecycleStatus>,
    pub new_lifecycle_status: LifecycleStatus,
    pub previous_qa_disposition: Option<QaDisposition>,
    pub new_qa_disposition: Option<QaDisposition>,
    pub actor_type: ActorType,
    pub actor_id: String,
    pub note: String,
    pub base_revision: u64,
    pub created_at: String,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct Exportability {
    pub id: String,
    pub relationship_id: String,
    pub format: ExportFormat,
    pub level: ExportabilityLevel,
    pub reasons: Vec<ExportReason>,
    pub policy_binding: PolicyBinding,
    pub lifecycle_status: LifecycleStatus,
    pub revision: u64,
}

wire_enum!(SourceInventoryCacheStatus { Miss, Hit });

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
pub enum SourceResourceLanguageId {
    #[serde(rename = "hbo")]
    BiblicalHebrew,
    #[serde(rename = "el-x-koine")]
    KoineGreek,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
pub enum SourceTokenLanguageId {
    #[serde(rename = "hbo")]
    BiblicalHebrew,
    #[serde(rename = "arc")]
    BiblicalAramaic,
    #[serde(rename = "el-x-koine")]
    KoineGreek,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
pub enum SourceResourceId {
    #[serde(rename = "uhb")]
    Uhb,
    #[serde(rename = "ugnt")]
    Ugnt,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct SourceInventoryToken {
    #[serde(flatten)]
    pub token: TokenInstance,
    pub language_id: SourceTokenLanguageId,
    pub upstream_identity: String,
    #[serde(default)]
    pub translation_word_concept_ids: Vec<String>,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct SourceInventoryCoverageAccount {
    pub id: String,
    pub audit_owner_unit_id: String,
    pub member_unit_ids: Vec<String>,
    pub coverage_dimension: CoverageDimension,
    pub semantic_fingerprint: String,
    pub excluded_duplicate_unit_ids: Vec<String>,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct SourceInventoryDiagnostics {
    pub source_token_instances: u64,
    pub source_tokens_represented: u64,
    pub required_semantic_obligations: u64,
    pub conditional_obligations: u64,
    pub grammatical_obligations: u64,
    pub derived_aggregate_units: u64,
    pub excluded_units: u64,
    pub review_only_units: u64,
    pub resource_enriched_units: u64,
    pub resource_conflicts: u64,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct SourceInventoryResource {
    pub language_id: SourceResourceLanguageId,
    pub resource_id: SourceResourceId,
    pub version: String,
    pub owner: String,
    pub commit: String,
    pub release: String,
    pub license: String,
    pub provenance_sha256: String,
    pub license_sha256: String,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct SourceSemanticInventory {
    pub id: String,
    pub book: String,
    pub range_key: String,
    pub canonical_references: Vec<String>,
    pub fingerprint: String,
    pub source_semantic_fingerprint: String,
    pub source_resource: SourceInventoryResource,
    pub inventory_engine_version: String,
    pub source_tokenization_version: String,
    pub policy_binding: PolicyBinding,
    pub tokens: Vec<SourceInventoryToken>,
    pub units: Vec<SemanticUnit>,
    pub coverage_accounts: Vec<SourceInventoryCoverageAccount>,
    pub evidence: Vec<EvidenceRecord>,
    pub diagnostics: SourceInventoryDiagnostics,
    pub cache_status: SourceInventoryCacheStatus,
}

wire_enum!(TargetSpanKind {
    Token,
    Subtoken,
    Phrase,
    StructuralSegment,
    Clause,
    Sentence
});
wire_enum!(TargetNeighborhoodScope {
    NormalizedVerse,
    StructuralSentence,
    Paragraph,
    AdjacentStructuralSegment,
    SelectedPassage,
    ChapterBoundaryContinuation
});
wire_enum!(TextDirection { Ltr, Rtl });

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct TargetAnalyzerIdentity {
    pub id: String,
    pub version: String,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct TargetLanguageCapabilities {
    pub language_tag: String,
    pub script: String,
    pub direction: TextDirection,
    pub tokenization: String,
    pub morphology: String,
    pub pos: String,
    pub dependency_syntax: String,
    pub sentence_boundary: String,
    pub coreference: String,
    pub semantic_roles: String,
    pub tokenizer_profile: String,
    pub normalization_profile: String,
    pub providers: Vec<TargetAnalyzerIdentity>,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct TargetSearchSpan {
    pub id: String,
    pub kind: TargetSpanKind,
    pub displayed_reference: String,
    pub token_instance_ids: Vec<String>,
    pub start_code_point: usize,
    pub end_code_point: usize,
    pub quote: String,
    pub quote_sha256: String,
    pub target_revision: String,
    pub span_policy_version: String,
    pub analysis: Option<String>,
    pub provider_id: Option<String>,
    pub provider_version: Option<String>,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct TargetSearchNeighborhood {
    pub id: String,
    pub scope_kind: TargetNeighborhoodScope,
    pub displayed_references: Vec<String>,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct TargetInventoryDiagnostics {
    pub target_characters: u64,
    pub grapheme_clusters: u64,
    pub orthographic_tokens: u64,
    pub subtokens_morphemes: u64,
    pub target_semantic_units: u64,
    pub lexical_units: u64,
    pub grammatical_units: u64,
    pub negation_units: u64,
    pub quantifier_units: u64,
    pub participant_units: u64,
    pub predicate_units: u64,
    pub clauses: u64,
    pub analyzer_derived_units: u64,
    pub review_only_units: u64,
    pub unknown_unsegmented_spans: u64,
    pub search_spans: u64,
    pub search_neighborhoods: u64,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct TargetSemanticInventory {
    pub id: String,
    pub book: String,
    pub range_key: String,
    pub canonical_references: Vec<String>,
    pub fingerprint: String,
    pub target_semantic_fingerprint: String,
    pub target_revision: String,
    pub target_content_hash: String,
    pub target_inventory_engine_version: String,
    pub span_policy_version: String,
    pub capabilities: TargetLanguageCapabilities,
    pub tokens: Vec<TokenInstance>,
    pub units: Vec<SemanticUnit>,
    pub search_spans: Vec<TargetSearchSpan>,
    pub search_neighborhoods: Vec<TargetSearchNeighborhood>,
    pub structure_markers: Vec<PassageStructureMarker>,
    pub diagnostics: TargetInventoryDiagnostics,
    pub cache_status: SourceInventoryCacheStatus,
}

wire_enum!(LocationOutcome {
    Located,
    Ambiguous,
    NotLocated,
    SearchIncomplete,
    UnsupportedAnalysis
});
wire_enum!(LocationRunStatus {
    Running,
    Complete,
    Failed
});
wire_enum!(LocationCalibrationStatus {
    Calibrated,
    UncalibratedInternal
});
wire_enum!(LocationEvidenceKind {
    SemanticSimilarity,
    Lexical,
    Concept,
    Morphology,
    StructuralProximity,
    PassageCoherence,
    Participant,
    HumanPrecedent,
    Resource,
    ExactSpan,
    CandidateCompetition
});
wire_enum!(EmbeddingRole {
    CandidateRetrievalOnly
});

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct SemanticEmbeddingDescriptor {
    pub provider_id: String,
    pub provider_version: String,
    pub model_id: String,
    pub model_hash: String,
    pub dimensions: u64,
    pub normalization: String,
    pub language_capabilities: Vec<String>,
    pub offline: bool,
    pub available: bool,
    pub role: EmbeddingRole,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct LocationEvidenceComponent {
    pub kind: LocationEvidenceKind,
    pub raw_score: f64,
    pub weight: f64,
    pub weighted_score: f64,
    pub provenance: String,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct LocationQuoteAnchor {
    pub span_id: String,
    pub quote: String,
    pub quote_sha256: String,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct SemanticLocationCandidate {
    pub id: String,
    pub source_owner_unit_id: String,
    pub source_semantic_unit_ids: Vec<String>,
    pub target_semantic_unit_ids: Vec<String>,
    pub target_span_ids: Vec<String>,
    pub target_token_instance_ids: Vec<String>,
    pub target_displayed_references: Vec<String>,
    pub target_canonical_references: Vec<String>,
    pub quotes: Vec<LocationQuoteAnchor>,
    pub realization: Realization,
    pub properties: Vec<RelationshipProperty>,
    pub raw_score: f64,
    pub evidence_components: Vec<LocationEvidenceComponent>,
    pub rank: u64,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct LocationConfidence {
    pub raw_score: Option<f64>,
    pub calibrated_value: f64,
    pub confidence_policy_version: String,
    pub calibration_version: String,
    pub calibration_status: LocationCalibrationStatus,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct SemanticLocationRelationship {
    pub id: String,
    pub source_owner_unit_id: String,
    pub source_semantic_unit_ids: Vec<String>,
    pub target_semantic_unit_ids: Vec<String>,
    pub target_span_ids: Vec<String>,
    pub target_token_instance_ids: Vec<String>,
    pub location_outcome: LocationOutcome,
    pub realization: Realization,
    pub properties: Vec<RelationshipProperty>,
    pub location_confidence: LocationConfidence,
    pub selected_candidate_id: Option<String>,
    pub alternative_candidate_ids: Vec<String>,
    pub review_status: ReviewStatus,
    pub lifecycle_status: LifecycleStatus,
    pub revision: u64,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct SemanticLocationDiagnostics {
    pub source_primary_obligations: u64,
    pub locations_found: u64,
    pub ambiguous: u64,
    pub not_located: u64,
    pub search_incomplete: u64,
    pub unsupported_analysis: u64,
    pub same_verse: u64,
    pub cross_verse: u64,
    pub split: u64,
    pub merged: u64,
    pub reordered: bool,
    pub grammatical: u64,
    pub pronominalized: u64,
    pub implicit: u64,
    pub average_candidate_count: f64,
    pub candidate_evaluations: u64,
    pub candidate_budget: u64,
    pub progressive_search_scope_evaluations: HashMap<String, u64>,
    pub contextual_support_edges: u64,
    pub retrieval_seconds: f64,
    pub ranking_seconds: f64,
    pub embedding_seconds: f64,
    pub embedding_cache_hits: u64,
    pub embedding_cache_misses: u64,
    pub embedding_failure: Option<String>,
    pub embedding_cache_hit_rate: f64,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct SemanticLocationRun {
    pub id: String,
    pub book: String,
    pub range_key: String,
    pub fingerprint: String,
    pub source_inventory_id: String,
    pub source_inventory_fingerprint: String,
    pub target_inventory_id: String,
    pub target_inventory_fingerprint: String,
    pub passage_fingerprint: String,
    pub location_engine_version: String,
    pub embedding_provider: SemanticEmbeddingDescriptor,
    pub confidence_policy_version: String,
    pub calibration_version: String,
    pub search_policy_version: String,
    pub run_status: LocationRunStatus,
    pub relationships: Vec<SemanticLocationRelationship>,
    pub candidates: Vec<SemanticLocationCandidate>,
    pub diagnostics: SemanticLocationDiagnostics,
    pub elapsed_seconds: f64,
    pub cache_status: SourceInventoryCacheStatus,
}

wire_enum!(MeaningComponentStatus {
    Preserved,
    PartiallyPreserved,
    Altered,
    Contradicted,
    TargetAddsSpecificity,
    TargetWeakensSpecificity,
    NotExplicitButRecoverable,
    NotDeterminable,
    NotApplicable
});
wire_enum!(MeaningRunStatus {
    Running,
    Complete,
    Failed
});
wire_enum!(MeaningAssessmentReason {
    Assessed,
    NoLocatedRealization,
    AmbiguousLocation,
    SearchIncomplete,
    UnsupportedAnalysis,
    LocationReviewRequired
});
wire_enum!(MeaningEvidenceKind {
    LexicalConcept,
    Polarity,
    Quantity,
    Participant,
    SemanticRole,
    Temporal,
    Completion,
    Modality,
    Grammatical,
    Contextual,
    Resource,
    DeterministicContradiction
});

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct MeaningEvidenceSummary {
    pub id: String,
    pub kind: MeaningEvidenceKind,
    pub resource_status: ResourceValidationStatus,
    pub resource_evidence_ids: Vec<String>,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct MeaningComponentAssessment {
    pub id: String,
    pub coverage_dimension: CoverageDimension,
    pub source_semantic_unit_ids: Vec<String>,
    pub target_semantic_unit_ids: Vec<String>,
    pub target_span_ids: Vec<String>,
    pub status: MeaningComponentStatus,
    pub confidence: LocationConfidence,
    pub evidence: MeaningEvidenceSummary,
    pub explanation: String,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct MeaningAssessment {
    pub id: String,
    pub semantic_location_relationship_id: String,
    pub source_semantic_unit_ids: Vec<String>,
    pub target_semantic_unit_ids: Vec<String>,
    pub meaning_status: MeaningStatus,
    pub meaning_confidence: LocationConfidence,
    pub component_assessments: Vec<MeaningComponentAssessment>,
    pub supporting_evidence_ids: Vec<String>,
    pub conflicting_evidence_ids: Vec<String>,
    pub location_outcome_snapshot: LocationOutcome,
    pub location_confidence_snapshot: LocationConfidence,
    pub location_review_required: bool,
    pub reason: MeaningAssessmentReason,
    pub explanation: String,
    pub source_inventory_fingerprint: String,
    pub target_inventory_fingerprint: String,
    pub target_revision_hashes: Vec<String>,
    pub source_resource_hashes: Vec<String>,
    pub policy_binding: PolicyBinding,
    pub engine_version: String,
    pub model_version: String,
    pub review_status: ReviewStatus,
    pub lifecycle_status: LifecycleStatus,
    pub revision: u64,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct MeaningAnalysisDiagnostics {
    pub located_relationships_assessed: u64,
    pub preserved: u64,
    pub preserved_with_restructuring: u64,
    pub partial: u64,
    pub undertranslated: u64,
    pub overtranslated: u64,
    pub meaning_shift: u64,
    pub contradicted: u64,
    pub unverifiable: u64,
    pub location_review_required: u64,
    pub resource_conflict: u64,
    pub average_component_count: f64,
    pub deterministic_contradiction_count: u64,
    pub analyzer_limited_assessments: u64,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct MeaningAnalysisRun {
    pub id: String,
    pub book: String,
    pub range_key: String,
    pub fingerprint: String,
    pub location_run_id: String,
    pub location_run_fingerprint: String,
    pub source_inventory_fingerprint: String,
    pub target_inventory_fingerprint: String,
    pub meaning_engine_version: String,
    pub meaning_policy_version: String,
    pub model_version: String,
    pub calibration_version: String,
    pub run_status: MeaningRunStatus,
    pub assessments: Vec<MeaningAssessment>,
    pub diagnostics: MeaningAnalysisDiagnostics,
    pub elapsed_seconds: f64,
    pub cache_status: SourceInventoryCacheStatus,
}

pub fn codepoint_span(text: &str, start: usize, end: usize) -> Result<String, String> {
    let points: Vec<char> = text.chars().collect();
    if start > end || end > points.len() {
        return Err(format!("invalid code-point range [{start}, {end})"));
    }
    Ok(points[start..end].iter().collect())
}

pub fn codepoint_to_utf8_offset(text: &str, offset: usize) -> Result<usize, String> {
    if offset > text.chars().count() {
        return Err("code-point offset outside text".into());
    }
    Ok(text.chars().take(offset).map(char::len_utf8).sum())
}

pub fn codepoint_to_utf16_offset(text: &str, offset: usize) -> Result<usize, String> {
    if offset > text.chars().count() {
        return Err("code-point offset outside text".into());
    }
    Ok(text.chars().take(offset).map(char::len_utf16).sum())
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde::Deserialize;

    #[derive(Deserialize)]
    #[serde(rename_all = "camelCase")]
    struct Fixture {
        text: String,
        start_code_point: usize,
        end_code_point: usize,
        quote: String,
    }

    #[test]
    fn shared_unicode_fixtures_use_code_point_coordinates() {
        let fixtures: Vec<Fixture> =
            serde_json::from_str(include_str!("../../schemas/fixtures/unicode-spans-v1.json"))
                .unwrap();
        for fixture in fixtures {
            assert_eq!(
                codepoint_span(
                    &fixture.text,
                    fixture.start_code_point,
                    fixture.end_code_point
                )
                .unwrap(),
                fixture.quote
            );
        }
    }

    #[test]
    fn supplementary_character_has_two_utf16_units() {
        assert_eq!(codepoint_to_utf8_offset("A😀B", 2).unwrap(), 5);
        assert_eq!(codepoint_to_utf16_offset("A😀B", 2).unwrap(), 3);
    }

    #[test]
    fn mandatory_state_enums_use_canonical_wire_values() {
        assert_eq!(
            serde_json::from_str::<ReviewStatus>("\"HUMAN_APPROVED\"").unwrap(),
            ReviewStatus::HumanApproved
        );
        assert_eq!(
            serde_json::from_str::<LifecycleStatus>("\"STALE\"").unwrap(),
            LifecycleStatus::Stale
        );
        assert_eq!(
            serde_json::from_str::<QaDisposition>("\"CONFIRMED_TRANSLATION_ERROR\"").unwrap(),
            QaDisposition::ConfirmedTranslationError
        );
        assert_eq!(
            serde_json::from_str::<Cardinality>("\"SOURCE_TO_NULL\"").unwrap(),
            Cardinality::SourceToNull
        );
        assert_eq!(
            serde_json::from_str::<ResourceValidationStatus>("\"CONFLICTING\"").unwrap(),
            ResourceValidationStatus::Conflicting
        );
        assert_eq!(PASSAGE_SEMANTIC_SCHEMA_VERSION, 1);
    }
}
