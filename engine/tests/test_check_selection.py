"""Milestone 3B.1: safe, translationCore-compatible tN/tW selection persistence."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from bridge_service import BridgeEngine
from greek_room_engine.protocol import EngineRequest
from tc_ai_bridge.secret_store import AppSettings
from tc_ai_bridge.tc_project import ProjectError, TranslationCoreProject
import tc_ai_bridge.tc_project as tc_project_module


def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


@pytest.fixture
def check_project(tmp_path: Path) -> Path:
    root = tmp_path / "tit"
    _write_json(root / "manifest.json", {
        "project": {"id": "tit", "name": "Titus"},
        "target_language": {"id": "en", "name": "English"},
        "tc_version": "8", "tc_edit_version": "3.7.0",
    })
    _write_json(
        root / ".apps" / "translationCore" / "alignmentData" / "tit" / "1.json",
        {"1": {"alignments": [], "wordBank": [
            {"word": word, "occurrence": 1, "occurrences": 1}
            for word in ("alpha", "beta", "gamma", "delta")
        ]}},
    )
    _write_json(root / "tit" / "1.json", {"1": "alpha beta alpha gamma delta"})

    reference = {"bookId": "tit", "chapter": "1", "verse": "1"}
    _write_json(
        root / ".apps" / "translationCore" / "index" / "translationNotes" / "tit" / "figs-metaphor.json",
        [{
            "contextId": {
                "reference": reference, "tool": "translationNotes",
                "groupId": "figs-metaphor", "checkId": "tn-1",
                "quoteString": "λόγος", "occurrence": 1,
                "occurrenceNote": "Review the figure of speech.",
            },
            "selections": False, "nothingToSelect": False, "invalidated": False,
        }],
    )
    _write_json(
        root / ".apps" / "translationCore" / "index" / "translationWords" / "tit" / "faith.json",
        [{
            "contextId": {
                "reference": reference, "tool": "translationWords",
                "groupId": "faith", "checkId": "tw-1",
                "quoteString": "πίστις", "occurrence": 1, "occurrenceNote": "",
            },
            "selections": False, "nothingToSelect": False, "invalidated": False,
        }],
    )
    return root


def _engine(tmp_path: Path) -> BridgeEngine:
    return BridgeEngine(settings=AppSettings(path=tmp_path / "settings.json"))


def _call(engine: BridgeEngine, method: str, params: dict | None = None) -> dict:
    request = EngineRequest(id="3b1", method=method, params=params or {})
    return engine.handle_request(request).to_dict()


def _open(engine: BridgeEngine, project: Path) -> None:
    response = _call(engine, "project.open", {"path": str(project)})
    assert response["success"] is True


def _review(engine: BridgeEngine, tool: str, check_id: str) -> dict:
    result = _call(engine, "check.listForVerse", {"chapter": "1", "verse": "1"})
    assert result["success"] is True
    return next(item for item in result["result"]["checks"] if item["tool"] == tool and item["checkId"] == check_id)


def _identity(review: dict) -> dict:
    return {
        "chapter": "1", "verse": "1", "tool": review["tool"],
        "groupId": review["groupId"], "checkId": review["checkId"],
    }


def test_list_exposes_selection_evaluation_and_provenance_as_separate_axes(check_project, tmp_path):
    engine = _engine(tmp_path)
    _open(engine, check_project)

    review = _review(engine, "translationNotes", "tn-1")

    assert review["selectionStatus"] == "pending"
    assert review["evaluationStatus"] == "not_run"
    assert review["provenance"] == "none"
    assert review["sourceQuote"] == "λόγος"
    assert len(review["stateFingerprint"]) == 64


def test_list_returns_preparing_without_blocking_behind_background_checks(check_project, tmp_path):
    engine = _engine(tmp_path)
    _open(engine, check_project)
    acquired = threading.Event()
    release = threading.Event()

    def hold_checker() -> None:
        with engine._checker_lock:
            acquired.set()
            release.wait(timeout=5)

    holder = threading.Thread(target=hold_checker, daemon=True)
    holder.start()
    assert acquired.wait(timeout=1)
    started = time.monotonic()
    response = _call(engine, "check.listForVerse", {"chapter": "1", "verse": "1"})
    elapsed = time.monotonic() - started
    release.set()
    holder.join(timeout=1)

    assert response["success"] is True
    assert response["result"]["state"] == "preparing"
    assert response["result"]["checks"] == []
    assert response["result"]["retryAfterMs"] > 0
    assert elapsed < 0.25

    ready = _call(engine, "check.listForVerse", {"chapter": "1", "verse": "1"})
    assert ready["result"]["state"] == "ready"
    assert len(ready["result"]["checks"]) == 2


def test_list_does_not_materialize_pending_resources_on_dispatch_thread(check_project, tmp_path, monkeypatch):
    engine = _engine(tmp_path)
    _open(engine, check_project)
    _write_json(check_project / ".bridge" / "import.json", {
        "capabilities": {
            "translationNotes": "requires-resource-index",
            "translationWords": "requires-resource-index",
        },
    })

    def forbidden_materialization(_project) -> None:
        raise AssertionError("interactive list request must not materialize resources")

    monkeypatch.setattr(engine, "_ensure_resource_indexes", forbidden_materialization)
    response = _call(engine, "check.listForVerse", {"chapter": "1", "verse": "1"})

    assert response["success"] is True
    assert response["result"]["state"] == "preparing"
    assert response["result"]["checks"] == []


def test_validation_is_read_only_and_checks_repeated_occurrences(check_project, tmp_path):
    engine = _engine(tmp_path)
    _open(engine, check_project)
    review = _review(engine, "translationNotes", "tn-1")
    check_data = check_project / ".apps" / "translationCore" / "checkData"

    valid = _call(engine, "check.validateSelection", {
        **_identity(review),
        "selections": [{"text": "alpha", "occurrence": 2, "occurrences": 2}],
        "nothingToSelect": False,
    })["result"]
    invalid = _call(engine, "check.validateSelection", {
        **_identity(review),
        "selections": [{"text": "alpha", "occurrence": 1, "occurrences": 1}],
        "nothingToSelect": False,
    })["result"]

    assert valid["valid"] is True
    assert valid["ranges"] == [{"start": 11, "end": 16}]
    assert invalid["valid"] is False
    assert "current verse has 2" in invalid["errors"][0]
    assert not check_data.exists()


@pytest.mark.parametrize("selections,nothing_to_select", [([], False), ([{"text": "beta", "occurrence": 1, "occurrences": 1}], True)])
def test_validation_rejects_incomplete_or_contradictory_completion(check_project, tmp_path, selections, nothing_to_select):
    engine = _engine(tmp_path)
    _open(engine, check_project)
    review = _review(engine, "translationNotes", "tn-1")

    result = _call(engine, "check.validateSelection", {
        **_identity(review), "selections": selections, "nothingToSelect": nothing_to_select,
    })["result"]

    assert result["valid"] is False


def test_validation_rejects_absent_duplicate_and_overlapping_text(check_project, tmp_path):
    engine = _engine(tmp_path)
    _open(engine, check_project)
    review = _review(engine, "translationNotes", "tn-1")
    cases = [
        [{"text": "missing", "occurrence": 1, "occurrences": 1}],
        [
            {"text": "beta", "occurrence": 1, "occurrences": 1},
            {"text": "beta", "occurrence": 1, "occurrences": 1},
        ],
        [
            {"text": "alpha beta", "occurrence": 1, "occurrences": 1},
            {"text": "beta", "occurrence": 1, "occurrences": 1},
        ],
    ]

    for selections in cases:
        result = _call(engine, "check.validateSelection", {
            **_identity(review), "selections": selections, "nothingToSelect": False,
        })["result"]
        assert result["valid"] is False


def test_human_save_writes_native_state_and_survives_restart(check_project, tmp_path):
    engine = _engine(tmp_path)
    _open(engine, check_project)
    review = _review(engine, "translationNotes", "tn-1")
    selection = {"text": "alpha", "occurrence": 2, "occurrences": 2}

    saved = _call(engine, "check.saveSelection", {
        **_identity(review), "selections": [selection], "nothingToSelect": False,
        "provenance": "human", "expectedFingerprint": review["stateFingerprint"],
        "metadata": {"reason": "manual review"},
    })

    assert saved["success"] is True
    mutation = saved["result"]
    assert mutation["review"]["selectionStatus"] == "selected"
    assert mutation["review"]["evaluationStatus"] == "not_run"
    assert mutation["review"]["provenance"] == "human"
    selection_record = json.loads(Path(mutation["files"]["selection"]).read_text(encoding="utf-8"))
    invalid_record = json.loads(Path(mutation["files"]["invalidated"]).read_text(encoding="utf-8"))
    audit_record = json.loads(Path(mutation["files"]["audit"]).read_text(encoding="utf-8"))
    assert selection_record["selections"] == [selection]
    assert selection_record["nothingToSelect"] is False
    assert invalid_record["invalidated"] is False
    assert audit_record["provenance"] == "human"
    assert audit_record["metadata"] == {"reason": "manual review"}

    restarted = _engine(tmp_path / "restart")
    _open(restarted, check_project)
    persisted = _review(restarted, "translationNotes", "tn-1")
    assert persisted["selections"] == [selection]
    assert persisted["provenance"] == "human"


def test_discontinuous_selection_nothing_to_select_and_clear_are_native_states(check_project, tmp_path):
    engine = _engine(tmp_path)
    _open(engine, check_project)
    tw = _review(engine, "translationWords", "tw-1")
    selections = [
        {"text": "beta", "occurrence": 1, "occurrences": 1},
        {"text": "delta", "occurrence": 1, "occurrences": 1},
    ]
    selected = _call(engine, "check.saveSelection", {
        **_identity(tw), "selections": selections, "nothingToSelect": False,
        "provenance": "human", "expectedFingerprint": tw["stateFingerprint"],
    })["result"]["review"]
    assert selected["selections"] == selections

    cleared = _call(engine, "check.clearSelection", {
        **_identity(selected), "provenance": "human",
        "expectedFingerprint": selected["stateFingerprint"],
    })["result"]["review"]
    assert cleared["selectionStatus"] == "pending"
    assert cleared["selections"] == []

    tn = _review(engine, "translationNotes", "tn-1")
    not_applicable = _call(engine, "check.saveSelection", {
        **_identity(tn), "selections": [], "nothingToSelect": True,
        "provenance": "human", "expectedFingerprint": tn["stateFingerprint"],
    })["result"]["review"]
    assert not_applicable["selectionStatus"] == "nothing_to_select"
    assert not_applicable["nothingToSelect"] is True


def test_stale_fingerprint_and_ai_overwrite_of_human_state_are_rejected(check_project, tmp_path):
    engine = _engine(tmp_path)
    _open(engine, check_project)
    review = _review(engine, "translationNotes", "tn-1")
    human = _call(engine, "check.saveSelection", {
        **_identity(review),
        "selections": [{"text": "beta", "occurrence": 1, "occurrences": 1}],
        "nothingToSelect": False, "provenance": "human",
        "expectedFingerprint": review["stateFingerprint"],
    })["result"]["review"]

    stale = _call(engine, "check.clearSelection", {
        **_identity(review), "provenance": "human",
        "expectedFingerprint": review["stateFingerprint"],
    })
    ai = _call(engine, "check.saveSelection", {
        **_identity(human),
        "selections": [{"text": "gamma", "occurrence": 1, "occurrences": 1}],
        "nothingToSelect": False, "provenance": "bridge_ai",
        "expectedFingerprint": human["stateFingerprint"],
    })

    assert stale["success"] is False
    assert "changed on disk" in stale["error"]["message"]
    assert ai["success"] is False
    assert "may not replace" in ai["error"]["message"]
    assert _review(engine, "translationNotes", "tn-1")["selections"][0]["text"] == "beta"


def test_imported_translationcore_selection_is_protected_from_ai(check_project, tmp_path):
    index_path = check_project / ".apps" / "translationCore" / "index" / "translationWords" / "tit" / "faith.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index[0]["selections"] = [{"text": "gamma", "occurrence": 1, "occurrences": 1}]
    _write_json(index_path, index)
    engine = _engine(tmp_path)
    _open(engine, check_project)
    review = _review(engine, "translationWords", "tw-1")

    response = _call(engine, "check.saveSelection", {
        **_identity(review),
        "selections": [{"text": "delta", "occurrence": 1, "occurrences": 1}],
        "nothingToSelect": False, "provenance": "bridge_ai",
        "expectedFingerprint": review["stateFingerprint"],
    })

    assert review["provenance"] == "existing_tc"
    assert response["success"] is False
    assert _review(engine, "translationWords", "tw-1")["selections"][0]["text"] == "gamma"


def test_bridge_ai_can_update_only_its_own_prior_selection(check_project, tmp_path):
    engine = _engine(tmp_path)
    _open(engine, check_project)
    review = _review(engine, "translationWords", "tw-1")
    first = _call(engine, "check.saveSelection", {
        **_identity(review),
        "selections": [{"text": "beta", "occurrence": 1, "occurrences": 1}],
        "nothingToSelect": False, "provenance": "bridge_ai",
        "expectedFingerprint": review["stateFingerprint"],
    })["result"]["review"]

    second = _call(engine, "check.saveSelection", {
        **_identity(first),
        "selections": [{"text": "gamma", "occurrence": 1, "occurrences": 1}],
        "nothingToSelect": False, "provenance": "bridge_ai",
        "expectedFingerprint": first["stateFingerprint"],
    })

    assert first["provenance"] == "bridge_ai"
    assert second["success"] is True
    assert second["result"]["review"]["selections"][0]["text"] == "gamma"


def test_same_check_id_in_different_tools_does_not_cross_contaminate_state(check_project, tmp_path):
    tw_path = check_project / ".apps" / "translationCore" / "index" / "translationWords" / "tit" / "faith.json"
    tw_data = json.loads(tw_path.read_text(encoding="utf-8"))
    tw_data[0]["contextId"]["checkId"] = "tn-1"
    _write_json(tw_path, tw_data)
    engine = _engine(tmp_path)
    _open(engine, check_project)
    tn = _review(engine, "translationNotes", "tn-1")

    saved = _call(engine, "check.saveSelection", {
        **_identity(tn),
        "selections": [{"text": "beta", "occurrence": 1, "occurrences": 1}],
        "nothingToSelect": False, "provenance": "human",
        "expectedFingerprint": tn["stateFingerprint"],
    })
    tw = _review(engine, "translationWords", "tn-1")

    assert saved["success"] is True
    assert tw["selectionStatus"] == "pending"
    assert tw["provenance"] == "none"


def test_scripture_edit_invalidates_selection_without_calling_it_failed(check_project, tmp_path):
    engine = _engine(tmp_path)
    _open(engine, check_project)
    review = _review(engine, "translationNotes", "tn-1")
    selected = _call(engine, "check.saveSelection", {
        **_identity(review),
        "selections": [{"text": "beta", "occurrence": 1, "occurrences": 1}],
        "nothingToSelect": False, "provenance": "human",
        "expectedFingerprint": review["stateFingerprint"],
    })
    assert selected["success"] is True

    edited = _call(engine, "verse.edit", {
        "chapter": "1", "verse": "1", "newText": "alpha changed alpha gamma delta",
    })
    assert edited["success"] is True
    invalidated = _review(engine, "translationNotes", "tn-1")
    assert invalidated["selectionStatus"] == "invalidated"
    assert invalidated["evaluationStatus"] == "needs_review"

    rechecked = _call(engine, "check.saveSelection", {
        **_identity(invalidated),
        "selections": [{"text": "changed", "occurrence": 1, "occurrences": 1}],
        "nothingToSelect": False, "provenance": "human",
        "expectedFingerprint": invalidated["stateFingerprint"],
    })
    assert rechecked["success"] is True
    assert rechecked["result"]["review"]["selectionStatus"] == "selected"
    assert rechecked["result"]["review"]["stale"] is False


def test_native_and_audit_files_roll_back_if_transaction_write_fails(check_project, monkeypatch):
    project = TranslationCoreProject(check_project)
    review = project.check_review("1", "1", "translationNotes", "figs-metaphor", "tn-1")
    index_path = check_project / ".apps" / "translationCore" / "index" / "translationNotes" / "tit" / "figs-metaphor.json"
    before = index_path.read_bytes()
    real_write = tc_project_module._write_json_atomic

    def fail_on_audit(path: Path, data) -> None:
        if "tc-selection" in Path(path).name:
            raise OSError("simulated audit write failure")
        real_write(path, data)

    monkeypatch.setattr(tc_project_module, "_write_json_atomic", fail_on_audit)
    with pytest.raises(OSError, match="simulated audit"):
        project.save_check_selection(
            "1", "1", "translationNotes", "figs-metaphor", "tn-1",
            [{"text": "beta", "occurrence": 1, "occurrences": 1}], False,
            "human", review["stateFingerprint"],
        )

    assert index_path.read_bytes() == before
    selection_root = check_project / ".apps" / "translationCore" / "checkData" / "selections"
    invalid_root = check_project / ".apps" / "translationCore" / "checkData" / "invalidated"
    assert not list(selection_root.rglob("*.json"))
    assert not list(invalid_root.rglob("*.json"))
