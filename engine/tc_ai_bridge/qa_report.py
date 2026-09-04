"""Project-wide QA report: every check Bridge has already run, every issue it
found, and what has happened to each one since -- as flat rows a reviewer can
filter, chart and export, plus a per-book coverage summary for the report
screen's book list.

Reads only persisted state. It never runs a check, never calls a model and
never touches BridgeEngine.project: report_jobs.ReportJobManager builds one
TranslationCoreProject per sibling book on a background thread, the same
isolation project_sweep.py uses, so a 66-book collection cannot block the
single-threaded stdio dispatcher (see BridgeEngine.build_project_report for
the ~800-verse incident that rule comes from). A book that was never opened
(lazy sibling) is reported as not checked without being materialized.

Sources, all already on disk:

  .bridge/progress.json
      which chapters a check job has covered, and the current status of
      every finding id -- the same rollup the dashboard's coverage bar reads,
      so this report and that bar agree on what is still open.
  .apps/translationCoreAI/checkFindings/<book>/<chapter>.json
      the findings those jobs actually produced, written by
      BridgeEngine._on_check_job_complete. Before that snapshot existed only
      whole-book USFM/Names findings survived a job on disk; per-verse
      Wildebeest and local findings were known to the rollup by id alone.
  .apps/translationCoreAI/checkCache.json
      whole-book USFM/Names passes (may be newer than a chapter snapshot).
  .apps/translationCoreAI/qaDecisions/
      decision notes and timestamps behind the rollup's statuses.
  .apps/translationCore/index/{translationNotes,translationWords}/<book>/
      every tN/tW check and its current selection -- read live, not from a
      snapshot, because a check pending at the last job may have been
      selected since.
  .apps/translationCore/checkData/{selections,verseEdits}/<book>/
      who made each selection (a human or "Bridge AI") and whether a later
      Scripture edit made it stale -- walked once per book instead of one
      glob per check (see _SelectionIndex).
  .apps/translationCore/tools/wordAlignment/{completed,invalid}/
      alignment completion/invalid marks.
  .apps/translationCore/alignmentData/<book>/<chapter>.json
      verse lists and alignment work state.
  .apps/translationCoreAI/aiReview/<book>/<chapter>/<verse>.json
      AI review verdicts and proposed corrections.
"""
from __future__ import annotations

import csv
import hashlib
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import VerseAlignment
from .tc_project import TranslationCoreProject, _read_json


REPORT_SCHEMA_VERSION = 1

# Row categories. These are the report's own axis (what the reviewer filters
# by), not QaFinding.category: every deterministic engine -- Wildebeest, the
# USFM checker, Names, and the local editorial checks -- lands in one
# "Greek Room" bucket, with the engine kept on the row for anyone who needs
# the finer split.
CATEGORY_GREEK_ROOM = "greekRoom"
CATEGORY_TN = "translationNotes"
CATEGORY_TW = "translationWords"
CATEGORY_ALIGNMENT = "alignment"
CATEGORY_AI_REVIEW = "aiReview"
CATEGORIES = (CATEGORY_GREEK_ROOM, CATEGORY_TN, CATEGORY_TW, CATEGORY_ALIGNMENT, CATEGORY_AI_REVIEW)

CHECK_FAMILIES = ("greekRoom", "translationNotes", "translationWords", "alignment", "aiReview")
# Families that count toward the collection's pass/fail totals. AI review is
# advisory and never a check that passes or fails on its own.
_SCORED_FAMILIES = ("greekRoom", "translationNotes", "translationWords", "alignment")

# A finding is closed once a human has done anything but leave it open or
# defer it -- identical to reporting._verse_coverage's PASS rule, so the
# report's "resolved" and the dashboard's PASS never disagree.
_UNRESOLVED_STATUSES = {"open", "needs_discussion"}

_SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}

EXPORT_FORMATS = {"csv": ",", "tsv": "\t"}

DEFAULT_EXPORT_COLUMNS = [
    "category", "book", "chapter", "verse", "issue", "explanation", "aiProposal",
    "fixedBy", "result", "status", "severity",
]


def stable_finding_id(*, chapter: str, verse: str, engine: str,
                      check_type: str, disambiguator: str = "") -> str:
    """Must produce exactly what bridge_service._stable_finding_id produces
    (pinned by test_qa_report.test_stable_ids_match_bridge_service): the
    report re-derives the id of a tN/tW pending finding or an alignment
    WA_INVALID finding to look up the decision a reviewer may have recorded
    on it through verse.decide. Duplicated rather than imported because
    bridge_service imports this module."""
    key = f"{chapter}:{verse}:{engine}:{check_type}:{disambiguator}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:20]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _percent(part: int, total: int) -> float:
    return round(100.0 * part / total, 1) if total else 0.0


def _normalize_severity(value: Any) -> str:
    sev = str(value or "medium").lower()
    if sev == "editorial":
        return "low"
    return sev if sev in _SEVERITY_ORDER else "medium"


def _verse_sort_key(chapter: str, verse: str) -> tuple[int, int, str]:
    return (
        int(chapter) if chapter.isdigit() else 999,
        int(verse) if verse.isdigit() else 999,
        verse,
    )


def _safe_read(path: Path) -> Any:
    try:
        return _read_json(path)
    except Exception:
        return None


class _SelectionIndex:
    """One walk of checkData/selections and checkData/verseEdits for a book,
    replacing TranslationCoreProject._latest_state_for_check's per-check glob
    (fine for one verse in the editor; thousands of directory listings for a
    whole Bible)."""

    def __init__(self, project: TranslationCoreProject):
        self.latest_selection: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
        self.latest_edit: dict[tuple[str, str], str] = {}
        root = project.check_dir / "selections" / project.book_id
        if root.is_dir():
            for path in root.rglob("*.json"):
                record = _safe_read(path)
                if not isinstance(record, dict):
                    continue
                ctx = record.get("contextId", {}) if isinstance(record.get("contextId"), dict) else {}
                # The directory is the verse the file was written for --
                # exactly what _state_files_for_verse globs by.
                chapter, verse = path.parent.parent.name, path.parent.name
                key = (
                    chapter, verse, str(ctx.get("checkId", "")),
                    str(ctx.get("tool", "")), str(ctx.get("groupId", "")),
                )
                ts = str(record.get("modifiedTimestamp") or record.get("timestamp") or path.name)
                current = self.latest_selection.get(key)
                if current is None or ts >= str(current.get("_ts", "")):
                    self.latest_selection[key] = {**record, "_ts": ts}
        edits = project.check_dir / "verseEdits" / project.book_id
        if edits.is_dir():
            for path in edits.rglob("*.json"):
                record = _safe_read(path)
                if not isinstance(record, dict):
                    continue
                key = (path.parent.parent.name, path.parent.name)
                ts = str(record.get("modifiedTimestamp", ""))
                if ts > self.latest_edit.get(key, ""):
                    self.latest_edit[key] = ts

    def selection_for(self, chapter: str, verse: str, check_id: str, tool: str, group_id: str) -> dict[str, Any] | None:
        exact = self.latest_selection.get((chapter, verse, check_id, tool, group_id))
        if exact is not None:
            return exact
        # Same relaxation _latest_state_for_check applies when tool/group are
        # blank on the stored record.
        best = None
        for (ch, vs, cid, tl, gid), record in self.latest_selection.items():
            if (ch, vs, cid) != (chapter, verse, check_id):
                continue
            if tl and tl != tool:
                continue
            if gid and gid != group_id:
                continue
            if best is None or record["_ts"] >= best["_ts"]:
                best = record
        return best

    def is_stale(self, chapter: str, verse: str, selection: dict[str, Any] | None) -> bool:
        """Exactly TranslationCoreProject.check_staleness: a selection no
        newer than the latest verse edit is stale."""
        if not selection:
            return False
        edit_ts = self.latest_edit.get((chapter, verse), "")
        return bool(edit_ts) and str(selection.get("_ts", "")) <= edit_ts


def _decision_index(project: TranslationCoreProject) -> dict[tuple[str, str, str], dict[str, Any]]:
    root = project.companion_dir() / "qaDecisions" / project.book_id
    out: dict[tuple[str, str, str], dict[str, Any]] = {}
    if not root.is_dir():
        return out
    for path in root.rglob("*.json"):
        record = _safe_read(path)
        if isinstance(record, dict):
            out[(str(record.get("chapter", "")), str(record.get("verse", "")), str(record.get("issueKey", "")))] = record
    return out


def _alignment_marks(project: TranslationCoreProject) -> dict[tuple[str, str], str]:
    """completed | invalid per verse from tools/wordAlignment, one directory
    walk instead of two stat() calls per verse."""
    marks: dict[tuple[str, str], str] = {}
    base = project.tc_dir / "tools" / "wordAlignment"
    for state in ("completed", "invalid"):  # invalid last: it wins, as word_alignment_state does
        root = base / state
        if not root.is_dir():
            continue
        for path in root.rglob("*.json"):
            marks[(path.parent.name, path.stem)] = state
    return marks


def _ai_reviews(project: TranslationCoreProject) -> dict[tuple[str, str], dict[str, Any]]:
    return {
        (str(r.get("chapter", "")), str(r.get("verse", ""))): r
        for r in project.list_ai_review_results()
    }


class _BookReportBuilder:
    def __init__(self, project: TranslationCoreProject, book_name: str = ""):
        self.project = project
        self.book_id = project.book_id
        self.book_name = book_name or project.summary.book_name
        self.rollup = project.load_progress_rollup()
        self.rollup_chapters: dict[str, Any] = (
            self.rollup.get("chapters", {}) if isinstance(self.rollup.get("chapters"), dict) else {}
        )
        self.decisions = _decision_index(project)
        self.selections = _SelectionIndex(project)
        self.marks = _alignment_marks(project)
        self.reviews = _ai_reviews(project)
        self.rows: list[dict[str, Any]] = []
        self.verses_by_chapter: dict[str, list[str]] = {}

    # -- helpers -------------------------------------------------------------

    def _rollup_verse(self, chapter: str, verse: str) -> dict[str, Any] | None:
        chapter_entry = self.rollup_chapters.get(chapter)
        if not isinstance(chapter_entry, dict):
            return None
        verses = chapter_entry.get("verses", {})
        entry = verses.get(verse) if isinstance(verses, dict) else None
        return entry if isinstance(entry, dict) else None

    def _rollup_status(self, chapter: str, verse: str, finding_id: str) -> str | None:
        entry = self._rollup_verse(chapter, verse)
        statuses = entry.get("findings", {}) if entry else {}
        value = statuses.get(finding_id) if isinstance(statuses, dict) else None
        return str(value) if value is not None else None

    def _chapter_checked(self, chapter: str) -> bool:
        entry = self.rollup_chapters.get(chapter)
        return bool(isinstance(entry, dict) and entry.get("aiChecked"))

    def _verse_checked(self, chapter: str, verse: str) -> bool:
        return self._chapter_checked(chapter) or self._rollup_verse(chapter, verse) is not None

    def _reference(self, chapter: str, verse: str) -> str:
        return f"{self.book_id.upper()} {chapter}:{verse}"

    def _row(self, **fields: Any) -> dict[str, Any]:
        status = str(fields.get("status", "open"))
        resolved = fields.pop("resolved", status not in _UNRESOLVED_STATUSES)
        row = {
            "id": "",
            "category": CATEGORY_GREEK_ROOM,
            "engine": "",
            "checkType": "",
            "severity": "medium",
            "book": self.book_id,
            "bookName": self.book_name,
            "chapter": "",
            "verse": "",
            "reference": "",
            "issue": "",
            "explanation": "",
            "aiProposal": "",
            "aiVerdict": "",
            "status": status,
            "resolution": "resolved" if resolved else "unresolved",
            "result": "pass" if resolved else "fail",
            "fixedBy": "",
            "fixedByDetail": "",
            "decidedAt": "",
            "note": "",
            "selection": "",
        }
        row.update(fields)
        row["reference"] = row["reference"] or self._reference(row["chapter"], row["verse"])
        row["id"] = f"{self.book_id}:{row['id']}"
        return row

    def _decision_fields(self, chapter: str, verse: str, finding_id: str) -> dict[str, Any]:
        record = self.decisions.get((chapter, verse, finding_id))
        if not record:
            return {}
        return {
            "decidedAt": str(record.get("modifiedTimestamp", "")),
            "note": str(record.get("note", "") or ""),
        }

    # -- Greek Room / local findings ------------------------------------------

    def _persisted_findings(self) -> dict[tuple[str, str], dict[str, dict[str, Any]]]:
        """{(chapter, verse): {finding id: finding dict}} from the chapter
        snapshots, then whatever the whole-book USFM/Names cache adds. The
        snapshot wins on a shared id (it carries the verse key the job used,
        which keeps bridged verses like '3-4' intact)."""
        by_verse: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
        for chapter in self.verses_by_chapter:
            snapshot = self.project.load_check_findings_snapshot(chapter)
            for verse, findings in snapshot.items():
                bucket = by_verse.setdefault((chapter, str(verse)), {})
                for finding in findings or []:
                    if isinstance(finding, dict) and finding.get("id"):
                        bucket.setdefault(str(finding["id"]), finding)
        cache = self.project.load_check_cache()
        for section in ("wildebeest", "usfm", "names"):
            for finding in (cache.get(section) or {}).get("findings", []) or []:
                if not isinstance(finding, dict) or not finding.get("id"):
                    continue
                key = (str(finding.get("chapter", "")), str(finding.get("verse", "")))
                by_verse.setdefault(key, {}).setdefault(str(finding["id"]), finding)
        return by_verse

    @staticmethod
    def _finding_category(finding: dict[str, Any]) -> str:
        category = str(finding.get("category", ""))
        if category == "alignment":
            return CATEGORY_ALIGNMENT
        if category == "translation_note":
            return CATEGORY_TN
        if category == "translation_word":
            return CATEGORY_TW
        return CATEGORY_GREEK_ROOM

    def _add_finding_rows(self) -> None:
        for (chapter, verse), findings in self._persisted_findings().items():
            for finding_id, finding in findings.items():
                category = self._finding_category(finding)
                if category in (CATEGORY_TN, CATEGORY_TW):
                    # tN/tW state is read live from the index below; the
                    # snapshot's TC_PENDING/TC_INVALIDATED copy may be stale.
                    continue
                status = self._rollup_status(chapter, verse, finding_id) or str(finding.get("status") or "open")
                resolved = status not in _UNRESOLVED_STATUSES
                explanation = str(finding.get("explanation", "") or "")
                # _qaissue_to_finding joins "title — detail"; Greek Room
                # engines write a plain sentence.
                title, sep, detail = explanation.partition(" — ")
                check_type = str(finding.get("check_type", "") or "")
                fields: dict[str, Any] = dict(
                    id=finding_id,
                    category=category,
                    engine=str(finding.get("engine", "") or ""),
                    checkType=check_type,
                    severity=_normalize_severity(finding.get("severity")),
                    chapter=chapter, verse=verse,
                    issue=title if sep else (check_type or title),
                    explanation=detail if sep else explanation,
                    aiProposal=str(finding.get("suggested_replacement") or ""),
                    status=status,
                    fixedBy="human" if resolved else "",
                    fixedByDetail="reviewer" if resolved else "",
                    note=str(finding.get("human_comment") or ""),
                )
                fields.update(self._decision_fields(chapter, verse, finding_id))
                self.rows.append(self._row(**fields))

    # -- tN/tW checks ---------------------------------------------------------

    def _add_helps_rows(self, tool: str) -> dict[str, int]:
        counts = {"total": 0, "passed": 0, "failed": 0, "pending": 0, "invalidated": 0}
        category = CATEGORY_TN if tool == "translationNotes" else CATEGORY_TW
        default_severity = "medium" if tool == "translationNotes" else "high"
        for entry in self.project._load_index_tool(tool):
            ctx = entry.get("contextId", {}) if isinstance(entry.get("contextId"), dict) else {}
            ref = ctx.get("reference", {}) if isinstance(ctx.get("reference"), dict) else {}
            chapter, verse = str(ref.get("chapter", "")), str(ref.get("verse", ""))
            check_id, group_id = str(ctx.get("checkId", "")), str(ctx.get("groupId", ""))
            quote = str(ctx.get("quoteString", "") or "")
            note = str(ctx.get("occurrenceNote", "") or "")
            selections = entry.get("selections") if isinstance(entry.get("selections"), list) else []
            nothing = bool(entry.get("nothingToSelect", False))
            selection = self.selections.selection_for(chapter, verse, check_id, tool, group_id)
            stale = self.selections.is_stale(chapter, verse, selection)
            invalidated = bool(entry.get("invalidated")) or bool(entry.get("verseEdits"))
            counts["total"] += 1

            if invalidated or stale:
                status, severity = ("invalidated" if invalidated else "stale"), "high"
                counts["invalidated"] += 1
            elif selections:
                status, severity = "selected", default_severity
            elif nothing:
                status, severity = "nothing_to_select", default_severity
            else:
                status, severity = "pending", default_severity
                counts["pending"] += 1

            resolved = status in ("selected", "nothing_to_select")
            fixed_by = fixed_detail = ""
            if resolved:
                username = str((selection or {}).get("username", "")).strip()
                if selection is None:
                    fixed_by, fixed_detail = "human", "translationCore"
                elif username.lower() == "bridge ai":
                    fixed_by, fixed_detail = "machine", "Bridge AI"
                else:
                    fixed_by, fixed_detail = "human", username or "reviewer"

            # A reviewer may have closed the pending/invalidated finding
            # itself through verse.decide (Ignore) -- same id
            # _qaissue_to_finding gives it.
            local_id = stable_finding_id(
                chapter=chapter, verse=verse, engine="translationCore",
                check_type=check_id, disambiguator=group_id,
            )
            decision_fields: dict[str, Any] = {}
            if not resolved:
                decided = self._rollup_status(chapter, verse, local_id)
                if decided and decided not in _UNRESOLVED_STATUSES:
                    resolved = True
                    fixed_by, fixed_detail = "human", "reviewer"
                    decision_fields = {"status": decided, **self._decision_fields(chapter, verse, local_id)}

            counts["passed" if resolved else "failed"] += 1

            review = self.reviews.get((chapter, verse), {})
            ai_proposal = ai_verdict = ""
            check_reviews = review.get("checkReviews", []) if isinstance(review.get("checkReviews"), list) else []
            for check_review in check_reviews:
                if not isinstance(check_review, dict):
                    continue
                if str(check_review.get("check_id", "")) != check_id or str(check_review.get("tool", "")) != tool:
                    continue
                ai_verdict = str(check_review.get("verdict", "") or "")
                ai_proposal = str(check_review.get("suggested_correction", "") or "")
                proposed = [str(x) for x in (check_review.get("proposed_selection_text") or []) if str(x).strip()]
                if not ai_proposal and proposed and not selections:
                    ai_proposal = "Select: " + " / ".join(proposed)
                break

            selected_text = " ".join(
                str(s.get("text", "")).strip() for s in selections
                if isinstance(s, dict) and str(s.get("text", "")).strip()
            )
            issue = f"{group_id}: {quote}" if quote else group_id
            if tool == "translationNotes":
                explanation = note or f"{group_id} / {check_id} has no selection yet."
            else:
                explanation = f"Key term '{group_id}' — source '{quote}'." if quote else f"Key term '{group_id}'."
            if status == "stale":
                explanation = f"{group_id} / {check_id} is stale after a later Scripture edit. {explanation}"
            elif status == "invalidated":
                explanation = f"{group_id} / {check_id} is invalidated. {explanation}"

            fields: dict[str, Any] = dict(
                id=f"{tool}:{chapter}:{verse}:{check_id}:{group_id}",
                category=category,
                engine=tool,
                checkType=group_id,
                severity=severity,
                chapter=chapter, verse=verse,
                issue=issue,
                explanation=explanation,
                aiProposal=ai_proposal,
                aiVerdict=ai_verdict,
                status=status,
                resolved=resolved,
                fixedBy=fixed_by,
                fixedByDetail=fixed_detail,
                selection="nothing to select" if nothing and not selections else selected_text,
                decidedAt=str((selection or {}).get("_ts", "")) if resolved and selection else "",
            )
            fields.update(decision_fields)
            self.rows.append(self._row(**fields))
        return counts

    # -- alignment ------------------------------------------------------------

    def _add_alignment_marks(self) -> None:
        """WA_INVALID for every verse translationCore currently marks invalid
        that no checked chapter's snapshot already reported."""
        seen = {
            (r["chapter"], r["verse"]) for r in self.rows
            if r["category"] == CATEGORY_ALIGNMENT and r["checkType"] == "WA_INVALID"
        }
        detail = "translationCore marks Word Alignment invalid after a target-text edit."
        for (chapter, verse), state in self.marks.items():
            if state != "invalid" or (chapter, verse) in seen:
                continue
            finding_id = stable_finding_id(
                chapter=chapter, verse=verse, engine="translationCore",
                check_type="WA_INVALID", disambiguator=detail,
            )
            status = self._rollup_status(chapter, verse, finding_id) or "open"
            resolved = status not in _UNRESOLVED_STATUSES
            self.rows.append(self._row(
                id=finding_id, category=CATEGORY_ALIGNMENT, engine="translationCore",
                checkType="WA_INVALID", severity="high", chapter=chapter, verse=verse,
                issue="Word Alignment recheck required", explanation=detail,
                status=status, fixedBy="human" if resolved else "",
                fixedByDetail="reviewer" if resolved else "",
                **self._decision_fields(chapter, verse, finding_id),
            ))

    # -- AI review ------------------------------------------------------------

    def _add_ai_review_rows(self) -> dict[str, int]:
        counts = {"current": 0, "stale": 0, "missing": 0}
        for chapter, verses in self.verses_by_chapter.items():
            for verse in verses:
                review = self.reviews.get((chapter, verse))
                if review is None:
                    counts["missing"] += 1
                    continue
                state = self.project.ai_review_cache_status(chapter, verse)
                counts["stale" if state != "current" else "current"] += 1
                if state != "current":
                    # The verse changed after the AI looked; its observations
                    # describe text that no longer exists.
                    continue
                issues = review.get("qaIssues", []) if isinstance(review.get("qaIssues"), list) else []
                for index, issue in enumerate(issues):
                    if not isinstance(issue, dict):
                        continue
                    self.rows.append(self._row(
                        id=f"ai:{chapter}:{verse}:{issue.get('code', '')}:{index}",
                        category=CATEGORY_AI_REVIEW, engine="ai",
                        checkType=str(issue.get("code", "") or ""),
                        severity=_normalize_severity(issue.get("severity")),
                        chapter=chapter, verse=verse,
                        issue=str(issue.get("title", "") or issue.get("code", "")),
                        explanation=str(issue.get("detail", "") or ""),
                        status="open",
                    ))
        return counts

    # -- assembly -------------------------------------------------------------

    def build(self) -> dict[str, Any]:
        project = self.project
        chapters = project.chapters()
        alignment_counts = {"complete": 0, "partial": 0, "untouched": 0, "invalid": 0}
        for chapter in chapters:
            data = project.load_alignment_chapter(chapter)
            verses = [v for v in project.verses(chapter) if v != "front"]
            self.verses_by_chapter[chapter] = verses
            for verse in verses:
                raw = data.get(verse)
                try:
                    state = (
                        project._alignment_work_state(VerseAlignment.from_dict(raw))
                        if isinstance(raw, dict) else "untouched"
                    )
                except Exception:
                    state = "untouched"
                if self.marks.get((chapter, verse)) == "invalid":
                    state = "invalid"
                alignment_counts[state] += 1

        self._add_finding_rows()
        capabilities = self._capabilities()
        helps: dict[str, dict[str, Any]] = {}
        for tool in ("translationNotes", "translationWords"):
            index_dir = project.index_dir / tool / project.book_id
            available = capabilities.get(tool) != "requires-resource-index" and index_dir.is_dir()
            counts = (
                self._add_helps_rows(tool) if available
                else {"total": 0, "passed": 0, "failed": 0, "pending": 0, "invalidated": 0}
            )
            helps[tool] = {**counts, "available": available}
        self._add_alignment_marks()
        ai_counts = self._add_ai_review_rows()

        self.rows.sort(key=lambda r: (
            0 if r["resolution"] == "unresolved" else 1,
            _SEVERITY_ORDER.get(r["severity"], 9),
            _verse_sort_key(r["chapter"], r["verse"]),
            r["category"], r["id"],
        ))

        total_verses = sum(len(v) for v in self.verses_by_chapter.values())
        checked_chapters = [ch for ch in chapters if self._chapter_checked(ch)]
        checked_verses = {
            (ch, vs) for ch, verses in self.verses_by_chapter.items() for vs in verses
            if self._verse_checked(ch, vs)
        }
        failing_gr_verses = {
            (r["chapter"], r["verse"]) for r in self.rows
            if r["category"] == CATEGORY_GREEK_ROOM and r["resolution"] == "unresolved"
        }
        gr_failed = len(checked_verses & failing_gr_verses)
        cache = project.load_check_cache()
        greek_room = {
            "state": self._state(len(checked_verses), total_verses, started=len(checked_verses)),
            "checked": len(checked_verses), "total": total_verses,
            "percent": _percent(len(checked_verses), total_verses),
            "checkedChapters": len(checked_chapters), "chapterCount": len(chapters),
            "engines": {
                "wildebeest": bool(checked_verses),
                "usfm": "usfm" in cache,
                "names": "names" in cache,
            },
            "run": len(checked_verses), "passed": len(checked_verses) - gr_failed, "failed": gr_failed,
        }
        alignment = {
            "state": self._state(
                alignment_counts["complete"], total_verses,
                started=total_verses - alignment_counts["untouched"],
            ),
            **alignment_counts, "total": total_verses,
            "percent": _percent(alignment_counts["complete"], total_verses),
            "run": total_verses - alignment_counts["untouched"],
            "passed": alignment_counts["complete"],
            "failed": alignment_counts["partial"] + alignment_counts["invalid"],
        }
        checks: dict[str, Any] = {"greekRoom": greek_room, "alignment": alignment}
        for tool in ("translationNotes", "translationWords"):
            counts = helps[tool]
            checks[tool] = {
                "state": (
                    "unavailable" if not counts["available"]
                    else self._state(counts["passed"], counts["total"], started=counts["total"])
                ),
                "available": counts["available"],
                "total": counts["total"], "passed": counts["passed"], "failed": counts["failed"],
                "pending": counts["pending"], "invalidated": counts["invalidated"],
                "percent": _percent(counts["passed"], counts["total"]),
                "run": counts["total"],
            }
        checks["aiReview"] = {
            "state": self._state(
                ai_counts["current"], total_verses, started=ai_counts["current"] + ai_counts["stale"],
            ),
            **ai_counts, "total": total_verses,
            "percent": _percent(ai_counts["current"], total_verses),
        }
        check_results = {
            key: sum(int(checks[f].get(key, 0)) for f in _SCORED_FAMILIES)
            for key in ("run", "passed", "failed")
        }
        return {
            "bookId": self.book_id, "bookName": self.book_name, "path": str(project.path),
            "lazy": False, "missing": False, "error": None,
            "chapterCount": len(chapters), "verseCount": total_verses,
            "checks": checks,
            "checkResults": check_results,
            "issues": summarize_rows(self.rows),
            "rows": self.rows,
        }

    @staticmethod
    def _state(done: int, total: int, *, started: int) -> str:
        """not_run until any of the work has happened at all (a tN index with
        every check still pending has been *run* -- it just has no passes),
        complete once everything is done, partial in between."""
        if total <= 0 or started <= 0:
            return "not_run"
        return "complete" if done >= total else "partial"

    def _capabilities(self) -> dict[str, str]:
        data = _safe_read(self.project.path / ".bridge" / "import.json")
        capabilities = data.get("capabilities") if isinstance(data, dict) else None
        return {str(k): str(v) for k, v in capabilities.items()} if isinstance(capabilities, dict) else {}


def summarize_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_category: dict[str, dict[str, int]] = {
        c: {"total": 0, "resolved": 0, "unresolved": 0} for c in CATEGORIES
    }
    by_severity: Counter = Counter()
    by_fixed_by = {"human": 0, "machine": 0, "unresolved": 0}
    resolved = 0
    for row in rows:
        bucket = by_category.setdefault(row["category"], {"total": 0, "resolved": 0, "unresolved": 0})
        bucket["total"] += 1
        if row["resolution"] == "resolved":
            bucket["resolved"] += 1
            resolved += 1
            by_fixed_by["machine" if row["fixedBy"] == "machine" else "human"] += 1
        else:
            bucket["unresolved"] += 1
            by_fixed_by["unresolved"] += 1
            by_severity[row["severity"]] += 1
    return {
        "total": len(rows), "resolved": resolved, "unresolved": len(rows) - resolved,
        "byCategory": by_category, "openBySeverity": dict(by_severity), "byFixedBy": by_fixed_by,
    }


def build_book_qa_report(project: TranslationCoreProject, *, book_name: str = "") -> dict[str, Any]:
    return _BookReportBuilder(project, book_name).build()


def _placeholder_checks() -> dict[str, Any]:
    return {
        "greekRoom": {
            "state": "not_run", "checked": 0, "total": 0, "percent": 0.0,
            "checkedChapters": 0, "chapterCount": 0,
            "engines": {"wildebeest": False, "usfm": False, "names": False},
            "run": 0, "passed": 0, "failed": 0,
        },
        "translationNotes": {
            "state": "not_run", "available": False, "total": 0, "passed": 0, "failed": 0,
            "pending": 0, "invalidated": 0, "percent": 0.0, "run": 0,
        },
        "translationWords": {
            "state": "not_run", "available": False, "total": 0, "passed": 0, "failed": 0,
            "pending": 0, "invalidated": 0, "percent": 0.0, "run": 0,
        },
        "alignment": {
            "state": "not_run", "complete": 0, "partial": 0, "untouched": 0, "invalid": 0,
            "total": 0, "percent": 0.0, "run": 0, "passed": 0, "failed": 0,
        },
        "aiReview": {"state": "not_run", "current": 0, "stale": 0, "missing": 0, "total": 0, "percent": 0.0},
    }


def unopened_book_report(*, book_id: str, book_name: str, path: str, lazy: bool, missing: bool,
                         error: str | None = None) -> dict[str, Any]:
    """A sibling Bridge never materialized (or cannot find, or failed to
    read): nothing has been checked, and saying so costs no I/O."""
    return {
        "bookId": book_id, "bookName": book_name, "path": path,
        "lazy": lazy, "missing": missing, "error": error,
        "chapterCount": 0, "verseCount": 0,
        "checks": _placeholder_checks(),
        "checkResults": {"run": 0, "passed": 0, "failed": 0},
        "issues": summarize_rows([]),
        "rows": [],
    }


_FAMILY_DONE_KEY = {
    "greekRoom": "checked", "translationNotes": "passed", "translationWords": "passed",
    "alignment": "complete", "aiReview": "current",
}


def aggregate_qa_report(project_name: str, book_reports: list[dict[str, Any]]) -> dict[str, Any]:
    """One collection-level payload: per-book summaries (rows stripped) plus
    every row in one list, so the report screen filters/exports across books
    without a second round trip."""
    rows: list[dict[str, Any]] = []
    books: list[dict[str, Any]] = []
    check_results: Counter = Counter()
    families: dict[str, Counter] = {f: Counter() for f in CHECK_FAMILIES}
    for report in book_reports:
        rows.extend(report.get("rows", []))
        books.append({k: v for k, v in report.items() if k != "rows"})
        for key, value in (report.get("checkResults") or {}).items():
            check_results[key] += int(value or 0)
        for family in CHECK_FAMILIES:
            for key, value in (report.get("checks", {}).get(family) or {}).items():
                if isinstance(value, (int, float)) and not isinstance(value, bool) and key != "percent":
                    families[family][key] += value
    checks: dict[str, Any] = {}
    for family, counts in families.items():
        total = int(counts.get("total", 0))
        done = int(counts.get(_FAMILY_DONE_KEY[family], 0))
        checks[family] = {**dict(counts), "percent": _percent(done, total)}
    return {
        "schemaVersion": REPORT_SCHEMA_VERSION,
        "generatedAt": _now(),
        "projectName": project_name,
        "bookCount": len(books),
        "books": books,
        "rows": rows,
        "checks": checks,
        "checkResults": {key: int(check_results.get(key, 0)) for key in ("run", "passed", "failed")},
        "issues": summarize_rows(rows),
        "note": "This report summarizes checks Bridge has already run and decisions already recorded. "
                "It does not itself approve Scripture, terminology, or publication.",
    }


def write_report_rows(output_path: str | Path, fmt: str, rows: list[dict[str, Any]],
                      columns: list[dict[str, str]] | None = None) -> dict[str, Any]:
    """Write already-filtered rows as CSV/TSV. UTF-8 with a BOM so Excel on
    Windows opens Tamil/Odia/Hebrew text as text, same as
    reporting.ReportService._write_csv."""
    delimiter = EXPORT_FORMATS.get(str(fmt).lower())
    if delimiter is None:
        raise ValueError(f"Unsupported export format '{fmt}'. Use csv or tsv.")
    if not isinstance(rows, list):
        raise ValueError("rows must be a list.")
    keys = [str(c.get("key", "")) for c in (columns or []) if isinstance(c, dict) and c.get("key")]
    if not keys:
        keys = list(DEFAULT_EXPORT_COLUMNS)
    labels = {
        str(c.get("key")): str(c.get("label") or c.get("key"))
        for c in (columns or []) if isinstance(c, dict)
    }
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle, delimiter=delimiter, lineterminator="\r\n")
        writer.writerow([labels.get(k, k) for k in keys])
        for row in rows:
            if not isinstance(row, dict):
                continue
            writer.writerow(["" if row.get(k) is None else str(row.get(k)) for k in keys])
    return {"written": True, "path": str(path), "rows": len(rows), "format": str(fmt).lower()}
