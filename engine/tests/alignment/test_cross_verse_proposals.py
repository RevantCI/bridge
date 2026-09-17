"""
Tests for `cross_verse_proposals.propose` (#138): ranking where a source word
with no counterpart in its own verse was probably realized.

`propose` is a pure function over a gap map and a `CorpusStatsTable`, so these
build the table by hand rather than standing up a fixture project with completed
alignments -- the scoring is what is under test, not the corpus scan
(`test_alignment_statistics.py` covers that).

These tests assert *relationships and behaviour* -- that corpus evidence
proposes, that proximity alone cannot, that a tie is reported as ambiguous --
and deliberately not the specific confidence numbers, which are uncalibrated
placeholders (see the module docstring). A test that pinned 0.65 would turn a
placeholder into a contract.
"""
import pytest

from tc_ai_bridge.alignment_statistics import CorpusStatsTable, strong_key
from tc_ai_bridge.cross_verse_proposals import ProposalPolicy, propose

VERSE_ORDER = ["1", "2", "3", "4", "5"]


def _source(token_id: str, word: str, strong: str = "") -> dict:
    return {
        "id": token_id, "word": word, "strong": strong, "lemma": "",
        "signature": f"{word}␟1␟1",
    }


def _target(token_id: str, word: str) -> dict:
    return {"id": token_id, "word": word, "signature": f"{word}␟1␟1"}


def _table(
    *, strong_pairs: dict | None = None, surface_pairs: dict | None = None,
    target_counts: dict | None = None, verses_scanned: int = 12,
) -> CorpusStatsTable:
    """A table in which `target_counts` defaults to the joint count, i.e. the
    target word has only ever been aligned to this one source -- the clean,
    unambiguous precedent."""
    table = CorpusStatsTable()
    table.verses_scanned = verses_scanned
    table.books_scanned = ["rut"]
    for (strong, target_word), count in (strong_pairs or {}).items():
        key = strong_key(strong)
        table.strong_pair_counts[(key, target_word)] = count
        table.strong_counts[key] += count
        table.total_pairs += count
    for (source_word, target_word), count in (surface_pairs or {}).items():
        table.pair_counts[(source_word, target_word)] = count
        table.source_counts[source_word] += count
        table.total_pairs += count
    counted = dict(target_counts or {})
    for (_, target_word), count in list((strong_pairs or {}).items()):
        counted.setdefault(target_word, count)
    for (_, target_word), count in list((surface_pairs or {}).items()):
        counted.setdefault(target_word, count)
    for word, count in counted.items():
        table.target_counts[word] = count
    return table


def _gaps(**by_verse) -> dict:
    return {
        verse: {"sourceGaps": sources, "targetGaps": targets}
        for verse, (sources, targets) in by_verse.items()
    }


def _propose(gaps, table, policy=None):
    return propose(
        gaps, table, chapter="1", verse_order=VERSE_ORDER, policy=policy,
    )


def test_a_corpus_precedent_proposes_the_word_in_the_other_verse():
    """The core case: verse 2's source word has no counterpart of its own, and
    the team's completed alignments say this is how they render that lemma."""
    table = _table(strong_pairs={("G2316", "கடவுள்"): 10})
    gaps = _gaps(
        **{"2": ([_source("H001", "θεοῦ", "G2316")], []),
           "3": ([], [_target("T004", "கடவுள்")])},
    )

    result = _propose(gaps, table)

    assert len(result["proposals"]) == 1
    proposal = result["proposals"][0]
    assert proposal["status"] == "PROPOSED"
    assert proposal["source"]["verse"] == "2"
    assert proposal["source"]["topId"] == "H001"
    assert proposal["target"]["verse"] == "3"
    assert proposal["target"]["word"] == "கடவுள்"
    assert proposal["confidence"] > 0


def test_the_strongs_index_finds_what_the_surface_index_misses():
    """An inflected source form is its own key in the surface index, so a
    rendering seen ten times can read as ten singletons. The Strong's index
    pools them -- this is the whole reason it was added."""
    # The corpus has only ever seen the nominative; the gap is the genitive.
    table = _table(
        strong_pairs={("G2316", "கடவுள்"): 10},
        surface_pairs={("θεός", "கடவுள்"): 10},
    )
    gaps = _gaps(
        **{"2": ([_source("H001", "θεοῦ", "G2316")], []),
           "3": ([], [_target("T004", "கடவுள்")])},
    )

    result = _propose(gaps, table)

    assert len(result["proposals"]) == 1
    evidence = {item["kind"]: item for item in result["proposals"][0]["evidence"]}
    assert evidence["STRONGS_PRECEDENT"]["rawScore"] > 0
    assert evidence["STRONGS_PRECEDENT"]["jointCount"] == 10
    # The surface form θεοῦ was never seen, so that component contributes nothing.
    assert evidence["SURFACE_PRECEDENT"]["rawScore"] == 0
    assert evidence["SURFACE_PRECEDENT"]["jointCount"] == 0


def test_proximity_alone_never_proposes_anything():
    """Verse distance is a tie-breaker, not evidence. A neighbouring verse full
    of unaligned words must not generate a proposal for every pairing."""
    table = _table(strong_pairs={("G9999", "வேறு"): 5})
    gaps = _gaps(
        **{"2": ([_source("H001", "θεοῦ", "G2316")], []),
           "3": ([], [_target("T004", "கடவுள்"), _target("T005", "ஆண்டவர்")])},
    )

    result = _propose(gaps, table)

    assert result["proposals"] == []


def test_same_verse_candidates_are_never_proposed():
    """That is alignment.realign, and the link store refuses both ends in one
    verse anyway (#117)."""
    table = _table(strong_pairs={("G2316", "கடவுள்"): 10})
    gaps = _gaps(
        **{"2": ([_source("H001", "θεοῦ", "G2316")], [_target("T004", "கடவுள்")])},
    )

    result = _propose(gaps, table)

    assert result["proposals"] == []


def test_a_tie_is_reported_ambiguous_rather_than_guessed():
    """Two identical target words in different verses are equally good
    candidates, and picking one would be a guess dressed as an answer."""
    table = _table(strong_pairs={("G2316", "கடவுள்"): 10})
    gaps = _gaps(
        **{"2": ([_source("H001", "θεοῦ", "G2316")], []),
           "3": ([], [_target("T004", "கடவுள்")]),
           "4": ([], [_target("T009", "கடவுள்")])},
    )

    result = _propose(gaps, table)

    assert len(result["proposals"]) == 1
    proposal = result["proposals"][0]
    # Verse 3 is nearer so it sorts first, but nearness is not evidence: the two
    # candidates are identical on every substantive component, so the margin the
    # status is decided on is zero.
    assert proposal["status"] == "AMBIGUOUS"
    assert proposal["margin"] == 0
    assert proposal["margin"] < ProposalPolicy().ambiguity_margin
    assert len(proposal["alternatives"]) == 1


def test_two_sources_wanting_the_same_word_are_both_ambiguous():
    """A target word can realize only one source token. Reported, not resolved."""
    table = _table(strong_pairs={("G2316", "கடவுள்"): 10})
    gaps = _gaps(
        **{"2": ([_source("H001", "θεοῦ", "G2316"), _source("H002", "θεῷ", "G2316")], []),
           "3": ([], [_target("T004", "கடவுள்")])},
    )

    result = _propose(gaps, table)

    assert len(result["proposals"]) == 2
    assert all(p["contested"] is True for p in result["proposals"])
    assert all(p["status"] == "AMBIGUOUS" for p in result["proposals"])


def test_a_clear_winner_is_not_contested_and_keeps_its_margin():
    table = _table(
        strong_pairs={("G2316", "கடவுள்"): 10},
        target_counts={"கடவுள்": 10, "வேறு": 40},
    )
    gaps = _gaps(
        **{"2": ([_source("H001", "θεοῦ", "G2316")], []),
           "3": ([], [_target("T004", "கடவுள்"), _target("T005", "வேறு")])},
    )

    result = _propose(gaps, table)

    proposal = result["proposals"][0]
    assert proposal["status"] == "PROPOSED"
    assert proposal["contested"] is False
    assert proposal["target"]["word"] == "கடவுள்"
    assert proposal["margin"] >= ProposalPolicy().ambiguity_margin


def test_no_completed_alignments_says_so_instead_of_returning_nothing():
    """The honest limit of an offline approach: the table is learned from
    completed verses, so a book with none teaches it nothing. An empty list
    would read as "no suggestions found", which is a different claim."""
    table = _table(strong_pairs={("G2316", "கடவுள்"): 10}, verses_scanned=0)
    gaps = _gaps(
        **{"2": ([_source("H001", "θεοῦ", "G2316")], []),
           "3": ([], [_target("T004", "கடவுள்")])},
    )

    result = _propose(gaps, table)

    assert result["proposals"] == []
    assert result["unavailable"]["reason"] == "no-completed-alignments"
    assert "complete" in result["unavailable"]["message"].lower()


def test_verse_bridges_are_measured_by_position_not_parsed_as_numbers():
    """"3-4" and "3a" are real input and are not integers (CLAUDE.md gotcha 12)."""
    table = _table(strong_pairs={("G2316", "கடவுள்"): 10})
    gaps = _gaps(
        **{"2": ([_source("H001", "θεοῦ", "G2316")], []),
           "3-4": ([], [_target("T004", "கடவுள்")])},
    )

    result = propose(
        gaps, table, chapter="1", verse_order=["1", "2", "3-4", "5"], policy=None,
    )

    assert len(result["proposals"]) == 1
    assert result["proposals"][0]["target"]["verse"] == "3-4"


def test_every_component_is_reported_with_its_weight():
    """Raw score and weighted score are kept apart so a real calibration can
    land later without rewriting stored proposals."""
    table = _table(strong_pairs={("G2316", "கடவுள்"): 10})
    gaps = _gaps(
        **{"2": ([_source("H001", "θεοῦ", "G2316")], []),
           "3": ([], [_target("T004", "கடவுள்")])},
    )

    result = _propose(gaps, table)

    evidence = result["proposals"][0]["evidence"]
    assert [item["kind"] for item in evidence] == [
        kind for kind, _ in ProposalPolicy().weights
    ]
    for item in evidence:
        assert item["weightedScore"] == pytest.approx(item["rawScore"] * item["weight"], abs=1e-4)
    assert result["calibrationVersion"] == "cross-verse-uncalibrated-v1"


def test_the_corpus_the_proposals_came_from_is_reported():
    table = _table(strong_pairs={("G2316", "கடவுள்"): 10})
    result = _propose(_gaps(**{"2": ([], [])}), table)
    assert result["corpus"]["versesScanned"] == 12
    assert result["corpus"]["booksScanned"] == ["rut"]
