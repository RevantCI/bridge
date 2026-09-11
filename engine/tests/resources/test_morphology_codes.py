from __future__ import annotations

from tc_ai_bridge.morphology_codes import decode_morph


def test_hebrew_simple_noun():
    language_id, segments = decode_morph("He,Ncmsa")

    assert language_id == "hbo"
    assert len(segments) == 1
    assert segments[0].label == "Noun, Common, Masculine, Singular, Absolute"


def test_hebrew_verb():
    _, segments = decode_morph("He,Vqp3ms")

    assert segments[0].label == "Verb, Qal, Perfect, 3rd person, Masculine, Singular"


def test_hebrew_compound_preposition_plus_noun_splits_on_colon():
    _, segments = decode_morph("He,R:Ncfsa")

    assert [s.label for s in segments] == ["Preposition", "Noun, Common, Feminine, Singular, Absolute"]


def test_hebrew_definite_article_plus_noun_matches_genesis_1_1():
    _, segments = decode_morph("He,Td:Ncbsa")

    assert segments[0].label == "Particle (definite article)"
    assert segments[1].label == "Noun, Common, Both genders, Singular, Absolute"


def test_greek_finite_verb():
    _, segments = decode_morph("Gr,V,IAA3,,S,")

    assert segments[0].label == "Verb, Indicative, Aorist, Active, 3rd person, Singular"


def test_greek_participle_uses_case_gender_number_not_person():
    _, segments = decode_morph("Gr,V,PPA,NMS,")

    assert segments[0].label == "Verb, Participle, Present, Active, Nominative, Masculine, Singular"


def test_greek_article():
    _, segments = decode_morph("Gr,EA,,,,NMS,")

    assert segments[0].label == "Definite article, Nominative, Masculine, Singular"


def test_greek_preposition_notes_governed_case():
    _, segments = decode_morph("Gr,P,,,,,A,,,")

    assert segments[0].label == "Preposition, governs the Accusative"


def test_unrecognized_language_prefix_falls_back_to_raw_text():
    language_id, segments = decode_morph("Xx,weird,code")

    assert language_id is None
    assert segments[0].raw == "Xx,weird,code"


def test_empty_morph_returns_no_segments():
    assert decode_morph("") == (None, [])
    assert decode_morph(None) == (None, [])
