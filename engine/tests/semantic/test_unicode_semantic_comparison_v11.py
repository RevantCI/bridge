from __future__ import annotations

import unicodedata

import pytest

from tc_ai_bridge.unicode_comparison import (
    COMPARISON_NORMALIZATION_VERSION,
    canonical_comparison_text,
    comparison_graphemes,
    comparison_normalize,
    comparison_tokens,
)


@pytest.mark.parametrize(
    ("script", "raw", "expected"),
    [
        ("Tamil", "இல்லை", "இல்லை"),
        ("Devanagari", "नहीं", "नहीं"),
        ("Malayalam", "മലയാളം", "മലയാളം"),
        ("Telugu", "తెలుగు", "తెలుగు"),
        ("Bengali", "বাংলা", "বাংলা"),
        ("Kannada", "ಕನ್ನಡ", "ಕನ್ನಡ"),
        ("Gujarati", "નહીં", "નહીં"),
        ("Gurmukhi", "ਨਹੀਂ", "ਨਹੀਂ"),
        ("Odia", "ନାହିଁ", "ନାହିଁ"),
        ("Arabic", "عَرَبِيّ", "عَرَبِيّ"),
        ("Greek", "Ἰησοῦς", "ἰησοῦσ"),
        ("Vietnamese", "Việt", "việt"),
        ("Latin", "CAFÉ", "café"),
        ("Thai", "ไม่", "ไม่"),
        ("Khmer", "ខ្មែរ", "ខ្មែរ"),
        ("Myanmar", "မြန်မာ", "မြန်မာ"),
        ("Lao", "ບໍ່", "ບໍ່"),
        ("Sinhala", "සිංහල", "සිංහල"),
    ],
)
def test_world_script_marks_survive_comparison_token_construction(
    script: str, raw: str, expected: str,
) -> None:
    assert comparison_normalize(raw) == expected, script
    assert "".join(comparison_graphemes(canonical_comparison_text(raw))) == (
        canonical_comparison_text(raw)
    )


@pytest.mark.parametrize(
    "raw",
    [
        "café",
        "Việt",
        "Ἰησοῦς",
        "בְּרֵאשִׁית",
        "கொண்டு",
        "नहीं",
    ],
)
def test_canonically_equivalent_nfc_and_nfd_have_one_comparison_key(raw: str) -> None:
    assert comparison_normalize(unicodedata.normalize("NFC", raw)) == comparison_normalize(
        unicodedata.normalize("NFD", raw)
    )


def test_biblical_hebrew_annotation_fold_is_explicit_and_other_marks_remain() -> None:
    pointed = "בְּרֵאשִׁ֖ית"
    assert comparison_normalize(pointed) == unicodedata.normalize("NFC", pointed)
    assert comparison_normalize(pointed, ignore_biblical_hebrew_annotations=True) == "בראשית"
    assert comparison_normalize("عَرَبِيّ", ignore_biblical_hebrew_annotations=True) == "عَرَبِيّ"
    assert comparison_normalize("இல்லை", ignore_biblical_hebrew_annotations=True) == "இல்லை"


def test_punctuation_is_a_boundary_without_becoming_mark_removal() -> None:
    assert comparison_tokens("‘café’—இல்லை, नहीं!") == (
        "café", "இல்லை", "नहीं",
    )
    assert comparison_normalize("word's quoted–word") == "word s quoted word"


def test_format_characters_are_preserved_inside_orthographic_runs() -> None:
    devanagari = "क्\u200dष"
    joined = "a\u2060b"
    assert comparison_normalize(devanagari) == devanagari
    assert comparison_normalize(joined) == joined
    assert comparison_normalize("\u200fא\u200f") == "א"


@pytest.mark.parametrize("raw", ["", "—!?", "\u0301", "🙂", "🙂தமிழ்🙂", "𐤀"])
def test_unexpected_or_malformed_unicode_fails_safely(raw: str) -> None:
    result = comparison_normalize(raw)
    assert isinstance(result, str)
    if raw == "🙂தமிழ்🙂":
        assert result == "தமிழ்"
    if raw == "𐤀":
        assert result == raw


def test_normalization_contract_is_explicitly_versioned() -> None:
    assert COMPARISON_NORMALIZATION_VERSION == "unicode-comparison-nfc-grapheme-v2"
