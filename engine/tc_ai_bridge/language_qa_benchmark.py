"""Language QA benchmark: per-rule precision and recall against the IRV
Round 2 and Pass 3 review reports (layered-rules brief, Phase 2).

What the numbers mean. Every review row is an AI proposal; the maintainer
decided on 2026-09-24 that they are all to be used as positives (a false
positive can be corrected later). A row is "maybe" instead when the reports
contradict themselves on it (see contradictions()) or a human verdict
contradicts it. Nothing in the inputs is a verified negative. So precision
here measures agreement with the AI review, not with verified truth --
docs/LANGUAGE_QA_BENCHMARK.md says so next to every table.

The scan is the app's own: every book is scanned by LanguageQaManager over
chapter JSON built the way import builds it (parse_scripture_file +
imported_verse_text), so nothing here can drift from what a translator sees.
No Scripture is written anywhere but a temporary directory.
"""
from __future__ import annotations

import csv
import json
import re
import tempfile
import time
import unicodedata
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable

from .language_qa import INLINE_RULES, PACK_VERSION, RULES
from .language_qa_jobs import LanguageQaManager
from .project_import import BOOK_NAMES, imported_verse_text, parse_scripture_file

# Issue Type -> the offline engine's bucket. Everything else is reported as
# out of scope (LQA-3+): meaning, grammar and source comparison are not
# text-only checks.
SCORED_TYPES = {
    "Confirmed typo": "typo",
    "Possible typo": "typo",
    "Sandhi / word-joining": "sandhi",
    "Punctuation": "punctuation",       # only spacing / repetition / space-before; see _punctuation_in_scope
    "Name consistency": "name",
    "USFM marker": "usfm",
    "Footnote / cross-reference": "usfm",
}
BUCKETS = ("typo", "sandhi", "punctuation", "name", "usfm")

# Which review bucket a rule's finding can agree with. A finding that only
# overlaps a row of another bucket is not a true positive for that rule.
RULE_BUCKETS = {
    "tamil.vallinam-missing": {"sandhi"},
    "tamil.repeated-word": {"typo"},
    "tamil.wordlist-variant": {"typo"},
    "tamil.mixed-word": {"typo"},
    "tamil.dependent-sign": {"typo"},
    "unicode.corruption": {"typo"},
    "unicode.nfc": {"typo"},
    "unicode.private-use": {"typo"},
    "unicode.invisible": {"typo"},
    "spacing.extra": {"punctuation", "usfm"},
    "spacing.unusual": {"punctuation"},
    "punctuation.repeated": {"punctuation"},
    "punctuation.space-before": {"punctuation", "usfm"},
    "terminology.deprecated-form": {"name", "typo"},
}

# House forms the Pass 3 reviewers confirmed are NOT errors
# (IRV_Pass3_Handoff.md, section 5, "Method notes carried forward"). A row
# that flags one of them contradicts that finding, so it is "maybe".
SANDHI_HOUSE_FORMS = (
    ("இந்த + bare hard consonant", re.compile(r"(?:^|\s)இந்த\s+[கசதப]")),
    ("அந்த தேச- bare", re.compile(r"(?:^|\s)அந்த\s+தேச")),
    ("-விட bare", re.compile(r"விட\s+[கசதப]")),
    ("proper name ending in -க்கு (ஈசாக்கு, ஏனோக்கு) is a nominative", re.compile(r"(?:ஈசாக்கு|ஏனோக்கு)\s")),
)


def _house_form(row: "ReviewRow") -> str | None:
    """The confirmed house form a row flags, if any."""
    original = nfc(row.original)
    if row.bucket == "sandhi":
        for name, pattern in SANDHI_HOUSE_FORMS:
            if pattern.search(original):
                return name
    # Digits: only a proposal to write out numerals contradicts the house form.
    if row.bucket in {"typo", "punctuation"} and re.search(r"\d", original) \
            and row.suggestion and not re.search(r"\d", row.suggestion):
        return "digits in verse text"
    return None

# A human verdict against an AI proposal is a contradiction, so "maybe", not a
# negative: the Philippians pass answered a different question (is this
# inconsistency worth an editorial fix), and the maintainer said its
# dispositions are not linguistic ground truth (BUILD_LOG, B3 entry; php 1:29
# later went from Rejected to Confirmed). Nothing in the inputs is a verified
# negative, so "negative" is reserved for a future human-labelled set.
HUMAN_NEGATIVE: set[str] = set()
HUMAN_MAYBE = {"rejected", "disputed"}

_BOOK_CODES = {name.lower(): code for code, name in BOOK_NAMES.items()}
_BOOK_CODES.update({code: code for code in BOOK_NAMES})
_BOOK_CODES.update({"psalm": "psa", "song of songs": "sng", "song of solomon": "sng"})


def nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text or "")


def book_code(value: str) -> str | None:
    return _BOOK_CODES.get((value or "").strip().lower())


@dataclass
class ReviewRow:
    source: str          # file name
    family: str          # "Round2" | "Pass3" | "Reviewed"
    book: str
    chapter: str
    verse: str
    issue_type: str
    bucket: str | None   # None: out of scope
    severity: str
    confidence: str
    original: str
    suggestion: str
    explanation: str
    status: str
    label: str = "positive"   # "positive" | "maybe" | "negative" | "out-of-scope" | "skipped"
    reason: str = ""
    anchored: bool = False    # Original Tamil found in the scanned verse text
    matched_by: list[str] = field(default_factory=list)


def _family(path: Path) -> str:
    name = path.name
    if "Pass3" in name:
        return "Pass3"
    if "Round2" in name and "Issues" in name and "QA_Issues" not in name:
        return "Round2"
    return "Reviewed"


def _punctuation_in_scope(original: str, suggestion: str, explanation: str) -> bool:
    """Spacing, repetition and space-before only; comma/semicolon policy is out."""
    squeeze = lambda s: re.sub(r"\s+", "", nfc(s))  # noqa: E731
    if suggestion and squeeze(original) == squeeze(suggestion) and nfc(original) != nfc(suggestion):
        return True
    if re.search(r" {2,}|([,;:!?.])\1| [,;:!?.]", original):
        return True
    return bool(re.search(r"\b(space|spacing|double|repeated|duplicated|stray)\b", explanation, re.I))


def load_review_rows(paths: Iterable[Path]) -> list[ReviewRow]:
    rows: list[ReviewRow] = []
    for path in paths:
        with Path(path).open(encoding="utf-8-sig", newline="") as handle:
            for raw in csv.DictReader(handle):
                get = lambda key: (raw.get(key) or "").strip()  # noqa: E731
                issue_type = get("Issue Type")
                row = ReviewRow(
                    source=Path(path).name, family=_family(Path(path)),
                    book=book_code(get("Book")) or get("Book").lower(),
                    chapter=get("Chapter"), verse=get("Verse"), issue_type=issue_type,
                    bucket=SCORED_TYPES.get(issue_type), severity=get("Severity"),
                    confidence=get("Confidence"), original=get("Original Tamil"),
                    suggestion=get("Suggested Correction"), explanation=get("Explanation"),
                    status=get("Status"),
                )
                rows.append(row)
    classify(rows)
    return rows


def classify(rows: list[ReviewRow]) -> None:
    """Scope first, then human verdicts, then contradictions."""
    for row in rows:
        if not row.chapter.isdigit() or not row.verse or not row.verse[:1].isdigit():
            row.label, row.reason = "skipped", "not a verse (Intro, book-level, or no verse)"
        elif not row.original:
            row.label, row.reason = "skipped", "no Original Tamil to match"
        elif row.bucket is None:
            row.label, row.reason = "out-of-scope", f"{row.issue_type}: not a text-only check (LQA-3+)"
        elif row.bucket == "punctuation" and not _punctuation_in_scope(row.original, row.suggestion, row.explanation):
            row.bucket, row.label, row.reason = None, "out-of-scope", "punctuation policy, not spacing"
        elif row.status.lower() in HUMAN_NEGATIVE:
            row.label, row.reason = "negative", f"human verdict: {row.status}"
        elif row.status.lower() in HUMAN_MAYBE:
            row.label, row.reason = "maybe", f"human verdict: {row.status} (contradicts the AI proposal)"
    for row, reason in contradictions(rows):
        if row.label == "positive":
            row.label, row.reason = "maybe", reason


def contradictions(rows: list[ReviewRow]) -> list[tuple[ReviewRow, str]]:
    """Rows the reports themselves disagree on:
    - two rows at one place, on the same text, proposing different fixes;
    - a fix that another row at the same verse proposes to undo;
    - a flag on a form the Pass 3 reviewers confirmed is house style."""
    found: list[tuple[ReviewRow, str]] = []
    in_scope = [r for r in rows if r.label == "positive"]
    by_place: dict[tuple[str, str, str, str], list[ReviewRow]] = defaultdict(list)
    by_verse: dict[tuple[str, str, str], list[ReviewRow]] = defaultdict(list)
    for row in in_scope:
        by_place[(row.book, row.chapter, row.verse, nfc(row.original))].append(row)
        by_verse[(row.book, row.chapter, row.verse)].append(row)
    for group in by_place.values():
        fixes = {nfc(r.suggestion) for r in group if r.suggestion}
        if len(fixes) > 1:
            found.extend((r, "reports propose different fixes for the same text") for r in group)
    for group in by_verse.values():
        for a in group:
            for b in group:
                if a is not b and a.suggestion and nfc(a.suggestion) == nfc(b.original) \
                        and nfc(b.suggestion) == nfc(a.original):
                    found.append((a, "another row at this verse proposes the opposite change"))
    for row in in_scope:
        name = _house_form(row)
        if name:
            found.append((row, f"Pass 3 confirmed house form: {name}"))
    return found


def book_verses(sfm: Path) -> tuple[str, dict[str, dict[str, str]]]:
    """(book id, chapter -> verse -> text) exactly as an import writes it."""
    parsed = parse_scripture_file(sfm)
    return parsed.book_id, {
        chapter: {verse: imported_verse_text(text) for verse, text in verses.items()}
        for chapter, verses in parsed.chapters.items()
    }


def scan_book(book: str, chapters: dict[str, dict[str, str]], *,
              terminology: list[dict[str, Any]] | None = None, timeout: float = 600.0) -> dict[str, Any]:
    """Scan with the app's own LanguageQaManager over temporary chapter JSON."""
    with tempfile.TemporaryDirectory(prefix="lqa-bench-") as tmp:
        root = Path(tmp)
        folder = root / book
        folder.mkdir()
        for chapter, verses in chapters.items():
            (folder / f"{chapter}.json").write_text(json.dumps(verses, ensure_ascii=False), encoding="utf-8")
        project = SimpleNamespace(path=root, book_id=book, book_dir=folder,
                                  manifest={"target_language": {"id": "tam"}},
                                  terminology_rules=lambda: list(terminology or []))
        manager = LanguageQaManager(debounce=0, yield_seconds=0)
        started = time.perf_counter()
        manager.bind(project)
        try:
            deadline = time.monotonic() + timeout
            while manager.status()["state"] not in {"completed", "failed"}:
                if time.monotonic() > deadline:
                    raise TimeoutError(f"Language QA did not finish {book}")
                time.sleep(0.01)
            status = manager.status()
            findings = [f for offset in range(0, status["totalFindings"], 100)
                        for f in manager.status(offset=offset, limit=100)["findings"]]
        finally:
            manager.unbind()
    return {"book": book, "wall": time.perf_counter() - started, "findings": findings,
            "limitations": status.get("limitations", []), "checkedVerses": status.get("checkedVerses", 0)}


def _overlaps(a: str, b: str) -> bool:
    a, b = nfc(a), nfc(b)
    return bool(a and b) and (a in b or b in a)


def score(rows: list[ReviewRow], scans: dict[str, dict[str, Any]],
          verses: dict[str, dict[str, dict[str, str]]]) -> dict[str, Any]:
    """Match findings to rows; count per rule and per bucket."""
    books = set(scans)
    scored = [r for r in rows if r.book in books and r.label in {"positive", "maybe", "negative"}]
    for row in scored:
        text = verses.get(row.book, {}).get(row.chapter, {}).get(row.verse)
        row.anchored = text is not None and nfc(row.original) in nfc(text)
    by_verse: dict[tuple[str, str, str], list[ReviewRow]] = defaultdict(list)
    for row in scored:
        by_verse[(row.book, row.chapter, row.verse)].append(row)

    per_rule: dict[str, Counter] = defaultdict(Counter)
    unmatched_findings: list[dict[str, Any]] = []
    for book, scan in scans.items():
        for finding in scan["findings"]:
            rule = finding["rule"]
            buckets = RULE_BUCKETS.get(rule, set())
            candidates = [r for r in by_verse.get((book, finding["chapter"], finding["verse"]), [])
                          if r.bucket in buckets and _overlaps(finding["originalText"], r.original)]
            labels = {r.label for r in candidates}
            for r in candidates:
                r.matched_by.append(finding["ruleId"])
            stats = per_rule[finding["ruleId"]]
            stats["findings"] += 1
            if "negative" in labels:
                stats["fp_strict"] += 1
                stats["fp_lenient"] += 1
                stats["matched_negative"] += 1
            elif "positive" in labels:
                stats["tp_strict"] += 1
                stats["tp_lenient"] += 1
            elif "maybe" in labels:
                stats["fp_strict"] += 1
                stats["tp_lenient"] += 1
                stats["matched_maybe"] += 1
            else:
                stats["fp_strict"] += 1
                stats["fp_lenient"] += 1
                # A finding on a form the Pass 3 reviewers confirmed is house
                # style: the abstains Phase 3's rule pack needs.
                house = next((name for name, pattern in SANDHI_HOUSE_FORMS
                              if pattern.search(nfc(finding["originalText"]))), None) \
                    if "sandhi" in buckets else None
                if house:
                    stats["fp_house_form"] += 1
                unmatched_findings.append({
                    "houseForm": house,
                    "book": book, "chapter": finding["chapter"], "verse": finding["verse"],
                    "ruleId": finding["ruleId"], "originalText": finding["originalText"],
                    "suggestion": finding.get("suggestedReplacement"), "message": finding["message"],
                })

    per_bucket: dict[str, Counter] = {bucket: Counter() for bucket in BUCKETS}
    unmatched_rows: list[dict[str, Any]] = []
    for row in scored:
        stats = per_bucket[row.bucket]
        stats[f"rows_{row.label}"] += 1
        if not row.anchored:
            stats["unanchored"] += 1
            continue
        if row.label == "negative":
            continue
        stats[f"anchored_{row.label}"] += 1
        if row.matched_by:
            stats[f"found_{row.label}"] += 1
        elif row.label == "positive":
            unmatched_rows.append({k: v for k, v in asdict(row).items() if k != "matched_by"})

    def ratio(numerator: int, denominator: int) -> float | None:
        return round(numerator / denominator, 4) if denominator else None

    rule_keys = ("findings", "tp_strict", "fp_strict", "tp_lenient", "fp_lenient",
                 "matched_maybe", "matched_negative", "fp_house_form")
    rules_out = {}
    for rule_id, stats in sorted(per_rule.items()):
        rules_out[rule_id] = {
            **{key: stats.get(key, 0) for key in rule_keys},
            "inline": rule_id.split("/", 1)[-1] in INLINE_RULES,
            "precision_strict": ratio(stats["tp_strict"], stats["tp_strict"] + stats["fp_strict"]),
            "precision_lenient": ratio(stats["tp_lenient"], stats["tp_lenient"] + stats["fp_lenient"]),
        }
    bucket_keys = [f"{prefix}_{label}" for prefix in ("rows", "anchored", "found")
                   for label in ("positive", "maybe", "negative")] + ["unanchored"]
    buckets_out = {}
    for bucket, stats in per_bucket.items():
        buckets_out[bucket] = {
            **{key: stats.get(key, 0) for key in bucket_keys},
            "recall_strict": ratio(stats["found_positive"], stats["anchored_positive"]),
            "recall_lenient": ratio(stats["found_positive"] + stats["found_maybe"],
                                    stats["anchored_positive"] + stats["anchored_maybe"]),
        }
    labels = Counter((r.label, r.family) for r in rows)
    return {
        "packVersion": PACK_VERSION,
        "books": sorted(books),
        "rows": {"total": len(rows), **{f"{label}/{family}": n for (label, family), n in sorted(labels.items())}},
        "outOfScope": dict(Counter(r.issue_type for r in rows if r.label == "out-of-scope" and r.book in books)),
        "rules": rules_out, "buckets": buckets_out,
        "unmatchedFindings": unmatched_findings, "unmatchedRows": unmatched_rows,
        "maybeReasons": dict(Counter(r.reason.split(":")[0] for r in scored if r.label == "maybe")),
        "scan": {b: {"wall": round(s["wall"], 2), "checkedVerses": s["checkedVerses"],
                     "findings": len(s["findings"])} for b, s in scans.items()},
    }


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.1f}%"


def markdown_tables(result: dict[str, Any]) -> str:
    lines = [
        f"Pack version `{result['packVersion']}`; books: {', '.join(b.upper() for b in result['books'])}.",
        "",
        "Per rule (a finding is a true positive when it overlaps a review row of a compatible type at the same verse):",
        "",
        "| Rule | Inline | Findings | TP (strict) | FP (strict) | of which on a house form | Precision strict | Precision lenient | Matched maybe | Matched negative |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for rule_id, s in result["rules"].items():
        lines.append(f"| `{rule_id}` | {'yes' if s['inline'] else 'no'} | {s.get('findings', 0)} | {s.get('tp_strict', 0)} "
                     f"| {s.get('fp_strict', 0)} | {s.get('fp_house_form', 0)} | {_pct(s['precision_strict'])} "
                     f"| {_pct(s['precision_lenient'])} | {s.get('matched_maybe', 0)} | {s.get('matched_negative', 0)} |")
    lines += [
        "",
        "Per review bucket (recall counts only rows whose Original Tamil is found in the scanned verse):",
        "",
        "| Bucket | Positive rows | Maybe rows | Negative rows | Unanchored | Found (positive) | Recall strict | Recall lenient |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for bucket, s in result["buckets"].items():
        lines.append(f"| {bucket} | {s.get('rows_positive', 0)} | {s.get('rows_maybe', 0)} | {s.get('rows_negative', 0)} "
                     f"| {s.get('unanchored', 0)} | {s.get('found_positive', 0)} | {_pct(s['recall_strict'])} "
                     f"| {_pct(s['recall_lenient'])} |")
    return "\n".join(lines)


def gate(result: dict[str, Any], baseline: dict[str, Any] | None, *,
         inline_min_precision: float = 0.90, max_drop: float = 0.02, min_findings: int = 10) -> list[str]:
    """Failures, empty when the gate passes:
    - an inline rule below `inline_min_precision` (strict);
    - any rule whose strict precision fell more than `max_drop` below the
      committed baseline (rules with fewer than `min_findings` findings in
      either run are too small to compare and are skipped)."""
    failures = []
    for rule_id, stats in result["rules"].items():
        precision = stats["precision_strict"]
        if stats["inline"] and precision is not None and precision < inline_min_precision:
            failures.append(f"{rule_id} is inline but strict precision is {_pct(precision)} (< {_pct(inline_min_precision)})")
        before = (baseline or {}).get("rules", {}).get(rule_id)
        if before and precision is not None and before.get("precision_strict") is not None \
                and stats.get("findings", 0) >= min_findings and before.get("findings", 0) >= min_findings \
                and precision < before["precision_strict"] - max_drop:
            failures.append(f"{rule_id} strict precision fell from {_pct(before['precision_strict'])} to {_pct(precision)}")
    return failures


def baseline_of(result: dict[str, Any]) -> dict[str, Any]:
    """The committed baseline: aggregate numbers only, no Scripture or review text."""
    keep = ("findings", "tp_strict", "fp_strict", "precision_strict", "precision_lenient", "inline")
    return {"packVersion": result["packVersion"], "books": result["books"],
            "rules": {rule: {k: s.get(k) for k in keep} for rule, s in result["rules"].items()},
            "buckets": {bucket: {k: s.get(k) for k in ("recall_strict", "recall_lenient", "rows_positive")}
                        for bucket, s in result["buckets"].items()}}


def labelled_examples(rows: list[ReviewRow], verses: dict[str, dict[str, dict[str, str]]], *,
                      per_bucket: int = 40) -> dict[str, list[dict[str, Any]]]:
    """Phase 2.4 fixtures, per bucket, deterministic and bounded:
    - every anchored negative row: {"text", "expect": [], "rejectedSpan"};
    - every anchored maybe row: {"text", "expect": [], "maybe": [{span, reason}]}
      -- a rule may or may not flag it; a test must not insist either way;
    - a strided sample of anchored positive rows: {"text", "expect": [{ruleId,
      category, span, fix}]}.
    ruleId is the current rule that found the row, or None where no rule
    does yet; the Phase 3 rule pack assigns its own."""
    out: dict[str, list[dict[str, Any]]] = {bucket: [] for bucket in BUCKETS}
    order = {"negative": 0, "maybe": 1, "positive": 2}
    for bucket in BUCKETS:
        candidates = sorted(
            (r for r in rows if r.bucket == bucket and r.anchored and r.label in order),
            key=lambda r: (order[r.label], r.book, int(r.chapter), r.verse, r.original))
        fixed = [r for r in candidates if r.label != "positive"]
        positives = [r for r in candidates if r.label == "positive"]
        stride = max(1, len(positives) // per_bucket) if positives else 1
        for row in fixed + positives[::stride][:per_bucket]:
            text = verses[row.book][row.chapter][row.verse]
            origin = f"{row.book.upper()} {row.chapter}:{row.verse} ({row.source})"
            if row.label == "negative":
                out[bucket].append({"text": text, "expect": [], "rejectedSpan": row.original, "origin": origin})
            elif row.label == "maybe":
                out[bucket].append({"text": text, "expect": [], "origin": origin,
                                    "maybe": [{"span": row.original, "fix": row.suggestion or None,
                                               "reason": row.reason}]})
            else:
                out[bucket].append({"text": text, "origin": origin, "expect": [{
                    "ruleId": next(iter(row.matched_by), None), "category": bucket,
                    "span": row.original, "fix": row.suggestion or None}]})
    return out


def load_rules_inline() -> dict[str, bool]:
    return {f"{meta.pack}/{rule}": rule in INLINE_RULES for rule, meta in RULES.items()}
