from __future__ import annotations

import json
import hashlib
from dataclasses import fields
from pathlib import Path

import pytest

from tc_ai_bridge.passage_semantic_models import (
    ActorType,
    AuditDirection,
    AuditEligibility,
    Cardinality,
    CharacterSpan,
    ConfidenceScore,
    CorrectionProposal,
    CoverageAccountingRole,
    CoverageDimension,
    DependencyRelation,
    EvidenceKind,
    EvidenceRecord,
    ExportFormat,
    ExportReason,
    Exportability,
    ExportabilityLevel,
    LifecycleStatus,
    LexicalAlignmentGroup,
    LexicalSolution,
    MeaningStatus,
    PassageRecord,
    PassageStructureKind,
    PassageStructureMarker,
    PolicyBinding,
    QaDisposition,
    QaFinding,
    QaFindingKind,
    ResourceValidationStatus,
    SCHEMA_ID,
    ReviewStatus,
    ReviewRecord,
    Realization,
    RelationshipProperty,
    SemanticObligationStrength,
    SemanticCoverageAccount,
    SemanticRelationship,
    SemanticRelation,
    SemanticUnitKind,
    SemanticUnit,
    SemanticUnitDependency,
    SemanticUnitProvenance,
    SemanticUnitRelationEdge,
    SourceSemanticUnit,
    SourceCoverage,
    TargetSupport,
    TargetSemanticUnit,
    TokenInstance,
    TokenKind,
    TokenLineage,
    TokenSide,
    TokenLayer,
)
from tc_ai_bridge.passage_semantic_repository import (
    DATABASE_SCHEMA_VERSION,
    FoundationConflict,
    FoundationRepository,
    FoundationValidationError,
    _MIGRATION_V1,
)
from tc_ai_bridge.unicode_coordinates import (
    codepoint_span,
    codepoint_to_utf16_offset,
    codepoint_to_utf8_offset,
    utf16_to_codepoint_offset,
    utf8_to_codepoint_offset,
    validate_codepoint_span,
)


ROOT = Path(__file__).resolve().parents[2]


def _solution(repo: FoundationRepository, solution_id: str, *, authoritative: bool = False) -> None:
    repo.create_lexical_solution(
        solution_id=solution_id,
        project_id="project-1",
        scope_key="PHP 1:3-6",
        profile_id="default",
        source_layer=TokenLayer.ORTHOGRAPHIC,
        target_layer=TokenLayer.ORTHOGRAPHIC,
        authoritative=authoritative,
    )


def _token(
    repo: FoundationRepository, token_id: str, side: TokenSide, layer: TokenLayer,
    *, parent_id: str | None = None,
) -> None:
    lineage_id = f"lineage-{token_id}"
    repo.save_token_lineage(TokenLineage(
        id=lineage_id, side=side, project_id="project-1" if side == TokenSide.TARGET else None,
        logical_resource_id="target" if side == TokenSide.TARGET else "UGNT", book="PHP",
        canonical_reference_scope=("PHP 1:1",), token_layer=layer, upstream_identity=None,
        created_at="2026-09-01T00:00:00+00:00", provenance=SemanticUnitProvenance.DETERMINISTIC_RULE,
    ))
    repo.save_token_instance(TokenInstance(
        id=token_id, lineage_id=lineage_id, side=side,
        project_id="project-1" if side == TokenSide.TARGET else None,
        resource_id="target" if side == TokenSide.TARGET else "UGNT", resource_version="v1",
        resource_hash="hash", text_revision="rev-1" if side == TokenSide.TARGET else None,
        book="PHP", displayed_reference="PHP 1:1", canonical_references=("PHP 1:1",),
        index=0, occurrence=1, occurrences=1, span=None, raw_form=token_id,
        normalized_form=token_id, normalization_profile="NFC-v1", tokenization_version="v1",
        token_layer=layer, token_kind=TokenKind.WORD, parent_instance_id=parent_id,
        instance_fingerprint=f"fp-{token_id}",
    ))


def _unit(unit_id: str, side: TokenSide, token_id: str) -> SemanticUnit:
    confidence = ConfidenceScore(None, 0.9, "confidence-v1", "calibration-v1")
    unit_type = SourceSemanticUnit if side == TokenSide.SOURCE else TargetSemanticUnit
    return unit_type(
        id=unit_id, side=side, project_id="project-1", book="PHP", kind=SemanticUnitKind.LEXICAL,
        displayed_references=("PHP 1:1",), canonical_references=("PHP 1:1",),
        token_instance_ids=(token_id,), token_lineage_ids=(f"lineage-{token_id}",),
        raw_surface=token_id, normalized_surface=token_id, semantic_features={},
        unit_confidence=confidence, provenance=SemanticUnitProvenance.DETERMINISTIC_RULE,
        evidence_ids=(), resource_validation_ids=(), audit_eligibility=AuditEligibility.ELIGIBLE,
        semantic_obligation=SemanticObligationStrength.REQUIRED,
        accounting_role=CoverageAccountingRole.PRIMARY, audit_owner_unit_id=unit_id,
        coverage_dimension=CoverageDimension.LEXICAL_CONTENT, semantic_fingerprint=f"semantic-{unit_id}",
        policy_binding=PolicyBinding.foundation_v1(), review_status=ReviewStatus.UNREVIEWED,
        lifecycle_status=LifecycleStatus.ACTIVE,
    )


def test_review_and_lifecycle_are_independent() -> None:
    proposal = CorrectionProposal.example("proposal-1", "qa-1")
    stale = proposal.with_lifecycle(LifecycleStatus.STALE)
    assert stale.review_status == ReviewStatus.AI_PROPOSED
    assert stale.lifecycle_status == LifecycleStatus.STALE


def test_only_one_authoritative_active_solution_per_scope_profile_layers(tmp_path: Path) -> None:
    repo = FoundationRepository(tmp_path / "semantic.sqlite3")
    _solution(repo, "solution-a", authoritative=True)
    _solution(repo, "solution-b")
    with pytest.raises(FoundationConflict, match="authoritative active lexical solution"):
        repo.activate_lexical_solution("solution-b", expected_revision=1, authoritative=True)
    repo.activate_lexical_solution(
        "solution-b", expected_revision=1, authoritative=True, supersede_solution_id="solution-a"
    )
    assert repo.lexical_solution("solution-a")["lifecycleStatus"] == "SUPERSEDED"
    assert repo.lexical_solution("solution-b")["lifecycleStatus"] == "ACTIVE"


def test_null_group_requires_null_layer_on_absent_side(tmp_path: Path) -> None:
    repo = FoundationRepository(tmp_path / "semantic.sqlite3")
    _solution(repo, "solution-a")
    repo.add_lexical_group(
        group_id="source-null",
        solution_id="solution-a",
        cardinality=Cardinality.SOURCE_TO_NULL,
        source_layer=TokenLayer.MORPHEME,
        target_layer=None,
        source_token_ids=("s1",),
        target_token_ids=(),
    )
    with pytest.raises(FoundationValidationError, match="absent target layer"):
        repo.add_lexical_group(
            group_id="bad-null",
            solution_id="solution-a",
            cardinality=Cardinality.SOURCE_TO_NULL,
            source_layer=TokenLayer.MORPHEME,
            target_layer=TokenLayer.ORTHOGRAPHIC,
            source_token_ids=("s2",),
            target_token_ids=(),
        )


def test_active_membership_is_exclusive_within_a_layer(tmp_path: Path) -> None:
    repo = FoundationRepository(tmp_path / "semantic.sqlite3")
    _solution(repo, "solution-a")
    _token(repo, "s1", TokenSide.SOURCE, TokenLayer.ORTHOGRAPHIC)
    _token(repo, "t1", TokenSide.TARGET, TokenLayer.ORTHOGRAPHIC)
    _token(repo, "t2", TokenSide.TARGET, TokenLayer.ORTHOGRAPHIC)
    repo.add_lexical_group(
        group_id="g1", solution_id="solution-a", cardinality=Cardinality.ONE_TO_ONE,
        source_layer=TokenLayer.ORTHOGRAPHIC, target_layer=TokenLayer.ORTHOGRAPHIC,
        source_token_ids=("s1",), target_token_ids=("t1",),
    )
    repo.add_lexical_group(
        group_id="g2", solution_id="solution-a", cardinality=Cardinality.ONE_TO_ONE,
        source_layer=TokenLayer.ORTHOGRAPHIC, target_layer=TokenLayer.ORTHOGRAPHIC,
        source_token_ids=("s1",), target_token_ids=("t2",),
    )
    with pytest.raises(FoundationConflict, match="more than one active ORTHOGRAPHIC"):
        repo.activate_lexical_solution("solution-a", expected_revision=1, authoritative=True)


def test_parent_child_layers_require_explicit_refinement(tmp_path: Path) -> None:
    repo = FoundationRepository(tmp_path / "semantic.sqlite3")
    _solution(repo, "solution-a")
    _token(repo, "s-parent", TokenSide.SOURCE, TokenLayer.ORTHOGRAPHIC)
    _token(repo, "t-parent", TokenSide.TARGET, TokenLayer.ORTHOGRAPHIC)
    _token(repo, "s-child", TokenSide.SOURCE, TokenLayer.MORPHEME, parent_id="s-parent")
    _token(repo, "t-child", TokenSide.TARGET, TokenLayer.MORPHEME, parent_id="t-parent")
    repo.add_lexical_group(
        group_id="parent", solution_id="solution-a", cardinality=Cardinality.ONE_TO_ONE,
        source_layer=TokenLayer.ORTHOGRAPHIC, target_layer=TokenLayer.ORTHOGRAPHIC,
        source_token_ids=("s-parent",), target_token_ids=("t-parent",), alignment_family_id="family",
    )
    repo.add_lexical_group(
        group_id="child", solution_id="solution-a", cardinality=Cardinality.ONE_TO_ONE,
        source_layer=TokenLayer.MORPHEME, target_layer=TokenLayer.MORPHEME,
        source_token_ids=("s-child",), target_token_ids=("t-child",), alignment_family_id="family",
    )
    with pytest.raises(FoundationConflict, match="explicitly refine"):
        repo.activate_lexical_solution("solution-a", expected_revision=1, authoritative=True)


def test_parent_child_layers_allow_declared_refinement(tmp_path: Path) -> None:
    repo = FoundationRepository(tmp_path / "semantic.sqlite3")
    _solution(repo, "solution-a")
    _token(repo, "s-parent", TokenSide.SOURCE, TokenLayer.ORTHOGRAPHIC)
    _token(repo, "t-parent", TokenSide.TARGET, TokenLayer.ORTHOGRAPHIC)
    _token(repo, "s-child", TokenSide.SOURCE, TokenLayer.MORPHEME, parent_id="s-parent")
    _token(repo, "t-child", TokenSide.TARGET, TokenLayer.MORPHEME, parent_id="t-parent")
    repo.add_lexical_group(
        group_id="parent", solution_id="solution-a", cardinality=Cardinality.ONE_TO_ONE,
        source_layer=TokenLayer.ORTHOGRAPHIC, target_layer=TokenLayer.ORTHOGRAPHIC,
        source_token_ids=("s-parent",), target_token_ids=("t-parent",), alignment_family_id="family",
    )
    repo.add_lexical_group(
        group_id="child", solution_id="solution-a", cardinality=Cardinality.ONE_TO_ONE,
        source_layer=TokenLayer.MORPHEME, target_layer=TokenLayer.MORPHEME,
        source_token_ids=("s-child",), target_token_ids=("t-child",),
        alignment_family_id="family", refines_group_id="parent",
    )
    repo.activate_lexical_solution("solution-a", expected_revision=1, authoritative=True)
    assert repo.lexical_solution("solution-a")["lifecycleStatus"] == "ACTIVE"


def test_dependency_dag_rejects_cycle_but_semantic_graph_allows_cycle(tmp_path: Path) -> None:
    repo = FoundationRepository(tmp_path / "semantic.sqlite3")
    for unit_id in ("u1", "u2", "u3"):
        repo.create_minimal_semantic_unit(unit_id, project_id="project-1")
    repo.add_dependency("u1", "u2", "CONTAINS")
    repo.add_dependency("u2", "u3", "DEPENDS_ON")
    with pytest.raises(FoundationValidationError, match="cycle"):
        repo.add_dependency("u3", "u1", "DERIVED_FROM")
    repo.add_semantic_relation("u1", "u2", "COREFERS_WITH")
    repo.add_semantic_relation("u2", "u1", "COREFERS_WITH")


def test_semantic_units_relationship_and_coverage_account_persist(tmp_path: Path) -> None:
    repo = FoundationRepository(tmp_path / "semantic.sqlite3")
    _token(repo, "s1", TokenSide.SOURCE, TokenLayer.ORTHOGRAPHIC)
    _token(repo, "t1", TokenSide.TARGET, TokenLayer.ORTHOGRAPHIC)
    source = _unit("source-unit", TokenSide.SOURCE, "s1")
    target = _unit("target-unit", TokenSide.TARGET, "t1")
    repo.save_semantic_unit(source)
    repo.save_semantic_unit(target)
    confidence = ConfidenceScore(None, 0.9, "confidence-v1", "calibration-v1")
    relationship = SemanticRelationship(
        id="relationship-1", project_id="project-1", book="PHP",
        source_semantic_unit_ids=(source.id,), target_semantic_unit_ids=(target.id,), lexical_group_ids=(),
        realization=Realization.LEXICALLY_REALIZED, properties=(), location_confidence=confidence,
        meaning_status=MeaningStatus.PRESERVED, meaning_confidence=confidence,
        source_coverage=SourceCoverage.COVERED, target_support=TargetSupport.SOURCE_SUPPORTED,
        evidence_ids=(), policy_binding=PolicyBinding.foundation_v1(),
        review_status=ReviewStatus.AI_PROPOSED, lifecycle_status=LifecycleStatus.INACTIVE,
    )
    repo.save_semantic_relationship(relationship)
    account = SemanticCoverageAccount(
        id="account-1", project_id="project-1", passage_id="PHP 1:1",
        direction=AuditDirection.SOURCE_COVERAGE, audit_owner_unit_id=source.id,
        member_unit_ids=(source.id,), coverage_dimension=CoverageDimension.LEXICAL_CONTENT,
        semantic_fingerprint="account-fingerprint", covered_by_relationship_ids=(relationship.id,),
        excluded_duplicate_unit_ids=(), finding_id=None, policy_binding=PolicyBinding.foundation_v1(),
        review_status=ReviewStatus.UNREVIEWED, lifecycle_status=LifecycleStatus.ACTIVE,
    )
    repo.save_coverage_account(account)
    assert repo.semantic_unit(source.id)["side"] == "SOURCE"
    assert repo.semantic_relationship(relationship.id)["meaningStatus"] == "PRESERVED"


def test_passage_evidence_qa_exportability_and_review_round_trip(tmp_path: Path) -> None:
    repo = FoundationRepository(tmp_path / "semantic.sqlite3")
    policy = PolicyBinding.foundation_v1()
    target_text = {"PHP 1:3": "என் தேவனை"}
    passage = PassageRecord(
        id="passage-1", project_id="project-1", book="PHP",
        displayed_source_references=("PHP 1:3",), displayed_target_references=("PHP 1:3", "PHP 1:6"),
        canonical_references=("PHP 1:3", "PHP 1:6"), source_resource_id="UGNT",
        source_resource_version="v1", source_resource_hash="source-hash", target_revision="target-rev-1",
        target_content_hash=repo.target_content_hash(target_text), structure_resource_id="IRVTam-import",
        structure_resource_version="v1", structure_resource_hash="structure-hash",
        target_text_by_displayed_reference=target_text,
        structure_markers=(PassageStructureMarker(PassageStructureKind.PARAGRAPH, "p", "PHP 1:3", 0, 0, 0),),
        policy_binding=policy, lifecycle_status=LifecycleStatus.ACTIVE,
    )
    repo.save_passage_record(passage)
    assert repo.passage_record("passage-1")["targetTextByDisplayedReference"] == target_text

    _token(repo, "s1", TokenSide.SOURCE, TokenLayer.ORTHOGRAPHIC)
    _token(repo, "t1", TokenSide.TARGET, TokenLayer.ORTHOGRAPHIC)
    source = _unit("source-unit", TokenSide.SOURCE, "s1")
    target = _unit("target-unit", TokenSide.TARGET, "t1")
    repo.save_semantic_unit(source)
    repo.save_semantic_unit(target)
    content = "resource occurrence"
    evidence = EvidenceRecord(
        id="evidence-1", project_id="project-1", book="PHP", kind=EvidenceKind.TRANSLATION_NOTE,
        resource_id="tn", resource_version="v1", resource_hash="resource-hash", occurrence_id="tn-PHP-1-3-1",
        displayed_references=("PHP 1:3",), canonical_references=("PHP 1:3",), content=content,
        content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        validation_status=ResourceValidationStatus.SUPPORTING, source_semantic_unit_ids=(source.id,),
        target_semantic_unit_ids=(target.id,), policy_binding=policy, review_status=ReviewStatus.UNREVIEWED,
        lifecycle_status=LifecycleStatus.ACTIVE,
    )
    repo.save_evidence_record(evidence)
    assert repo.evidence_record("evidence-1")["occurrenceId"] == "tn-PHP-1-3-1"

    confidence = ConfidenceScore(None, 0.9, "confidence-v1", "calibration-v1")
    relationship = SemanticRelationship(
        id="relationship-1", project_id="project-1", book="PHP", source_semantic_unit_ids=(source.id,),
        target_semantic_unit_ids=(target.id,), lexical_group_ids=(), realization=Realization.LEXICALLY_REALIZED,
        properties=(RelationshipProperty.CROSS_VERSE,), location_confidence=confidence,
        meaning_status=MeaningStatus.PRESERVED, meaning_confidence=confidence,
        source_coverage=SourceCoverage.COVERED, target_support=TargetSupport.SOURCE_SUPPORTED,
        evidence_ids=(evidence.id,), policy_binding=policy, review_status=ReviewStatus.AI_PROPOSED,
        lifecycle_status=LifecycleStatus.INACTIVE,
    )
    repo.save_semantic_relationship(relationship)
    exportability = Exportability(
        id="export-1", relationship_id=relationship.id,
        format=ExportFormat.TRANSLATIONCORE_ALIGNED_USFM,
        level=ExportabilityLevel.NOT_REPRESENTABLE, reasons=(ExportReason.CROSS_VERSE,),
        policy_binding=policy, lifecycle_status=LifecycleStatus.ACTIVE,
    )
    repo.save_exportability(exportability)
    assert repo.exportability("export-1")["level"] == "NOT_REPRESENTABLE"

    finding = QaFinding(
        id="qa-rich", project_id="project-1", book="PHP", passage_id=passage.id,
        kind=QaFindingKind.NEEDS_PASSAGE_REVIEW, direction=AuditDirection.SOURCE_COVERAGE,
        source_semantic_unit_ids=(source.id,), target_semantic_unit_ids=(target.id,),
        semantic_relationship_ids=(relationship.id,), evidence_ids=(evidence.id,), explanation="Review passage",
        confidence=confidence, current_target_revision=passage.target_revision,
        qa_disposition=QaDisposition.UNRESOLVED, policy_binding=policy,
        review_status=ReviewStatus.UNREVIEWED, lifecycle_status=LifecycleStatus.ACTIVE,
    )
    repo.save_qa_finding(finding)
    repo.update_qa_disposition("qa-rich", QaDisposition.NEEDS_DISCUSSION, 1, "Reviewer")
    reviews = repo.review_records("QA_FINDING", "qa-rich")
    assert reviews[0]["newQaDisposition"] == "NEEDS_DISCUSSION"


def test_qa_disposition_is_independent_and_round_trips(tmp_path: Path) -> None:
    repo = FoundationRepository(tmp_path / "semantic.sqlite3")
    repo.create_qa_finding("qa-1", "project-1")
    repo.update_qa_disposition(
        "qa-1", QaDisposition.ACCEPTABLE_TRANSLATION, expected_revision=1, reviewer="Reviewer"
    )
    finding = repo.qa_finding("qa-1")
    assert finding["qaDisposition"] == "ACCEPTABLE_TRANSLATION"
    assert finding["reviewStatus"] == "HUMAN_APPROVED"
    assert finding["lifecycleStatus"] == "ACTIVE"


def test_correction_application_requires_human_and_stales_dependencies(tmp_path: Path) -> None:
    repo = FoundationRepository(tmp_path / "semantic.sqlite3")
    repo.create_qa_finding("qa-1", "project-1")
    proposal = CorrectionProposal.example("proposal-1", "qa-1")
    repo.save_correction_proposal(proposal)
    _solution(repo, "solution-dependent")
    repo.add_record_dependency(
        "LEXICAL_SOLUTION", "solution-dependent", "CORRECTION_PROPOSAL", "proposal-1"
    )
    with pytest.raises(FoundationValidationError, match="explicit human action"):
        repo.record_correction_applied(
            "proposal-1", actor_type="SYSTEM", applied_target_revision="rev-2", expected_revision=1
        )
    repo.record_correction_applied(
        "proposal-1", actor_type="HUMAN", applied_target_revision="rev-2", expected_revision=1
    )
    assert repo.correction_proposal("proposal-1")["appliedTargetRevision"] == "rev-2"
    assert repo.qa_finding("qa-1")["lifecycleStatus"] == "STALE"
    assert repo.qa_finding("qa-1")["reviewStatus"] == "HUMAN_APPROVED"
    assert repo.lexical_solution("solution-dependent")["lifecycleStatus"] == "STALE"


def test_revision_cas_rejects_stale_write(tmp_path: Path) -> None:
    repo = FoundationRepository(tmp_path / "semantic.sqlite3")
    repo.create_qa_finding("qa-1", "project-1")
    repo.update_qa_disposition("qa-1", QaDisposition.NEEDS_DISCUSSION, 1, "Reviewer")
    with pytest.raises(FoundationConflict, match="revision"):
        repo.update_qa_disposition("qa-1", QaDisposition.FALSE_POSITIVE, 1, "Reviewer")


def test_backup_restore_and_recovery_check(tmp_path: Path) -> None:
    db = tmp_path / "semantic.sqlite3"
    repo = FoundationRepository(db)
    repo.create_qa_finding("qa-1", "project-1")
    backup = repo.backup(tmp_path / "backups", reason="test")
    repo.update_qa_disposition("qa-1", QaDisposition.CORRECTED, 1, "Reviewer")
    repo.restore(backup)
    assert repo.qa_finding("qa-1")["qaDisposition"] == "UNRESOLVED"
    assert repo.recovery_check()["ok"] is True


def test_recovery_failure_enters_read_only_mode(tmp_path: Path) -> None:
    import sqlite3

    repo = FoundationRepository(tmp_path / "semantic.sqlite3")
    _solution(repo, "solution-a")
    _token(repo, "s1", TokenSide.SOURCE, TokenLayer.ORTHOGRAPHIC)
    _token(repo, "t1", TokenSide.TARGET, TokenLayer.ORTHOGRAPHIC)
    repo.add_lexical_group(
        group_id="g1", solution_id="solution-a", cardinality=Cardinality.ONE_TO_ONE,
        source_layer=TokenLayer.ORTHOGRAPHIC, target_layer=TokenLayer.ORTHOGRAPHIC,
        source_token_ids=("s1",), target_token_ids=("t1",),
    )
    repo.activate_lexical_solution("solution-a", expected_revision=1, authoritative=True)
    with sqlite3.connect(tmp_path / "semantic.sqlite3") as conn:
        conn.execute("UPDATE lexical_groups SET lifecycle_status='INACTIVE' WHERE id='g1'")
    result = repo.recovery_check()
    assert result["ok"] is False
    assert result["readOnly"] is True


@pytest.mark.parametrize("fixture", json.loads((ROOT / "schemas" / "fixtures" / "unicode-spans-v1.json").read_text(encoding="utf-8")))
def test_unicode_coordinate_fixture(fixture: dict[str, object]) -> None:
    text = str(fixture["text"])
    start = int(fixture["startCodePoint"])
    end = int(fixture["endCodePoint"])
    quote = str(fixture["quote"])
    assert codepoint_span(text, start, end) == quote
    validate_codepoint_span(text, start, end, quote)
    utf8 = codepoint_to_utf8_offset(text, start)
    utf16 = codepoint_to_utf16_offset(text, start)
    assert utf8_to_codepoint_offset(text, utf8) == start
    assert utf16_to_codepoint_offset(text, utf16) == start


def test_canonical_schema_declares_mandatory_amendments() -> None:
    schema = json.loads((ROOT / "schemas" / "bridge-passage-semantic-v1.schema.json").read_text(encoding="utf-8"))
    defs = schema["$defs"]
    assert schema["$id"] == SCHEMA_ID
    assert defs["LifecycleStatus"]["enum"] == ["ACTIVE", "INACTIVE", "STALE", "SUPERSEDED", "QUARANTINED"]
    assert "CONFIRMED_TRANSLATION_ERROR" in defs["QaDisposition"]["enum"]
    assert "CorrectionProposal" in defs
    assert "SourceSemanticUnit" in defs
    assert "TargetSemanticUnit" in defs


def test_python_and_typescript_controlled_enums_match_canonical_schema() -> None:
    schema = json.loads((ROOT / "schemas" / "bridge-passage-semantic-v1.schema.json").read_text(encoding="utf-8"))
    defs = schema["$defs"]
    enum_types = {
        "ReviewStatus": ReviewStatus,
        "LifecycleStatus": LifecycleStatus,
        "QaDisposition": QaDisposition,
        "TokenLayer": TokenLayer,
        "Cardinality": Cardinality,
        "SemanticUnitKind": SemanticUnitKind,
        "DependencyRelation": DependencyRelation,
        "SemanticRelation": SemanticRelation,
        "AuditEligibility": AuditEligibility,
        "SemanticObligationStrength": SemanticObligationStrength,
        "CoverageAccountingRole": CoverageAccountingRole,
        "CoverageDimension": CoverageDimension,
        "AuditDirection": AuditDirection,
        "ActorType": ActorType,
        "ResourceValidationStatus": ResourceValidationStatus,
        "EvidenceKind": EvidenceKind,
        "QaFindingKind": QaFindingKind,
        "PassageStructureKind": PassageStructureKind,
        "ExportFormat": ExportFormat,
        "ExportabilityLevel": ExportabilityLevel,
        "ExportReason": ExportReason,
        "Realization": Realization,
        "RelationshipProperty": RelationshipProperty,
        "MeaningStatus": MeaningStatus,
        "SourceCoverage": SourceCoverage,
        "TargetSupport": TargetSupport,
    }
    ts = (ROOT / "src" / "lib" / "types" / "passageSemanticV1.ts").read_text(encoding="utf-8")
    for schema_name, enum_type in enum_types.items():
        expected = defs[schema_name]["enum"]
        assert [member.value for member in enum_type] == expected
        for value in expected:
            assert f'"{value}"' in ts


def test_python_record_fields_match_canonical_schema() -> None:
    schema = json.loads((ROOT / "schemas" / "bridge-passage-semantic-v1.schema.json").read_text(encoding="utf-8"))
    defs = schema["$defs"]
    model_types = {
        "PolicyBinding": PolicyBinding, "ConfidenceScore": ConfidenceScore, "CharacterSpan": CharacterSpan,
        "TokenLineage": TokenLineage, "TokenInstance": TokenInstance,
        "SemanticUnitBase": SemanticUnit, "SemanticUnitDependency": SemanticUnitDependency,
        "SemanticUnitRelationEdge": SemanticUnitRelationEdge,
        "SemanticRelationship": SemanticRelationship,
        "SemanticCoverageAccount": SemanticCoverageAccount, "PassageStructureMarker": PassageStructureMarker,
        "PassageRecord": PassageRecord, "EvidenceRecord": EvidenceRecord,
        "LexicalSolution": LexicalSolution, "LexicalAlignmentGroup": LexicalAlignmentGroup,
        "QaFinding": QaFinding, "CorrectionProposal": CorrectionProposal, "ReviewRecord": ReviewRecord,
        "Exportability": Exportability,
    }

    def camel(name: str) -> str:
        head, *tail = name.split("_")
        return head + "".join(part[:1].upper() + part[1:] for part in tail)

    for definition, model_type in model_types.items():
        assert {camel(item.name) for item in fields(model_type)} == set(defs[definition]["required"])


def test_migration_is_idempotent_and_preserves_unrelated_legacy_table(tmp_path: Path) -> None:
    import sqlite3

    db = tmp_path / "semantic.sqlite3"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE legacy_marker(value TEXT NOT NULL)")
        conn.execute("INSERT INTO legacy_marker VALUES('preserve-me')")
    first = FoundationRepository(db)
    second = FoundationRepository(db)
    assert first.schema_version() == second.schema_version() == DATABASE_SCHEMA_VERSION
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT value FROM legacy_marker").fetchone()[0] == "preserve-me"


def test_v1_database_upgrade_creates_automatic_pre_migration_backup(tmp_path: Path) -> None:
    import sqlite3

    db = tmp_path / "passageSemantic" / "bridge-semantic.sqlite3"
    db.parent.mkdir(parents=True)
    with sqlite3.connect(db) as conn:
        conn.executescript(_MIGRATION_V1)
        conn.execute(
            "CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, schema_id TEXT NOT NULL, applied_at TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO schema_migrations VALUES(1,?,?)",
            (SCHEMA_ID, "2026-09-01T00:00:00+00:00"),
        )
        conn.execute("PRAGMA user_version = 1")

    repo = FoundationRepository(db)
    assert repo.schema_version() == DATABASE_SCHEMA_VERSION
    backups = list((db.parent / "backups").glob("pre-schema-v2-*/backup-manifest.json"))
    assert len(backups) == 1
    manifest = json.loads(backups[0].read_text(encoding="utf-8"))
    assert manifest["databaseSchemaVersion"] == 1
    assert manifest["targetDatabaseSchemaVersion"] == 2
    repo.create_qa_finding("post-upgrade-only", "project-1")
    repo.restore(backups[0].parent)
    assert repo.schema_version() == DATABASE_SCHEMA_VERSION
    with pytest.raises(FoundationValidationError, match="Unknown QA finding"):
        repo.qa_finding("post-upgrade-only")


def test_ambiguous_legacy_alignment_can_be_quarantined_without_mutation(tmp_path: Path) -> None:
    repo = FoundationRepository(tmp_path / "semantic.sqlite3")
    original = {"topWords": [{"word": "θεῷ"}], "bottomWords": []}
    quarantine_id = repo.quarantine_migration_record(
        source_kind="TRANSLATIONCORE_ALIGNMENT_GROUP", source_identity="PHP 1:3/group-1",
        reason_code="LEGACY_EMPTY_BOTTOM_WORDS_AMBIGUOUS", payload=original,
    )
    records = repo.migration_quarantine_records()
    assert records == [{
        "id": quarantine_id, "sourceKind": "TRANSLATIONCORE_ALIGNMENT_GROUP",
        "sourceIdentity": "PHP 1:3/group-1", "reasonCode": "LEGACY_EMPTY_BOTTOM_WORDS_AMBIGUOUS",
        "payload": original, "createdAt": records[0]["createdAt"],
    }]
