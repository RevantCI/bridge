"""
Tests for NamesAdapter, which wraps two real dependencies:
  - the real PyPI "uroman" package (romanization)
  - the vendored Greek Room Smart Edit Distance module
    (engine/vendor/greekroom-smart-edit-distance/, see NOTICE.md there)

Both are real dependencies, not mocked — see
docs/DEVELOPER_HANDOFF.md's Phase 5 research breadcrumb for why: unlike
Wildebeest, uroman has no known installability problem on any supported
Python version, so there's no mock-fallback path to test around.
"""
from __future__ import annotations

import time

from greek_room_engine.adapters.names_adapter import NamesAdapter
from greek_room_engine.models.finding import FindingCategory, Severity


def test_adapter_reports_real_engine_available():
    adapter = NamesAdapter()
    assert adapter.is_available() is True
    assert adapter.using_real_engine() is True
    assert "uroman" in adapter.version()


def test_flags_a_real_typo_against_the_majority_spelling():
    adapter = NamesAdapter()
    token_occurrences = {
        "Titus": [("1", "1"), ("1", "4"), ("3", "12")],
        "Tituss": [("2", "7")],  # a plausible one-off typo
    }
    findings = adapter.check_book(
        project_id="p1", book_id="TIT", lang_code="eng",
        token_occurrences=token_occurrences,
    )
    assert len(findings) == 1
    finding = findings[0]
    assert finding.original_text == "Tituss"
    assert finding.suggested_replacement == "Titus"
    assert finding.engine == "names"
    assert finding.check_type == "names.spelling_similarity"
    assert finding.category == FindingCategory.SPELLING
    # Anchored at the minority spelling's own occurrence, not a placeholder.
    assert (finding.chapter, finding.verse) == (2, 7)
    assert 0.0 < finding.confidence <= 1.0


def test_flags_cross_script_phonetic_variants_via_uroman_and_sed():
    """The concrete scenario the vendored module's own docstring names:
    "Muhammad" vs "Mohamed" should register as suspiciously close, matching
    the real cost (0.22) measured directly during the Phase 5 investigation
    — not a synthetic/assumed number."""
    adapter = NamesAdapter()
    token_occurrences = {
        "Muhammad": [("1", "1")],
        "Mohamed": [("1", "2")],
    }
    findings = adapter.check_book(
        project_id="p1", book_id="TST", lang_code="eng",
        token_occurrences=token_occurrences,
    )
    assert len(findings) == 1
    cost_evidence = findings[0].evidence[-1]
    assert cost_evidence.label == "Romanized similarity cost"
    assert cost_evidence.value.startswith("0.22")


def test_does_not_flag_an_ordinary_plural_pair():
    """Real false-positive class found during development: "church" and
    "churches" are both correctly spelled, unrelated to name consistency —
    the general cost-rules table still scores them at 0.70 (measured), so
    the threshold must stay below that, not just below the vendored
    module's own "Jim"/"Kim" = 1.0 baseline."""
    adapter = NamesAdapter()
    token_occurrences = {
        "church": [("1", "5"), ("1", "6")],
        "churches": [("1", "7")],
    }
    findings = adapter.check_book(
        project_id="p1", book_id="TST", lang_code="eng",
        token_occurrences=token_occurrences,
    )
    assert findings == []


def test_does_not_flag_the_vendored_modules_own_meaningfully_different_example():
    adapter = NamesAdapter()
    token_occurrences = {
        "Jim": [("1", "1")],
        "Kim": [("1", "2")],
    }
    findings = adapter.check_book(
        project_id="p1", book_id="TST", lang_code="eng",
        token_occurrences=token_occurrences,
    )
    assert findings == []


def test_skips_tokens_shorter_than_the_minimum_length():
    adapter = NamesAdapter()
    token_occurrences = {
        "he": [("1", "1")],
        "hi": [("1", "2")],
    }
    findings = adapter.check_book(
        project_id="p1", book_id="TST", lang_code="eng",
        token_occurrences=token_occurrences,
    )
    assert findings == []


def test_identical_spellings_produce_no_finding():
    adapter = NamesAdapter()
    token_occurrences = {"Titus": [("1", "1"), ("1", "4"), ("2", "7")]}
    findings = adapter.check_book(
        project_id="p1", book_id="TIT", lang_code="eng",
        token_occurrences=token_occurrences,
    )
    assert findings == []


def test_large_vocabulary_completes_quickly_via_bigram_blocking():
    """Regression guard for a real measured performance bug: plain
    length-bucket pruning alone took 133 SECONDS for ~3000 distinct word
    types (timed directly, not estimated) — far too slow for a whole-book
    background check. Bigram-index blocking (see NamesAdapter._candidate_pairs)
    brought the same scenario under a few seconds. This uses a smaller
    vocabulary than that real benchmark so the test suite itself stays
    fast, with a generous bound well under the fixed bug's behavior."""
    import random
    rng = random.Random(1234)
    letters = "abcdefghijklmnopqrstuvwxyz"
    vocab: dict[str, list[tuple[str, str]]] = {}
    for _ in range(800):
        word = "".join(rng.choice(letters) for _ in range(rng.randint(3, 12)))
        vocab.setdefault(word, []).append((str(rng.randint(1, 30)), str(rng.randint(1, 30))))

    adapter = NamesAdapter()
    start = time.time()
    adapter.check_book(project_id="p", book_id="TST", lang_code="eng", token_occurrences=vocab)
    elapsed = time.time() - start
    assert elapsed < 30.0, f"whole-book comparison took {elapsed:.1f}s — bigram blocking regression?"


def test_severity_is_lower_for_a_more_marginal_match():
    adapter = NamesAdapter()
    close = adapter.check_book(
        project_id="p", book_id="TST", lang_code="eng",
        token_occurrences={"Titus": [("1", "1")], "Tituss": [("1", "2")]},
    )[0]
    assert close.severity == Severity.MEDIUM
