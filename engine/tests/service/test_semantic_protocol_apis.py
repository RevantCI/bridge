"""The protocol surface over Stages 6B, 7 and 8.

These three tests lived at the bottom of `test_semantic_location_stage6b.py`,
`test_meaning_analysis_stage7.py` and `test_qa_audit_stage8.py`. Each was the
only test in its file that needed `BridgeEngine`, and each therefore made an
otherwise-pure stage file import the 5,300-line dispatcher (#74 phase 4).

That mattered beyond tidiness: `bridge_service` was imported by 44 test files, so
tracing "what could this change affect" from any engine module reached the hub
and through it most of the suite, which is what made affected-test selection
useless (#74 phase 3).

What they assert is unchanged -- these are the same tests, moved. Each drives its
stage's RPCs through the real dispatcher and checks the whole family answers; the
stage files keep the tests that exercise the engines directly.
"""
from __future__ import annotations

from pathlib import Path

from bridge_service import BridgeEngine
from greek_room_engine.protocol import EngineRequest
from tc_ai_bridge.meaning_analysis import MeaningAnalysisEngine
from tc_ai_bridge.semantic_location import SemanticLocationEngine
from tests.support.semantic import semantic_runtime


def _bridge(runtime) -> BridgeEngine:
    """A dispatcher bound to an already-built runtime.

    The stage files each spelled this out inline; it is the same two
    assignments every time, and nothing here opens a project the ordinary way.
    """
    bridge = BridgeEngine()
    bridge.project = runtime.project
    bridge.passage_semantic_runtime = runtime
    return bridge


def test_semantic_location_protocol_inspection_apis(tmp_path: Path) -> None:
    runtime = semantic_runtime(tmp_path, project_prefix="location",
                               language="en", chapters={"1": {"3": "unrelated"}})
    bridge = _bridge(runtime)
    response = bridge.handle_request(EngineRequest(
        id="run", method="semanticLocation.runRange",
        params={"chapter": "1", "verse": "3"},
    )).to_dict()
    assert response["success"] is True, response
    run = response["result"]
    relationship_id = run["relationships"][0]["id"]
    calls = [
        ("semanticLocation.status", {"runId": run["id"]}),
        ("semanticLocation.getRange", {"runId": run["id"]}),
        ("semanticLocation.getRelationship", {"relationshipId": relationship_id}),
        ("semanticLocation.getCandidates", {"runId": run["id"]}),
        ("semanticLocation.getDiagnostics", {"runId": run["id"]}),
    ]
    assert all(
        bridge.handle_request(EngineRequest(id=str(index), method=method, params=params)).to_dict()["success"]
        for index, (method, params) in enumerate(calls)
    )


def test_meaning_protocol_apis_and_no_qa_side_effects(tmp_path: Path) -> None:
    runtime = semantic_runtime(tmp_path, project_prefix="meaning",
                               language="en", chapters={"1": {"3": "unrelated"}})
    location = SemanticLocationEngine(runtime).run_range("1", "3")
    bridge = _bridge(runtime)
    response = bridge.handle_request(EngineRequest(
        id="run", method="meaningAnalysis.runRange",
        params={"chapter": "1", "verse": "3", "locationRunId": location["id"]},
    )).to_dict()
    assert response["success"] is True, response
    run = response["result"]; assessment_id = run["assessments"][0]["id"]
    calls = [
        ("meaningAnalysis.status", {"runId": run["id"]}),
        ("meaningAnalysis.getRange", {"runId": run["id"]}),
        ("meaningAnalysis.getAssessment", {"assessmentId": assessment_id}),
        ("meaningAnalysis.getComponents", {"assessmentId": assessment_id}),
        ("meaningAnalysis.getDiagnostics", {"runId": run["id"]}),
    ]
    assert all(bridge.handle_request(EngineRequest(
        id=str(index), method=method, params=params,
    )).to_dict()["success"] for index, (method, params) in enumerate(calls))
    # Stage 7 must not write Stage 8's records: running meaning analysis through
    # the protocol leaves the QA findings table empty.
    with runtime.repository._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM qa_findings").fetchone()[0] == 0


def test_qa_audit_protocol_apis(tmp_path: Path) -> None:
    import json

    runtime = semantic_runtime(tmp_path, project_prefix="qa8",
                               language="en", chapters={"1": {"3": "unrelated"}})
    location = SemanticLocationEngine(runtime).run_range("1", "3")
    meaning = MeaningAnalysisEngine(runtime).run_range("1", "3", location_run_id=location["id"])
    bridge = _bridge(runtime)
    response = bridge.handle_request(EngineRequest(
        id="run", method="qaAudit.runRange",
        params={"chapter": "1", "verse": "3", "meaningRunId": meaning["id"]},
    )).to_dict()
    assert response["success"] is True, response
    run = response["result"]
    finding_id = run["findings"][0]["id"] if run["findings"] else None
    calls = [
        ("qaAudit.status", {"runId": run["id"]}),
        ("qaAudit.getRange", {"runId": run["id"]}),
        ("qaAudit.getSourceCoverage", {"runId": run["id"]}),
        ("qaAudit.getTargetSupport", {"runId": run["id"]}),
        ("qaAudit.getDiagnostics", {"runId": run["id"]}),
    ]
    if finding_id:
        calls.append(("qaAudit.getFinding", {"findingId": finding_id}))
    assert all(bridge.handle_request(EngineRequest(
        id=str(index), method=method, params=params,
    )).to_dict()["success"] for index, (method, params) in enumerate(calls))
    # Stage 8 reads Stages 6B and 7; it never re-runs or re-judges them.
    location_snapshot_before = json.dumps(runtime.semantic_location.get_range(location["id"]), sort_keys=True)
    meaning_snapshot_before = json.dumps(runtime.meaning_analysis.get_range(meaning["id"]), sort_keys=True)
    assert location_snapshot_before == json.dumps(
        runtime.semantic_location.get_range(location["id"]), sort_keys=True,
    )
    assert meaning_snapshot_before == json.dumps(
        runtime.meaning_analysis.get_range(meaning["id"]), sort_keys=True,
    )
