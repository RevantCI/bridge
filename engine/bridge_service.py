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

import atexit
import copy
import hashlib
import json
import os
import re
import shutil
import threading
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable, Optional

from greek_room_engine.engine import GreekRoomEngine
from greek_room_engine.adapters.usfm_adapter import UsfmCheckerCancelled, UsfmCheckerError
from greek_room_engine.adapters.names_adapter import NamesCheckError
from greek_room_engine.models.finding import QaFinding, FindingCategory, Severity, FindingStatus
from greek_room_engine.protocol import EngineRequest, EngineResponse

from tc_ai_bridge.tc_project import TranslationCoreProject, ProjectError
from tc_ai_bridge.project_import import (
    apply_resource_materialization,
    collection_projects,
    ensure_bridge_original_language,
    import_source,
    inspect_import,
    materialize_lazy_project,
)
from tc_ai_bridge.original_language_resources import resource_inventory
from tc_ai_bridge.project_registry import ProjectRegistry, source_fingerprints
from tc_ai_bridge.local_checks import run_local_qa
from tc_ai_bridge.alignment_engine import (
    AlignmentError, apply_proposal, make_inventory, realign, unalign_bottom,
    validate_preparation_proposal,
)
from tc_ai_bridge.aligned_usfm import AlignedUsfmError, render_aligned_verse
from tc_ai_bridge.alignment_reliability import structural_issues
from tc_ai_bridge.ai_client import AIError, OpenAIResponsesClient, Transport
from tc_ai_bridge.knowledge_base import KnowledgeBaseError
from tc_ai_bridge.paratext_connector import ParatextConnectorClient, ParatextConnectorError
from tc_ai_bridge.logos_connector import LogosConnectorClient, LogosConnectorError
from tc_ai_bridge.models import QAIssue, TokenRef, VerseAlignment
from tc_ai_bridge.secret_store import AppSettings
from tc_ai_bridge.resource_materializer import materialize_book_checks
from tc_ai_bridge.usfm import whitespace_tokens
from tc_ai_bridge import versification as versification_tool
from tc_ai_bridge import alignment_statistics as corpus_stats_tool
from check_jobs import (
    CheckJobConflict,
    CheckJobError,
    CheckJobManager,
    CheckJobNotFound,
    CheckJobSpec,
)
from ai_review_jobs import (
    AIReviewJobConflict,
    AIReviewJobError,
    AIReviewJobManager,
    AIReviewJobNotFound,
    AIReviewJobSpec,
)

BRIDGE_VERSION = "0.8.0-beta.9"

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
        # USFM permits verse bridges (for example 3-4) and segments (3a).
        # QaFinding currently stores numeric anchors, while the project/UI
        # retain the exact string reference. Use the first numeric component
        # so valid Scripture does not crash the checking pass.
        book=book,
        chapter=int(next(iter(re.findall(r"\d+", str(chapter))), "0")),
        verse=int(next(iter(re.findall(r"\d+", str(verse))), "0")),
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
    PROJECT_LIST = "project.list"
    PROJECT_FORGET = "project.forget"
    PROJECT_DELETE = "project.delete"
    PROJECT_SCAN = "project.scan"
    PROJECT_INSPECT_IMPORT = "project.inspectImport"
    PROJECT_IMPORT = "project.import"
    CHAPTER_VERSES = "chapter.verses"
    CHAPTER_VERSE_DATA = "chapter.verseData"

    CHECKS_START = "checks.start"
    CHECKS_STATUS = "checks.status"
    CHECKS_CANCEL = "checks.cancel"
    CHECKS_RETRY = "checks.retry"

    VERSE_GET = "verse.get"
    VERSE_RUN_CHECKS = "verse.runChecks"
    VERSE_DECIDE = "verse.decide"
    VERSE_EDIT = "verse.edit"

    CHECK_LIST_FOR_VERSE = "check.listForVerse"
    CHECK_VALIDATE_SELECTION = "check.validateSelection"
    CHECK_SAVE_SELECTION = "check.saveSelection"
    CHECK_CLEAR_SELECTION = "check.clearSelection"

    ALIGNMENT_GET = "alignment.get"
    ALIGNMENT_STATUS = "alignment.status"
    ALIGNMENT_REALIGN = "alignment.realign"
    ALIGNMENT_UNALIGN = "alignment.unalign"
    ALIGNMENT_SAVE = "alignment.save"
    ALIGNMENT_COMPLETE = "alignment.complete"
    ALIGNMENT_UNDO = "alignment.undo"
    ALIGNMENT_BACKUPS = "alignment.backups"
    ALIGNMENT_RESTORE = "alignment.restore"

    SETTINGS_GET = "settings.get"
    SETTINGS_SET = "settings.set"

    EXPORT_ALIGNED = "export.aligned"
    EXPORT_NON_ALIGNED = "export.nonAligned"

    VERSIFICATION_DETECT = "versification.detect"
    VERSIFICATION_ORG_REF = "versification.orgRef"
    VERSIFICATION_BACK_MAP = "versification.backVersificationMap"

    ALIGNMENT_CORPUS_STATS_SUMMARY = "alignment.corpusStats.summary"
    ALIGNMENT_CORPUS_STATS_FOR_VERSE = "alignment.corpusStats.forVerse"

    ALIGNMENT_AI_PROPOSE = "alignment.aiPropose"
    ALIGNMENT_AI_APPLY_PROPOSAL = "alignment.aiApplyProposal"

    AI_EXPLAIN_VERSE = "ai.explain"
    AI_REVIEW_START = "ai.review.start"
    AI_REVIEW_STATUS = "ai.review.status"
    AI_REVIEW_CANCEL = "ai.review.cancel"
    AI_REVIEW_RETRY = "ai.review.retry"
    AI_REVIEW_LIST_CHAPTER = "ai.review.listForChapter"

    PARATEXT_GET_STATE = "paratext.getState"
    PARATEXT_SET_REFERENCE = "paratext.setReference"

    LOGOS_GET_STATE = "logos.getState"
    LOGOS_SET_REFERENCE = "logos.setReference"


class BridgeEngine:
    def __init__(self, settings: Optional[AppSettings] = None, ai_transport: Optional[Transport] = None) -> None:
        # ai_transport lets tests inject a fake OpenAI-Responses-shaped
        # transport (the same Callable[[url, headers, body, timeout],
        # (status, bytes)] shape ai_client.OpenAIResponsesClient already
        # accepts) instead of a real network call — mirrors that class's
        # own existing dependency-injection pattern, extended one level up
        # so BridgeEngine's AI protocol methods are unit-testable without a
        # real API key. None in production means "use the real network".
        self._ai_transport = ai_transport
        # LogosConnectorClient owns one persistent -STA PowerShell subprocess (COM
        # automation needs a single-threaded apartment) — unlike ParatextConnectorClient's
        # stateless per-call named-pipe open, spawning a fresh PowerShell process on every
        # poll would be far too slow (real measured startup well over a second). Created
        # lazily on first use, reused for the rest of this process's life.
        self._logos_client: Optional[LogosConnectorClient] = None
        self.greek_room = GreekRoomEngine()
        self.project: Optional[TranslationCoreProject] = None
        # USFM structural checks run once per whole book (not once per
        # verse — each run spawns a subprocess loading a real tag/Unicode
        # database, far too slow to repeat per verse.runChecks call). Keyed
        # by project path so switching books/projects naturally invalidates.
        # Not invalidated by verse.edit — see _usfm_findings_for_book.
        self._usfm_findings_by_book: dict[str, list[QaFinding]] = {}
        self._usfm_errors_by_book: dict[str, str] = {}
        # Versification detection is cheap (in-memory dict scans against
        # already-loaded schema data, not a subprocess) but still whole-book
        # work, so it's cached per project path the same way USFM findings
        # are, computed lazily on first request rather than on every open.
        self._versification_by_book: dict[str, dict[str, Any]] = {}
        # Names/transliteration spelling-consistency is also inherently
        # whole-book (there's nothing to compare a single verse's spelling
        # against), so it's cached the same way as USFM findings — not
        # invalidated by verse.edit either, see _names_findings_for_book.
        self._names_findings_by_book: dict[str, list[QaFinding]] = {}
        self._names_errors_by_book: dict[str, str] = {}
        # UAlign-style corpus statistics (Phase 6) scan every COMPLETED verse
        # across the open book's whole collection — see
        # alignment_statistics.py's own docstring for why this is a fresh
        # implementation against Bridge's own data rather than a vendored
        # ualign.py. Cached per primary project path like the caches above,
        # but ALSO invalidated by any alignment mutation that changes which
        # verses are complete for the current book (_save_alignment,
        # complete_alignment, undo_alignment) — unlike USFM/names findings,
        # this cache is cheap enough (a linear scan over already-completed
        # verses, not a subprocess or whole-book vocabulary comparison) that
        # keeping it fresh on every mutation is worth it rather than waiting
        # for the next project.open.
        self._corpus_stats_by_book: dict[str, corpus_stats_tool.CorpusStatsTable] = {}
        self._checker_lock = threading.RLock()
        self._import_lock = threading.Lock()
        self._check_jobs = CheckJobManager()
        self._ai_review_jobs = AIReviewJobManager()
        # AppSettings() with no path defaults to a real, persistent location
        # (%LOCALAPPDATA%/Bridge/data/settings.json on Windows — a subfolder
        # of the NSIS install dir, not the dir itself, so an uninstall can't
        # wipe user data as a side effect; see _default_app_root()'s
        # docstring in secret_store.py for the legacy-path migration), and
        # get_api_key() also checks OPENAI_API_KEY. That's correct for
        # production use — settings should survive restarts — but tests must
        # inject an isolated instance rather than touch the real machine's
        # settings. See tests/test_bridge_service.py.
        self.settings = settings if settings is not None else AppSettings()

        # Keep imported projects in the same application-owned folder as settings.
        settings_root = self.settings.path.parent
        self.project_root = settings_root / "projects"
        self.project_registry = ProjectRegistry(
            settings_root / "project-registry.json", self.project_root,
        )

    # -- lifecycle ------------------------------------------------------

    def info(self) -> dict[str, Any]:
        return {
            "bridgeVersion": BRIDGE_VERSION,
            "projectOpen": self.project is not None,
            "greekRoom": self.greek_room.info(),
        }

    def open_project(self, path: str, project_id: str = "") -> dict[str, Any]:
        self._usfm_findings_by_book.clear()
        self._usfm_errors_by_book.clear()
        self._versification_by_book.clear()
        self._names_findings_by_book.clear()
        self._names_errors_by_book.clear()
        self._corpus_stats_by_book.clear()
        materialize_lazy_project(path)
        ensure_bridge_original_language(path)
        candidate = TranslationCoreProject(path)
        if project_id:
            existing = self.project_registry.get(project_id)
            if existing:
                existing_book = str(existing.get("bookId") or "").lower()
                existing_language = str(existing.get("targetLanguageId") or "").lower()
                candidate_target = candidate.manifest.get("target_language", {})
                candidate_language = str(
                    candidate_target.get("id") or "" if isinstance(candidate_target, dict) else ""
                ).lower()
                if existing_book and existing_book != candidate.book_id.lower():
                    raise ProjectError(
                        f"The selected folder is {candidate.book_id.upper()}, but the missing "
                        f"project is {existing_book.upper()}. Choose the original project folder."
                    )
                if existing_language and candidate_language and existing_language != candidate_language:
                    raise ProjectError(
                        "The selected folder has a different target language from the missing project."
                    )
        self.project = candidate
        info = self._project_info()
        siblings = collection_projects(path)
        if siblings:
            info["importedProjects"] = siblings
        registered = self.project_registry.register(path, touch=True, project_id=project_id)
        info.update({
            "projectId": registered["projectId"],
            "collectionId": registered.get("collectionId", ""),
            "managed": registered.get("managed", False),
        })
        return info

    def list_projects(self) -> dict[str, Any]:
        return {"projects": self.project_registry.list_projects(collapse_collections=True)}

    def forget_project(self, project_id: str) -> dict[str, Any]:
        if not project_id:
            raise ProjectError("projectId is required")
        return {"forgotten": self.project_registry.forget(project_id)}

    def delete_project(self, project_id: str) -> dict[str, Any]:
        if not project_id:
            raise ProjectError("projectId is required")
        entry = self.project_registry.get(project_id)
        if entry is None:
            raise ProjectError("Project not found")
        managed = bool(entry.get("managed"))
        if managed:
            managed_root = self.project_registry.managed_root
            for sibling in self.project_registry.group_entries(project_id):
                sibling_path = Path(str(sibling.get("path") or ""))
                if not sibling_path.exists():
                    continue
                resolved = sibling_path.resolve(strict=False)
                if resolved != managed_root and managed_root not in resolved.parents:
                    continue
                shutil.rmtree(resolved, ignore_errors=True)
        forgotten = self.project_registry.forget(project_id)
        return {"deleted": forgotten, "managed": managed}

    def _project_info(self) -> dict[str, Any]:
        self._require_project()
        summary = self.project.summary  # property, not a method
        target = self.project.manifest.get("target_language", {})
        resource = self.project.manifest.get("resource", {})
        bridge_project = self.project.manifest.get("bridge_project", {})
        original_language = resource_inventory(self.project.book_id)
        project_original_language = self.project.manifest.get("bridge_original_language", {})
        project_original_version = str(
            self.project.manifest.get("tc_orig_lang_check_version_wordAlignment") or ""
        )
        original_language.update({
            "projectVersion": project_original_version,
            "projectResource": project_original_language,
            "versionMismatch": bool(
                isinstance(project_original_language, dict)
                and project_original_language
                and (
                    str(project_original_language.get("version") or "") != str(original_language.get("version") or "")
                    or str(project_original_language.get("commit") or "") != str(original_language.get("commit") or "")
                )
            ),
        })
        return {
            "path": str(summary.path),
            "bookId": summary.book_id,
            "bookName": summary.book_name,
            "targetLanguage": summary.target_language,
            "targetLanguageId": str(target.get("id") or "") if isinstance(target, dict) else "",
            "targetLanguageDirection": str(target.get("direction") or "") if isinstance(target, dict) else "",
            "projectName": str(bridge_project.get("name") or summary.book_name) if isinstance(bridge_project, dict) else summary.book_name,
            "bibleName": str(resource.get("name") or resource.get("id") or "") if isinstance(resource, dict) else "",
            "tcVersion": summary.tc_version,
            "chapters": self.project.chapters(),
            "checkTypes": self.project.check_types(),
            "originalLanguageResource": original_language,
        }

    def inspect_project_import(self, path: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        """Read-only detection/validation used before the metadata form."""
        preview = inspect_import(path)
        preview["duplicates"] = self.project_registry.classify(preview, metadata)
        return preview

    def import_project(self, path: str, metadata: dict[str, Any],
                       destination_root: str = "", allow_duplicate: bool = False) -> dict[str, Any]:
        """Normalize USFM/SFM, Paratext folders, or tC archives, then open it.

        Existing translationCore state is copied intact. Raw Scripture becomes
        a tC-compatible primary book immediately; other books in a collection
        are copied into application storage and normalized when first opened.
        TranslationNotes/translationWords indexes are prepared by the checking
        job instead of blocking navigation into the editor.
        """
        if not self._import_lock.acquire(blocking=False):
            raise ProjectError("Another project import is already running.")
        try:
            preview = inspect_import(path)
            duplicate = self.project_registry.classify(preview, metadata)
            if duplicate["classification"] == "exactDuplicate" and not allow_duplicate:
                raise ProjectError(
                    "This source has already been imported. Open the existing project, "
                    "or explicitly choose Import as separate copy."
                )
            root = Path(destination_root).resolve() if destination_root else self.project_root
            result = import_source(path, root, metadata)
            fingerprints = source_fingerprints(preview)
            for imported in result["projects"]:
                book_id = str(imported.get("bookId") or "").lower()
                registered = self.project_registry.register(
                    imported["path"],
                    source_fingerprint=fingerprints.get(book_id, ""),
                    project_id=str(imported.get("projectId") or ""),
                    collection_id=str(imported.get("collectionId") or ""),
                )
                imported.update({
                    "projectId": registered["projectId"],
                    "collectionId": registered.get("collectionId", ""),
                })

            info = self.open_project(result["primaryProjectPath"])
            info["import"] = result
            info["importedProjects"] = result["projects"]
            return info
        finally:
            self._import_lock.release()

    def _ensure_resource_indexes(self, project: TranslationCoreProject) -> None:
        """Prepare raw-import tN/tW indexes on demand, once per book."""
        import_path = project.path / ".bridge" / "import.json"
        if not import_path.is_file():
            return
        try:
            import_data = json.loads(import_path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            return
        capabilities = import_data.get("capabilities")
        if not isinstance(capabilities, dict) or not any(
            capabilities.get(tool) == "requires-resource-index"
            for tool in ("translationNotes", "translationWords")
        ):
            return
        resources_root = project.path.parent.parent / "resources"
        materialization = materialize_book_checks(project.path, project.book_id, resources_root)
        apply_resource_materialization(project.path, materialization)

    @staticmethod
    def _resource_indexes_pending(project: TranslationCoreProject) -> bool:
        """Return quickly when a raw import still needs its tN/tW indexes.

        Materialization belongs to the background-check preflight.  Interactive
        review requests must never perform that potentially expensive work on
        the single stdio dispatcher thread, otherwise every later request
        (including checks.status/cancel) queues behind it.
        """
        import_path = project.path / ".bridge" / "import.json"
        if not import_path.is_file():
            return False
        try:
            import_data = json.loads(import_path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            return False
        capabilities = import_data.get("capabilities")
        return isinstance(capabilities, dict) and any(
            capabilities.get(tool) == "requires-resource-index"
            for tool in ("translationNotes", "translationWords")
        )

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
            "alignmentStatus": self._alignment_verse_status(self.project, chapter, verse),
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
                "alignmentStatus": self._alignment_verse_status(self.project, chapter, v),
            }
        return {"chapter": chapter, "verses": out}

    def list_checks_for_verse(self, chapter: str, verse: str) -> dict[str, Any]:
        self._require_project()
        project = self.project
        # Never wait behind whole-book USFM/names preparation on the stdio
        # dispatcher.  A blocking request here prevents even checks.status
        # and checks.cancel from being read until Rust's 30-second timeout.
        if self._resource_indexes_pending(project):
            return {
                "chapter": str(chapter), "verse": str(verse), "checks": [],
                "state": "preparing", "retryAfterMs": 750,
                "message": "Preparing translationNotes and translationWords resources…",
            }
        if not self._checker_lock.acquire(blocking=False):
            return {
                "chapter": str(chapter), "verse": str(verse), "checks": [],
                "state": "preparing", "retryAfterMs": 750,
                "message": "Translation checks are running; review data will appear shortly.",
            }
        try:
            self.project.invalidate_index_cache()
            checks = self.project.check_reviews_for_verse(chapter, verse)
            ai_review_state = self.project.ai_review_cache_status(chapter, verse)
            cached_ai = self.project.load_ai_review_result(chapter, verse) if ai_review_state == "current" else None
            ai_reviews = list((cached_ai or {}).get("checkReviews") or [])
            ai_by_identity = {
                (str(item.get("tool") or ""), str(item.get("check_id") or "")): item
                for item in ai_reviews if isinstance(item, dict)
            }
            evaluation = {
                "pass": "passed", "not_applicable": "passed",
                "problem": "issue_open", "review": "needs_review",
            }
            for check in checks:
                ai_item = ai_by_identity.get((str(check.get("tool") or ""), str(check.get("checkId") or "")))
                if ai_item:
                    check["evaluationStatus"] = evaluation.get(str(ai_item.get("verdict") or ""), "needs_review")
                elif ai_review_state == "stale":
                    check["evaluationStatus"] = "needs_review"
        finally:
            self._checker_lock.release()
        return {
            "chapter": str(chapter), "verse": str(verse), "checks": checks,
            "state": "ready", "retryAfterMs": 0, "message": "",
            "aiReviewState": ai_review_state,
            "aiReviews": ai_reviews,
            "aiQaIssues": list((cached_ai or {}).get("qaIssues") or []),
            "aiSummary": str((cached_ai or {}).get("summary") or ""),
        }

    def validate_check_selection(
        self, chapter: str, verse: str, tool: str, group_id: str, check_id: str,
        selections: Any, nothing_to_select: bool,
    ) -> dict[str, Any]:
        self._require_project()
        with self._checker_lock:
            return self.project.validate_check_selection(
                chapter, verse, tool, group_id, check_id, selections, nothing_to_select,
            )

    def save_check_selection(
        self, chapter: str, verse: str, tool: str, group_id: str, check_id: str,
        selections: list[dict[str, Any]], nothing_to_select: bool, provenance: str,
        expected_fingerprint: str, metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._require_project()
        with self._checker_lock:
            result = self.project.save_check_selection(
                chapter, verse, tool, group_id, check_id, selections, nothing_to_select,
                provenance, expected_fingerprint,
                username=self.settings.reviewer_name or "Bridge Reviewer",
                audit_metadata=metadata,
            )
            if provenance == "bridge_ai":
                self.project.rebase_ai_review_fingerprint(chapter, verse)
            return result

    def clear_check_selection(
        self, chapter: str, verse: str, tool: str, group_id: str, check_id: str,
        provenance: str, expected_fingerprint: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._require_project()
        with self._checker_lock:
            return self.project.clear_check_selection(
                chapter, verse, tool, group_id, check_id, provenance, expected_fingerprint,
                username=self.settings.reviewer_name or "Bridge Reviewer",
                audit_metadata=metadata,
            )

    # -- word alignment ---------------------------------------------------

    @staticmethod
    def _target_token_inventory(text: str) -> list[TokenRef]:
        words = whitespace_tokens(text)
        totals = Counter(words)
        seen: Counter[str] = Counter()
        result: list[TokenRef] = []
        for word in words:
            seen[word] += 1
            result.append(TokenRef(word, seen[word], totals[word], type="bottomWord"))
        return result

    @staticmethod
    def _alignment_verse_status(
        project: TranslationCoreProject, chapter: str, verse: str,
    ) -> str:
        if project.word_alignment_state(chapter, verse) == "invalid":
            return "invalid"
        return project.alignment_work_state(chapter, verse)

    def alignment_status(self, chapter: str = "") -> dict[str, Any]:
        self._require_project()
        project_chapters = self.project.chapters()
        chapters = [str(chapter)] if chapter else project_chapters
        counts = {"complete": 0, "partial": 0, "untouched": 0, "invalid": 0}
        verses: dict[str, str] = {}
        for ch in chapters:
            if ch not in project_chapters:
                raise ProjectError(f"Chapter {ch} does not exist in this project.")
            for verse in self.project.verses(ch):
                if verse == "front":
                    continue
                status = self._alignment_verse_status(self.project, ch, verse)
                counts[status] += 1
                verses[f"{ch}:{verse}"] = status
        return {"chapter": str(chapter), "counts": counts, "verses": verses}

    def _alignment_context(self, chapter: str, verse: str) -> dict[str, Any]:
        self._require_project()
        alignment = self.project.load_verse_alignment(chapter, verse)
        inventory = make_inventory(alignment)
        expected_bottom = self._target_token_inventory(
            self.project.target_verse_text(chapter, verse)
        )
        expected_signatures = [token.signature for token in expected_bottom]
        actual_bottom = alignment.all_bottom()
        actual_signatures = [token.signature for token in actual_bottom]
        issues = list(structural_issues(alignment))
        missing = [signature for signature in expected_signatures if signature not in actual_signatures]
        extra = [signature for signature in actual_signatures if signature not in expected_signatures]
        duplicate_top = [
            key for key, count in Counter(t.signature for t in alignment.all_top()).items()
            if count > 1
        ]
        duplicate_bottom = [key for key, count in Counter(actual_signatures).items() if count > 1]
        if missing:
            issues.append(f"{len(missing)} target token(s) are missing from alignment data.")
        if extra:
            issues.append(f"{len(extra)} alignment token(s) are absent from current target text.")
        if duplicate_top:
            issues.append(f"{len(duplicate_top)} source token(s) occur in more than one alignment group.")
        if duplicate_bottom:
            issues.append(f"{len(duplicate_bottom)} target token(s) occur more than once in alignment data.")
        target_positions = {
            token.signature: position for position, token in enumerate(expected_bottom)
        }
        discontinuous_groups = 0
        for group in alignment.alignments:
            positions = sorted(
                target_positions[token.signature]
                for token in group.bottom_words
                if token.signature in target_positions
            )
            if len(positions) > 1 and positions[-1] - positions[0] + 1 != len(positions):
                discontinuous_groups += 1
        if discontinuous_groups:
            issues.append(
                f"{discontinuous_groups} alignment group(s) contain non-adjacent target words; "
                "aligned USFM requires each target span to be contiguous."
            )

        top_tokens = [
            {"id": token_id, **token.to_dict()}
            for token_id, token in inventory.top_ids.items()
        ]
        # Present target words in verse order, independent of group order.
        bottom_tokens: list[dict[str, Any]] = []
        seen_bottom_ids: set[str] = set()
        for token in expected_bottom:
            token_id = inventory.bottom_sig_to_id.get(token.signature)
            if token_id:
                bottom_tokens.append({
                    "id": token_id,
                    **inventory.bottom_ids[token_id].to_dict(bottom=True),
                })
                seen_bottom_ids.add(token_id)
        for token_id, token in inventory.bottom_ids.items():
            if token_id not in seen_bottom_ids:
                bottom_tokens.append({"id": token_id, **token.to_dict(bottom=True)})

        groups = []
        for index, group in enumerate(alignment.alignments):
            groups.append({
                "id": f"G{index + 1:03d}",
                "topIds": [
                    inventory.top_sig_to_id[token.signature]
                    for token in group.top_words
                    if token.signature in inventory.top_sig_to_id
                ],
                "bottomIds": [
                    inventory.bottom_sig_to_id[token.signature]
                    for token in group.bottom_words
                    if token.signature in inventory.bottom_sig_to_id
                ],
            })
        source_direction = "rtl" if any(
            token.strong.upper().startswith("H") or token.morph.startswith("He,")
            for token in alignment.all_top()
        ) else "ltr"
        target = self.project.manifest.get("target_language", {})
        target_direction = str(target.get("direction") or "ltr") if isinstance(target, dict) else "ltr"
        source_available = bool(top_tokens)
        work_state = self._alignment_verse_status(self.project, chapter, verse)
        can_complete = (
            source_available
            and not issues
            and not alignment.word_bank
            and bool(alignment.alignments)
            and all(group.top_words and group.bottom_words for group in alignment.alignments)
        )
        return {
            "chapter": str(chapter), "verse": str(verse),
            "alignment": alignment.to_dict(),
            "topTokens": top_tokens, "bottomTokens": bottom_tokens, "groups": groups,
            "status": work_state,
            "completionState": self.project.word_alignment_state(chapter, verse),
            "sourceAvailable": source_available,
            "sourceMessage": "" if source_available else (
                "This verse has no original-language source tokens. Import a translationCore project "
                "or aligned USFM 3 containing source alignment milestones before creating alignments."
            ),
            "sourceDirection": source_direction, "targetDirection": target_direction,
            "issues": issues, "canComplete": can_complete,
            "history": self.project.alignment_history(chapter, verse)[:20],
            "chapterStatus": self.alignment_status(chapter)["counts"],
        }

    def get_alignment(self, chapter: str, verse: str) -> dict[str, Any]:
        return self._alignment_context(chapter, verse)

    @staticmethod
    def _tokens_for_ids(
        inventory, top_ids: list[str], bottom_ids: list[str],
    ) -> tuple[list[TokenRef], list[TokenRef]]:
        unknown_top = [token_id for token_id in top_ids if token_id not in inventory.top_ids]
        unknown_bottom = [token_id for token_id in bottom_ids if token_id not in inventory.bottom_ids]
        if unknown_top or unknown_bottom:
            raise AlignmentError(
                "The alignment changed or contains unknown token IDs. Reload before saving."
            )
        return (
            [inventory.top_ids[token_id] for token_id in dict.fromkeys(top_ids)],
            [inventory.bottom_ids[token_id] for token_id in dict.fromkeys(bottom_ids)],
        )

    @staticmethod
    def _validate_alignment_identity(current: VerseAlignment, proposed: VerseAlignment) -> None:
        if Counter(t.signature for t in current.all_top()) != Counter(t.signature for t in proposed.all_top()):
            raise AlignmentError("A save may regroup source tokens but may not add, remove, or duplicate them.")
        if Counter(t.signature for t in current.all_bottom()) != Counter(t.signature for t in proposed.all_bottom()):
            raise AlignmentError("A save may regroup target tokens but may not add, remove, or duplicate them.")

    def _save_alignment(
        self,
        chapter: str,
        verse: str,
        proposed: VerseAlignment,
        expected_original: dict[str, Any],
        operation: str,
    ) -> dict[str, Any]:
        current = self.project.load_verse_alignment(chapter, verse)
        self._validate_alignment_identity(current, proposed)
        self.project.save_verse_alignment(
            chapter, verse, proposed,
            expected_original=expected_original,
            operation=operation,
        )
        self.project.mark_word_alignment_pending(chapter, verse)
        self._corpus_stats_by_book.pop(str(self.project.path), None)
        return self._alignment_context(chapter, verse)

    def realign_words(
        self,
        chapter: str,
        verse: str,
        top_ids: list[str],
        bottom_ids: list[str],
        expected_original: dict[str, Any],
    ) -> dict[str, Any]:
        current = self.project.load_verse_alignment(chapter, verse)
        inventory = make_inventory(current)
        selected_top, selected_bottom = self._tokens_for_ids(inventory, top_ids, bottom_ids)
        proposed = realign(current, selected_top, selected_bottom)
        return self._save_alignment(chapter, verse, proposed, expected_original, "realign")

    def unalign_words(
        self,
        chapter: str,
        verse: str,
        bottom_ids: list[str],
        expected_original: dict[str, Any],
    ) -> dict[str, Any]:
        current = self.project.load_verse_alignment(chapter, verse)
        inventory = make_inventory(current)
        _, selected_bottom = self._tokens_for_ids(inventory, [], bottom_ids)
        proposed = unalign_bottom(current, selected_bottom)
        return self._save_alignment(chapter, verse, proposed, expected_original, "unalign")

    def save_alignment(
        self,
        chapter: str,
        verse: str,
        value: dict[str, Any],
        expected_original: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise AlignmentError("Alignment must be an object.")
        return self._save_alignment(
            chapter, verse, VerseAlignment.from_dict(value), expected_original, "save",
        )

    def complete_alignment(self, chapter: str, verse: str) -> dict[str, Any]:
        context = self._alignment_context(chapter, verse)
        if not context["sourceAvailable"]:
            raise AlignmentError(context["sourceMessage"])
        if not context["canComplete"]:
            detail = "; ".join(context["issues"]) or "unaligned source or target words remain"
            raise AlignmentError(f"Alignment cannot be completed: {detail}.")
        self.project.mark_word_alignment_completed(
            chapter, verse, username=self.settings.reviewer_name or "Bridge Reviewer",
        )
        self._corpus_stats_by_book.pop(str(self.project.path), None)
        return self._alignment_context(chapter, verse)

    def undo_alignment(
        self,
        chapter: str,
        verse: str,
        expected_original: dict[str, Any],
        history_id: str = "",
    ) -> dict[str, Any]:
        self.project.restore_verse_alignment_history(
            chapter, verse, history_id=history_id, expected_original=expected_original,
        )
        self.project.mark_word_alignment_pending(chapter, verse)
        self._corpus_stats_by_book.pop(str(self.project.path), None)
        return self._alignment_context(chapter, verse)

    def _ai_client(self) -> OpenAIResponsesClient:
        api_key = self.settings.get_api_key()
        if not api_key:
            raise AIError(
                "No OpenAI-compatible API key is configured. Add one in Settings before "
                "requesting an AI alignment proposal."
            )
        kwargs: dict[str, Any] = {}
        if self._ai_transport is not None:
            kwargs["transport"] = self._ai_transport
        return OpenAIResponsesClient(
            api_key, model=self.settings.model, base_url=self.settings.api_base_url, **kwargs
        )

    def propose_ai_alignment(self, chapter: str, verse: str, mode: str = "gap_fill") -> dict[str, Any]:
        """Ask AI for individual token links, then compile them deterministically into
        legal tC groups via alignment_reliability.compile_link_proposal. Read-only: the
        proposal is returned for human review and is not written to project files —
        alignment.aiApplyProposal is a separate, explicit step. gap_fill (the default)
        protects every existing non-empty group; audit is a read-only whole-verse
        comparison not meant to be applied directly (see compile_link_proposal's own
        docstring — an audit proposal is rejected by alignment.aiApplyProposal's
        validate_preparation_proposal safety check if it would detach an established
        group)."""
        self._require_project()
        client = self._ai_client()
        alignment = self.project.load_verse_alignment(chapter, verse)
        proposal = client.propose_alignment(self.project, chapter, verse, alignment, mode=mode)
        self.settings.record_ai_usage(client.last_usage.total_tokens, client.last_cost_usd)
        return {
            # The proposal's internal field names (top_ids/bottom_ids/requires_human_review/...)
            # match alignment_reliability.compile_link_proposal's own schema verbatim, unlike this
            # file's usual camelCase protocol convention — it must round-trip byte-for-byte back
            # into alignment.aiApplyProposal's apply_proposal() call, which reads those exact
            # snake_case keys. Re-keying it here would risk a lossy/asymmetric conversion for no
            # benefit, since the frontend only needs to read top_ids/bottom_ids generically to
            # resolve token labels, the same way it already does for existing alignment groups.
            "proposal": proposal,
            "usage": {
                "totalTokens": client.last_usage.total_tokens,
                "estimatedCostUSD": round(client.last_cost_usd, 6),
            },
        }

    def apply_ai_alignment_proposal(
        self, chapter: str, verse: str, proposal: dict[str, Any], expected_original: dict[str, Any],
    ) -> dict[str, Any]:
        """Human-triggered, explicit step that actually writes a previously returned AI
        proposal to the project — never called automatically by propose_ai_alignment.
        Goes through the exact same identity-preserving save pipeline as a manual
        realign/save (_save_alignment), so an AI proposal can add no protection an
        ordinary manual edit wouldn't also get."""
        self._require_project()
        current = self.project.load_verse_alignment(chapter, verse)
        validate_preparation_proposal(current, proposal)
        proposed = apply_proposal(current, proposal)
        return self._save_alignment(chapter, verse, proposed, expected_original, "ai_propose_apply")

    def explain_verse(self, chapter: str, verse: str) -> dict[str, Any]:
        """ai.explain: one-click AI preparation of a verse's translationCore checks
        for the human final reviewer (ai_client.OpenAIResponsesClient.prepare_verse_review).
        AI reads translationNotes/translationWords/translationAcademy evidence, proposes
        target-word selections for each check, and performs whole-verse QA — all backed by
        real evidence_catalog citations. Nothing is written to project files: the human
        reviewer sees this as a preparation to confirm/reject, same "AI says what it may
        mean, human decides" boundary as everywhere else in Bridge. Requires both an
        original-language source (to build the alignment inventory) and a configured API
        key; needs real translationNotes/translationWords/translationAcademy evidence to be
        materialized for grounded results — a project still 'requires-resource-index' will
        simply get thin evidence, not an error, matching how run_full_review degrades."""
        self._require_project()
        client = self._ai_client()
        alignment = self.project.load_verse_alignment(chapter, verse)
        proposal, review_alignment, reviews, issues, summary, meta = client.prepare_verse_review(
            self.project, chapter, verse, alignment,
        )
        self.settings.record_ai_usage(
            int(meta.get("total_tokens_for_prepare", 0) or 0), float(meta.get("estimated_cost_usd", 0.0) or 0.0),
        )
        return {
            "summary": summary,
            "checkReviews": [r.to_dict() for r in reviews],
            "qaIssues": [i.to_dict() for i in issues],
            "alignmentProposal": proposal,
            "alignmentWasAIProposed": bool(proposal is not None),
            "usage": {
                "totalTokens": int(meta.get("total_tokens_for_prepare", 0) or 0),
                "estimatedCostUSD": round(float(meta.get("estimated_cost_usd", 0.0) or 0.0), 6),
            },
        }

    @staticmethod
    def _safe_ai_selection_reason(review: Any) -> str:
        """Return an empty string only when a model proposal is safe to auto-apply.

        Structured-output validation proves shape and token identity.  This second,
        deterministic policy gate proves that the conclusion is decisive, grounded,
        and complete enough for Basic mode.  The native persistence layer remains the
        final authority and independently blocks overwriting imported/human choices.
        """
        if review.verdict not in {"pass", "problem", "not_applicable"}:
            return "AI verdict requires human review"
        if float(review.confidence or 0.0) < 0.82:
            return "AI confidence is below the 82% automatic-selection threshold"
        if not review.evidence_used:
            return "No bundled evidence was cited"
        if review.verdict == "not_applicable" and not review.nothing_to_select:
            return "Not-applicable verdict must explicitly select nothing"
        if review.nothing_to_select:
            return "" if not review.proposed_selections else "Proposal contradicts nothing-to-select"
        if not review.proposed_selections:
            return "No exact target selection was proposed"
        return ""

    def _apply_basic_ai_selections(
        self,
        project: TranslationCoreProject,
        chapter: str,
        verse: str,
        reviews: list[Any],
        *,
        model: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        applied: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        for review in reviews:
            reason = self._safe_ai_selection_reason(review)
            identity = {
                "tool": review.tool, "groupId": review.group_id, "checkId": review.check_id,
            }
            if reason:
                skipped.append({**identity, "reason": reason})
                continue
            try:
                with self._checker_lock:
                    validation = project.validate_check_selection(
                        chapter, verse, review.tool, review.group_id, review.check_id,
                        review.proposed_selections, review.nothing_to_select,
                    )
                    if not validation.get("valid"):
                        skipped.append({
                            **identity,
                            "reason": " ".join(validation.get("errors") or ["Selection validation failed"]),
                        })
                        continue
                    mutation = project.save_check_selection(
                        chapter, verse, review.tool, review.group_id, review.check_id,
                        validation.get("selections") or [], review.nothing_to_select,
                        "bridge_ai", str(validation.get("stateFingerprint") or ""),
                        username="Bridge AI",
                        audit_metadata={
                            "interface": "basic", "model": model,
                            "confidence": review.confidence, "verdict": review.verdict,
                            "evidenceGrounded": True,
                        },
                    )
                applied.append({**identity, "review": mutation.get("review")})
            except ProjectError as exc:
                # Protected imported/human choices and concurrent changes are a safe
                # per-check skip, not a reason to lose every other verse result.
                skipped.append({**identity, "reason": str(exc)})
        if applied:
            with self._checker_lock:
                project.rebase_ai_review_fingerprint(chapter, verse)
        return applied, skipped

    def _run_ai_review_for_project(
        self,
        project: TranslationCoreProject,
        chapter: str,
        verse: str,
        mode: str,
        progress_callback: Callable[[int, str], None],
        cancel_event: threading.Event,
    ) -> dict[str, Any]:
        if cancel_event.is_set():
            raise AIError("AI review cancelled before the verse started.")
        with self._checker_lock:
            self._ensure_resource_indexes(project)
        client = self._ai_client()
        alignment = project.load_verse_alignment(chapter, verse)
        proposal, _, reviews, issues, summary, meta = client.prepare_verse_review(
            project, chapter, verse, alignment, progress_callback=progress_callback,
        )
        total_tokens = int(meta.get("total_tokens_for_prepare", 0) or 0)
        cost = float(meta.get("estimated_cost_usd", 0.0) or 0.0)
        self.settings.record_ai_usage(total_tokens, cost)
        if cancel_event.is_set():
            project.mark_ai_review_incomplete(chapter, verse, "cancelled")
            raise AIError("AI review cancelled; the completed model result was not automatically applied.")
        applied: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        if mode == "basic":
            progress_callback(94, "Applying safe evidence-grounded selections")
            applied, skipped = self._apply_basic_ai_selections(
                project, chapter, verse, reviews, model=str(meta.get("model") or client.model),
            )
        progress_callback(100, "Verse AI review complete")
        return {
            "summary": summary,
            "checkReviews": [item.to_dict() for item in reviews],
            "qaIssues": [item.to_dict() for item in issues],
            "alignmentProposal": proposal,
            "alignmentWasAIProposed": bool(proposal is not None),
            "appliedSelections": applied,
            "skippedSelections": skipped,
            "usage": {"totalTokens": total_tokens, "estimatedCostUSD": round(cost, 6)},
        }

    def _start_ai_review_spec(
        self, project: TranslationCoreProject, spec: AIReviewJobSpec,
    ) -> dict[str, Any]:
        # Fail immediately with the familiar settings error instead of starting a
        # background job whose first verse can only fail for a missing API key.
        self._ai_client()
        return self._ai_review_jobs.start(
            spec,
            run_verse=lambda ch, vs, reviewer_mode, progress, cancel: self._run_ai_review_for_project(
                project, ch, vs, reviewer_mode, progress, cancel,
            ),
        )

    def start_ai_review_job(
        self, scope: str, chapter: str = "", verse: str = "", mode: str = "",
    ) -> dict[str, Any]:
        self._require_project()
        project = self.project
        resolved_mode = str(mode or self.settings.reviewer_mode or "basic").lower()
        available = project.chapters()
        if scope == "book":
            chapters = available
        else:
            if not chapter or str(chapter) not in available:
                raise ProjectError(f"Chapter {chapter or '?'} does not exist in this project.")
            chapters = [str(chapter)]
        requested = {
            item: [value for value in project.verses(item) if value != "front"]
            for item in chapters
        }
        if scope == "verse":
            if not verse or str(verse) not in requested[str(chapter)]:
                raise ProjectError(f"Verse {chapter}:{verse or '?'} does not exist in this project.")
            chapter_verses = {str(chapter): [str(verse)]}
            skipped_current = 0
        else:
            # Chapter/book buttons are resumable by default. Already-current cached
            # reviews are real completed work and should not consume API calls again.
            chapter_verses = {
                ch: [vs for vs in values if project.ai_review_cache_status(ch, vs) != "current"]
                for ch, values in requested.items()
            }
            skipped_current = sum(len(values) for values in requested.values()) - sum(
                len(values) for values in chapter_verses.values()
            )
        spec = AIReviewJobSpec(
            scope=scope, mode=resolved_mode, project_path=str(project.path),
            chapters=tuple(chapters), chapter_verses=chapter_verses,
            skipped_current=skipped_current,
        )
        return self._start_ai_review_spec(project, spec)

    def ai_review_job_status(self, job_id: str = "") -> dict[str, Any]:
        return self._ai_review_jobs.status(job_id)

    def cancel_ai_review_job(self, job_id: str = "") -> dict[str, Any]:
        return self._ai_review_jobs.cancel(job_id)

    def retry_ai_review_job(self, job_id: str) -> dict[str, Any]:
        self._require_project()
        spec = self._ai_review_jobs.spec_for_retry(job_id)
        if str(self.project.path) != spec.project_path:
            raise ProjectError("Reopen the original project before retrying this AI review job.")
        return self._start_ai_review_spec(self.project, spec)

    @staticmethod
    def _compact_ai_review(item: dict[str, Any]) -> dict[str, Any]:
        compact = copy.deepcopy(item)
        compact["evidence_used"] = [
            {
                key: copy.deepcopy(evidence.get(key))
                for key in ("kind", "title", "identifier", "version", "provider", "authoritative")
                if evidence.get(key) not in (None, "")
            }
            for evidence in list(item.get("evidence_used") or []) if isinstance(evidence, dict)
        ]
        return compact

    def list_ai_reviews_for_chapter(self, chapter: str) -> dict[str, Any]:
        """Restore compact current reviews for chapter-wide inline highlighting."""
        self._require_project()
        if str(chapter) not in self.project.chapters():
            raise ProjectError(f"Chapter {chapter} does not exist in this project.")
        reviews_by_verse: dict[str, list[dict[str, Any]]] = {}
        states: dict[str, str] = {}
        for verse in self.project.verses(chapter):
            if verse == "front":
                continue
            state = self.project.ai_review_cache_status(chapter, verse)
            states[str(verse)] = state
            if state != "current":
                continue
            saved = self.project.load_ai_review_result(chapter, verse) or {}
            reviews_by_verse[str(verse)] = [
                self._compact_ai_review(item)
                for item in list(saved.get("checkReviews") or []) if isinstance(item, dict)
            ]
        return {
            "chapter": str(chapter),
            "reviewsByVerse": reviews_by_verse,
            "states": states,
            "current": sum(1 for state in states.values() if state == "current"),
            "stale": sum(1 for state in states.values() if state == "stale"),
            "missing": sum(1 for state in states.values() if state == "missing"),
        }

    # -- live desktop connectors (Paratext/Logos) --------------------------
    #
    # Direct pass-through calls only in this pass: read the connector's current
    # state, or push one explicit reference into it. This deliberately does NOT
    # wire tc_ai_bridge/navigation.py's NavigationBroker/NavigationOwnership into
    # an automatic background polling loop yet — that's a real, separate UX design
    # (conflict handling, a background job, a live-sync toggle) worth its own pass
    # once these two connectors have been proven against real running
    # Paratext/Logos instances. What's here is already useful on its own: a
    # "Connections" panel can show live state and let a reviewer manually push
    # Bridge's current verse into either application.

    def paratext_get_state(self) -> dict[str, Any]:
        state = ParatextConnectorClient().get_state()
        return asdict(state)

    def paratext_set_reference(self, reference: str, origin_id: str = "") -> dict[str, Any]:
        return ParatextConnectorClient().set_reference(reference, origin_id)

    def _logos_client_instance(self) -> LogosConnectorClient:
        if self._logos_client is None:
            self._logos_client = LogosConnectorClient()
            # Best-effort clean shutdown of the persistent PowerShell helper on a
            # normal interpreter exit. atexit does not run on a hard kill (e.g. Tauri
            # force-terminating the sidecar) — a known, documented limitation, not
            # silently unaddressed; see logos_connector/README.md.
            atexit.register(self._logos_client.close)
        return self._logos_client

    def logos_get_state(self) -> dict[str, Any]:
        state = self._logos_client_instance().get_state()
        return asdict(state)

    def logos_set_reference(self, reference: str, origin_id: str = "") -> dict[str, Any]:
        state = self._logos_client_instance().set_reference(reference, origin_id=origin_id)
        return asdict(state)

    def _usfm_findings_for_book(
        self, project: Optional[TranslationCoreProject] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> list[QaFinding]:
        """Lazily compute + cache whole-book USFM structural findings.

        Not invalidated by verse.edit: re-running the real checker (a
        subprocess loading a full tag database) after every keystroke-level
        edit would be far too slow, and a single verse edit essentially
        never changes book-wide structure (duplicate/missing verse numbers,
        unclosed markers). Accepted as a known limitation, not an oversight —
        re-opening the project re-runs it fresh.
        """
        project = project or self.project
        if project is None:
            raise ProjectError("No project open — call project.open first")
        book_key = str(project.path)
        cached = self._usfm_findings_by_book.get(book_key)
        if cached is not None:
            return cached
        cached_error = self._usfm_errors_by_book.get(book_key)
        if cached_error is not None:
            raise UsfmCheckerError(cached_error)

        usfm_path = project.usfm_path()
        findings: list[QaFinding] = []
        if usfm_path is not None:
            try:
                usfm_text = usfm_path.read_text(encoding="utf-8-sig")
            except OSError:
                usfm_text = ""
            if usfm_text:
                try:
                    findings = self.greek_room.check_book_usfm(
                        project_id=str(project.summary.path),
                        book_id=project.book_id,
                        usfm_text=usfm_text,
                        cancel_event=cancel_event,
                    )
                except UsfmCheckerCancelled:
                    raise
                except UsfmCheckerError as exc:
                    self._usfm_errors_by_book[book_key] = str(exc)
                    raise
                for f in findings:
                    # Same stabilization as Greek Room findings (see
                    # run_verse_checks below) — otherwise a fresh subprocess
                    # run after an app restart would hand out new random
                    # uuid4 ids for the same underlying issues, and any
                    # decision recorded on them in a prior session could
                    # never be matched back.
                    f.id = _stable_finding_id(
                        chapter=str(f.chapter), verse=str(f.verse), engine=f.engine,
                        check_type=f.check_type, disambiguator=f.explanation,
                    )
        self._usfm_findings_by_book[book_key] = findings
        return findings

    def _names_findings_for_book(
        self, project: Optional[TranslationCoreProject] = None,
    ) -> list[QaFinding]:
        """Lazily compute + cache whole-book names/transliteration spelling
        findings (Uroman romanization + vendored Smart Edit Distance — see
        NamesAdapter's own docstring). Same reason and shape as
        _usfm_findings_for_book: consistency is inherently a corpus-level
        question, so this is computed once per book and not invalidated by
        verse.edit — a single verse edit changing one word's spelling could
        in principle change the answer, but re-running a full whole-book
        vocabulary scan after every keystroke-level edit would be far too
        slow; re-opening the project re-runs it fresh, same tradeoff as USFM.
        """
        project = project or self.project
        if project is None:
            raise ProjectError("No project open — call project.open first")
        book_key = str(project.path)
        cached = self._names_findings_by_book.get(book_key)
        if cached is not None:
            return cached
        cached_error = self._names_errors_by_book.get(book_key)
        if cached_error is not None:
            raise NamesCheckError(cached_error)

        token_occurrences: dict[str, list[tuple[str, str]]] = {}
        for ref, text in self._book_verse_text_map(project).items():
            chapter, _, verse = ref.partition(":")
            for token in whitespace_tokens(text):
                token_occurrences.setdefault(token, []).append((chapter, verse))

        target = project.manifest.get("target_language", {})
        lang_code = str(target.get("id") or "") if isinstance(target, dict) else ""

        try:
            findings = self.greek_room.check_book_names(
                project_id=str(project.summary.path),
                book_id=project.book_id,
                lang_code=lang_code,
                token_occurrences=token_occurrences,
            )
        except NamesCheckError as exc:
            self._names_errors_by_book[book_key] = str(exc)
            raise
        for f in findings:
            # Same stabilization reason as USFM findings above: a stable id
            # keyed on the two spellings being compared (sorted, so it
            # doesn't matter which one this run happened to treat as
            # "majority") so a repeat run's random pairing order can't
            # orphan a prior human decision.
            disambiguator = "::".join(sorted([f.original_text, f.suggested_replacement or ""]))
            f.id = _stable_finding_id(
                chapter=str(f.chapter), verse=str(f.verse), engine=f.engine,
                check_type=f.check_type, disambiguator=disambiguator,
            )
        self._names_findings_by_book[book_key] = findings
        return findings

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
        with self._checker_lock:
            if any(name in checks for name in ("local", "tN", "tW")):
                self._ensure_resource_indexes(self.project)
            return self._run_verse_checks_for_project(self.project, chapter, verse, checks)

    def _run_verse_checks_for_project(
        self,
        project: TranslationCoreProject,
        chapter: str,
        verse: str,
        checks: list[str],
    ) -> list[QaFinding]:
        findings: list[QaFinding] = []
        project_id = str(project.summary.path)
        book = project.summary.book_id

        target_text = project.target_verse_text(chapter, verse)

        if "local" in checks or "tN" in checks or "tW" in checks or "alignment" in checks:
            alignment = project.load_verse_alignment(chapter, verse)
            issues = run_local_qa(project, chapter, verse, alignment)
            for issue in issues:
                findings.append(_qaissue_to_finding(
                    issue, project_id=project_id, book=book,
                    chapter=chapter, verse=verse,
                ))

        if "local" in checks or "usfm" in checks:
            # Whole-book findings that fall on this chapter; a finding with
            # no existing verse slot (e.g. "chapter is missing verse 4")
            # surfaces on the chapter's first verse rather than nowhere,
            # since the UI can only request verses that actually exist.
            book_verses = project.verses(chapter) if chapter in project.chapters() else []
            existing_verses = {str(value) for value in book_verses}
            first_verse = book_verses[0] if book_verses else None
            for f in self._usfm_findings_for_book(project):
                if str(f.chapter) != str(chapter):
                    continue
                if str(f.verse) == str(verse):
                    findings.append(f)
                elif (
                    first_verse is not None
                    and str(verse) == str(first_verse)
                    and (f.verse == 0 or str(f.verse) not in existing_verses)
                ):
                    findings.append(f)

        if "local" in checks or "names" in checks:
            # Unlike USFM findings, every names/spelling finding is anchored
            # at a real occurrence's own verse (the minority spelling's
            # first location — see NamesAdapter._build_finding), never a
            # placeholder chapter-level slot, so no first-verse fallback is
            # needed here.
            for f in self._names_findings_for_book(project):
                if str(f.chapter) == str(chapter) and str(f.verse) == str(verse):
                    findings.append(f)

        if "greekroom" in checks or "wildebeest" in checks:
            target_language = project.manifest.get("target_language", {})
            language_id = str(target_language.get("id") or "") if isinstance(target_language, dict) else ""
            gr_findings = self.greek_room.check_verse(
                project_id=project_id,
                lang_code=language_id,
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
        prior_decisions = project.qa_decisions_for_verse(chapter, verse)
        for finding in findings:
            record = prior_decisions.get(finding.id)
            if record:
                try:
                    finding.status = FindingStatus(record.get("decision", "open"))
                except ValueError:
                    pass
                finding.human_comment = record.get("note") or None

        return findings

    # -- background checking jobs -----------------------------------------

    def start_check_job(
        self,
        *,
        scope: str = "chapter",
        chapters: Optional[list[str]] = None,
        checks: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        self._require_project()
        project = self.project
        available = project.chapters()
        requested = [str(ch) for ch in (chapters or ([] if scope == "book" else available[:1]))]
        if scope == "book" and not requested:
            requested = list(available)
        if scope not in {"chapter", "book"}:
            raise CheckJobError("Check scope must be 'chapter' or 'book'.")
        if not requested:
            raise CheckJobError("At least one chapter is required.")
        unknown = [ch for ch in requested if ch not in available]
        if unknown:
            raise CheckJobError(f"Unknown chapter(s): {', '.join(unknown)}")

        selected_checks = tuple(dict.fromkeys(checks or ["local", "greekroom"]))
        supported = {"local", "tN", "tW", "alignment", "usfm", "greekroom", "wildebeest"}
        invalid = [name for name in selected_checks if name not in supported]
        if invalid:
            raise CheckJobError(f"Unknown check type(s): {', '.join(invalid)}")

        spec = CheckJobSpec(
            scope=scope,
            project_path=str(project.path),
            chapters=tuple(requested),
            chapter_verses={ch: list(project.verses(ch)) for ch in requested},
            checks=selected_checks,
        )
        return self._start_check_job_from_spec(spec, project)

    def _start_check_job_from_spec(
        self, spec: CheckJobSpec, project: TranslationCoreProject,
    ) -> dict[str, Any]:
        def run_stage(chapter: str, verse: str, stage_checks: list[str]) -> list[dict[str, Any]]:
            with self._checker_lock:
                return [
                    finding.to_dict()
                    for finding in self._run_verse_checks_for_project(
                        project, chapter, verse, stage_checks,
                    )
                ]

        preflight = None
        if any(name in spec.checks for name in ("local", "tN", "tW", "usfm", "names")):
            def run_preflight(cancel_event: threading.Event) -> None:
                with self._checker_lock:
                    if any(name in spec.checks for name in ("local", "tN", "tW")):
                        self._ensure_resource_indexes(project)
                    if cancel_event.is_set():
                        return
                    if any(name in spec.checks for name in ("local", "usfm")):
                        self._usfm_findings_for_book(project, cancel_event=cancel_event)
                    if cancel_event.is_set():
                        return
                    if any(name in spec.checks for name in ("local", "names")):
                        # Unlike USFM's subprocess, this is in-process pure
                        # Python with no mid-flight cancellation support yet
                        # — it either hasn't started (skipped by the check
                        # above) or runs to completion. Acceptable for now;
                        # revisit if real book-sized timing (see
                        # docs/BUILD_LOG.md's Phase 5 section) shows
                        # this needs the same cooperative-cancel treatment
                        # USFM's subprocess has.
                        self._names_findings_for_book(project)
            preflight = run_preflight

        return self._check_jobs.start(
            spec, run_stage=run_stage, preflight=preflight,
        )

    def check_job_status(self, job_id: str = "") -> dict[str, Any]:
        return self._check_jobs.status(job_id)

    def cancel_check_job(self, job_id: str = "") -> dict[str, Any]:
        return self._check_jobs.cancel(job_id)

    def retry_check_job(self, job_id: str) -> dict[str, Any]:
        self._require_project()
        spec = self._check_jobs.spec_for_retry(job_id)
        if str(self.project.path) != spec.project_path:
            raise CheckJobConflict("The project changed; start a new check job instead.")
        return self._start_check_job_from_spec(spec, self.project)

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
        """Human-authorized scripture edit.

        tc_project.TranslationCoreProject.apply_scripture_edit() already
        implements the real, tC-compatible write: updates the target chapter
        JSON, reconciles alignment (keeps bottomWords tokens that still
        exist in the new text by word/occurrence signature, moves the rest
        to wordBank), marks word alignment invalid (surfaced by local_checks'
        existing WA_INVALID check), flags touched tN/tW index entries
        verseEdits=True, and runs it all through its own TransactionJournal
        transaction with rollback on failure — undoable and crash-safe.
        Nothing here reinvents that; it only calls it."""
        self._require_project()
        result = self.project.apply_scripture_edit(chapter, verse, new_text)
        return {"committed": True, "chapter": chapter, "verse": verse, **result}

    # -- export -------------------------------------------------------------
    #
    # Raw imports preserve their original USFM alongside the normalized tC
    # project. Use that file as a structural template so headings, poetry,
    # footnotes, custom/ESFM markers, and verse bridges survive export. The
    # normalized target chapter JSON supplies each current verse payload,
    # which also removes imported USFM 3 alignment milestones. Older tC
    # projects without a source USFM still receive an explicit simplified
    # reconstruction rather than failing export altogether.

    def _source_preserving_usfm(
        self, verse_renderer: Optional[Callable[[str, str], str]] = None,
    ) -> str | None:
        source_path = self.project.usfm_path()
        if source_path is None:
            return None
        try:
            raw_source = source_path.read_bytes()
        except OSError:
            return None
        source = ""
        for encoding in ("utf-8-sig", "utf-16", "utf-16-le", "utf-16-be"):
            try:
                candidate = raw_source.decode(encoding)
            except UnicodeError:
                continue
            if "\\c" in candidate and "\\v" in candidate:
                source = candidate
                break
        if not source:
            return None
        # Avoid mixed or doubled CRLF when the rendered string is written
        # through Python's platform-aware text layer on Windows.
        source = source.replace("\r\n", "\n").replace("\r", "\n")

        chapter_pattern = re.compile(
            r"(?im)^[ \t]*\\c\s+(?P<number>\S+)(?:[ \t].*)?(?:\r?\n|$)"
        )
        verse_pattern = re.compile(
            r"(?im)^[ \t]*\\v\s+(?P<number>\S+)(?P<separator>[ \t]*)"
        )
        chapters = list(chapter_pattern.finditer(source))
        verses = list(verse_pattern.finditer(source))
        if not chapters or not verses:
            return None

        replacements: list[tuple[int, int, str]] = []
        chapter_index = -1
        available_chapters = set(self.project.chapters())
        verse_cache: dict[str, set[str]] = {}
        for verse_index, verse_match in enumerate(verses):
            while (
                chapter_index + 1 < len(chapters)
                and chapters[chapter_index + 1].start() < verse_match.start()
            ):
                chapter_index += 1
            if chapter_index < 0:
                continue
            chapter = chapters[chapter_index].group("number")
            verse = verse_match.group("number")
            if chapter not in available_chapters:
                continue
            chapter_verses = verse_cache.setdefault(chapter, set(self.project.verses(chapter)))
            if verse not in chapter_verses:
                continue

            next_verse = (
                verses[verse_index + 1].start()
                if verse_index + 1 < len(verses)
                else len(source)
            )
            next_chapter = (
                chapters[chapter_index + 1].start()
                if chapter_index + 1 < len(chapters)
                else len(source)
            )
            content_end = min(next_verse, next_chapter)
            current_text = (
                verse_renderer(chapter, verse)
                if verse_renderer is not None
                else self.project.target_verse_text(chapter, verse)
            ).strip()
            if current_text and not verse_match.group("separator"):
                current_text = " " + current_text
            replacements.append(
                (verse_match.end(), content_end, current_text.rstrip() + "\n")
            )

        if not replacements:
            return None
        pieces: list[str] = []
        cursor = 0
        for start, end, replacement in replacements:
            pieces.extend((source[cursor:start], replacement))
            cursor = end
        pieces.append(source[cursor:])
        rendered = "".join(pieces)
        return rendered if rendered.endswith("\n") else rendered + "\n"

    def export_non_aligned(self, output_path: str) -> dict[str, Any]:
        """Write current verse text as non-aligned, re-importable USFM."""
        self._require_project()
        summary = self.project.summary
        content = self._source_preserving_usfm()
        fidelity = "source-preserving"
        if content is None:
            fidelity = "simplified"
            lines = [f"\\id {summary.book_id.upper()}"]
            for chapter in self.project.chapters():
                lines.append(f"\\c {chapter}")
                for verse in self.project.verses(chapter):
                    if verse == "front":
                        continue
                    text = self.project.target_verse_text(chapter, verse)
                    lines.append(f"\\v {verse} {text}")
            content = "\n".join(lines) + "\n"
        Path(output_path).write_text(content, encoding="utf-8")
        return {
            "written": True, "path": output_path,
            "bookId": summary.book_id, "chapters": len(self.project.chapters()),
            "fidelity": fidelity,
            "note": (
                "Original USFM structure preserved with current verse text."
                if fidelity == "source-preserving"
                else "No source USFM was available; generated id/chapter/verse markers only."
            ),
        }

    def export_aligned(self, output_path: str) -> dict[str, Any]:
        """Write interoperable aligned USFM 3.

        A `.json` destination remains supported for backward compatibility
        with the earlier diagnostic export, but the desktop now defaults to
        `.usfm` and emits unfoldingWord-compatible `zaln`/`w` markers.
        """
        self._require_project()
        if Path(output_path).suffix.lower() == ".json":
            return self._export_alignment_json(output_path)
        summary = self.project.summary
        book = summary.book_id

        def render(chapter: str, verse: str) -> str:
            try:
                return render_aligned_verse(
                    self.project.target_verse_text(chapter, verse),
                    self.project.load_verse_alignment(chapter, verse),
                )
            except AlignedUsfmError as exc:
                raise ProjectError(
                    f"Cannot export aligned USFM at {book.upper()} {chapter}:{verse}: {exc}"
                ) from exc

        content = self._source_preserving_usfm(render)
        fidelity = "source-preserving"
        if content is None:
            fidelity = "simplified"
            lines = [f"\\id {book.upper()}", "\\usfm 3.0"]
            for chapter in self.project.chapters():
                lines.append(f"\\c {chapter}")
                for verse in self.project.verses(chapter):
                    if verse == "front":
                        continue
                    lines.append(f"\\v {verse} {render(chapter, verse)}")
            content = "\n".join(lines) + "\n"
        version_pattern = re.compile(r"(?im)^[ \t]*\\usfm\s+\S+[^\r\n]*$")
        if version_pattern.search(content):
            content = version_pattern.sub(r"\\usfm 3.0", content, count=1)
        else:
            id_line = re.search(r"(?im)^[ \t]*\\id\s+[^\r\n]*(?:\r?\n|$)", content)
            insert_at = id_line.end() if id_line else 0
            content = content[:insert_at] + "\\usfm 3.0\n" + content[insert_at:]
        Path(output_path).write_text(content, encoding="utf-8")
        status = self.alignment_status()
        return {
            "written": True, "path": output_path, "bookId": book,
            "chapters": len(self.project.chapters()), "format": "usfm3-aligned",
            "fidelity": fidelity, "alignmentStatus": status["counts"],
        }

    def _export_alignment_json(self, output_path: str) -> dict[str, Any]:
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
                "chapters": len(self.project.chapters()), "format": "alignment-json"}

    # -- versification ------------------------------------------------------

    def _book_verse_text_map(self, project: TranslationCoreProject) -> dict[str, str]:
        result: dict[str, str] = {}
        for chapter in project.chapters():
            for verse in project.verses(chapter):
                text = project.target_verse_text(chapter, verse)
                if text:
                    result[f"{chapter}:{verse}"] = text
        return result

    def detect_versification(self) -> dict[str, Any]:
        """Sniff which of the six standard schemas this book's verse
        numbering best matches, e.g. distinguishing an 'eng'-numbered Psalter
        from an 'org' one. Cached per project path — cheap (in-memory dict
        scans, not a subprocess) but still whole-book work, so this is
        computed once on first request rather than on every project.open."""
        self._require_project()
        book_key = str(self.project.path)
        cached = self._versification_by_book.get(book_key)
        if cached is not None:
            return cached
        if not versification_tool.is_available():
            result = {"available": False}
        else:
            verses = self._book_verse_text_map(self.project)
            result = versification_tool.detect_schema(self.project.book_id, verses)
            result["available"] = True
        self._versification_by_book[book_key] = result
        return result

    def versification_org_ref(self, chapter: str, verse: str, schema: str = "") -> dict[str, Any]:
        """Normalize one chapter:verse into its 'org' (Hebrew/Greek) ref.
        Defaults to the project's own detected schema when none is given."""
        self._require_project()
        effective_schema = schema or self.detect_versification().get("bestSchema") or "eng"
        return versification_tool.to_org_ref(
            self.project.book_id, chapter, verse, effective_schema,
        )

    def versification_back_map(self, schema: str = "") -> dict[str, Any]:
        """org ref -> project-schema ref for every org verse in this book,
        so callers can display/export references the way the project
        actually numbers them."""
        self._require_project()
        effective_schema = schema or self.detect_versification().get("bestSchema") or "eng"
        return {
            "schema": effective_schema,
            "map": versification_tool.back_versification_map(self.project.book_id, effective_schema),
        }

    # -- alignment corpus statistics (Phase 6) -----------------------------

    def _corpus_stats_for_book(self) -> corpus_stats_tool.CorpusStatsTable:
        self._require_project()
        book_key = str(self.project.path)
        cached = self._corpus_stats_by_book.get(book_key)
        if cached is not None:
            return cached
        table = corpus_stats_tool.build_corpus_stats(self.project, include_collection=True)
        self._corpus_stats_by_book[book_key] = table
        return table

    def corpus_stats_summary(self) -> dict[str, Any]:
        """Aggregate counts over every completed verse in the open book's
        whole collection (see alignment_statistics.build_corpus_stats) —
        cheap introspection so a caller can tell whether there's enough
        approved data yet for per-verse stats to be meaningful."""
        table = self._corpus_stats_for_book()
        return {
            "booksScanned": table.books_scanned,
            "versesScanned": table.verses_scanned,
            "distinctSourceTypes": len(table.source_counts),
            "distinctTargetTypes": len(table.target_counts),
            "distinctPairs": len(table.pair_counts),
            "totalLinkInstances": table.total_pairs,
        }

    def corpus_stats_for_verse(self, chapter: str, verse: str) -> dict[str, Any]:
        """Corpus-wide count/probability/PMI (and, when Uroman + the
        vendored Smart Edit Distance are available, a phonetic-boosted
        probability for sparse pairs) for every top<->bottom link in one
        verse's CURRENT alignment groups. Works on a verse that isn't
        complete yet — useful while still aligning it, to see how the
        current groupings compare to the rest of the corpus. Read-only:
        never mutates the alignment, and never counts the verse's OWN links
        against itself beyond however build_corpus_stats already counted
        them if this same verse happens to be complete (no leave-one-out
        adjustment — this reports, it doesn't iteratively retrain)."""
        self._require_project()
        table = self._corpus_stats_for_book()
        alignment = self.project.load_verse_alignment(chapter, verse)
        pairs: list[dict[str, Any]] = []
        for group in alignment.alignments:
            if not group.top_words or not group.bottom_words:
                continue
            for top in group.top_words:
                for bottom in group.bottom_words:
                    stats = table.pair_stats(top.word, bottom.word)
                    pairs.append(stats.to_dict())
        return {"chapter": str(chapter), "verse": str(verse), "pairs": pairs}

    # -- settings ---------------------------------------------------------

    def get_settings(self) -> dict[str, Any]:
        return {
            "provider": self.settings.provider,
            "apiBaseUrl": self.settings.api_base_url,
            "model": self.settings.model,
            "reviewerName": self.settings.reviewer_name,
            "reviewerMode": self.settings.reviewer_mode,
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
        if "reviewerMode" in kwargs:
            self.settings.reviewer_mode = kwargs["reviewerMode"]
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
                return EngineResponse.ok(request.id, result=self.open_project(
                    p["path"], p.get("projectId", ""),
                ))
            if m == Methods.PROJECT_LIST:
                return EngineResponse.ok(request.id, result=self.list_projects())
            if m == Methods.PROJECT_FORGET:
                return EngineResponse.ok(request.id, result=self.forget_project(p.get("projectId", "")))
            if m == Methods.PROJECT_DELETE:
                return EngineResponse.ok(request.id, result=self.delete_project(p.get("projectId", "")))
            if m == Methods.PROJECT_SCAN:
                return EngineResponse.ok(request.id, result=self.scan_project())
            if m == Methods.PROJECT_INSPECT_IMPORT:
                return EngineResponse.ok(request.id, result=self.inspect_project_import(
                    p["path"], p.get("metadata"),
                ))
            if m == Methods.PROJECT_IMPORT:
                return EngineResponse.ok(request.id, result=self.import_project(
                    p["path"], p.get("metadata", {}), p.get("destinationRoot", ""),
                    bool(p.get("allowDuplicate", False)),
                ))
            if m == Methods.CHAPTER_VERSES:
                return EngineResponse.ok(request.id, result={"verses": self.chapter_verses(p["chapter"])})
            if m == Methods.CHAPTER_VERSE_DATA:
                return EngineResponse.ok(request.id, result=self.get_chapter_verse_data(p["chapter"]))
            if m == Methods.CHECKS_START:
                return EngineResponse.ok(request.id, result=self.start_check_job(
                    scope=p.get("scope", "chapter"),
                    chapters=p.get("chapters"),
                    checks=p.get("checks"),
                ))
            if m == Methods.CHECKS_STATUS:
                return EngineResponse.ok(
                    request.id, result=self.check_job_status(p.get("jobId", "")),
                )
            if m == Methods.CHECKS_CANCEL:
                return EngineResponse.ok(
                    request.id, result=self.cancel_check_job(p.get("jobId", "")),
                )
            if m == Methods.CHECKS_RETRY:
                return EngineResponse.ok(
                    request.id, result=self.retry_check_job(p["jobId"]),
                )
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
            if m == Methods.CHECK_LIST_FOR_VERSE:
                return EngineResponse.ok(request.id, result=self.list_checks_for_verse(
                    p["chapter"], p["verse"],
                ))
            if m == Methods.CHECK_VALIDATE_SELECTION:
                return EngineResponse.ok(request.id, result=self.validate_check_selection(
                    p["chapter"], p["verse"], p["tool"], p["groupId"], p["checkId"],
                    p.get("selections", []), p.get("nothingToSelect", False),
                ))
            if m == Methods.CHECK_SAVE_SELECTION:
                return EngineResponse.ok(request.id, result=self.save_check_selection(
                    p["chapter"], p["verse"], p["tool"], p["groupId"], p["checkId"],
                    p.get("selections", []), p.get("nothingToSelect", False),
                    p.get("provenance", "human"), p.get("expectedFingerprint", ""),
                    p.get("metadata"),
                ))
            if m == Methods.CHECK_CLEAR_SELECTION:
                return EngineResponse.ok(request.id, result=self.clear_check_selection(
                    p["chapter"], p["verse"], p["tool"], p["groupId"], p["checkId"],
                    p.get("provenance", "human"), p.get("expectedFingerprint", ""),
                    p.get("metadata"),
                ))
            if m == Methods.ALIGNMENT_GET:
                return EngineResponse.ok(
                    request.id, result=self.get_alignment(p["chapter"], p["verse"]),
                )
            if m == Methods.ALIGNMENT_STATUS:
                return EngineResponse.ok(
                    request.id, result=self.alignment_status(p.get("chapter", "")),
                )
            if m == Methods.ALIGNMENT_REALIGN:
                return EngineResponse.ok(request.id, result=self.realign_words(
                    p["chapter"], p["verse"], p.get("topIds", []), p.get("bottomIds", []),
                    p["expectedOriginal"],
                ))
            if m == Methods.ALIGNMENT_UNALIGN:
                return EngineResponse.ok(request.id, result=self.unalign_words(
                    p["chapter"], p["verse"], p.get("bottomIds", []), p["expectedOriginal"],
                ))
            if m == Methods.ALIGNMENT_SAVE:
                return EngineResponse.ok(request.id, result=self.save_alignment(
                    p["chapter"], p["verse"], p["alignment"], p["expectedOriginal"],
                ))
            if m == Methods.ALIGNMENT_COMPLETE:
                return EngineResponse.ok(
                    request.id, result=self.complete_alignment(p["chapter"], p["verse"]),
                )
            if m == Methods.ALIGNMENT_UNDO:
                return EngineResponse.ok(request.id, result=self.undo_alignment(
                    p["chapter"], p["verse"], p["expectedOriginal"],
                ))
            if m == Methods.ALIGNMENT_BACKUPS:
                context = self.get_alignment(p["chapter"], p["verse"])
                return EngineResponse.ok(request.id, result={"history": context["history"]})
            if m == Methods.ALIGNMENT_RESTORE:
                return EngineResponse.ok(request.id, result=self.undo_alignment(
                    p["chapter"], p["verse"], p["expectedOriginal"], p["historyId"],
                ))
            if m == Methods.SETTINGS_GET:
                return EngineResponse.ok(request.id, result=self.get_settings())
            if m == Methods.SETTINGS_SET:
                return EngineResponse.ok(request.id, result=self.set_settings(**p))
            if m == Methods.EXPORT_ALIGNED:
                return EngineResponse.ok(request.id, result=self.export_aligned(p["outputPath"]))
            if m == Methods.EXPORT_NON_ALIGNED:
                return EngineResponse.ok(request.id, result=self.export_non_aligned(p["outputPath"]))
            if m == Methods.VERSIFICATION_DETECT:
                return EngineResponse.ok(request.id, result=self.detect_versification())
            if m == Methods.VERSIFICATION_ORG_REF:
                return EngineResponse.ok(request.id, result=self.versification_org_ref(
                    p["chapter"], p["verse"], p.get("schema", ""),
                ))
            if m == Methods.VERSIFICATION_BACK_MAP:
                return EngineResponse.ok(
                    request.id, result=self.versification_back_map(p.get("schema", "")),
                )
            if m == Methods.ALIGNMENT_CORPUS_STATS_SUMMARY:
                return EngineResponse.ok(request.id, result=self.corpus_stats_summary())
            if m == Methods.ALIGNMENT_CORPUS_STATS_FOR_VERSE:
                return EngineResponse.ok(request.id, result=self.corpus_stats_for_verse(
                    p["chapter"], p["verse"],
                ))
            if m == Methods.ALIGNMENT_AI_PROPOSE:
                return EngineResponse.ok(request.id, result=self.propose_ai_alignment(
                    p["chapter"], p["verse"], p.get("mode", "gap_fill"),
                ))
            if m == Methods.ALIGNMENT_AI_APPLY_PROPOSAL:
                return EngineResponse.ok(request.id, result=self.apply_ai_alignment_proposal(
                    p["chapter"], p["verse"], p["proposal"], p["expectedOriginal"],
                ))
            if m == Methods.AI_EXPLAIN_VERSE:
                return EngineResponse.ok(request.id, result=self.explain_verse(p["chapter"], p["verse"]))
            if m == Methods.AI_REVIEW_START:
                return EngineResponse.ok(request.id, result=self.start_ai_review_job(
                    p.get("scope", "verse"), p.get("chapter", ""), p.get("verse", ""),
                    p.get("mode", ""),
                ))
            if m == Methods.AI_REVIEW_STATUS:
                return EngineResponse.ok(
                    request.id, result=self.ai_review_job_status(p.get("jobId", "")),
                )
            if m == Methods.AI_REVIEW_CANCEL:
                return EngineResponse.ok(
                    request.id, result=self.cancel_ai_review_job(p.get("jobId", "")),
                )
            if m == Methods.AI_REVIEW_RETRY:
                return EngineResponse.ok(
                    request.id, result=self.retry_ai_review_job(p["jobId"]),
                )
            if m == Methods.AI_REVIEW_LIST_CHAPTER:
                return EngineResponse.ok(
                    request.id, result=self.list_ai_reviews_for_chapter(p["chapter"]),
                )
            if m == Methods.PARATEXT_GET_STATE:
                return EngineResponse.ok(request.id, result=self.paratext_get_state())
            if m == Methods.PARATEXT_SET_REFERENCE:
                return EngineResponse.ok(request.id, result=self.paratext_set_reference(
                    p["reference"], p.get("originId", ""),
                ))
            if m == Methods.LOGOS_GET_STATE:
                return EngineResponse.ok(request.id, result=self.logos_get_state())
            if m == Methods.LOGOS_SET_REFERENCE:
                return EngineResponse.ok(request.id, result=self.logos_set_reference(
                    p["reference"], p.get("originId", ""),
                ))

            return EngineResponse.fail(request.id, "unknown_method", f"No handler for '{m}'")
        except ProjectError as exc:
            return EngineResponse.fail(request.id, "project_error", str(exc))
        except AlignmentError as exc:
            return EngineResponse.fail(request.id, "alignment_error", str(exc))
        except AIError as exc:
            return EngineResponse.fail(request.id, "ai_error", str(exc))
        except KnowledgeBaseError as exc:
            return EngineResponse.fail(request.id, "knowledge_base_error", str(exc))
        except ParatextConnectorError as exc:
            return EngineResponse.fail(request.id, "paratext_connector_error", str(exc))
        except LogosConnectorError as exc:
            return EngineResponse.fail(request.id, "logos_connector_error", str(exc))
        except UsfmCheckerError as exc:
            return EngineResponse.fail(request.id, "checker_error", str(exc))
        except versification_tool.VersificationUnavailable as exc:
            return EngineResponse.fail(request.id, "versification_unavailable", str(exc))
        except CheckJobNotFound as exc:
            return EngineResponse.fail(request.id, "job_not_found", str(exc))
        except CheckJobConflict as exc:
            return EngineResponse.fail(request.id, "job_conflict", str(exc))
        except CheckJobError as exc:
            return EngineResponse.fail(request.id, "job_error", str(exc))
        except AIReviewJobNotFound as exc:
            return EngineResponse.fail(request.id, "ai_job_not_found", str(exc))
        except AIReviewJobConflict as exc:
            return EngineResponse.fail(request.id, "ai_job_conflict", str(exc))
        except AIReviewJobError as exc:
            return EngineResponse.fail(request.id, "ai_job_error", str(exc))
        except Exception as exc:  # noqa: BLE001 - protocol boundary must never crash the sidecar
            return EngineResponse.fail(request.id, "internal_error", str(exc))
