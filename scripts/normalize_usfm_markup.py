"""Repair redundant character-style close-and-reopen pairs in USFM files (#203).

Some exports close and reopen a character style clause by clause with the
space *inside* the reopened marker: `many lepers\\wj*\\wj in Israel`. By the
USFM spec that space is marker syntax, so a faithful reader -- usfmtc, Bridge's
`usfm_verse.lift_verse` -- shows "lepersin". The ESV in the local corpus has
2,708 such pairs, 2,674 of them glued to the previous word. Fixing a reference
Bible one finding at a time is not a workflow; this script repairs the source
files before import, with the same detector the in-app check uses
(`tc_ai_bridge.usfm_verse.redundant_style_reopens`): the pair is dropped,
keeping one space when it was glued to the previous word.

Only character styles are touched (`STYLE_MARKERS`). Back-to-back notes
(`\\f*\\f `) and aligned words (`who\\w*\\w soever`, one word on purpose) are
left alone.

Dry run by default -- it prints per-file counts and a few examples. `--write`
rewrites each file in place, keeping its encoding (UTF-8 with or without BOM,
or UTF-16) and its line endings.

    python scripts/normalize_usfm_markup.py <file-or-folder>... [--write]

Not a translation-team tool: a team's own text gets the in-app finding with its
one-click fix, so a human sees each change.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parents[1] / "engine"
sys.path.insert(0, str(ENGINE_DIR))

from tc_ai_bridge.usfm_verse import normalize_style_reopens, redundant_style_reopens  # noqa: E402

_ENCODINGS = ("utf-8-sig", "utf-16", "utf-16-le", "utf-16-be", "utf-8")


def _decode(raw: bytes) -> tuple[str, str] | None:
    """(text, encoding) for the first encoding that yields USFM, or None.

    The encoding returned is the one to write back with: `utf-8-sig` only when
    the file really starts with a BOM (the codec also accepts a file without
    one, and re-encoding that as `utf-8-sig` would *add* a BOM -- which is what
    the first run of this script did to eight ESV files)."""
    for encoding in _ENCODINGS:
        try:
            text = raw.decode(encoding)
        except UnicodeError:
            continue
        if "\\" in text:
            if encoding == "utf-8-sig" and not raw.startswith(b"\xef\xbb\xbf"):
                encoding = "utf-8"
            return text, encoding
    return None


def _usfm_files(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        if path.is_dir():
            files.extend(sorted(p for p in path.rglob("*") if p.suffix.lower() in {".sfm", ".usfm"}))
        elif path.is_file():
            files.append(path)
    return files


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("paths", nargs="+", type=Path, help="USFM files or folders (searched recursively)")
    parser.add_argument("--write", action="store_true", help="rewrite the files in place (default: report only)")
    parser.add_argument("--examples", type=int, default=2, help="examples to show per file (default 2)")
    args = parser.parse_args(argv)

    total_pairs = total_files = 0
    for path in _usfm_files(args.paths):
        decoded = _decode(path.read_bytes())
        if decoded is None:
            print(f"{path}: not UTF-8/UTF-16 USFM, skipped")
            continue
        text, encoding = decoded
        fixes = redundant_style_reopens(text)
        if not fixes:
            continue
        total_pairs += len(fixes)
        total_files += 1
        glued = sum(1 for fix in fixes if fix.replacement)
        print(f"{path}: {len(fixes)} redundant reopen(s), {glued} glued to the previous word")
        for fix in fixes[:args.examples]:
            before = text[max(0, fix.start - 20):fix.start].replace("\n", " ")
            after = text[fix.end:fix.end + 20].replace("\n", " ")
            print(f"    …{before}{fix.original}{after}…  ->  …{before}{fix.replacement}{after}…")
        if args.write:
            repaired = normalize_style_reopens(text)
            # Python decoded "\r\n" as-is (no universal newlines on bytes), so
            # the original line endings are still in the text and survive.
            path.write_bytes(repaired.encode(encoding))
            print(f"    written ({encoding})")

    verb = "repaired" if args.write else "found"
    print(f"\n{total_pairs} redundant reopen(s) {verb} in {total_files} file(s)"
          + ("" if args.write else "; re-run with --write to repair"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
