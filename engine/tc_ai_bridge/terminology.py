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
            note = str(term.get("note") or "")
            for rejected in term.get("rejectedRenderings") or []:
                rejected = str(rejected).strip()
                if not rejected:
                    continue
                tokens = phrase_tokens(rejected)
                if not tokens or len(tokens) > MAX_PHRASE_WORDS:
                    continue  # malformed/unsupported entry: skip, don't crash, don't widen the search bound
                self._by_phrase[tokens] = {
                    "conceptId": concept_id, "rejectedForm": rejected,
                    "preferredRenderings": preferred, "note": note,
                }
                self.max_phrase_length = max(self.max_phrase_length, len(tokens))

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
