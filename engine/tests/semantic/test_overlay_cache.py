"""The two-level cache on build_current_text_overlay (#91 Phase 3a).

rebuild_current_passage runs in loops (affected re-analysis, word-alignment
evidence, Stage 6B per range) and each call used to re-parse the whole book
twice. Level 1 caches the source skeleton by the preserved file's hash; level 2
caches the finished overlay by (path, source hash, hash of the current chapter
JSON). A verse edit therefore misses level 2 and hits level 1; a changed source
file misses both; a guard failure is never cached.
"""
from __future__ import annotations

import json

import pytest

from tc_ai_bridge import passage_semantic_runtime as runtime_module
from tc_ai_bridge.passage_semantic_runtime import (
    FoundationValidationError, build_current_text_overlay, clear_overlay_caches,
)
from tc_ai_bridge.tc_project import TranslationCoreProject
from tests.support.semantic import semantic_runtime


@pytest.fixture(autouse=True)
def _fresh_caches():
    clear_overlay_caches()
    yield
    clear_overlay_caches()


class _Counter:
    def __init__(self, monkeypatch, name):
        self.calls = 0
        original = getattr(runtime_module, name)

        def counted(*args, **kwargs):
            self.calls += 1
            return original(*args, **kwargs)

        monkeypatch.setattr(runtime_module, name, counted)


def test_a_second_build_for_unchanged_inputs_is_served_from_the_cache(tmp_path, monkeypatch):
    project = semantic_runtime(tmp_path, project_prefix="cache").project
    skeletons = _Counter(monkeypatch, "_source_skeleton")
    parses = _Counter(monkeypatch, "_authoritative_current_segments")
    first = build_current_text_overlay(project)
    second = build_current_text_overlay(project)
    assert second is first
    assert skeletons.calls == 1 and parses.calls == 1


def test_a_verse_edit_rebuilds_the_overlay_but_keeps_the_source_skeleton(tmp_path, monkeypatch):
    project = semantic_runtime(tmp_path, project_prefix="cache").project
    skeletons = _Counter(monkeypatch, "_source_skeleton")
    before = build_current_text_overlay(project)
    chapter = project.path / "php" / "1.json"
    verses = json.loads(chapter.read_text(encoding="utf-8"))
    verses["3"] = "திருத்தப்பட்ட வசனம்."
    chapter.write_text(json.dumps(verses, ensure_ascii=False), encoding="utf-8")
    after = build_current_text_overlay(TranslationCoreProject(project.path))
    assert after is not before
    assert {s.reference: s.text for s in after.index.segments}["PHP 1:3"] == "திருத்தப்பட்ட வசனம்."
    assert skeletons.calls == 1  # the preserved source did not change


def test_a_changed_source_file_misses_both_levels(tmp_path, monkeypatch):
    project = semantic_runtime(tmp_path, project_prefix="cache").project
    skeletons = _Counter(monkeypatch, "_source_skeleton")
    before = build_current_text_overlay(project)
    usfm = project.path / "php.usfm"
    usfm.write_text(usfm.read_text(encoding="utf-8").replace("\\p\n", "\\p\n\\q1\n", 1), encoding="utf-8")
    after = build_current_text_overlay(TranslationCoreProject(project.path))
    assert after is not before and after.structure_hash != before.structure_hash
    assert skeletons.calls == 2
    assert any(m.marker == "q1" for m in after.structure_markers)


def test_a_guard_failure_is_not_cached(tmp_path, monkeypatch):
    project = semantic_runtime(tmp_path, project_prefix="cache").project
    monkeypatch.setattr(runtime_module, "_authoritative_current_segments", lambda *_a, **_k: {})
    with pytest.raises(FoundationValidationError):
        build_current_text_overlay(project)
    monkeypatch.undo()
    overlay = build_current_text_overlay(project)  # a fresh, correct build
    assert {s.reference for s in overlay.index.segments} >= {"PHP 1:3", "PHP 1:6"}


def test_two_projects_with_the_same_source_share_the_skeleton_not_the_overlay(tmp_path, monkeypatch):
    one = semantic_runtime(tmp_path / "a", project_prefix="cache").project
    two = semantic_runtime(tmp_path / "b", project_prefix="cache").project
    skeletons = _Counter(monkeypatch, "_source_skeleton")
    first = build_current_text_overlay(one)
    second = build_current_text_overlay(two)
    assert first is not second                 # different paths are different overlays
    assert skeletons.calls == 1                # but one identical source file, parsed once
