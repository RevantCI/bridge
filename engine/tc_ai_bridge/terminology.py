"""Termbase domain module: term entries and phrase matching against target text.

Pure domain logic -- no I/O, no database access, no orchestration. Loading
terminology rows from a project and running this against a scan pass belongs
to the caller (language_qa_jobs.py), not here.

Only 'approved'-status entries are ever matchable: an automatically
discovered or freshly imported rendering must not be treated as authoritative
just because it exists. See tc_project.py's record_terminology_rule for the
status contract this enforces -- frequency is evidence, not authority.
"""
from __future__ import annotations

import unicodedata
from typing import Any

from .language_qa import WORD

MAX_PHRASE_WORDS = 6
MATCH_MODES = ("exact", "prefix")

# Termbase v3 (layered-rules 6.1). The closed list of case and plural endings
# a "prefix" entry is matched with, written as they are spoken; join_suffix()
# attaches them the way written Tamil does. It is deliberately small: a form
# outside it is added by hand under `inflectedForms`.
CASE_SUFFIXES = (
    "ஐ", "க்கு", "உக்கு", "இல்", "ஆல்", "ஓடு", "உடன்", "இன்", "உம்", "இடம்", "இலிருந்து",
    "கள்", "களை", "களுக்கு", "களின்", "களால்", "களோடு", "களும்",
)
PULLI = "்"
# An initial vowel of a suffix fuses with a consonant-final stem into a sign.
VOWEL_SIGNS = {"அ": "", "ஆ": "ா", "இ": "ி", "ஈ": "ீ", "உ": "ு", "ஊ": "ூ",
               "எ": "ெ", "ஏ": "ே", "ஐ": "ை", "ஒ": "ொ", "ஓ": "ோ", "ஔ": "ௌ"}


def join_suffix(word: str, suffix: str) -> str:
    """தேவன் + ஐ = தேவனை: a pulli-final stem and a vowel-initial suffix fuse
    into one syllable; anything else is simply joined."""
    word = unicodedata.normalize("NFC", word)
    if word.endswith(PULLI) and suffix[:1] in VOWEL_SIGNS:
        return unicodedata.normalize("NFC", word[:-1] + VOWEL_SIGNS[suffix[0]] + suffix[1:])
    return unicodedata.normalize("NFC", word + suffix)


def phrase_tokens(rendering: str) -> tuple[str, ...]:
    """NFC-normalized word tokens of one termbase rendering string."""
    return tuple(unicodedata.normalize("NFC", m.group()) for m in WORD.finditer(rendering))


class TermIndex:
    """Book-scoped index of authoritative deprecated-form phrases.

    Built once per scan pass from raw terminology_rules() rows; matching a
    verse against it is then a pure lookup, no re-validation per verse.
    """

    def __init__(self, terms: list[dict[str, Any]]):
        self._by_phrase: dict[tuple[str, ...], dict[str, Any]] = {}
        self.max_phrase_length = 1
        # Sort by conceptId so two entries that register the same rejected
        # phrase resolve deterministically regardless of the loader's own
        # return order -- "last wins" here means "lexically last conceptId",
        # a documented, stable tie-break rather than undefined behavior.
        ordered = sorted(
            (t for t in terms if isinstance(t, dict)),
            key=lambda t: str(t.get("conceptId") or ""),
        )
        for term in ordered:
            if term.get("status") != "approved":
                continue  # provisional/imported-unreviewed entries are never authoritative
            concept_id = str(term.get("conceptId") or "").strip()
            if not concept_id:
                continue
            preferred = [str(r) for r in (term.get("approvedRenderings") or []) if str(r).strip()]
            allowed = [str(r) for r in (term.get("allowedAlternatives") or []) if str(r).strip()]
            note = str(term.get("note") or "")
            prefix = term.get("matchMode") == "prefix"
            inflected = term.get("inflectedForms") if isinstance(term.get("inflectedForms"), dict) else {}
            for rejected in term.get("rejectedRenderings") or []:
                rejected = str(rejected).strip()
                if not rejected:
                    continue
                # The rendering itself, then the forms a reviewer listed (as
                # authoritative as the rendering), then -- for a "prefix" entry
                # -- each case/plural ending, matched at medium confidence and
                # suggested with the same ending on the preferred form.
                variants = [(rejected, "", "high")]
                variants += [(str(f).strip(), "", "high") for f in inflected.get(rejected) or [] if str(f).strip()]
                if prefix:
                    variants += [(self._inflect(rejected, s), s, "medium") for s in CASE_SUFFIXES]
                for form, suffix, confidence in variants:
                    tokens = phrase_tokens(form)
                    if not tokens or len(tokens) > MAX_PHRASE_WORDS:
                        continue  # malformed/unsupported entry: skip, don't crash, don't widen the search bound
                    if tokens in self._by_phrase and confidence == "medium":
                        continue  # a generated form never displaces a listed one
                    ranked = [(self._inflect(p, suffix), "Preferred form") for p in preferred]
                    ranked += [(self._inflect(a, suffix), "Allowed alternative") for a in allowed]
                    self._by_phrase[tokens] = {
                        "conceptId": concept_id, "rejectedForm": rejected,
                        "preferredRenderings": preferred, "note": note, "confidence": confidence,
                        "matchedForm": form, "suffix": suffix,
                        "suggestions": ranked,
                        # A term may exist with only rejected forms recorded and no
                        # preferred one settled yet -- never invent one, None is a
                        # real, expected value here, not an oversight.
                        "suggestedReplacement": ranked[0][0] if ranked else None,
                    }
                    self.max_phrase_length = max(self.max_phrase_length, len(tokens))

    @staticmethod
    def _inflect(rendering: str, suffix: str) -> str:
        """The rendering with `suffix` on its last word (a multi-word
        rendering inflects at the end)."""
        if not suffix:
            return rendering
        head, _, last = rendering.rpartition(" ")
        return (head + " " if head else "") + join_suffix(last, suffix)

    def match(self, tokens: tuple[str, ...]) -> dict[str, Any] | None:
        return self._by_phrase.get(tokens)

    def __bool__(self) -> bool:
        return bool(self._by_phrase)


def find_deprecated_forms(text: str, index: TermIndex) -> list[dict[str, Any]]:
    """Word/phrase-boundary-aware exact matches of `index`'s deprecated forms in `text`.

    Returns raw match dicts (span + term metadata) in left-to-right order;
    the caller builds the actual finding shape and a stable id. Matching is
    whitespace-only-gap, NFC-normalized, never a naive substring search --
    the same discipline already proven by tamil.vallinam-missing and
    tamil.wordlist-variant.
    """
    if not index:
        return []
    positions = [(unicodedata.normalize("NFC", m.group()), m.start(), m.end())
                 for m in WORD.finditer(text)]
    matches: list[dict[str, Any]] = []
    total = len(positions)
    for i in range(total):
        max_length = min(index.max_phrase_length, total - i)
        for length in range(1, max_length + 1):
            if length > 1:
                gap = text[positions[i + length - 2][2]:positions[i + length - 1][1]]
                if not gap.isspace():
                    break  # a broken boundary here breaks every longer phrase from `i` too
            tokens = tuple(positions[i + k][0] for k in range(length))
            hit = index.match(tokens)
            if hit is not None:
                start, end = positions[i][1], positions[i + length - 1][2]
                matches.append({**hit, "start": start, "end": end, "matchedText": text[start:end]})
    return matches
