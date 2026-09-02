"""Independent Stage 6B location benchmark loading and quality metrics.

The benchmark is location-only.  In particular, records marked ``meaningTrap``
are deliberately incorrect translations whose corresponding target expression
must still be located.
"""
from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path
from typing import Any, Iterable


BENCHMARK_PATH = (
    Path(__file__).resolve().parents[1]
    / "resources"
    / "semantic_location"
    / "benchmark-v1.json"
)


def load_location_benchmark(path: Path = BENCHMARK_PATH) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    validate_location_benchmark(payload)
    return payload


def validate_location_benchmark(payload: dict[str, Any]) -> None:
    if payload.get("schema") != "bridge.semantic-location-benchmark/v1":
        raise ValueError("Unsupported semantic-location benchmark schema")
    seen: set[str] = set()
    allowed_splits = {"TRAIN", "CALIBRATION", "TEST"}
    allowed_outcomes = {
        "LOCATED", "AMBIGUOUS", "NOT_LOCATED", "SEARCH_INCOMPLETE",
        "UNSUPPORTED_ANALYSIS",
    }
    for case in payload.get("cases", []):
        case_id = str(case.get("id", ""))
        if not case_id or case_id in seen:
            raise ValueError(f"Missing or duplicate benchmark case id: {case_id!r}")
        seen.add(case_id)
        if case.get("split") not in allowed_splits:
            raise ValueError(f"Invalid benchmark split for {case_id}")
        if case.get("outcome") not in allowed_outcomes:
            raise ValueError(f"Invalid location outcome for {case_id}")
        target_text = case.get("targetTextByReference") or {}
        for span in case.get("targetSpans", []):
            text = target_text.get(span.get("reference"))
            if text is None:
                raise ValueError(f"Missing target reference text for {case_id}")
            start, end = int(span["startCodePoint"]), int(span["endCodePoint"])
            if start < 0 or end <= start or text[start:end] != span.get("quote"):
                raise ValueError(f"Invalid exact code-point span for {case_id}")


def _span_key(span: dict[str, Any]) -> tuple[str, int, int]:
    return (
        str(span.get("reference", "")),
        int(span.get("startCodePoint", -1)),
        int(span.get("endCodePoint", -1)),
    )


def _candidate_spans(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    return list(candidate.get("targetSpans") or candidate.get("spans") or [])


def _exact(candidate: dict[str, Any], gold: list[dict[str, Any]]) -> bool:
    return {_span_key(item) for item in _candidate_spans(candidate)} == {
        _span_key(item) for item in gold
    }


def _overlap(candidate: dict[str, Any], gold: list[dict[str, Any]]) -> float:
    predicted = _candidate_spans(candidate)
    if not predicted and not gold:
        return 1.0
    intersection = 0
    predicted_size = 0
    for item in predicted:
        reference, start, end = _span_key(item)
        predicted_size += max(0, end - start)
        for expected in gold:
            expected_ref, expected_start, expected_end = _span_key(expected)
            if reference == expected_ref:
                intersection += max(0, min(end, expected_end) - max(start, expected_start))
    return intersection / predicted_size if predicted_size else 0.0


def _mean(values: Iterable[float]) -> float:
    values = list(values)
    return sum(values) / len(values) if values else 0.0


def evaluate_location_predictions(
    benchmark: dict[str, Any], predictions: dict[str, dict[str, Any]],
    *, evaluation_split: str = "TEST", recall_k: int = 5,
) -> dict[str, Any]:
    """Evaluate ranking separately from held-out confidence calibration.

    Prediction records contain ``outcome``, ranked ``candidates`` and optional
    ``confidence``.  Candidate spans use benchmark code-point coordinates.
    Accuracy is reported only on ``evaluation_split``. Calibration statistics
    are computed only from the disjoint ``CALIBRATION`` partition.
    """
    validate_location_benchmark(benchmark)
    evaluation = [case for case in benchmark["cases"] if case["split"] == evaluation_split]
    located = [case for case in evaluation if case["outcome"] == "LOCATED"]

    def prediction(case: dict[str, Any]) -> dict[str, Any]:
        return predictions.get(case["id"], {"outcome": "SEARCH_INCOMPLETE", "candidates": []})

    recall_one = []
    recall_k_values = []
    top1_precision = []
    overlap_precision = []
    for case in located:
        candidates = list(prediction(case).get("candidates") or [])
        recall_one.append(float(bool(candidates) and _exact(candidates[0], case["targetSpans"])))
        recall_k_values.append(float(any(
            _exact(item, case["targetSpans"]) for item in candidates[:recall_k]
        )))
        if candidates:
            top1_precision.append(float(_exact(candidates[0], case["targetSpans"])))
            overlap_precision.append(_overlap(candidates[0], case["targetSpans"]))

    def property_accuracy(property_name: str) -> float:
        cases = [case for case in evaluation if property_name in case.get("properties", [])]
        return _mean(
            float(
                prediction(case).get("outcome") == case["outcome"]
                and property_name in prediction(case).get("properties", [])
            )
            for case in cases
        )

    ambiguity_cases = [case for case in evaluation if case["outcome"] == "AMBIGUOUS"]
    not_located = [case for case in evaluation if case["outcome"] == "NOT_LOCATED"]
    meaning_traps = [case for case in evaluation if case.get("meaningTrap")]
    abstentions = {"AMBIGUOUS", "NOT_LOCATED", "SEARCH_INCOMPLETE", "UNSUPPORTED_ANALYSIS"}

    calibration_cases = [case for case in benchmark["cases"] if case["split"] == "CALIBRATION"]
    calibration_pairs: list[tuple[float, float]] = []
    for case in calibration_cases:
        predicted = prediction(case)
        if "confidence" not in predicted:
            continue
        candidates = list(predicted.get("candidates") or [])
        correct = float(
            predicted.get("outcome") == case["outcome"]
            and (
                case["outcome"] != "LOCATED"
                or (bool(candidates) and _exact(candidates[0], case["targetSpans"]))
            )
        )
        calibration_pairs.append((float(predicted["confidence"]), correct))
    brier = _mean((confidence - correct) ** 2 for confidence, correct in calibration_pairs)
    bins: dict[int, list[tuple[float, float]]] = defaultdict(list)
    for pair in calibration_pairs:
        bins[min(9, int(pair[0] * 10))].append(pair)
    ece = sum(
        len(items) / len(calibration_pairs)
        * abs(_mean(item[0] for item in items) - _mean(item[1] for item in items))
        for items in bins.values()
    ) if calibration_pairs else 0.0

    return {
        "benchmarkVersion": benchmark["benchmarkVersion"],
        "evaluationSplit": evaluation_split,
        "evaluationCases": len(evaluation),
        "candidateRecallAt1": _mean(recall_one),
        "candidateRecallAtK": _mean(recall_k_values),
        "recallK": recall_k,
        "exactSpanTop1Precision": _mean(top1_precision),
        "overlapSpanPrecision": _mean(overlap_precision),
        "crossVerseAccuracy": property_accuracy("CROSS_VERSE"),
        "splitAccuracy": property_accuracy("SPLIT"),
        "mergedAccuracy": property_accuracy("MERGED"),
        "ambiguityAccuracy": _mean(
            float(prediction(case).get("outcome") == "AMBIGUOUS")
            for case in ambiguity_cases
        ),
        "abstentionRate": _mean(
            float(prediction(case).get("outcome") in abstentions) for case in evaluation
        ),
        "falseForcedLocationRate": _mean(
            float(prediction(case).get("outcome") == "LOCATED") for case in not_located
        ),
        "genuineNotLocatedAccuracy": _mean(
            float(prediction(case).get("outcome") == "NOT_LOCATED") for case in not_located
        ),
        "mistranslationLocationAccuracy": _mean(
            float(
                prediction(case).get("outcome") == "LOCATED"
                and bool(prediction(case).get("candidates"))
                and _exact(prediction(case)["candidates"][0], case["targetSpans"])
            )
            for case in meaning_traps
        ),
        "calibrationSplit": "CALIBRATION",
        "calibrationCasesScored": len(calibration_pairs),
        "calibrationBrierScore": brier,
        "calibrationExpectedError": ece,
    }
