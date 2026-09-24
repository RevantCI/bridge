"""The Phase 2.4 labelled examples (engine/tests/fixtures/language_qa/labelled/),
sampled from the IRV review reports by scripts/language_qa_benchmark.py
--write-labelled. Positives name the rule that finds them today (or None,
for rows no rule covers yet); maybes are contradicted rows a test must not
insist on either way. The Phase 3 rule pack runs its own examples plus these."""
import json
import unicodedata

import pytest

from tc_ai_bridge.language_qa import scan_text
from tc_ai_bridge.language_qa_benchmark import BUCKETS
from tests.support.paths import REPO_ROOT

LABELLED = REPO_ROOT / "engine" / "tests" / "fixtures" / "language_qa" / "labelled"


def examples():
    return [
        pytest.param(bucket, json.loads(line), id=f"{bucket}-{number}")
        for bucket in BUCKETS
        for number, line in enumerate((LABELLED / f"{bucket}.jsonl").read_text(encoding="utf-8").splitlines(), start=1)
    ]


def nfc(text):
    return unicodedata.normalize("NFC", text)


def test_every_bucket_has_a_fixture_file():
    assert sorted(p.stem for p in LABELLED.glob("*.jsonl")) == sorted(BUCKETS)


@pytest.mark.parametrize("bucket,example", examples())
def test_example_is_well_formed(bucket, example):
    assert example["text"] and example["origin"]
    for expected in example["expect"]:
        assert expected["category"] == bucket
        assert nfc(expected["span"]) in nfc(example["text"])
    for maybe in example.get("maybe", []):
        assert nfc(maybe["span"]) in nfc(example["text"]) and maybe["reason"]
    assert example["expect"] or example.get("maybe") or "rejectedSpan" in example


def lexicon_over(text):
    from tc_ai_bridge.language_packs.lexicon import default_lexicon, lexicon_findings
    from tc_ai_bridge.language_qa import RULE_VERSION, rule_fields, suggestion, word_occurrences
    counts, first_seen = {}, {}
    for word, start, end in word_occurrences(text):
        counts[word] = counts.get(word, 0) + 1
        first_seen.setdefault(word, ("1", "1", start, end, text[start:end], "h"))
    return lexicon_findings("x", counts, first_seen, default_lexicon(), rule_fields=rule_fields,
                            suggestion=suggestion, rule_version=RULE_VERSION)


@pytest.mark.parametrize("bucket,example", examples())
def test_a_positive_credited_to_a_rule_is_still_found_by_it(bucket, example):
    for expected in example["expect"]:
        if not expected["ruleId"]:
            continue  # no current rule covers it; Phase 3+ will
        if expected["ruleId"].endswith("/tamil.wordlist-variant"):
            continue  # a book-wide audit, not a per-verse rule; the benchmark measures it
        if "/lexicon." in expected["ruleId"]:
            # The lexicon rules run over a book's word counts; over this verse
            # alone every word is "rare in the book", and a known misspelling
            # needs no book at all, so the verse is a book of one.
            findings = lexicon_over(example["text"])
        else:
            findings = scan_text(example["text"], book="x", chapter="1", verse="1", tamil=True)["findings"]
        # ruleId, not the `rule` alias: migrated pack rules keep their legacy name there.
        spans = [nfc(f["originalText"]) for f in findings if f["ruleId"] == expected["ruleId"]]
        span = nfc(expected["span"])
        assert any(s in span or span in s for s in spans), (expected, spans)
