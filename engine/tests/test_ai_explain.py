"""
Tests for Phase 7's ai.explain protocol method (bridge_service.py), which
wires ai_client.OpenAIResponsesClient.prepare_verse_review() into the
protocol for the first time — that method (and run_full_review/
run_quality_review it calls) was real, complete, already-implemented code
from Phases 1-3 with zero protocol wiring and zero test coverage before this
pass (confirmed by the same grep this project used to find the analogous gap
in alignment_reliability.py — see docs/DEVELOPER_HANDOFF.md).

Uses a fake HTTP transport (same BridgeEngine(ai_transport=...) injection
seam as test_ai_alignment_propose.py) so no real OpenAI-compatible API key
is required. Exercises real materialized translationNotes/translationWords
evidence (via a real import + verse.runChecks preflight, not synthetic
fixtures), since prepare_verse_review's evidence-gathering path is the whole
point of wiring this up — a fake-everything test wouldn't prove the real
knowledge_base.py gap (fixed earlier in this phase) actually closed.
"""
import json

import pytest

from bridge_service import BridgeEngine
from greek_room_engine.protocol import EngineRequest
from tc_ai_bridge.secret_store import AppSettings
from tc_ai_bridge.tc_project import TranslationCoreProject


def call(engine, method, params=None):
    return engine.handle_request(EngineRequest(id="t", method=method, params=params or {})).to_dict()


def _metadata(**overrides):
    value = {
        "languageId": "eng", "languageName": "English", "languageDirection": "ltr",
        "projectName": "Titus review", "bibleName": "Test Bible",
    }
    value.update(overrides)
    return value


def _fake_transport_for_full_review(check_ids):
    """Responds to BOTH real AI calls prepare_verse_review can make: the
    gap_fill alignment-proposal call (schema name tc_alignment_proposal —
    responds with no links, since this fixture project has no
    original-language source tokens to align against) and the full-review
    call (schema name tc_full_review — responds with a pass verdict for
    every real materialized check, discovered from the real project rather
    than guessed)."""
    alignment_payload = {"links": [], "implicit_top_ids": [], "target_only_ids": [], "review_notes": []}
    full_review_payload = {
        "summary": "Fake AI summary for test.",
        "check_reviews": [
            {
                "tool": "translationWords", "group_id": "", "check_id": check_id,
                "source_quote": "", "selection_ids": [], "nothing_to_select": True,
                "verdict": "pass", "severity": "info", "rationale": "Fake reviewer.",
                "suggested_correction": "", "confidence": 0.9, "evidence_ids": [],
            }
            for check_id in check_ids
        ],
        "qa_issues": [],
    }

    def transport(url, headers, body, timeout):
        request = json.loads(body.decode("utf-8"))
        schema_name = request.get("text", {}).get("format", {}).get("name", "")
        payload = alignment_payload if schema_name == "tc_alignment_proposal" else full_review_payload
        response = {
            "output_text": json.dumps(payload),
            "usage": {
                "input_tokens": 200, "output_tokens": 80, "total_tokens": 280,
                "input_tokens_details": {"cached_tokens": 0},
            },
        }
        return 200, json.dumps(response).encode("utf-8")

    return transport


@pytest.fixture
def imported_titus_project(tmp_path):
    isolated = AppSettings(path=tmp_path / "settings.json")
    engine = BridgeEngine(settings=isolated)
    source = tmp_path / "57-TIT.usfm"
    source.write_text(
        "\\id TIT\n\\h Titus\n\\c 1\n\\p\n\\v 1 Paul, a servant of God.\n", encoding="utf-8",
    )
    result = engine.import_project(str(source), _metadata())
    # Materializes real translationNotes/translationWords (and, since this phase,
    # translationAcademy is bundled too) so prepare_verse_review has real evidence.
    call(engine, "verse.runChecks", {"chapter": "1", "verse": "1", "checks": ["local"]})
    return isolated, result["path"]


def test_ai_explain_requires_configured_api_key(imported_titus_project, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    settings, project_path = imported_titus_project
    engine = BridgeEngine(settings=settings)
    call(engine, "project.open", {"path": project_path})

    result = call(engine, "ai.explain", {"chapter": "1", "verse": "1"})

    assert result["success"] is False
    assert result["error"]["code"] == "ai_error"


def test_ai_explain_returns_real_evidence_backed_check_reviews(imported_titus_project, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    settings, project_path = imported_titus_project
    settings.set_api_key("sk-test-123")

    # Discover the REAL materialized checkIds for this verse rather than guessing them,
    # so the fake AI response covers exactly what prepare_verse_review will actually ask about.
    project = TranslationCoreProject(project_path)
    real_checks = project.checks_for_verse("1", "1")
    check_ids = [c.get("contextId", {}).get("checkId") for c in real_checks if c.get("contextId", {}).get("checkId")]
    assert check_ids, "expected real materialized translationWords/translationNotes checks for Titus 1:1"

    engine = BridgeEngine(settings=settings, ai_transport=_fake_transport_for_full_review(check_ids))
    call(engine, "project.open", {"path": project_path})

    result = call(engine, "ai.explain", {"chapter": "1", "verse": "1"})

    assert result["success"] is True, result
    body = result["result"]
    assert body["summary"] == "Fake AI summary for test."
    assert len(body["checkReviews"]) == len(check_ids)
    assert all(review["verdict"] == "pass" for review in body["checkReviews"])
    assert body["usage"]["totalTokens"] > 0

    totals = settings.get_ai_usage_totals()
    assert totals["tokens"] >= body["usage"]["totalTokens"]
