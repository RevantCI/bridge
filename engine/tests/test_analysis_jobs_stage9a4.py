from __future__ import annotations

import threading
import time
from typing import Any

import pytest

from tc_ai_bridge.analysis_jobs import (
    AnalysisJobConflict,
    AnalysisJobManager,
    AnalysisJobNotFound,
)
from tc_ai_bridge.passage_semantic_runtime import PassageSemanticRuntime
from tc_ai_bridge.tc_project import TranslationCoreProject

from .test_qa_audit_stage8 import _runtime


def _wait(manager: AnalysisJobManager, job_id: str, timeout: float = 5.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = manager.status(job_id)
        if result["overallStatus"] in {
            "COMPLETED", "COMPLETED_WITH_WARNINGS", "FAILED", "CANCELLED",
        }:
            return result
        time.sleep(0.01)
    raise AssertionError(f"analysis job {job_id} did not finish")


class _Provider:
    provider_id = "unavailable"
    provider_version = "v1"
    model_hash = "unavailable"
    available = False
    fixture_only = False

    def descriptor(self) -> dict[str, Any]:
        return {
            "providerId": self.provider_id,
            "providerVersion": self.provider_version,
            "modelHash": self.model_hash,
            "available": self.available,
            "fixtureOnly": self.fixture_only,
        }


class _Stage:
    def __init__(
        self, name: str, calls: list[str], *, cache: str = "MISS",
        fail: bool = False, entered: threading.Event | None = None,
        release: threading.Event | None = None, search_incomplete: int = 0,
    ) -> None:
        self.name = name
        self.calls = calls
        self.cache = cache
        self.fail = fail
        self.entered = entered
        self.release = release
        self.search_incomplete = search_incomplete
        self.embedding_provider = _Provider()

    def _result(self) -> dict[str, Any]:
        if self.fail:
            raise RuntimeError(f"{self.name} failed")
        if self.entered:
            self.entered.set()
        if self.release:
            assert self.release.wait(3)
        result: dict[str, Any] = {
            "id": f"{self.name.lower()}-run",
            "cacheStatus": self.cache,
            "diagnostics": {},
            "elapsedSeconds": 0.01,
        }
        if self.name == "TARGET_INVENTORY":
            result["targetContentHash"] = "target-hash"
        if self.name == "LOCATION":
            result.update({
                "diagnostics": {"searchIncomplete": self.search_incomplete},
                "relationships": [],
            })
        if self.name == "QA":
            result.update({
                "findings": [],
                "phaseProfile": {
                    "sourceCoverageAudit": 0.01,
                    "targetSupportAudit": 0.02,
                    "findingSynthesis": 0.0,
                    "persistence": 0.03,
                },
            })
        return result

    def build_range(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
        self.calls.append(self.name)
        return self._result()

    def run_range(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
        self.calls.append(self.name)
        return self._result()


def _stub_stages(runtime: Any, *, cache: str = "MISS", fail: str = "") -> list[str]:
    calls: list[str] = []
    runtime.source_semantic = _Stage("SOURCE_INVENTORY", calls, cache=cache, fail=fail == "SOURCE_INVENTORY")
    runtime.target_semantic = _Stage("TARGET_INVENTORY", calls, cache=cache, fail=fail == "TARGET_INVENTORY")
    runtime.semantic_location = _Stage("LOCATION", calls, cache=cache, fail=fail == "LOCATION")
    runtime.meaning_analysis = _Stage("MEANING", calls, cache=cache, fail=fail == "MEANING")
    runtime.qa_audit = _Stage("QA", calls, cache=cache, fail=fail == "QA")
    return calls


def _start(manager: AnalysisJobManager, runtime: Any, **options: Any) -> dict[str, Any]:
    return manager.start(
        runtime,
        requested_scope={
            "kind": "SELECTED_RANGE", "startChapter": "1", "startVerse": "3",
            "endChapter": "1", "endVerse": "3",
        },
        **options,
    )


def test_runs_stage_5_through_8_in_dependency_order_and_persists_job(tmp_path) -> None:
    runtime = _runtime(tmp_path, language="en", chapters={"1": {"3": "text"}})
    scripture = runtime.project.path / "php" / "1.json"
    alignment = runtime.project.path / ".apps" / "translationCore" / "alignmentData" / "php" / "1.json"
    scripture_before, alignment_before = scripture.read_bytes(), alignment.read_bytes()
    calls = _stub_stages(runtime)
    manager = AnalysisJobManager()
    completed = _wait(manager, _start(manager, runtime)["jobId"])
    assert calls == ["SOURCE_INVENTORY", "TARGET_INVENTORY", "LOCATION", "MEANING", "QA"]
    assert completed["overallStatus"] == "COMPLETED_WITH_WARNINGS"
    assert completed["stageStatuses"]["SOURCE_INVENTORY"]["status"] == "COMPLETED"
    assert completed["createdRunIds"] == [
        "source_inventory-run", "target_inventory-run", "location-run", "meaning-run", "qa-run",
    ]
    assert runtime.repository.analysis_job(completed["jobId"])["overallStatus"] == completed["overallStatus"]
    assert set(completed["timings"]) == {
        "SOURCE_INVENTORY", "TARGET_INVENTORY", "LOCATION", "MEANING", "QA",
    }
    assert set(completed["stage8PhaseTimings"]) == {
        "sourceCoverageAudit", "targetSupportAudit", "findingSynthesis", "persistence",
    }
    assert scripture.read_bytes() == scripture_before
    assert alignment.read_bytes() == alignment_before


def test_cached_stage_results_are_reused_not_recomputed_as_new_runs(tmp_path) -> None:
    runtime = _runtime(tmp_path, language="en", chapters={"1": {"3": "text"}})
    _stub_stages(runtime, cache="HIT")
    manager = AnalysisJobManager()
    completed = _wait(manager, _start(manager, runtime)["jobId"])
    assert completed["createdRunIds"] == []
    assert completed["reusedRunIds"] == [
        "source_inventory-run", "target_inventory-run", "location-run", "meaning-run", "qa-run",
    ]
    assert all(value["status"] == "REUSED" for value in completed["stageStatuses"].values())


def test_failure_is_recoverable_and_never_looks_current(tmp_path) -> None:
    runtime = _runtime(tmp_path, language="en", chapters={"1": {"3": "text"}})
    _stub_stages(runtime, fail="LOCATION")
    manager = AnalysisJobManager()
    failed = _wait(manager, _start(manager, runtime)["jobId"])
    assert failed["overallStatus"] == "FAILED"
    assert failed["stageStatuses"]["LOCATION"]["status"] == "FAILED"
    assert failed["failures"][0]["stage"] == "LOCATION"
    assert manager.get_scope_status(runtime, failed["requestedScope"])["state"] == "FAILED"


def test_cancellation_is_cooperative_between_stages(tmp_path) -> None:
    runtime = _runtime(tmp_path, language="en", chapters={"1": {"3": "text"}})
    calls: list[str] = []
    entered, release = threading.Event(), threading.Event()
    runtime.source_semantic = _Stage("SOURCE_INVENTORY", calls, entered=entered, release=release)
    runtime.target_semantic = _Stage("TARGET_INVENTORY", calls)
    runtime.semantic_location = _Stage("LOCATION", calls)
    runtime.meaning_analysis = _Stage("MEANING", calls)
    runtime.qa_audit = _Stage("QA", calls)
    manager = AnalysisJobManager()
    started = _start(manager, runtime)
    assert entered.wait(2)
    cancelling = manager.cancel(started["jobId"])
    assert cancelling["cancellationRequested"] is True
    release.set()
    cancelled = _wait(manager, started["jobId"])
    assert cancelled["overallStatus"] == "CANCELLED"
    assert calls == ["SOURCE_INVENTORY"]


def test_only_one_active_job_is_allowed_for_a_project(tmp_path) -> None:
    runtime = _runtime(tmp_path, language="en", chapters={"1": {"3": "text"}})
    calls: list[str] = []
    entered, release = threading.Event(), threading.Event()
    runtime.source_semantic = _Stage("SOURCE_INVENTORY", calls, entered=entered, release=release)
    runtime.target_semantic = _Stage("TARGET_INVENTORY", calls)
    runtime.semantic_location = _Stage("LOCATION", calls)
    runtime.meaning_analysis = _Stage("MEANING", calls)
    runtime.qa_audit = _Stage("QA", calls)
    manager = AnalysisJobManager()
    first = _start(manager, runtime)
    assert entered.wait(2)
    with pytest.raises(AnalysisJobConflict):
        _start(manager, runtime)
    manager.cancel(first["jobId"]); release.set(); _wait(manager, first["jobId"])


def test_database_prevents_active_jobs_from_two_managers(tmp_path) -> None:
    runtime = _runtime(tmp_path, language="en", chapters={"1": {"3": "text"}})
    calls: list[str] = []
    entered, release = threading.Event(), threading.Event()
    runtime.source_semantic = _Stage("SOURCE_INVENTORY", calls, entered=entered, release=release)
    runtime.target_semantic = _Stage("TARGET_INVENTORY", calls)
    runtime.semantic_location = _Stage("LOCATION", calls)
    runtime.meaning_analysis = _Stage("MEANING", calls)
    runtime.qa_audit = _Stage("QA", calls)
    first_manager, second_manager = AnalysisJobManager(), AnalysisJobManager()
    first = _start(first_manager, runtime)
    assert entered.wait(2)
    with pytest.raises(AnalysisJobConflict, match="already active"):
        _start(second_manager, runtime)
    first_manager.cancel(first["jobId"]); release.set(); _wait(first_manager, first["jobId"])


def test_unknown_job_is_reported(tmp_path) -> None:
    runtime = _runtime(tmp_path, language="en", chapters={"1": {"3": "text"}})
    manager = AnalysisJobManager()
    manager.bind_runtime(runtime)
    with pytest.raises(AnalysisJobNotFound):
        manager.status("missing")


def test_reopen_recovers_abandoned_running_job_as_failed(tmp_path) -> None:
    runtime = _runtime(tmp_path, language="en", chapters={"1": {"3": "text"}})
    payload = AnalysisJobManager.new_job_payload(
        runtime, {
            "kind": "SELECTED_RANGE", "startChapter": "1", "startVerse": "3",
            "endChapter": "1", "endVerse": "3",
        },
    )
    payload["overallStatus"] = "RUNNING"
    runtime.repository.create_analysis_job(payload)
    recovered = AnalysisJobManager().bind_runtime(runtime)
    assert recovered == 1
    assert runtime.repository.analysis_job(payload["jobId"])["overallStatus"] == "FAILED"


def test_completed_job_is_reloadable_after_manager_restart(tmp_path) -> None:
    runtime = _runtime(tmp_path, language="en", chapters={"1": {"3": "text"}})
    _stub_stages(runtime)
    first = AnalysisJobManager()
    completed = _wait(first, _start(first, runtime)["jobId"])
    restarted = AnalysisJobManager()
    assert restarted.bind_runtime(runtime) == 0
    assert restarted.status(completed["jobId"])["overallStatus"] == completed["overallStatus"]


def test_scope_states_distinguish_unanalyzed_current_and_stale(tmp_path) -> None:
    runtime = _runtime(tmp_path, language="en", chapters={"1": {"3": "text"}})
    manager = AnalysisJobManager(); manager.bind_runtime(runtime)
    scope = {
        "kind": "SELECTED_RANGE", "startChapter": "1", "startVerse": "3",
        "endChapter": "1", "endVerse": "3",
    }
    assert manager.get_scope_status(runtime, scope)["state"] == "NOT_ANALYZED"
    _stub_stages(runtime)
    _wait(manager, manager.start(runtime, requested_scope=scope)["jobId"])
    assert manager.get_scope_status(runtime, scope)["state"] == "CURRENT"
    runtime.project.apply_scripture_edit("1", "3", "changed text")
    runtime.synchronize_current_text()
    stale = manager.get_scope_status(runtime, scope)
    assert stale["state"] == "STALE"
    assert stale["affectedReferences"] == ["PHP 1:3"]


def test_affected_rerun_currentizes_a_larger_scope_without_recomputing_it(tmp_path) -> None:
    initial = _runtime(
        tmp_path, language="en", chapters={"1": {"3": "three", "4": "four"}},
    )
    root = initial.project.path
    (root / "php.usfm").write_text(
        "\\id PHP\n\\c 1\n\\p\n\\v 3 OLD THREE\n\\p\n\\v 4 OLD FOUR\n",
        encoding="utf-8",
    )
    runtime = PassageSemanticRuntime(TranslationCoreProject(root), initial.project_id)
    manager = AnalysisJobManager(); manager.bind_runtime(runtime)
    scope = {
        "kind": "SELECTED_RANGE", "startChapter": "1", "startVerse": "3",
        "endChapter": "1", "endVerse": "4",
    }
    _stub_stages(runtime)
    _wait(manager, manager.start(runtime, requested_scope=scope)["jobId"])
    runtime.project.apply_scripture_edit("1", "3", "changed three")
    runtime.synchronize_current_text()
    assert manager.get_scope_status(runtime, scope)["affectedReferences"] == ["PHP 1:3"]

    affected = {**scope, "kind": "AFFECTED", "baseKind": "SELECTED_RANGE"}
    _stub_stages(runtime)
    rerun = _wait(manager, manager.start(runtime, requested_scope=affected)["jobId"])
    assert rerun["rangeKey"] == "PHP 1:3..PHP 1:3"
    assert manager.get_scope_status(runtime, scope)["state"] == "CURRENT"


def test_unavailable_provider_is_explicit_and_never_a_fixture(tmp_path) -> None:
    runtime = _runtime(tmp_path, language="en", chapters={"1": {"3": "text"}})
    manager = AnalysisJobManager()
    capability = manager.provider_capability(runtime)
    assert capability == {
        "semanticRetrieval": "LIMITED",
        "multilingualEmbeddingProvider": "NOT_CONFIGURED",
        "providerId": "unavailable",
        "providerVersion": "v1",
        "modelHash": "none",
        "fixtureProvider": False,
    }


def test_provider_change_marks_prior_analysis_stale(tmp_path) -> None:
    runtime = _runtime(tmp_path, language="en", chapters={"1": {"3": "text"}})
    _stub_stages(runtime)
    manager = AnalysisJobManager()
    completed = _wait(manager, _start(manager, runtime)["jobId"])
    runtime.semantic_location.embedding_provider.provider_id = "production-multilingual"
    runtime.semantic_location.embedding_provider.provider_version = "v2"
    runtime.semantic_location.embedding_provider.model_hash = "new-model"
    runtime.semantic_location.embedding_provider.available = True
    status = manager.get_scope_status(runtime, completed["requestedScope"])
    assert status["state"] == "STALE"
    assert status["affectedReferences"] == ["PHP 1:3"]
    assert status["providerCapability"]["semanticRetrieval"] == "FULL"


def test_fixture_provider_is_rejected_by_normal_orchestration(tmp_path) -> None:
    from tc_ai_bridge.analysis_jobs import AnalysisJobError

    runtime = _runtime(tmp_path, language="en", chapters={"1": {"3": "text"}})
    _stub_stages(runtime)
    runtime.semantic_location.embedding_provider.available = True
    runtime.semantic_location.embedding_provider.fixture_only = True
    with pytest.raises(AnalysisJobError, match="Fixture semantic providers"):
        _start(AnalysisJobManager(), runtime)


def test_search_incomplete_is_preserved_as_a_scope_state(tmp_path) -> None:
    runtime = _runtime(tmp_path, language="en", chapters={"1": {"3": "text"}})
    calls = _stub_stages(runtime)
    runtime.semantic_location = _Stage("LOCATION", calls, search_incomplete=2)
    manager = AnalysisJobManager()
    completed = _wait(manager, _start(manager, runtime)["jobId"])
    assert completed["overallStatus"] == "COMPLETED_WITH_WARNINGS"
    assert completed["searchIncomplete"] is True
    assert completed["qaFindingCount"] == 0
    assert manager.get_scope_status(runtime, completed["requestedScope"])["state"] == "SEARCH_INCOMPLETE"


def test_analysis_job_apis_round_trip_over_bridge_protocol(tmp_path) -> None:
    from bridge_service import BridgeEngine
    from greek_room_engine.protocol import EngineRequest

    runtime = _runtime(tmp_path, language="en", chapters={"1": {"3": "text"}})
    _stub_stages(runtime)
    bridge = BridgeEngine()
    bridge.project = runtime.project
    bridge.passage_semantic_runtime = runtime
    bridge._analysis_jobs.bind_runtime(runtime)
    scope = {
        "kind": "SELECTED_RANGE", "startChapter": "1", "startVerse": "3",
        "endChapter": "1", "endVerse": "3",
    }

    def call(method: str, params: dict[str, Any]) -> dict[str, Any]:
        return bridge.handle_request(
            EngineRequest(id="analysis", method=method, params=params),
        ).to_dict()

    before = call("analysisJob.getScopeStatus", {"requestedScope": scope})
    assert before["success"] is True
    assert before["result"]["state"] == "NOT_ANALYZED"
    assert before["result"]["providerCapability"]["semanticRetrieval"] == "LIMITED"

    started = call("analysisJob.start", {"requestedScope": scope})
    assert started["success"] is True
    job_id = started["result"]["jobId"]
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        status = call("analysisJob.status", {"jobId": job_id})
        assert status["success"] is True
        if status["result"]["overallStatus"] in {
            "COMPLETED", "COMPLETED_WITH_WARNINGS", "FAILED", "CANCELLED",
        }:
            break
        time.sleep(0.01)
    else:
        raise AssertionError("protocol analysis job did not finish")

    assert status["result"]["overallStatus"] == "COMPLETED_WITH_WARNINGS"
    recent = call("analysisJob.getRecent", {"limit": 5})
    assert recent["success"] is True
    assert recent["result"][0]["jobId"] == job_id


def test_normal_unseeded_runtime_runs_without_fixture_vectors(tmp_path) -> None:
    runtime = _runtime(
        tmp_path, language="en", chapters={"1": {"3": "unrelated target words"}},
    )
    manager = AnalysisJobManager()
    completed = _wait(manager, _start(manager, runtime)["jobId"], timeout=15)
    assert completed["overallStatus"] in {"COMPLETED", "COMPLETED_WITH_WARNINGS"}
    assert completed["providerCapability"]["fixtureProvider"] is False
    assert completed["providerCapability"]["multilingualEmbeddingProvider"] == "NOT_CONFIGURED"
    assert completed["stageProgress"] == {"completedStages": 5, "totalStages": 5}
    assert manager.get_scope_status(runtime, completed["requestedScope"])["state"] in {
        "CURRENT", "SEARCH_INCOMPLETE",
    }
