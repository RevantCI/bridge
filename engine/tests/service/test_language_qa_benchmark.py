"""The Phase 2 benchmark harness, on a synthetic book and review report so it
runs anywhere (the real IRV text and reports are outside the repository)."""
import csv
import json
import subprocess
import sys

import pytest

from tc_ai_bridge import language_qa_benchmark as bench
from tests.support.paths import REPO_ROOT

COLUMNS = ["Book", "Chapter", "Verse", "Issue Type", "Priority Category", "Severity", "Confidence",
           "Original Tamil", "Suggested Correction", "Explanation", "Source / Reference Note",
           "Reviewer Decision Needed", "Status"]

SFM = "\n".join([
    "\\id RUT synthetic benchmark book", "\\c 1", "\\p",
    "\\v 1 அவன் அந்த காகம் பார்த்தான்.",       # vallinam, flagged by the review -> TP
    "\\v 2 அவள் அந்த பெண் வந்தாள்.",            # vallinam, not in the review -> FP
    "\\v 3 அவன் இந்த கல்லை எடுத்தான்.",          # vallinam on a Pass 3 house form (இந்த + bare), no row -> FP, house form
    "\\v 4 அவன் இந்த பட்டணம் போனான்.",          # vallinam; the row flagging it is house form -> maybe
    "\\v 5 அவர் அந்த சபையைக் கண்டார்.",          # vallinam; a human rejected the AI row -> maybe
    "\\v 7 அவன் அந்த தேசத்தில் இருந்தான்.",       # the pack abstains: IRV house form அந்த தேச- -> no finding
    "\\v 6 இது முழவதும் சரி.",                   # typo row the engine cannot find -> FN
    "",
])


def review_rows():
    def row(chapter, verse, kind, original, fix, status="Open", explanation="AI proposal"):
        return {"Book": "Ruth", "Chapter": chapter, "Verse": verse, "Issue Type": kind, "Priority Category": "",
                "Severity": "Medium", "Confidence": "Medium", "Original Tamil": original,
                "Suggested Correction": fix, "Explanation": explanation, "Source / Reference Note": "",
                "Reviewer Decision Needed": "", "Status": status}
    return [
        row("1", "1", "Sandhi / word-joining", "அந்த காகம்", "அந்தக் காகம்"),
        row("1", "4", "Sandhi / word-joining", "இந்த பட்டணம்", "இந்தப் பட்டணம்"),
        row("1", "5", "Sandhi / word-joining", "அந்த சபையை", "அந்தச் சபையை", status="Rejected"),
        row("1", "6", "Confirmed typo", "முழவதும்", "முழுவதும்"),
        row("1", "6", "Source comparison", "இது", "அது"),                     # out of scope
        row("1", "6", "Punctuation", "சரி.", "சரி;", explanation="Comma splice policy"),  # policy, out
        row("1", "2", "Punctuation", "வந்தாள் .", "வந்தாள்.", explanation="Space before full stop"),
        row("Intro", "—", "Confirmed typo", "x", "y"),                        # skipped
    ]


def write_inputs(tmp_path, rows):
    irv = tmp_path / "irv"
    irv.mkdir()
    (irv / "08RUTIRVTam.SFM").write_text(SFM, encoding="utf-8")
    reviews = tmp_path / "reviews"
    reviews.mkdir()
    with (reviews / "RUT_Round2_Proofreading_Issues.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return irv, reviews


@pytest.fixture
def benchmark(tmp_path):
    irv, reviews = write_inputs(tmp_path, review_rows())
    rows = bench.load_review_rows([reviews / "RUT_Round2_Proofreading_Issues.csv"])
    book, chapters = bench.book_verses(irv / "08RUTIRVTam.SFM")
    scans = {book: bench.scan_book(book, chapters)}
    return rows, bench.score(rows, scans, {book: chapters}), {book: chapters}


def test_rows_are_labelled_by_scope_verdict_and_contradiction(benchmark):
    rows, _, _ = benchmark
    labels = {(r.chapter, r.verse, r.issue_type): (r.label, r.reason) for r in rows}
    assert all(r.book == "rut" for r in rows)
    assert labels[("1", "1", "Sandhi / word-joining")][0] == "positive"
    assert labels[("1", "4", "Sandhi / word-joining")] == (
        "maybe", "Pass 3 confirmed house form: இந்த + bare hard consonant")
    # A human verdict against the AI proposal is a contradiction, not ground truth.
    assert labels[("1", "5", "Sandhi / word-joining")] == (
        "maybe", "human verdict: Rejected (contradicts the AI proposal)")
    assert labels[("1", "6", "Source comparison")][0] == "out-of-scope"
    assert labels[("1", "6", "Punctuation")] == ("out-of-scope", "punctuation policy, not spacing")
    assert labels[("1", "2", "Punctuation")][0] == "positive"
    assert labels[("Intro", "—", "Confirmed typo")][0] == "skipped"


def test_contradicting_rows_become_maybe():
    def row(original, fix, verse="1", bucket="typo"):
        return bench.ReviewRow(source="x", family="Round2", book="gen", chapter="1", verse=verse,
                               issue_type="Possible typo", bucket=bucket, severity="", confidence="",
                               original=original, suggestion=fix, explanation="", status="Open")
    different = [row("அவன்", "அவர்"), row("அவன்", "அவள்")]
    reversal = [row("மாலை வரை", "மாலைவரை", verse="2"), row("மாலைவரை", "மாலை வரை", verse="2")]
    digits = [row("12 பேர்", "பன்னிரண்டு பேர்", verse="3"), row("4. வது", "4 வது", verse="4")]
    rows = different + reversal + digits
    bench.classify(rows)
    assert [r.label for r in different] == ["maybe", "maybe"]
    assert [r.label for r in reversal] == ["maybe", "maybe"]
    # Writing out numerals contradicts the digits house form; fixing a stray stop does not.
    assert [r.label for r in digits] == ["maybe", "positive"]


def test_findings_are_scored_against_compatible_rows_only(benchmark):
    _, result, _ = benchmark
    vallinam = result["rules"]["ta-irv/sandhi.vallinam.demonstrative"]
    assert vallinam["findings"] == 5
    assert vallinam["tp_strict"] == 1                 # 1:1
    assert vallinam["matched_maybe"] == 2             # 1:4 house form, 1:5 human-rejected: strict FP, lenient TP
    assert vallinam["matched_negative"] == 0
    assert vallinam["fp_strict"] == 4 and vallinam["tp_lenient"] == 3
    assert vallinam["fp_house_form"] == 1             # 1:3 இந்த + bare (1:7 அந்த தேச- is abstained by the pack)
    assert vallinam["precision_strict"] == 0.2 and vallinam["precision_lenient"] == 0.6
    assert vallinam["inline"] is True
    # The spacing row at 1:2 is not matched by the vallinam finding at the same verse.
    assert result["buckets"]["punctuation"]["found_positive"] == 0


def test_recall_counts_only_anchored_rows(benchmark):
    _, result, _ = benchmark
    sandhi = result["buckets"]["sandhi"]
    assert (sandhi["rows_positive"], sandhi["rows_maybe"], sandhi["rows_negative"]) == (1, 2, 0)
    assert sandhi["recall_strict"] == 1.0 and sandhi["recall_lenient"] == 1.0
    typo = result["buckets"]["typo"]
    assert typo["anchored_positive"] == 1 and typo["found_positive"] == 0 and typo["recall_strict"] == 0.0
    assert [r["original"] for r in result["unmatchedRows"] if r["bucket"] == "typo"] == ["முழவதும்"]
    punctuation = result["buckets"]["punctuation"]
    assert punctuation["unanchored"] == 1  # "வந்தாள் ." is not in the verse text
    assert result["outOfScope"] == {"Source comparison": 1, "Punctuation": 1}


def test_unmatched_findings_are_listed_for_a_human_to_label(benchmark):
    _, result, _ = benchmark
    unmatched = {(f["verse"], f["originalText"]): f for f in result["unmatchedFindings"]}
    assert set(unmatched) == {("2", "அந்த பெண்"), ("3", "இந்த கல்லை")}
    assert unmatched[("3", "இந்த கல்லை")]["houseForm"] == "இந்த + bare hard consonant"
    assert unmatched[("2", "அந்த பெண்")]["houseForm"] is None


def test_gate_fails_an_imprecise_inline_rule_and_a_precision_drop(benchmark):
    _, result, _ = benchmark
    rule = result["rules"]["ta-irv/sandhi.vallinam.demonstrative"]
    # Signed off for inline at 41.25%: this synthetic 20% is more than 2 points below that.
    assert rule["signOff"]["precisionStrict"] == 0.4125
    assert bench.gate(result, None) == [
        "ta-irv/sandhi.vallinam.demonstrative fell below its inline sign-off: 20.0% < 41.2% - 2 points"]
    # Within 2 points of the sign-off it passes, though far below 90%.
    rule["signOff"] = {**rule["signOff"], "precisionStrict": 0.21}
    assert bench.gate(result, None) == []
    # Without a sign-off an inline rule must reach 90%.
    rule["signOff"] = None
    assert bench.gate(result, None) == [
        "ta-irv/sandhi.vallinam.demonstrative is inline but strict precision is 20.0% (< 90.0%)"]
    rule["signOff"] = {"by": "m", "date": "d", "precisionStrict": None}
    assert "records no precision" in bench.gate(result, None)[0]
    rule["signOff"] = {"by": "m", "date": "d", "precisionStrict": 0.21}
    baseline = {"rules": {"ta-irv/sandhi.vallinam.demonstrative": {"precision_strict": 0.5, "findings": 12}}}
    assert bench.gate(result, baseline) == []  # 5 findings now: too few to compare a drop
    rule["findings"] = 12
    dropped = bench.gate(result, baseline)
    assert "fell from 50.0% to 20.0%" in dropped[-1]
    assert bench.gate(result, baseline, inline_min_precision=0.1, max_drop=0.5) == []


def test_baseline_holds_numbers_only(benchmark):
    _, result, _ = benchmark
    text = json.dumps(bench.baseline_of(result), ensure_ascii=False)
    assert "அந்த" not in text and "unmatched" not in text
    assert bench.baseline_of(result)["rules"]["ta-irv/sandhi.vallinam.demonstrative"]["precision_strict"] == 0.2


def test_labelled_examples_quote_their_verse(benchmark):
    rows, _, verses = benchmark
    examples = bench.labelled_examples(rows, verses)
    sandhi = examples["sandhi"]
    # Maybe rows first; a test on them must not insist either way.
    assert [e["maybe"][0]["span"] for e in sandhi[:2]] == ["இந்த பட்டணம்", "அந்த சபையை"]
    assert all(e["expect"] == [] for e in sandhi[:2])
    positive = sandhi[2]
    assert positive["expect"][0]["span"] in positive["text"]
    assert positive["expect"][0]["fix"] == "அந்தக் காகம்"
    assert positive["expect"][0]["ruleId"] == "ta-irv/sandhi.vallinam.demonstrative"
    assert positive["origin"].startswith("RUT 1:1")


@pytest.mark.subprocess
def test_cli_gate_exit_code_and_outputs(tmp_path):
    irv, reviews = write_inputs(tmp_path, review_rows())
    out = tmp_path / "out"
    command = [sys.executable, str(REPO_ROOT / "scripts" / "language_qa_benchmark.py"),
               "--irv-dir", str(irv), "--reviews", str(reviews), "--out-dir", str(out),
               "--baseline", str(tmp_path / "baseline.json")]
    written = subprocess.run(command + ["--write-baseline"], capture_output=True, text=True, encoding="utf-8")
    assert written.returncode == 0, written.stderr
    assert "| `ta-irv/sandhi.vallinam.demonstrative` | yes | 5 |" in written.stdout
    assert json.loads((tmp_path / "baseline.json").read_text(encoding="utf-8"))["books"] == ["rut"]
    [result_file] = out.glob("*.json")
    assert json.loads(result_file.read_text(encoding="utf-8"))["unmatchedFindings"]
    gated = subprocess.run(command + ["--gate"], capture_output=True, text=True, encoding="utf-8")
    assert gated.returncode == 1 and "gate: FAIL" in gated.stderr
