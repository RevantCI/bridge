"""Stage 9B.3b strict explicit-human correction application tests."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tc_ai_bridge.correction_application import CorrectionApplicationService
from tc_ai_bridge.passage_semantic_models import (
    AffectedTargetSpan, CorrectionCreationMode, CorrectionIntent,
    CorrectionProposalV2, CoverageDimension, LifecycleStatus, PolicyBinding,
    ReviewStatus,
)
from tc_ai_bridge.passage_semantic_repository import FoundationConflict, FoundationValidationError
from tc_ai_bridge.passage_semantic_runtime import PassageSemanticRuntime
from tc_ai_bridge.tc_project import TranslationCoreProject


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _fixture(tmp_path: Path, before: str, original: str, replacement: str):
    root = tmp_path / "project"
    alignment = root / ".apps" / "translationCore" / "alignmentData" / "php"
    alignment.mkdir(parents=True)
    (root / "php").mkdir(parents=True)
    (root / "manifest.json").write_text(json.dumps({
        "project": {"id": "php", "name": "Philippians"},
        "target_language": {"id": "tam", "name": "Tamil"},
        "resource": {"id": "irv", "name": "IRVTam"}, "tc_version": "8",
    }), encoding="utf-8")
    (root / "php" / "1.json").write_text(
        json.dumps({"3": "unchanged source-corresponding target", "6": before}, ensure_ascii=False),
        encoding="utf-8",
    )
    (alignment / "1.json").write_text(json.dumps({
        "3": {"alignments": [], "wordBank": []},
        "6": {"alignments": [], "wordBank": []},
    }), encoding="utf-8")
    (root / "php.usfm").write_text("\\id PHP\n\\c 1\n\\v 3 IMPORTED THREE\n\\v 6 IMPORTED SIX\n", encoding="utf-8")
    project = TranslationCoreProject(root)
    runtime = PassageSemanticRuntime(project, "project-1")
    project.attach_passage_semantic_runtime(runtime)
    repo = runtime.repository
    repo.create_qa_finding("finding-1", "project-1")
    finding = repo.qa_finding("finding-1")
    finding.update({
        "book": "PHP", "displayedReferences": ["PHP 1:6"],
        "targetContentHashes": [_hash(before)],
        "qaDisposition": "CONFIRMED_TRANSLATION_ERROR",
        "reviewStatus": "HUMAN_APPROVED", "lifecycleStatus": "ACTIVE",
    })
    with repo._connect() as conn:
        conn.execute(
            "UPDATE qa_findings SET qa_disposition='CONFIRMED_TRANSLATION_ERROR',"
            "review_status='HUMAN_APPROVED',lifecycle_status='ACTIVE',payload_json=? WHERE id='finding-1'",
            (json.dumps(finding, ensure_ascii=False),),
        )
        conn.commit()
    current = repo.current_target_revision("project-1", "PHP", "PHP 1:6")
    start = before.index(original)
    proposal = CorrectionProposalV2(
        id="proposal-1", qa_finding_id="finding-1", project_id="project-1",
        intent=CorrectionIntent(
            failed_dimension=CoverageDimension.LEXICAL_CONTENT,
            observed_meaning="missing", required_meaning="required",
            affected_source_semantic_unit_ids=(),
            affected_target_span=AffectedTargetSpan(
                displayed_reference="PHP 1:6", canonical_references=("PHP 1:6",),
                start_code_point=start, end_code_point=start + len(original),
                original_text=original, target_text_revision=current["textRevision"],
                target_content_hash=_hash(before),
            ),
        ),
        affected_references=("PHP 1:3", "PHP 1:6"), current_text=original,
        proposed_text=replacement, explanation="reviewed correction", evidence_ids=(),
        semantic_relationship_ids=(), meaning_assessment_ids=(), created_by="Reviewer",
        created_at="2026-09-05T00:00:00Z",
        creation_mode=CorrectionCreationMode.HUMAN_AUTHORED,
        policy_binding=PolicyBinding.foundation_v1(),
        review_status=ReviewStatus.HUMAN_MODIFIED,
        lifecycle_status=LifecycleStatus.ACTIVE,
    )
    repo.save_correction_proposal_v2(proposal)
    service = CorrectionApplicationService(
        runtime,
        lambda chapter, verse, text, **options: project.apply_scripture_edit(
            chapter, verse, text, **options,
        ),
    )
    return root, project, runtime, service, finding, proposal


def _apply(service, finding_revision=1, proposal_revision=1, application_id="apply-1"):
    return service.apply(
        proposal_id="proposal-1", expected_proposal_revision=proposal_revision,
        finding_id="finding-1", expected_finding_revision=finding_revision,
        application_id=application_id,
        actor={"actorType": "HUMAN", "actorId": "Reviewer"},
    )


@pytest.mark.parametrize("before,original,replacement", [
    ("முன் என் தேவனை பின்", "என் தேவனை", "என்னுடைய தேவனை"),
    ("אָבִ֑י שָׁלוֹם סוף", "שָׁלוֹם", "שָׁלוֹם־לְךָ"),
    ("ἀρχή λόγος τέλος", "λόγος", "λόγος"),
    ("left 😀 right", "😀", "𐐷"),
    ("prefix suffix", "", "insert "),
    ("prefix delete suffix", "delete ", ""),
])
def test_exact_unicode_replacement_insertion_and_deletion(
    tmp_path: Path, before: str, original: str, replacement: str,
) -> None:
    root, project, runtime, service, finding, proposal = _fixture(
        tmp_path, before, original, replacement,
    )
    result = _apply(service)
    span = proposal.intent.affected_target_span
    expected = before[:span.start_code_point] + replacement + before[span.end_code_point:]
    assert result["applicationState"] == "COMPLETED"
    assert project.target_verse_text("1", "6") == expected
    assert project.target_verse_text("1", "3") == "unchanged source-corresponding target"
    assert (root / "php.usfm").read_text(encoding="utf-8").endswith("\\v 6 IMPORTED SIX\n")
    assert (root / ".apps" / "translationCore" / "alignmentData" / "php" / "1.json.invalid").exists() is False
    assert (root / ".apps" / "translationCore" / "tools" / "wordAlignment" / "invalid" / "1" / "6.json").exists()
    stored_finding = runtime.repository.qa_finding("finding-1")
    assert stored_finding["qaDisposition"] == "CONFIRMED_TRANSLATION_ERROR"
    assert stored_finding["lifecycleStatus"] == "STALE"
    assert runtime.repository.correction_proposal("proposal-1")["verificationStatus"] == "PENDING"
    assert result["resultMetadata"]["affectedAnalysisStarted"] is False


def test_duplicate_apply_is_idempotent_and_never_inserts_twice(tmp_path: Path) -> None:
    _root, project, _runtime, service, _finding, _proposal = _fixture(
        tmp_path, "before after", "", "NEW ",
    )
    first = _apply(service)
    second = _apply(service, application_id="different-retry-id")
    assert second["applicationId"] == first["applicationId"]
    assert project.target_verse_text("1", "6") == "NEW before after"


def test_external_edit_causes_revision_conflict_without_relocation(tmp_path: Path) -> None:
    _root, project, _runtime, service, _finding, _proposal = _fixture(
        tmp_path, "same token suffix", "same", "reviewed",
    )
    project.apply_scripture_edit("1", "6", "external token suffix")
    with pytest.raises((FoundationConflict, FoundationValidationError), match="changed|REVISION_CONFLICT"):
        _apply(service)
    assert project.target_verse_text("1", "6") == "external token suffix"


def test_unreviewed_proposal_is_not_applicable(tmp_path: Path) -> None:
    _root, project, runtime, service, _finding, _proposal = _fixture(
        tmp_path, "before", "before", "after",
    )
    with runtime.repository._connect() as conn:
        payload = runtime.repository.correction_proposal("proposal-1")
        payload["reviewStatus"] = "AI_PROPOSED"
        conn.execute(
            "UPDATE correction_proposals SET review_status='AI_PROPOSED',payload_json=? WHERE id='proposal-1'",
            (json.dumps(payload, ensure_ascii=False),),
        )
        conn.commit()
    with pytest.raises(FoundationValidationError, match="reviewed by a human"):
        _apply(service)
    assert project.target_verse_text("1", "6") == "before"
