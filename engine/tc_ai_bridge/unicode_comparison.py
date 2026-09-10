"""Unicode-canonical, grapheme-safe text preparation for semantic comparison.

This module creates transient comparison keys only.  It never mutates or
persists Scripture text, and its output must never be used as a correction
coordinate space.  Persistent Bridge spans remain half-open Unicode
code-point offsets over the authoritative raw text.

NFC is used because it makes canonically equivalent spellings stable while
preserving compatibility distinctions.  Unicode case folding is applied for
the existing case-insensitive Stage 7 comparisons, then NFC is applied again
because case folding itself can produce decomposed sequences.

``regex``'s Unicode ``\\X`` implementation provides extended grapheme clusters.
The resulting orthographic runs are deliberately modest comparison tokens,
not a claim of linguistic word segmentation.  In particular, Thai, Khmer,
Lao, and Myanmar text without spaces can remain a single run.
"""
from __future__ import annotations

from functools import lru_cache
import unicodedata

import regex


COMPARISON_NORMALIZATION_VERSION = "unicode-comparison-nfc-grapheme-v2"
COMPARISON_NORMALIZATION_FORM = "NFC"

_GRAPHEME_RE = regex.compile(r"\X")


def canonical_comparison_text(value: str) -> str:
    """Return a canonically stable, case-insensitive transient text value."""
    raw = str(value or "")
    return unicodedata.normalize(
        COMPARISON_NORMALIZATION_FORM,
        unicodedata.normalize(COMPARISON_NORMALIZATION_FORM, raw).casefold(),
    )


def comparison_graphemes(value: str) -> tuple[str, ...]:
    """Return Unicode extended grapheme clusters without changing the input."""
    return tuple(match.group(0) for match in _GRAPHEME_RE.finditer(str(value or "")))


def _without_biblical_hebrew_annotations(value: str) -> str:
    """Fold U+0591..U+05C7 combining annotations to their consonantal base.

    Stage 7's small controlled Hebrew inventories intentionally compare
    pointed/cantillated UHB forms with unpointed forms.  This is an explicit
    Biblical-Hebrew comparison policy, not the default Unicode normalizer and
    not a rewrite of UHB tokens.  Marks in every other script remain present.
    """
    decomposed = unicodedata.normalize("NFD", value)
    folded = "".join(
        character
        for character in decomposed
        if not (
            "\u0591" <= character <= "\u05c7"
            and unicodedata.category(character).startswith("M")
        )
    )
    return unicodedata.normalize(COMPARISON_NORMALIZATION_FORM, folded)


def comparison_tokens(
    value: str, *, ignore_biblical_hebrew_annotations: bool = False,
) -> tuple[str, ...]:
    """Build punctuation-delimited orthographic runs without dropping marks.

    A run must contain at least one Unicode Letter or Number.  Mark and Format
    clusters are retained when attached to, or occurring between, such
    material.  Standalone malformed marks/format controls fail closed by not
    becoming semantic tokens.  Separators, punctuation, and symbols are token
    boundaries; this preserves the prior Stage 7 punctuation behavior.
    """
    normalized = canonical_comparison_text(value)
    if ignore_biblical_hebrew_annotations:
        normalized = _without_biblical_hebrew_annotations(normalized)

    tokens: list[str] = []
    current: list[str] = []
    pending_internal: list[str] = []

    def flush() -> None:
        if current:
            tokens.append("".join(current))
        current.clear()
        pending_internal.clear()

    for cluster in comparison_graphemes(normalized):
        categories = tuple(unicodedata.category(character) for character in cluster)
        has_base = any(category.startswith(("L", "N")) for category in categories)
        only_marks = bool(categories) and all(category.startswith("M") for category in categories)
        only_format = bool(categories) and all(category == "Cf" for category in categories)

        if has_base:
            if current and pending_internal:
                current.extend(pending_internal)
            pending_internal.clear()
            current.append(cluster)
        elif only_marks and current:
            # Some script data classifies a spacing vowel sign as a separate
            # grapheme even when it follows its base.  It is still part of the
            # orthographic run and must not be dropped at end of input.
            current.append(cluster)
        elif only_format and current:
            pending_internal.append(cluster)
        else:
            flush()

    flush()
    return tuple(tokens)


@lru_cache(maxsize=8192)
def _cached_comparison_normalize(
    value: str, ignore_biblical_hebrew_annotations: bool,
) -> str:
    return " ".join(
        comparison_tokens(
            value,
            ignore_biblical_hebrew_annotations=ignore_biblical_hebrew_annotations,
        )
    )


def comparison_normalize(
    value: str, *, ignore_biblical_hebrew_annotations: bool = False,
) -> str:
    """Return Stage 7's deterministic space-joined semantic comparison key.

    The bounded cache avoids re-segmenting the small controlled comparison
    inventories for every semantic unit.  It stores comparison keys only in
    process memory and has no effect on persistent cache or Scripture text.
    """
    return _cached_comparison_normalize(
        str(value or ""), bool(ignore_biblical_hebrew_annotations),
    )
