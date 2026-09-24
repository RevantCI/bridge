"""The corpus lexicon and its rules (layered-rules Phase 5).

`lexicon.json` (built by scripts/build_tamil_lexicon.py, bundled with the
pack) holds how often each word occurs in the IRV corpus, the words common
enough to suggest, their precomputed one-cluster deletion neighbours, and a
curated map of known misspellings. Two rules use it:

- `lexicon.rare-near-common`: a word rare in this book (at most
  RARE_BOOK_MAX times) and rare in the corpus (absent from, or at most
  RARE_CORPUS_MAX in, the lexicon) that is within MAX_DISTANCE of words
  common in the corpus (at least COMMON_MIN, and RATIO_MIN times the rare
  word's own corpus count). Up to five ranked suggestions, by (distance,
  corpus count, same-book count), each with its evidence. It replaces the
  within-book wordlist audit whenever a pack has a lexicon.
- `lexicon.known-misspelling`: a word in the curated `deprecated` map, with its
  correction. Confidence high: it is a reviewed correction, not a guess.

The lexicon is evidence for ranking and never learns by itself: translator
decisions are reported for a human to fold into the curated list
(scripts/lexicon_feedback_report.py), never written back (DECISIONS.md).
"""
from __future__ import annotations

import functools
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .tamil_distance import clusters, tamil_distance

LEXICON_VERSION = "ta-irv-lexicon@1"
# Build-time bounds (scripts/build_tamil_lexicon.py).
MIN_LISTED_COUNT = 3   # a word seen fewer times is not listed: absent means rare
COMMON_MIN = 6         # corpus count a suggestion needs
# The rule's thresholds, in one place; docs/LANGUAGE_QA_BENCHMARK.md cites them.
RARE_BOOK_MAX = 2
RARE_CORPUS_MAX = 2
RATIO_MIN = 5
# 0.5: the typist confusions only (tamil_distance). At 1.0 -- any one cluster
# edit -- Tamil inflection floods it: 2,931 findings at 0.8% strict precision
# on the review set, against 76 at 2.6% here (BUILD_LOG, Phase 5).
MAX_DISTANCE = 0.5
MIN_CLUSTERS = 3
MAX_SUGGESTIONS = 5
MAX_LEXICON_FINDINGS = 200

LEXICON_PATH = Path(__file__).resolve().parent / "ta-irv" / "lexicon.json"


def deletion_keys(word: str) -> set[str]:
    """The word with one grapheme cluster removed, every way."""
    parts = clusters(word)
    return {"".join(parts[:i] + parts[i + 1:]) for i in range(len(parts))}


@dataclass
class Lexicon:
    version: str
    forms: dict[str, list[int]]
    common: list[str]
    buckets: dict[str, list[int]]
    deprecated: dict[str, str]
    corpus: dict[str, Any]

    def count(self, word: str) -> int:
        entry = self.forms.get(word)
        return int(entry[0]) if entry else 0

    def candidates(self, word: str) -> set[str]:
        """Common words sharing a one-cluster deletion neighbour with `word`
        (covers one substitution, insertion or deletion)."""
        found: set[str] = set()
        for key in {word, *deletion_keys(word)}:
            for index in self.buckets.get(key, ()):
                found.add(self.common[index])
        found.discard(word)
        return found


def load_lexicon(path: Path | None = None) -> Lexicon | None:
    path = path or LEXICON_PATH
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return Lexicon(version=str(data.get("version") or LEXICON_VERSION), forms=data.get("forms") or {},
                   common=list(data.get("common") or []), buckets=data.get("buckets") or {},
                   deprecated=data.get("deprecated") or {}, corpus=data.get("corpus") or {})


_LOADED: dict[str, Lexicon | None] = {}


def default_lexicon() -> Lexicon | None:
    """The bundled lexicon, loaded once, on first need (never at startup)."""
    if "ta-irv" not in _LOADED:
        _LOADED["ta-irv"] = load_lexicon()
    return _LOADED["ta-irv"]


def lexicon_findings(book: str, counts: dict[str, int],
                     first_seen: dict[str, tuple[str, str, int, int, str, str]],
                     lexicon: Lexicon, *, rule_fields: Any, suggestion: Any, rule_version: str,
                     ) -> list[dict[str, Any]]:
    """Pure function over one book's word counts. `first_seen` maps a word to
    (chapter, verse, start, end, originalText, textHash) of its first
    occurrence; the finding sits there. `rule_fields`/`suggestion` are
    language_qa's own builders (passed in to keep the import one-way)."""
    findings: list[dict[str, Any]] = []
    near = 0  # the cap is per rule: the noisier rule must not crowd out the reviewed one
    for word in sorted(counts):
        if word not in first_seen:
            continue
        chapter, verse, start, end, original, text_hash = first_seen[word]
        right = lexicon.deprecated.get(word)
        if right:
            findings.append(_finding(
                book, "lexicon.known-misspelling", word, chapter, verse, start, end, original, text_hash,
                f'"{word}" is a reviewed misspelling of "{right}" in this project\'s corrections. Verify this occurrence.',
                [suggestion(right, "lexicon", "Reviewed correction (Round 2 / Pass 3 reports)")],
                rule_fields, rule_version))
            continue
        book_count = counts[word]
        corpus_count = lexicon.count(word)
        if (near >= MAX_LEXICON_FINDINGS or book_count > RARE_BOOK_MAX or corpus_count > RARE_CORPUS_MAX
                or len(clusters(word)) < MIN_CLUSTERS):
            continue
        ranked = []
        for candidate in lexicon.candidates(word):
            candidate_count = lexicon.count(candidate)
            if candidate_count < COMMON_MIN or candidate_count < max(1, corpus_count) * RATIO_MIN:
                continue
            distance = tamil_distance(word, candidate)
            if distance > MAX_DISTANCE:
                continue
            ranked.append((distance, -candidate_count, -counts.get(candidate, 0), candidate))
        if not ranked:
            continue
        ranked.sort()
        suggestions = [
            suggestion(candidate, "lexicon",
                       f"occurs {-corpus}× in the corpus, {-same}× in this book (distance {distance:g})")
            for distance, corpus, same, candidate in ranked[:MAX_SUGGESTIONS]
        ]
        best = ranked[0][3]
        findings.append(_finding(
            book, "lexicon.rare-near-common", word, chapter, verse, start, end, original, text_hash,
            (f'"{word}" occurs {book_count}× in this book and {corpus_count}× in the corpus; '
             f'"{best}" occurs {-ranked[0][1]}× in the corpus. Verify whether this is a misspelling '
             f'or a distinct word or name.'),
            suggestions, rule_fields, rule_version))
        near += 1
    return findings


def _finding(book, rule, word, chapter, verse, start, end, original, text_hash, message, suggestions,
             rule_fields, rule_version) -> dict[str, Any]:
    identity = f"{book}:{rule}:{word}"
    return {
        "id": hashlib.sha1(identity.encode("utf-8", errors="surrogatepass")).hexdigest()[:20],
        "book": book, "chapter": chapter, "verse": verse, "rule": rule,
        "severity": "medium" if rule == "lexicon.known-misspelling" else "low",
        "start": start, "end": end, "originalText": original, "message": message,
        "textHash": text_hash, "ruleVersion": rule_version, "status": "review-needed",
        **rule_fields(rule, suggestions),
    }


@functools.lru_cache(maxsize=1)
def lexicon_fingerprint() -> str:
    lexicon = default_lexicon()
    return f"{lexicon.version}:{len(lexicon.forms)}:{len(lexicon.deprecated)}" if lexicon else "none"
