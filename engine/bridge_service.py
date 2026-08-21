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
import os
import re
import threading
from pathlib import Path
from typing import Any, Optional

from greek_room_engine.engine import GreekRoomEngine
from greek_room_engine.adapters.usfm_adapter import UsfmCheckerCancelled, UsfmCheckerError
from greek_room_engine.models.finding import QaFinding, FindingCategory, Severity, FindingStatus
from greek_room_engine.protocol import EngineRequest, EngineResponse

from tc_ai_bridge.tc_project import TranslationCoreProject, ProjectError
from tc_ai_bridge.project_import import import_source, inspect_import, apply_resource_materialization
from tc_ai_bridge.local_checks import run_local_qa
from tc_ai_bridge.models import QAIssue
from tc_ai_bridge.secret_store import AppSettings
from tc_ai_bridge.resource_materializer import materialize_book_checks
from check_jobs import (
    CheckJobConflict,
    CheckJobError,
    CheckJobManager,
    CheckJobNotFound,
    CheckJobSpec,
)

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

    SETTINGS_GET = "settings.get"
    SETTINGS_SET = "settings.set"

    EXPORT_ALIGNED = "export.aligned"
    EXPORT_NON_ALIGNED = "export.nonAligned"


class BridgeEngine:
    def __init__(self, settings: Optional[AppSettings] = None) -> None:
        self.greek_room = GreekRoomEngine()
        self.project: Optional[TranslationCoreProject] = None
        # USFM structural checks run once per whole book (not once per
        # verse — each run spawns a subprocess loading a real tag/Unicode
        # database, far too slow to repeat per verse.runChecks call). Keyed
        # by project path so switching books/projects naturally invalidates.
        # Not invalidated by verse.edit — see _usfm_findings_for_book.
        self._usfm_findings_by_book: dict[str, list[QaFinding]] = {}
        self._usfm_errors_by_book: dict[str, str] = {}
        self._checker_lock = threading.RLock()
        self._check_jobs = CheckJobManager()
        # AppSettings() with no path defaults to a real, persistent location
        # (%LOCALAPPDATA%/.translationcore-ai-bridge/settings.json on
        # Windows), and get_api_key() also checks OPENAI_API_KEY. That's
        # correct for production use — settings should survive restarts —
        # but tests must inject an isolated instance rather than touch the
        # real machine's settings. See tests/test_bridge_service.py.
        self.settings = settings if settings is not None else AppSettings()

        # Keep imported projects in application-owned storage. Older builds
        # placed settings.json directly under LOCALAPPDATA, so account for
        # that legacy path instead of creating a generic LOCALAPPDATA/projects.
        settings_root = self.settings.path.parent
        local_app_data = os.getenv("LOCALAPPDATA")
        if local_app_data:
            try:
                if settings_root.resolve() == Path(local_app_data).resolve():
                    settings_root = settings_root / ".translationcore-ai-bridge"
            except OSError:
                pass
        self.project_root = settings_root / "projects"

    # -- lifecycle ------------------------------------------------------

    def info(self) -> dict[str, Any]:
        return {
            "bridgeVersion": BRIDGE_VERSION,
            "projectOpen": self.project is not None,
            "greekRoom": self.greek_room.info(),
        }

    def open_project(self, path: str) -> dict[str, Any]:
        self._usfm_findings_by_book.clear()
        self._usfm_errors_by_book.clear()
        self.project = TranslationCoreProject(path)
        return self._project_info()

    def _project_info(self) -> dict[str, Any]:
        self._require_project()
        summary = self.project.summary  # property, not a method
        target = self.project.manifest.get("target_language", {})
        resource = self.project.manifest.get("resource", {})
        bridge_project = self.project.manifest.get("bridge_project", {})
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
        }

    def inspect_project_import(self, path: str) -> dict[str, Any]:
        """Read-only detection/validation used before the metadata form."""
        return inspect_import(path)

    def import_project(self, path: str, metadata: dict[str, Any],
                       destination_root: str = "") -> dict[str, Any]:
        """Normalize USFM/SFM, Paratext folders, or tC archives, then open it.

        Existing translationCore state is copied intact. Raw Scripture becomes
        a tC-compatible book project with chapter JSON, preserved source USFM,
        word-bank/alignment data, provenance, and real translationNotes/
        translationWords indexes materialized from the bundled English
        resource snapshot (see tc_ai_bridge.resource_materializer).
        """
        root = Path(destination_root).resolve() if destination_root else self.project_root
        result = import_source(path, root, metadata)

        # Only raw Scripture imports need materialized tN/tW — an imported
        # existing translationCore/translationStudio project already has
        # its own real indexes, which must never be overwritten with the
        # bundled English snapshot (see docs/IMPORTS.md's tN/tW boundary).
        if result["kind"] not in {"translationCore", "translationCoreArchive"}:
            resources_root = root.parent / "resources"
            for entry in result["projects"]:
                project_root = Path(entry["path"])
                materialization = materialize_book_checks(project_root, entry["bookId"], resources_root)
                apply_resource_materialization(project_root, materialization)
                statuses = {materialization["translationNotes"]["status"], materialization["translationWords"]["status"]}
                entry["checkIndexStatus"] = "ready" if statuses == {"ready"} else ("unavailable" if statuses == {"unavailable"} else "partial")
                entry["resourceMaterialization"] = materialization

        self.project = TranslationCoreProject(result["primaryProjectPath"])
        self._usfm_findings_by_book.clear()
        self._usfm_errors_by_book.clear()
        info = self._project_info()
        info["import"] = result
        info["importedProjects"] = result["projects"]
        return info

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
        if any(name in spec.checks for name in ("local", "usfm")):
            def run_preflight(cancel_event: threading.Event) -> None:
                with self._checker_lock:
                    self._usfm_findings_for_book(project, cancel_event=cancel_event)
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

    def _source_preserving_usfm(self) -> str | None:
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
            current_text = self.project.target_verse_text(chapter, verse).strip()
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
        """Writes a structured JSON export: per chapter/verse, target text
        + full alignment groups + any recorded human QA decisions. This is
        genuinely complete (alignment data IS already the project's native
        format, nothing simplified here)."""
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
            if m == Methods.PROJECT_INSPECT_IMPORT:
                return EngineResponse.ok(request.id, result=self.inspect_project_import(p["path"]))
            if m == Methods.PROJECT_IMPORT:
                return EngineResponse.ok(request.id, result=self.import_project(
                    p["path"], p.get("metadata", {}), p.get("destinationRoot", ""),
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
        except UsfmCheckerError as exc:
            return EngineResponse.fail(request.id, "checker_error", str(exc))
        except CheckJobNotFound as exc:
            return EngineResponse.fail(request.id, "job_not_found", str(exc))
        except CheckJobConflict as exc:
            return EngineResponse.fail(request.id, "job_conflict", str(exc))
        except CheckJobError as exc:
            return EngineResponse.fail(request.id, "job_error", str(exc))
        except Exception as exc:  # noqa: BLE001 - protocol boundary must never crash the sidecar
            return EngineResponse.fail(request.id, "internal_error", str(exc))
