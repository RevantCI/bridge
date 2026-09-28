"""The labelled examples (engine/tests/fixtures/language_qa/labelled/).

Two sources, one format:
- Phase 2.4, sampled from the IRV AI review reports by
  scripts/language_qa_benchmark.py --write-labelled. Positives name the rule
  that finds them today (or None, for rows no rule covers yet); maybes are
  contradicted rows a test must not insist on either way.
- The 2026-09-28 human review (benchmark/human/2026-09-28/labelled/, appended;
  origin "... (human review 2026...)"). `expect` is a finding the reviewer
  confirmed, with the reviewer's fix; `negative` is a confirmed false alarm,
  which its rule must not raise; `maybe` is evidence of another defect (a
  split word), which no sandhi rule may claim.

When a human-review example fails, the pack disagrees with the reviewer:
fix the pack, never the fixture."""
import json
import re
import unicodedata

import pytest

from tc_ai_bridge.language_qa import scan_text
from tc_ai_bridge.language_qa_benchmark import BUCKETS, CATEGORY_BUCKETS
from tests.support.paths import REPO_ROOT

LABELLED = REPO_ROOT / "engine" / "tests" / "fixtures" / "language_qa" / "labelled"


# (test, example id) the pack does not yet satisfy: the reviewer disagrees with
# it, and the pack changes that follow the review fix them. Strict, so each
# entry must start passing when its fix lands, and is then deleted here.
PENDING_PACK_CHANGES: set[tuple[str, str]] = {
    ("negative", "sandhi-74"), ("negative", "sandhi-78"), ("negative", "sandhi-81"),
    ("negative", "sandhi-82"), ("negative", "sandhi-83"), ("negative", "sandhi-87"),
    ("negative", "sandhi-88"), ("negative", "sandhi-89"), ("negative", "sandhi-90"),
    ("negative", "sandhi-91"), ("negative", "sandhi-93"), ("negative", "sandhi-97"),
    ("negative", "sandhi-98"), ("negative", "sandhi-111"), ("negative", "sandhi-113"),
    ("negative", "sandhi-136"), ("negative", "sandhi-141"), ("negative", "sandhi-166"),
    ("negative", "sandhi-180"), ("negative", "sandhi-221"), ("negative", "sandhi-222"),
    ("negative", "sandhi-223"), ("negative", "sandhi-224"), ("negative", "sandhi-225"),
    ("negative", "sandhi-226"), ("negative", "sandhi-227"), ("negative", "sandhi-228"),
    ("negative", "sandhi-229"), ("negative", "sandhi-230"), ("negative", "sandhi-231"),
    ("negative", "sandhi-232"), ("negative", "sandhi-233"), ("negative", "sandhi-234"),
    ("negative", "sandhi-235"), ("negative", "sandhi-236"), ("negative", "sandhi-237"),
    ("negative", "sandhi-238"), ("negative", "sandhi-239"), ("negative", "sandhi-240"),
    ("negative", "typo-94"), ("negative", "typo-95"), ("negative", "typo-96"), ("negative", "typo-97"),
    ("negative", "typo-98"), ("negative", "typo-99"), ("negative", "typo-100"), ("negative", "typo-101"),
    ("negative", "typo-102"), ("negative", "typo-103"), ("negative", "typo-104"), ("negative", "typo-105"),
    ("negative", "typo-106"), ("negative", "typo-107"), ("negative", "typo-108"), ("negative", "typo-109"),
    ("negative", "typo-110"), ("negative", "typo-111"), ("negative", "typo-112"), ("negative", "typo-113"),
    ("negative", "typo-114"), ("negative", "usfm-42"), ("negative", "usfm-43"), ("negative", "usfm-44"),
    ("negative", "usfm-45"), ("negative", "usfm-46"), ("negative", "usfm-47"), ("negative", "usfm-48"),
    ("negative", "usfm-49"), ("negative", "usfm-50"), ("negative", "usfm-51"), ("negative", "usfm-52"),
    ("negative", "usfm-53"), ("negative", "usfm-54"), ("negative", "usfm-55"), ("negative", "usfm-56"),
    ("positive", "sandhi-184"), ("positive", "sandhi-185"), ("positive", "sandhi-186"),
    ("positive", "sandhi-187"), ("positive", "sandhi-188"), ("positive", "sandhi-189"),
    ("positive", "sandhi-190"), ("positive", "sandhi-191"), ("positive", "sandhi-192"),
    ("positive", "sandhi-193"), ("positive", "sandhi-194"), ("positive", "sandhi-195"),
    ("positive", "sandhi-196"), ("positive", "sandhi-197"), ("positive", "sandhi-198"),
    ("positive", "sandhi-199"), ("positive", "sandhi-200"), ("positive", "sandhi-201"),
    ("positive", "sandhi-202"), ("positive", "sandhi-203"), ("positive", "sandhi-204"),
    ("positive", "sandhi-205"), ("positive", "sandhi-206"), ("positive", "sandhi-207"),
    ("positive", "sandhi-208"), ("positive", "sandhi-209"), ("positive", "sandhi-211"),
    ("positive", "sandhi-212"), ("positive", "sandhi-213"), ("positive", "sandhi-214"),
    ("positive", "sandhi-215"), ("positive", "sandhi-216"), ("positive", "sandhi-217"),
    ("positive", "sandhi-218"), ("positive", "sandhi-219"), ("positive", "sandhi-220"),
}


def examples(test: str = ""):
    params = []
    for bucket in BUCKETS:
        lines = (LABELLED / f"{bucket}.jsonl").read_text(encoding="utf-8").splitlines()
        for number, line in enumerate(lines, start=1):
            ident = f"{bucket}-{number}"
            marks = [pytest.mark.xfail(strict=True, reason="the pack disagrees with the 2026-09-28 reviewer")] \
                if (test, ident) in PENDING_PACK_CHANGES else []
            params.append(pytest.param(bucket, json.loads(line), id=ident, marks=marks))
    return params


def squeezed(text):
    # The reviewer writes a pair across a poetry line with a space; the verse
    # has a line break there. Any whitespace run anchors as one space.
    return re.sub(r"\s+", " ", nfc(text))


def human(example):
    return "(human review 2026" in example["origin"]


def nfc(text):
    return unicodedata.normalize("NFC", text)


def test_every_bucket_has_a_fixture_file():
    assert sorted(p.stem for p in LABELLED.glob("*.jsonl")) == sorted(BUCKETS)


@pytest.mark.parametrize("bucket,example", examples())
def test_example_is_well_formed(bucket, example):
    assert example["text"] and example["origin"]
    for expected in example["expect"]:
        # The bucket itself, or a category the benchmark scores against it (a
        # human-review spacing finding sits in the punctuation bucket).
        assert expected["category"] == bucket or bucket in CATEGORY_BUCKETS.get(expected["category"], ())
        assert squeezed(expected["span"]) in squeezed(example["text"])
    for maybe in example.get("maybe", []):
        assert squeezed(maybe["span"]) in squeezed(example["text"]) and maybe["reason"]
    for negative in example.get("negative", []):
        assert nfc(negative["span"]) in nfc(example["text"]) and negative["ruleId"] and negative["reason"]
    assert example["expect"] or example.get("maybe") or example.get("negative") or "rejectedSpan" in example


def lexicon_over(text):
    from tc_ai_bridge.language_packs.lexicon import default_lexicon, lexicon_findings
    from tc_ai_bridge.language_qa import RULE_VERSION, rule_fields, suggestion, word_occurrences
    counts, first_seen = {}, {}
    for word, start, end in word_occurrences(text):
        counts[word] = counts.get(word, 0) + 1
        first_seen.setdefault(word, ("1", "1", start, end, text[start:end], "h"))
    return lexicon_findings("x", counts, first_seen, default_lexicon(), rule_fields=rule_fields,
                            suggestion=suggestion, rule_version=RULE_VERSION)


def findings_of(example, rule_id):
    if "/lexicon." in rule_id:
        # The lexicon rules run over a book's word counts; over this verse
        # alone every word is "rare in the book", and a known misspelling
        # needs no book at all, so the verse is a book of one.
        findings = lexicon_over(example["text"])
    else:
        findings = scan_text(example["text"], book="x", chapter="1", verse="1", tamil=True)["findings"]
    # ruleId, not the `rule` alias: migrated pack rules keep their legacy name there.
    return [f for f in findings if f["ruleId"] == rule_id]


def overlaps(a, b):
    a, b = squeezed(a), squeezed(b)
    return a in b or b in a


@pytest.mark.parametrize("bucket,example", examples("negative"))
def test_a_confirmed_false_alarm_is_not_raised_by_its_rule(bucket, example):
    for negative in example.get("negative", []):
        raised = [f for f in findings_of(example, negative["ruleId"]) if overlaps(f["originalText"], negative["span"])]
        # The reviewer's reason for integrity.space-before-note-end is "USFM
        # formatting, not a text error": the rule stays, as a low-severity
        # markup item, and must never present itself as a text error.
        raised = [f for f in raised if not (f["category"] == "usfm" and f["severity"] == "low")]
        assert not raised, (negative, [(f["originalText"], f["category"]) for f in raised])


@pytest.mark.parametrize("bucket,example", examples("maybe"))
def test_a_reviewed_other_defect_is_not_claimed_by_a_sandhi_rule(bucket, example):
    """The reviewer's "maybe" items are split words (கை கோலில் -> கைக்கோலில்,
    சு வரை -> சுவரை), not a missing வல்லினம். The வல்லினம் rules keep these
    words excluded; a split-word check is scoped separately (LANGUAGE_QA_PLAN)."""
    if not human(example):
        return  # Phase 2.4 maybes: contradicted AI rows, not insisted on either way
    findings = scan_text(example["text"], book="x", chapter="1", verse="1", tamil=True)["findings"]
    for maybe in example.get("maybe", []):
        claimed = [f["originalText"] for f in findings
                   if f["category"] == "sandhi" and overlaps(f["originalText"], maybe["span"])]
        assert not claimed, (maybe, claimed)


@pytest.mark.parametrize("bucket,example", examples("positive"))
def test_a_positive_credited_to_a_rule_is_still_found_by_it(bucket, example):
    for expected in example["expect"]:
        if not expected["ruleId"]:
            continue  # no current rule covers it; Phase 3+ will
        if expected["ruleId"].endswith("/tamil.wordlist-variant"):
            continue  # a book-wide audit, not a per-verse rule; the benchmark measures it
        found = findings_of(example, expected["ruleId"])
        span = nfc(expected["span"])
        assert any(overlaps(f["originalText"], span) for f in found), (expected, [f["originalText"] for f in found])
        if human(example) and expected.get("fix"):
            # The reviewer confirmed this fix: where the finding covers exactly
            # the reviewed span, one of its suggestions must be it.
            for finding in (f for f in found if nfc(f["originalText"]) == span):
                assert nfc(expected["fix"]) in {nfc(s["text"]) for s in finding["suggestions"]}, \
                    (expected, finding["suggestions"])
