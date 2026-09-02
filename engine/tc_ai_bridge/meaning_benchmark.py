"""Machine-proposed Stage 7 benchmark validation and deterministic baseline."""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
from typing import Any

from .meaning_analysis import DeterministicMeaningComparator, MeaningPolicy


BENCHMARK_PATH = Path(__file__).resolve().parents[1] / "resources" / "meaning_analysis" / "benchmark-v1.json"


def load_meaning_benchmark(path: Path = BENCHMARK_PATH) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != "bridge.meaning-benchmark/v1":
        raise ValueError("Unsupported meaning benchmark schema")
    if payload.get("reviewStatus") != "MACHINE_PROPOSED":
        raise ValueError("Stage 7 benchmark provenance must not imply human review")
    ids = [item["id"] for item in payload.get("cases", [])]
    if len(ids) != len(set(ids)) or len(ids) < 18:
        raise ValueError("Meaning benchmark needs at least 18 unique cases")
    return payload


def deterministic_baseline(payload: dict[str, Any], split: str = "TEST") -> dict[str, Any]:
    cases = [item for item in payload["cases"] if item["split"] == split]
    confusion: Counter[tuple[str, str]] = Counter()
    for case in cases:
        component, _confidence, _evidence, _explanation = DeterministicMeaningComparator.compare(
            case["source"], case["target"], case["dimension"],
            realization=case.get("realization", "LEXICALLY_REALIZED"),
        )
        predicted = MeaningPolicy.aggregate(
            [component.value], bool(case.get("properties"))
            or case.get("realization", "LEXICALLY_REALIZED") != "LEXICALLY_REALIZED",
        ).value
        confusion[(case["expected"], predicted)] += 1
    correct = sum(value for (expected, predicted), value in confusion.items() if expected == predicted)
    return {
        "benchmarkVersion": payload["benchmarkVersion"], "split": split,
        "cases": len(cases), "accuracy": correct / len(cases) if cases else 0.0,
        "confusion": {f"{expected}->{predicted}": value
                      for (expected, predicted), value in sorted(confusion.items())},
    }
