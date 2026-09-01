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
