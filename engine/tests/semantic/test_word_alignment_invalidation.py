"""V11-000a: completing/invalidating a tC Word Alignment stales the Stage 6B
runs that depend on it -- in the same session, not only after a restart.
See docs/V11-000_STAGE6B_ALIGNMENT_SPIKE.md, work item 5.
"""
from __future__ import annotations

import json
from pathlib import Path

from tc_ai_bridge.passage_semantic_runtime import PassageSemanticRuntime
from tc_ai_bridge.semantic_location import SemanticLocationEngine
from tc_ai_bridge.tc_project import TranslationCoreProject


def _runtime(tmp_path: Path) -> PassageSemanticRuntime:
    root = tmp_path / "php-en"
    (root / "php").mkdir(parents=True)
    (root / ".apps" / "translationCore" / "alignmentData" / "php").mkdir(parents=True)
    (root / "manifest.json").write_text(json.dumps({
        "project": {"id": "php", "name": "Philippians"},
        "target_language": {"id": "en"}, "resource": {"id": "test"}, "tc_version": "8",
    }), encoding="utf-8")
    (root / "php" / "1.json").write_text(
        json.dumps({"3": "I thank my God"}, ensure_ascii=False), encoding="utf-8",
    )
    (root / ".apps" / "translationCore" / "alignmentData" / "php" / "1.json").write_text(
        json.dumps({"3": {"alignments": [], "wordBank": []}}), encoding="utf-8",
    )
    (root / "php.usfm").write_text("\\id PHP\n\\c 1\n\\p\n\\v 3 OLD IMPORTED\n", encoding="utf-8")
    return PassageSemanticRuntime(TranslationCoreProject(root), f"alignment-invalidation-{tmp_path.name}")


def _write_alignment(runtime: PassageSemanticRuntime, bottom_word: str) -> None:
    chapter_path = runtime.project.alignment_dir / "1.json"
    payload = {
        "3": {
            "alignments": [{
                "topWords": [{
                    "word": "Θεῷ", "occurrence": 1, "occurrences": 1,
                    "strong": "G2316", "lemma": "θεός", "morph": "Gr,N,,,,,DMS,",
                }],
                "bottomWords": [{"word": bottom_word, "occurrence": 1, "occurrences": 1}],
            }],
            "wordBank": [],
        },
    }
    chapter_path.write_text(json.dumps(payload), encoding="utf-8")


def _mark_completed(runtime: PassageSemanticRuntime) -> None:
    completed_dir = runtime.project.tc_dir / "tools" / "wordAlignment" / "completed" / "1"
    completed_dir.mkdir(parents=True, exist_ok=True)
    (completed_dir / "3.json").write_text(
        json.dumps({"username": "tester", "modifiedTimestamp": "2026-01-01T00:00:00.000Z"}),
        encoding="utf-8",
    )


def test_completing_an_alignment_stales_a_cached_location_run_in_the_same_session(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)
    engine = SemanticLocationEngine(runtime)

    first = engine.run_range("1", "3")
    assert first["cacheStatus"] == "MISS"
    assert engine.run_range("1", "3")["cacheStatus"] == "HIT"

    # Complete the alignment -- content changes, and it becomes "completed" --
    # without restarting or reconstructing the runtime.
    _write_alignment(runtime, "God")
    _mark_completed(runtime)
    sync = runtime.synchronize_alignment_state()
    assert sync["staled"] >= 1

    second = engine.run_range("1", "3")
    assert second["cacheStatus"] == "MISS"
    assert second["fingerprint"] != first["fingerprint"]


def test_completion_state_alone_stales_even_with_identical_alignment_content(
    tmp_path: Path,
) -> None:
    """complete_alignment() can flip completed/invalid with no content byte
    changing (bridge_service.py:1753) -- alignment_state_digest, not just
    alignment_directory_digest, must catch that."""
    runtime = _runtime(tmp_path)
    _write_alignment(runtime, "God")  # content already present, not yet completed
    engine = SemanticLocationEngine(runtime)
    first = engine.run_range("1", "3")
    assert not any(
        component["kind"] == "WORD_ALIGNMENT" and component["rawScore"] > 0
        for candidate in first["candidates"] for component in candidate["evidenceComponents"]
    )

    _mark_completed(runtime)  # same alignment content, only the marker changes
    sync = runtime.synchronize_alignment_state()
    assert sync["staled"] >= 1

    second = engine.run_range("1", "3")
    assert second["cacheStatus"] == "MISS"
    assert any(
        component["kind"] == "WORD_ALIGNMENT" and component["rawScore"] > 0
        for candidate in second["candidates"] for component in candidate["evidenceComponents"]
    )


def test_synchronize_alignment_state_is_a_crash_safe_no_op_when_nothing_changed(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)
    SemanticLocationEngine(runtime).run_range("1", "3")  # something to stale

    _write_alignment(runtime, "God")
    _mark_completed(runtime)
    first = runtime.synchronize_alignment_state()
    assert first["staled"] >= 1
    # Simulates the "called at both project open and after a mutation"
    # double-call this function is designed for, and a crash-recovery replay
    # landing on an already-processed digest -- neither should re-stale.
    second = runtime.synchronize_alignment_state()
    assert second == {"changed": False, "staled": 0}


def test_a_location_run_depends_on_the_book_alignment_anchor_even_with_no_evidence_yet(
    tmp_path: Path,
) -> None:
    """A verse with no alignment evidence today must still be invalidated
    once one is completed later -- the dependency edge is unconditional."""
    runtime = _runtime(tmp_path)
    engine = SemanticLocationEngine(runtime)
    run = engine.run_range("1", "3")
    with runtime.repository._connect() as conn:
        edges = conn.execute(
            "SELECT depends_on_type, depends_on_id FROM record_dependencies "
            "WHERE record_type='LOCATION_RUN' AND record_id=?", (run["id"],),
        ).fetchall()
    expected_id = runtime.repository.alignment_dependency_id(runtime.project_id, runtime.book)
    assert ("WORD_ALIGNMENT", expected_id) in {(row[0], row[1]) for row in edges}
