"""One-time characterisation for #91 Phase 1b: `strip_usfm`/`whitespace_tokens`
moved from their own regexes onto the fragment reader. The regex implementation
they replaced is frozen here, verbatim, and compared on every stored verse of
both IRV fixtures. Tokens must be identical -- they feed tC
`word/occurrence/occurrences`, so a change there is an alignment change -- and
the text may differ only where the old code inserted a space for a marker.

Delete this file in #91 Phase 4, when the old code it characterises is a memory.
"""
from __future__ import annotations

import re

from tc_ai_bridge.usfm import strip_usfm, whitespace_tokens
from tc_ai_bridge.usfm_parser import parse_usfm

_TRIM = ' \t\r\n.,;:!?“”‘’"\'()[]{}<>—–…।॥'


def _old_strip_usfm(text: str) -> str:
    text = re.sub(r'\\f\s.*?\\f\*', ' ', text, flags=re.S)
    text = re.sub(r'\\x\s.*?\\x\*', ' ', text, flags=re.S)
    text = re.sub(r'\\[A-Za-z0-9+_-]+\*?', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()


def _old_whitespace_tokens(text: str) -> list[str]:
    cleaned = _old_strip_usfm(text)
    return [t for t in (raw.strip(_TRIM) for raw in cleaned.split()) if t] if cleaned else []


def _verses(path):
    return parse_usfm(path.read_text(encoding="utf-8-sig")).verses


def test_tokens_are_identical_to_the_regex_tokeniser_on_both_irv_books(tamil_php_usfm, tamil_luk_usfm):
    for path in (tamil_php_usfm, tamil_luk_usfm):
        for verse in _verses(path):
            assert whitespace_tokens(verse.text) == _old_whitespace_tokens(verse.text), (
                path.name, verse.chapter, verse.verse,
            )


def test_text_differs_only_by_the_space_the_regex_put_around_a_marker(tamil_php_usfm, tamil_luk_usfm):
    # Measured 2026-10-01 before the switch: PHP 0 verses, LUK 14 verses,
    # every one a note or marker the old code replaced with a space next to
    # punctuation (`word .` vs `word.`). Pinned so a different kind of drift
    # cannot hide behind these numbers.
    expected = {tamil_php_usfm.name: 0, tamil_luk_usfm.name: 14}
    for path in (tamil_php_usfm, tamil_luk_usfm):
        differing = [v for v in _verses(path) if strip_usfm(v.text) != _old_strip_usfm(v.text)]
        assert len(differing) == expected[path.name], [(v.chapter, v.verse) for v in differing][:5]
        for verse in differing:
            # Removing the spaces the old code inserted makes them agree.
            assert strip_usfm(verse.text).replace(" ", "") == _old_strip_usfm(verse.text).replace(" ", "")


def test_what_changed_on_purpose():
    # The old code put a space where a marker was; the reader removes the
    # marker and nothing else. Both are visible in English more than Tamil.
    assert _old_strip_usfm("the \\nd Lord\\nd*, said") == "the Lord , said"
    assert strip_usfm("the \\nd Lord\\nd*, said") == "the Lord, said"
    assert _old_whitespace_tokens("the \\nd Lord\\nd*’s throne") == ["the", "Lord", "s", "throne"]
    assert whitespace_tokens("the \\nd Lord\\nd*’s throne") == ["the", "Lord’s", "throne"]
    # Attributes were visible text to the old code; they never were Scripture.
    assert _old_whitespace_tokens('\\w word|x-occurrence="1"\\w*') == ['word|x-occurrence="1']  # closing quote trimmed
    assert whitespace_tokens('\\w word|x-occurrence="1"\\w*') == ["word"]
