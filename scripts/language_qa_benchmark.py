"""Language QA accuracy benchmark (layered-rules brief, Phase 2).

    python scripts/language_qa_benchmark.py --irv-dir "D:/…/IRV Tamil" \
        --reviews "D:/…/Claude outputs" "C:/…/Philippians_Round2_QA_Issues.csv" \
        [--gate] [--write-baseline] [--update-doc] [--write-labelled]

Run it with the engine's interpreter (engine/.venv). It reads the IRV SFM
books and the review CSVs, scans every reviewed book with the app's own
Language QA, and prints per-rule precision and per-bucket recall. The full
result (with verse text and review rows, for a human to label the
unmatched findings) is written to benchmark/results/, which is not
committed; only aggregate numbers go into benchmark/baseline.json and
docs/LANGUAGE_QA_BENCHMARK.md. See that doc for what the numbers mean.

--gate exits 1 when an inline rule's strict precision is below 0.90, or a
rule's strict precision fell more than 2 points below the committed
baseline. It is a local gate: the IRV text and review reports live outside
the repository, so CI cannot run it (maintainer decision, 2026-09-24).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "engine"))

from tc_ai_bridge import language_qa_benchmark as bench  # noqa: E402

DOC = REPO / "docs" / "LANGUAGE_QA_BENCHMARK.md"
START, END = "<!-- benchmark:start -->", "<!-- benchmark:end -->"


def review_files(paths: list[str]) -> list[Path]:
    files: list[Path] = []
    for value in paths:
        path = Path(value)
        # Top level only: v1-before-split/ holds superseded reports.
        files.extend(sorted(path.glob("*_Issues.csv")) if path.is_dir() else [path])
    return files


ID_LINE = re.compile(r"\\id\s+([0-9A-Za-z]{3})")


def sfm_by_book(irv_dir: Path) -> dict[str, Path]:
    """Book code -> SFM file, from each file's own \\id line."""
    found: dict[str, Path] = {}
    for sfm in sorted(irv_dir.glob("*.SFM")) + sorted(irv_dir.glob("*.usfm")):
        with sfm.open(encoding="utf-8-sig", errors="replace") as handle:
            match = ID_LINE.search(handle.read(512))
        if match:
            found.setdefault(match.group(1).lower(), sfm)
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--irv-dir", required=True, type=Path)
    parser.add_argument("--reviews", required=True, nargs="+")
    parser.add_argument("--books", nargs="*", help="limit to these book codes")
    parser.add_argument("--out-dir", type=Path, default=REPO / "benchmark" / "results")
    parser.add_argument("--baseline", type=Path, default=REPO / "benchmark" / "baseline.json")
    parser.add_argument("--gate", action="store_true")
    parser.add_argument("--write-baseline", action="store_true")
    parser.add_argument("--update-doc", action="store_true")
    parser.add_argument("--write-labelled", action="store_true")
    args = parser.parse_args()

    rows = bench.load_review_rows(review_files(args.reviews))
    wanted = {b.lower() for b in args.books} if args.books else None
    books = sorted({r.book for r in rows if r.book in bench.BOOK_NAMES and (wanted is None or r.book in wanted)})
    sfms = sfm_by_book(args.irv_dir)
    verses, scans = {}, {}
    for book in books:
        if book not in sfms:
            print(f"warning: no SFM for {book.upper()} in {args.irv_dir}; its rows are not scored", file=sys.stderr)
            continue
        _, chapters = bench.book_verses(sfms[book])
        verses[book] = chapters
        scans[book] = bench.scan_book(book, chapters)
        print(f"scanned {book.upper()}: {scans[book]['checkedVerses']} verses, "
              f"{len(scans[book]['findings'])} findings, {scans[book]['wall']:.2f}s", file=sys.stderr)
    result = bench.score(rows, scans, verses)
    result["generatedAt"] = dt.datetime.now().isoformat(timespec="seconds")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.date.today().isoformat()
    out = args.out_dir / f"{stamp}-{result['packVersion']}.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    table = bench.markdown_tables(result)
    print(table)
    print(f"\nfull result: {out}", file=sys.stderr)

    if args.write_labelled:
        target = REPO / "engine" / "tests" / "fixtures" / "language_qa" / "labelled"
        target.mkdir(parents=True, exist_ok=True)
        for bucket, examples in bench.labelled_examples(rows, verses).items():
            with (target / f"{bucket}.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
                for example in examples:
                    handle.write(json.dumps(example, ensure_ascii=False) + "\n")
        print(f"labelled fixtures written to {target}", file=sys.stderr)
    if args.update_doc:
        doc = DOC.read_text(encoding="utf-8")
        block = f"{START}\n_Generated {result['generatedAt']} by scripts/language_qa_benchmark.py._\n\n{table}\n{END}"
        head, _, rest = doc.partition(START)
        _, _, tail = rest.partition(END)
        DOC.write_text(head + block + tail, encoding="utf-8")
        print(f"updated {DOC}", file=sys.stderr)
    baseline = json.loads(args.baseline.read_text(encoding="utf-8")) if args.baseline.exists() else None
    if args.write_baseline:
        args.baseline.parent.mkdir(parents=True, exist_ok=True)
        args.baseline.write_text(json.dumps(bench.baseline_of(result), ensure_ascii=False, indent=1) + "\n",
                                 encoding="utf-8")
        print(f"baseline written to {args.baseline}", file=sys.stderr)
    if args.gate:
        failures = bench.gate(result, baseline)
        for failure in failures:
            print(f"GATE: {failure}", file=sys.stderr)
        print("gate: " + ("FAIL" if failures else "pass"), file=sys.stderr)
        return 1 if failures else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
