from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from bridge_service import BridgeEngine
from greek_room_engine.protocol import EngineRequest
from tc_ai_bridge.semantic_mapping import SemanticMappingError
from tc_ai_bridge.secret_store import AppSettings
from tc_ai_bridge.semantic_validation_service import (
    decide_semantic_validation_candidate, list_semantic_validation_candidates,
)
from tc_ai_bridge.tc_project import TranslationCoreProject
from tc_ai_bridge.usfm_passages import UsfmPassageIndex


@pytest.fixture
def php_validation_project(tmp_path: Path, tamil_php_usfm: Path) -> Path:
    root = tmp_path / "php"
    (root / "php").mkdir(parents=True)
    alignment = root / ".apps" / "translationCore" / "alignmentData" / "php"
    alignment.mkdir(parents=True)
    (root / "manifest.json").write_text(json.dumps({
        "project": {"id": "php", "name": "Philippians"},
        "target_language": {"id": "tam", "name": "Tamil"},
        "tc_version": "8", "tc_edit_version": "3.7.0",
    }), encoding="utf-8")
    index = UsfmPassageIndex.from_path(tamil_php_usfm, book_hint="PHP")
    by_chapter: dict[str, dict[str, str]] = {}
    for segment in index.segments:
        by_chapter.setdefault(segment.chapter, {})[segment.verse] = segment.text
    for chapter, verses in by_chapter.items():
        (root / "php" / f"{chapter}.json").write_text(
            json.dumps(verses, ensure_ascii=False), encoding="utf-8",
        )
        (alignment / f"{chapter}.json").write_text(
            json.dumps({verse: {"alignments": [], "wordBank": []} for verse in verses}),
            encoding="utf-8",
        )
    shutil.copyfile(tamil_php_usfm, root / "php.usfm")
    return root


@pytest.fixture
def validation_manifest(tmp_path: Path, tamil_php_usfm: Path, monkeypatch) -> tuple[Path, dict]:
    index = UsfmPassageIndex.from_path(tamil_php_usfm, book_hint="PHP")
    segment = index.segment_for_source_reference("1", "6")
    assert segment is not None
    quote = "என் தேவனை"
    start = segment.text.index(quote)
    candidate = {
        "candidateId": "php-1-3-validation",
        "proposalProvenance": "MACHINE_PROPOSED",
        "validationStatus": "UNCONFIRMED",
        "diagnosticScore": 100,
        "rank": 1,
        "sourceUnit": {
            "id": "translationNotes:gjyv", "tool": "translationNotes",
            "check_id": "gjyv", "group_id": "figs-explicit",
            "source_reference": "PHP 1:3", "source_quote": "τῷ Θεῷ μου",
            "note": "", "occurrence": 1,
        },
        "targetSpans": [{
            "reference": "PHP 1:6", "quote": quote, "start": start, "end": start + len(quote),
        }],
        "relationships": ["CROSS_VERSE", "CROSS_VERSE_REORDERED"],
        "meaningStatus": "PRESERVED", "confidence": 0.99,
        "evidence": {"source": "τῷ Θεῷ μου", "target": quote, "explanation": "Regression mapping"},
        "mappingFingerprint": "fixture-fingerprint",
    }
    manifest = {
        "schema": "bridge.semantic_mapping_validation_set.v0.1",
        "model": "gpt-5.6-test", "candidates": [candidate],
    }
    path = tmp_path / "validation.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("BRIDGE_SEMANTIC_VALIDATION_SET", str(path))
    return path, candidate


def test_validation_queue_confirms_and_persists_append_only_audit(
    php_validation_project, validation_manifest,
):
    project = TranslationCoreProject(php_validation_project)
    original_usfm = (php_validation_project / "php.usfm").read_bytes()
    queue = list_semantic_validation_candidates(project)
    assert queue["available"] is True
    assert queue["summary"]["counts"]["UNCONFIRMED"] == 1
    assert queue["candidates"][0]["projectMatch"] is True

    result = decide_semantic_validation_candidate(
        project, candidate_id="php-1-3-validation", decision="confirmed",
        reviewer="Benz", note="Checked source and target passage",
    )
    assert result["event"]["validationStatus"] == "HUMAN_CONFIRMED"
    assert result["event"]["mapping"]["proposal_provenance"] == "HUMAN_CONFIRMED"
    assert (php_validation_project / "php.usfm").read_bytes() == original_usfm

    reopened = TranslationCoreProject(php_validation_project)
    persisted = list_semantic_validation_candidates(reopened)
    assert persisted["summary"]["counts"]["HUMAN_CONFIRMED"] == 1
    assert persisted["candidates"][0]["reviewDecision"]["reviewer"] == "Benz"
    assert persisted["calibration"]["reviewed"] == 1
    assert persisted["calibration"]["proposalAgreementPercent"] == 100
    audit = json.loads(Path(result["auditPath"]).read_text(encoding="utf-8"))
    assert len(audit["audit"]) == 1

    decide_semantic_validation_candidate(
        reopened, candidate_id="php-1-3-validation", decision="unsure",
        reviewer="Consultant", note="Needs group review",
    )
    audit = json.loads(Path(result["auditPath"]).read_text(encoding="utf-8"))
    assert len(audit["audit"]) == 2
    assert audit["decisions"]["php-1-3-validation"]["decision"] == "unsure"


def test_checked_in_php_queue_matches_the_irvtam_project_exactly(
    php_validation_project, monkeypatch,
):
    monkeypatch.delenv("BRIDGE_SEMANTIC_VALIDATION_SET", raising=False)
    queue = list_semantic_validation_candidates(TranslationCoreProject(php_validation_project))
    assert queue["manifestSha256"] == "c4610f094f85a1530e4ad137412b1434e88a41a04686126e782e1ad3e989c344"
    assert queue["summary"]["total"] == 12
    assert all(candidate["projectMatch"] for candidate in queue["candidates"])


def test_correction_requires_exact_usfm_and_cross_verse_relationship(
    php_validation_project, validation_manifest,
):
    project = TranslationCoreProject(php_validation_project)
    with pytest.raises(SemanticMappingError, match="occur exactly once"):
        decide_semantic_validation_candidate(
            project, candidate_id="php-1-3-validation", decision="corrected", reviewer="Benz",
            corrected_mapping={
                "target_spans": [{"reference": "PHP 1:6", "quote": "not in the verse", "start": None, "end": None}],
                "relationships": ["CROSS_VERSE"], "meaning_status": "PRESERVED", "confidence": 0.9,
            },
        )
    with pytest.raises(SemanticMappingError, match="cross-verse relationship"):
        decide_semantic_validation_candidate(
            project, candidate_id="php-1-3-validation", decision="corrected", reviewer="Benz",
            corrected_mapping={
                "target_spans": [{"reference": "PHP 1:6", "quote": "என் தேவனை", "start": None, "end": None}],
                "relationships": ["SAME_VERSE"], "meaning_status": "PRESERVED", "confidence": 0.9,
            },
        )
    result = decide_semantic_validation_candidate(
        project, candidate_id="php-1-3-validation", decision="corrected", reviewer="Benz",
        corrected_mapping={
            "target_spans": [{"reference": "PHP 1:6", "quote": "என் தேவனை", "start": None, "end": None}],
            "relationships": ["CROSS_VERSE", "CROSS_VERSE_REORDERED"],
            "meaning_status": "PRESERVED", "confidence": 0.95,
        },
    )
    assert result["event"]["validationStatus"] == "HUMAN_CORRECTED"
    assert result["event"]["mapping"]["target_spans"][0]["quote"] == "என் தேவனை"


def test_validation_protocol_requires_reviewer_and_survives_dispatch(
    php_validation_project, validation_manifest, tmp_path,
):
    engine = BridgeEngine(settings=AppSettings(path=tmp_path / "settings.json"))
    opened = engine.handle_request(EngineRequest(
        id="open", method="project.open", params={"path": str(php_validation_project)},
    )).to_dict()
    assert opened["success"] is True
    listed = engine.handle_request(EngineRequest(
        id="list", method="semanticValidation.list", params={},
    )).to_dict()
    assert listed["success"] is True and listed["result"]["summary"]["total"] == 1
    missing_reviewer = engine.handle_request(EngineRequest(
        id="decide", method="semanticValidation.decide",
        params={"candidateId": "php-1-3-validation", "decision": "confirmed", "reviewer": ""},
    )).to_dict()
    assert missing_reviewer["success"] is False
    assert "Reviewer name is required" in missing_reviewer["error"]["message"]
