from __future__ import annotations

from tc_ai_bridge.lexicon_resources import lexicon_entry_for_strong


def test_hebrew_lookup_matches_golden_translationcore_style_gloss():
    entry = lexicon_entry_for_strong("H776", "hbo")

    assert entry["lemma"] == "אֶרֶץ"
    assert entry["meaning"] == "the earth (at large, or partitively a land)"
    assert entry["usage"] == (
        "× common, country, earth, field, ground, land, × natins, way, + wilderness, world."
    )
    assert entry["derivation"] == "from an unused root probably meaning to be firm;"


def test_hebrew_lookup_normalizes_leading_zero_padding():
    assert lexicon_entry_for_strong("H0776", "hbo") == lexicon_entry_for_strong("H776", "hbo")


def test_hebrew_lookup_strips_oshb_homonym_disambiguation_letter():
    # "H1254a" is the exact strong value OSHB uses for ברא ("create") in
    # Genesis 1:1 — OSHB's own homonym-disambiguation letter, not present in
    # the classic Strong's dictionary this looks up, so it must be stripped.
    assert lexicon_entry_for_strong("H1254a", "hbo") == lexicon_entry_for_strong("H1254", "hbo")
    assert lexicon_entry_for_strong("H1254", "hbo") is not None


def test_greek_lookup_strips_ugnt_trailing_variant_digit():
    entry = lexicon_entry_for_strong("G23160", "el-x-koine")

    assert entry is not None
    assert entry["lemma"] == "θεός"


def test_unresolved_strong_returns_none_rather_than_raising():
    assert lexicon_entry_for_strong("H999999", "hbo") is None
    assert lexicon_entry_for_strong("", "hbo") is None
