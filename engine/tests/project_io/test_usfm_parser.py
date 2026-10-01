"""The shared USFM parser (#91): usfmtc decides structure, text is cut from the source."""
from __future__ import annotations

import io
import re
from contextlib import redirect_stdout

import pytest

from tc_ai_bridge.project_import import parse_scripture_file
from tc_ai_bridge.usfm import whitespace_tokens
from tc_ai_bridge.usfm_parser import HEADING_MARKERS, UsfmParseError, parse_usfm


def _verses(parsed):
    return {(v.chapter, v.verse): v.text for v in parsed.verses}


def test_real_irv_files_parse_to_the_expected_verse_counts(tamil_php_usfm, tamil_luk_usfm):
    for path, book, count in ((tamil_php_usfm, "PHP", 104), (tamil_luk_usfm, "LUK", 1140)):
        parsed = parse_usfm(path.read_text(encoding="utf-8-sig").replace("\r\n", "\n"))
        assert parsed.book_code == book
        assert len(parsed.verses) == count


def test_no_verse_ends_with_the_next_heading(tamil_php_usfm, tamil_luk_usfm):
    """#92: the heading between two verses belonged to neither verse's text."""
    for path in (tamil_php_usfm, tamil_luk_usfm):
        parsed = parse_usfm(path.read_text(encoding="utf-8-sig").replace("\r\n", "\n"))
        assert parsed.headings
        heading_marker = re.compile(r"\\(%s)\b" % "|".join(sorted(HEADING_MARKERS, key=len, reverse=True)))
        assert not [v for v in parsed.verses if heading_marker.search(v.text)]
        order = [(v.chapter, v.verse) for v in parsed.verses]
        texts = _verses(parsed)
        for heading in parsed.headings:
            introduced = order.index((heading.chapter, heading.verse))
            if introduced:
                previous = texts[order[introduced - 1]]
                assert not whitespace_tokens(previous)[-len(whitespace_tokens(heading.text)):] == whitespace_tokens(heading.text)


def test_philippians_1_2_ends_before_its_heading_and_the_heading_introduces_1_3(tamil_php_usfm):
    parsed = parse_usfm(tamil_php_usfm.read_text(encoding="utf-8-sig").replace("\r\n", "\n"))
    assert _verses(parsed)[("1", "2")].endswith("உண்டாவதாக.")
    introduces_3 = [h for h in parsed.headings if (h.chapter, h.verse) == ("1", "3")]
    assert [(h.tag, h.text) for h in introduces_3] == [("s", "நன்றி சொல்லுதலும் ஜெபமும்")]


def test_verse_text_is_a_verbatim_slice_notes_included(tamil_php_usfm):
    """Stored text is cut from the source, not re-serialised by the parser."""
    source = tamil_php_usfm.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    verse = _verses(parse_usfm(source))[("1", "1")]
    assert "\\x + \\xo 1:1 \\xt அப் 16:12\\x*" in verse
    assert verse in source


def test_an_unclosed_xt_inside_a_footnote_is_read_leniently(tamil_luk_usfm):
    """Luke's line 255 has `\\xt ... \\f*` with no `\\xt*`; the TC reference parser
    accepts it, and so must an import."""
    source = tamil_luk_usfm.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    assert "\\xt ஆதி 12:1-3 \\f*" in source
    parsed = parse_usfm(source)
    assert len(parsed.verses) == 1140


def test_bridges_and_segments_stay_opaque_strings():
    parsed = parse_usfm("\\id TIT\n\\c 1\n\\p\n\\v 1 one\n\\v 2-3 bridged\n\\v 4a first\n\\v 4b second\n")
    assert [v.verse for v in parsed.verses] == ["1", "2-3", "4a", "4b"]


def test_a_verse_that_does_not_start_its_line_is_still_a_verse():
    """The line regex it replaced lost `\\q1 \\v 1 ...` entirely when it opened a
    chapter (text before a chapter's first line-initial \\v was discarded) --
    263 verses of ESV poetry on the development corpus."""
    parsed = parse_usfm("\\id JOB\n\\c 10\n\\q1 \\v 1 I loathe my life;\n\\q2 I will speak.\n\\q1 \\v 2 I will say\n")
    assert _verses(parsed) == {
        ("10", "1"): "I loathe my life;\n\\q2 I will speak.\n\\q1",
        ("10", "2"): "I will say",
    }


def test_headings_are_filed_against_the_verse_they_introduce():
    parsed = parse_usfm(
        "\\id TIT\n\\c 1\n\\s Opening\n\\p\n\\v 1 a\n\\v 2 b\n\\s The work\n\\p\n\\v 3 c\n\\s Trailing\n"
        "\\c 2\n\\p\n\\v 1 d\n"
    )
    assert [(h.chapter, h.verse, h.text) for h in parsed.headings] == [
        ("1", "1", "Opening"), ("1", "3", "The work"), ("1", "3", "Trailing"),
    ]
    assert _verses(parsed)[("1", "2")] == "b"
    assert _verses(parsed)[("1", "3")] == "c"


def test_descriptive_title_stays_in_the_verse():
    """\\d is translated content (a Psalm superscription), not a heading."""
    parsed = parse_usfm("\\id PSA\n\\c 3\n\\q1\n\\v 1 a\n\\d A Psalm of David\n\\q1\n\\v 2 b\n")
    assert "A Psalm of David" in _verses(parsed)[("3", "1")]
    assert not parsed.headings


def test_headers_come_from_the_preamble_in_order():
    parsed = parse_usfm("\\id PHP ta_Tamil_ltr\n\\usfm 3.0\n\\ide UTF-8\n\\h Phil\n\\toc1 Letter\n\\c 1\n\\v 1 a\n")
    assert [(h.tag, h.content) for h in parsed.headers] == [
        ("id", "PHP ta_Tamil_ltr"), ("usfm", "3.0"), ("ide", "UTF-8"), ("h", "Phil"), ("toc1", "Letter"),
    ]
    assert parsed.header("h") == "Phil"
    assert parsed.id_line == "PHP ta_Tamil_ltr"


def test_alignment_milestones_survive_verbatim_in_verse_text():
    raw = ('\\zaln-s |x-strong="G1" x-lemma="a" x-occurrence="1" x-occurrences="1" x-content="A"\\*'
           '\\w word|x-occurrence="1" x-occurrences="1"\\w*\\zaln-e\\* rest.')
    parsed = parse_usfm(f"\\id TIT\n\\c 1\n\\p\n\\v 1 {raw}\n")
    assert _verses(parsed)[("1", "1")] == raw


def test_short_input_is_never_mistaken_for_a_filename():
    """Handed a bare string, usfmtc opens it as a file when os.path.exists says
    so and raises FileNotFoundError for any short one-line string that is not."""
    parsed = parse_usfm("\\c 1")
    assert parsed.chapters == ("1",)


def test_parsing_never_writes_to_stdout(tamil_php_usfm):
    """stdout is the sidecar's JSON-lines channel."""
    captured = io.StringIO()
    with redirect_stdout(captured):
        parse_usfm(tamil_php_usfm.read_text(encoding="utf-8-sig").replace("\r\n", "\n"))
    assert captured.getvalue() == ""


def test_import_tokens_match_the_parsers_own_plain_text(tamil_luk_usfm):
    """Every consumer tokenises the stored slice with whitespace_tokens; the words
    it yields must be the Scripture words the parser saw, nothing from headings."""
    book = parse_scripture_file(tamil_luk_usfm)
    heading_words = {
        word for chapter in book.headings.values() for items in chapter.values()
        for item in items for word in whitespace_tokens(item["text"])
    }
    stored_words = {w for verses in book.chapters.values() for text in verses.values() for w in whitespace_tokens(text)}
    # Heading-only vocabulary (words that never occur in Scripture) must be absent.
    assert heading_words - stored_words
    assert book.verse_count == 1140


def test_a_numberless_verse_marker_keeps_its_text_with_the_verse_before_it():
    """A real IRV Isaiah has `\\v \\x - \\xo 61:2 ...`. The line regex stored that
    text under the verse key "\\x"; it is Scripture, so it stays with 61:1, and
    only the numberless `\\v` token is removed."""
    parsed = parse_usfm(
        "\\id ISA\n\\c 61\n\\p\n\\v 1 one,\n\\v \\x - \\xo 61:2: \\xt Mt 5:4\\x*two,\n\\v 3 three\n"
    )
    assert [v.verse for v in parsed.verses] == ["1", "3"]
    assert _verses(parsed)[("61", "1")] == "one,\n\\x - \\xo 61:2: \\xt Mt 5:4\\x*two,"
    assert any("61:1" in w and "no verse number at line 5" in w for w in parsed.warnings)


def test_chapter_chunking_changes_nothing(tamil_php_usfm, tamil_luk_usfm, monkeypatch):
    """The book is handed to usfmtc a chapter at a time (its lexer is quadratic
    in input length). A chapter boundary resets all state, so the result must
    equal a single whole-book parse."""
    from tc_ai_bridge import usfm_parser

    for path in (tamil_php_usfm, tamil_luk_usfm):
        text = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
        chunked = parse_usfm(text)
        with monkeypatch.context() as patch:
            patch.setattr(usfm_parser, "_chapter_chunks", lambda value: [value])
            whole = parse_usfm(text)
        assert chunked.verses == whole.verses
        assert chunked.headings == whole.headings
        assert chunked.headers == whole.headers


def test_a_chapter_marker_mid_line_is_still_a_chapter():
    parsed = parse_usfm("\\id TIT\n\\c 1\n\\p\n\\v 1 a\n\\p \\c 2\n\\p\n\\v 1 b\n")
    assert parsed.chapters == ("1", "2")
    assert _verses(parsed) == {("1", "1"): "a\n\\p", ("2", "1"): "b"}


def test_identify_reads_the_preamble_and_counts_verse_markers():
    from tc_ai_bridge.usfm_parser import identify_usfm

    identity = identify_usfm("\\id PHP ta_Tamil_ltr\n\\h Phil\n\\c 1\n\\p\n\\v 1 a\n\\q1 \\v 2 b\n\\c 2\n\\v 1 c\n")
    assert identity.book_code == "PHP"
    assert identity.id_line == "PHP ta_Tamil_ltr"
    assert [(h.tag, h.content) for h in identity.headers] == [("id", "PHP ta_Tamil_ltr"), ("h", "Phil")]
    assert identity.has_chapters
    assert identity.verse_markers == 3


def test_preview_verse_count_matches_the_full_parse_on_real_files(tamil_php_usfm, tamil_luk_usfm):
    from tc_ai_bridge.project_import import identify_scripture_file

    for path in (tamil_php_usfm, tamil_luk_usfm):
        identity = identify_scripture_file(path)
        book = parse_scripture_file(path)
        assert (identity.book_id, identity.book_name, identity.verse_count) == (
            book.book_id, book.book_name, book.verse_count,
        )


def test_input_the_parser_cannot_read_is_a_parse_error(monkeypatch):
    import usfmtc

    def boom(*args, **kwargs):
        raise RuntimeError("grammar exploded")

    monkeypatch.setattr(usfmtc.USX, "fromUsfm", boom)
    with pytest.raises(UsfmParseError, match="grammar exploded"):
        parse_usfm("\\id TIT\n\\c 1\n\\v 1 a\n")


def _text_from_spans(source: str, verse) -> str:
    head = source[verse.start:verse.head_end]
    tail = [source[a:b] for a, b in verse.tail_spans]
    return "\n".join(head.split("\n") + tail).strip()


def test_verse_spans_reproduce_the_verse_text_on_real_files(tamil_php_usfm, tamil_luk_usfm):
    """An export writes current text back at [start, head_end) and deletes the
    tail spans (#190), so those offsets must be exactly where `text` came from."""
    for path in (tamil_php_usfm, tamil_luk_usfm):
        source = path.read_text(encoding="utf-8-sig")
        parsed = parse_usfm(source)
        for verse in parsed.verses:
            assert _text_from_spans(source, verse) == verse.text, (path.name, verse.chapter, verse.verse)
            assert verse.start <= verse.head_end
            assert source[verse.start - 1] in " \t", (verse.chapter, verse.verse)


def test_verse_spans_for_a_heading_inside_a_verse_and_a_mid_line_verse():
    source = (
        "\\id PSA\n\\c 1\n\\p\n"
        "\\v 1 Blessed is the man.\n"
        "\\s The wicked\n"
        "\\q1 \\v 2 Not so,\n\\q2 like chaff.\n"
        "\\v 3 Head text\n\\s Odd heading mid-verse\n\\p\nTail scripture line.\n"
    )
    parsed = parse_usfm(source)
    by_verse = {v.verse: v for v in parsed.verses}
    one, two, three = by_verse["1"], by_verse["2"], by_verse["3"]
    assert source[one.start:one.head_end] == "Blessed is the man."
    assert one.tail_spans == ()
    # The mid-line verse's span starts after its own marker; the `\\q1 ` before it is untouched.
    assert source[two.start:two.head_end] == "Not so,\n\\q2 like chaff."
    assert source[two.start - 5:two.start] == "\\v 2 "
    # Scripture after a heading inside the verse is a tail span; the heading and `\\p` are not.
    assert source[three.start:three.head_end] == "Head text"
    assert [source[a:b] for a, b in three.tail_spans] == ["Tail scripture line."]
    assert three.text == "Head text\nTail scripture line."
    for verse in parsed.verses:
        assert _text_from_spans(source, verse) == verse.text
