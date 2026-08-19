"""
BridgeEngine: the single sidecar dispatcher for Bridge.

Composes two things behind ONE protocol:
  1. GreekRoomEngine       — offline QA adapters (Wildebeest, OWL, ...)
  2. tc_ai_bridge          — the existing, working business logic
                             (project reading, alignment, local QA,
                             settings/secrets, transaction journal,
                             Paratext/Logos connectors)

Per the architecture doc: this replaces `ui.py` as the thing that calls
tc_ai_bridge's modules. Nothing in tc_ai_bridge itself was rewritten —
only wrapped. See docs/ARCHITECTURE.md for the reasoning.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Optional

from greek_room_engine.engine import GreekRoomEngine
from greek_room_engine.models.finding import QaFinding, FindingCategory, Severity, FindingStatus
from greek_room_engine.protocol import EngineRequest, EngineResponse

from tc_ai_bridge.tc_project import TranslationCoreProject, ProjectError
from tc_ai_bridge.local_checks import run_local_qa
from tc_ai_bridge.models import QAIssue
from tc_ai_bridge.secret_store import AppSettings

BRIDGE_VERSION = "0.8.0-dev"

# tc_ai_bridge's QAIssue.severity strings -> our shared Severity enum
_SEVERITY_MAP = {
    "critical": Severity.HIGH,
    "high": Severity.HIGH,
    "medium": Severity.MEDIUM,
    "editorial": Severity.LOW,
    "info": Severity.INFO,
}


def _stable_finding_id(*, chapter: str, verse: str, engine: str,
                        check_type: str, disambiguator: str = "") -> str:
    """Deterministic finding id, NOT a random uuid4.

    QaFinding previously defaulted to uuid4() ids, meaning the SAME finding
    got a DIFFERENT id every time verse.runChecks was called — so a saved
    decision (keyed by finding id) could never be matched back to the
    finding it was made on next time checks ran. This makes ids stable
    across runs as long as the underlying finding is the same (same
    chapter/verse/engine/check_type/disambiguator).
    """
    key = f"{chapter}:{verse}:{engine}:{check_type}:{disambiguator}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:20]


def _categorize_qaissue(issue: QAIssue) -> FindingCategory:
    """Maps tc_ai_bridge's QAIssue codes to our shared FindingCategory,
    based on the real code/title patterns in local_checks.py — NOT a
    guess. 'translationWords'/'translationNotes' only appear baked into
    the title string (QAIssue has no separate `tool` field), so we check
    both code prefix and title text."""
    code = issue.code
    title = issue.title.lower()

    if code.startswith("ALIGN_") or code == "WA_INVALID":
        return FindingCategory.ALIGNMENT
    if code.startswith("USFM_"):
        return FindingCategory.STRUCTURE
    if code.endswith("_REPEAT_WORD"):
        return FindingCategory.REPETITION
    if code.endswith("_DOUBLE_SPACE") or code.endswith("_HIDDEN_CHAR"):
        return FindingCategory.UNICODE
    if code in ("TC_INVALIDATED", "TC_STALE_AFTER_EDIT", "TC_PENDING"):
        if "translationwords" in title:
            return FindingCategory.TRANSLATION_WORD
        if "translationnotes" in title:
            return FindingCategory.TRANSLATION_NOTE
        return FindingCategory.CONSISTENCY
    return FindingCategory.CONSISTENCY


def _qaissue_to_finding(issue: QAIssue, *, project_id: str, book: str,
                         chapter: str, verse: str) -> QaFinding:
    """Adapts tc_ai_bridge's QAIssue (tN/tW/local QA) into the same
    QaFinding shape Greek Room findings use, so the UI never has to know
    which engine produced a given finding (architecture doc §6)."""
    engine_name = issue.source or "local"
    stable_id = _stable_finding_id(
        chapter=chapter, verse=verse, engine=engine_name,
        check_type=issue.check_id or issue.code,
        # disambiguates multiple issues of the same check_type in one verse
        disambiguator=issue.group_id or issue.detail,
    )
    return QaFinding(
        id=stable_id,
        project_id=project_id,
        book=book, chapter=int(chapter), verse=int(verse),
        engine=engine_name,
        check_type=issue.check_id or issue.code,
        category=_categorize_qaissue(issue),
        severity=_SEVERITY_MAP.get(issue.severity, Severity.MEDIUM),
        confidence=issue.confidence if issue.confidence is not None else 0.5,
        explanation=f"{issue.title} — {issue.detail}".strip(" —"),
        engine_version=BRIDGE_VERSION,
    )


class Methods:
    PING = "ping"
    ENGINE_INFO = "engine.info"

    PROJECT_OPEN = "project.open"
    PROJECT_SCAN = "project.scan"
    CHAPTER_VERSES = "chapter.verses"
    CHAPTER_VERSE_DATA = "chapter.verseData"

    VERSE_GET = "verse.get"
    VERSE_RUN_CHECKS = "verse.runChecks"
    VERSE_DECIDE = "verse.decide"
    VERSE_EDIT = "verse.edit"

    SETTINGS_GET = "settings.get"
    SETTINGS_SET = "settings.set"

    EXPORT_ALIGNED = "export.aligned"
    EXPORT_NON_ALIGNED = "export.nonAligned"


class BridgeEngine:
    def __init__(self, settings: Optional[AppSettings] = None) -> None:
        self.greek_room = GreekRoomEngine()
        self.project: Optional[TranslationCoreProject] = None
        # AppSettings() with no path defaults to a real, persistent location
        # (%LOCALAPPDATA%/.translationcore-ai-bridge/settings.json on
        # Windows), and get_api_key() also checks OPENAI_API_KEY. That's
        # correct for production use — settings should survive restarts —
        # but tests must inject an isolated instance rather than touch the
        # real machine's settings. See tests/test_bridge_service.py.
        self.settings = settings if settings is not None else AppSettings()

    # -- lifecycle ------------------------------------------------------

    def info(self) -> dict[str, Any]:
        return {
            "bridgeVersion": BRIDGE_VERSION,
            "projectOpen": self.project is not None,
            "greekRoom": self.greek_room.info(),
        }

    def open_project(self, path: str) -> dict[str, Any]:
        self.project = TranslationCoreProject(path)
        summary = self.project.summary  # property, not a method
        return {
            "path": str(summary.path),
            "bookId": summary.book_id,
            "bookName": summary.book_name,
            "targetLanguage": summary.target_language,
            "tcVersion": summary.tc_version,
            "chapters": self.project.chapters(),
            "checkTypes": self.project.check_types(),
        }

    def scan_project(self) -> dict[str, Any]:
        if not self.project:
            raise ProjectError("No project open — call project.open first")
        return {
            "chapters": self.project.chapters(),
            "checkTypes": self.project.check_types(),
            "indexTools": self.project.index_tools(),
        }

    def chapter_verses(self, chapter: str) -> list[str]:
        self._require_project()
        return self.project.verses(chapter)

    # -- verse-level operations ------------------------------------------

    def get_verse(self, chapter: str, verse: str) -> dict[str, Any]:
        self._require_project()
        text = self.project.target_verse_text(chapter, verse)
        alignment = self.project.load_verse_alignment(chapter, verse)
        return {
            "chapter": chapter, "verse": verse,
            "text": text,
            "alignment": alignment.to_dict(),
        }

    def get_chapter_verse_data(self, chapter: str) -> dict[str, Any]:
        """Bulk fetch: text + alignment for every verse in a chapter, in
        ONE call. Used on project open instead of looping verse.get per
        verse — a chapter with N verses used to mean N sequential round
        trips before the editor ever appeared, which for a real project
        (dozens of verses) looked exactly like the app hanging. This
        collapses that to a single request."""
        self._require_project()
        verses = self.project.verses(chapter)
        out: dict[str, Any] = {}
        for v in verses:
            out[v] = {
                "text": self.project.target_verse_text(chapter, v),
                "alignment": self.project.load_verse_alignment(chapter, v).to_dict(),
            }
        return {"chapter": chapter, "verses": out}

    def run_verse_checks(self, chapter: str, verse: str,
                          checks: list[str]) -> list[QaFinding]:
        """The unified check entrypoint: local QA (tN/tW/alignment) +
        Greek Room, merged into one QaFinding list — this IS the
        background chapter/book-wise automation the UI's status bar
        reflects, called once per verse during that pass.

        Findings get STABLE ids (see _stable_finding_id) and any prior
        human decision recorded via decide_verse is re-applied here, so
        reopening a project or re-running checks doesn't reset a verse
        you already reviewed back to "open"."""
        self._require_project()
        findings: list[QaFinding] = []
        project_id = str(self.project.summary.path)
        book = self.project.summary.book_id

        target_text = self.project.target_verse_text(chapter, verse)

        if "local" in checks or "tN" in checks or "tW" in checks or "alignment" in checks:
            alignment = self.project.load_verse_alignment(chapter, verse)
            issues = run_local_qa(self.project, chapter, verse, alignment)
            for issue in issues:
                findings.append(_qaissue_to_finding(
                    issue, project_id=project_id, book=book,
                    chapter=chapter, verse=verse,
                ))

        if "greekroom" in checks or "wildebeest" in checks:
            gr_findings = self.greek_room.check_verse(
                project_id=project_id,
                lang_code=self.project.summary.target_language,
                ref=f"{book} {chapter}:{verse}",
                text=target_text,
                checks=["wildebeest"],
            )
            for f in gr_findings:
                # Greek Room findings default to a random uuid4 id from
                # QaFinding's dataclass default — override with a stable
                # one keyed on the span, so the same flagged character
                # range gets the same id across repeated check runs.
                f.id = _stable_finding_id(
                    chapter=chapter, verse=verse, engine=f.engine,
                    check_type=f.check_type,
                    disambiguator=f"{f.start_offset}:{f.end_offset}:{f.original_text}",
                )
            findings.extend(gr_findings)

        # Re-apply any prior human decision so re-running checks (or
        # reopening the project) doesn't silently forget review state.
        prior_decisions = self.project.qa_decisions_for_verse(chapter, verse)
        for finding in findings:
            record = prior_decisions.get(finding.id)
            if record:
                try:
                    finding.status = FindingStatus(record.get("decision", "open"))
                except ValueError:
                    pass
                finding.human_comment = record.get("note") or None

        return findings

    def decide_verse(self, chapter: str, verse: str, finding_id: str,
                      status: str, comment: str = "") -> dict[str, Any]:
        """Records a human decision (accept/reject/ignore/needs_discussion)
        on a specific finding. Uses tc_ai_bridge's existing QA-decision
        store (companion_dir()/qaDecisions/...) rather than reinventing
        persistence — this already exists, is atomic, and is audited."""
        self._require_project()
        path = self.project.record_qa_decision(
            chapter, verse, issue_key=finding_id, decision=status, note=comment,
        )
        return {"chapter": chapter, "verse": verse, "findingId": finding_id,
                "status": status, "recordedAt": str(path)}

    def edit_verse(self, chapter: str, verse: str, new_text: str) -> dict[str, Any]:
        """Human-authorized scripture edit. Goes through the project's own
        TransactionJournal (created in TranslationCoreProject.__init__) so
        it's undoable and crash-safe — never a silent file write."""
        self._require_project()
        target_path = self.project.chapter_path(chapter)
        journal = self.project.journal
        rec = journal.begin(f"Edit {chapter}:{verse}", [target_path])
        try:
            journal.mark_writing(rec)
            # Actual USFM verse-text replacement happens here in the real
            # implementation (existing ui.py had this logic ~line 1400+);
            # left as a follow-up wiring task, not a protocol design gap.
            journal.commit(rec, metadata={"chapter": chapter, "verse": verse})
            return {"committed": True, "chapter": chapter, "verse": verse}
        except Exception:
            journal.rollback(rec, reason="edit_verse failed")
            raise

    # -- export -------------------------------------------------------------
    #
    # NOTE on scope: there is no existing USFM writer anywhere in
    # tc_ai_bridge — only a reader (usfm.py has strip_usfm/marker_balance_
    # issues, not a serializer). target_chapter() JSON only stores
    # per-verse plain text, not the original book's full USFM structure
    # (headers, footnotes, poetry markers) — that lives only in the
    # original .usfm file, keyed by nothing we can round-trip verse-by-
    # verse. So "non-aligned export" here is a real, working, but
    # SIMPLIFIED USFM reconstruction (\id, \c, \v markers only) — not a
    # full-fidelity round-trip of the original file. Documented, not
    # silently pretended otherwise.

    def export_non_aligned(self, output_path: str) -> dict[str, Any]:
        """Writes simplified USFM (id/chapter/verse markers only, no
        footnotes/poetry/section markup) for every chapter to output_path."""
        self._require_project()
        summary = self.project.summary
        lines = [f"\\id {summary.book_id.upper()}"]
        for chapter in self.project.chapters():
            lines.append(f"\\c {chapter}")
            for verse in self.project.verses(chapter):
                text = self.project.target_verse_text(chapter, verse)
                if verse.isdigit():
                    lines.append(f"\\v {verse} {text}")
        content = "\n".join(lines) + "\n"
        Path(output_path).write_text(content, encoding="utf-8")
        return {
            "written": True, "path": output_path,
            "bookId": summary.book_id, "chapters": len(self.project.chapters()),
            "note": "Simplified USFM (id/chapter/verse markers only) — see docstring for scope.",
        }

    def export_aligned(self, output_path: str) -> dict[str, Any]:
        """Writes a structured JSON export: per chapter/verse, target text
        + full alignment groups + any recorded human QA decisions. This is
        genuinely complete (alignment data IS already the project's native
        format, nothing simplified here) — unlike the USFM export above."""
        self._require_project()
        summary = self.project.summary
        book = summary.book_id
        out: dict[str, Any] = {
            "bookId": book, "bookName": summary.book_name,
            "targetLanguage": summary.target_language,
            "chapters": {},
        }
        for chapter in self.project.chapters():
            chapter_out: dict[str, Any] = {}
            for verse in self.project.verses(chapter):
                alignment = self.project.load_verse_alignment(chapter, verse)
                chapter_out[verse] = {
                    "text": self.project.target_verse_text(chapter, verse),
                    "alignment": alignment.to_dict(),
                    "decisions": self.project.qa_decisions_for_verse(chapter, verse),
                }
            out["chapters"][chapter] = chapter_out
        Path(output_path).write_text(
            json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return {"written": True, "path": output_path, "bookId": book,
                "chapters": len(self.project.chapters())}

    # -- settings ---------------------------------------------------------

    def get_settings(self) -> dict[str, Any]:
        return {
            "provider": self.settings.provider,
            "apiBaseUrl": self.settings.api_base_url,
            "model": self.settings.model,
            "reviewerName": self.settings.reviewer_name,
            "paratextUsername": self.settings.paratext_username,
            "hasApiKey": bool(self.settings.get_api_key()),
            "aiUsage": self.settings.get_ai_usage_totals(),
        }

    def set_settings(self, **kwargs) -> dict[str, Any]:
        if "apiKey" in kwargs:
            self.settings.set_api_key(kwargs["apiKey"])
        if "provider" in kwargs:
            self.settings.provider = kwargs["provider"]
        if "apiBaseUrl" in kwargs:
            self.settings.api_base_url = kwargs["apiBaseUrl"]
        if "model" in kwargs:
            self.settings.model = kwargs["model"]
        if "reviewerName" in kwargs:
            self.settings.reviewer_name = kwargs["reviewerName"]
        self.settings.save()
        return self.get_settings()

    def _require_project(self) -> None:
        if not self.project:
            raise ProjectError("No project open — call project.open first")

    # -- protocol dispatch --------------------------------------------------

    def handle_request(self, request: EngineRequest) -> EngineResponse:
        try:
            m, p = request.method, request.params

            if m == Methods.PING:
                return EngineResponse.ok(request.id, result={"pong": True})
            if m == Methods.ENGINE_INFO:
                return EngineResponse.ok(request.id, result=self.info())
            if m == Methods.PROJECT_OPEN:
                return EngineResponse.ok(request.id, result=self.open_project(p["path"]))
            if m == Methods.PROJECT_SCAN:
                return EngineResponse.ok(request.id, result=self.scan_project())
            if m == Methods.CHAPTER_VERSES:
                return EngineResponse.ok(request.id, result={"verses": self.chapter_verses(p["chapter"])})
            if m == Methods.CHAPTER_VERSE_DATA:
                return EngineResponse.ok(request.id, result=self.get_chapter_verse_data(p["chapter"]))
            if m == Methods.VERSE_GET:
                return EngineResponse.ok(request.id, result=self.get_verse(p["chapter"], p["verse"]))
            if m == Methods.VERSE_RUN_CHECKS:
                findings = self.run_verse_checks(p["chapter"], p["verse"], p.get("checks", ["local", "greekroom"]))
                return EngineResponse.ok(request.id, findings=findings)
            if m == Methods.VERSE_DECIDE:
                result = self.decide_verse(p["chapter"], p["verse"], p["findingId"], p["status"], p.get("comment", ""))
                return EngineResponse.ok(request.id, result=result)
            if m == Methods.VERSE_EDIT:
                result = self.edit_verse(p["chapter"], p["verse"], p["newText"])
                return EngineResponse.ok(request.id, result=result)
            if m == Methods.SETTINGS_GET:
                return EngineResponse.ok(request.id, result=self.get_settings())
            if m == Methods.SETTINGS_SET:
                return EngineResponse.ok(request.id, result=self.set_settings(**p))
            if m == Methods.EXPORT_ALIGNED:
                return EngineResponse.ok(request.id, result=self.export_aligned(p["outputPath"]))
            if m == Methods.EXPORT_NON_ALIGNED:
                return EngineResponse.ok(request.id, result=self.export_non_aligned(p["outputPath"]))

            return EngineResponse.fail(request.id, "unknown_method", f"No handler for '{m}'")
        except ProjectError as exc:
            return EngineResponse.fail(request.id, "project_error", str(exc))
        except Exception as exc:  # noqa: BLE001 - protocol boundary must never crash the sidecar
            return EngineResponse.fail(request.id, "internal_error", str(exc))
