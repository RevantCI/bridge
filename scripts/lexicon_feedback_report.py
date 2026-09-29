"""Translator decisions on lexicon findings, across projects (layered-rules 5.4).

    python scripts/lexicon_feedback_report.py <project-or-folder> [...] [--out feedback.csv]

Lists every Language QA decision recorded on a `lexicon.*` finding: which
suggestion a translator chose with Use, and which findings were marked false
positive. It is a report for a person to fold into the curated corrections
(`scripts/build_tamil_lexicon.py --curated`). It never changes the lexicon:
learning may improve ranking, never become an unconditional rule
(DECISIONS.md, "The lexicon is never updated from decisions").
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "engine"))

from tc_ai_bridge.tc_project import TranslationCoreProject  # noqa: E402

COLUMNS = ["project", "book", "chapter", "verse", "rule", "originalText", "decision", "chosen",
           "suggestedReplacement", "decidedAt"]


def project_roots(paths: list[str]) -> list[Path]:
    roots: list[Path] = []
    for value in paths:
        path = Path(value)
        if (path / "manifest.json").is_file():
            roots.append(path)
        elif path.is_dir():
            roots.extend(sorted(p.parent for p in path.glob("*/manifest.json")))
    return roots


def feedback_rows(root: Path) -> list[dict[str, str]]:
    project = TranslationCoreProject(root)
    rows = []
    for decision in project.project_qa_decisions():
        issue = decision.get("issue") if isinstance(decision.get("issue"), dict) else {}
        rule = str(issue.get("rule") or "")
        if issue.get("source") != "languageQa" or not rule.startswith("lexicon."):
            continue
        rows.append({
            "project": root.name, "book": project.book_id,
            "chapter": str(decision.get("chapter", "")), "verse": str(decision.get("verse", "")),
            "rule": rule, "originalText": str(issue.get("originalText") or ""),
            "decision": str(decision.get("decision") or ""),
            "chosen": str(issue.get("chosenSuggestion") or ""),
            "suggestedReplacement": str(issue.get("suggestedReplacement") or ""),
            "decidedAt": str(decision.get("modifiedTimestamp") or ""),
        })
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("paths", nargs="+")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    rows = [row for root in project_roots(args.paths) for row in feedback_rows(root)]
    handle = args.out.open("w", encoding="utf-8-sig", newline="") if args.out else sys.stdout
    writer = csv.DictWriter(handle, fieldnames=COLUMNS)
    writer.writeheader()
    writer.writerows(rows)
    if args.out:
        handle.close()
        print(f"{len(rows)} decision(s) -> {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
