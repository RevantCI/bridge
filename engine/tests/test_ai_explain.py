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
import time

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


def _fake_transport_for_full_review(checks):
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
                "tool": check.get("contextId", {}).get("tool", ""),
                "group_id": check.get("contextId", {}).get("groupId", ""),
                "check_id": check.get("contextId", {}).get("checkId", ""),
                "source_quote": check.get("contextId", {}).get("quoteString", ""),
                "selection_ids": [], "nothing_to_select": True,
                "verdict": "pass", "severity": "info", "rationale": "Fake reviewer.",
                "suggested_correction": "", "confidence": 0.9, "evidence_ids": [],
            }
            for check in checks
            if check.get("contextId", {}).get("checkId")
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


def _grounded_fake_transport():
    """Return exact IDs/evidence from Bridge's own structured input.

    This exercises the important half of the contract: the model never gets to
    invent a target word or citation.  The production parser must resolve the
    supplied opaque ID back to text + repeated-word occurrence metadata.
    """
    alignment_payload = {"links": [], "implicit_top_ids": [], "target_only_ids": [], "review_notes": []}

    def transport(url, headers, body, timeout):
        request = json.loads(body.decode("utf-8"))
        schema_format = request.get("text", {}).get("format", {})
        assert schema_format.get("type") == "json_schema"
        assert schema_format.get("strict") is True
        if schema_format.get("name") == "tc_alignment_proposal":
            payload = alignment_payload
        else:
            review_input = json.loads(request["input"])
            target_id = review_input["target_bottomWords"][0]["id"]
            payload = {
                "summary": "Grounded automatic review.",
                "check_reviews": [
                    {
                        "tool": check["tool"], "group_id": check["groupId"],
                        "check_id": check["checkId"], "source_quote": check.get("source_quote") or "",
                        "selection_ids": [target_id], "nothing_to_select": False,
                        "verdict": "pass", "severity": "info", "rationale": "Supported by bundled evidence.",
                        "suggested_correction": "", "confidence": 0.91,
                        "evidence_ids": check["evidence_ids"][:1],
                    }
                    for check in review_input["translationCore_checks"]
                ],
                "qa_issues": [],
            }
        return 200, json.dumps({
            "output_text": json.dumps(payload),
            "usage": {"input_tokens": 200, "output_tokens": 80, "total_tokens": 280,
                      "input_tokens_details": {"cached_tokens": 0}},
        }).encode("utf-8")

    return transport


def _wait_for_ai_job(engine, job_id, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = call(engine, "ai.review.status", {"jobId": job_id})
        assert status["success"] is True, status
        snapshot = status["result"]
        if snapshot["state"] in {"succeeded", "failed", "cancelled"}:
            return snapshot
        time.sleep(0.02)
    raise AssertionError("AI review job did not finish")


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

    engine = BridgeEngine(settings=settings, ai_transport=_fake_transport_for_full_review(real_checks))
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


def test_advanced_background_review_keeps_proposals_uncommitted(imported_titus_project, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    settings, project_path = imported_titus_project
    settings.set_api_key("sk-test-123")
    engine = BridgeEngine(settings=settings, ai_transport=_grounded_fake_transport())
    call(engine, "project.open", {"path": project_path})
    before = engine.project.check_reviews_for_verse("1", "1")

    started = call(engine, "ai.review.start", {
        "scope": "verse", "chapter": "1", "verse": "1", "mode": "advanced",
    })
    assert started["success"] is True, started
    snapshot = _wait_for_ai_job(engine, started["result"]["jobId"])

    assert snapshot["state"] == "succeeded", snapshot
    result = snapshot["latestResult"]["result"]
    assert result["checkReviews"]
    assert result["appliedSelections"] == []
    assert result["checkReviews"][0]["proposed_selections"][0]["text"] == "Paul"
    after = engine.project.check_reviews_for_verse("1", "1")
    assert [item["selectionStatus"] for item in after] == [item["selectionStatus"] for item in before]

    listed = call(engine, "check.listForVerse", {"chapter": "1", "verse": "1"})["result"]
    assert listed["aiReviewState"] == "current"
    assert listed["aiReviews"]
    assert listed["checks"][0]["evaluationStatus"] == "passed"

    restored = call(engine, "ai.review.listForChapter", {"chapter": "1"})
    assert restored["success"] is True
    assert restored["result"]["current"] == 1
    assert restored["result"]["reviewsByVerse"]["1"]

    resumed = call(engine, "ai.review.start", {
        "scope": "chapter", "chapter": "1", "verse": "1", "mode": "advanced",
    })
    resumed_snapshot = _wait_for_ai_job(engine, resumed["result"]["jobId"])
    assert resumed_snapshot["state"] == "succeeded"
    assert resumed_snapshot["totalVerses"] == 0
    assert resumed_snapshot["skippedCurrentVerses"] == 1


def test_basic_background_review_applies_only_grounded_safe_selections(imported_titus_project, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    settings, project_path = imported_titus_project
    settings.set_api_key("sk-test-123")
    engine = BridgeEngine(settings=settings, ai_transport=_grounded_fake_transport())
    call(engine, "project.open", {"path": project_path})

    started = call(engine, "ai.review.start", {
        "scope": "verse", "chapter": "1", "verse": "1", "mode": "basic",
    })
    snapshot = _wait_for_ai_job(engine, started["result"]["jobId"])

    assert snapshot["state"] == "succeeded", snapshot
    result = snapshot["latestResult"]["result"]
    assert result["appliedSelections"], result
    # Checks without explicit resource evidence are retained for human review,
    # never silently called safe merely because the model returned high confidence.
    assert all("reason" in item for item in result["skippedSelections"])
    native = engine.project.check_reviews_for_verse("1", "1")
    applied_ids = {item["checkId"] for item in result["appliedSelections"]}
    for item in native:
        if item["checkId"] in applied_ids:
            assert item["selectionStatus"] == "selected"
            assert item["provenance"] == "bridge_ai"
    assert engine.project.ai_review_cache_status("1", "1") == "current"


def test_basic_ai_never_overwrites_a_human_selection(imported_titus_project, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    settings, project_path = imported_titus_project
    settings.set_api_key("sk-test-123")
    engine = BridgeEngine(settings=settings, ai_transport=_grounded_fake_transport())
    call(engine, "project.open", {"path": project_path})
    check = engine.project.check_reviews_for_verse("1", "1")[0]
    validation = engine.project.validate_check_selection(
        "1", "1", check["tool"], check["groupId"], check["checkId"],
        [{"text": "servant", "occurrence": 1, "occurrences": 1}], False,
    )
    assert validation["valid"] is True
    engine.project.save_check_selection(
        "1", "1", check["tool"], check["groupId"], check["checkId"],
        validation["selections"], False, "human", validation["stateFingerprint"],
        username="Human Reviewer",
    )

    started = call(engine, "ai.review.start", {
        "scope": "verse", "chapter": "1", "verse": "1", "mode": "basic",
    })
    snapshot = _wait_for_ai_job(engine, started["result"]["jobId"])

    assert snapshot["state"] == "succeeded", snapshot
    result = snapshot["latestResult"]["result"]
    protected = [item for item in result["skippedSelections"] if item["checkId"] == check["checkId"]]
    assert protected and "may not replace" in protected[0]["reason"]
    current = engine.project.check_review("1", "1", check["tool"], check["groupId"], check["checkId"])
    assert current["provenance"] == "human"
    assert current["selections"][0]["text"] == "servant"
