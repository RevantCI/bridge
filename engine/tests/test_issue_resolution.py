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
