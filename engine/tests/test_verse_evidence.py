"""
Tests for tc_ai_bridge/verse_evidence.py — the new VerseEvidence composing
object (issue #5 of the Full Bible QA Orchestrator milestone) and its
BridgeEngine-level wiring (verse.evidence), which attaches QaFindings and
cached AI review state on top of the pure tc_ai_bridge resolution.

Uses the same real fixture-project shape as test_bridge_service.py's
fixture_project (Ruth, target text Tamil) rather than mocking
tc_ai_bridge — real bundled Hebrew UHB tokens exist for RUT 1:1 (19 tokens,
verified against the actual resource data, not assumed), so
source_tokens_for_verse is exercised for real here, not stubbed.
"""
import json

import pytest

from bridge_service import BridgeEngine
from greek_room_engine.protocol import EngineRequest
from tc_ai_bridge.tc_project import TranslationCoreProject
from tc_ai_bridge.verse_evidence import resolve_verse_evidence


def call(engine, method, params=None):
    return engine.handle_request(EngineRequest(id="t", method=method, params=params or {})).to_dict()


@pytest.fixture
def fixture_project(tmp_path):
    root = tmp_path / "rut"
    align_dir = root / ".apps" / "translationCore" / "alignmentData" / "rut"
    align_dir.mkdir(parents=True)
    (root / "rut").mkdir(parents=True)

    (root / "manifest.json").write_text(json.dumps({
        "project": {"id": "rut", "name": "Ruth"},
        "target_language": {"id": "tam", "name": "Tamil", "direction": "ltr"},
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

    (root / "rut.usfm").write_text(
        "\\id RUT\n\\c 1\n\\v 1 ஆதியிலே தேவன் வானத்தையும் பூமியையும் படைத்தார்.\n",
        encoding="utf-8",
    )
    return root


def test_resolve_verse_evidence_composes_target_source_and_alignment(fixture_project):
    project = TranslationCoreProject(fixture_project)
    evidence = resolve_verse_evidence(project, "1", "1")

    assert evidence.book_id == "rut"
    assert evidence.target_language_id == "tam"
    assert "தேவன்" in evidence.target_text
    assert "தேவன்" in evidence.target_tokens

    # Real bundled Hebrew source tokens for RUT 1:1 — not the alignment's
    # own single manually-aligned topWord, the FULL verse from UHB.
    assert len(evidence.source_tokens) == 19
    assert all(t.strong for t in evidence.source_tokens if t.strong)

    assert len(evidence.alignment.alignments) == 1
    assert evidence.alignment.alignments[0].bottom_words[0].word == "தேவன்"
    assert evidence.alignment_state == "pending"  # never marked complete in this fixture

    assert evidence.human_decisions == {}
    assert evidence.resolved_at  # non-empty ISO timestamp


def test_resolve_verse_evidence_reflects_prior_human_decisions(fixture_project):
    project = TranslationCoreProject(fixture_project)
    project.record_qa_decision("1", "1", issue_key="some-finding-id", decision="accepted", note="looks fine")

    evidence = resolve_verse_evidence(project, "1", "1")

    assert "some-finding-id" in evidence.human_decisions
    assert evidence.human_decisions["some-finding-id"]["decision"] == "accepted"


def test_resolve_verse_evidence_carries_through_resource_versions(fixture_project):
    project = TranslationCoreProject(fixture_project)
    evidence = resolve_verse_evidence(project, "1", "1", resource_versions={"translationNotes": "v90_unfoldingWord"})
    assert evidence.resource_versions == {"translationNotes": "v90_unfoldingWord"}
    assert evidence.to_dict()["resourceVersions"] == {"translationNotes": "v90_unfoldingWord"}


def test_verse_evidence_to_dict_uses_camel_case_protocol_shape(fixture_project):
    project = TranslationCoreProject(fixture_project)
    d = resolve_verse_evidence(project, "1", "1").to_dict()
    for key in (
        "projectId", "bookId", "targetLanguageId", "targetText", "targetTokens",
        "sourceTokens", "alignment", "alignmentState", "translationHelps",
        "referenceBibles", "resourceProvenance", "resourceVersions", "humanDecisions", "resolvedAt",
    ):
        assert key in d, f"missing {key}"


def test_verse_evidence_protocol_method_attaches_findings_and_ai_review(fixture_project):
    """BridgeEngine.get_verse_evidence is the only place that can attach
    cross-engine QaFindings and AI review state on top of the pure
    tc_ai_bridge VerseEvidence — this proves that composition, not just
    the pure resolver in isolation."""
    engine = BridgeEngine()
    call(engine, "project.open", {"path": str(fixture_project)})

    result = call(engine, "verse.evidence", {"chapter": "1", "verse": "1"})
    assert result["success"] is True
    evidence = result["result"]

    assert evidence["bookId"] == "rut"
    assert len(evidence["sourceTokens"]) == 19
    assert "தேவன்" in evidence["targetText"]
    assert isinstance(evidence["findings"], list)
    assert evidence["aiReviewState"] in {"missing", "current", "stale"}
    assert evidence["aiReview"] is None  # no AI review has ever run in this fixture


def test_verse_evidence_requires_open_project():
    engine = BridgeEngine()
    result = call(engine, "verse.evidence", {"chapter": "1", "verse": "1"})
    assert result["success"] is False
