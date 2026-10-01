"""The overlay's source skeleton comes from the parser (#91 Phase 3c).

`build_current_text_overlay` lays current chapter JSON over a marker-only
skeleton of the preserved source. The skeleton used to be a line regex; it is
now `ParsedUsfm.headers` + `ParsedUsfm.structure`. These pin the event stream
the overlay consumes, including the two places the parser reads the source
better than the regex did: a mid-line `\\v` is a verse, and a mid-line `\\c` is
a chapter.
"""
from __future__ import annotations

from tc_ai_bridge.passage_semantic_models import PassageStructureKind
from tc_ai_bridge.passage_semantic_runtime import _source_skeleton, build_current_text_overlay
from tc_ai_bridge.tc_project import TranslationCoreProject
from tests.support.semantic import semantic_runtime


def _events(source: str):
    return [(e.kind, e.value, e.inline, e.keep) for e in _source_skeleton(source)]


def test_headers_then_body_structure_with_inline_markers_and_keep_flags():
    source = (
        "\\id PHP Philippians\n\\usfm 3.0\n\\ide UTF-8\n\\h Philippians\n\\toc1 The Letter\n\\mt1 Philippians\n"
        "\\c 1\n\\p\n"
        "\\v 1 Paul \\nd Lord\\nd*, \\f + \\fr 1.1 \\ft note\\f* servant.\n"
        "\\q2 a continuation with \\wj words\\wj*\n"
        "\\s A heading\n\\q1 \\v 2 Grace.\n"
    )
    assert _events(source) == [
        ("m", "id", (), False),
        ("m", "usfm", (), True),
        ("m", "ide", (), False),
        ("m", "h", (), False),
        ("m", "toc1", (), False),
        ("m", "mt1", (), True),
        ("c", "1", (), True),
        ("m", "p", (), True),
        ("v", "1", ("nd", "nd", "f", "fr", "ft", "f"), True),
        ("m", "q2", ("wj", "wj"), True),
        ("m", "s", (), True),
        ("m", "q1", (), True),      # the `\q1` that opens the mid-line verse: no spurious "v"
        ("v", "2", (), True),       # ...and the verse itself is a verse event
    ]


def test_a_chapter_marker_mid_line_is_a_chapter():
    assert [(e.kind, e.value) for e in _source_skeleton("\\id PHP\n\\p \\c 1\n\\v 1 a\n\\p \\c 2\n\\v 1 b\n")] == [
        ("m", "id"), ("m", "p"), ("c", "1"), ("v", "1"), ("m", "p"), ("c", "2"), ("v", "1"),
    ]


def test_overlay_structure_markers_record_notes_and_styles_on_the_verse_line(tmp_path):
    runtime = semantic_runtime(tmp_path, project_prefix="skeleton", chapters={"1": {"1": "current text."}})
    usfm = runtime.project.path / "php.usfm"
    usfm.write_text(
        "\\id PHP\n\\c 1\n\\p\n\\v 1 old \\nd Lord\\nd* \\f + \\ft n\\f* words\n\\q2 \\wj red\\wj*\n",
        encoding="utf-8",
    )
    overlay = build_current_text_overlay(TranslationCoreProject(runtime.project.path))
    kinds = [(m.marker, m.kind, m.displayed_reference) for m in overlay.structure_markers]
    assert ("nd", PassageStructureKind.INLINE_MARKUP, "PHP 1:1") in kinds
    assert ("f", PassageStructureKind.NOTE, "PHP 1:1") in kinds
    assert ("q2", PassageStructureKind.POETRY, None) in kinds        # after the last verse: introduces none
    assert ("wj", PassageStructureKind.INLINE_MARKUP, None) in kinds
    assert [s.text for s in overlay.index.segments] == ["current text."]
    assert overlay.mismatches == ()
