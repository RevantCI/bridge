import pytest

from tc_ai_bridge.aligned_usfm import AlignedUsfmError, render_aligned_verse
from tc_ai_bridge.models import AlignmentGroup, TokenRef, VerseAlignment


def _top(word, occurrence=1, occurrences=1):
    return TokenRef(
        word, occurrence, occurrences,
        strong="H1", lemma=word, morph="He,Ncmsa",
    )


def _bottom(word, occurrence=1, occurrences=1):
    return TokenRef(word, occurrence, occurrences, type="bottomWord")


def test_repeated_words_keep_occurrence_identity_and_punctuation():
    alignment = VerseAlignment([
        AlignmentGroup([_top("א", 1, 2)], [_bottom("word", 1, 2)]),
        AlignmentGroup([_top("א", 2, 2)], [_bottom("word", 2, 2)]),
    ], [])

    rendered = render_aligned_verse("“word word.”", alignment)

    assert rendered.startswith("“\\zaln-s")
    assert 'x-occurrence="1" x-occurrences="2"\\w*' in rendered
    assert 'x-occurrence="2" x-occurrences="2"\\w*' in rendered
    assert rendered.endswith("\\zaln-e\\*.”")


def test_inline_markers_and_footnotes_are_preserved_without_aligning_note_text():
    alignment = VerseAlignment([
        AlignmentGroup([_top("א")], [_bottom("Added")]),
        AlignmentGroup([_top("ב")], [_bottom("text")]),
    ], [])
    source = "\\add Added\\add* text. \\f + \\ft note text\\f*"

    rendered = render_aligned_verse(source, alignment)

    assert "\\add " in rendered and "\\add*" in rendered
    assert "\\f + \\ft note text\\f*" in rendered
    assert "\\w note" not in rendered


def test_discontinuous_target_group_is_rejected_instead_of_changing_meaning():
    alignment = VerseAlignment([
        AlignmentGroup([_top("א")], [_bottom("one"), _bottom("three")]),
        AlignmentGroup([_top("ב")], [_bottom("two")]),
    ], [])

    with pytest.raises(AlignedUsfmError, match="discontinuous"):
        render_aligned_verse("one two three", alignment)


def test_aligned_export_requires_original_language_tokens():
    alignment = VerseAlignment([], [_bottom("target")])

    with pytest.raises(AlignedUsfmError, match="No original-language source tokens"):
        render_aligned_verse("target", alignment)
