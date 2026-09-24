"""Tamil confusion-set distance (layered-rules Phase 5.2).

A weighted edit distance over grapheme clusters (`regex` `\\X`). Inserting,
deleting or substituting a cluster costs 1, except for the confusions a Tamil
typist actually makes, which cost 0.5:

- the consonant pairs ர/ற, ல/ள/ழ, ண/ன/ந, with the same vowel sign;
- short/long vowels: எ/ஏ, ஒ/ஓ, இ/ஈ, உ/ஊ as independent letters, and their
  signs ெ/ே, ொ/ோ, ி/ீ, ு/ூ on the same consonant;
- ஐ/அய் and ஔ/அவ் (one cluster against two);
- the same consonant with and without pulli (க/க்), or with and without ா
  (க/கா).

Comparison keys are NFC; the text itself is never normalised or rewritten.
This is the confusion set the brief names. It is not a model of Tamil
spelling, and a distance below the threshold is a reason to suggest, not a
verdict.
"""
from __future__ import annotations

import functools
import unicodedata

import regex

CLUSTER = regex.compile(r"\X")
PULLI = "்"
AA = "ா"
LOW = 0.5

_CONSONANT_SETS = ("ரற", "லளழ", "ணனந")
_VOWEL_PAIRS = ("எஏ", "ஒஓ", "இஈ", "உஊ")
_SIGN_PAIRS = ("ெே", "ொோ", "ிீ", "ுூ")  # ெே ொோ ிீ ுூ
# One cluster against two clusters, cost LOW.
_SPLITS = {"ஐ": ("அ", "ய்"), "ஔ": ("அ", "வ்")}

_CONSONANT_GROUP = {c: group for group in _CONSONANT_SETS for c in group}
_VOWEL_GROUP = {c: pair for pair in _VOWEL_PAIRS for c in pair}
_SIGN_GROUP = {c: pair for pair in _SIGN_PAIRS for c in pair}


def clusters(text: str) -> list[str]:
    return CLUSTER.findall(unicodedata.normalize("NFC", text))


def _split(cluster: str) -> tuple[str, str]:
    """(base letter, the marks after it)."""
    return cluster[:1], cluster[1:]


@functools.lru_cache(maxsize=65536)
def substitution_cost(a: str, b: str) -> float:
    if a == b:
        return 0.0
    base_a, marks_a = _split(a)
    base_b, marks_b = _split(b)
    if not marks_a and not marks_b and base_a in _VOWEL_GROUP and _VOWEL_GROUP[base_a] == _VOWEL_GROUP.get(base_b):
        return LOW
    if marks_a == marks_b and base_a in _CONSONANT_GROUP and _CONSONANT_GROUP[base_a] == _CONSONANT_GROUP.get(base_b):
        return LOW
    if base_a == base_b:
        if {marks_a, marks_b} in ({"", PULLI}, {"", AA}):
            return LOW
        if len(marks_a) == len(marks_b) == 1 and marks_a in _SIGN_GROUP and _SIGN_GROUP[marks_a] == _SIGN_GROUP.get(marks_b):
            return LOW
    return 1.0


def tamil_distance(a: str, b: str) -> float:
    """Weighted edit distance between two words (see the module docstring)."""
    x, y = clusters(a), clusters(b)
    n, m = len(x), len(y)
    previous = [float(j) for j in range(m + 1)]
    rows = [previous]
    for i in range(1, n + 1):
        current = [float(i)] + [0.0] * m
        for j in range(1, m + 1):
            best = min(previous[j] + 1.0, current[j - 1] + 1.0,
                       previous[j - 1] + substitution_cost(x[i - 1], y[j - 1]))
            # One cluster against two (ஐ/அய், ஔ/அவ்), in either direction.
            if j >= 2 and _SPLITS.get(x[i - 1]) == (y[j - 2], y[j - 1]):
                best = min(best, previous[j - 2] + LOW)
            if i >= 2 and _SPLITS.get(y[j - 1]) == (x[i - 2], x[i - 1]):
                best = min(best, rows[i - 2][j - 1] + LOW)
            current[j] = best
        rows.append(current)
        previous = current
    return previous[m]
