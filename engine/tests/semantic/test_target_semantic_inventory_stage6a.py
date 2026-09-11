from __future__ import annotations

import json
from pathlib import Path

from bridge_service import BridgeEngine
from greek_room_engine.protocol import EngineRequest
from tc_ai_bridge.passage_semantic_runtime import PassageSemanticRuntime
from tc_ai_bridge.target_semantic_inventory import (
    TargetAnalyzerProvider, TargetSemanticInventory,
)
from tc_ai_bridge.tc_project import TranslationCoreProject


TAMIL = {
    "3": "நற்செய்தி உங்களுக்கு அறிவிக்கப்பட்ட நாள் முதல் இதுவரைக்கும் நீங்கள் எங்களோடு ஊழியத்தில் ஐக்கியப்பட்டிருப்பதால்,",
    "4": "நான் பண்ணுகிற ஒவ்வொரு விண்ணப்பத்திலும் உங்கள் அனைவருக்காகவும் எப்பொழுதும் மகிழ்ச்சியோடு ஜெபம் செய்து,",
    "5": "உங்களில் நல்ல செயலைத் தொடங்கினவர் அதை இயேசு கிறிஸ்துவின் நாள் வரை நடத்தி வருவார் என்று நம்பி,",
    "6": "நான் உங்களை நினைக்கும் போதெல்லாம் என் தேவனை ஸ்தோத்திரிக்கிறேன்.",
}


def _runtime(tmp_path: Path, *, book: str = "PHP", language: str = "ta",
             chapters: dict[str, dict[str, str]] | None = None, usfm: bool = True) -> PassageSemanticRuntime:
    root = tmp_path / f"{book}-{language}"
    lower = book.lower()
    (root / lower).mkdir(parents=True)
    (root / ".apps" / "translationCore" / "alignmentData" / lower).mkdir(parents=True)
    chapters = chapters or {"1": TAMIL}
    (root / "manifest.json").write_text(json.dumps({
        "project": {"id": lower, "name": book}, "target_language": {"id": language},
        "resource": {"id": "test"}, "tc_version": "8",
    }), encoding="utf-8")
    for chapter, verses in chapters.items():
        (root / lower / f"{chapter}.json").write_text(json.dumps(verses, ensure_ascii=False), encoding="utf-8")
        (root / ".apps" / "translationCore" / "alignmentData" / lower / f"{chapter}.json").write_text(
            json.dumps({v: {"alignments": [], "wordBank": []} for v in verses}), encoding="utf-8",
        )
    if usfm:
        lines = [f"\\id {book}", "\\s OLD NON SCRIPTURE HEADING", "\\p", "\\q1"]
        for chapter, verses in chapters.items():
            lines.append(f"\\c {chapter}")
            lines.extend(f"\\v {v} OLD IMPORTED WORDING" for v in verses)
        (root / f"{lower}.usfm").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return PassageSemanticRuntime(TranslationCoreProject(root), f"project-{book}-{language}")


def test_stage5_golden_freeze_and_tamil_target_inventory_without_source_leakage(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    first = runtime.target_semantic.build_range("1", "3", "1", "6")
    runtime.source_semantic.build_range("1", "3", "1", "6")
    second = runtime.target_semantic.build_range("1", "3", "1", "6")
    assert first["targetSemanticFingerprint"] == second["targetSemanticFingerprint"]
    assert second["cacheStatus"] == "HIT"
    assert first["diagnostics"]["targetSemanticUnits"] > 0
    assert "OLD IMPORTED" not in json.dumps(first, ensure_ascii=False)
    assert "OLD NON SCRIPTURE" not in json.dumps(first, ensure_ascii=False)
    assert {marker["kind"] for marker in first["structureMarkers"]} >= {"PARAGRAPH", "POETRY"}
    assert not any(key in first for key in ("semanticRelationships", "meaningStatus", "locationConfidence"))


def test_current_target_edit_invalidates_old_inventory_and_changes_fingerprint(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    first = runtime.target_semantic.build_range("1", "3")
    path = runtime.project.book_dir / "1.json"
    chapter = json.loads(path.read_text(encoding="utf-8")); chapter["3"] += " மாற்றம்"
    path.write_text(json.dumps(chapter, ensure_ascii=False), encoding="utf-8")
    second = runtime.target_semantic.build_range("1", "3")
    assert second["fingerprint"] != first["fingerprint"]
    try:
        runtime.target_semantic.get_range(first["id"])
        assert False, "stale inventory must not be served"
    except Exception as exc:
        assert "stale" in str(exc).lower()


def test_exact_content_revert_safely_reactivates_content_addressed_inventory(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    path = runtime.project.book_dir / "1.json"
    original = path.read_text(encoding="utf-8")
    first = runtime.target_semantic.build_range("1", "3")

    chapter = json.loads(original); chapter["3"] += " மாற்றம்"
    path.write_text(json.dumps(chapter, ensure_ascii=False), encoding="utf-8")
    changed = runtime.target_semantic.build_range("1", "3")
    assert changed["id"] != first["id"]

    path.write_text(original, encoding="utf-8")
    restored = runtime.target_semantic.build_range("1", "3")
    assert restored["id"] == first["id"]
    assert restored["fingerprint"] == first["fingerprint"]
    assert runtime.target_semantic.get_range(first["id"])["id"] == first["id"]


def test_tamil_unicode_spans_quantifiers_and_agglutinative_subtokens(tmp_path: Path) -> None:
    result = _runtime(tmp_path).target_semantic.build_range("1", "3", "1", "6")
    assert result["capabilities"]["script"] == "Tamil"
    assert result["diagnostics"]["quantifierUnits"] >= 1
    assert result["diagnostics"]["subtokensMorphemes"] >= 1
    texts = TAMIL
    for span in result["searchSpans"]:
        text = texts[span["displayedReference"].split(":")[-1]]
        assert text[span["startCodePoint"]:span["endCodePoint"]] == span["quote"]
        assert len(span["quoteSha256"]) == 64


def test_whitespace_provider_detects_negation_quantifier_and_ambiguous_pronoun(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path, language="en", chapters={"1": {"1": "They did not give all gifts."}})
    result = runtime.target_semantic.build_range("1", "1")
    assert result["diagnostics"]["negationUnits"] == 1
    assert result["diagnostics"]["quantifierUnits"] == 1
    referent = next(unit for unit in result["units"] if unit["kind"] == "REFERENT")
    assert referent["semanticFeatures"]["interpretation"] == "AMBIGUOUS_PRONOUN"
    assert referent["auditEligibility"] == "REVIEW_ONLY"


def test_no_space_language_preserves_large_span_instead_of_inventing_boundaries(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path, language="ja", chapters={"1": {"1": "初めに神が天と地を造った。"}})
    result = runtime.target_semantic.build_range("1", "1")
    assert result["capabilities"]["tokenization"] == "FALLBACK"
    assert result["diagnostics"]["unknownUnsegmentedSpans"] == 1
    lexical = [u for u in result["units"] if u["kind"] == "LEXICAL"]
    assert len(lexical) == 1


def test_rtl_combining_script_and_morphology_absence_are_supported(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path, language="he", chapters={"1": {"1": "לֹא כָל־דָּבָר"}})
    result = runtime.target_semantic.build_range("1", "1")
    assert result["capabilities"]["direction"] == "RTL"
    assert result["capabilities"]["morphology"] == "UNAVAILABLE"
    assert result["diagnostics"]["graphemeClusters"] < result["diagnostics"]["targetCharacters"]


class MorphProvider(TargetAnalyzerProvider):
    provider_id = "test-morphology"
    version = "v2"

    def supports(self, language_tag: str) -> bool:
        return language_tag == "ta"

    def capabilities(self) -> dict[str, str]:
        return {"morphology": "AVAILABLE", "pos": "AVAILABLE"}

    def analyze_token(self, token: dict) -> list[dict]:
        return [{"kind": "MORPHOLOGICAL", "dimension": "OTHER",
                 "interpretation": "TEST_MORPHOLOGY", "confidence": 0.9}]


def test_optional_morphology_provider_is_versioned_and_analyzer_derived(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    baseline = runtime.target_semantic.build_range("1", "3")
    enriched = TargetSemanticInventory(runtime, [MorphProvider()]).build_range("1", "3")
    assert baseline["capabilities"]["morphology"] == "UNAVAILABLE"
    assert enriched["capabilities"]["morphology"] == "AVAILABLE"
    assert enriched["fingerprint"] != baseline["fingerprint"]
    assert any(unit["kind"] == "MORPHOLOGICAL" and unit["provenance"] == "LANGUAGE_ANALYZER"
               for unit in enriched["units"])


def test_span_lattice_is_bounded_and_punctuation_does_not_bridge_phrases(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path, language="en", chapters={"1": {"1": "One, two three four five."}})
    result = runtime.target_semantic.build_range("1", "1")
    token_count = result["diagnostics"]["orthographicTokens"]
    assert result["diagnostics"]["searchSpans"] <= token_count * 5 + 2
    assert not any(span["kind"] == "PHRASE" and "," in span["quote"] for span in result["searchSpans"])
    assert not any(unit["rawSurface"] in {",", "."} for unit in result["units"])


def test_paragraph_and_cross_chapter_search_neighborhoods(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path, language="en", chapters={"1": {"1": "First."}, "2": {"1": "Second."}})
    result = runtime.target_semantic.build_range("1", "1", "2", "1")
    scopes = {item["scopeKind"] for item in result["searchNeighborhoods"]}
    assert "PARAGRAPH" in scopes
    assert "CHAPTER_BOUNDARY_CONTINUATION" in scopes
    assert "SELECTED_PASSAGE" in scopes


def test_stage6a_creates_no_alignment_or_qa_records(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    runtime.target_semantic.build_range("1", "3", "1", "6")
    with runtime.repository._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM semantic_relationships").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM lexical_groups").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM qa_findings").fetchone()[0] == 0


def test_minimal_target_semantic_protocol_apis(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    engine = BridgeEngine()
    engine.project = runtime.project
    engine.passage_semantic_runtime = runtime
    built_response = engine.handle_request(EngineRequest(
        id="build", method="targetSemantic.buildRange",
        params={"chapter": "1", "verse": "3", "endChapter": "1", "endVerse": "6"},
    )).to_dict()
    assert built_response["success"] is True, built_response
    built = built_response["result"]
    inventory_id, unit_id = built["id"], built["units"][0]["id"]
    calls = [
        ("targetSemantic.getRange", {"inventoryId": inventory_id}),
        ("targetSemantic.getUnit", {"unitId": unit_id}),
        ("targetSemantic.getDiagnostics", {"inventoryId": inventory_id}),
        ("targetSemantic.getSearchSpans", {"inventoryId": inventory_id}),
        ("targetSemantic.getCapabilities", {"inventoryId": inventory_id}),
    ]
    assert all(engine.handle_request(EngineRequest(id=str(i), method=m, params=p)).to_dict()["success"]
               for i, (m, p) in enumerate(calls))
