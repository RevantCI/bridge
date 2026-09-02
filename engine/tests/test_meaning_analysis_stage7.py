from __future__ import annotations

import json
import hashlib
from pathlib import Path
import unicodedata

import pytest

from bridge_service import BridgeEngine
from greek_room_engine.protocol import EngineRequest
from tc_ai_bridge.meaning_analysis import DeterministicMeaningComparator, MeaningAnalysisEngine, MeaningPolicy
from tc_ai_bridge.semantic_location import SemanticLocationEngine
from tc_ai_bridge.semantic_location import SemanticEmbeddingProvider
from tc_ai_bridge.passage_semantic_runtime import PassageSemanticRuntime
from tc_ai_bridge.tc_project import TranslationCoreProject


TAMIL = {
    "3": "நற்செய்தி உங்களுக்கு அறிவிக்கப்பட்ட நாள் முதல் இதுவரைக்கும் நீங்கள் எங்களோடு ஊழியத்தில் ஐக்கியப்பட்டிருப்பதால்,",
    "4": "நான் பண்ணுகிற ஒவ்வொரு விண்ணப்பத்திலும் உங்கள் அனைவருக்காகவும் எப்பொழுதும் மகிழ்ச்சியோடு ஜெபம் செய்து,",
    "5": "உங்களில் நல்ல செயலைத் தொடங்கினவர் அதை இயேசு கிறிஸ்துவின் நாள் வரை நடத்தி வருவார் என்று நம்பி,",
    "6": "நான் உங்களை நினைக்கும் போதெல்லாம் என் தேவனை ஸ்தோத்திரிக்கிறேன்.",
}
PHP_PAIRS = [
    ("εὐχαριστέω", "ஸ்தோத்திரிக்கிறேன்"), ("θεός", "தேவனை"), ("μνεία", "நினைக்கும்"),
    ("πάντοτε", "எப்பொழுதும்"), ("δέησις", "விண்ணப்பத்திலும்"), ("χαρά", "மகிழ்ச்சியோடு"),
    ("ποιέω", "செய்து"), ("κοινωνία", "ஐக்கியப்பட்டிருப்பதால்"), ("εὐαγγέλιον", "நற்செய்தி"),
    ("πρῶτος", "முதல்"), ("ἡμέρα", "நாள்"), ("νῦν", "இதுவரைக்கும்"), ("πείθω", "நம்பி"),
    ("ἐνάρχομαι", "தொடங்கினவர்"), ("ἔργον", "செயலைத்"), ("ἀγαθός", "நல்ல"),
    ("ἐπιτελέω", "நடத்தி வருவார்"), ("χριστός", "கிறிஸ்துவின்"), ("Ἰησοῦς", "இயேசு"),
]


def _runtime(tmp_path: Path, *, book: str = "PHP", language: str = "ta",
             chapters: dict[str, dict[str, str]] | None = None) -> PassageSemanticRuntime:
    root = tmp_path / f"{book}-{language}"; lower = book.lower()
    (root / lower).mkdir(parents=True)
    alignment = root / ".apps" / "translationCore" / "alignmentData" / lower
    alignment.mkdir(parents=True)
    chapters = chapters or {"1": TAMIL}
    (root / "manifest.json").write_text(json.dumps({
        "project": {"id": lower, "name": book}, "target_language": {"id": language},
        "resource": {"id": "test"}, "tc_version": "8",
    }), encoding="utf-8")
    lines = [f"\\id {book}"]
    for chapter, verses in chapters.items():
        (root / lower / f"{chapter}.json").write_text(json.dumps(verses, ensure_ascii=False), encoding="utf-8")
        (alignment / f"{chapter}.json").write_text(json.dumps({
            ref: {"alignments": [], "wordBank": []} for ref in verses
        }), encoding="utf-8")
        lines.extend([f"\\c {chapter}", "\\p"])
        lines.extend(f"\\v {ref} OLD IMPORTED" for ref in verses)
    (root / f"{lower}.usfm").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return PassageSemanticRuntime(TranslationCoreProject(root), f"meaning-{book}-{language}-{tmp_path.name}")


def _norm(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value).casefold().split())


class FixtureEmbeddingProvider(SemanticEmbeddingProvider):
    provider_id = "stage7-fixture"; provider_version = "v1"; model_id = "stage7-fixture"
    normalization = "L2"; languages = ("el", "hbo", "arc", "ta", "en"); offline = True; available = True
    def __init__(self, vectors: dict[str, list[float]]):
        self.vectors = {_norm(key): value for key, value in vectors.items()}
        self.dimensions = len(next(iter(vectors.values())))
        self.model_hash = hashlib.sha256(json.dumps(self.vectors, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self.vectors.get(_norm(text), [0.0] * self.dimensions) for text in texts]


def paired_vectors(pairs: list[tuple[str, str]]) -> dict[str, list[float]]:
    result = {}
    for index, (source, target) in enumerate(pairs):
        vector = [0.0] * len(pairs); vector[index] = 1.0
        result[source] = vector; result[target] = vector
    return result


@pytest.mark.parametrize(("source", "target", "dimension", "expected"), [
    ("all", "some", "QUANTITY", "CONTRADICTED"),
    ("not", "yes", "POLARITY", "CONTRADICTED"),
    ("before", "after", "TEMPORAL_ASPECTUAL", "CONTRADICTED"),
    ("2", "3", "QUANTITY", "CONTRADICTED"),
    ("complete", "continue", "TEMPORAL_ASPECTUAL", "TARGET_WEAKENS_SPECIFICITY"),
    ("certain", "may", "OTHER", "TARGET_WEAKENS_SPECIFICITY"),
    ("God", "man", "PARTICIPANT", "CONTRADICTED"),
    ("give to him", "he gives", "CLAUSE_RELATION", "CONTRADICTED"),
    ("city", "holy city", "LEXICAL_CONTENT", "TARGET_ADDS_SPECIFICITY"),
    ("heart was lifted", "became proud", "LEXICAL_CONTENT", "NOT_EXPLICIT_BUT_RECOVERABLE"),
    ("he", "the man", "PARTICIPANT", "NOT_EXPLICIT_BUT_RECOVERABLE"),
    ("all", "all", "QUANTITY", "PRESERVED"),
])
def test_deterministic_high_priority_component_rules(
    source: str, target: str, dimension: str, expected: str,
) -> None:
    status, confidence, _kind, _explanation = DeterministicMeaningComparator.compare(
        source, target, dimension,
    )
    assert status.value == expected
    assert confidence >= 0.8


def test_all_to_some_location_remains_fixed_and_meaning_is_contradicted(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path, language="en", chapters={"1": {"3": "some"}})
    location = SemanticLocationEngine(
        runtime, FixtureEmbeddingProvider(paired_vectors([("πᾶς", "some")])),
    ).run_range("1", "3")
    before = json.dumps(location["relationships"], sort_keys=True)
    meaning = MeaningAnalysisEngine(runtime).run_range(
        "1", "3", location_run_id=location["id"],
    )
    source = {unit["id"]: unit for unit in runtime.source_semantic.build_range("1", "3")["units"]}
    assessment = next(
        item for item in meaning["assessments"]
        if any(source[unit_id]["kind"] == "QUANTIFIER" for unit_id in item["sourceSemanticUnitIds"])
    )
    assert assessment["meaningStatus"] == "CONTRADICTED"
    assert any(component["coverageDimension"] == "QUANTITY"
               and component["status"] == "CONTRADICTED"
               for component in assessment["componentAssessments"])
    assert json.dumps(runtime.semantic_location.get_range(location["id"])["relationships"], sort_keys=True) == before
    assert "MISSING" not in json.dumps(meaning)


def test_unlocated_ambiguous_and_search_incomplete_are_unverifiable(tmp_path: Path) -> None:
    absent_runtime = _runtime(tmp_path / "absent", language="en", chapters={"1": {"3": "unrelated"}})
    absent_location = SemanticLocationEngine(absent_runtime).run_range("1", "3")
    absent = MeaningAnalysisEngine(absent_runtime).run_range(
        "1", "3", location_run_id=absent_location["id"],
    )
    reasons = {item["reason"] for item in absent["assessments"]}
    assert "NO_LOCATED_REALIZATION" in reasons
    assert all(item["meaningStatus"] == "UNVERIFIABLE"
               for item in absent["assessments"] if item["reason"] != "ASSESSED")

    ambiguous_runtime = _runtime(tmp_path / "ambiguous", language="en", chapters={"1": {"3": "some some"}})
    provider = FixtureEmbeddingProvider(paired_vectors([("πᾶς", "some")]))
    ambiguous_location = SemanticLocationEngine(ambiguous_runtime, provider).run_range("1", "3")
    ambiguous = MeaningAnalysisEngine(ambiguous_runtime).run_range(
        "1", "3", location_run_id=ambiguous_location["id"],
    )
    assert any(item["reason"] == "AMBIGUOUS_LOCATION" and item["locationReviewRequired"]
               for item in ambiguous["assessments"])

    budget_runtime = _runtime(tmp_path / "budget", language="en", chapters={"1": {"3": "some"}})
    budget_location = SemanticLocationEngine(budget_runtime, provider).run_range(
        "1", "3", max_candidate_evaluations=1,
    )
    budget = MeaningAnalysisEngine(budget_runtime).run_range(
        "1", "3", location_run_id=budget_location["id"],
    )
    assert any(item["reason"] == "SEARCH_INCOMPLETE" for item in budget["assessments"])


def test_split_merged_and_cross_verse_relationship_identity_is_preserved(tmp_path: Path) -> None:
    split_runtime = _runtime(tmp_path / "split", language="en", chapters={"1": {"3": "alpha middle omega"}})
    vectors = {"θεός": [1.0, 1.0], "alpha": [1.0, 0.0], "omega": [0.0, 1.0],
               "alpha … omega": [1.0, 1.0]}
    split_location = SemanticLocationEngine(
        split_runtime, FixtureEmbeddingProvider(vectors),
    ).run_range("1", "3")
    split_ids = {item["id"] for item in split_location["relationships"]}
    split_meaning = MeaningAnalysisEngine(split_runtime).run_range(
        "1", "3", location_run_id=split_location["id"],
    )
    assert {item["semanticLocationRelationshipId"] for item in split_meaning["assessments"]} == split_ids
    assert any("SPLIT" in item["properties"] for item in split_location["relationships"])

    merge_runtime = _runtime(tmp_path / "merge", language="en", chapters={"1": {"3": "combined"}})
    merge_location = SemanticLocationEngine(
        merge_runtime, FixtureEmbeddingProvider({"θεός": [1.0], "μνεία": [1.0], "combined": [1.0]}),
    ).run_range("1", "3")
    merge_meaning = MeaningAnalysisEngine(merge_runtime).run_range(
        "1", "3", location_run_id=merge_location["id"],
    )
    assert len(merge_meaning["assessments"]) == len(merge_location["relationships"])
    assert any("MERGED" in item["properties"] for item in merge_location["relationships"])


def test_php_completion_is_independent_and_location_relationships_do_not_change(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    location = SemanticLocationEngine(
        runtime, FixtureEmbeddingProvider(paired_vectors(PHP_PAIRS)),
    ).run_range("1", "3", "1", "6")
    location_snapshot = json.dumps(location["relationships"], sort_keys=True)
    source_inventory = runtime.source_semantic.build_range("1", "3", "1", "6")
    enriched = next(unit for unit in source_inventory["units"]
                    if unit.get("evidenceIds") and unit.get("accountingRole") == "PRIMARY")
    evidence_id = enriched["evidenceIds"][0]
    with runtime.repository._connect() as conn:
        evidence_payload = json.loads(conn.execute(
            "SELECT payload_json FROM evidence_records WHERE id=?", (evidence_id,),
        ).fetchone()[0])
        evidence_payload["validationStatus"] = "CONFLICTING"
        conn.execute(
            "UPDATE evidence_records SET validation_status='CONFLICTING',payload_json=? WHERE id=?",
            (json.dumps(evidence_payload), evidence_id),
        ); conn.commit()
    meaning = MeaningAnalysisEngine(runtime).run_range(
        "1", "3", "1", "6", location_run_id=location["id"],
    )
    source = {unit["id"]: unit for unit in runtime.source_semantic.build_range("1", "3", "1", "6")["units"]}
    completion = [
        component for item in meaning["assessments"] for component in item["componentAssessments"]
        if any(source[unit_id].get("semanticFeatures", {}).get("lemma") == "ἐπιτελέω"
               for unit_id in component["sourceSemanticUnitIds"])
    ]
    assert completion
    assert any(component["evidence"]["kind"] == "COMPLETION" for component in completion)
    resource_ids = [
        evidence_id for item in meaning["assessments"] for component in item["componentAssessments"]
        for evidence_id in component["evidence"]["resourceEvidenceIds"]
    ]
    assert resource_ids
    assert any(runtime.repository.evidence_record(item)["kind"] in {
        "TRANSLATION_NOTE", "TRANSLATION_WORD", "TRANSLATION_WORD_LIST"
    } for item in resource_ids)
    assert meaning["diagnostics"]["resourceConflict"] > 0
    assert json.dumps(runtime.semantic_location.get_range(location["id"])["relationships"], sort_keys=True) == location_snapshot


def test_meaning_cache_stale_propagation_and_human_review_preservation(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path, language="en", chapters={"1": {"3": "some"}})
    location = SemanticLocationEngine(
        runtime, FixtureEmbeddingProvider(paired_vectors([("πᾶς", "some")])),
    ).run_range("1", "3")
    engine = MeaningAnalysisEngine(runtime)
    first = engine.run_range("1", "3", location_run_id=location["id"])
    assert engine.run_range("1", "3", location_run_id=location["id"])["cacheStatus"] == "HIT"
    assessment_id = first["assessments"][0]["id"]
    with runtime.repository._connect() as conn:
        payload = json.loads(conn.execute(
            "SELECT payload_json FROM meaning_assessments WHERE id=?", (assessment_id,),
        ).fetchone()[0])
        payload["reviewStatus"] = "HUMAN_APPROVED"
        conn.execute(
            "UPDATE meaning_assessments SET review_status='HUMAN_APPROVED',payload_json=? WHERE id=?",
            (json.dumps(payload), assessment_id),
        ); conn.commit()
    lock = runtime.repository.source_lock(runtime.project_id, "PHP")
    runtime.repository.synchronize_source_lock(
        project_id=runtime.project_id, book="PHP", resource_id=lock["resource_id"],
        resource_version="changed", resource_hash="e" * 64,
    )
    with pytest.raises(Exception, match="stale|inactive"):
        runtime.repository.meaning_analysis_run(first["id"])
    with runtime.repository._connect() as conn:
        row = conn.execute(
            "SELECT review_status,lifecycle_status,payload_json FROM meaning_assessments WHERE id=?",
            (assessment_id,),
        ).fetchone()
    assert row["review_status"] == "HUMAN_APPROVED"
    assert row["lifecycle_status"] == "STALE"
    assert json.loads(row["payload_json"])["reviewStatus"] == "HUMAN_APPROVED"

    target_runtime = _runtime(tmp_path / "target", language="en", chapters={"1": {"3": "some"}})
    target_location = SemanticLocationEngine(
        target_runtime, FixtureEmbeddingProvider(paired_vectors([("πᾶς", "some")])),
    ).run_range("1", "3")
    target_meaning = MeaningAnalysisEngine(target_runtime).run_range(
        "1", "3", location_run_id=target_location["id"],
    )
    chapter_path = target_runtime.project.book_dir / "1.json"
    chapter = json.loads(chapter_path.read_text(encoding="utf-8")); chapter["3"] = "all"
    chapter_path.write_text(json.dumps(chapter), encoding="utf-8")
    SemanticLocationEngine(target_runtime).run_range("1", "3")
    with pytest.raises(Exception, match="stale|inactive"):
        target_runtime.repository.meaning_analysis_run(target_meaning["id"])

    policy_runtime = _runtime(tmp_path / "policy", language="en", chapters={"1": {"3": "some"}})
    policy_location = SemanticLocationEngine(
        policy_runtime, FixtureEmbeddingProvider(paired_vectors([("πᾶς", "some")])),
    ).run_range("1", "3")
    base = MeaningAnalysisEngine(policy_runtime).run_range(
        "1", "3", location_run_id=policy_location["id"],
    )
    class PolicyV2(MeaningPolicy):
        version = "meaning-policy-test-v2"
    policy_changed = MeaningAnalysisEngine(policy_runtime, PolicyV2()).run_range(
        "1", "3", location_run_id=policy_location["id"],
    )
    model_changed = MeaningAnalysisEngine(
        policy_runtime, PolicyV2(), model_version="meaning-model-test-v2",
    ).run_range("1", "3", location_run_id=policy_location["id"])
    assert len({base["id"], policy_changed["id"], model_changed["id"]}) == 3


def test_meaning_protocol_apis_and_no_qa_side_effects(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path, language="en", chapters={"1": {"3": "unrelated"}})
    location = SemanticLocationEngine(runtime).run_range("1", "3")
    bridge = BridgeEngine(); bridge.project = runtime.project; bridge.passage_semantic_runtime = runtime
    response = bridge.handle_request(EngineRequest(
        id="run", method="meaningAnalysis.runRange",
        params={"chapter": "1", "verse": "3", "locationRunId": location["id"]},
    )).to_dict()
    assert response["success"] is True, response
    run = response["result"]; assessment_id = run["assessments"][0]["id"]
    calls = [
        ("meaningAnalysis.status", {"runId": run["id"]}),
        ("meaningAnalysis.getRange", {"runId": run["id"]}),
        ("meaningAnalysis.getAssessment", {"assessmentId": assessment_id}),
        ("meaningAnalysis.getComponents", {"assessmentId": assessment_id}),
        ("meaningAnalysis.getDiagnostics", {"runId": run["id"]}),
    ]
    assert all(bridge.handle_request(EngineRequest(
        id=str(index), method=method, params=params,
    )).to_dict()["success"] for index, (method, params) in enumerate(calls))
    with runtime.repository._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM qa_findings").fetchone()[0] == 0


@pytest.mark.parametrize(("book", "chapter", "verse", "target", "pairs"), [
    ("GEN", "2", "5", "not all", [("לֹא", "not"), ("כֹּל", "all")]),
    ("DAN", "2", "4", "king", [("מֶלֶךְ", "king")]),
])
def test_hebrew_and_aramaic_meaning_runs_preserve_source_identity(
    tmp_path: Path, book: str, chapter: str, verse: str, target: str,
    pairs: list[tuple[str, str]],
) -> None:
    runtime = _runtime(tmp_path, book=book, language="en", chapters={chapter: {verse: target}})
    location = SemanticLocationEngine(
        runtime, FixtureEmbeddingProvider(paired_vectors(pairs)),
    ).run_range(chapter, verse)
    meaning = MeaningAnalysisEngine(runtime).run_range(
        chapter, verse, location_run_id=location["id"],
    )
    assert meaning["book"] == book
    assert meaning["locationRunId"] == location["id"]
    assert meaning["assessments"]


def test_hebrew_points_do_not_hide_polarity_or_quantity_contradictions() -> None:
    quantity, quantity_confidence, _kind, _explanation = DeterministicMeaningComparator.compare(
        "כֹּל", "some", "QUANTITY",
    )
    polarity, polarity_confidence, _kind, _explanation = DeterministicMeaningComparator.compare(
        "לֹא", "yes", "POLARITY",
    )
    assert quantity.value == "CONTRADICTED"
    assert polarity.value == "CONTRADICTED"
    assert quantity_confidence >= 0.95
    assert polarity_confidence >= 0.95


def test_no_space_target_and_analyzer_unavailable_are_conservative(tmp_path: Path) -> None:
    runtime = _runtime(
        tmp_path, language="ja", chapters={"1": {"3": "初めに神が天と地を造った。"}},
    )
    location = SemanticLocationEngine(
        runtime, FixtureEmbeddingProvider(paired_vectors([("θεός", "初めに神が天と地を造った")])),
    ).run_range("1", "3")
    meaning = MeaningAnalysisEngine(runtime).run_range(
        "1", "3", location_run_id=location["id"],
    )
    assert meaning["assessments"]
    assert not any(item["meaningStatus"] == "PRESERVED"
                   and not item["componentAssessments"] for item in meaning["assessments"])
    status, _confidence, _kind, explanation = DeterministicMeaningComparator.compare(
        "plural", "they", "QUANTITY", realization="GRAMMATICALLY_REALIZED",
        target_capabilities={"morphology": "UNAVAILABLE"},
    )
    assert status.value == "NOT_DETERMINABLE"
    assert "unavailable" in explanation
