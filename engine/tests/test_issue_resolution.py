"""Milestone 3B.4: durable issue resolution and retry-safe Paratext handoff."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace

import pytest

import bridge_service as bridge_service_module
from bridge_service import BridgeEngine
from greek_room_engine.protocol import EngineRequest
from tc_ai_bridge.paratext_connector import ParatextConnectorError
from tc_ai_bridge.secret_store import AppSettings


def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


@pytest.fixture
def resolution_project(tmp_path: Path) -> Path:
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
            for word in ("alpha", "beta", "gamma")
        ]}},
    )
    _write_json(root / "tit" / "1.json", {"1": "alpha beta gamma"})
    _write_json(
        root / ".apps" / "translationCore" / "index" / "translationNotes" / "tit" / "figs-metaphor.json",
        [{
            "contextId": {
                "reference": {"bookId": "tit", "chapter": "1", "verse": "1"},
                "tool": "translationNotes", "groupId": "figs-metaphor", "checkId": "tn-1",
                "quoteString": "λόγος", "occurrence": 1,
            },
            "selections": False, "nothingToSelect": False, "invalidated": False,
        }],
    )
    return root


def _call(engine: BridgeEngine, method: str, params: dict | None = None) -> dict:
    return engine.handle_request(EngineRequest(id="3b4", method=method, params=params or {})).to_dict()


def _engine(tmp_path: Path, project: Path) -> BridgeEngine:
    engine = BridgeEngine(settings=AppSettings(path=tmp_path / "settings.json"))
    opened = _call(engine, "project.open", {"path": str(project)})
    assert opened["success"] is True
    return engine


def _check(engine: BridgeEngine) -> dict:
    listed = _call(engine, "check.listForVerse", {"chapter": "1", "verse": "1"})
    return listed["result"]["checks"][0]


def _save(engine: BridgeEngine, check: dict) -> dict:
    response = _call(engine, "issueResolution.save", {
        "chapter": "1", "verse": "1", "tool": check["tool"],
        "groupId": check["groupId"], "checkId": check["checkId"],
        "expectedFingerprint": check["stateFingerprint"],
        "selectedText": "beta", "issueSummary": "The metaphor may be translated literally.",
        "reviewerNote": "Please review this expression in context.",
        "proposedCorrection": "Use a natural metaphor in the target language.",
        "evidence": [{"title": "Translation Academy", "identifier": "figs-metaphor"}],
    })
    assert response["success"] is True
    return response["result"]


def test_resolution_is_persisted_and_rejects_stale_or_false_target_text(resolution_project, tmp_path):
    engine = _engine(tmp_path, resolution_project)
    check = _check(engine)
    saved = _save(engine, check)

    assert saved["status"] == "open"
    assert saved["selectedText"] == "beta"
    assert saved["paratext"]["status"] == "not_queued"
    restarted = _engine(tmp_path / "restart", resolution_project)
    listed = _call(restarted, "issueResolution.list", {"chapter": "1", "verse": "1"})
    assert listed["result"]["items"][0]["resolutionId"] == saved["resolutionId"]

    bad_text = _call(engine, "issueResolution.save", {
        "chapter": "1", "verse": "1", "tool": check["tool"],
        "groupId": check["groupId"], "checkId": check["checkId"],
        "expectedFingerprint": check["stateFingerprint"], "selectedText": "absent",
        "issueSummary": "Issue", "reviewerNote": "Review",
    })
    assert bad_text["success"] is False
    assert "not present" in bad_text["error"]["message"]


def test_unavailable_connector_keeps_one_idempotent_note_safely_queued(
    resolution_project, tmp_path, monkeypatch,
):
    class UnavailableConnector:
        def get_state(self):
            raise ParatextConnectorError("Paratext is offline")

    monkeypatch.setattr(bridge_service_module, "ParatextConnectorClient", UnavailableConnector)
    engine = _engine(tmp_path, resolution_project)
    saved = _save(engine, _check(engine))
    params = {"chapter": "1", "verse": "1", "resolutionId": saved["resolutionId"]}

    first = _call(engine, "issueResolution.queueParatext", params)
    second = _call(engine, "issueResolution.queueParatext", params)

    assert first["success"] is True
    assert second["result"]["handoff"]["status"] == "queued"
    assert second["result"]["handoff"]["attempts"] == 2
    assert "offline" in second["result"]["handoff"]["lastError"]
    notes = resolution_project / ".apps" / "translationCoreAI" / "paratextNotes" / "Notes_AI_Suggestion.xml"
    assert len(ET.parse(notes).getroot().findall("thread")) == 1
    state = json.loads((notes.parent / "live_sync_state.json").read_text(encoding="utf-8"))
    assert len(state["items"]) == 1


def test_confirmed_matching_project_sends_once_and_preserves_message_identity(
    resolution_project, tmp_path, monkeypatch,
):
    calls: list[dict] = []

    class LiveConnector:
        def get_state(self):
            # The installed v0.7.4 Paratext companion advertises the feature
            # family as project_notes while newer companions may use the wire
            # action name create_note.
            return SimpleNamespace(capabilities=["state", "project_notes"], project_id="ptx-titus")

        def create_note(self, reference, selected_text, comment, **kwargs):
            calls.append({
                "reference": reference, "selectedText": selected_text,
                "comment": comment, **kwargs,
            })
            return {"note_id": "remote-1"}

    monkeypatch.setattr(bridge_service_module, "ParatextConnectorClient", LiveConnector)
    engine = _engine(tmp_path, resolution_project)
    saved = _save(engine, _check(engine))
    params = {
        "chapter": "1", "verse": "1", "resolutionId": saved["resolutionId"],
        "expectedProjectId": "ptx-titus",
    }

    first = _call(engine, "issueResolution.queueParatext", params)
    second = _call(engine, "issueResolution.queueParatext", params)

    assert first["result"]["handoff"]["status"] == "sent"
    assert first["result"]["record"]["paratext"]["remoteId"] == "remote-1"
    assert second["result"]["handoff"]["status"] == "sent"
    restored = _call(engine, "issueResolution.list", {"chapter": "1", "verse": "1"})
    restored_record = next(
        item for item in restored["result"]["items"]
        if item["resolutionId"] == saved["resolutionId"]
    )
    assert restored_record["paratext"]["status"] == "sent"
    assert restored_record["paratext"]["remoteId"] == "remote-1"
    assert len(calls) == 1
    assert calls[0]["message_id"].startswith(f"bridge-{saved['resolutionId']}-")
    assert calls[0]["project_id"] == "ptx-titus"


def test_active_project_mismatch_never_sends(resolution_project, tmp_path, monkeypatch):
    class WrongProjectConnector:
        def get_state(self):
            return SimpleNamespace(capabilities=["create_note"], project_id="wrong-project")

        def create_note(self, *args, **kwargs):
            raise AssertionError("must not send to a different active project")

    monkeypatch.setattr(bridge_service_module, "ParatextConnectorClient", WrongProjectConnector)
    engine = _engine(tmp_path, resolution_project)
    saved = _save(engine, _check(engine))
    result = _call(engine, "issueResolution.queueParatext", {
        "chapter": "1", "verse": "1", "resolutionId": saved["resolutionId"],
        "expectedProjectId": "ptx-titus",
    })

    assert result["success"] is True
    assert result["result"]["handoff"]["status"] == "queued"
    assert "does not match" in result["result"]["handoff"]["lastError"]


def test_scripture_edit_marks_resolution_stale_and_requests_automatic_recheck(
    resolution_project, tmp_path,
):
    engine = _engine(tmp_path, resolution_project)
    saved = _save(engine, _check(engine))

    edited = _call(engine, "verse.edit", {
        "chapter": "1", "verse": "1", "newText": "alpha beta delta",
    })

    assert edited["success"] is True
    assert edited["result"]["issueResolutionsNeedingRecheck"] == 1
    record = _call(engine, "issueResolution.list", {
        "chapter": "1", "verse": "1",
    })["result"]["items"][0]
    assert record["resolutionId"] == saved["resolutionId"]
    assert record["status"] == "open"
    assert record["recheck"]["status"] == "stale"
    assert record["recheck"]["inputFingerprint"]
    assert record["history"][-1]["event"] == "recheck_stale"


def test_completed_ai_recheck_resolves_and_persists_grounded_result(
    resolution_project, tmp_path,
):
    engine = _engine(tmp_path, resolution_project)
    saved = _save(engine, _check(engine))
    engine.project.mark_issue_resolutions_recheck(
        "1", "1", "running", reason="Automatic AI recheck started.",
    )

    updated = engine.project.reconcile_issue_resolutions_after_ai_review(
        "1", "1", [{
            "tool": "translationNotes", "group_id": "figs-metaphor", "check_id": "tn-1",
            "verdict": "pass", "confidence": 0.94,
            "rationale": "The revised wording communicates the metaphor naturally.",
            "suggested_correction": "", "evidence_used": [{
                "title": "Translation Academy", "identifier": "figs-metaphor",
            }],
        }], model="review-model", summary="The correction addresses the issue.",
    )

    assert updated[0]["status"] == "resolved"
    assert updated[0]["recheck"]["status"] == "resolved"
    assert updated[0]["recheck"]["verdict"] == "pass"
    assert updated[0]["recheck"]["confidence"] == pytest.approx(0.94)
    assert updated[0]["recheck"]["evidence"][0]["identifier"] == "figs-metaphor"
    restarted = _engine(tmp_path / "restart", resolution_project)
    restored = _call(restarted, "issueResolution.list", {
        "chapter": "1", "verse": "1",
    })["result"]
    assert restored["resolved"] == 1
    assert restored["items"][0]["resolutionId"] == saved["resolutionId"]
    assert restored["items"][0]["recheck"]["model"] == "review-model"


def test_problem_reflags_and_failed_retry_never_restores_a_previous_pass(
    resolution_project, tmp_path,
):
    engine = _engine(tmp_path, resolution_project)
    _save(engine, _check(engine))
    engine.project.mark_issue_resolutions_recheck("1", "1", "running")
    reflagged = engine.project.reconcile_issue_resolutions_after_ai_review(
        "1", "1", [{
            "tool": "translationNotes", "group_id": "figs-metaphor", "check_id": "tn-1",
            "verdict": "problem", "confidence": 0.91,
            "rationale": "The same literal metaphor remains.", "evidence_used": [{
                "title": "Translation Academy", "identifier": "figs-metaphor",
            }],
        }], model="review-model",
    )[0]
    assert reflagged["status"] == "reflagged"
    assert reflagged["recheck"]["status"] == "reflagged"

    engine.project.mark_issue_resolutions_recheck("1", "1", "stale", reason="Verse changed")
    engine.project.mark_issue_resolutions_recheck("1", "1", "running")
    failed = engine.project.mark_issue_resolutions_recheck(
        "1", "1", "failed", reason="Automatic AI recheck failed.", error="Provider unavailable",
    )[0]
    assert failed["status"] == "open"
    assert failed["recheck"]["status"] == "failed"
    assert failed["recheck"]["error"] == "Provider unavailable"
    audit_root = resolution_project / ".apps" / "translationCoreAI" / "audit" / "tit" / "1" / "1"
    events = [
        json.loads(path.read_text(encoding="utf-8"))["event"]
        for path in audit_root.glob("*_recheck_*.json")
    ]
    assert "recheck_reflagged" in events
    assert "recheck_failed" in events


def test_ungrounded_or_low_confidence_pass_cannot_close_a_resolution(
    resolution_project, tmp_path,
):
    engine = _engine(tmp_path, resolution_project)
    _save(engine, _check(engine))
    engine.project.mark_issue_resolutions_recheck("1", "1", "running")

    result = engine.project.reconcile_issue_resolutions_after_ai_review(
        "1", "1", [{
            "tool": "translationNotes", "group_id": "figs-metaphor", "check_id": "tn-1",
            "verdict": "pass", "confidence": 0.79,
            "rationale": "The wording may be acceptable, but evidence is insufficient.",
            "evidence_used": [],
        }], model="review-model",
    )[0]

    assert result["status"] == "open"
    assert result["recheck"]["status"] == "needs_review"
    assert result["recheck"]["verdict"] == "pass"


def test_advanced_pass_waits_for_explicit_proposal_application_before_closing(
    resolution_project, tmp_path,
):
    engine = _engine(tmp_path, resolution_project)
    check = _check(engine)
    _save(engine, check)
    ai_review = {
        "tool": "translationNotes", "group_id": "figs-metaphor", "check_id": "tn-1",
        "verdict": "pass", "confidence": 0.95,
        "rationale": "The revised expression communicates the intended meaning.",
        "evidence_used": [{
            "title": "Translation Academy", "identifier": "figs-metaphor",
        }],
    }
    engine.project.record_ai_review_result("1", "1", {
        "summary": "Grounded pass", "model": "review-model", "checkReviews": [ai_review],
    })

    pending = engine.project.reconcile_issue_resolutions_after_ai_review(
        "1", "1", [ai_review], model="review-model",
        allow_automatic_resolution=False,
    )[0]
    assert pending["status"] == "open"
    assert pending["recheck"]["status"] == "needs_review"

    applied = engine.save_check_selection(
        "1", "1", check["tool"], check["groupId"], check["checkId"],
        [{"text": "beta", "occurrence": 1, "occurrences": 1}], False,
        "human", check["stateFingerprint"],
        {
            "interface": "advanced-ai-proposal", "acceptedAIProposal": True,
            "confidence": 0.95,
        },
    )
    assert applied["review"]["provenance"] == "human"
    assert applied["resolutionLifecycle"][0]["status"] == "resolved"
    restored = _call(engine, "issueResolution.list", {
        "chapter": "1", "verse": "1",
    })["result"]["items"][0]
    assert restored["status"] == "resolved"
    assert restored["recheck"]["status"] == "resolved"
