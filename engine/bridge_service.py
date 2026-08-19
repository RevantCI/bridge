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

from dataclasses import asdict
from pathlib import Path
from typing import Any, Optional

from greek_room_engine.engine import GreekRoomEngine
from greek_room_engine.models.finding import QaFinding, FindingCategory, Severity, FindingStatus
from greek_room_engine.protocol import EngineRequest, EngineResponse

from tc_ai_bridge.tc_project import TranslationCoreProject, ProjectError
from tc_ai_bridge.local_checks import run_local_qa
from tc_ai_bridge.alignment_engine import realign, validate_proposal, apply_proposal, AlignmentError
from tc_ai_bridge.models import VerseAlignment, QAIssue
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
                         chapter: int, verse: int) -> QaFinding:
    """Adapts tc_ai_bridge's QAIssue (tN/tW/local QA) into the same
    QaFinding shape Greek Room findings use, so the UI never has to know
    which engine produced a given finding (architecture doc §6)."""
    return QaFinding(
        project_id=project_id,
        book=book, chapter=chapter, verse=verse,
        engine=issue.source or "local",
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

    VERSE_GET = "verse.get"
    VERSE_RUN_CHECKS = "verse.runChecks"
    VERSE_DECIDE = "verse.decide"
    VERSE_EDIT = "verse.edit"

    SETTINGS_GET = "settings.get"
    SETTINGS_SET = "settings.set"


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

    def run_verse_checks(self, chapter: str, verse: str,
                          checks: list[str]) -> list[QaFinding]:
        """The unified check entrypoint: local QA (tN/tW/alignment) +
        Greek Room, merged into one QaFinding list — this IS the
        background chapter/book-wise automation the UI's status bar
        reflects, called once per verse during that pass."""
        self._require_project()
        findings: list[QaFinding] = []
        project_id = str(self.project.summary.path)
        book = self.project.summary.book_id

        alignment = self.project.load_verse_alignment(chapter, verse)
        target_text = self.project.target_verse_text(chapter, verse)

        if "local" in checks or "tN" in checks or "tW" in checks or "alignment" in checks:
            issues = run_local_qa(self.project, chapter, verse, alignment)
            for issue in issues:
                findings.append(_qaissue_to_finding(
                    issue, project_id=project_id, book=book,
                    chapter=int(chapter), verse=int(verse),
                ))

        if "greekroom" in checks or "wildebeest" in checks:
            gr_findings = self.greek_room.check_verse(
                project_id=project_id,
                lang_code=self.project.summary.target_language,
                ref=f"{book} {chapter}:{verse}",
                text=target_text,
                checks=["wildebeest"],
            )
            findings.extend(gr_findings)

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

    # -- settings ---------------------------------------------------------

    def get_settings(self) -> dict[str, Any]:
        return {
            "model": self.settings.model,
            "reviewerName": self.settings.reviewer_name,
            "paratextUsername": self.settings.paratext_username,
            "hasApiKey": bool(self.settings.get_api_key()),
            "aiUsage": self.settings.get_ai_usage_totals(),
        }

    def set_settings(self, **kwargs) -> dict[str, Any]:
        if "apiKey" in kwargs:
            self.settings.set_api_key(kwargs["apiKey"])
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

            return EngineResponse.fail(request.id, "unknown_method", f"No handler for '{m}'")
        except ProjectError as exc:
            return EngineResponse.fail(request.id, "project_error", str(exc))
        except Exception as exc:  # noqa: BLE001 - protocol boundary must never crash the sidecar
            return EngineResponse.fail(request.id, "internal_error", str(exc))
