"""Machine-proposed Stage 8 omission/addition benchmarks and false-positive metrics.

Cases are synthetic gate inputs (not full pipeline runs) that drive
QaAuditPolicy.source_coverage_for / target_support_for directly, mirroring
how meaning_benchmark.py drives DeterministicMeaningComparator directly.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any
import json

from .qa_audit import QaAuditPolicy


RESOURCES_DIR = Path(__file__).resolve().parents[1] / "resources" / "qa_audit"
OMISSION_BENCHMARK_PATH = RESOURCES_DIR / "omission-benchmark-v1.json"
ADDITION_BENCHMARK_PATH = RESOURCES_DIR / "addition-benchmark-v1.json"


def _load(path: Path, schema: str, minimum_cases: int) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != schema:
        raise ValueError(f"Unsupported QA benchmark schema at {path}")
    if payload.get("reviewStatus") != "MACHINE_PROPOSED":
        raise ValueError("Stage 8 benchmark provenance must not imply human review")
    ids = [item["id"] for item in payload.get("cases", [])]
    if len(ids) != len(set(ids)) or len(ids) < minimum_cases:
        raise ValueError(f"QA benchmark at {path} needs at least {minimum_cases} unique cases")
    return payload


def load_omission_benchmark(path: Path = OMISSION_BENCHMARK_PATH) -> dict[str, Any]:
    return _load(path, "bridge.qa-omission-benchmark/v1", 10)


def load_addition_benchmark(path: Path = ADDITION_BENCHMARK_PATH) -> dict[str, Any]:
    return _load(path, "bridge.qa-addition-benchmark/v1", 10)


def _predict_source_coverage(case: dict[str, Any]) -> str:
    owner_unit = {
        "accountingRole": case.get("ownerRole", "PRIMARY"),
        "auditEligibility": case.get("ownerEligibility", "ELIGIBLE"),
    }
    outcome = case.get("locationOutcome")
    relationships: list[dict[str, Any]] = []
    assessments: dict[str, dict[str, Any]] = {}
    if outcome and outcome != "NONE":
        relationships = [{
            "id": "rel-1", "locationOutcome": outcome,
            "properties": case.get("properties", []),
            "realization": case.get("realization", "LEXICALLY_REALIZED"),
        }]
        if case.get("meaningStatus"):
            assessments["rel-1"] = {"meaningStatus": case["meaningStatus"]}
    status, _reason = QaAuditPolicy.source_coverage_for(
        owner_unit, relationships, assessments, bool(case.get("hasVariantEvidence")),
    )
    return status.value


def _predict_target_support(case: dict[str, Any]) -> str:
    unit = {
        "accountingRole": case.get("ownerRole", "PRIMARY"),
        "auditEligibility": case.get("ownerEligibility", "ELIGIBLE"),
        "normalizedSurface": case.get("targetText", ""),
    }
    if case.get("isFunctionWord"):
        unit["normalizedSurface"] = next(iter(QaAuditPolicy.FUNCTION_WORD_FORMS))
    elif case.get("isExplicitation"):
        unit["normalizedSurface"] = next(iter(QaAuditPolicy.LICENSED_EXPLICITATIONS_TARGETS))
    elif case.get("hasUnsupportedSpecificity"):
        unit["normalizedSurface"] = next(iter(QaAuditPolicy.SPECIFICITY_MARKERS))
    outcome = case.get("locationOutcome")
    relationships: list[dict[str, Any]] = []
    assessments: dict[str, dict[str, Any]] = {}
    if outcome and outcome != "NONE":
        relationships = [{"id": "rel-1", "locationOutcome": outcome}]
        if case.get("meaningStatus"):
            assessments["rel-1"] = {
                "meaningStatus": case["meaningStatus"],
                "componentAssessments": (
                    [{"status": "TARGET_ADDS_SPECIFICITY"}]
                    if case.get("hasUnsupportedSpecificity") else []
                ),
            }
    status, _reason = QaAuditPolicy.target_support_for(unit, relationships, assessments)
    return status.value


def deterministic_baseline(payload: dict[str, Any], audience: str, split: str = "TEST") -> dict[str, Any]:
    predictor = _predict_source_coverage if audience == "SOURCE_COVERAGE" else _predict_target_support
    cases = [item for item in payload["cases"] if item["split"] == split]
    confusion: Counter[tuple[str, str]] = Counter()
    for case in cases:
        predicted = predictor(case)
        confusion[(case["expected"], predicted)] += 1
    correct = sum(value for (expected, predicted), value in confusion.items() if expected == predicted)
    return {
        "benchmarkVersion": payload["benchmarkVersion"], "audience": audience, "split": split,
        "cases": len(cases), "accuracy": correct / len(cases) if cases else 0.0,
        "confusion": {f"{expected}->{predicted}": value
                      for (expected, predicted), value in sorted(confusion.items())},
    }


def false_positive_metrics(
    omission_payload: dict[str, Any], addition_payload: dict[str, Any], split: str = "TEST",
) -> dict[str, Any]:
    """Item 32 -- report false-positive/false-negative rates, not one accuracy number."""
    omission_cases = [item for item in omission_payload["cases"] if item["split"] == split]
    addition_cases = [item for item in addition_payload["cases"] if item["split"] == split]

    def rate(cases: list[dict[str, Any]], predictor, positive_value: str) -> dict[str, float]:
        predicted_positive = actual_positive = true_positive = false_positive = 0
        legitimate_restructuring_false_positive = 0
        for case in cases:
            predicted = predictor(case)
            is_predicted_positive = predicted == positive_value
            is_actual_positive = case["expected"] == positive_value
            predicted_positive += is_predicted_positive
            actual_positive += is_actual_positive
            if is_predicted_positive and is_actual_positive:
                true_positive += 1
            if is_predicted_positive and not is_actual_positive:
                false_positive += 1
                if case.get("legitimateRestructuring"):
                    legitimate_restructuring_false_positive += 1
        precision = true_positive / predicted_positive if predicted_positive else 1.0
        recall = true_positive / actual_positive if actual_positive else 1.0
        false_rate = false_positive / len(cases) if cases else 0.0
        return {
            "precision": precision, "recall": recall, "falseRate": false_rate,
            "legitimateRestructuringFalsePositives": legitimate_restructuring_false_positive,
        }

    omission_metrics = rate(omission_cases, _predict_source_coverage, "POSSIBLY_MISSING")
    addition_metrics = rate(addition_cases, _predict_target_support, "POSSIBLY_UNSUPPORTED")
    ambiguity_leakage = sum(
        1 for case in omission_cases
        if case.get("locationOutcome") in {"AMBIGUOUS", "SEARCH_INCOMPLETE"}
        and _predict_source_coverage(case) == "POSSIBLY_MISSING"
    )
    return {
        "split": split,
        "possibleOmissionPrecision": omission_metrics["precision"],
        "possibleOmissionRecall": omission_metrics["recall"],
        "falseOmissionRate": omission_metrics["falseRate"],
        "falseIssueRateOnLegitimateRestructuring": omission_metrics["legitimateRestructuringFalsePositives"],
        "possibleAdditionPrecision": addition_metrics["precision"],
        "possibleAdditionRecall": addition_metrics["recall"],
        "falseAdditionRate": addition_metrics["falseRate"],
        "grammaticalRealizationFalsePositives": addition_metrics["legitimateRestructuringFalsePositives"],
        "ambiguityOrSearchIncompleteToErrorLeakage": ambiguity_leakage,
    }
