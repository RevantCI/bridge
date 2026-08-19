"""
Tests for BridgeEngine — the unified dispatcher composing GreekRoomEngine
with real tc_ai_bridge business logic.

Uses a minimal but spec-accurate fixture translationCore project (built
directly from reading TranslationCoreProject's actual parsing code, not
guessed) rather than mocking tc_ai_bridge — the whole point of Phase 1 is
proving the real modules work behind the new protocol.
"""
import json
import shutil
from pathlib import Path

import pytest

from bridge_service import BridgeEngine
from greek_room_engine.protocol import EngineRequest


@pytest.fixture
def fixture_project(tmp_path):
    root = tmp_path / "rut"
    align_dir = root / ".apps" / "translationCore" / "alignmentData" / "rut"
    align_dir.mkdir(parents=True)
    (root / "rut").mkdir(parents=True)

    (root / "manifest.json").write_text(json.dumps({
        "project": {"id": "rut", "name": "Ruth"},
        "target_language": {"id": "tam", "name": "Tamil"},
        "tc_version": "8", "tc_edit_version": "3.7.0",
    }), encoding="utf-8")

    (align_dir / "1.json").write_text(json.dumps({
        "1": {
            "alignments": [{
                "topWords": [{"word": "אֱלֹהִ֑ים", "strong": "H430", "occurrence": 1, "occurrences": 1}],
                "bottomWords": [{"word": "தேவன்", "occurrence": 1, "occurrences": 1}],
            }],
            "wordBank": [],
        }
    }, ensure_ascii=False), encoding="utf-8")

    (root / "rut" / "1.json").write_text(json.dumps({
        "1": "ஆதியிலே தேவன் வானத்தையும் பூமியையும் படைத்தார்."
    }, ensure_ascii=False), encoding="utf-8")

    return root


def call(engine, method, params=None):
    return engine.handle_request(EngineRequest(id="t", method=method, params=params or {})).to_dict()


def test_ping_and_info_work_without_a_project():
    engine = BridgeEngine()
    assert call(engine, "ping")["result"] == {"pong": True}
    info = call(engine, "engine.info")["result"]
    assert info["projectOpen"] is False
    assert "greekRoom" in info


def test_open_real_fixture_project(fixture_project):
    engine = BridgeEngine()
    result = call(engine, "project.open", {"path": str(fixture_project)})
    assert result["success"] is True
    assert result["result"]["bookId"] == "rut"
    assert result["result"]["targetLanguage"] == "Tamil"
    assert result["result"]["chapters"] == ["1"]


def test_verse_get_returns_real_alignment_data(fixture_project):
    engine = BridgeEngine()
    call(engine, "project.open", {"path": str(fixture_project)})
    result = call(engine, "verse.get", {"chapter": "1", "verse": "1"})["result"]
    assert "தேவன்" in result["text"]
    assert result["alignment"]["alignments"][0]["bottomWords"][0]["word"] == "தேவன்"


def test_clean_verse_has_no_findings(fixture_project):
    engine = BridgeEngine()
    call(engine, "project.open", {"path": str(fixture_project)})
    result = call(engine, "verse.runChecks", {"chapter": "1", "verse": "1", "checks": ["local", "greekroom"]})
    assert result["findings"] == []


def test_mixed_script_verse_is_flagged_by_greek_room():
    engine = BridgeEngine()
    findings = engine.greek_room.check_verse(
        project_id="p", lang_code="tam", ref="RUT 1:1", text="தேவன்aஆதி", checks=["wildebeest"],
    )
    assert any(f.check_type == "wildebeest.script.mixed" for f in findings)


def test_decide_verse_writes_real_qa_decision_file(fixture_project):
    engine = BridgeEngine()
    call(engine, "project.open", {"path": str(fixture_project)})
    result = call(engine, "verse.decide", {
        "chapter": "1", "verse": "1", "findingId": "test-finding",
        "status": "accepted", "comment": "looks fine",
    })["result"]
    written = Path(result["recordedAt"])
    assert written.exists()
    data = json.loads(written.read_text(encoding="utf-8"))
    assert data["decision"] == "accepted"
    assert data["issueKey"] == "test-finding"


def test_edit_verse_creates_transaction_backup(fixture_project):
    engine = BridgeEngine()
    call(engine, "project.open", {"path": str(fixture_project)})
    result = call(engine, "verse.edit", {"chapter": "1", "verse": "1", "newText": "test"})
    assert result["result"]["committed"] is True
    tx_dir = fixture_project / ".apps" / "translationCoreAI" / "transactions"
    assert any(tx_dir.glob("*.json"))


def test_open_missing_project_fails_gracefully():
    engine = BridgeEngine()
    result = call(engine, "project.open", {"path": "/no/such/path"})
    assert result["success"] is False
    assert result["error"]["code"] == "project_error"


def test_verse_op_before_project_open_fails_gracefully():
    engine = BridgeEngine()
    result = call(engine, "chapter.verses", {"chapter": "1"})
    assert result["success"] is False
    assert result["error"]["code"] == "project_error"


def test_settings_get_has_safe_defaults(tmp_path, monkeypatch):
    # AppSettings() with no explicit path reads a real, persistent location
    # on the machine (and get_api_key() also checks $OPENAI_API_KEY) — that
    # is correct production behavior, but tests must not depend on or leak
    # into the real machine's settings. Isolate explicitly.
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    from tc_ai_bridge.secret_store import AppSettings
    isolated = AppSettings(path=tmp_path / "settings.json")
    engine = BridgeEngine(settings=isolated)
    result = call(engine, "settings.get")["result"]
    assert result["hasApiKey"] is False
    assert "model" in result


def test_settings_get_reflects_a_saved_api_key(tmp_path, monkeypatch):
    """Documents the real (correct) behavior: once a key is saved, hasApiKey
    flips to True. This is what you're seeing on a machine that already has
    a saved key or OPENAI_API_KEY set — not a bug."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    from tc_ai_bridge.secret_store import AppSettings
    isolated = AppSettings(path=tmp_path / "settings.json")
    engine = BridgeEngine(settings=isolated)
    call(engine, "settings.set", {"apiKey": "sk-test-123"})
    result = call(engine, "settings.get")["result"]
    assert result["hasApiKey"] is True


def test_qaissue_categorization_matches_real_local_checks_codes():
    """Locks in the code/title -> FindingCategory mapping against the
    ACTUAL codes local_checks.py produces (checked against source, not
    assumed) so the UI's tN/tW/Alignment color-coding stays correct."""
    from bridge_service import _categorize_qaissue
    from tc_ai_bridge.models import QAIssue
    from greek_room_engine.models.finding import FindingCategory

    cases = [
        (QAIssue("ALIGN_DUP_TOP", "critical", "x", "y"), FindingCategory.ALIGNMENT),
        (QAIssue("WA_INVALID", "high", "x", "y", "translationCore"), FindingCategory.ALIGNMENT),
        (QAIssue("USFM_BALANCE", "high", "x", "y", "local"), FindingCategory.STRUCTURE),
        (QAIssue("SRC_REPEAT_WORD", "medium", "x", "y"), FindingCategory.REPETITION),
        (QAIssue("TGT_HIDDEN_CHAR", "editorial", "x", "y"), FindingCategory.UNICODE),
        (QAIssue("TC_PENDING", "high", "translationWords: unchecked item", "y", "translationCore"), FindingCategory.TRANSLATION_WORD),
        (QAIssue("TC_INVALIDATED", "high", "translationNotes: recheck required", "y", "translationCore"), FindingCategory.TRANSLATION_NOTE),
        (QAIssue("TC_COMMENTS", "info", "Reviewer comments present", "y", "translationCore"), FindingCategory.CONSISTENCY),
    ]
    for issue, expected in cases:
        assert _categorize_qaissue(issue) == expected, f"{issue.code} -> expected {expected}"
