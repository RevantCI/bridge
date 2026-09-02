from tc_ai_bridge.meaning_benchmark import deterministic_baseline, load_meaning_benchmark


def test_machine_proposed_meaning_benchmark_composition_and_baseline() -> None:
    benchmark = load_meaning_benchmark()
    assert len(benchmark["cases"]) == 20
    assert {item["split"] for item in benchmark["cases"]} == {"TRAIN", "CALIBRATION", "TEST"}
    assert {item["id"] for item in benchmark["cases"]} >= {
        "all-some", "positive-negative", "before-after", "completion-continuation",
        "giver-receiver", "participant-swap", "idiom", "split", "merged", "cross-reordered",
    }
    result = deterministic_baseline(benchmark)
    assert result["cases"] > 0
    assert 0.0 <= result["accuracy"] <= 1.0
    assert "CONTRADICTED->CONTRADICTED" in result["confusion"]
