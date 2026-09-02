"""Stage 3 passage-semantic foundation models.

These types are deliberately isolated from the existing Stage 3 candidate
engine and translationCore models.  They define persistence/wire contracts;
they do not run semantic mapping, QA audits, correction generation, or export.
"""
from __future__ import annotations

from dataclasses import dataclass, field, fields, replace
from enum import StrEnum
from typing import Any


SCHEMA_ID = "https://bridge.local/schemas/bridge-passage-semantic-v1.schema.json"
SCHEMA_VERSION = 1
WIRE_VERSION = 1


class ReviewStatus(StrEnum):
    UNREVIEWED = "UNREVIEWED"
    AI_PROPOSED = "AI_PROPOSED"
    HUMAN_APPROVED = "HUMAN_APPROVED"
    HUMAN_REJECTED = "HUMAN_REJECTED"
    HUMAN_MODIFIED = "HUMAN_MODIFIED"
    NEEDS_DISCUSSION = "NEEDS_DISCUSSION"


class LifecycleStatus(StrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    STALE = "STALE"
    SUPERSEDED = "SUPERSEDED"
    QUARANTINED = "QUARANTINED"


class QaDisposition(StrEnum):
    UNRESOLVED = "UNRESOLVED"
    CONFIRMED_TRANSLATION_ERROR = "CONFIRMED_TRANSLATION_ERROR"
    ACCEPTABLE_TRANSLATION = "ACCEPTABLE_TRANSLATION"
    FALSE_POSITIVE = "FALSE_POSITIVE"
    NEEDS_DISCUSSION = "NEEDS_DISCUSSION"
    CORRECTED = "CORRECTED"


class TokenSide(StrEnum):
    SOURCE = "SOURCE"
    TARGET = "TARGET"


class TokenLayer(StrEnum):
    ORTHOGRAPHIC = "ORTHOGRAPHIC"
    SUBTOKEN = "SUBTOKEN"
    MORPHEME = "MORPHEME"


class TokenKind(StrEnum):
    WORD = "WORD"
    CLITIC = "CLITIC"
    MORPHEME = "MORPHEME"
    PUNCTUATION = "PUNCTUATION"
    SYMBOL = "SYMBOL"
    UNKNOWN = "UNKNOWN"


class Cardinality(StrEnum):
    ONE_TO_ONE = "ONE_TO_ONE"
    ONE_TO_MANY = "ONE_TO_MANY"
    MANY_TO_ONE = "MANY_TO_ONE"
    MANY_TO_MANY = "MANY_TO_MANY"
    SOURCE_TO_NULL = "SOURCE_TO_NULL"
    NULL_TO_TARGET = "NULL_TO_TARGET"


class SemanticUnitKind(StrEnum):
    LEXICAL = "LEXICAL"
    MORPHOLOGICAL = "MORPHOLOGICAL"
    NEGATION = "NEGATION"
    QUANTIFIER = "QUANTIFIER"
    PARTICIPANT = "PARTICIPANT"
    REFERENT = "REFERENT"
    PREDICATE = "PREDICATE"
    SEMANTIC_ROLE = "SEMANTIC_ROLE"
    CLAUSE = "CLAUSE"
    CLAUSE_RELATION = "CLAUSE_RELATION"
    DISCOURSE_RELATION = "DISCOURSE_RELATION"
    IMPLICIT_GRAMMATICAL = "IMPLICIT_GRAMMATICAL"
    IDIOM = "IDIOM"
    CONSTRUCTION = "CONSTRUCTION"
    TEMPORAL = "TEMPORAL"
    SPATIAL = "SPATIAL"


class DependencyRelation(StrEnum):
    CONTAINS = "CONTAINS"
    DEPENDS_ON = "DEPENDS_ON"
    DERIVED_FROM = "DERIVED_FROM"
    REFINES = "REFINES"


class SemanticRelation(StrEnum):
    COREFERS_WITH = "COREFERS_WITH"
    COEXTENSIVE_WITH = "COEXTENSIVE_WITH"
    MODIFIES = "MODIFIES"
    NEGATES = "NEGATES"
    QUANTIFIES = "QUANTIFIES"
    PARTICIPANT_OF = "PARTICIPANT_OF"
    ARGUMENT_OF = "ARGUMENT_OF"
    SEMANTICALLY_RELATED = "SEMANTICALLY_RELATED"


class SemanticUnitProvenance(StrEnum):
    CANONICAL_RESOURCE = "CANONICAL_RESOURCE"
    DETERMINISTIC_RULE = "DETERMINISTIC_RULE"
    LANGUAGE_ANALYZER = "LANGUAGE_ANALYZER"
    RESOURCE_ENRICHED = "RESOURCE_ENRICHED"
    AI_PROPOSED = "AI_PROPOSED"
    HUMAN_DEFINED = "HUMAN_DEFINED"
    IMPORTED_TC = "IMPORTED_TC"
    IMPORTED_STAGE3 = "IMPORTED_STAGE3"
    MIGRATION = "MIGRATION"


class AuditEligibility(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    CONDITIONAL = "CONDITIONAL"
    AGGREGATE_ONLY = "AGGREGATE_ONLY"
    EXCLUDED = "EXCLUDED"
    REVIEW_ONLY = "REVIEW_ONLY"


class SemanticObligationStrength(StrEnum):
    REQUIRED = "REQUIRED"
    CONTEXT_DEPENDENT = "CONTEXT_DEPENDENT"
    GRAMMATICAL = "GRAMMATICAL"
    DERIVED = "DERIVED"
    NON_OBLIGATORY = "NON_OBLIGATORY"
    UNCERTAIN = "UNCERTAIN"


class CoverageAccountingRole(StrEnum):
    PRIMARY = "PRIMARY"
    COMPONENT = "COMPONENT"
    AGGREGATE = "AGGREGATE"
    EVIDENCE_ONLY = "EVIDENCE_ONLY"


class CoverageDimension(StrEnum):
    LEXICAL_CONTENT = "LEXICAL_CONTENT"
    POLARITY = "POLARITY"
    QUANTITY = "QUANTITY"
    PARTICIPANT = "PARTICIPANT"
    REFERENT = "REFERENT"
    PREDICATION = "PREDICATION"
    TEMPORAL_ASPECTUAL = "TEMPORAL_ASPECTUAL"
    SPATIAL_RELATION = "SPATIAL_RELATION"
    CLAUSE_RELATION = "CLAUSE_RELATION"
    DISCOURSE_RELATION = "DISCOURSE_RELATION"
    OTHER = "OTHER"


class AuditDirection(StrEnum):
    SOURCE_COVERAGE = "SOURCE_COVERAGE"
    TARGET_SUPPORT = "TARGET_SUPPORT"


class LineageRelation(StrEnum):
    SAME_LINEAGE = "SAME_LINEAGE"
    POSSIBLE_SUCCESSOR = "POSSIBLE_SUCCESSOR"
    SPLIT_FROM = "SPLIT_FROM"
    MERGED_FROM = "MERGED_FROM"
    NO_CORRESPONDENCE = "NO_CORRESPONDENCE"


class Realization(StrEnum):
    LEXICALLY_REALIZED = "LEXICALLY_REALIZED"
    GRAMMATICALLY_REALIZED = "GRAMMATICALLY_REALIZED"
    PRONOMINALIZED = "PRONOMINALIZED"
    IMPLICIT = "IMPLICIT"
    NOT_LOCATED = "NOT_LOCATED"
    UNCERTAIN = "UNCERTAIN"


class LocationOutcome(StrEnum):
    LOCATED = "LOCATED"
    AMBIGUOUS = "AMBIGUOUS"
    NOT_LOCATED = "NOT_LOCATED"
    SEARCH_INCOMPLETE = "SEARCH_INCOMPLETE"
    UNSUPPORTED_ANALYSIS = "UNSUPPORTED_ANALYSIS"


class LocationRunStatus(StrEnum):
    RUNNING = "RUNNING"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"


class LocationEvidenceKind(StrEnum):
    SEMANTIC_SIMILARITY = "SEMANTIC_SIMILARITY"
    LEXICAL = "LEXICAL"
    CONCEPT = "CONCEPT"
    MORPHOLOGY = "MORPHOLOGY"
    STRUCTURAL_PROXIMITY = "STRUCTURAL_PROXIMITY"
    PASSAGE_COHERENCE = "PASSAGE_COHERENCE"
    PARTICIPANT = "PARTICIPANT"
    HUMAN_PRECEDENT = "HUMAN_PRECEDENT"
    RESOURCE = "RESOURCE"
    EXACT_SPAN = "EXACT_SPAN"
    CANDIDATE_COMPETITION = "CANDIDATE_COMPETITION"


class LocationCalibrationStatus(StrEnum):
    CALIBRATED = "CALIBRATED"
    UNCALIBRATED_INTERNAL = "UNCALIBRATED_INTERNAL"


class EmbeddingRole(StrEnum):
    CANDIDATE_RETRIEVAL_ONLY = "CANDIDATE_RETRIEVAL_ONLY"


class RelationshipProperty(StrEnum):
    SPLIT = "SPLIT"
    MERGED = "MERGED"
    CROSS_VERSE = "CROSS_VERSE"
    REORDERED = "REORDERED"
    DISCONTIGUOUS = "DISCONTIGUOUS"
    EXPLICITATED = "EXPLICITATED"
    CLAUSE_RESTRUCTURED = "CLAUSE_RESTRUCTURED"
    IDIOMATIC_REALIZATION = "IDIOMATIC_REALIZATION"
    VERSIFICATION_DIFFERENCE = "VERSIFICATION_DIFFERENCE"


class MeaningStatus(StrEnum):
    PRESERVED = "PRESERVED"
    PRESERVED_WITH_RESTRUCTURING = "PRESERVED_WITH_RESTRUCTURING"
    PARTIAL = "PARTIAL"
    OVERTRANSLATED = "OVERTRANSLATED"
    UNDERTRANSLATED = "UNDERTRANSLATED"
    MEANING_SHIFT = "MEANING_SHIFT"
    CONTRADICTED = "CONTRADICTED"
    UNVERIFIABLE = "UNVERIFIABLE"


class MeaningComponentStatus(StrEnum):
    PRESERVED = "PRESERVED"
    PARTIALLY_PRESERVED = "PARTIALLY_PRESERVED"
    ALTERED = "ALTERED"
    CONTRADICTED = "CONTRADICTED"
    TARGET_ADDS_SPECIFICITY = "TARGET_ADDS_SPECIFICITY"
    TARGET_WEAKENS_SPECIFICITY = "TARGET_WEAKENS_SPECIFICITY"
    NOT_EXPLICIT_BUT_RECOVERABLE = "NOT_EXPLICIT_BUT_RECOVERABLE"
    NOT_DETERMINABLE = "NOT_DETERMINABLE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class MeaningRunStatus(StrEnum):
    RUNNING = "RUNNING"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"


class MeaningAssessmentReason(StrEnum):
    ASSESSED = "ASSESSED"
    NO_LOCATED_REALIZATION = "NO_LOCATED_REALIZATION"
    AMBIGUOUS_LOCATION = "AMBIGUOUS_LOCATION"
    SEARCH_INCOMPLETE = "SEARCH_INCOMPLETE"
    UNSUPPORTED_ANALYSIS = "UNSUPPORTED_ANALYSIS"
    LOCATION_REVIEW_REQUIRED = "LOCATION_REVIEW_REQUIRED"


class MeaningEvidenceKind(StrEnum):
    LEXICAL_CONCEPT = "LEXICAL_CONCEPT"
    POLARITY = "POLARITY"
    QUANTITY = "QUANTITY"
    PARTICIPANT = "PARTICIPANT"
    SEMANTIC_ROLE = "SEMANTIC_ROLE"
    TEMPORAL = "TEMPORAL"
    COMPLETION = "COMPLETION"
    MODALITY = "MODALITY"
    GRAMMATICAL = "GRAMMATICAL"
    CONTEXTUAL = "CONTEXTUAL"
    RESOURCE = "RESOURCE"
    DETERMINISTIC_CONTRADICTION = "DETERMINISTIC_CONTRADICTION"


class SourceCoverage(StrEnum):
    NOT_CHECKED = "NOT_CHECKED"
    COVERED = "COVERED"
    COVERED_BY_RESTRUCTURING = "COVERED_BY_RESTRUCTURING"
    POSSIBLY_MISSING = "POSSIBLY_MISSING"
    MISSING = "MISSING"
    UNCERTAIN = "UNCERTAIN"


class TargetSupport(StrEnum):
    NOT_CHECKED = "NOT_CHECKED"
    SOURCE_SUPPORTED = "SOURCE_SUPPORTED"
    CONTEXT_SUPPORTED = "CONTEXT_SUPPORTED"
    GRAMMATICALLY_REQUIRED = "GRAMMATICALLY_REQUIRED"
    EXPLICITATION_SUPPORTED = "EXPLICITATION_SUPPORTED"
    POSSIBLY_UNSUPPORTED = "POSSIBLY_UNSUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"
    UNCERTAIN = "UNCERTAIN"


class ActorType(StrEnum):
    HUMAN = "HUMAN"
    AI = "AI"
    SYSTEM = "SYSTEM"
    MIGRATION = "MIGRATION"


class ResourceValidationStatus(StrEnum):
    NOT_CHECKED = "NOT_CHECKED"
    CONSISTENT = "CONSISTENT"
    SUPPORTING = "SUPPORTING"
    CONFLICTING = "CONFLICTING"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class EvidenceKind(StrEnum):
    SOURCE_TEXT = "SOURCE_TEXT"
    TARGET_TEXT = "TARGET_TEXT"
    MORPHOLOGY = "MORPHOLOGY"
    TRANSLATION_NOTE = "TRANSLATION_NOTE"
    TRANSLATION_WORD = "TRANSLATION_WORD"
    TRANSLATION_WORD_LIST = "TRANSLATION_WORD_LIST"
    VERSIFICATION = "VERSIFICATION"
    STRUCTURE = "STRUCTURE"
    HUMAN_NOTE = "HUMAN_NOTE"
    AI_RATIONALE = "AI_RATIONALE"
    SOURCE_VARIANT = "SOURCE_VARIANT"


class QaFindingKind(StrEnum):
    POSSIBLY_MISSING = "POSSIBLY_MISSING"
    MISSING = "MISSING"
    POSSIBLY_UNSUPPORTED = "POSSIBLY_UNSUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"
    RESOURCE_CONFLICT = "RESOURCE_CONFLICT"
    NEEDS_PASSAGE_REVIEW = "NEEDS_PASSAGE_REVIEW"
    NEEDS_EXTENDED_PASSAGE_REVIEW = "NEEDS_EXTENDED_PASSAGE_REVIEW"
    POSSIBLE_OMISSION = "POSSIBLE_OMISSION"
    POSSIBLE_ADDITION = "POSSIBLE_ADDITION"
    POSSIBLE_UNDERTRANSLATION = "POSSIBLE_UNDERTRANSLATION"
    POSSIBLE_OVERTRANSLATION = "POSSIBLE_OVERTRANSLATION"
    MEANING_SHIFT = "MEANING_SHIFT"
    CONTRADICTION = "CONTRADICTION"
    NEGATION_PROBLEM = "NEGATION_PROBLEM"
    QUANTITY_PROBLEM = "QUANTITY_PROBLEM"
    TEMPORAL_PROBLEM = "TEMPORAL_PROBLEM"
    PARTICIPANT_PROBLEM = "PARTICIPANT_PROBLEM"
    REFERENT_PROBLEM = "REFERENT_PROBLEM"
    SOURCE_VARIANT_REVIEW = "SOURCE_VARIANT_REVIEW"


class QaFindingSeverity(StrEnum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"


class QaRunStatus(StrEnum):
    RUNNING = "RUNNING"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"


class PassageStructureKind(StrEnum):
    CHAPTER = "CHAPTER"
    VERSE = "VERSE"
    VERSE_BRIDGE = "VERSE_BRIDGE"
    PARAGRAPH = "PARAGRAPH"
    POETRY = "POETRY"
    HEADING = "HEADING"
    NOTE = "NOTE"
    CROSS_REFERENCE = "CROSS_REFERENCE"
    INLINE_MARKUP = "INLINE_MARKUP"


class ExportFormat(StrEnum):
    BRIDGE = "BRIDGE"
    CLEAN_USFM = "CLEAN_USFM"
    TRANSLATIONCORE_ALIGNED_USFM = "TRANSLATIONCORE_ALIGNED_USFM"
    SCRIPTURE_BURRITO = "SCRIPTURE_BURRITO"


class ExportabilityLevel(StrEnum):
    FULL = "FULL"
    PARTIAL = "PARTIAL"
    NOT_REPRESENTABLE = "NOT_REPRESENTABLE"
    TEXT_ONLY = "TEXT_ONLY"


class ExportReason(StrEnum):
    NONE = "NONE"
    CROSS_VERSE = "CROSS_VERSE"
    NULL_ALIGNMENT = "NULL_ALIGNMENT"
    SEMANTIC_ONLY = "SEMANTIC_ONLY"
    PARTIAL_LEXICAL_COVERAGE = "PARTIAL_LEXICAL_COVERAGE"
    FORMAT_LIMITATION = "FORMAT_LIMITATION"
    TEXT_ONLY_REQUEST = "TEXT_ONLY_REQUEST"


@dataclass(frozen=True)
class PolicyBinding:
    confidence_policy_version: str
    calibration_version: str
    audit_policy_version: str

    @classmethod
    def foundation_v1(cls) -> "PolicyBinding":
        return cls("confidence-v1", "calibration-v1", "audit-v1")


@dataclass(frozen=True)
class ConfidenceScore:
    raw_score: float | None
    calibrated_value: float
    confidence_policy_version: str
    calibration_version: str

    def __post_init__(self) -> None:
        for value in (self.raw_score, self.calibrated_value):
            if value is not None and not 0.0 <= value <= 1.0:
                raise ValueError("Confidence values must be between 0 and 1")


@dataclass(frozen=True)
class CharacterSpan:
    start_code_point: int
    end_code_point: int
    start_grapheme: int
    end_grapheme: int
    quote: str
    quote_sha256: str
    coordinate_version: str = "unicode-code-point-v1"
    unicode_version: str = "15.1"
    grapheme_segmentation_version: str = "UAX29-15.1"

    def __post_init__(self) -> None:
        if min(self.start_code_point, self.end_code_point, self.start_grapheme, self.end_grapheme) < 0:
            raise ValueError("Character-span coordinates cannot be negative")
        if self.end_code_point < self.start_code_point or self.end_grapheme < self.start_grapheme:
            raise ValueError("Character-span end coordinates must not precede their starts")
        if len(self.quote_sha256) != 64 or any(ch not in "0123456789abcdef" for ch in self.quote_sha256):
            raise ValueError("quote_sha256 must be a lowercase hexadecimal SHA-256 digest")


@dataclass(frozen=True)
class TokenLineage:
    id: str
    side: TokenSide
    project_id: str | None
    logical_resource_id: str
    book: str
    canonical_reference_scope: tuple[str, ...]
    token_layer: TokenLayer
    upstream_identity: str | None
    created_at: str
    provenance: SemanticUnitProvenance
    review_status: ReviewStatus = ReviewStatus.UNREVIEWED
    lifecycle_status: LifecycleStatus = LifecycleStatus.ACTIVE
    revision: int = 1


@dataclass(frozen=True)
class TokenInstance:
    id: str
    lineage_id: str
    side: TokenSide
    project_id: str | None
    resource_id: str
    resource_version: str | None
    resource_hash: str
    text_revision: str | None
    book: str
    displayed_reference: str
    canonical_references: tuple[str, ...]
    index: int
    occurrence: int
    occurrences: int
    span: CharacterSpan | None
    raw_form: str
    normalized_form: str
    normalization_profile: str
    tokenization_version: str
    token_layer: TokenLayer
    token_kind: TokenKind
    parent_instance_id: str | None
    instance_fingerprint: str
    lemma: str | None = None
    strong: str | None = None
    morphology: str | None = None
    morphological_features: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class SemanticUnit:
    id: str
    side: TokenSide
    project_id: str
    book: str
    kind: SemanticUnitKind
    displayed_references: tuple[str, ...]
    canonical_references: tuple[str, ...]
    token_instance_ids: tuple[str, ...]
    token_lineage_ids: tuple[str, ...]
    raw_surface: str
    normalized_surface: str
    semantic_features: dict[str, str]
    unit_confidence: ConfidenceScore
    provenance: SemanticUnitProvenance
    evidence_ids: tuple[str, ...]
    resource_validation_ids: tuple[str, ...]
    audit_eligibility: AuditEligibility
    semantic_obligation: SemanticObligationStrength
    accounting_role: CoverageAccountingRole
    audit_owner_unit_id: str
    coverage_dimension: CoverageDimension
    semantic_fingerprint: str
    policy_binding: PolicyBinding
    review_status: ReviewStatus
    lifecycle_status: LifecycleStatus
    revision: int = 1


@dataclass(frozen=True)
class SourceSemanticUnit(SemanticUnit):
    def __post_init__(self) -> None:
        if self.side != TokenSide.SOURCE:
            raise ValueError("SourceSemanticUnit.side must be SOURCE")


@dataclass(frozen=True)
class TargetSemanticUnit(SemanticUnit):
    def __post_init__(self) -> None:
        if self.side != TokenSide.TARGET:
            raise ValueError("TargetSemanticUnit.side must be TARGET")


@dataclass(frozen=True)
class SemanticUnitDependency:
    parent_unit_id: str
    child_unit_id: str
    relation: DependencyRelation
    confidence: ConfidenceScore
    provenance: SemanticUnitProvenance
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class SemanticUnitRelationEdge:
    left_unit_id: str
    right_unit_id: str
    relation: SemanticRelation
    confidence: ConfidenceScore
    provenance: SemanticUnitProvenance
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class SemanticRelationship:
    id: str
    project_id: str
    book: str
    source_semantic_unit_ids: tuple[str, ...]
    target_semantic_unit_ids: tuple[str, ...]
    lexical_group_ids: tuple[str, ...]
    realization: Realization
    properties: tuple[RelationshipProperty, ...]
    location_confidence: ConfidenceScore
    meaning_status: MeaningStatus
    meaning_confidence: ConfidenceScore
    source_coverage: SourceCoverage
    target_support: TargetSupport
    evidence_ids: tuple[str, ...]
    policy_binding: PolicyBinding
    review_status: ReviewStatus
    lifecycle_status: LifecycleStatus
    revision: int = 1


@dataclass(frozen=True)
class SemanticCoverageAccount:
    id: str
    project_id: str
    passage_id: str
    direction: AuditDirection
    audit_owner_unit_id: str
    member_unit_ids: tuple[str, ...]
    coverage_dimension: CoverageDimension
    semantic_fingerprint: str
    covered_by_relationship_ids: tuple[str, ...]
    excluded_duplicate_unit_ids: tuple[str, ...]
    finding_id: str | None
    policy_binding: PolicyBinding
    review_status: ReviewStatus
    lifecycle_status: LifecycleStatus
    revision: int = 1
    coverage_status: str = "NOT_CHECKED"

    def __post_init__(self) -> None:
        if self.direction == AuditDirection.SOURCE_COVERAGE:
            try:
                SourceCoverage(self.coverage_status)
            except ValueError as exc:
                raise ValueError(
                    "SOURCE_COVERAGE account requires a SourceCoverage coverage_status"
                ) from exc
        elif self.direction == AuditDirection.TARGET_SUPPORT:
            try:
                TargetSupport(self.coverage_status)
            except ValueError as exc:
                raise ValueError(
                    "TARGET_SUPPORT account requires a TargetSupport coverage_status"
                ) from exc


@dataclass(frozen=True)
class LexicalSolution:
    id: str
    project_id: str
    scope_key: str
    profile_id: str
    source_layer: TokenLayer | None
    target_layer: TokenLayer | None
    authoritative: bool
    policy_binding: PolicyBinding
    review_status: ReviewStatus
    lifecycle_status: LifecycleStatus
    revision: int = 1


@dataclass(frozen=True)
class LexicalAlignmentGroup:
    id: str
    solution_id: str
    cardinality: Cardinality
    source_layer: TokenLayer | None
    target_layer: TokenLayer | None
    source_token_instance_ids: tuple[str, ...]
    target_token_instance_ids: tuple[str, ...]
    alignment_family_id: str
    refines_group_id: str | None
    policy_binding: PolicyBinding
    review_status: ReviewStatus
    lifecycle_status: LifecycleStatus
    revision: int = 1

    def __post_init__(self) -> None:
        if self.cardinality == Cardinality.SOURCE_TO_NULL and (
            self.source_layer is None or self.target_layer is not None
            or not self.source_token_instance_ids or self.target_token_instance_ids
        ):
            raise ValueError("SOURCE_TO_NULL requires a null target layer and no target tokens")
        if self.cardinality == Cardinality.NULL_TO_TARGET and (
            self.source_layer is not None or self.target_layer is None
            or self.source_token_instance_ids or not self.target_token_instance_ids
        ):
            raise ValueError("NULL_TO_TARGET requires a null source layer and no source tokens")


@dataclass(frozen=True)
class PassageStructureMarker:
    kind: PassageStructureKind
    marker: str
    displayed_reference: str | None
    start_code_point: int | None
    end_code_point: int | None
    source_order: int


@dataclass(frozen=True)
class PassageRecord:
    id: str
    project_id: str
    book: str
    displayed_source_references: tuple[str, ...]
    displayed_target_references: tuple[str, ...]
    canonical_references: tuple[str, ...]
    source_resource_id: str
    source_resource_version: str | None
    source_resource_hash: str
    target_revision: str
    target_content_hash: str
    structure_resource_id: str
    structure_resource_version: str | None
    structure_resource_hash: str
    target_text_by_displayed_reference: dict[str, str]
    structure_markers: tuple[PassageStructureMarker, ...]
    policy_binding: PolicyBinding
    lifecycle_status: LifecycleStatus
    revision: int = 1


@dataclass(frozen=True)
class EvidenceRecord:
    id: str
    project_id: str
    book: str
    kind: EvidenceKind
    resource_id: str
    resource_version: str | None
    resource_hash: str
    occurrence_id: str | None
    displayed_references: tuple[str, ...]
    canonical_references: tuple[str, ...]
    content: str
    content_hash: str
    validation_status: ResourceValidationStatus
    source_semantic_unit_ids: tuple[str, ...]
    target_semantic_unit_ids: tuple[str, ...]
    policy_binding: PolicyBinding
    review_status: ReviewStatus
    lifecycle_status: LifecycleStatus
    revision: int = 1


@dataclass(frozen=True)
class Exportability:
    id: str
    relationship_id: str
    format: ExportFormat
    level: ExportabilityLevel
    reasons: tuple[ExportReason, ...]
    policy_binding: PolicyBinding
    lifecycle_status: LifecycleStatus
    revision: int = 1


@dataclass(frozen=True)
class QaFinding:
    id: str
    project_id: str
    book: str
    passage_id: str
    kind: QaFindingKind
    direction: AuditDirection
    source_semantic_unit_ids: tuple[str, ...]
    target_semantic_unit_ids: tuple[str, ...]
    semantic_relationship_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    explanation: str
    confidence: ConfidenceScore
    current_target_revision: str
    qa_disposition: QaDisposition
    policy_binding: PolicyBinding
    review_status: ReviewStatus
    lifecycle_status: LifecycleStatus
    severity: QaFindingSeverity
    meaning_assessment_ids: tuple[str, ...]
    coverage_account_ids: tuple[str, ...]
    location_outcome_snapshot: str
    meaning_status_snapshot: str
    supporting_evidence_ids: tuple[str, ...]
    conflicting_evidence_ids: tuple[str, ...]
    resource_evidence_ids: tuple[str, ...]
    target_content_hashes: tuple[str, ...]
    source_resource_hashes: tuple[str, ...]
    qa_engine_version: str
    qa_policy_version: str
    fingerprint: str
    revision: int = 1


@dataclass(frozen=True)
class CorrectionProposal:
    id: str
    project_id: str
    qa_finding_id: str
    target_displayed_references: tuple[str, ...]
    current_target_revision: str
    current_text: str
    proposed_text: str
    evidence_ids: tuple[str, ...]
    source_semantic_unit_ids: tuple[str, ...]
    policy_binding: PolicyBinding
    review_status: ReviewStatus
    lifecycle_status: LifecycleStatus
    applied_target_revision: str | None
    applied_by: str | None
    applied_at: str | None
    revision: int = 1

    @classmethod
    def example(cls, proposal_id: str, qa_finding_id: str) -> "CorrectionProposal":
        return cls(
            id=proposal_id, project_id="project-1", qa_finding_id=qa_finding_id,
            target_displayed_references=("PHP 1:3",), current_target_revision="rev-1",
            current_text="current", proposed_text="proposed", evidence_ids=(),
            source_semantic_unit_ids=(), policy_binding=PolicyBinding.foundation_v1(),
            review_status=ReviewStatus.AI_PROPOSED, lifecycle_status=LifecycleStatus.INACTIVE,
            applied_target_revision=None, applied_by=None, applied_at=None,
        )

    def with_lifecycle(self, status: LifecycleStatus) -> "CorrectionProposal":
        return replace(self, lifecycle_status=status)


@dataclass(frozen=True)
class ReviewRecord:
    id: str
    entity_type: str
    entity_id: str
    previous_review_status: ReviewStatus | None
    new_review_status: ReviewStatus
    previous_lifecycle_status: LifecycleStatus | None
    new_lifecycle_status: LifecycleStatus
    previous_qa_disposition: QaDisposition | None
    new_qa_disposition: QaDisposition | None
    actor_type: ActorType
    actor_id: str
    note: str
    base_revision: int
    created_at: str


def _wire(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, tuple):
        return [_wire(x) for x in value]
    if isinstance(value, list):
        return [_wire(x) for x in value]
    if isinstance(value, dict):
        return {k: _wire(v) for k, v in value.items()}
    if hasattr(value, "__dataclass_fields__"):
        return {_camel(item.name): _wire(getattr(value, item.name)) for item in fields(value)}
    return value


def _camel(name: str) -> str:
    head, *tail = name.split("_")
    return head + "".join(part[:1].upper() + part[1:] for part in tail)


def to_wire(value: Any) -> dict[str, Any]:
    result = _wire(value)
    if not isinstance(result, dict):
        raise TypeError("A wire record must serialize to an object")
    return result
