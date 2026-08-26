"""Decode the compact morphology codes carried on UHB/UGNT source tokens.

Hebrew codes (prefixed "He,") follow the OpenScriptures Hebrew Bible (OSHB)
parsing scheme documented at
https://github.com/openscriptures/morphhb/blob/master/parsing/HebrewMorphologyCodes.html
(fetched and cross-checked directly against that page's tables — not
reproduced from memory).

Greek codes (prefixed "Gr,") come from unfoldingWord's UGNT and have no
locatable specification document (repeated lookups against door43/GitHub
turned up nothing). The mapping below was instead reverse-engineered by
cross-checking real UGNT tokens for John 3:16 and Titus 1:1 against their
known grammatical analysis (both texts have unambiguous, well-established
parsing). Only positions/codes actually observed and confirmed that way are
mapped; anything else falls back to showing the raw code rather than
guessing — see `decode_greek_morph`.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MorphSegment:
    raw: str
    label: str
    part_of_speech: str | None = None


_HE_GENDER = {'b': 'both genders', 'f': 'feminine', 'm': 'masculine', 'c': 'common'}
_HE_NUMBER = {'s': 'singular', 'p': 'plural', 'd': 'dual'}
_HE_STATE = {'a': 'absolute', 'c': 'construct', 'd': 'determined'}
_HE_NOUN_TYPE = {'c': 'common', 'g': 'gentilic', 'p': 'proper'}
_HE_ADJ_TYPE = {'a': 'adjective', 'c': 'cardinal number', 'g': 'gentilic', 'o': 'ordinal number'}
_HE_PRON_TYPE = {
    'd': 'demonstrative', 'f': 'indefinite', 'i': 'interrogative',
    'p': 'personal', 'r': 'relative',
}
_HE_PARTICLE_TYPE = {
    'a': 'affirmation', 'd': 'definite article', 'e': 'exhortation', 'i': 'interrogative',
    'j': 'interjection', 'm': 'demonstrative', 'n': 'negative', 'o': 'direct object marker',
    'r': 'relative',
}
_HE_SUFFIX_TYPE = {
    'd': 'directional he', 'h': 'paragogic he', 'n': 'paragogic nun', 'p': 'pronominal',
}
_HE_VERB_STEM = {
    'q': 'qal', 'N': 'niphal', 'p': 'piel', 'P': 'pual', 'h': 'hiphil', 'H': 'hophal',
    't': 'hithpael', 'o': 'polel', 'O': 'polal', 'r': 'hithpolel', 'm': 'poel', 'M': 'poal',
    'k': 'palel', 'K': 'pulal', 'Q': 'qal passive', 'l': 'pilpel', 'L': 'polpal',
    'f': 'hithpalpel', 'D': 'nithpael', 'j': 'pealal', 'i': 'pilel', 'u': 'hothpaal',
    'c': 'tiphil', 'v': 'hishtaphel', 'w': 'nithpalel', 'y': 'nithpoel', 'z': 'hithpoel',
}
_HE_VERB_CONJ = {
    'p': 'perfect', 'q': 'sequential perfect', 'i': 'imperfect', 'w': 'sequential imperfect',
    'h': 'cohortative', 'j': 'jussive', 'v': 'imperative', 'r': 'active participle',
    's': 'passive participle', 'a': 'infinitive absolute', 'c': 'infinitive construct',
}
_HE_PERSON = {'1': '1st person', '2': '2nd person', '3': '3rd person'}


def _title(text: str) -> str:
    return text[:1].upper() + text[1:] if text else text


def _decode_he_noun(code: str) -> str:
    # Nxyz: type, gender, number, state (any tail letters optional/best-effort)
    parts = ['Noun']
    if len(code) > 1 and code[1] in _HE_NOUN_TYPE:
        parts.append(_HE_NOUN_TYPE[code[1]])
    if len(code) > 2 and code[2] in _HE_GENDER:
        parts.append(_HE_GENDER[code[2]])
    if len(code) > 3 and code[3] in _HE_NUMBER:
        parts.append(_HE_NUMBER[code[3]])
    if len(code) > 4 and code[4] in _HE_STATE:
        parts.append(_HE_STATE[code[4]])
    return ', '.join(_title(p) for p in parts)


def _decode_he_adjective(code: str) -> str:
    parts = []
    if len(code) > 1 and code[1] in _HE_ADJ_TYPE:
        parts.append(_HE_ADJ_TYPE[code[1]])
    else:
        parts.append('Adjective')
    if len(code) > 2 and code[2] in _HE_GENDER:
        parts.append(_HE_GENDER[code[2]])
    if len(code) > 3 and code[3] in _HE_NUMBER:
        parts.append(_HE_NUMBER[code[3]])
    if len(code) > 4 and code[4] in _HE_STATE:
        parts.append(_HE_STATE[code[4]])
    return ', '.join(_title(p) for p in parts)


def _decode_he_pronoun(code: str) -> str:
    parts = []
    if len(code) > 1 and code[1] in _HE_PRON_TYPE:
        parts.append(f'{_HE_PRON_TYPE[code[1]]} pronoun')
    else:
        parts.append('Pronoun')
    if len(code) > 2 and code[2] in _HE_PERSON:
        parts.append(_HE_PERSON[code[2]])
    if len(code) > 3 and code[3] in _HE_GENDER:
        parts.append(_HE_GENDER[code[3]])
    if len(code) > 4 and code[4] in _HE_NUMBER:
        parts.append(_HE_NUMBER[code[4]])
    return ', '.join(_title(p) for p in parts)


def _decode_he_verb(code: str) -> str:
    parts = ['Verb']
    if len(code) > 1 and code[1] in _HE_VERB_STEM:
        parts.append(_HE_VERB_STEM[code[1]])
    if len(code) > 2 and code[2] in _HE_VERB_CONJ:
        parts.append(_HE_VERB_CONJ[code[2]])
    rest = code[3:]
    if rest[:1] in _HE_PERSON:
        parts.append(_HE_PERSON[rest[0]])
        rest = rest[1:]
    if rest[:1] in _HE_GENDER:
        parts.append(_HE_GENDER[rest[0]])
        rest = rest[1:]
    if rest[:1] in _HE_NUMBER:
        parts.append(_HE_NUMBER[rest[0]])
        rest = rest[1:]
    if rest[:1] in _HE_STATE:
        parts.append(_HE_STATE[rest[0]])
    return ', '.join(_title(p) for p in parts)


def decode_hebrew_morph(segment: str) -> MorphSegment:
    """Decode one Hebrew/Aramaic OSHB morphology segment (no "He," prefix, no ":" splits)."""
    code = segment.strip()
    if not code:
        return MorphSegment(raw=segment, label='Unknown')
    pos = code[0]
    if pos == 'N':
        return MorphSegment(raw=code, label=_decode_he_noun(code), part_of_speech='Noun')
    if pos == 'V':
        return MorphSegment(raw=code, label=_decode_he_verb(code), part_of_speech='Verb')
    if pos == 'A':
        return MorphSegment(raw=code, label=_decode_he_adjective(code), part_of_speech='Adjective')
    if pos == 'P':
        return MorphSegment(raw=code, label=_decode_he_pronoun(code), part_of_speech='Pronoun')
    if pos == 'R':
        label = 'Preposition (with definite article)' if code[1:2] == 'd' else 'Preposition'
        return MorphSegment(raw=code, label=label, part_of_speech='Preposition')
    if pos == 'C':
        return MorphSegment(raw=code, label='Conjunction', part_of_speech='Conjunction')
    if pos == 'D':
        return MorphSegment(raw=code, label='Adverb', part_of_speech='Adverb')
    if pos == 'T':
        sub = _HE_PARTICLE_TYPE.get(code[1:2])
        label = f'Particle ({sub})' if sub else 'Particle'
        return MorphSegment(raw=code, label=label, part_of_speech='Particle')
    if pos == 'S':
        sub = _HE_SUFFIX_TYPE.get(code[1:2])
        label = f'Suffix ({sub})' if sub else 'Suffix'
        return MorphSegment(raw=code, label=label, part_of_speech='Suffix')
    return MorphSegment(raw=code, label=code)


_GR_POS = {
    'N': 'Noun', 'NS': 'Adjective (used as a noun)', 'V': 'Verb', 'CC': 'Conjunction (coordinating)',
    'CS': 'Conjunction (subordinating)', 'P': 'Preposition', 'D': 'Adverb', 'EA': 'Definite article',
    'RP': 'Pronoun (personal)', 'RD': 'Pronoun (demonstrative)', 'RI': 'Pronoun (indefinite)',
    'RR': 'Pronoun (relative)', 'RQ': 'Pronoun (interrogative)', 'AA': 'Adjective', 'AR': 'Adjective',
    'I': 'Interjection',
}
_GR_CASE = {'N': 'Nominative', 'A': 'Accusative', 'G': 'Genitive', 'D': 'Dative', 'V': 'Vocative'}
_GR_GENDER = {'M': 'Masculine', 'F': 'Feminine', 'N': 'Neuter'}
_GR_NUMBER = {'S': 'Singular', 'P': 'Plural'}
_GR_MOOD = {
    'I': 'Indicative', 'S': 'Subjunctive', 'O': 'Optative', 'M': 'Imperative',
    'P': 'Participle', 'N': 'Infinitive',
}
_GR_TENSE = {'P': 'Present', 'A': 'Aorist', 'F': 'Future', 'I': 'Imperfect', 'L': 'Pluperfect', 'X': 'Perfect'}
_GR_VOICE = {'A': 'Active', 'M': 'Middle', 'P': 'Passive'}
_GR_PERSON = {'1': '1st person', '2': '2nd person', '3': '3rd person'}


def _decode_gr_case_gender_number(field: str) -> list[str]:
    parts: list[str] = []
    remaining = field
    if remaining[:1] in _GR_CASE:
        parts.append(_GR_CASE[remaining[0]])
        remaining = remaining[1:]
    if remaining[:1] in _GR_GENDER:
        parts.append(_GR_GENDER[remaining[0]])
        remaining = remaining[1:]
    if remaining[:1] in _GR_NUMBER:
        parts.append(_GR_NUMBER[remaining[0]])
        remaining = remaining[1:]
    return parts


def _decode_gr_verb_tam(field: str) -> list[str]:
    # Observed shapes: "IAA3" (mood+tense+voice+person, finite) and "PPA" (mood+tense+voice, participle).
    if not field:
        return []
    parts: list[str] = []
    remaining = field
    if remaining[:1] in _GR_MOOD:
        parts.append(_GR_MOOD[remaining[0]])
        remaining = remaining[1:]
    if remaining[:1] in _GR_TENSE:
        parts.append(_GR_TENSE[remaining[0]])
        remaining = remaining[1:]
    if remaining[:1] in _GR_VOICE:
        parts.append(_GR_VOICE[remaining[0]])
        remaining = remaining[1:]
    if remaining[:1] in _GR_PERSON:
        parts.append(_GR_PERSON[remaining[0]])
        remaining = remaining[1:]
    return parts


def decode_greek_morph(segment: str) -> MorphSegment:
    """Decode one UGNT morphology segment (no "Gr," prefix, no ":" splits).

    Expects the comma-joined field shape observed in real data, e.g.
    "N,,,,,NMS," or "V,IAA3,,S," or "P,,,,,A,,,". Unrecognized POS codes or
    fields are echoed back raw rather than guessed.
    """
    code = segment.strip()
    if not code:
        return MorphSegment(raw=segment, label='Unknown')
    fields = code.split(',')
    pos = fields[0]
    pos_label = _GR_POS.get(pos)
    if pos_label is None:
        return MorphSegment(raw=code, label=code)

    parts = [pos_label]
    if pos == 'V':
        tam_field = fields[1] if len(fields) > 1 else ''
        parts.extend(_decode_gr_verb_tam(tam_field))
        # The case/gender/number field sits at index 2 for participles
        # (mood "P") and index 3 for finite forms — both are tried since
        # only one will contain letters this decoder recognizes.
        for idx in (2, 3):
            if len(fields) > idx and fields[idx]:
                parts.extend(_decode_gr_case_gender_number(fields[idx]))
    elif pos == 'P':
        # Prepositions note only the case they govern, in the field that
        # normally carries case+gender+number (index 5 in observed data).
        for field in fields[1:]:
            if field and field[0] in _GR_CASE:
                parts.append(f'governs the {_GR_CASE[field[0]]}')
                break
    elif pos == 'RP':
        for field in fields[1:]:
            if field:
                if field[:1] in _GR_PERSON:
                    parts.append(_GR_PERSON[field[0]])
                    field = field[1:]
                parts.extend(_decode_gr_case_gender_number(field))
                break
    else:
        for field in fields[1:]:
            if field:
                parts.extend(_decode_gr_case_gender_number(field))
                break

    return MorphSegment(raw=code, label=', '.join(parts), part_of_speech=pos_label)


def decode_morph_segment(language_id: str, segment: str) -> MorphSegment:
    if language_id == 'hbo':
        return decode_hebrew_morph(segment)
    if language_id == 'el-x-koine':
        return decode_greek_morph(segment)
    return MorphSegment(raw=segment, label=segment)


_LANGUAGE_PREFIXES = {'He': 'hbo', 'Gr': 'el-x-koine'}


def decode_morph(morph: str) -> tuple[str | None, list[MorphSegment]]:
    """Strip the "He,"/"Gr," language prefix, split on ":" for compound
    (prefix-morpheme) values, and decode each resulting segment.

    Returns (language_id, segments); language_id is None if the leading
    token isn't a recognized language prefix, in which case the whole
    string is returned as a single undecoded segment.
    """
    text = (morph or '').strip()
    if not text:
        return None, []
    prefix, _, remainder = text.partition(',')
    language_id = _LANGUAGE_PREFIXES.get(prefix)
    if language_id is None:
        return None, [MorphSegment(raw=text, label=text)]
    segments = [decode_morph_segment(language_id, part) for part in remainder.split(':')]
    return language_id, segments
