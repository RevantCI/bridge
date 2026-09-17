"""
UAlign-style corpus statistics over Bridge's own human-approved alignments.

See docs/BUILD_LOG.md's Phase 6 section for the full investigation
this module is built on. Summary: "UAlign" is real, unpublished vendored-repo
code — ``utilities/ualign.py`` in the same pinned ``BibleNLP/greek-room``
commit (``18ddcf0e6c03fa2774b73b21186115d712e4cba9``) already used for the
USFM checker, versification, and Smart Edit Distance (SED) — but it is a
3,600-line CLI script built around a ``fast_align``-style file pipeline
(Pharaoh-format alignment files, triple-pipe parallel-text files, ttable
model files) plus HTML visualization, morphology-variant checking, and a
spell-checker. None of that I/O shape or extra scope matches Bridge's own
data (tC's ``alignmentData/<book>/<chapter>.json``, already-loaded
``VerseAlignment``/``TokenRef`` objects) or its "backend data only" scope
for this phase. Rather than vendor the whole script and bridge two
incompatible file formats just to extract a few numbers, this module
reimplements the specific statistics — co-occurrence counts, translation
probability, PMI, and an optional Smart-Edit-Distance phonetic boost for
sparse pairs — directly against Bridge's own data, the same "reimplement
against our own shape" choice ``versification.py`` made for a different
reason (a real library vs. a monolithic script). The formulas mirror
``ualign.py``'s own ``AlignmentModel.support_probability()`` (verified by
reading that method directly, not guessed) but are original, small,
textbook implementations — not copied code — so this carries no new vendor
license obligation beyond the SED vendor tree already vendored and licensed
for Phase 5 (see ``engine/vendor/greekroom-smart-edit-distance/NOTICE.md``).

Scope for this pass, matching how the USFM checker, versification, and the
names check all shipped their first pass: protocol data only, no QaFinding
output. A future phase can layer findings (or AI explain) on top of this
data without recomputing it.
"""
from __future__ import annotations

import math
import sys
import threading
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .models import VerseAlignment
from .project_import import collection_projects
from .tc_project import TranslationCoreProject


def _vendor_root() -> Path:
    """Same frozen-vs-source resolution as names_adapter.py's _vendor_root()
    and versification.py's — this module is imported directly into
    bridge-engine, so in a frozen build the vendor tree must be resolved
    under sys._MEIPASS (already bundled by bridge-engine.spec's `datas` for
    Phase 5's names check; this module reuses that same vendored tree and
    needs no new packaging entry)."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "vendor" / "greekroom-smart-edit-distance"
    return Path(__file__).resolve().parent.parent / "vendor" / "greekroom-smart-edit-distance"


VENDOR_ROOT = _vendor_root()
COST_RULES_PATH = VENDOR_ROOT / "data" / "string-distance-cost-rules.txt"

# Mirrors ualign.py's AlignmentModel.support_probability(): a phonetic-boost
# term added to both the numerator and denominator of a translation
# probability, strongest (4.0) at cost 0, tapering to 0 at cost 1 (SED's own
# max_cost ceiling). Verified by reading that method directly (see this
# module's own docstring) rather than guessed from the general shape of the
# formula.
_SED_BOOST_SCALE = 4.0

# Hebrew and Greek Unicode blocks, used only to pick a reasonable Uroman
# lang-code hint for a source (original-language) token. This is a cheap
# script heuristic, not real testament/book detection (which would also
# need to account for Aramaic portions of Ezra/Daniel) — an approximation
# is acceptable here because a wrong hint only degrades one optional
# phonetic-boost signal, never crashes or produces an incorrect count/PMI
# value (those never depend on script detection at all).
_HEBREW_RANGE = (0x0590, 0x05FF)
_GREEK_RANGES = ((0x0370, 0x03FF), (0x1F00, 0x1FFF))


def _source_lang_hint(word: str) -> str:
    for ch in word:
        cp = ord(ch)
        if _HEBREW_RANGE[0] <= cp <= _HEBREW_RANGE[1]:
            return "hbo"
        for lo, hi in _GREEK_RANGES:
            if lo <= cp <= hi:
                return "grc"
    return ""


def _pmi(a_count: float, b_count: float, ab_count: float, total_count: float,
         smoothing: float = 1.0) -> float:
    """Pointwise mutual information. Standard textbook formula — the same
    one (unused) already vendored in ualign_utilities.py — reimplemented
    here directly rather than imported, to avoid coupling this module to
    versification.py's vendor-path/sys.path lifecycle for two lines of math
    with no vendor-specific tuning to preserve."""
    if a_count == 0 or b_count == 0 or total_count == 0:
        return 0.0
    p_a = a_count / total_count
    p_b = b_count / total_count
    expected_ab = p_a * p_b * total_count
    if expected_ab == 0 and smoothing == 0:
        return -99.0
    return math.log((ab_count + smoothing) / (expected_ab + smoothing))


_lock = threading.Lock()
_uroman = None
_uroman_unavailable = False
_sed_module = None
_sed_unavailable_reason: Optional[str] = None
_sed_cache: dict[tuple[str, str], Any] = {}


class AlignmentStatisticsUnavailable(RuntimeError):
    """Uroman or Smart Edit Distance could not be loaded — SED-boosted
    probability degrades gracefully to plain counts/PMI when this is
    raised; it never blocks the rest of the corpus-stats computation."""


def _ensure_uroman():
    """Lazy singleton, same shape as names_adapter.py's _ensure_uroman().

    Deliberately a SEPARATE instance from the names check's own singleton
    rather than a shared one: they live in different layers
    (greek_room_engine/adapters vs tc_ai_bridge) and sharing would require
    either a new cross-layer import or promoting the loader to a common
    module — a real refactor of already-shipped, tested Phase 5 code that
    is out of scope here. The accepted cost is a second ~1.8-2.1s Uroman
    table load if a session uses both features in the same process — a
    bounded, one-time cost, not a recurring one; see
    docs/BUILD_LOG.md's Phase 6 section for the explicit tradeoff.
    """
    global _uroman, _uroman_unavailable
    if _uroman is not None or _uroman_unavailable:
        return _uroman
    with _lock:
        if _uroman is not None or _uroman_unavailable:
            return _uroman
        try:
            import uroman as uroman_pkg
        except ImportError:
            _uroman_unavailable = True
            return None
        _uroman = uroman_pkg.Uroman()
        return _uroman


def _load_sed_module():
    global _sed_module, _sed_unavailable_reason
    if _sed_module is not None or _sed_unavailable_reason is not None:
        return _sed_module
    if not COST_RULES_PATH.is_file():
        _sed_unavailable_reason = f"cost rules file not found: {COST_RULES_PATH}"
        return None
    if str(VENDOR_ROOT) not in sys.path:
        sys.path.insert(0, str(VENDOR_ROOT))
    try:
        import smart_edit_distance as sed_mod
    except ImportError as exc:
        _sed_unavailable_reason = f"vendored smart_edit_distance module could not be imported: {exc}"
        return None
    _sed_module = sed_mod
    return _sed_module


def _ensure_sed(lang_code1: str, lang_code2: str):
    """Load (and cache) a SmartEditDistance instance for one (source-script,
    target-language) pair. Cached per pair for the same reason
    names_adapter.py caches per target language: language-restricted cost
    rules (::lc1/::lc2) are applied at LOAD time, not compare time."""
    key = (lang_code1 or "", lang_code2 or "")
    with _lock:
        cached = _sed_cache.get(key)
        if cached is not None:
            return cached
        sed_mod = _load_sed_module()
        if sed_mod is None:
            return None
        sd = sed_mod.SmartEditDistance()
        with COST_RULES_PATH.open(encoding="utf-8") as fh:
            sd.load_smart_edit_distance_data(fh, key[0], key[1])
        _sed_cache[key] = sd
        return sd


@dataclass
class CorpusPairStats:
    source_word: str
    target_word: str
    joint_count: int
    source_count: int
    target_count: int
    translation_probability: float
    pmi: float
    sed_cost: Optional[float] = None
    sed_boosted_probability: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "sourceWord": self.source_word,
            "targetWord": self.target_word,
            "jointCount": self.joint_count,
            "sourceCount": self.source_count,
            "targetCount": self.target_count,
            "translationProbability": round(self.translation_probability, 4),
            "pmi": round(self.pmi, 4),
        }
        if self.sed_cost is not None:
            out["sedCost"] = round(self.sed_cost, 4)
        if self.sed_boosted_probability is not None:
            out["sedBoostedProbability"] = round(self.sed_boosted_probability, 4)
        return out


def strong_key(strong: str) -> str:
    """A Strong's key that is self-consistent *within one project's own data*.

    Deliberately NOT `lexicon_resources.normalize_strong`: that maps onto the
    classic Strong's dictionary key and needs a `language_id` to know whether to
    strip UGNT's extra trailing variant digit — a language this table neither
    has nor needs. Here both sides of every comparison come from the same
    project's own alignmentData and the same pinned UHB/UGNT packs, so all that
    is required is that the same lemma always produces the same key.

    Leading zeros and OSHB's trailing homonym letter are still folded ("H0430"
    and "H430" are one lemma; "H1254a" and "H1254" are one lemma), because a
    collection can span packs. The H/G prefix is kept, so an OT and an NT book
    in one collection cannot collide (#138).

    UGNT's extra trailing "variant" digit is folded too ("G23160" and "G2316"
    are one lemma). `normalize_strong` needs a `language_id` to know whether to
    strip it; here the "G" prefix already says the number is Greek, so no
    language has to be plumbed through. It is stripped only from a 5-digit
    number, because classic Strong's Greek numbering stops at four digits --
    so a number already in the classic form is left alone rather than
    truncated into a different lemma.
    """
    text = str(strong or "").strip().upper()
    if len(text) < 2 or text[0] not in ("H", "G"):
        return ""
    digits = text[1:].rstrip("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
    if not digits.isdigit():
        return ""
    if text[0] == "G" and len(digits.lstrip("0") or "0") == 5:
        digits = (digits.lstrip("0") or "0")[:-1]
    return f"{text[0]}{digits.lstrip('0') or '0'}"


@dataclass
class CorpusStatsTable:
    """Aggregate bilingual co-occurrence statistics over every COMPLETED
    verse scanned. Source/target "word" identity is the exact surface
    token string (same identity tC itself uses for occurrence tracking) —
    not lemma-normalized, since target tokens generally have no lemma.

    #138 adds a second, parallel index keyed by Strong's number rather than
    surface form. The surface index is sparse for an inflected source language —
    every case and number of a Greek noun is its own key, so a rendering seen
    forty times can still read as forty singletons — while the Strong's index
    pools them. Both are kept: the surface pair is the more specific evidence
    when it exists, and the Strong's pair is what survives inflection.
    """
    source_counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    target_counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    pair_counts: dict[tuple[str, str], int] = field(default_factory=lambda: defaultdict(int))
    source_fertility: dict[str, Counter] = field(default_factory=lambda: defaultdict(Counter))
    target_fertility: dict[str, Counter] = field(default_factory=lambda: defaultdict(Counter))
    strong_counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    strong_pair_counts: dict[tuple[str, str], int] = field(default_factory=lambda: defaultdict(int))
    total_pairs: int = 0
    verses_scanned: int = 0
    books_scanned: list[str] = field(default_factory=list)

    def pair_stats(self, source_word: str, target_word: str, *,
                    with_sed_boost: bool = True) -> CorpusPairStats:
        joint = self.pair_counts.get((source_word, target_word), 0)
        s_count = self.source_counts.get(source_word, 0)
        t_count = self.target_counts.get(target_word, 0)
        probability = (joint / t_count) if t_count else 0.0
        pmi_score = _pmi(s_count, t_count, joint, self.total_pairs)

        sed_cost: Optional[float] = None
        sed_probability: Optional[float] = None
        if with_sed_boost:
            sed_cost, sed_probability = _sed_boosted_probability(
                source_word, target_word, joint_count=joint, target_count=t_count,
            )

        return CorpusPairStats(
            source_word=source_word, target_word=target_word,
            joint_count=joint, source_count=s_count, target_count=t_count,
            translation_probability=probability, pmi=pmi_score,
            sed_cost=sed_cost, sed_boosted_probability=sed_probability,
        )

    def strong_pair_stats(self, strong: str, target_word: str) -> CorpusPairStats:
        """The same statistics over the Strong's index rather than the surface
        one (#138), so an inflected source form still finds its rendering.

        No SED boost: phonetic similarity is a property of two *surface* strings
        (a transliterated name against its original), and a Strong's number is
        not a string anyone romanizes. `pair_stats` remains the place that
        signal comes from.
        """
        key = strong_key(strong)
        joint = self.strong_pair_counts.get((key, target_word), 0) if key else 0
        s_count = self.strong_counts.get(key, 0) if key else 0
        t_count = self.target_counts.get(target_word, 0)
        return CorpusPairStats(
            source_word=key, target_word=target_word,
            joint_count=joint, source_count=s_count, target_count=t_count,
            translation_probability=(joint / t_count) if t_count else 0.0,
            pmi=_pmi(s_count, t_count, joint, self.total_pairs),
        )


def _sed_boosted_probability(
    source_word: str, target_word: str, *, joint_count: int, target_count: int,
) -> tuple[Optional[float], Optional[float]]:
    """Mirrors ualign.py's AlignmentModel.support_probability(): romanize
    both tokens, compute Smart Edit Distance cost between the romanized
    forms, and if that cost is low enough, boost the plain co-occurrence
    probability by a term that peaks at cost 0 and vanishes at cost 1.
    Returns (None, None) — never raises — when Uroman/SED aren't available
    or either token's script can't be hinted, so a missing optional
    dependency degrades the signal rather than failing the whole request."""
    uroman = _ensure_uroman()
    if uroman is None:
        return None, None
    source_lc = _source_lang_hint(source_word)
    sed = _ensure_sed(source_lc, "")
    if sed is None:
        return None, None
    try:
        rom_source = uroman.romanize_string(source_word, lcode=source_lc or None)
        rom_target = uroman.romanize_string(target_word)
        cost, _log = sed.string_distance_cost(rom_source, rom_target, max_cost=1)
    except Exception:
        return None, None
    if cost is None or cost >= 1:
        return None, None
    boost = _SED_BOOST_SCALE * (1 - cost) * (1 - cost)
    probability = (joint_count + boost) / (target_count + boost) if (target_count + boost) else 0.0
    return cost, probability


def build_corpus_stats(
    project: TranslationCoreProject, *, include_collection: bool = True,
) -> CorpusStatsTable:
    """Scan every verse marked complete (tC's own
    tools/wordAlignment/completed/<chapter>/<verse>.json markers — the same
    signal ``alignment.complete`` writes via mark_word_alignment_completed)
    in `project`'s own book, plus — when include_collection is True — every
    already-normalized sibling book from the same multi-book collection
    (.bridge/collection.json). A sibling still marked lazy (not yet opened,
    per project_import.materialize_lazy_project) is skipped rather than
    force-materialized just to compute statistics — it has no real
    alignmentData on disk yet, and opening it is a real, visible action the
    user should trigger themselves by navigating to that book."""
    table = CorpusStatsTable()
    book_paths: list[Path] = [project.path]
    if include_collection:
        for sibling in collection_projects(project.path):
            if sibling.get("lazy"):
                continue
            sib_path = Path(str(sibling.get("path") or ""))
            if not sib_path or sib_path.resolve() == project.path.resolve():
                continue
            book_paths.append(sib_path)

    for book_path in book_paths:
        try:
            book_project = project if book_path == project.path else TranslationCoreProject(book_path)
        except Exception:
            continue
        try:
            _accumulate_book(book_project, table)
        except Exception:
            continue
        table.books_scanned.append(book_project.book_id)

    return table


def _accumulate_book(project: TranslationCoreProject, table: CorpusStatsTable) -> None:
    """Reads only chapters that actually have a completed-verse marker, and
    reads each such chapter's alignment JSON exactly once regardless of how
    many completed verses it holds (via load_alignment_chapter, not a
    per-verse load_verse_alignment call) — the real cost driver here is
    completed verses, not the project's total verse count, which matters
    for a whole-Bible-sized collection where most verses are never touched
    by manual alignment at all."""
    completed_dir = project.tc_dir / "tools" / "wordAlignment" / "completed"
    if not completed_dir.is_dir():
        return
    for chapter_dir in sorted(p for p in completed_dir.iterdir() if p.is_dir()):
        chapter = chapter_dir.name
        completed_verses = sorted(m.stem for m in chapter_dir.glob("*.json"))
        if not completed_verses:
            continue
        try:
            chapter_data = project.load_alignment_chapter(chapter)
        except Exception:
            continue
        for verse in completed_verses:
            raw = chapter_data.get(verse)
            if raw is None:
                continue
            try:
                alignment = VerseAlignment.from_dict(raw)
            except Exception:
                continue
            _accumulate_verse(alignment, table)
            table.verses_scanned += 1


def _accumulate_verse(alignment: VerseAlignment, table: CorpusStatsTable) -> None:
    for group in alignment.alignments:
        tops = group.top_words
        bottoms = group.bottom_words
        if not tops or not bottoms:
            continue
        for token in tops:
            table.source_fertility[token.word][len(bottoms)] += 1
            table.source_counts[token.word] += 1
            # #138: the parallel Strong's index. A token with no Strong's value
            # (rare, but real in hand-edited alignmentData) simply contributes
            # to the surface index only.
            key = strong_key(token.strong)
            if key:
                table.strong_counts[key] += 1
        for token in bottoms:
            table.target_fertility[token.word][len(tops)] += 1
            table.target_counts[token.word] += 1
        for top in tops:
            top_key = strong_key(top.strong)
            for bottom in bottoms:
                table.pair_counts[(top.word, bottom.word)] += 1
                table.total_pairs += 1
                if top_key:
                    table.strong_pair_counts[(top_key, bottom.word)] += 1
