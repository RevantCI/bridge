"""Seed the three Stage 9B.4 installed-acceptance projects (A / B / C).

Run this from the repository, then open the printed folders in the installed
Bridge and follow ``docs/STAGE_9B4_ACCEPTANCE.md``.

What each case is, stated plainly, because the difference matters:

A  PASSED      **Controlled verification fixture.**  The application, the
               affected-analysis job and the current Stage 6A/6B/7/8 evidence
               are published directly, so the verifier meets positive evidence
               that the original obligation is satisfied.  This is *not*
               production end-to-end: see case C for why a real run cannot
               reach PASSED today.
B  FAILED      **Controlled verification fixture.**  Same shape, but the
               current evidence positively contradicts the source obligation
               on the dimension the correction targeted.
C  UNCERTAIN   **Real production flow.**  A genuine Stage 5 -> 6A -> 6B -> 7 ->
               8 run whose finding the tester confirms, corrects, applies,
               re-analyses and verifies through the app.  It reaches UNCERTAIN
               rather than PASSED because Bridge ships no production
               multilingual embedding provider, so Stage 6B cannot re-locate a
               cross-language obligation after the edit.  The verifier says so
               itself with PROVIDER_LIMITED.  That is the correct verdict, not
               a defect, and your acceptance spec lists provider limitation as
               an acceptable UNCERTAIN cause.

A and B deliberately reuse the Stage 9B.4 unit tests' own controlled-evidence
builders rather than copying them, so the fixtures and the tests cannot drift
apart.

    python scripts/seed_correction_acceptance.py [destination]

The generated projects are disposable: delete the destination to remove them.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine"))
sys.path.insert(0, str(ROOT / "scripts"))

from tc_ai_bridge.analysis_jobs import AnalysisJobManager  # noqa: E402
from tc_ai_bridge.passage_semantic_runtime import PassageSemanticRuntime  # noqa: E402
from tc_ai_bridge.project_registry import ProjectRegistry  # noqa: E402
from tc_ai_bridge.semantic_location import SemanticLocationEngine  # noqa: E402
from tc_ai_bridge.tc_project import TranslationCoreProject  # noqa: E402

from seed_review_fixture import FixtureEmbeddingProvider  # noqa: E402

from tests.test_correction_stage9b3b import _apply, _fixture  # noqa: E402
from tests.test_correction_stage9b4 import (  # noqa: E402
    BEFORE,
    ORIGINAL_SPAN,
    _analysis_job,
    _publish_evidence,
    _set_dimension,
)


# --- Case C: the real pipeline ----------------------------------------------
#
# English target on purpose.  The deterministic Stage 7 comparator recognises
# Greek and English quantity forms, so "some" against πᾶς is a real
# CONTRADICTED quantity component rather than anything language-specific, and
# the open Tamil normalization defect cannot decide the result.
#
# The Greek quantifier is realized in PHP 1:6 while its source obligation sits
# in PHP 1:3 -- the canonical cross-verse shape the acceptance asks for.
PRODUCTION_VERSES = {
    "3": "i thank my god,",
    "4": "always in every prayer of mine making my prayer with joy,",
    "5": "because of your partnership in the gospel from the first day until now,",
    "6": "some remembrance of you remains with me and he who began a good work will carry it on.",
}
BROKEN_WORD, CORRECTED_WORD = "some", "all"


def _configure_console_output() -> None:
    """Make the Unicode fixture summary printable from Windows PowerShell.

    Python uses the active Windows code page when stdout is redirected through
    a pipe.  On the common cp1252 code page, printing the Tamil corrected verse
    raised ``UnicodeEncodeError`` after all three projects had been seeded.
    UTF-8 keeps the useful human-readable summary and ``backslashreplace`` is a
    last-resort guard for unusual stream implementations.
    """
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding="utf-8", errors="backslashreplace")


def _write_identity(root: Path, project_id: str) -> None:
    """Mint the identity Bridge will reuse when it opens this folder.

    The companion database is bound to a project id and Bridge refuses to open
    one bound to a different identity, so the seeded results would be rejected
    if the app minted a fresh id on first open.
    """
    identity = root / ".bridge" / "project.json"
    identity.parent.mkdir(parents=True, exist_ok=True)
    identity.write_text(json.dumps({
        "schemaVersion": 1, "projectId": project_id, "collectionId": "",
        "sourceFingerprint": "stage9b4-acceptance-fixture",
        "createdAt": "2026-09-08T00:00:00Z",
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_production_project(root: Path) -> Path:
    (root / "php").mkdir(parents=True)
    alignment = root / ".apps" / "translationCore" / "alignmentData" / "php"
    alignment.mkdir(parents=True)
    (root / "manifest.json").write_text(json.dumps({
        "project": {"id": "php", "name": "Philippians"},
        "target_language": {"id": "en", "name": "English", "direction": "ltr"},
        "resource": {"id": "acceptance"}, "tc_version": "8",
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (root / "php" / "1.json").write_text(
        json.dumps(PRODUCTION_VERSES, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (alignment / "1.json").write_text(json.dumps(
        {reference: {"alignments": [], "wordBank": []} for reference in PRODUCTION_VERSES},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["\\id PHP", "\\c 1", "\\p"]
    lines.extend(f"\\v {verse} {text}" for verse, text in PRODUCTION_VERSES.items())
    (root / "php.usfm").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return root


def _register(root: Path) -> str:
    scratch = root.parent / f"{root.name}-seed-registry.json"
    registry = ProjectRegistry(scratch, root.parent / "managed")
    registered = registry.register(root, touch=True)
    scratch.unlink(missing_ok=True)
    return str(registered["projectId"])


def seed_case_c(root: Path) -> dict[str, object]:
    """Run the real Stage 5-8 pipeline and stop, leaving the finding UNRESOLVED."""
    build_production_project(root)
    project_id = _register(root)
    runtime = PassageSemanticRuntime(TranslationCoreProject(root), project_id)
    # One shared axis for the Greek quantifier and both the broken and the
    # corrected target word, so retrieval can reach whichever is on disk.
    vectors = {"πᾶς": [1.0], BROKEN_WORD: [1.0], CORRECTED_WORD: [1.0]}
    runtime.semantic_location = SemanticLocationEngine(
        runtime, FixtureEmbeddingProvider(vectors))
    manager = AnalysisJobManager(allow_fixture_provider=True)
    started = manager.start(runtime, requested_scope={
        "kind": "SELECTED_RANGE", "startChapter": "1", "startVerse": "3",
        "endChapter": "1", "endVerse": "6",
    })
    budget = float(os.environ.get("BRIDGE_FIXTURE_ANALYSIS_TIMEOUT", "300"))
    deadline = time.monotonic() + budget
    job = manager.status(started["jobId"])
    while time.monotonic() < deadline:
        job = manager.status(started["jobId"])
        if job["overallStatus"] in {
            "COMPLETED", "COMPLETED_WITH_WARNINGS", "FAILED", "CANCELLED",
        }:
            break
        time.sleep(0.02)
    if job["overallStatus"] not in {"COMPLETED", "COMPLETED_WITH_WARNINGS"}:
        raise SystemExit(f"Case C analysis failed: {job['failures']}")

    audit = runtime.qa_audit.get_range(job["stageStatuses"]["QA"]["runId"])
    chosen = [
        finding for finding in audit["findings"]
        if finding["kind"] == "QUANTITY_PROBLEM"
        and finding["displayedReferences"] == ["PHP 1:3", "PHP 1:6"]
    ]
    if not chosen:
        raise SystemExit(
            "Case C did not emit the expected cross-verse QUANTITY_PROBLEM; got "
            + ", ".join(f"{f['kind']}{f['displayedReferences']}" for f in audit["findings"])
        )
    finding = chosen[0]
    _write_identity(root, project_id)
    return {
        "case": "C",
        "kind": "production",
        "projectId": project_id,
        "findingId": finding["id"],
        "findingKind": finding["kind"],
        "sourceReference": "PHP 1:3",
        "targetReference": "PHP 1:6",
        "brokenWord": BROKEN_WORD,
        "correctedWord": CORRECTED_WORD,
        "qaRun": audit["id"],
        "analysisJob": job["jobId"],
        "findings": len(audit["findings"]),
    }


# --- Cases A and B: controlled verification fixtures ------------------------

def _seed_controlled(
    root: Path, project_id: str, *, application_id: str, evidence: dict[str, object],
    dimension: str | None = None,
) -> dict[str, object]:
    """Apply a correction and publish controlled current evidence for it."""
    parent = root.parent
    _root, _project, runtime, application_service, finding, proposal = _fixture(
        parent, BEFORE, ORIGINAL_SPAN, "என் தேவனையே",
        project_root=root, project_id=project_id,
    )
    application = _apply(application_service, application_id=application_id)
    if application["applicationState"] != "COMPLETED":
        raise SystemExit(f"{root.name}: application did not complete: {application}")
    if dimension:
        _set_dimension(runtime, dimension)
    corrected = str(runtime.project.target_verse_text("1", "6"))
    runs = _publish_evidence(runtime, verse_text=corrected, **evidence)
    job = _analysis_job(runtime, application, runs)
    _write_identity(root, project_id)
    return {
        "projectId": project_id,
        "findingId": finding["id"],
        "proposalId": proposal.id,
        "applicationId": application["applicationId"],
        "analysisJobId": job["jobId"],
        "sourceReference": "PHP 1:3",
        "targetReference": "PHP 1:6",
        "correctedVerse": corrected,
    }


def seed_case_a(root: Path) -> dict[str, object]:
    """Controlled PASSED: current evidence positively satisfies the obligation."""
    summary = _seed_controlled(
        root, "acceptance-a-passed", application_id="acceptance-a-apply",
        evidence={
            "source_text": "τῷ θεῷ μου", "target_text": "என் தேவனையே",
            "component_status": "PRESERVED", "coverage_status": "COVERED",
        },
    )
    summary.update({"case": "A", "kind": "controlled", "expectedVerification": "PASSED"})
    return summary


def seed_case_b(root: Path) -> dict[str, object]:
    """Controlled FAILED: positive contradiction, not mere absence."""
    summary = _seed_controlled(
        root, "acceptance-b-failed", application_id="acceptance-b-apply",
        dimension="QUANTITY",
        evidence={
            "source_text": "all", "target_text": "some",
            "component_status": "CONTRADICTED", "component_dimension": "QUANTITY",
            "source_dimension": "QUANTITY",
            "component_evidence_kind": "DETERMINISTIC_CONTRADICTION",
            "meaning_status": "CONTRADICTED", "coverage_status": "UNCERTAIN",
        },
    )
    summary.update({"case": "B", "kind": "controlled", "expectedVerification": "FAILED"})
    return summary


def main() -> int:
    _configure_console_output()
    destination = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd() / "acceptance-0.9.4"
    destination = destination.resolve()
    if destination.exists():
        raise SystemExit(
            f"{destination} already exists. Delete it first, or pass another destination."
        )
    destination.mkdir(parents=True)

    cases = [
        ("A-passed-controlled", seed_case_a),
        ("B-failed-controlled", seed_case_b),
        ("C-uncertain-production", seed_case_c),
    ]
    summaries = []
    for name, seed in cases:
        root = destination / name
        print(f"seeding {name} ...", flush=True)
        summary = seed(root)
        summary["projectPath"] = str(root)
        summaries.append(summary)

    manifest = destination / "acceptance-manifest.json"
    manifest.write_text(
        json.dumps(summaries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print()
    for summary in summaries:
        print(f"[{summary['case']}] {summary['kind']}  {summary['projectPath']}")
        for key in sorted(summary):
            if key in {"case", "kind", "projectPath"}:
                continue
            print(f"    {key}: {summary[key]}")
        print()
    print(f"manifest: {manifest}")
    print("Follow docs/STAGE_9B4_ACCEPTANCE.md for the click-by-click script.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
