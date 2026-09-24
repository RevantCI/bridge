"""Build the ta-irv corpus lexicon (layered-rules Phase 5.1).

    python scripts/build_tamil_lexicon.py --irv-dir "C:/…/IRV Tamil" [--curated DIR_OR_CSV …] [--top N]

Writes engine/tc_ai_bridge/language_packs/ta-irv/lexicon.json:

- `forms`: word -> [corpus count, number of books], for every word seen at
  least MIN_LISTED_COUNT times (bounded at `--top`). A word absent from the
  list is rare in the corpus -- which is exactly what the lexicon rule asks.
- `common` and `buckets`: the words frequent enough to be suggested (count >=
  COMMON_MIN) and their one-cluster deletion neighbours, precomputed here so
  the engine never rebuilds them at load (performance contract).
- `deprecated`: wrong -> right from the Round 2 / Pass 3 reports' positive
  typo rows (`--curated`), kept only where the wrong form is rare in the
  corpus and the right form is attested. A hard rule; the frequency table is
  evidence only.

Tokens are the runtime's own: imported_verse_text -> lift_inline_usfm ->
language_qa.word_occurrences (NFC keys; the text is never rewritten).
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "engine"))

from tc_ai_bridge import language_qa_benchmark as bench  # noqa: E402
from tc_ai_bridge.language_packs.lexicon import (  # noqa: E402
    COMMON_MIN, LEXICON_VERSION, MIN_LISTED_COUNT, deletion_keys,
)
from tc_ai_bridge.language_packs.tamil_distance import tamil_distance  # noqa: E402
from tc_ai_bridge.language_qa import lift_inline_usfm, word_occurrences  # noqa: E402
from tc_ai_bridge.project_import import imported_verse_text, parse_scripture_file  # noqa: E402

OUT = REPO / "engine" / "tc_ai_bridge" / "language_packs" / "ta-irv" / "lexicon.json"


def corpus_counts(irv_dir: Path) -> tuple[collections.Counter, dict[str, set], int, int, list[str]]:
    counts: collections.Counter = collections.Counter()
    books: dict[str, set] = collections.defaultdict(set)
    verses = tokens = 0
    book_ids = []
    for sfm in sorted(irv_dir.glob("*.SFM")):
        book = parse_scripture_file(sfm)
        book_ids.append(book.book_id)
        for items in book.chapters.values():
            for raw in items.values():
                lifted, _ = lift_inline_usfm(imported_verse_text(raw))
                if lifted is None:
                    continue
                verses += 1
                for word, _, _ in word_occurrences(lifted.visible):
                    counts[word] += 1
                    books[word].add(book.book_id)
                    tokens += 1
    return counts, books, verses, tokens, book_ids


def curated_pairs(paths: list[str], counts: collections.Counter) -> tuple[dict[str, str], dict[str, int]]:
    """wrong -> right from positive typo rows whose Original and Suggested
    differ in exactly one word; a conflicting or unsafe pair is dropped."""
    files: list[Path] = []
    for value in paths:
        path = Path(value)
        # Top level only, as the benchmark reads them: v1-before-split/ is superseded.
        files.extend(sorted(path.glob("*_Issues.csv")) if path.is_dir() else [path])
    rows = bench.load_review_rows(files)
    bench.classify(rows)
    proposals: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    stats = collections.Counter()
    for row in rows:
        if row.label != "positive" or row.bucket != "typo":
            continue
        before = [w for w, _, _ in word_occurrences(row.original)]
        after = [w for w, _, _ in word_occurrences(row.suggestion)]
        if len(before) != len(after):
            stats["different word count"] += 1
            continue
        changed = [(a, b) for a, b in zip(before, after) if a != b]
        if len(changed) != 1:
            stats["not one word"] += 1
            continue
        proposals[changed[0][0]][changed[0][1]] += 1
    deprecated = {}
    for wrong, rights in sorted(proposals.items()):
        if len(rights) > 1:
            stats["reviews disagree"] += 1
            continue
        right = next(iter(rights))
        if counts[wrong] > 2:
            stats["wrong form is common in the corpus"] += 1
            continue
        if counts[right] < 1:
            stats["right form unattested"] += 1
            continue
        if tamil_distance(wrong, right) > 2.0:
            stats["too far apart to be a typo"] += 1
            continue
        deprecated[wrong] = right
    return deprecated, dict(stats)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--irv-dir", required=True, type=Path)
    parser.add_argument("--curated", nargs="*", default=[])
    parser.add_argument("--top", type=int, default=60_000, help="bound on listed forms (most frequent first)")
    args = parser.parse_args()
    counts, books, verses, tokens, book_ids = corpus_counts(args.irv_dir)
    listed = [w for w, c in counts.most_common() if c >= MIN_LISTED_COUNT][:args.top]
    common = sorted(w for w in listed if counts[w] >= COMMON_MIN)
    index = {w: i for i, w in enumerate(common)}
    buckets: dict[str, list[int]] = collections.defaultdict(list)
    for word in common:
        for key in {word, *deletion_keys(word)}:
            buckets[key].append(index[word])
    deprecated, curated_stats = curated_pairs(args.curated, counts) if args.curated else ({}, {})
    data = {
        "version": LEXICON_VERSION,
        "corpus": {"books": len(book_ids), "verseCount": verses, "tokenCount": tokens,
                   "distinctForms": len(counts), "listedForms": len(listed),
                   "minListedCount": MIN_LISTED_COUNT, "commonMin": COMMON_MIN},
        "forms": {w: [counts[w], len(books[w])] for w in listed},
        "common": common,
        "buckets": {k: v for k, v in sorted(buckets.items())},
        "deprecated": deprecated,
        "curatedStats": curated_stats,
    }
    OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{len(book_ids)} books, {verses} verses, {tokens} tokens, {len(counts)} distinct forms", file=sys.stderr)
    print(f"listed {len(listed)} (count >= {MIN_LISTED_COUNT}), common {len(common)} (>= {COMMON_MIN}), "
          f"{len(buckets)} bucket keys, {len(deprecated)} deprecated pairs {curated_stats}", file=sys.stderr)
    print(f"{OUT} {OUT.stat().st_size / 2**20:.2f} MB", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
