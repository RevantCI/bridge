from __future__ import annotations

from copy import deepcopy

import pytest

from tc_ai_bridge.semantic_location_benchmark import (
    evaluate_location_predictions,
    load_location_benchmark,
    validate_location_benchmark,
)


def _gold_prediction(case: dict) -> dict:
    candidates = []
    if case["targetSpans"]:
        candidates.append({"targetSpans": deepcopy(case["targetSpans"])})
    return {
        "outcome": case["outcome"],
        "properties": list(case.get("properties", [])),
        "candidates": candidates,
        "confidence": 0.9,
    }


def test_proposed_location_benchmark_has_required_composition_and_exact_spans() -> None:
    benchmark = load_location_benchmark()
    assert benchmark["reviewStatus"] == "MACHINE_PROPOSED"
    cases = benchmark["cases"]
    assert len(cases) >= 20
    assert {case["sourceLanguage"] for case in cases} >= {"el", "hbo", "arc"}
    assert {case["targetLanguage"] for case in cases} >= {"en", "ta", "ja"}
    properties = {value for case in cases for value in case.get("properties", [])}
    assert properties >= {"CROSS_VERSE", "REORDERED", "SPLIT", "MERGED"}
    assert any(case.get("meaningTrap") for case in cases)
    assert any(case["outcome"] == "NOT_LOCATED" for case in cases)
    assert any(case["outcome"] == "AMBIGUOUS" for case in cases)
    assert {case["split"] for case in cases} == {"TRAIN", "CALIBRATION", "TEST"}


def test_benchmark_rejects_non_exact_unicode_span() -> None:
    benchmark = load_location_benchmark()
    benchmark["cases"][1]["targetSpans"][0]["endCodePoint"] -= 1
    with pytest.raises(ValueError, match="exact code-point span"):
        validate_location_benchmark(benchmark)


def test_metrics_separate_test_ranking_from_calibration_partition() -> None:
    benchmark = load_location_benchmark()
    predictions = {case["id"]: _gold_prediction(case) for case in benchmark["cases"]}
    metrics = evaluate_location_predictions(benchmark, predictions, evaluation_split="TEST")
    assert metrics["candidateRecallAt1"] == 1.0
    assert metrics["candidateRecallAtK"] == 1.0
    assert metrics["exactSpanTop1Precision"] == 1.0
    assert metrics["overlapSpanPrecision"] == 1.0
    assert metrics["crossVerseAccuracy"] == 1.0
    assert metrics["splitAccuracy"] == 1.0
    assert metrics["ambiguityAccuracy"] == 1.0
    assert metrics["falseForcedLocationRate"] == 0.0
    assert metrics["genuineNotLocatedAccuracy"] == 1.0
    assert metrics["mistranslationLocationAccuracy"] == 1.0
    assert metrics["evaluationCases"] == 12
    assert metrics["calibrationCasesScored"] == 6


def test_metrics_expose_forced_match_and_retrieval_failure() -> None:
    benchmark = load_location_benchmark()
    predictions = {case["id"]: _gold_prediction(case) for case in benchmark["cases"]}
    absent = next(case for case in benchmark["cases"] if case["id"] == "genuine-no-location")
    predictions[absent["id"]] = {
        "outcome": "LOCATED",
        "properties": [],
        "candidates": [{"targetSpans": [{
            "reference": "TST 1:9", "quote": "unrelated",
            "startCodePoint": 0, "endCodePoint": 9,
        }]}],
        "confidence": 0.8,
    }
    missing = next(case for case in benchmark["cases"] if case["id"] == "wrong-before-after")
    predictions[missing["id"]]["candidates"] = []
    predictions[missing["id"]]["outcome"] = "SEARCH_INCOMPLETE"
    metrics = evaluate_location_predictions(benchmark, predictions)
    assert metrics["falseForcedLocationRate"] == 1.0
    assert metrics["candidateRecallAt1"] < 1.0
    assert metrics["mistranslationLocationAccuracy"] < 1.0
