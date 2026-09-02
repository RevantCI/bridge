from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import unicodedata

import pytest

from bridge_service import BridgeEngine
from greek_room_engine.protocol import EngineRequest
from tc_ai_bridge.passage_semantic_models import Cardinality, TokenLayer
from tc_ai_bridge.semantic_location import (
    LocationSearchPolicy, SemanticEmbeddingProvider, SemanticLocationEngine,
)
from tc_ai_bridge.passage_semantic_runtime import PassageSemanticRuntime
from tc_ai_bridge.tc_project import TranslationCoreProject


TAMIL = {
    "3": "நற்செய்தி உங்களுக்கு அறிவிக்கப்பட்ட நாள் முதல் இதுவரைக்கும் நீங்கள் எங்களோடு ஊழியத்தில் ஐக்கியப்பட்டிருப்பதால்,",
    "4": "நான் பண்ணுகிற ஒவ்வொரு விண்ணப்பத்திலும் உங்கள் அனைவருக்காகவும் எப்பொழுதும் மகிழ்ச்சியோடு ஜெபம் செய்து,",
    "5": "உங்களில் நல்ல செயலைத் தொடங்கினவர் அதை இயேசு கிறிஸ்துவின் நாள் வரை நடத்தி வருவார் என்று நம்பி,",
    "6": "நான் உங்களை நினைக்கும் போதெல்லாம் என் தேவனை ஸ்தோத்திரிக்கிறேன்.",
}


def _runtime(tmp_path: Path, *, book: str = "PHP", language: str = "ta",
             chapters: dict[str, dict[str, str]] | None = None) -> PassageSemanticRuntime:
    root = tmp_path / f"{book}-{language}"
    lower = book.lower()
    (root / lower).mkdir(parents=True)
    alignment = root / ".apps" / "translationCore" / "alignmentData" / lower
    alignment.mkdir(parents=True)
    chapters = chapters or {"1": TAMIL}
    (root / "manifest.json").write_text(json.dumps({
        "project": {"id": lower, "name": book}, "target_language": {"id": language},
        "resource": {"id": "test"}, "tc_version": "8",
    }), encoding="utf-8")
    for chapter, verses in chapters.items():
        (root / lower / f"{chapter}.json").write_text(
            json.dumps(verses, ensure_ascii=False), encoding="utf-8",
        )
        (alignment / f"{chapter}.json").write_text(json.dumps({
            ref: {"alignments": [], "wordBank": []} for ref in verses
        }), encoding="utf-8")
    lines = [f"\\id {book}"]
    for chapter, verses in chapters.items():
        lines.extend([f"\\c {chapter}", "\\p"])
        lines.extend(f"\\v {verse} OLD IMPORTED" for verse in verses)
    (root / f"{lower}.usfm").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return PassageSemanticRuntime(TranslationCoreProject(root), f"location-{book}-{language}-{tmp_path.name}")


def norm(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value).casefold().split())


class FixtureEmbeddingProvider(SemanticEmbeddingProvider):
    provider_id = "stage6b-fixture-embedding"
    provider_version = "v1"
    model_id = "human-location-fixture-v1"
    normalization = "L2"
    languages = ("el", "hbo", "arc", "ta", "en", "ja")
    offline = True
    available = True

    def __init__(self, vectors: dict[str, list[float]], version: str = "v1"):
        self.vectors = {norm(key): value for key, value in vectors.items()}
        self.dimensions = len(next(iter(vectors.values())))
        self.model_hash = hashlib.sha256(json.dumps(
            {"version": version, "vectors": self.vectors}, sort_keys=True,
            ensure_ascii=False,
        ).encode("utf-8")).hexdigest()

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self.vectors.get(norm(text), [0.0] * self.dimensions) for text in texts]


class FailingEmbeddingProvider(FixtureEmbeddingProvider):
    def embed(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("fixture provider failure")


def paired_vectors(pairs: list[tuple[str, str]]) -> dict[str, list[float]]:
    result: dict[str, list[float]] = {}
    for index, (source, target) in enumerate(pairs):
        vector = [0.0] * len(pairs); vector[index] = 1.0
        result[source] = vector; result[target] = vector
    return result


PHP_PAIRS = [
    ("εὐχαριστέω", "ஸ்தோத்திரிக்கிறேன்"), ("θεός", "தேவனை"),
    ("μνεία", "நினைக்கும்"), ("πάντοτε", "எப்பொழுதும்"),
    ("δέησις", "விண்ணப்பத்திலும்"), ("χαρά", "மகிழ்ச்சியோடு"),
    ("ποιέω", "செய்து"), ("κοινωνία", "ஐக்கியப்பட்டிருப்பதால்"),
    ("εὐαγγέλιον", "நற்செய்தி"), ("πρῶτος", "முதல்"),
    ("ἡμέρα", "நாள்"), ("νῦν", "இதுவரைக்கும்"),
    ("πείθω", "நம்பி"), ("ἐνάρχομαι", "தொடங்கினவர்"),
    ("ἔργον", "செயலைத்"), ("ἀγαθός", "நல்ல"),
    ("ἐπιτελέω", "நடத்தி வருவார்"), ("χριστός", "கிறிஸ்துவின்"),
    ("Ἰησοῦς", "இயேசு"),
]


def test_irvtam_php_passage_reordering_is_discovered_without_engine_book_rules(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    engine = SemanticLocationEngine(runtime, FixtureEmbeddingProvider(paired_vectors(PHP_PAIRS)))
    result = engine.run_range("1", "3", "1", "6")
    candidates = {item["id"]: item for item in result["candidates"]}
    source_units = {item["id"]: item for item in runtime.source_semantic.build_range("1", "3", "1", "6")["units"]}
    votes: dict[str, Counter[str]] = {}
    for relationship in result["relationships"]:
        selected = candidates.get(relationship.get("selectedCandidateId"))
        if not selected:
            continue
        target_ref = selected["targetDisplayedReferences"][0]
        for unit_id in relationship["sourceSemanticUnitIds"]:
            source_ref = source_units[unit_id]["canonicalReferences"][0]
            votes.setdefault(source_ref, Counter())[target_ref] += 1
    golden = json.loads((
        Path(__file__).parent / "fixtures" / "stage6b-location-golden-v1.json"
    ).read_text(encoding="utf-8"))
    expected = {
        item["sourceReference"]: item["targetReference"]
        for item in golden["relationships"]
    }
    assert {reference: counter.most_common(1)[0][0] for reference, counter in votes.items()} == expected
    assert result["diagnostics"]["reordered"] is True
    assert result["diagnostics"]["crossVerse"] > 0
    assert result["diagnostics"]["contextualSupportEdges"] > 0
    assert any(
        component["kind"] == "PASSAGE_COHERENCE"
        for candidate in result["candidates"] for component in candidate["evidenceComponents"]
    )
    assert all("meaningStatus" not in item for item in result["relationships"])
    assert runtime.repository._connect is not None


def test_mistranslation_location_is_kept_separate_from_meaning_and_true_absence(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path, language="en", chapters={"1": {"3": "some"}})
    vectors = paired_vectors([("πᾶς", "some")])
    located = SemanticLocationEngine(runtime, FixtureEmbeddingProvider(vectors)).run_range("1", "3")
    source = {unit["id"]: unit for unit in runtime.source_semantic.build_range("1", "3")["units"]}
    quantifier = next(
        relationship for relationship in located["relationships"]
        if any(source[item]["kind"] == "QUANTIFIER" for item in relationship["sourceSemanticUnitIds"])
    )
    assert quantifier["locationOutcome"] == "LOCATED"
    assert "meaningStatus" not in quantifier

    absent_runtime = _runtime(tmp_path / "absent", language="en", chapters={"1": {"3": "unrelated"}})
    absent = SemanticLocationEngine(absent_runtime).run_range("1", "3")
    absent_source = {unit["id"]: unit for unit in absent_runtime.source_semantic.build_range("1", "3")["units"]}
    missing_location = next(
        relationship for relationship in absent["relationships"]
        if any(absent_source[item]["kind"] == "QUANTIFIER" for item in relationship["sourceSemanticUnitIds"])
    )
    assert missing_location["locationOutcome"] == "NOT_LOCATED"
    assert "SOURCE_TO_NULL" not in json.dumps(absent)


def test_repeated_candidates_are_ambiguous_and_search_exhaustion_is_incomplete(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path, language="en", chapters={"1": {"3": "some some"}})
    provider = FixtureEmbeddingProvider(paired_vectors([("πᾶς", "some")]))
    result = SemanticLocationEngine(runtime, provider).run_range("1", "3")
    source = {unit["id"]: unit for unit in runtime.source_semantic.build_range("1", "3")["units"]}
    quantifier = next(
        relationship for relationship in result["relationships"]
        if any(source[item]["kind"] == "QUANTIFIER" for item in relationship["sourceSemanticUnitIds"])
    )
    assert quantifier["locationOutcome"] == "AMBIGUOUS"
    alternatives = [item for item in result["candidates"] if item["sourceOwnerUnitId"] == quantifier["sourceOwnerUnitId"]]
    assert len({tuple(item["targetTokenInstanceIds"]) for item in alternatives[:2]}) == 2

    exhausted_runtime = _runtime(tmp_path / "budget", language="en", chapters={"1": {"3": "some"}})
    exhausted = SemanticLocationEngine(exhausted_runtime, provider).run_range(
        "1", "3", max_candidate_evaluations=1,
    )
    assert exhausted["diagnostics"]["searchIncomplete"] > 0


def test_split_merged_many_to_many_and_pronominalized_realizations(tmp_path: Path) -> None:
    split_runtime = _runtime(tmp_path / "split", language="en", chapters={"1": {"3": "alpha middle omega"}})
    split_vectors = {
        "θεός": [1.0, 1.0], "alpha": [1.0, 0.0], "omega": [0.0, 1.0],
        "alpha … omega": [1.0, 1.0],
    }
    split = SemanticLocationEngine(split_runtime, FixtureEmbeddingProvider(split_vectors)).run_range("1", "3")
    source = {unit["id"]: unit for unit in split_runtime.source_semantic.build_range("1", "3")["units"]}
    split_relationship = next(
        item for item in split["relationships"]
        if any(source[unit_id].get("semanticFeatures", {}).get("lemma") == "θεός"
               for unit_id in item["sourceSemanticUnitIds"])
    )
    assert split_relationship["locationOutcome"] == "LOCATED"
    assert "SPLIT" in split_relationship["properties"]
    assert len(split_relationship["targetSpanIds"]) == 2

    merge_runtime = _runtime(tmp_path / "merge", language="en", chapters={"1": {"3": "combined"}})
    merge_vectors = {"θεός": [1.0], "μνεία": [1.0], "combined": [1.0]}
    merged = SemanticLocationEngine(merge_runtime, FixtureEmbeddingProvider(merge_vectors)).run_range("1", "3")
    merge_source = {unit["id"]: unit for unit in merge_runtime.source_semantic.build_range("1", "3")["units"]}
    merge_debug = [
        ([merge_source[unit_id].get("semanticFeatures", {}).get("lemma")
          for unit_id in item["sourceSemanticUnitIds"]], item["locationOutcome"],
         item["targetSpanIds"], item["properties"])
        for item in merged["relationships"]
    ]
    merged_relationship = next(
        (item for item in merged["relationships"] if "MERGED" in item["properties"]), None,
    )
    assert any(
        "μνεία" in lemmas and outcome == "LOCATED"
        for lemmas, outcome, _spans, _properties in merge_debug
    ), merge_debug
    assert merged_relationship is not None, merge_debug
    assert len(merged_relationship["sourceSemanticUnitIds"]) >= 2
    assert len(merged_relationship["targetTokenInstanceIds"]) == 1

    pronoun_runtime = _runtime(tmp_path / "pronoun", language="en", chapters={"1": {"3": "he"}})
    pronoun = SemanticLocationEngine(
        pronoun_runtime, FixtureEmbeddingProvider(paired_vectors([("θεός", "he")])),
    ).run_range("1", "3")
    assert any(item["realization"] == "PRONOMINALIZED" for item in pronoun["relationships"])


def test_no_space_and_agglutinative_target_spans_are_locatable(tmp_path: Path) -> None:
    no_space_runtime = _runtime(
        tmp_path / "nospace", language="ja", chapters={"1": {"3": "初めに神が天と地を造った。"}},
    )
    no_space = SemanticLocationEngine(
        no_space_runtime,
        FixtureEmbeddingProvider(paired_vectors([("θεός", "初めに神が天と地を造った")])),
    ).run_range("1", "3")
    assert any(item["locationOutcome"] == "LOCATED" for item in no_space["relationships"])

    agglutinative_runtime = _runtime(
        tmp_path / "agglutinative", language="ta", chapters={"1": {"3": TAMIL["3"]}},
    )
    inventory = agglutinative_runtime.target_semantic.build_range("1", "3")
    subtoken_quotes = [span["quote"] for span in inventory["searchSpans"] if span["kind"] == "SUBTOKEN"]
    assert "தால்" in subtoken_quotes, subtoken_quotes
    agglutinative = SemanticLocationEngine(
        agglutinative_runtime,
        FixtureEmbeddingProvider(paired_vectors([("εὐχαριστέω", "தால்")])),
    ).run_range("1", "3")
    candidates = {item["id"]: item for item in agglutinative["candidates"]}
    selected_quotes = [
        quote["quote"] for item in agglutinative["relationships"] if item.get("selectedCandidateId")
        for quote in candidates[item["selectedCandidateId"]]["quotes"]
    ]
    assert any(
        any(quote["quote"] == "தால்" for quote in candidates[item["selectedCandidateId"]]["quotes"])
        for item in agglutinative["relationships"] if item.get("selectedCandidateId")
    ), selected_quotes


def test_location_cache_model_and_target_revision_invalidation(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path, language="en", chapters={"1": {"3": "some"}})
    vectors = paired_vectors([("πᾶς", "some")])
    first_engine = SemanticLocationEngine(runtime, FixtureEmbeddingProvider(vectors, "v1"))
    first = first_engine.run_range("1", "3")
    assert first_engine.run_range("1", "3")["cacheStatus"] == "HIT"
    second = SemanticLocationEngine(runtime, FixtureEmbeddingProvider(vectors, "v2")).run_range("1", "3")
    assert second["id"] != first["id"]

    chapter_path = runtime.project.book_dir / "1.json"
    chapter = json.loads(chapter_path.read_text(encoding="utf-8")); chapter["3"] = "different"
    chapter_path.write_text(json.dumps(chapter), encoding="utf-8")
    third = first_engine.run_range("1", "3")
    assert third["id"] != first["id"]
    with pytest.raises(Exception, match="stale|inactive"):
        runtime.repository.semantic_location_run(first["id"])


def test_embedding_cache_source_resource_invalidation_and_provider_failure(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path, language="en", chapters={"1": {"3": "some"}})
    vectors = paired_vectors([("πᾶς", "some")])
    provider = FixtureEmbeddingProvider(vectors)
    first = SemanticLocationEngine(runtime, provider).run_range("1", "3")
    cached_vectors = SemanticLocationEngine(
        runtime, provider, LocationSearchPolicy(max_candidate_evaluations=24_999),
    ).run_range("1", "3")
    assert cached_vectors["diagnostics"]["embeddingCacheHits"] > 0

    lock = runtime.repository.source_lock(runtime.project_id, "PHP")
    assert lock is not None
    invalidated = runtime.repository.synchronize_source_lock(
        project_id=runtime.project_id, book="PHP", resource_id=lock["resource_id"],
        resource_version="stage6b-changed", resource_hash="f" * 64,
    )
    assert invalidated["changed"] is True
    with pytest.raises(Exception, match="stale|inactive"):
        runtime.repository.semantic_location_run(first["id"])

    failed_runtime = _runtime(
        tmp_path / "failed", language="en", chapters={"1": {"3": "unrelated"}},
    )
    failed = SemanticLocationEngine(
        failed_runtime, FailingEmbeddingProvider(vectors),
    ).run_range("1", "3")
    assert failed["diagnostics"]["embeddingFailure"]
    assert failed["diagnostics"]["searchIncomplete"] > 0
    assert failed["diagnostics"]["notLocated"] == 0


def test_exact_current_span_validation_and_optional_embedding_fallback(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path, language="el", chapters={"1": {"3": "θεός"}})
    inventory = runtime.target_semantic.build_range("1", "3")
    engine = SemanticLocationEngine(runtime)
    exact = next(span for span in inventory["searchSpans"] if span["quote"] == "θεός")
    engine._validate_span(exact, inventory)
    damaged = {**exact, "quote": "other"}
    with pytest.raises(Exception, match="quote hash"):
        engine._validate_span(damaged, inventory)
    result = engine.run_range("1", "3")
    assert result["embeddingProvider"]["available"] is False
    assert any(item["locationOutcome"] == "LOCATED" for item in result["relationships"])


def test_pronoun_competition_is_ambiguous_and_implicit_is_not_invented(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path, language="en", chapters={"1": {"3": "he he"}})
    result = SemanticLocationEngine(
        runtime, FixtureEmbeddingProvider(paired_vectors([("θεός", "he")])),
    ).run_range("1", "3")
    source = {unit["id"]: unit for unit in runtime.source_semantic.build_range("1", "3")["units"]}
    relationship = next(
        item for item in result["relationships"]
        if any(source[unit_id].get("semanticFeatures", {}).get("lemma") == "θεός"
               for unit_id in item["sourceSemanticUnitIds"])
    )
    assert relationship["locationOutcome"] == "AMBIGUOUS"
    candidates = [
        item for item in result["candidates"]
        if item["sourceOwnerUnitId"] == relationship["sourceOwnerUnitId"]
    ]
    assert len({tuple(item["targetTokenInstanceIds"]) for item in candidates[:2]}) == 2
    assert all(item["realization"] == "PRONOMINALIZED" for item in candidates[:2])
    assert not any(item["realization"] == "IMPLICIT" for item in result["relationships"])


def test_human_approved_precedent_uses_revision_bound_token_identity(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path, language="en", chapters={"1": {"3": "anchor"}})
    source = runtime.source_semantic.build_range("1", "3")
    target = runtime.target_semantic.build_range("1", "3")
    source_unit = next(unit for unit in source["units"] if unit.get("semanticFeatures", {}).get("lemma") == "θεός")
    target_token = next(token for token in target["tokens"] if token["rawForm"] == "anchor")
    runtime.repository.create_lexical_solution(
        solution_id="human-precedent-solution", project_id=runtime.project_id,
        scope_key="PHP 1:3", profile_id="human-local-v1",
        source_layer=TokenLayer.ORTHOGRAPHIC, target_layer=TokenLayer.ORTHOGRAPHIC,
        authoritative=False,
    )
    runtime.repository.add_lexical_group(
        group_id="human-precedent-group", solution_id="human-precedent-solution",
        cardinality=Cardinality.ONE_TO_ONE,
        source_layer=TokenLayer.ORTHOGRAPHIC, target_layer=TokenLayer.ORTHOGRAPHIC,
        source_token_ids=tuple(source_unit["tokenInstanceIds"]),
        target_token_ids=(target_token["id"],), alignment_family_id="human-family",
    )
    runtime.repository.activate_lexical_solution(
        "human-precedent-solution", expected_revision=1, authoritative=True,
    )
    with runtime.repository._connect() as conn:
        payload = json.loads(conn.execute(
            "SELECT payload_json FROM lexical_groups WHERE id='human-precedent-group'"
        ).fetchone()[0])
        payload["reviewStatus"] = "HUMAN_APPROVED"
        conn.execute(
            "UPDATE lexical_groups SET review_status='HUMAN_APPROVED',payload_json=? "
            "WHERE id='human-precedent-group'", (json.dumps(payload),),
        )
        conn.commit()
    result = SemanticLocationEngine(runtime).run_range("1", "3")
    relationship = next(
        item for item in result["relationships"]
        if source_unit["id"] in item["sourceSemanticUnitIds"]
    )
    assert relationship["locationOutcome"] == "LOCATED"
    candidate = next(item for item in result["candidates"] if item["id"] == relationship["selectedCandidateId"])
    assert any(component["kind"] == "HUMAN_PRECEDENT" for component in candidate["evidenceComponents"])


def test_unsupported_analysis_and_no_qa_or_native_alignment_writes(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path, language="ja", chapters={"1": {"3": "対象"}})
    engine = SemanticLocationEngine(runtime)
    assert engine._unsupported({"kind": "MORPHOLOGICAL"}, {"morphology": "UNAVAILABLE"})
    result = engine.run_range("1", "3")
    encoded = json.dumps(result)
    assert all(term not in encoded for term in (
        "MISSING", "UNSUPPORTED\"", "CORRECTION", "NULL_TO_TARGET", "SOURCE_TO_NULL",
    ))
    with runtime.repository._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM qa_findings").fetchone()[0] == 0


def test_semantic_location_protocol_inspection_apis(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path, language="en", chapters={"1": {"3": "unrelated"}})
    bridge = BridgeEngine(); bridge.project = runtime.project
    bridge.passage_semantic_runtime = runtime
    response = bridge.handle_request(EngineRequest(
        id="run", method="semanticLocation.runRange",
        params={"chapter": "1", "verse": "3"},
    )).to_dict()
    assert response["success"] is True, response
    run = response["result"]
    relationship_id = run["relationships"][0]["id"]
    calls = [
        ("semanticLocation.status", {"runId": run["id"]}),
        ("semanticLocation.getRange", {"runId": run["id"]}),
        ("semanticLocation.getRelationship", {"relationshipId": relationship_id}),
        ("semanticLocation.getCandidates", {"runId": run["id"]}),
        ("semanticLocation.getDiagnostics", {"runId": run["id"]}),
    ]
    assert all(
        bridge.handle_request(EngineRequest(id=str(index), method=method, params=params)).to_dict()["success"]
        for index, (method, params) in enumerate(calls)
    )


@pytest.mark.parametrize(("book", "chapter", "verse", "target", "pairs", "expected_kind"), [
    ("GEN", "2", "5", "not all", [("לֹא", "not"), ("כֹּל", "all")], "NEGATION"),
    ("DAN", "2", "4", "king live forever", [("מֶלֶךְ", "king"), ("חֲיָא", "live")], "LEXICAL"),
])
def test_hebrew_and_aramaic_source_location_fixtures(
    tmp_path: Path, book: str, chapter: str, verse: str, target: str,
    pairs: list[tuple[str, str]], expected_kind: str,
) -> None:
    runtime = _runtime(
        tmp_path, book=book, language="en", chapters={chapter: {verse: target}},
    )
    result = SemanticLocationEngine(
        runtime, FixtureEmbeddingProvider(paired_vectors(pairs)),
    ).run_range(chapter, verse)
    source = {
        unit["id"]: unit
        for unit in runtime.source_semantic.build_range(chapter, verse)["units"]
    }
    assert any(
        relationship["locationOutcome"] == "LOCATED"
        and any(source[unit_id]["kind"] == expected_kind
                for unit_id in relationship["sourceSemanticUnitIds"])
        for relationship in result["relationships"]
    )
