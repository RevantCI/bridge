"""Proposed cross-verse links: where a source word with no counterpart in its
own verse was probably realized, because the translation paraphrased across the
verse boundary (#138).

**Why this does not simply ask Stage 6B.** Stage 6B is the passage-aware
location engine and it already marks a relationship CROSS_VERSE when the winning
target span sits in another verse -- but it cannot find one unaided in the
shipped app. Its weights are SEMANTIC_SIMILARITY 0.42 + LEXICAL 0.38 + CONCEPT
0.15 + MORPHOLOGY 0.12 + STRUCTURAL_PROXIMITY 0.05 + EXACT_SPAN 0.01, against
`LocationSearchPolicy.located_minimum` of 0.36. `SemanticEmbeddingProvider.
available` is False in the shipped app, so SEMANTIC_SIMILARITY is always 0; and
`_lexical_score` compares an NFC Greek or Hebrew string against a target-language
one, so for any real translation pair it is 0 too. The most the remaining
components can sum to is 0.33 -- below the threshold. The two components that
*can* carry a relationship over it, HUMAN_PRECEDENT and WORD_ALIGNMENT, are both
weight 0.65 and both mean "a human already said so" (#119). So for a token that
is still a gap, and therefore has no human judgement attached, Stage 6B has
nothing to contribute; wiring it in here would look like evidence and be
tautology. It is left out deliberately, not overlooked. If the embedding
provider ever ships, that is the moment to add a STAGE6B_AGREEMENT component.

**What is used instead.** The project's own completed alignments, via
`alignment_statistics.CorpusStatsTable` -- co-occurrence counts, translation
probability, PMI, and the Smart-Edit-Distance phonetic boost. That table is the
only offline signal that is genuinely bilingual: it encodes "this team renders
this source word as that target word", which is exactly the relation a
paraphrase redistributes across verses.

**Nothing here writes anything.** These are proposals; a link is written only
through `alignment.crossVerse.link` (#117), the one writer.

**Nothing *this module* produces is ever applied without a click**, at any
confidence. That is deliberate and unchanged: a single uncalibrated score
(see below) is not a thing to write on.

What did change, in #146: `cross_verse_ai_proposals.py` may mark a proposal
`autoLinkable`, and the caller may then link it without a per-link click. It can
only do so where the model's pick and *this* module's top candidate are the same
uncontested pair -- two methods, scoring by unrelated evidence, reaching the same
answer. This module is one half of that gate and is unaware of the other; it
neither knows nor cares whether a model agreed. The maintainer took that decision
on 2026-09-18, reversing the position recorded here and in #23; the earlier note
that `alignment_reliability.AUTO_LINK_THRESHOLD`'s pattern would never be revived
no longer holds, and the difference worth keeping is that the gate is agreement
between methods rather than a threshold on one number.

**The numbers below are uncalibrated.** Every weight and cut-off is a starting
placeholder, in the same sense as `MEANING_CALIBRATION_VERSION`'s
"meaning-uncalibrated-v1" and `qa_audit.severity_for()`'s 0.85/0.9. Raw score and
each component are kept separately in the output so a real calibration can land
later. Do not build behaviour that treats these as meaningful, and do not tune
them to make a test pass.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .alignment_statistics import CorpusStatsTable

#: Bump when a component, weight or cut-off changes, so a stored proposal is
#: never confused with one produced by different arithmetic.
PROPOSAL_CALIBRATION_VERSION = "cross-verse-uncalibrated-v1"

STRONGS_PRECEDENT = "STRONGS_PRECEDENT"
SURFACE_PRECEDENT = "SURFACE_PRECEDENT"
PHONETIC = "PHONETIC"
PROXIMITY = "PROXIMITY"


@dataclass(frozen=True)
class ProposalPolicy:
    """Placeholders, every one of them -- see the module docstring.

    `propose_minimum` sits above what PROXIMITY alone can reach (0.10), so verse
    distance can never propose anything by itself. It sits just below PHONETIC +
    PROXIMITY at an adjacent verse (0.35), which is the transliterated
    proper-noun case -- a name with no co-occurrence history yet, whose romanized
    forms all but match. That case is meant to surface.

    `ambiguity_margin` is applied to the *substantive* score, which excludes
    PROXIMITY, so that two candidates separated only by verse distance come out
    AMBIGUOUS rather than having the nearer one promoted. Distance orders the
    list; it never settles it.
    """
    propose_minimum: float = 0.30
    ambiguity_margin: float = 0.05
    max_candidates_per_source: int = 3
    weights: tuple[tuple[str, float], ...] = (
        (STRONGS_PRECEDENT, 0.55),
        (SURFACE_PRECEDENT, 0.45),
        (PHONETIC, 0.25),
        (PROXIMITY, 0.10),
    )
    version: str = PROPOSAL_CALIBRATION_VERSION


def _proximity(verse_order: list[str], left: str, right: str) -> float:
    """1.0 for neighbouring verses, decaying with distance.

    Distance is measured in positions within the chapter's own verse list, never
    by parsing verse numbers: bridges ("3-4") and lettered segments ("3a") are
    real input and are not integers (CLAUDE.md gotcha 12).
    """
    try:
        distance = abs(verse_order.index(left) - verse_order.index(right))
    except ValueError:
        return 0.0
    return 1.0 / distance if distance else 0.0


def _phonetic(stats: Any) -> float:
    """Romanized Smart-Edit-Distance cost, as a 0..1 similarity.

    `sed_cost` is None whenever Uroman or the SED vendor tree is unavailable, or
    either token's script cannot be hinted -- an optional dependency, so its
    absence costs this one component rather than failing the proposal.
    """
    cost = getattr(stats, "sed_cost", None)
    if cost is None:
        return 0.0
    return max(0.0, min(1.0, 1.0 - float(cost)))


def _score(
    source: dict[str, Any], target: dict[str, Any], *,
    table: CorpusStatsTable, verse_order: list[str],
    source_verse: str, target_verse: str, policy: ProposalPolicy,
) -> tuple[float, list[dict[str, Any]], float]:
    surface = table.pair_stats(source["word"], target["word"])
    strongs = table.strong_pair_stats(str(source.get("strong") or ""), target["word"])
    values = {
        STRONGS_PRECEDENT: strongs.translation_probability,
        SURFACE_PRECEDENT: surface.translation_probability,
        PHONETIC: _phonetic(surface),
        PROXIMITY: _proximity(verse_order, source_verse, target_verse),
    }
    evidence: list[dict[str, Any]] = []
    raw = 0.0
    for kind, weight in policy.weights:
        value = max(0.0, min(1.0, float(values.get(kind, 0.0))))
        raw += value * weight
        entry = {
            "kind": kind, "rawScore": round(value, 4), "weight": weight,
            "weightedScore": round(value * weight, 4),
        }
        if kind == STRONGS_PRECEDENT:
            entry["jointCount"] = strongs.joint_count
            entry["sourceCount"] = strongs.source_count
            entry["strongKey"] = strongs.source_word
        elif kind == SURFACE_PRECEDENT:
            entry["jointCount"] = surface.joint_count
            entry["sourceCount"] = surface.source_count
        elif kind == PHONETIC and surface.sed_cost is not None:
            entry["sedCost"] = round(surface.sed_cost, 4)
        evidence.append(entry)
    # The substantive subtotal excludes PROXIMITY. Two candidates that differ
    # only in how near they sit are not separated by any *evidence*, and the
    # margin below is measured on this rather than on the total -- otherwise
    # verse distance, which the policy calls a tie-breaker, would silently
    # promote one of two indistinguishable candidates to a confident proposal.
    substantive = sum(
        item["weightedScore"] for item in evidence if item["kind"] != PROXIMITY
    )
    return min(1.0, raw), evidence, substantive


def propose(
    gaps_by_verse: dict[str, dict[str, Any]],
    table: CorpusStatsTable,
    *,
    chapter: str,
    verse_order: Iterable[str],
    policy: ProposalPolicy | None = None,
) -> dict[str, Any]:
    """Rank, for each unmatched source token, the unaccounted target words of the
    *other* verses in range that might be realizing it.

    A pure function over already-gathered data -- no project, no I/O -- so the
    scoring can be tested against a hand-built table rather than a fixture
    project with completed alignments.

    Same-verse candidates are never proposed: that is `alignment.realign`, and
    the cross-verse link store refuses both ends in one verse anyway (#117).
    """
    policy = policy or ProposalPolicy()
    order = list(verse_order)

    # Cold start, stated rather than papered over. The table is built from
    # COMPLETED verses only (`build_corpus_stats`), so a book nobody has
    # finished aligning yet teaches it nothing, and every score would be
    # PROXIMITY alone -- which by construction proposes nothing. Saying so is
    # more useful than returning an empty list that looks like "no gaps".
    if table.verses_scanned == 0:
        return {
            "chapter": chapter, "proposals": [], "calibrationVersion": policy.version,
            "unavailable": {
                "reason": "no-completed-alignments",
                "message": (
                    "Cross-verse suggestions are learned from this project's own completed "
                    "alignments, and no verse in this book (or its collection) is marked "
                    "complete yet. Align and complete a few verses, then try again."
                ),
            },
        }

    ranked: list[dict[str, Any]] = []
    for source_verse, entry in gaps_by_verse.items():
        for source in entry.get("sourceGaps", ()):
            candidates: list[dict[str, Any]] = []
            for target_verse, other in gaps_by_verse.items():
                if target_verse == source_verse:
                    continue
                for target in other.get("targetGaps", ()):
                    score, evidence, substantive = _score(
                        source, target, table=table, verse_order=order,
                        source_verse=source_verse, target_verse=target_verse, policy=policy,
                    )
                    if score < policy.propose_minimum:
                        continue
                    candidates.append({
                        "confidence": round(score, 4),
                        "_substantive": substantive,
                        "source": {
                            "chapter": chapter, "verse": source_verse, "topId": source["id"],
                            "word": source["word"], "signature": source["signature"],
                            "strong": source.get("strong", ""), "lemma": source.get("lemma", ""),
                        },
                        "target": {
                            "chapter": chapter, "verse": target_verse, "bottomId": target["id"],
                            "word": target["word"], "signature": target["signature"],
                        },
                        "evidence": evidence,
                    })
            if not candidates:
                continue
            candidates.sort(key=lambda item: (-item["confidence"], item["target"]["verse"], item["target"]["bottomId"]))
            best = candidates[0]
            runner_up = candidates[1]["_substantive"] if len(candidates) > 1 else 0.0
            margin = best["_substantive"] - runner_up
            best["status"] = "AMBIGUOUS" if margin < policy.ambiguity_margin else "PROPOSED"
            best["margin"] = round(margin, 4)
            best["alternatives"] = [
                {key: value for key, value in item.items() if key != "_substantive"}
                for item in candidates[1:policy.max_candidates_per_source]
            ]
            best.pop("_substantive", None)
            ranked.append(best)

    # A target word can realize only one source token, so two source tokens whose
    # best candidate is the same word are competing and neither is settled. This
    # is reported rather than resolved: picking a winner here would be a guess
    # dressed as an answer, and the reviewer can see both in one glance.
    contested: dict[tuple[str, str], int] = {}
    for proposal in ranked:
        key = (proposal["target"]["verse"], proposal["target"]["bottomId"])
        contested[key] = contested.get(key, 0) + 1
    for proposal in ranked:
        key = (proposal["target"]["verse"], proposal["target"]["bottomId"])
        proposal["contested"] = contested[key] > 1
        if proposal["contested"]:
            proposal["status"] = "AMBIGUOUS"

    ranked.sort(key=lambda item: (-item["confidence"], item["source"]["verse"], item["source"]["topId"]))
    return {
        "chapter": chapter, "proposals": ranked,
        "calibrationVersion": policy.version,
        "corpus": {
            "versesScanned": table.verses_scanned,
            "booksScanned": list(table.books_scanned),
            "totalPairs": table.total_pairs,
        },
    }
