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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from greek_room_engine.engine import GreekRoomEngine
from greek_room_engine.adapters.usfm_adapter import UsfmCheckerCancelled, UsfmCheckerError
from greek_room_engine.adapters.names_adapter import NamesCheckError
from greek_room_engine.models.finding import QaFinding, FindingCategory, Severity, FindingStatus, EvidenceItem
from greek_room_engine.protocol import EngineRequest, EngineResponse

from tc_ai_bridge.tc_project import TranslationCoreProject, ProjectError, read_progress_rollup
from tc_ai_bridge.project_import import (
    apply_resource_materialization,
    collection_projects,
    ensure_bridge_original_language,
    import_source,
    inspect_import,
    materialize_lazy_project,
)
from tc_ai_bridge.original_language_resources import resource_inventory
from tc_ai_bridge.lexicon_resources import lexicon_entry_for_strong, HEBREW_PREFIX_LABELS
from tc_ai_bridge.morphology_codes import decode_morph
from tc_ai_bridge.project_registry import ProjectIdentityError, ProjectRegistry, source_fingerprints
from tc_ai_bridge.passage_semantic_repository import (
    FoundationConflict,
    FoundationValidationError,
)
from tc_ai_bridge.passage_semantic_runtime import PassageSemanticRuntime
from tc_ai_bridge.analysis_jobs import (
    AnalysisJobConflict,
    AnalysisJobError,
    AnalysisJobManager,
    AnalysisJobNotFound,
)
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
from tc_ai_bridge.navigation import NavigationSyncCoordinator
from tc_ai_bridge.models import QAIssue, TokenRef, VerseAlignment
from tc_ai_bridge.secret_store import AppSettings
from tc_ai_bridge.resource_materializer import materialize_book_checks
from tc_ai_bridge.usfm import whitespace_tokens
from tc_ai_bridge import versification as versification_tool
from tc_ai_bridge import alignment_statistics as corpus_stats_tool
from tc_ai_bridge.reporting import ReportService
from tc_ai_bridge.verse_evidence import resolve_verse_evidence
from tc_ai_bridge.semantic_mapping_service import semantic_mappings_for_verse, confirm_semantic_mapping
from tc_ai_bridge.semantic_validation_service import (
    decide_semantic_validation_candidate, list_semantic_validation_candidates,
)
from tc_ai_bridge.semantic_mapping_bridge import prepare_semantic_mappings_for_review
from tc_ai_bridge.semantic_review_policy import native_tc_apply_allowed
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
from project_sweep import (
    ProjectSweepManager,
    SweepBook,
    SweepConflict,
    SweepError,
    SweepNotFound,
)

BRIDGE_VERSION = "0.8.0-beta.13"

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


_WHITESPACE_TOKEN_TRIM_CHARS = ' \t\r\n.,;:!?“”‘’"\'()[]{}<>—–…।॥'


def _first_token_span(text: str, token: str) -> Optional[tuple[int, int]]:
    """Locate `token`'s first whole-word occurrence in `text`, using the
    same whitespace + punctuation-trim boundary rule as tc_ai_bridge.usfm's
    whitespace_tokens — but computed directly against the caller's raw
    string rather than that function's strip_usfm()'d copy, since the
    result must index into the exact same string a QaFinding's
    start_offset/end_offset is highlighted against on the frontend, and
    strip_usfm's whitespace collapsing can shift character positions."""
    for match in re.finditer(r"\S+", text):
        raw = match.group()
        stripped = raw.strip(_WHITESPACE_TOKEN_TRIM_CHARS)
        if stripped != token:
            continue
        offset = raw.index(stripped)
        start = match.start() + offset
        return start, start + len(stripped)
    return None


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
                         chapter: str, verse: str,
                         resource_versions: dict[str, str] | None = None) -> QaFinding:
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
        resource_versions=dict(resource_versions) if resource_versions else {},
    )


class Methods:
    PING = "ping"
    ENGINE_INFO = "engine.info"

    PROJECT_OPEN = "project.open"
    PROJECT_LIST = "project.list"
    PROJECT_LIST_BOOK_PROGRESS = "project.listBookProgress"
    PROJECT_FORGET = "project.forget"
    PROJECT_DELETE = "project.delete"
    PROJECT_SCAN = "project.scan"
    PROJECT_REPORT = "project.report"
    PROJECT_SWEEP_START = "project.sweepStart"
    PROJECT_SWEEP_STATUS = "project.sweepStatus"
    PROJECT_SWEEP_CANCEL = "project.sweepCancel"
    PROJECT_COLLECTION_REPORT = "project.collectionReport"
    PROJECT_INSPECT_IMPORT = "project.inspectImport"
    PROJECT_IMPORT = "project.import"
    CHAPTER_VERSES = "chapter.verses"
    CHAPTER_VERSE_DATA = "chapter.verseData"

    CHECKS_START = "checks.start"
    CHECKS_STATUS = "checks.status"
    CHECKS_CANCEL = "checks.cancel"
    CHECKS_RETRY = "checks.retry"

    VERSE_GET = "verse.get"
    VERSE_EVIDENCE = "verse.evidence"
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

    LEXICON_GET_ENTRY = "lexicon.getEntry"

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

    SEMANTIC_MAPPING_GET_FOR_VERSE = "semanticMapping.getForVerse"
    SEMANTIC_MAPPING_CONFIRM = "semanticMapping.confirm"
    SEMANTIC_MAPPING_RERUN_FOR_VERSE = "semanticMapping.rerunForVerse"
    SEMANTIC_VALIDATION_LIST = "semanticValidation.list"
    SEMANTIC_VALIDATION_DECIDE = "semanticValidation.decide"
    PASSAGE_SEMANTIC_STATUS = "passageSemantic.status"
    PASSAGE_SEMANTIC_PROJECT_METADATA = "passageSemantic.getProjectMetadata"
    PASSAGE_SEMANTIC_CURRENT_PASSAGE = "passageSemantic.getCurrentPassage"
    PASSAGE_SEMANTIC_STALE_SUMMARY = "passageSemantic.getStaleSummary"
    PASSAGE_SEMANTIC_MIGRATION_REPORT = "passageSemantic.getMigrationReport"
    PASSAGE_SEMANTIC_REBUILD_PASSAGE = "passageSemantic.rebuildCurrentPassage"
    SOURCE_SEMANTIC_BUILD_RANGE = "sourceSemantic.buildRange"
    SOURCE_SEMANTIC_GET_RANGE = "sourceSemantic.getRange"
    SOURCE_SEMANTIC_GET_UNIT = "sourceSemantic.getUnit"
    SOURCE_SEMANTIC_GET_COVERAGE_ACCOUNTS = "sourceSemantic.getCoverageAccounts"
    SOURCE_SEMANTIC_GET_DIAGNOSTICS = "sourceSemantic.getDiagnostics"
    TARGET_SEMANTIC_BUILD_RANGE = "targetSemantic.buildRange"
    TARGET_SEMANTIC_GET_RANGE = "targetSemantic.getRange"
    TARGET_SEMANTIC_GET_UNIT = "targetSemantic.getUnit"
    TARGET_SEMANTIC_GET_DIAGNOSTICS = "targetSemantic.getDiagnostics"
    TARGET_SEMANTIC_GET_SEARCH_SPANS = "targetSemantic.getSearchSpans"
    TARGET_SEMANTIC_GET_CAPABILITIES = "targetSemantic.getCapabilities"
    SEMANTIC_LOCATION_RUN_RANGE = "semanticLocation.runRange"
    SEMANTIC_LOCATION_STATUS = "semanticLocation.status"
    SEMANTIC_LOCATION_GET_RANGE = "semanticLocation.getRange"
    SEMANTIC_LOCATION_GET_RELATIONSHIP = "semanticLocation.getRelationship"
    SEMANTIC_LOCATION_GET_CANDIDATES = "semanticLocation.getCandidates"
    SEMANTIC_LOCATION_GET_DIAGNOSTICS = "semanticLocation.getDiagnostics"
    MEANING_ANALYSIS_RUN_RANGE = "meaningAnalysis.runRange"
    MEANING_ANALYSIS_STATUS = "meaningAnalysis.status"
    MEANING_ANALYSIS_GET_RANGE = "meaningAnalysis.getRange"
    MEANING_ANALYSIS_GET_ASSESSMENT = "meaningAnalysis.getAssessment"
    MEANING_ANALYSIS_GET_COMPONENTS = "meaningAnalysis.getComponents"
    MEANING_ANALYSIS_GET_DIAGNOSTICS = "meaningAnalysis.getDiagnostics"
    QA_AUDIT_RUN_RANGE = "qaAudit.runRange"
    QA_AUDIT_STATUS = "qaAudit.status"
    QA_AUDIT_GET_RANGE = "qaAudit.getRange"
    QA_AUDIT_GET_SOURCE_COVERAGE = "qaAudit.getSourceCoverage"
    QA_AUDIT_GET_TARGET_SUPPORT = "qaAudit.getTargetSupport"
    QA_AUDIT_GET_FINDING = "qaAudit.getFinding"
    QA_AUDIT_GET_DIAGNOSTICS = "qaAudit.getDiagnostics"
    QA_REVIEW_GET_QUEUE = "qaReview.getQueue"
    QA_REVIEW_GET_FINDING = "qaReview.getFinding"
    QA_REVIEW_DECIDE_FINDING = "qaReview.decideFinding"
    QA_REVIEW_ADD_NOTE = "qaReview.addNote"
    SEMANTIC_REVIEW_DECIDE_LOCATION = "semanticReview.decideLocation"
    SEMANTIC_REVIEW_DECIDE_MEANING = "semanticReview.decideMeaning"
    REVIEW_HISTORY_GET_ENTITY_HISTORY = "reviewHistory.getEntityHistory"
    ANALYSIS_JOB_START = "analysisJob.start"
    ANALYSIS_JOB_STATUS = "analysisJob.status"
    ANALYSIS_JOB_CANCEL = "analysisJob.cancel"
    ANALYSIS_JOB_GET_RECENT = "analysisJob.getRecent"
    ANALYSIS_JOB_GET_SCOPE_STATUS = "analysisJob.getScopeStatus"

    PARATEXT_GET_STATE = "paratext.getState"
    PARATEXT_SET_REFERENCE = "paratext.setReference"

    ISSUE_RESOLUTION_LIST = "issueResolution.list"
    ISSUE_RESOLUTION_SAVE = "issueResolution.save"
    ISSUE_RESOLUTION_QUEUE_PARATEXT = "issueResolution.queueParatext"
    ISSUE_RESOLUTION_RETRY_PARATEXT = "issueResolution.retryParatext"

    LOGOS_GET_STATE = "logos.getState"
    LOGOS_SET_REFERENCE = "logos.setReference"

    NAVIGATION_STATUS = "navigation.status"
    NAVIGATION_POLL = "navigation.poll"
    NAVIGATION_BRIDGE_CHANGED = "navigation.bridgeChanged"
    NAVIGATION_RESOLVE = "navigation.resolve"


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
        self.passage_semantic_runtime: PassageSemanticRuntime | None = None
        self._passage_semantic_status: dict[str, Any] = {
            "available": False, "readOnly": True, "state": "NO_PROJECT",
        }
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
        # Wildebeest findings have no whole-book cache: they're computed
        # live, per-verse, only when a user opens that verse in the editor
        # (ReviewPanel.svelte's runVerseChecks(["greekroom"]) on selection).
        # A whole-book Wildebeest cache was tried for the project report's
        # exception queue (issue #24) and reverted the same day — see
        # build_project_report's docstring for why computing it inline
        # there is unsafe (blocks the single-threaded stdio dispatcher).
        # Layer-2 corpus-consistency findings (see _consistency_findings_for_book)
        # — whole-book like USFM/names above, and for the same reason: this
        # scans every completed verse's alignment, too slow to redo per verse.
        self._consistency_findings_by_book: dict[str, list[QaFinding]] = {}
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
        self._analysis_jobs = AnalysisJobManager()
        self._project_sweep = ProjectSweepManager()
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

        # Connector I/O is deliberately performed by NavigationSyncCoordinator's
        # daemon probe rather than this service's single-threaded stdio request loop.
        self._navigation = NavigationSyncCoordinator(
            paratext_client=lambda: ParatextConnectorClient(),
            logos_client=self._logos_client_instance,
        )
        self._navigation.configure(
            paratext=self.settings.paratext_navigation,
            logos=self.settings.logos_navigation,
        )

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
        self._consistency_findings_by_book.clear()
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
        try:
            registered = self.project_registry.register(path, touch=True, project_id=project_id)
        except ProjectIdentityError as exc:
            raise ProjectError(str(exc)) from exc
        self.project = candidate
        self.passage_semantic_runtime = None
        self._passage_semantic_status = {
            "available": False, "readOnly": True, "state": "UNAVAILABLE",
        }
        try:
            runtime = PassageSemanticRuntime(candidate, str(registered["projectId"]))
            candidate.attach_passage_semantic_runtime(runtime)
            self.passage_semantic_runtime = runtime
            self._analysis_jobs.bind_runtime(runtime)
            self._passage_semantic_status = {"state": "READY", **runtime.status()}
        except Exception as exc:
            # Scripture/tC access remains fully usable. Semantic APIs expose the
            # recovery diagnostic rather than making project.open fail.
            candidate.attach_passage_semantic_runtime(None)
            self._passage_semantic_status = {
                "available": False, "readOnly": True,
                "state": "RECOVERY_REQUIRED", "error": str(exc),
            }
        info = self._project_info()
        siblings = collection_projects(path)
        if siblings:
            info["importedProjects"] = siblings
        info.update({
            "projectId": registered["projectId"],
            "collectionId": registered.get("collectionId", ""),
            "managed": registered.get("managed", False),
            "passageSemantic": dict(self._passage_semantic_status),
        })
        return info

    def list_projects(self) -> dict[str, Any]:
        return {"projects": self.project_registry.list_projects(collapse_collections=True)}

    def list_book_progress(self) -> dict[str, Any]:
        """Progress rollups for every book in the currently open collection,
        for the project dashboard. Lazy siblings are never materialized just
        to compute stats — their progress comes back null and the frontend
        renders a distinct 'not yet opened' state."""
        self._require_project()
        siblings = collection_projects(str(self.project.path))
        if not siblings:
            siblings = [{
                "path": str(self.project.path), "bookId": self.project.book_id,
                "bookName": self.project.summary.book_name, "lazy": False,
            }]
        books: list[dict[str, Any]] = []
        for entry in siblings:
            path = Path(str(entry.get("path") or ""))
            lazy = bool(entry.get("lazy"))
            progress = None
            missing = not path.is_dir()
            if not lazy and not missing:
                rollup = read_progress_rollup(path)
                if rollup is not None:
                    progress = {**rollup.get("totals", {}), "updatedAt": rollup.get("updatedAt")}
            books.append({
                "path": str(path), "bookId": str(entry.get("bookId") or ""),
                "bookName": str(entry.get("bookName") or ""), "lazy": lazy,
                "missing": missing, "progress": progress,
            })
        return {"books": books}

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

    @staticmethod
    def _pinned_resource_versions(project: TranslationCoreProject) -> dict[str, str]:
        """Bundled-resource versions this project's tN/tW indexes and
        wordAlignment resources were built against, as already stamped on
        manifest.json by apply_resource_materialization/ensure_bridge_
        original_language. Absent for existing translationCore/
        translationStudio imports Bridge never materialized itself — that's
        an honest 'version not tracked', not an error."""
        manifest = project.manifest
        versions = {
            "translationNotes": manifest.get("tc_en_check_version_translationNotes"),
            "translationWords": manifest.get("tc_en_check_version_translationWords"),
            "originalLanguage": manifest.get("tc_orig_lang_check_version_wordAlignment"),
        }
        return {k: str(v) for k, v in versions.items() if v}

    def build_project_report(self) -> dict[str, Any]:
        """Deterministic QA/publication report for the current book, via the
        existing tc_ai_bridge.reporting.ReportService — never previously
        exposed over the protocol (see docs/BUILD_LOG.md). Book-scoped for
        now, same as ReportService itself; a whole-collection rollup is a
        separate, larger piece of work (multi-book aggregation).

        Deliberately does NOT warm the local-finding caches here (tried in
        issue #24, reverted the same day): the stdio dispatcher in
        stdio_transport.py is a single-threaded `for line in sys.stdin`
        loop — nothing else the sidecar does is concurrent with a request
        handler. project.report is called on every book/dashboard view, so
        synchronously computing whole-book USFM/Names/Wildebeest here (fast
        enough on a 1-2 verse test fixture to look fine) blocked the entire
        sidecar long enough on a real ~800-verse book (1 Samuel) that even
        an unrelated project.open for a different book queued behind it and
        timed out client-side. exception_first_queue still merges whatever
        local findings already happen to be cached (from a prior
        verse.runChecks/checks.start pass) — a book nobody has opened at
        all in this session just won't have any yet, same as before #24.
        Warming these safely needs a background job (CheckJobManager/
        AIReviewJobManager's own pattern), not inline in this handler.
        """
        self._require_project()
        return ReportService(self.project).build_book_report()

    def _sibling_sweep_books(self) -> list[SweepBook]:
        """Every book in the currently open collection, or just the current
        book when it isn't part of a multi-book collection — same sibling
        resolution list_book_progress already uses."""
        self._require_project()
        siblings = collection_projects(str(self.project.path))
        if not siblings:
            siblings = [{
                "path": str(self.project.path), "bookId": self.project.book_id,
                "bookName": self.project.summary.book_name, "lazy": False,
            }]
        books: list[SweepBook] = []
        for entry in siblings:
            path = str(entry.get("path") or "")
            if not Path(path).is_dir():
                continue  # a registered but missing sibling — nothing to sweep
            books.append(SweepBook(
                path=path, book_id=str(entry.get("bookId") or ""),
                book_name=str(entry.get("bookName") or ""),
            ))
        return books

    def _run_layer1_checks_for_book(self, book: SweepBook) -> tuple[list[dict[str, Any]], Optional[str]]:
        """USFM structure + names/spelling consistency + per-verse Wildebeest
        — the Layer-1 deterministic checks already used by verse.runChecks,
        run here against a freshly constructed TranslationCoreProject for
        ONE sibling book. Deliberately never touches self.project (the
        engine-wide 'open in the UI' slot), so this can run in the sweep's
        background thread while the user keeps editing whatever book they
        actually have open. Versification detection is intentionally not
        included: nothing in this codebase turns a versification mismatch
        into a QaFinding today (see versification_org_ref/back_map — those
        only normalize references), so 'checking' it here would mean
        inventing a new finding shape, out of scope for wiring up the
        existing checks project-wide.
        """
        materialize_lazy_project(book.path)
        project = TranslationCoreProject(book.path)
        project_id = str(project.summary.path)
        target = project.manifest.get("target_language", {})
        language_id = str(target.get("id") or "") if isinstance(target, dict) else ""

        findings: list[QaFinding] = list(self._usfm_findings_for_book(project=project))
        findings.extend(self._names_findings_for_book(project=project))

        text_map = self._book_verse_text_map(project)
        for ref, text in text_map.items():
            chapter, _, verse = ref.partition(":")
            gr_findings = self.greek_room.check_verse(
                project_id=project_id, lang_code=language_id,
                ref=f"{project.book_id} {chapter}:{verse}", text=text, checks=["wildebeest"],
            )
            for f in gr_findings:
                # Same stabilization as _run_verse_checks_for_project's
                # greekroom branch — keeps ids identical to what opening
                # this book normally and running checks verse-by-verse
                # would produce, so a sweep finding and a live-editor
                # finding for the same issue are the same finding.
                f.id = _stable_finding_id(
                    chapter=chapter, verse=verse, engine=f.engine, check_type=f.check_type,
                    disambiguator=f"{f.start_offset}:{f.end_offset}:{f.original_text}",
                )
            findings.extend(gr_findings)

        by_verse: dict[tuple[str, str], list[QaFinding]] = {}
        for f in findings:
            by_verse.setdefault((str(f.chapter), str(f.verse)), []).append(f)
        for (chapter, verse), verse_findings in by_verse.items():
            prior_decisions = project.qa_decisions_for_verse(chapter, verse)
            for f in verse_findings:
                record = prior_decisions.get(f.id)
                if record:
                    try:
                        f.status = FindingStatus(record.get("decision", "open"))
                    except ValueError:
                        pass
                    f.human_comment = record.get("note") or None

        return [f.to_dict() for f in findings], None

    def start_project_sweep(self) -> dict[str, Any]:
        """Kick off a background Layer-1 sweep across every book in the
        current collection. One sweep at a time (see ProjectSweepManager);
        does not conflict with a concurrent checks.* chapter/book job — a
        separate lock domain by design."""
        books = self._sibling_sweep_books()
        return self._project_sweep.start(books, run_book=self._run_layer1_checks_for_book)

    def project_sweep_status(self, job_id: str = "") -> dict[str, Any]:
        return self._project_sweep.status(job_id)

    def cancel_project_sweep(self, job_id: str = "") -> dict[str, Any]:
        return self._project_sweep.cancel(job_id)

    def build_collection_report(self) -> dict[str, Any]:
        """Project-level rollup across every book in the current collection
        -- builds each sibling's own build_book_report() (same reused
        TranslationCoreProject construction as _run_layer1_checks_for_book)
        and aggregates them with ReportService.build_collection_report.
        Synchronous: fine for a handful of books, but this does not solve
        the whole-Bible performance question (see issue #17) -- a 66-book
        collection sequentially building 66 full reports in one request
        could run long."""
        books = self._sibling_sweep_books()
        reports: list[dict[str, Any]] = []
        for book in books:
            materialize_lazy_project(book.path)
            reports.append(ReportService(TranslationCoreProject(book.path)).build_book_report())
        return ReportService.build_collection_report(reports)

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

    def get_verse_evidence(self, chapter: str, verse: str) -> dict[str, Any]:
        """Resolve one shared VerseEvidence for this verse (target text/
        tokens, source tokens, alignment, translation-helps evidence, human
        decisions — see tc_ai_bridge/verse_evidence.py's own docstring for
        what this does and doesn't replace) and attach the two pieces that
        module can't see on its own: current QaFindings and any cached AI
        review result, since only BridgeEngine composes both GreekRoomEngine
        and tc_ai_bridge."""
        self._require_project()
        project = self.project
        evidence = resolve_verse_evidence(
            project, chapter, verse,
            resource_versions=self._pinned_resource_versions(project),
        )
        findings = self.run_verse_checks(chapter, verse, ["local", "greekroom"])
        ai_review_state = project.ai_review_cache_status(chapter, verse)
        cached_ai_review = project.load_ai_review_result(chapter, verse) if ai_review_state == "current" else None

        result = evidence.to_dict()
        result["findings"] = [f.to_dict() for f in findings]
        result["aiReviewState"] = ai_review_state
        result["aiReview"] = cached_ai_review
        return result

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
            outcomes = dict((cached_ai or {}).get("automaticSelection") or {})
            for check in checks:
                identity = (str(check.get("tool") or ""), str(check.get("checkId") or ""))
                ai_item = ai_by_identity.get(identity)
                if ai_item:
                    check["evaluationStatus"] = evaluation.get(str(ai_item.get("verdict") or ""), "needs_review")
                elif ai_review_state == "stale":
                    check["evaluationStatus"] = "needs_review"
                outcome = outcomes.get(f"{identity[0]}:{identity[1]}")
                check["automaticSelection"] = (
                    {
                        "outcome": str(outcome.get("outcome") or ""),
                        "reason": str(outcome.get("reason") or ""),
                    }
                    if isinstance(outcome, dict) else None
                )
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
        accepted_advanced_proposal = (
            provenance == "human"
            and str((metadata or {}).get("interface") or "") == "advanced-ai-proposal"
            and bool((metadata or {}).get("acceptedAIProposal"))
        )
        if (
            accepted_advanced_proposal
            and nothing_to_select
            and str((metadata or {}).get("verdict") or "") == "problem"
        ):
            raise ProjectError(
                "An AI-reported translation problem cannot be saved as Nothing to Select. "
                "Leave it pending, select the affected target text, or resolve the issue."
            )
        with self._checker_lock:
            result = self.project.save_check_selection(
                chapter, verse, tool, group_id, check_id, selections, nothing_to_select,
                provenance, expected_fingerprint,
                username=self.settings.reviewer_name or "Bridge Reviewer",
                audit_metadata=metadata,
            )
            if provenance == "bridge_ai" or accepted_advanced_proposal:
                self.project.rebase_ai_review_fingerprint(chapter, verse)
                # In Advanced mode the model result remains advisory until the
                # reviewer explicitly applies it. That explicit mutation is the
                # human confirmation which may close a safely grounded pass.
                saved_ai = self.project.load_ai_review_result(chapter, verse) or {}
                if self.project.ai_review_cache_status(chapter, verse) == "current":
                    result["resolutionLifecycle"] = self.project.reconcile_issue_resolutions_after_ai_review(
                        chapter, verse, list(saved_ai.get("checkReviews") or []),
                        model=str(saved_ai.get("model") or ""),
                        summary=str(saved_ai.get("summary") or ""),
                        allow_automatic_resolution=True,
                    )
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

    def get_lexicon_entry(self, strong: str, morph: str) -> dict[str, Any]:
        """Look up lexicon glosses + decoded morphology for one source token.

        `strong` and `morph` come straight off an AlignmentToken; both may be
        compound (colon-joined) when the surface word is a lexeme plus a
        Hebrew proclitic prefix (e.g. strong "b:H7225", morph "He,R:Ncfsa") —
        this decodes and looks up each morpheme segment independently.
        """
        language_id, morph_segments = decode_morph(morph)
        strong_parts = [part for part in str(strong or "").split(":") if part]

        segment_count = max(len(strong_parts), len(morph_segments), 1)
        segments: list[dict[str, Any]] = []
        for index in range(segment_count):
            strong_part = strong_parts[index] if index < len(strong_parts) else ""
            morph_segment = morph_segments[index] if index < len(morph_segments) else None
            entry = (
                lexicon_entry_for_strong(strong_part, language_id)
                if strong_part and language_id else None
            )
            prefix_label = (
                HEBREW_PREFIX_LABELS.get(strong_part)
                if not entry and language_id == "hbo" else None
            )
            segments.append({
                "strong": strong_part or None,
                "morphLabel": morph_segment.label if morph_segment else None,
                "partOfSpeech": morph_segment.part_of_speech if morph_segment else None,
                "lemma": entry.get("lemma") if entry else None,
                "translit": entry.get("translit") if entry else None,
                "pron": entry.get("pron") if entry else None,
                "meaning": (entry.get("meaning") if entry else None) or prefix_label,
                "usage": entry.get("usage") if entry else None,
                "source": entry.get("derivation") if entry else None,
            })
        return {"languageId": language_id, "segments": segments}

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

    def _finish_alignment_mutation(self, chapter: str, verse: str) -> dict[str, Any]:
        """Shared tail for every alignment-mutating path (manual realign/unalign/save,
        AI auto-align, undo/restore): clear pending/invalid caches, then automatically
        mark the verse complete the moment every word is grouped — no separate human
        "Mark alignment complete" click. `mark_word_alignment_pending` runs first even
        when the verse turns out to still be complete, so an edit that keeps a
        previously human-completed verse fully aligned re-earns "completed" through
        the same check rather than leaving a stale marker in place.
        """
        self.project.mark_word_alignment_pending(chapter, verse)
        self._corpus_stats_by_book.pop(str(self.project.path), None)
        self._consistency_findings_by_book.pop(str(self.project.path), None)
        context = self._alignment_context(chapter, verse)
        if context["canComplete"] and context["completionState"] != "completed":
            self.project.mark_word_alignment_completed(
                chapter, verse, username=self.settings.reviewer_name or "Bridge Reviewer",
            )
            context = self._alignment_context(chapter, verse)
        return context

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
        return self._finish_alignment_mutation(chapter, verse)

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
        self._consistency_findings_by_book.pop(str(self.project.path), None)
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
        return self._finish_alignment_mutation(chapter, verse)

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
        and complete enough to write without asking.  The native persistence layer
        remains the final authority and independently blocks overwriting
        imported/human choices -- which is what makes running this unconditionally
        safe, including when the reviewer has manual override enabled and may edit
        the result afterwards.
        """
        if review.verdict not in {"pass", "problem", "not_applicable"}:
            return "AI verdict requires human review"
        if float(review.confidence or 0.0) < 0.82:
            return "AI confidence is below the 82% automatic-selection threshold"
        if not review.evidence_used:
            return "No bundled evidence was cited"
        selection_state = str(getattr(review, "selection_state", "") or "")
        if selection_state and not native_tc_apply_allowed(review):
            return "Stage 3 mapping is not safe for a verse-local automatic selection"
        if review.verdict == "not_applicable" and not review.nothing_to_select:
            return "Not-applicable verdict must explicitly select nothing"
        if review.nothing_to_select:
            if review.verdict == "problem":
                return "An unresolved translation problem cannot be completed as nothing-to-select"
            return "" if not review.proposed_selections else "Proposal contradicts nothing-to-select"
        if not review.proposed_selections:
            return "No exact target selection was proposed"
        return ""

    def _apply_safe_ai_selections(
        self,
        project: TranslationCoreProject,
        chapter: str,
        verse: str,
        reviews: list[Any],
        *,
        model: str,
        qa_issues: list[Any] | None = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        applied: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        qa_issues = list(qa_issues or [])
        for review in reviews:
            reason = self._safe_ai_selection_reason(review)
            identity = {
                "tool": review.tool, "groupId": review.group_id, "checkId": review.check_id,
            }
            contradictory = [
                issue for issue in qa_issues
                if (
                    str(getattr(issue, "check_id", "") or "") == str(review.check_id)
                    or (
                        not str(getattr(issue, "check_id", "") or "")
                        and str(getattr(issue, "group_id", "") or "") == str(review.group_id)
                    )
                )
                and str(getattr(issue, "severity", "") or "") in {"critical", "high", "medium"}
                and float(getattr(issue, "confidence", 0.0) or 0.0) >= 0.75
            ]
            if contradictory:
                reason = "Contradictory QA evidence requires human review"
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
                            "interface": "automatic", "model": model,
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
        # Written last so the reason a check stayed pending outlives this job
        # result and can be shown whenever the reviewer reopens the verse. Under
        # the same lock as the rebase above: both rewrite the one review record
        # that a concurrent list_checks_for_verse reads.
        with self._checker_lock:
            project.record_ai_selection_outcomes(chapter, verse, applied, skipped)
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
            project.mark_issue_resolutions_recheck(
                chapter, verse, "cancelled", reason="AI review was cancelled before this verse started.",
            )
            raise AIError("AI review cancelled before the verse started.")
        project.mark_issue_resolutions_recheck(
            chapter, verse, "running", reason="Automatic AI recheck started.",
        )
        try:
            with self._checker_lock:
                self._ensure_resource_indexes(project)
            client = self._ai_client()
            alignment = project.load_verse_alignment(chapter, verse)
            proposal, review_alignment, reviews, issues, summary, meta = client.prepare_verse_review(
                project, chapter, verse, alignment, progress_callback=progress_callback,
            )
            total_tokens = int(meta.get("total_tokens_for_prepare", 0) or 0)
            cost = float(meta.get("estimated_cost_usd", 0.0) or 0.0)
            self.settings.record_ai_usage(total_tokens, cost)
            if cancel_event.is_set():
                project.mark_ai_review_incomplete(chapter, verse, "cancelled")
                project.mark_issue_resolutions_recheck(
                    chapter, verse, "cancelled",
                    reason="AI review was cancelled; no lifecycle conclusion was accepted.",
                )
                raise AIError("AI review cancelled; the completed model result was not automatically applied.")
            if proposal is not None and review_alignment.to_dict() != alignment.to_dict():
                progress_callback(90, "Saving AI-filled alignment gaps")
                try:
                    with self._checker_lock:
                        self._save_alignment(
                            chapter, verse, review_alignment, alignment.to_dict(), "ai_review_auto_align",
                        )
                        # The verse alignment is part of review_input_fingerprint,
                        # and prepare_verse_review already stamped the stored review
                        # with the fingerprint from BEFORE this write. Without the
                        # rebase the review invalidates itself: the UI showed
                        # "Verse changed - the previous AI review is stale" the
                        # instant the review finished. Only _apply_safe_ai_selections
                        # rebased, and only when it applied something, so Manual mode
                        # (which applies nothing) always went stale.
                        project.rebase_ai_review_fingerprint(chapter, verse)
                except Exception:
                    # A concurrent edit or a validation edge case here must not sink the
                    # tN/tW review this verse otherwise completed; the verse simply stays
                    # unaligned and is picked up by the alignment-popup/verse-list flag.
                    pass
            # Safe, evidence-grounded selections are applied for every review.
            # `mode` (allow-manual-override) decides whether the reviewer may
            # then hand-edit the result, not whether the AI is allowed to fill
            # it in -- gating the write on the mode meant turning override on
            # silently stopped tN/tW words being selected at all.
            progress_callback(94, "Applying safe evidence-grounded selections")
            applied, skipped = self._apply_safe_ai_selections(
                project, chapter, verse, reviews, model=str(meta.get("model") or client.model),
                qa_issues=issues,
            )
            review_dicts = [item.to_dict() for item in reviews]
            lifecycle = project.reconcile_issue_resolutions_after_ai_review(
                chapter, verse, review_dicts,
                model=str(meta.get("model") or client.model), summary=summary,
            )
            progress_callback(100, "Verse AI review complete")
            return {
                "summary": summary,
                "checkReviews": review_dicts,
                "qaIssues": [item.to_dict() for item in issues],
                "alignmentProposal": proposal,
                "alignmentWasAIProposed": bool(proposal is not None),
                "appliedSelections": applied,
                "skippedSelections": skipped,
                "resolutionLifecycle": lifecycle,
                "usage": {"totalTokens": total_tokens, "estimatedCostUSD": round(cost, 6)},
            }
        except Exception as exc:
            if not cancel_event.is_set():
                project.mark_issue_resolutions_recheck(
                    chapter, verse, "failed",
                    reason="Automatic AI recheck failed.", error=str(exc),
                )
            raise

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

    def semantic_mapping_get_for_verse(self, chapter: str, verse: str) -> dict[str, Any]:
        self._require_project()
        return semantic_mappings_for_verse(self.project, chapter, verse)

    def semantic_mapping_confirm(
        self, fingerprint: str, source_unit_id: str, decision: str,
        reviewer: str = "", note: str = "", edited_mapping: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._require_project()
        return confirm_semantic_mapping(
            self.project,
            fingerprint=fingerprint, source_unit_id=source_unit_id, decision=decision,
            reviewer=reviewer, note=note, edited_mapping=edited_mapping,
        )

    def semantic_mapping_rerun_for_verse(self, chapter: str, verse: str) -> dict[str, Any]:
        self._require_project()
        return prepare_semantic_mappings_for_review(
            project=self.project, client=self._ai_client(), chapter=chapter, verse=verse, force=True,
        )

    def semantic_validation_list(self) -> dict[str, Any]:
        self._require_project()
        return list_semantic_validation_candidates(self.project)

    def semantic_validation_decide(
        self, candidate_id: str, decision: str, reviewer: str,
        note: str = "", corrected_mapping: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._require_project()
        return decide_semantic_validation_candidate(
            self.project, candidate_id=candidate_id, decision=decision,
            reviewer=reviewer, note=note, corrected_mapping=corrected_mapping,
        )

    # -- passage-semantic runtime foundation -----------------------------

    def passage_semantic_status(self) -> dict[str, Any]:
        if self.passage_semantic_runtime is None:
            return dict(self._passage_semantic_status)
        self._passage_semantic_status = {
            "state": "READY", **self.passage_semantic_runtime.status(),
        }
        return dict(self._passage_semantic_status)

    def _require_passage_semantic_runtime(self) -> PassageSemanticRuntime:
        self._require_project()
        if self.passage_semantic_runtime is None:
            error = str(self._passage_semantic_status.get("error") or "")
            raise ProjectError(
                "Passage-semantic companion storage is unavailable."
                + (f" Recovery detail: {error}" if error else "")
            )
        return self.passage_semantic_runtime

    def passage_semantic_project_metadata(self) -> dict[str, Any]:
        return self._require_passage_semantic_runtime().project_metadata()

    def passage_semantic_current_passage(
        self, chapter: str, verse: str, end_chapter: str = "", end_verse: str = "",
    ) -> dict[str, Any]:
        return self._require_passage_semantic_runtime().get_current_passage(
            chapter, verse, end_chapter, end_verse,
        )

    def passage_semantic_stale_summary(self) -> dict[str, Any]:
        return self._require_passage_semantic_runtime().stale_summary()

    def passage_semantic_migration_report(self) -> dict[str, Any]:
        return self._require_passage_semantic_runtime().migration_report()

    def passage_semantic_rebuild_passage(
        self, chapter: str, verse: str, end_chapter: str = "", end_verse: str = "",
        tokenizer_profile: str = "bridge-unicode-word-v1",
    ) -> dict[str, Any]:
        return self._require_passage_semantic_runtime().rebuild_current_passage(
            chapter, verse, end_chapter, end_verse, tokenizer_profile,
        )

    def source_semantic_build_range(
        self, chapter: str, verse: str, end_chapter: str = "", end_verse: str = "",
    ) -> dict[str, Any]:
        return self._require_passage_semantic_runtime().build_source_semantic_range(
            chapter, verse, end_chapter, end_verse,
        )

    def source_semantic_get_range(self, inventory_id: str) -> dict[str, Any]:
        return self._require_passage_semantic_runtime().source_semantic_range(inventory_id)

    def source_semantic_get_unit(self, unit_id: str) -> dict[str, Any]:
        return self._require_passage_semantic_runtime().source_semantic_unit(unit_id)

    def source_semantic_get_coverage_accounts(self, inventory_id: str) -> list[dict[str, Any]]:
        return self._require_passage_semantic_runtime().source_semantic_coverage_accounts(inventory_id)

    def source_semantic_get_diagnostics(self, inventory_id: str) -> dict[str, Any]:
        return self._require_passage_semantic_runtime().source_semantic_diagnostics(inventory_id)

    def target_semantic_build_range(
        self, chapter: str, verse: str, end_chapter: str = "", end_verse: str = "",
    ) -> dict[str, Any]:
        return self._require_passage_semantic_runtime().build_target_semantic_range(
            chapter, verse, end_chapter, end_verse,
        )

    def target_semantic_get_range(self, inventory_id: str) -> dict[str, Any]:
        return self._require_passage_semantic_runtime().target_semantic_range(inventory_id)

    def target_semantic_get_unit(self, unit_id: str) -> dict[str, Any]:
        return self._require_passage_semantic_runtime().target_semantic_unit(unit_id)

    def target_semantic_get_diagnostics(self, inventory_id: str) -> dict[str, Any]:
        return self._require_passage_semantic_runtime().target_semantic_diagnostics(inventory_id)

    def target_semantic_get_search_spans(self, inventory_id: str) -> list[dict[str, Any]]:
        return self._require_passage_semantic_runtime().target_semantic_search_spans(inventory_id)

    def target_semantic_get_capabilities(self, inventory_id: str = "") -> dict[str, Any]:
        return self._require_passage_semantic_runtime().target_semantic_capabilities(inventory_id)

    def semantic_location_run_range(
        self, chapter: str, verse: str, end_chapter: str = "", end_verse: str = "",
        max_candidate_evaluations: int | None = None,
    ) -> dict[str, Any]:
        return self._require_passage_semantic_runtime().run_semantic_location_range(
            chapter, verse, end_chapter, end_verse, max_candidate_evaluations,
        )

    def semantic_location_status(self, run_id: str) -> dict[str, Any]:
        return self._require_passage_semantic_runtime().semantic_location_status(run_id)

    def semantic_location_get_range(self, run_id: str) -> dict[str, Any]:
        return self._require_passage_semantic_runtime().semantic_location_range(run_id)

    def semantic_location_get_relationship(self, relationship_id: str) -> dict[str, Any]:
        return self._require_passage_semantic_runtime().semantic_location_relationship(relationship_id)

    def semantic_location_get_candidates(
        self, run_id: str, source_owner_unit_id: str = "",
    ) -> list[dict[str, Any]]:
        return self._require_passage_semantic_runtime().semantic_location_candidates(
            run_id, source_owner_unit_id,
        )

    def semantic_location_get_diagnostics(self, run_id: str) -> dict[str, Any]:
        return self._require_passage_semantic_runtime().semantic_location_diagnostics(run_id)

    def meaning_analysis_run_range(
        self, chapter: str, verse: str, end_chapter: str = "", end_verse: str = "",
        location_run_id: str = "",
    ) -> dict[str, Any]:
        return self._require_passage_semantic_runtime().run_meaning_analysis_range(
            chapter, verse, end_chapter, end_verse, location_run_id,
        )

    def meaning_analysis_status(self, run_id: str) -> dict[str, Any]:
        return self._require_passage_semantic_runtime().meaning_analysis_status(run_id)

    def meaning_analysis_get_range(self, run_id: str) -> dict[str, Any]:
        return self._require_passage_semantic_runtime().meaning_analysis_range(run_id)

    def meaning_analysis_get_assessment(self, assessment_id: str) -> dict[str, Any]:
        return self._require_passage_semantic_runtime().meaning_assessment(assessment_id)

    def meaning_analysis_get_components(self, assessment_id: str) -> list[dict[str, Any]]:
        return self._require_passage_semantic_runtime().meaning_components(assessment_id)

    def meaning_analysis_get_diagnostics(self, run_id: str) -> dict[str, Any]:
        return self._require_passage_semantic_runtime().meaning_analysis_diagnostics(run_id)

    def qa_audit_run_range(
        self, chapter: str, verse: str, end_chapter: str = "", end_verse: str = "",
        meaning_run_id: str = "",
    ) -> dict[str, Any]:
        return self._require_passage_semantic_runtime().run_qa_audit_range(
            chapter, verse, end_chapter, end_verse, meaning_run_id,
        )

    def qa_audit_status(self, run_id: str) -> dict[str, Any]:
        return self._require_passage_semantic_runtime().qa_audit_status(run_id)

    def qa_audit_get_range(self, run_id: str) -> dict[str, Any]:
        return self._require_passage_semantic_runtime().qa_audit_range(run_id)

    def qa_audit_get_source_coverage(self, run_id: str) -> list[dict[str, Any]]:
        return self._require_passage_semantic_runtime().qa_audit_source_coverage(run_id)

    def qa_audit_get_target_support(self, run_id: str) -> list[dict[str, Any]]:
        return self._require_passage_semantic_runtime().qa_audit_target_support(run_id)

    def qa_audit_get_finding(self, finding_id: str) -> dict[str, Any]:
        return self._require_passage_semantic_runtime().qa_audit_finding(finding_id)

    def qa_audit_get_diagnostics(self, run_id: str) -> dict[str, Any]:
        return self._require_passage_semantic_runtime().qa_audit_diagnostics(run_id)

    # -- Stage 9A human review --------------------------------------------
    # Deliberately separate from the qaAudit.* analysis methods above: these
    # write human decisions, those only read machine analysis.

    def qa_review_get_queue(self, **filters: Any) -> dict[str, Any]:
        return self._require_passage_semantic_runtime().qa_review_queue(**filters)

    def qa_review_get_finding(self, finding_id: str) -> dict[str, Any]:
        return self._require_passage_semantic_runtime().qa_review_finding(finding_id)

    def qa_review_decide_finding(
        self, finding_id: str, disposition: str, **options: Any,
    ) -> dict[str, Any]:
        return self._require_passage_semantic_runtime().qa_review_decide(
            finding_id, disposition, **options)

    def qa_review_add_note(
        self, entity_type: str, entity_id: str, note: str,
    ) -> dict[str, Any]:
        return self._require_passage_semantic_runtime().qa_review_add_note(
            entity_type, entity_id, note)

    def semantic_review_decide_location(
        self, relationship_id: str, decision: str, **options: Any,
    ) -> dict[str, Any]:
        return self._require_passage_semantic_runtime().semantic_review_decide_location(
            relationship_id, decision, **options)

    def semantic_review_decide_meaning(
        self, assessment_id: str, meaning_status: str, **options: Any,
    ) -> dict[str, Any]:
        return self._require_passage_semantic_runtime().semantic_review_decide_meaning(
            assessment_id, meaning_status, **options)

    def review_history_get_entity_history(
        self, entity_type: str, entity_id: str,
    ) -> dict[str, Any]:
        return self._require_passage_semantic_runtime().review_history(entity_type, entity_id)

    # -- Stage 9A.4 analysis orchestration --------------------------------

    def analysis_job_start(
        self, requested_scope: dict[str, Any], expected_analysis_fingerprint: str = "",
    ) -> dict[str, Any]:
        if not expected_analysis_fingerprint:
            raise AnalysisJobConflict(
                "Resolve the selected scope status before starting analysis"
            )
        return self._analysis_jobs.start(
            self._require_passage_semantic_runtime(), requested_scope=requested_scope,
            expected_analysis_fingerprint=expected_analysis_fingerprint,
        )

    def analysis_job_status(self, job_id: str) -> dict[str, Any]:
        return self._analysis_jobs.status(job_id)

    def analysis_job_cancel(self, job_id: str) -> dict[str, Any]:
        return self._analysis_jobs.cancel(job_id)

    def analysis_job_get_recent(self, limit: int = 20) -> list[dict[str, Any]]:
        return self._analysis_jobs.get_recent(
            self._require_passage_semantic_runtime(), limit=limit,
        )

    def analysis_job_get_scope_status(
        self, requested_scope: dict[str, Any],
    ) -> dict[str, Any]:
        return self._analysis_jobs.get_scope_status(
            self._require_passage_semantic_runtime(), requested_scope,
        )

    # -- live desktop connectors (Paratext/Logos) --------------------------
    #
    # Explicit connector calls remain available for diagnostics and Paratext note
    # handoff. Continuous navigation uses the coordinator below so slow/unavailable
    # desktop applications never block ordinary Bridge requests.

    def paratext_get_state(self) -> dict[str, Any]:
        state = ParatextConnectorClient().get_state()
        return asdict(state)

    def paratext_set_reference(self, reference: str, origin_id: str = "") -> dict[str, Any]:
        return ParatextConnectorClient().set_reference(reference, origin_id)

    # -- issue resolution + explicit Paratext handoff --------------------

    def list_issue_resolutions(self, chapter: str, verse: str) -> dict[str, Any]:
        self._require_project()
        items = self.project.list_issue_resolutions(chapter, verse)
        return {
            "chapter": str(chapter), "verse": str(verse), "items": items,
            "queued": sum(1 for item in items if (item.get("paratext") or {}).get("status") == "queued"),
            "sent": sum(1 for item in items if (item.get("paratext") or {}).get("status") == "sent"),
            "resolved": sum(1 for item in items if item.get("status") == "resolved"),
            "reflagged": sum(1 for item in items if item.get("status") == "reflagged"),
        }

    def save_issue_resolution(
        self, chapter: str, verse: str, tool: str, group_id: str, check_id: str,
        expected_fingerprint: str, selected_text: str = "", issue_summary: str = "",
        reviewer_note: str = "", proposed_correction: str = "",
        evidence: Optional[list[Any]] = None,
    ) -> dict[str, Any]:
        self._require_project()
        with self._checker_lock:
            return self.project.save_issue_resolution(
                chapter, verse, tool, group_id, check_id, expected_fingerprint,
                selected_text=selected_text, issue_summary=issue_summary,
                reviewer_note=reviewer_note, proposed_correction=proposed_correction,
                evidence=evidence or [],
                username=self.settings.reviewer_name or "Bridge Reviewer",
            )

    @staticmethod
    def _issue_handoff_comment(record: dict[str, Any]) -> str:
        check = record.get("check") if isinstance(record.get("check"), dict) else {}
        tool = "Translation Note" if check.get("tool") == "translationNotes" else "Translation Word"
        parts = [
            f"Bridge {tool} review for {record.get('reference', '')}",
            f"Issue: {record.get('issueSummary', '')}",
        ]
        correction = str(record.get("proposedCorrection") or "").strip()
        if correction:
            parts.append(f"Proposed correction: {correction}")
        evidence = list(record.get("evidence") or [])
        if evidence:
            labels = []
            for item in evidence[:10]:
                if isinstance(item, dict):
                    labels.append(str(item.get("title") or item.get("identifier") or item.get("kind") or "Evidence"))
                else:
                    labels.append(str(item))
            parts.append("Evidence: " + "; ".join(x for x in labels if x))
        parts.append(f"Reviewer note: {record.get('reviewerNote', '')}")
        return "\n\n".join(parts)

    def _save_handoff_item(
        self, chapter: str, verse: str, resolution_id: str,
        item: dict[str, Any], event: str,
    ) -> dict[str, Any]:
        state = self.project.load_paratext_note_sync_state()
        items = dict(state.get("items") or {})
        items[str(item["messageId"])] = item
        state["items"] = items
        self.project.save_paratext_note_sync_state(state)
        return self.project.update_issue_resolution_paratext(
            chapter, verse, resolution_id,
            {
                "status": item["status"], "messageId": item["messageId"],
                "attempts": item["attempts"], "lastError": item.get("lastError", ""),
                "sentAt": item.get("sentAt", ""), "remoteId": item.get("remoteId", ""),
                "contentSignature": item["contentSignature"],
                "expectedProjectId": item.get("expectedProjectId", ""),
            },
            event,
        )

    def _attempt_issue_handoff(
        self, chapter: str, verse: str, resolution_id: str, item: dict[str, Any],
    ) -> dict[str, Any]:
        item = dict(item)
        item["attempts"] = int(item.get("attempts") or 0) + 1
        expected_project_id = str(item.get("expectedProjectId") or "").strip()
        try:
            state = ParatextConnectorClient().get_state()
            capabilities = {str(capability).strip().casefold() for capability in state.capabilities}
            if not capabilities.intersection({"create_note", "project_notes"}):
                raise ParatextConnectorError(
                    "The connected Paratext companion does not support live note creation yet; the Notes 1.1 handoff remains safely queued."
                )
            if not expected_project_id:
                raise ParatextConnectorError(
                    "Confirm the destination Paratext project before sending this note."
                )
            if state.project_id.casefold() != expected_project_id.casefold():
                raise ParatextConnectorError(
                    "The active Paratext project does not match the project confirmed for this handoff."
                )
            payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
            response = ParatextConnectorClient().create_note(
                str(payload.get("reference") or ""), str(payload.get("selectedText") or ""),
                str(payload.get("comment") or ""), project_id=expected_project_id,
                message_id=str(item.get("messageId") or ""),
            )
            item["status"] = "sent"
            item["lastError"] = ""
            item["sentAt"] = datetime.now(timezone.utc).isoformat()
            item["remoteId"] = str(response.get("note_id") or response.get("thread_id") or "")
            record = self._save_handoff_item(chapter, verse, resolution_id, item, "paratext_sent")
        except ParatextConnectorError as exc:
            item["status"] = "queued"
            item["lastError"] = str(exc)
            record = self._save_handoff_item(chapter, verse, resolution_id, item, "paratext_queued")
        return {"record": record, "handoff": item}

    def queue_issue_resolution_for_paratext(
        self, chapter: str, verse: str, resolution_id: str, expected_project_id: str = "",
    ) -> dict[str, Any]:
        self._require_project()
        record = self.project.load_issue_resolution(chapter, verse, resolution_id)
        comment = self._issue_handoff_comment(record)
        signature = str((record.get("paratext") or {}).get("contentSignature") or "")
        message_id = f"bridge-{resolution_id}-{signature[:12]}"
        sync = self.project.load_paratext_note_sync_state()
        existing = (sync.get("items") or {}).get(message_id)
        if isinstance(existing, dict) and existing.get("status") == "sent":
            return {"record": record, "handoff": existing}
        note_path = self.project.record_paratext_note(
            chapter, verse, comment,
            username=self.settings.reviewer_name or "Bridge Reviewer",
            selected_text=str(record.get("selectedText") or ""),
            metadata={"resolutionId": resolution_id, "paratextThreadType": "BridgeTranslationIssue"},
            thread_id=message_id,
        )
        item = dict(existing) if isinstance(existing, dict) else {
            "messageId": message_id, "resolutionId": resolution_id,
            "createdAt": datetime.now(timezone.utc).isoformat(), "attempts": 0,
        }
        item.update({
            "status": "queued", "contentSignature": signature,
            "expectedProjectId": str(expected_project_id or item.get("expectedProjectId") or ""),
            "notePath": str(note_path),
            "payload": {
                "reference": record["reference"], "selectedText": record.get("selectedText", ""),
                "comment": comment,
            },
        })
        self._save_handoff_item(chapter, verse, resolution_id, item, "paratext_queued")
        return self._attempt_issue_handoff(chapter, verse, resolution_id, item)

    def retry_issue_resolution_paratext(
        self, chapter: str, verse: str, resolution_id: str,
    ) -> dict[str, Any]:
        self._require_project()
        record = self.project.load_issue_resolution(chapter, verse, resolution_id)
        message_id = str((record.get("paratext") or {}).get("messageId") or "")
        item = (self.project.load_paratext_note_sync_state().get("items") or {}).get(message_id)
        if not message_id or not isinstance(item, dict):
            raise ProjectError('This issue has not been queued for Paratext yet.')
        if item.get("status") == "sent":
            return {"record": record, "handoff": item}
        return self._attempt_issue_handoff(chapter, verse, resolution_id, item)

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

    def navigation_status(self, context: str = "") -> dict[str, Any]:
        return self._navigation.snapshot(context=context)

    def navigation_bridge_changed(self, reference: str) -> dict[str, Any]:
        return self._navigation.bridge_changed(reference)

    def navigation_resolve(
        self, request_id: str, accepted: bool, bridge_reference: str = "", context: str = "",
    ) -> dict[str, Any]:
        return self._navigation.resolve(
            request_id,
            accepted=accepted,
            bridge_reference=bridge_reference,
            context=context,
        )

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
                content_hash = hashlib.sha256(usfm_text.encode("utf-8")).hexdigest()
                cached_section = project.load_check_cache().get("usfm") or {}
                if cached_section.get("contentHash") == content_hash:
                    findings = [QaFinding.from_dict(d) for d in cached_section.get("findings", [])]
                    self._usfm_findings_by_book[book_key] = findings
                    return findings
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
                # Persist after id stabilization so a cache hit hands back
                # the same stable ids a fresh run would — required for prior
                # decisions (keyed by finding id) to keep matching.
                project.save_check_cache_section(
                    "usfm", content_hash, [f.to_dict() for f in findings],
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

        text_map = self._book_verse_text_map(project)
        # "|spans-v1" forces a one-time cache invalidation for on-disk
        # checkCache.json sections written before findings carried
        # start_offset/end_offset — otherwise a content-hash match on
        # unchanged verse text would keep silently returning the older,
        # offset-less cached findings.
        content_hash = hashlib.sha256(
            ("\n".join(f"{k}={v}" for k, v in sorted(text_map.items())) + "|spans-v1").encode("utf-8")
        ).hexdigest()
        cached_section = project.load_check_cache().get("names") or {}
        if cached_section.get("contentHash") == content_hash:
            findings = [QaFinding.from_dict(d) for d in cached_section.get("findings", [])]
            self._names_findings_by_book[book_key] = findings
            return findings

        token_occurrences: dict[str, list[tuple[str, str]]] = {}
        for ref, text in text_map.items():
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
            # NamesAdapter deliberately never sees verse text (only
            # token_occurrences), so it can't compute a span itself — do it
            # here, against the exact same raw text_map string the frontend
            # highlights into, not whitespace_tokens' strip_usfm'd copy
            # (which can shift character positions via whitespace collapse).
            verse_text = text_map.get(f"{f.chapter}:{f.verse}")
            if verse_text:
                span = _first_token_span(verse_text, f.original_text)
                if span:
                    f.start_offset, f.end_offset = span
        # Persist after id stabilization (see USFM above — same reasoning).
        # The hash is over current verse text, so an edit_verse call between
        # opens correctly invalidates this on the next reopen, unlike the
        # in-memory cache this replaces which never distinguished the two.
        project.save_check_cache_section(
            "names", content_hash, [f.to_dict() for f in findings],
        )
        self._names_findings_by_book[book_key] = findings
        return findings

    # Heuristic thresholds for _consistency_findings_for_book — unlike the
    # PMI/translation-probability formulas in alignment_statistics.py
    # (which mirror ualign.py's own AlignmentModel.support_probability()),
    # these three numbers have no textbook source; they're a starting,
    # tunable bar for "recurrent enough and fragmented enough to be worth a
    # human's attention", deliberately conservative (low severity, low
    # confidence — see the finding below) so this never claims more
    # certainty than a corpus-frequency heuristic actually has.
    _CONSISTENCY_MIN_OCCURRENCES = 3
    _CONSISTENCY_MIN_RENDERINGS = 3
    _CONSISTENCY_DOMINANCE_THRESHOLD = 0.7

    def _consistency_findings_for_book(
        self, project: Optional[TranslationCoreProject] = None,
    ) -> list[QaFinding]:
        """Whole-book Layer-2 check: a source (original-language) word that
        recurs often across this book's own human-completed alignments but
        maps to many different target renderings with no dominant one is
        flagged as a possible inconsistent-translation signal — using
        alignment_statistics.py's existing corpus co-occurrence table
        exactly as that module's own docstring anticipated ("a future
        phase can layer findings on top of this data without recomputing
        it"). This is corpus-wide, not tied to any one occurrence's
        chapter:verse — CorpusStatsTable aggregates counts only, it does
        not retain which verse produced which pairing (see its own
        docstring) — so, like a whole-book USFM finding with no matching
        verse slot, this surfaces on the book's first chapter at verse 0
        rather than a fabricated precise location. An honest book-level
        flag, not a claim about any specific occurrence.

        A blunt statistical signal, not a semantic judgment: some of what
        this flags will be legitimate contextual variation, not a real
        error — see the roadmap's own caution about distinguishing the
        two. That distinction needs real semantic evaluation (issue #16),
        not corpus frequency alone, hence the low severity/confidence.
        """
        project = project or self.project
        if project is None:
            raise ProjectError("No project open — call project.open first")
        book_key = str(project.path)
        cached = self._consistency_findings_by_book.get(book_key)
        if cached is not None:
            return cached

        table = self._corpus_stats_by_book.get(book_key)
        if table is None:
            table = corpus_stats_tool.build_corpus_stats(project)
            self._corpus_stats_by_book[book_key] = table

        renderings: dict[str, Counter] = {}
        for (source_word, target_word), count in table.pair_counts.items():
            renderings.setdefault(source_word, Counter())[target_word] += count

        chapters = project.chapters()
        first_chapter = chapters[0] if chapters else "1"
        findings: list[QaFinding] = []
        for source_word, counts in renderings.items():
            total = sum(counts.values())
            if total < self._CONSISTENCY_MIN_OCCURRENCES or len(counts) < self._CONSISTENCY_MIN_RENDERINGS:
                continue
            top_word, top_count = counts.most_common(1)[0]
            if top_count / total >= self._CONSISTENCY_DOMINANCE_THRESHOLD:
                continue  # one rendering clearly dominates — not flagged
            evidence = [
                EvidenceItem(label=f'"{word}"', value=f"{n} of {total} occurrence(s)")
                for word, n in counts.most_common()
            ]
            findings.append(QaFinding(
                id=_stable_finding_id(
                    chapter=str(first_chapter), verse="0", engine="alignment-corpus",
                    check_type="alignment.inconsistent_rendering", disambiguator=source_word,
                ),
                project_id=str(project.summary.path), book=project.book_id,
                chapter=int(next(iter(re.findall(r"\d+", str(first_chapter))), "0")), verse=0,
                engine="alignment-corpus", check_type="alignment.inconsistent_rendering",
                category=FindingCategory.CONSISTENCY, severity=Severity.LOW, confidence=0.4,
                original_text=source_word,
                explanation=(
                    f'"{source_word}" occurs {total} times in completed alignments across this '
                    f"book with {len(counts)} different target renderings and no single dominant "
                    f'one (most common: "{top_word}", {top_count}/{total}).'
                ),
                evidence=evidence,
                engine_version=BRIDGE_VERSION,
            ))

        self._consistency_findings_by_book[book_key] = findings
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
        project = self.project
        # ReviewPanel asks for a Greek-Room-only live check as soon as a verse
        # is selected.  First-time tN/tW/USFM/names preparation can hold the
        # checker lock for much longer than the desktop's interactive timeout.
        # Waiting here would block the synchronous stdio dispatcher itself, so
        # checks.status and check.listForVerse queued behind this request would
        # time out too.  Greek Room reads only the captured project/verse and
        # its own adapter; it does not touch tC selection/index state and does
        # not need the checker lock.
        needs_checker_lock = any(
            name in {"local", "tN", "tW", "alignment", "usfm", "names", "consistency"}
            for name in checks
        )
        if not needs_checker_lock:
            return self._run_verse_checks_for_project(project, chapter, verse, checks)
        with self._checker_lock:
            if any(name in checks for name in ("local", "tN", "tW")):
                self._ensure_resource_indexes(project)
            return self._run_verse_checks_for_project(project, chapter, verse, checks)

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
            resource_versions = self._pinned_resource_versions(project)
            for issue in issues:
                findings.append(_qaissue_to_finding(
                    issue, project_id=project_id, book=book,
                    chapter=chapter, verse=verse,
                    resource_versions=resource_versions,
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

        if "consistency" in checks:
            # Opt-in, not bundled into "local" — a corpus-frequency
            # heuristic (see _consistency_findings_for_book) that would
            # otherwise silently change the finding volume for every
            # existing "local" caller. Same book-level chapter-0/verse-0
            # placeholder fallback as the USFM block above, since these
            # findings aren't anchored to one specific occurrence either.
            book_verses = project.verses(chapter) if chapter in project.chapters() else []
            existing_verses = {str(value) for value in book_verses}
            first_verse = book_verses[0] if book_verses else None
            for f in self._consistency_findings_for_book(project):
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
            on_complete=lambda job: self._on_check_job_complete(project, job),
        )

    def _on_check_job_complete(self, project: TranslationCoreProject, job: Any) -> None:
        """Rebuilds the progress rollup's entries for exactly the chapters
        this job covered — chapters it didn't touch are left alone. Only a
        succeeded job (no failed verses) updates anything; a failed/cancelled
        job must not claim a chapter is AI-checked when it isn't. Best-effort,
        same reasoning as _apply_decision_to_progress: never let this surface
        as a check-job failure to the UI."""
        if job.state != "succeeded":
            return
        try:
            by_chapter: dict[str, dict[str, dict[str, str]]] = {}
            for result in job.results.values():
                chapter = result.get("chapter")
                verse = result.get("verse")
                if chapter is None or verse is None or chapter not in job.spec.chapters:
                    continue
                verse_findings = {
                    str(f["id"]): str(f.get("status", FindingStatus.OPEN.value))
                    for f in (result.get("findings") or []) if f.get("id")
                }
                by_chapter.setdefault(str(chapter), {})[str(verse)] = verse_findings

            rollup = project.load_progress_rollup()
            chapters_dict = rollup.setdefault("chapters", {})
            now = project.timestamp_iso()
            for chapter, verses_map in by_chapter.items():
                chapters_dict[chapter] = {
                    "verseCount": len(project.verses(chapter)),
                    "aiChecked": True,
                    "aiCheckedAt": now,
                    "verses": {v: {"findings": f} for v, f in verses_map.items()},
                }
            self._recompute_progress_totals(project, rollup)
            project.save_progress_rollup(rollup)
        except Exception:
            pass

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
        self._apply_decision_to_progress(self.project, chapter, verse, finding_id, status)
        return {"chapter": chapter, "verse": verse, "findingId": finding_id,
                "status": status, "recordedAt": str(path)}

    def _apply_decision_to_progress(
        self, project: TranslationCoreProject, chapter: str, verse: str,
        finding_id: str, status: str,
    ) -> None:
        """Incrementally updates the book's progress rollup for one decision
        — reads/updates/writes one small file, never rescans qaDecisions on
        disk. Best-effort: a rollup bookkeeping failure must never surface as
        a decide_verse failure, since the actual decision is already safely
        recorded via record_qa_decision above."""
        try:
            rollup = project.load_progress_rollup()
            chapters = rollup.setdefault("chapters", {})
            chapter_key = str(chapter)
            chapter_entry = chapters.setdefault(chapter_key, {
                "verseCount": len(project.verses(chapter_key)) if chapter_key in project.chapters() else 0,
                "aiChecked": False, "aiCheckedAt": None, "verses": {},
            })
            verse_entry = chapter_entry.setdefault("verses", {}).setdefault(str(verse), {"findings": {}})
            verse_entry["findings"][str(finding_id)] = str(status)
            self._recompute_progress_totals(project, rollup)
            project.save_progress_rollup(rollup)
        except Exception:
            pass

    @staticmethod
    def _recompute_progress_totals(project: TranslationCoreProject, rollup: dict[str, Any]) -> None:
        chapters_dict = rollup.get("chapters", {})
        all_chapters = project.chapters()
        checked_chapter_count = 0
        checked_verse_count = 0
        reviewed_verse_count = 0
        finding_count = 0
        approved_finding_count = 0
        for chapter_entry in chapters_dict.values():
            if chapter_entry.get("aiChecked"):
                checked_chapter_count += 1
                checked_verse_count += int(chapter_entry.get("verseCount") or 0)
            for verse_entry in chapter_entry.get("verses", {}).values():
                findings = verse_entry.get("findings", {})
                finding_count += len(findings)
                verse_reviewed = bool(findings)
                for status in findings.values():
                    if status == FindingStatus.OPEN.value:
                        verse_reviewed = False
                    else:
                        approved_finding_count += 1
                if verse_reviewed:
                    reviewed_verse_count += 1
        rollup["totals"] = {
            "chapterCount": len(all_chapters),
            "checkedChapterCount": checked_chapter_count,
            "verseCount": sum(len(project.verses(ch)) for ch in all_chapters),
            "checkedVerseCount": checked_verse_count,
            "reviewedVerseCount": reviewed_verse_count,
            "findingCount": finding_count,
            "approvedFindingCount": approved_finding_count,
        }

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
        Nothing here reinvents that; it only calls it.

        Also invalidates the in-memory whole-book consistency cache (see
        _consistency_findings_for_book's own docstring) for THIS book only
        — cheap, in-memory corpus-stats arithmetic, same cost as the
        existing invalidation every alignment mutation already does in
        _finish_alignment_mutation.

        Deliberately does NOT touch the USFM/names caches, even though a
        finding whose text this edit just fixed (e.g. a
        names.spelling_similarity correction) will keep reappearing until
        the project is reopened. Tried clearing them here too and reverted
        it the same session: saveVerseEdit's post-save runVerseChecks(
        ["local", "greekroom"]) calls straight into
        _usfm_findings_for_book/_names_findings_for_book on every edit
        (see run_verse_checks), and those functions' own docstrings say
        why they're never invalidated by verse.edit — a real rescan means
        the isolated USFM checker subprocess (a 120-second hard timeout on
        its own) and a full whole-book names/vocabulary scan. Popping the
        cache here made that recheck pay for both, synchronously, inside
        the single-threaded stdio dispatcher and while holding
        _checker_lock — so a save could block the sidecar long enough that
        an unrelated project.report queued behind it timed out client-side
        (same failure mode as issue #24, just via a different call path).
        Accepted as a known limitation, same tradeoff as the two functions
        it depends on."""
        self._require_project()
        result = self.project.apply_scripture_edit(chapter, verse, new_text)
        self._consistency_findings_by_book.pop(str(self.project.path), None)
        resolutions = self.project.list_issue_resolutions(chapter, verse)
        return {
            "committed": True, "chapter": chapter, "verse": verse,
            "issueResolutionsNeedingRecheck": sum(
                1 for item in resolutions
                if str((item.get("recheck") or {}).get("status") or "") == "stale"
            ),
            **result,
        }

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
            "paratextNavigation": self.settings.paratext_navigation,
            "logosNavigation": self.settings.logos_navigation,
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
        if "paratextNavigation" in kwargs:
            self.settings.paratext_navigation = bool(kwargs["paratextNavigation"])
        if "logosNavigation" in kwargs:
            self.settings.logos_navigation = bool(kwargs["logosNavigation"])
        self._navigation.configure(
            paratext=self.settings.paratext_navigation,
            logos=self.settings.logos_navigation,
        )
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
            if m == Methods.PROJECT_LIST_BOOK_PROGRESS:
                return EngineResponse.ok(request.id, result=self.list_book_progress())
            if m == Methods.PROJECT_FORGET:
                return EngineResponse.ok(request.id, result=self.forget_project(p.get("projectId", "")))
            if m == Methods.PROJECT_DELETE:
                return EngineResponse.ok(request.id, result=self.delete_project(p.get("projectId", "")))
            if m == Methods.PROJECT_SCAN:
                return EngineResponse.ok(request.id, result=self.scan_project())
            if m == Methods.PROJECT_REPORT:
                return EngineResponse.ok(request.id, result=self.build_project_report())
            if m == Methods.PROJECT_SWEEP_START:
                return EngineResponse.ok(request.id, result=self.start_project_sweep())
            if m == Methods.PROJECT_SWEEP_STATUS:
                return EngineResponse.ok(request.id, result=self.project_sweep_status(p.get("jobId", "")))
            if m == Methods.PROJECT_SWEEP_CANCEL:
                return EngineResponse.ok(request.id, result=self.cancel_project_sweep(p.get("jobId", "")))
            if m == Methods.PROJECT_COLLECTION_REPORT:
                return EngineResponse.ok(request.id, result=self.build_collection_report())
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
            if m == Methods.VERSE_EVIDENCE:
                return EngineResponse.ok(request.id, result=self.get_verse_evidence(p["chapter"], p["verse"]))
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
            if m == Methods.LEXICON_GET_ENTRY:
                return EngineResponse.ok(
                    request.id, result=self.get_lexicon_entry(p.get("strong", ""), p.get("morph", "")),
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
            if m == Methods.SEMANTIC_MAPPING_GET_FOR_VERSE:
                return EngineResponse.ok(
                    request.id, result=self.semantic_mapping_get_for_verse(p["chapter"], p["verse"]),
                )
            if m == Methods.SEMANTIC_MAPPING_CONFIRM:
                return EngineResponse.ok(request.id, result=self.semantic_mapping_confirm(
                    str(p.get("fingerprint") or ""), str(p.get("sourceUnitId") or ""),
                    str(p.get("decision") or ""), p.get("reviewer", ""), p.get("note", ""),
                    p.get("editedMapping"),
                ))
            if m == Methods.SEMANTIC_MAPPING_RERUN_FOR_VERSE:
                return EngineResponse.ok(
                    request.id, result=self.semantic_mapping_rerun_for_verse(p["chapter"], p["verse"]),
                )
            if m == Methods.SEMANTIC_VALIDATION_LIST:
                return EngineResponse.ok(request.id, result=self.semantic_validation_list())
            if m == Methods.SEMANTIC_VALIDATION_DECIDE:
                return EngineResponse.ok(request.id, result=self.semantic_validation_decide(
                    str(p.get("candidateId") or ""), str(p.get("decision") or ""),
                    str(p.get("reviewer") or ""), str(p.get("note") or ""),
                    p.get("correctedMapping"),
                ))
            if m == Methods.PASSAGE_SEMANTIC_STATUS:
                return EngineResponse.ok(request.id, result=self.passage_semantic_status())
            if m == Methods.PASSAGE_SEMANTIC_PROJECT_METADATA:
                return EngineResponse.ok(
                    request.id, result=self.passage_semantic_project_metadata(),
                )
            if m == Methods.PASSAGE_SEMANTIC_CURRENT_PASSAGE:
                return EngineResponse.ok(request.id, result=self.passage_semantic_current_passage(
                    str(p.get("chapter") or ""), str(p.get("verse") or ""),
                    str(p.get("endChapter") or ""), str(p.get("endVerse") or ""),
                ))
            if m == Methods.PASSAGE_SEMANTIC_STALE_SUMMARY:
                return EngineResponse.ok(
                    request.id, result=self.passage_semantic_stale_summary(),
                )
            if m == Methods.PASSAGE_SEMANTIC_MIGRATION_REPORT:
                return EngineResponse.ok(
                    request.id, result=self.passage_semantic_migration_report(),
                )
            if m == Methods.PASSAGE_SEMANTIC_REBUILD_PASSAGE:
                return EngineResponse.ok(request.id, result=self.passage_semantic_rebuild_passage(
                    str(p.get("chapter") or ""), str(p.get("verse") or ""),
                    str(p.get("endChapter") or ""), str(p.get("endVerse") or ""),
                    str(p.get("tokenizerProfile") or "bridge-unicode-word-v1"),
                ))
            if m == Methods.SOURCE_SEMANTIC_BUILD_RANGE:
                return EngineResponse.ok(request.id, result=self.source_semantic_build_range(
                    str(p.get("chapter") or ""), str(p.get("verse") or ""),
                    str(p.get("endChapter") or ""), str(p.get("endVerse") or ""),
                ))
            if m == Methods.SOURCE_SEMANTIC_GET_RANGE:
                return EngineResponse.ok(
                    request.id, result=self.source_semantic_get_range(str(p.get("inventoryId") or "")),
                )
            if m == Methods.SOURCE_SEMANTIC_GET_UNIT:
                return EngineResponse.ok(
                    request.id, result=self.source_semantic_get_unit(str(p.get("unitId") or "")),
                )
            if m == Methods.SOURCE_SEMANTIC_GET_COVERAGE_ACCOUNTS:
                return EngineResponse.ok(request.id, result=self.source_semantic_get_coverage_accounts(
                    str(p.get("inventoryId") or ""),
                ))
            if m == Methods.SOURCE_SEMANTIC_GET_DIAGNOSTICS:
                return EngineResponse.ok(request.id, result=self.source_semantic_get_diagnostics(
                    str(p.get("inventoryId") or ""),
                ))
            if m == Methods.TARGET_SEMANTIC_BUILD_RANGE:
                return EngineResponse.ok(request.id, result=self.target_semantic_build_range(
                    str(p.get("chapter") or ""), str(p.get("verse") or ""),
                    str(p.get("endChapter") or ""), str(p.get("endVerse") or ""),
                ))
            if m == Methods.TARGET_SEMANTIC_GET_RANGE:
                return EngineResponse.ok(request.id, result=self.target_semantic_get_range(
                    str(p.get("inventoryId") or ""),
                ))
            if m == Methods.TARGET_SEMANTIC_GET_UNIT:
                return EngineResponse.ok(request.id, result=self.target_semantic_get_unit(
                    str(p.get("unitId") or ""),
                ))
            if m == Methods.TARGET_SEMANTIC_GET_DIAGNOSTICS:
                return EngineResponse.ok(request.id, result=self.target_semantic_get_diagnostics(
                    str(p.get("inventoryId") or ""),
                ))
            if m == Methods.TARGET_SEMANTIC_GET_SEARCH_SPANS:
                return EngineResponse.ok(request.id, result=self.target_semantic_get_search_spans(
                    str(p.get("inventoryId") or ""),
                ))
            if m == Methods.TARGET_SEMANTIC_GET_CAPABILITIES:
                return EngineResponse.ok(request.id, result=self.target_semantic_get_capabilities(
                    str(p.get("inventoryId") or ""),
                ))
            if m == Methods.SEMANTIC_LOCATION_RUN_RANGE:
                budget = p.get("maxCandidateEvaluations")
                return EngineResponse.ok(request.id, result=self.semantic_location_run_range(
                    str(p.get("chapter") or ""), str(p.get("verse") or ""),
                    str(p.get("endChapter") or ""), str(p.get("endVerse") or ""),
                    int(budget) if budget is not None else None,
                ))
            if m == Methods.SEMANTIC_LOCATION_STATUS:
                return EngineResponse.ok(request.id, result=self.semantic_location_status(
                    str(p.get("runId") or ""),
                ))
            if m == Methods.SEMANTIC_LOCATION_GET_RANGE:
                return EngineResponse.ok(request.id, result=self.semantic_location_get_range(
                    str(p.get("runId") or ""),
                ))
            if m == Methods.SEMANTIC_LOCATION_GET_RELATIONSHIP:
                return EngineResponse.ok(request.id, result=self.semantic_location_get_relationship(
                    str(p.get("relationshipId") or ""),
                ))
            if m == Methods.SEMANTIC_LOCATION_GET_CANDIDATES:
                return EngineResponse.ok(request.id, result=self.semantic_location_get_candidates(
                    str(p.get("runId") or ""), str(p.get("sourceOwnerUnitId") or ""),
                ))
            if m == Methods.SEMANTIC_LOCATION_GET_DIAGNOSTICS:
                return EngineResponse.ok(request.id, result=self.semantic_location_get_diagnostics(
                    str(p.get("runId") or ""),
                ))
            if m == Methods.MEANING_ANALYSIS_RUN_RANGE:
                return EngineResponse.ok(request.id, result=self.meaning_analysis_run_range(
                    str(p.get("chapter") or ""), str(p.get("verse") or ""),
                    str(p.get("endChapter") or ""), str(p.get("endVerse") or ""),
                    str(p.get("locationRunId") or ""),
                ))
            if m == Methods.MEANING_ANALYSIS_STATUS:
                return EngineResponse.ok(request.id, result=self.meaning_analysis_status(
                    str(p.get("runId") or ""),
                ))
            if m == Methods.MEANING_ANALYSIS_GET_RANGE:
                return EngineResponse.ok(request.id, result=self.meaning_analysis_get_range(
                    str(p.get("runId") or ""),
                ))
            if m == Methods.MEANING_ANALYSIS_GET_ASSESSMENT:
                return EngineResponse.ok(request.id, result=self.meaning_analysis_get_assessment(
                    str(p.get("assessmentId") or ""),
                ))
            if m == Methods.MEANING_ANALYSIS_GET_COMPONENTS:
                return EngineResponse.ok(request.id, result=self.meaning_analysis_get_components(
                    str(p.get("assessmentId") or ""),
                ))
            if m == Methods.MEANING_ANALYSIS_GET_DIAGNOSTICS:
                return EngineResponse.ok(request.id, result=self.meaning_analysis_get_diagnostics(
                    str(p.get("runId") or ""),
                ))
            if m == Methods.QA_AUDIT_RUN_RANGE:
                return EngineResponse.ok(request.id, result=self.qa_audit_run_range(
                    str(p.get("chapter") or ""), str(p.get("verse") or ""),
                    str(p.get("endChapter") or ""), str(p.get("endVerse") or ""),
                    str(p.get("meaningRunId") or ""),
                ))
            if m == Methods.QA_AUDIT_STATUS:
                return EngineResponse.ok(request.id, result=self.qa_audit_status(
                    str(p.get("runId") or ""),
                ))
            if m == Methods.QA_AUDIT_GET_RANGE:
                return EngineResponse.ok(request.id, result=self.qa_audit_get_range(
                    str(p.get("runId") or ""),
                ))
            if m == Methods.QA_AUDIT_GET_SOURCE_COVERAGE:
                return EngineResponse.ok(request.id, result=self.qa_audit_get_source_coverage(
                    str(p.get("runId") or ""),
                ))
            if m == Methods.QA_AUDIT_GET_TARGET_SUPPORT:
                return EngineResponse.ok(request.id, result=self.qa_audit_get_target_support(
                    str(p.get("runId") or ""),
                ))
            if m == Methods.QA_AUDIT_GET_FINDING:
                return EngineResponse.ok(request.id, result=self.qa_audit_get_finding(
                    str(p.get("findingId") or ""),
                ))
            if m == Methods.QA_AUDIT_GET_DIAGNOSTICS:
                return EngineResponse.ok(request.id, result=self.qa_audit_get_diagnostics(
                    str(p.get("runId") or ""),
                ))
            if m == Methods.QA_REVIEW_GET_QUEUE:
                return EngineResponse.ok(request.id, result=self.qa_review_get_queue(
                    book=str(p.get("book") or ""),
                    chapter=(int(p["chapter"]) if p.get("chapter") not in (None, "") else None),
                    canonical_references=tuple(p.get("canonicalReferences") or ()),
                    kinds=tuple(p.get("kinds") or ()),
                    severities=tuple(p.get("severities") or ()),
                    dispositions=tuple(p.get("dispositions") or ()),
                    review_statuses=tuple(p.get("reviewStatuses") or ()),
                    lifecycle_statuses=tuple(p.get("lifecycleStatuses") or ()),
                    order=str(p.get("order") or "CANONICAL"),
                    limit=int(p.get("limit") or 50), cursor=str(p.get("cursor") or ""),
                ))
            if m == Methods.QA_REVIEW_GET_FINDING:
                return EngineResponse.ok(request.id, result=self.qa_review_get_finding(
                    str(p.get("findingId") or ""),
                ))
            if m == Methods.QA_REVIEW_DECIDE_FINDING:
                return EngineResponse.ok(request.id, result=self.qa_review_decide_finding(
                    str(p.get("findingId") or ""), str(p.get("disposition") or ""),
                    expected_revision=int(p.get("expectedEntityRevision") or 0),
                    expected_target_content_hashes=tuple(p.get("expectedTargetContentHashes") or ()),
                    note=str(p.get("note") or ""), promote=bool(p.get("promote") or False),
                ))
            if m == Methods.QA_REVIEW_ADD_NOTE:
                return EngineResponse.ok(request.id, result=self.qa_review_add_note(
                    str(p.get("entityType") or ""), str(p.get("entityId") or ""),
                    str(p.get("note") or ""),
                ))
            if m == Methods.SEMANTIC_REVIEW_DECIDE_LOCATION:
                return EngineResponse.ok(request.id, result=self.semantic_review_decide_location(
                    str(p.get("relationshipId") or ""), str(p.get("decision") or ""),
                    expected_revision=int(p.get("expectedEntityRevision") or 0),
                    note=str(p.get("note") or ""),
                    selected_candidate_id=str(p.get("selectedCandidateId") or ""),
                ))
            if m == Methods.SEMANTIC_REVIEW_DECIDE_MEANING:
                return EngineResponse.ok(request.id, result=self.semantic_review_decide_meaning(
                    str(p.get("assessmentId") or ""), str(p.get("meaningStatus") or ""),
                    expected_revision=int(p.get("expectedEntityRevision") or 0),
                    note=str(p.get("note") or ""),
                ))
            if m == Methods.REVIEW_HISTORY_GET_ENTITY_HISTORY:
                return EngineResponse.ok(request.id, result=self.review_history_get_entity_history(
                    str(p.get("entityType") or ""), str(p.get("entityId") or ""),
                ))
            if m == Methods.ANALYSIS_JOB_START:
                return EngineResponse.ok(request.id, result=self.analysis_job_start(
                    dict(p.get("requestedScope") or {}),
                    str(p.get("expectedAnalysisFingerprint") or ""),
                ))
            if m == Methods.ANALYSIS_JOB_STATUS:
                return EngineResponse.ok(request.id, result=self.analysis_job_status(
                    str(p.get("jobId") or ""),
                ))
            if m == Methods.ANALYSIS_JOB_CANCEL:
                return EngineResponse.ok(request.id, result=self.analysis_job_cancel(
                    str(p.get("jobId") or ""),
                ))
            if m == Methods.ANALYSIS_JOB_GET_RECENT:
                return EngineResponse.ok(request.id, result=self.analysis_job_get_recent(
                    int(p.get("limit") or 20),
                ))
            if m == Methods.ANALYSIS_JOB_GET_SCOPE_STATUS:
                return EngineResponse.ok(request.id, result=self.analysis_job_get_scope_status(
                    dict(p.get("requestedScope") or {}),
                ))
            if m == Methods.ISSUE_RESOLUTION_LIST:
                return EngineResponse.ok(
                    request.id, result=self.list_issue_resolutions(p["chapter"], p["verse"]),
                )
            if m == Methods.ISSUE_RESOLUTION_SAVE:
                return EngineResponse.ok(request.id, result=self.save_issue_resolution(
                    p["chapter"], p["verse"], p["tool"], p["groupId"], p["checkId"],
                    p.get("expectedFingerprint", ""), p.get("selectedText", ""),
                    p.get("issueSummary", ""), p.get("reviewerNote", ""),
                    p.get("proposedCorrection", ""), p.get("evidence", []),
                ))
            if m == Methods.ISSUE_RESOLUTION_QUEUE_PARATEXT:
                return EngineResponse.ok(request.id, result=self.queue_issue_resolution_for_paratext(
                    p["chapter"], p["verse"], p["resolutionId"], p.get("expectedProjectId", ""),
                ))
            if m == Methods.ISSUE_RESOLUTION_RETRY_PARATEXT:
                return EngineResponse.ok(request.id, result=self.retry_issue_resolution_paratext(
                    p["chapter"], p["verse"], p["resolutionId"],
                ))
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
            if m in (Methods.NAVIGATION_STATUS, Methods.NAVIGATION_POLL):
                return EngineResponse.ok(request.id, result=self.navigation_status(
                    str(p.get("context") or ""),
                ))
            if m == Methods.NAVIGATION_BRIDGE_CHANGED:
                return EngineResponse.ok(request.id, result=self.navigation_bridge_changed(
                    p.get("reference", ""),
                ))
            if m == Methods.NAVIGATION_RESOLVE:
                return EngineResponse.ok(request.id, result=self.navigation_resolve(
                    str(p.get("requestId") or ""), bool(p.get("accepted", False)),
                    str(p.get("bridgeReference") or ""), str(p.get("context") or ""),
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
        except SweepNotFound as exc:
            return EngineResponse.fail(request.id, "sweep_not_found", str(exc))
        except SweepConflict as exc:
            return EngineResponse.fail(request.id, "sweep_conflict", str(exc))
        except SweepError as exc:
            return EngineResponse.fail(request.id, "sweep_error", str(exc))
        except AnalysisJobNotFound as exc:
            return EngineResponse.fail(request.id, "analysis_job_not_found", str(exc))
        except AnalysisJobConflict as exc:
            return EngineResponse.fail(request.id, "analysis_job_conflict", str(exc))
        except AnalysisJobError as exc:
            return EngineResponse.fail(request.id, "analysis_job_error", str(exc))
        except FoundationConflict as exc:
            # Optimistic concurrency: a human review decision written against a
            # revision that has since moved is rejected, never merged blindly.
            return EngineResponse.fail(request.id, "revision_conflict", str(exc))
        except FoundationValidationError as exc:
            return EngineResponse.fail(request.id, "semantic_validation_error", str(exc))
        except Exception as exc:  # noqa: BLE001 - protocol boundary must never crash the sidecar
            return EngineResponse.fail(request.id, "internal_error", str(exc))
