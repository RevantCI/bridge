"""Real Stage 9B.4 Case C correction and affected-analysis regression."""
from __future__ import annotations

from pathlib import Path
import sys
import time

import tc_ai_bridge.source_semantic_inventory as inventory_module

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.seed_correction_acceptance import (
    BROKEN_WORD,
    CORRECTED_WORD,
    PRODUCTION_VERSES,
    seed_case_c,
)
from tc_ai_bridge.analysis_jobs import AnalysisJobManager
from tc_ai_bridge.correction_affected_analysis import CorrectionAffectedAnalysisService
from tc_ai_bridge.correction_application import CorrectionApplicationService
from tc_ai_bridge.passage_semantic_models import (
    AffectedTargetSpan,
    CorrectionIntent,
    CoverageDimension,
)
from tc_ai_bridge.passage_semantic_runtime import PassageSemanticRuntime
from tc_ai_bridge.tc_project import TranslationCoreProject


def _wait(manager: AnalysisJobManager, job_id: str) -> dict:
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        job = manager.status(job_id)
        if job["overallStatus"] in {
            "COMPLETED", "COMPLETED_WITH_WARNINGS", "FAILED", "CANCELLED",
        }:
            return job
        time.sleep(0.02)
    raise AssertionError(f"analysis job did not finish: {job_id}")


def test_real_case_c_survives_help_resource_revision_and_affected_reanalysis(
    tmp_path: Path, monkeypatch,
) -> None:
    """Stage 5→8 → confirm/propose/apply → affected Stage 5→8 stays valid."""
    root = tmp_path / "case-c"
    seeded = seed_case_c(root)
    project = TranslationCoreProject(root)
    runtime = PassageSemanticRuntime(project, str(seeded["projectId"]))
    project.attach_passage_semantic_runtime(runtime)

    finding = runtime.repository.qa_finding(str(seeded["findingId"]))
    decided = runtime.qa_review_decide(
        finding["id"], "CONFIRMED_TRANSLATION_ERROR",
        expected_revision=int(finding["revision"]),
        expected_target_content_hashes=tuple(finding["targetContentHashes"]),
        note="Installed Case C regression confirmation.",
    )["finding"]
    context = runtime.correction_get_review_context(finding["id"])
    span = next(
        item for item in context["candidateSpans"]
        if item["displayedReference"] == "PHP 1:6"
        and item["originalText"] == BROKEN_WORD
    )
    intent = CorrectionIntent(
        failed_dimension=CoverageDimension.QUANTITY,
        observed_meaning="the target says some",
        required_meaning="the source requires all",
        affected_source_semantic_unit_ids=tuple(
            context["suggestedIntent"]["affectedSourceSemanticUnitIds"]
        ),
        affected_target_span=AffectedTargetSpan(
            displayed_reference=span["displayedReference"],
            canonical_references=tuple(span["canonicalReferences"]),
            start_code_point=int(span["startCodePoint"]),
            end_code_point=int(span["endCodePoint"]),
            original_text=span["originalText"],
            target_text_revision=span["targetTextRevision"],
            target_content_hash=span["targetContentHash"],
        ),
    )
    proposal = runtime.correction_create_proposal(
        finding_id=finding["id"], intent=intent,
        human_proposed_text=CORRECTED_WORD,
        explanation="Restore the source quantity.", actor_id="Reviewer",
    )
    reviewed = runtime.correction_edit_proposal(
        proposal["id"], proposed_text=CORRECTED_WORD,
        expected_revision=int(proposal["revision"]), actor_id="Reviewer",
        explanation="Human-reviewed Case C wording.",
    )
    application_service = CorrectionApplicationService(
        runtime,
        lambda chapter, verse, text, **options: project.apply_scripture_edit(
            chapter, verse, text, **options,
        ),
    )
    applied = application_service.apply(
        proposal_id=reviewed["id"],
        expected_proposal_revision=int(reviewed["revision"]),
        finding_id=finding["id"],
        expected_finding_revision=int(decided["revision"]),
        application_id="case-c-real-apply",
        actor={"actorType": "HUMAN", "actorId": "Reviewer"},
    )
    assert applied["applicationState"] == "COMPLETED"

    # Reproduce the installed blocker: the project was seeded against one
    # immutable tN/tW/TWL snapshot and is then opened with another.  Every
    # evidence ID changes because resource hashes are part of its identity.
    original_file_hash = inventory_module._file_hash

    def revised_file_hash(path: Path | None) -> str:
        value = original_file_hash(path)
        return value if path is None else f"installed-revision-{value}"

    monkeypatch.setattr(inventory_module, "_file_hash", revised_file_hash)
    manager = AnalysisJobManager()
    manager.bind_runtime(runtime)
    affected = CorrectionAffectedAnalysisService(runtime, manager)
    started = affected.start(applied["applicationId"], requested_by="Reviewer")
    completed = _wait(manager, started["analysisJobId"])

    assert completed["overallStatus"] in {"COMPLETED", "COMPLETED_WITH_WARNINGS"}
    assert completed["requestedScope"]["resolvedSourceReferences"] == ["PHP 1:3"]
    assert completed["requestedScope"]["resolvedTargetReferences"] == ["PHP 1:6"]
    assert completed["displayedReferences"] == [
        "PHP 1:3", "PHP 1:4", "PHP 1:5", "PHP 1:6",
    ]
    assert completed["stageStatuses"]["SOURCE_INVENTORY"]["status"] == "COMPLETED"
    for stage in ("TARGET_INVENTORY", "LOCATION", "MEANING", "QA"):
        assert completed["stageStatuses"][stage]["status"] in {"COMPLETED", "REUSED"}
    assert project.target_verse_text("1", "3") == PRODUCTION_VERSES["3"]
    assert project.target_verse_text("1", "6").startswith(f"{CORRECTED_WORD} remembrance")
    assert (
        root / ".apps" / "translationCore" / "tools" / "wordAlignment"
        / "invalid" / "1" / "6.json"
    ).is_file()
    attempts = runtime.repository.application_intent(applied["applicationId"])[
        "resultMetadata"
    ]["affectedAnalysisAttempts"]
    assert attempts[-1]["analysisJobId"] == completed["jobId"]
