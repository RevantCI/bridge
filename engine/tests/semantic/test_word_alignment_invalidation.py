"""V11-000a: completing/invalidating a tC Word Alignment stales the Stage 6B
runs that depend on it -- in the same session, not only after a restart.
See docs/V11-000_STAGE6B_ALIGNMENT_SPIKE.md, work item 5.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from bridge_service import BridgeEngine
from tc_ai_bridge.passage_semantic_runtime import PassageSemanticRuntime
from tc_ai_bridge.semantic_location import SemanticLocationEngine
from tc_ai_bridge.tc_project import TranslationCoreProject


def _run_status(repository, run_id: str) -> str | None:
    with repository._connect() as conn:
        row = conn.execute(
            "SELECT lifecycle_status FROM semantic_location_runs WHERE id=?", (run_id,),
        ).fetchone()
    return row[0] if row else None


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


class _FailingExecuteManyConnection:
    """Delegates everything to a real sqlite3.Connection except `executemany`,
    which raises for one chosen SQL statement -- `sqlite3.Connection` is a C
    type and does not allow patching a method on the class or an instance
    directly, so this wraps it instead."""

    def __init__(self, real: sqlite3.Connection, fail_when_sql_contains: str):
        object.__setattr__(self, "_real", real)
        object.__setattr__(self, "_fail_when_sql_contains", fail_when_sql_contains)

    def executemany(self, sql: str, params):
        if self._fail_when_sql_contains in sql:
            raise sqlite3.OperationalError(f"simulated failure: {self._fail_when_sql_contains}")
        return self._real.executemany(sql, params)

    def __getattr__(self, name):
        return getattr(self._real, name)

    def __setattr__(self, name, value):
        setattr(self._real, name, value)


def test_save_semantic_location_run_is_atomic_if_the_alignment_edge_write_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """V11-000a review fix F2: the WORD_ALIGNMENT edge is written in the same
    transaction as the run row, not via a separate post-commit call -- a run
    row without its edge must be impossible, not just unlikely."""
    runtime = _runtime(tmp_path)
    repository = runtime.repository
    real_run = SemanticLocationEngine(runtime).run_range("1", "3")  # real, ACTIVE inventories to reuse

    real_connect = sqlite3.connect

    def patched_connect(*args, **kwargs):
        return _FailingExecuteManyConnection(real_connect(*args, **kwargs), "record_dependencies")

    monkeypatch.setattr(sqlite3, "connect", patched_connect)

    doomed_run_id = "location-run-atomicity-probe"
    with pytest.raises(sqlite3.OperationalError, match="record_dependencies"):
        repository.save_semantic_location_run(
            run_id=doomed_run_id, project_id=runtime.project_id, book=runtime.book,
            range_key="PHP 1:3..PHP 1:3", fingerprint="atomicity-probe-fingerprint",
            source_inventory_id=real_run["sourceInventoryId"],
            target_inventory_id=real_run["targetInventoryId"],
            run_status="COMPLETE", payload={"id": doomed_run_id}, candidates=[], relationships=[],
            alignment_dependency_id=repository.alignment_dependency_id(runtime.project_id, runtime.book),
        )

    monkeypatch.undo()  # restore the real sqlite3.connect before touching the DB again
    with repository._connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM semantic_location_runs WHERE id=?", (doomed_run_id,),
        ).fetchone()
    assert row is None


def test_editing_a_verse_refreshes_the_alignment_memo_so_a_fresh_reopen_finds_nothing_stale(
    tmp_path: Path,
) -> None:
    """V11-000a review fix F6: apply_scripture_edit writes the word-alignment
    `invalid` marker (tc_project.py) as a side effect of every Scripture
    edit, which changes what Stage 6B's WORD_ALIGNMENT evidence should find
    -- so it must refresh the alignment invalidation memo in the same call,
    not leave that for the next project reopen to notice. Without that, a
    location run published later in the same session already reflects the
    post-edit state, but a freshly reopened runtime -- comparing current
    disk state against a memo that never advanced -- incorrectly stales it.
    This is the reproduction from docs/V11-000a_REVIEW_FIX_PROMPT.md F6; it
    fails on 370be9c.
    """
    runtime = _runtime(tmp_path)
    runtime.project.attach_passage_semantic_runtime(runtime)
    engine = SemanticLocationEngine(runtime)
    engine.run_range("1", "3")  # establishes the pre-edit memo baseline

    runtime.project.apply_scripture_edit("1", "3", "I thank my Lord")

    published = engine.run_range("1", "3")
    assert _run_status(runtime.repository, published["id"]) == "ACTIVE"

    reopened_project = TranslationCoreProject(runtime.project.path)
    reopened = PassageSemanticRuntime(reopened_project, runtime.project_id)
    reopened_project.attach_passage_semantic_runtime(reopened)

    assert _run_status(reopened.repository, published["id"]) == "ACTIVE"
    assert reopened.synchronize_alignment_state() == {"changed": False, "staled": 0}


def _completable_project(tmp_path: Path) -> Path:
    root = tmp_path / "php-en-completable"
    (root / "php").mkdir(parents=True)
    (root / ".apps" / "translationCore" / "alignmentData" / "php").mkdir(parents=True)
    (root / "manifest.json").write_text(json.dumps({
        "project": {"id": "php", "name": "Philippians"},
        "target_language": {"id": "en"}, "resource": {"id": "test"}, "tc_version": "8",
    }), encoding="utf-8")
    (root / "php" / "1.json").write_text(json.dumps({"3": "God"}, ensure_ascii=False), encoding="utf-8")
    (root / ".apps" / "translationCore" / "alignmentData" / "php" / "1.json").write_text(json.dumps({
        "3": {
            "alignments": [{
                "topWords": [{
                    "word": "Θεῷ", "occurrence": 1, "occurrences": 1,
                    "strong": "G2316", "lemma": "θεός", "morph": "Gr,N,,,,,DMS,",
                }],
                "bottomWords": [{"word": "God", "occurrence": 1, "occurrences": 1}],
            }],
            "wordBank": [],
        },
    }), encoding="utf-8")
    (root / "php.usfm").write_text("\\id PHP\n\\c 1\n\\p\n\\v 3 OLD IMPORTED\n", encoding="utf-8")
    return root


def test_completing_an_alignment_through_the_rpc_refreshes_the_memo_so_a_fresh_reopen_finds_nothing_stale(
    tmp_path: Path,
) -> None:
    """V11-000a review fix F6, complete_alignment side: this RPC (unlike
    realign/unalign/save/undo) does not go through _finish_alignment_mutation,
    so without its own memo refresh a location run published right after
    completion is likewise over-invalidated on the next reopen. Same
    reproduction shape as the apply_scripture_edit regression above, through
    the real BridgeEngine RPC surface.
    """
    root = _completable_project(tmp_path)
    engine = BridgeEngine()
    engine.open_project(str(root))
    runtime = engine.passage_semantic_runtime
    assert runtime is not None

    location = SemanticLocationEngine(runtime)
    location.run_range("1", "3")  # pre-completion memo baseline

    completed = engine.complete_alignment("1", "3")
    assert completed["completionState"] == "completed"

    published = location.run_range("1", "3")
    assert _run_status(runtime.repository, published["id"]) == "ACTIVE"

    reopened_project = TranslationCoreProject(root)
    reopened = PassageSemanticRuntime(reopened_project, runtime.project_id)
    reopened_project.attach_passage_semantic_runtime(reopened)

    assert _run_status(reopened.repository, published["id"]) == "ACTIVE"
    assert reopened.synchronize_alignment_state() == {"changed": False, "staled": 0}
