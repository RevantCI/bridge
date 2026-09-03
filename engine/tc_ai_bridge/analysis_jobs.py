"""Stage 9A.4 background orchestration for the frozen Stage 5--8 engines.

The worker coordinates existing content-addressed engines; it does not
implement semantic analysis itself.  Job state is persisted in the companion
SQLite database after every stage so a crashed/restarted sidecar cannot leave
an incomplete analysis looking current.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import threading
import time
from typing import Any
import uuid

from .passage_semantic_repository import (
    FoundationConflict,
    FoundationValidationError,
)


STAGES = (
    "SOURCE_INVENTORY", "TARGET_INVENTORY", "LOCATION", "MEANING", "QA",
)
TERMINAL = {"COMPLETED", "COMPLETED_WITH_WARNINGS", "FAILED", "CANCELLED"}


class AnalysisJobError(RuntimeError):
    pass


class AnalysisJobConflict(AnalysisJobError):
    pass


class AnalysisJobNotFound(AnalysisJobError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _reference_parts(reference: str) -> tuple[str, str]:
    _, _, location = str(reference).rpartition(" ")
    chapter, separator, verse = location.partition(":")
    if not separator or not chapter.isdigit() or not verse.isdigit():
        raise FoundationValidationError(f"Analysis requires a numbered reference: {reference}")
    return chapter, verse


class _Control:
    def __init__(self, runtime: Any, payload: dict[str, Any]):
        self.runtime = runtime
        self.payload = payload
        self.cancel = threading.Event()
        self.lock = threading.RLock()

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return copy.deepcopy(self.payload)

    def persist(self) -> None:
        with self.lock:
            self.payload = self.runtime.repository.update_analysis_job(
                self.payload["jobId"], self.payload, self.payload["revision"],
            )


class AnalysisJobManager:
    """Own background analysis jobs and recover their durable snapshots."""

    def __init__(self, *, allow_fixture_provider: bool = False) -> None:
        self._jobs: dict[str, _Control] = {}
        self._repositories: dict[str, Any] = {}
        self._active_by_project: dict[str, str] = {}
        self._lock = threading.RLock()
        self._allow_fixture_provider = allow_fixture_provider

    @staticmethod
    def provider_capability(runtime: Any) -> dict[str, Any]:
        provider = runtime.semantic_location.embedding_provider
        available = bool(getattr(provider, "available", False))
        fixture = bool(getattr(provider, "fixture_only", False))
        return {
            "semanticRetrieval": "FULL" if available and not fixture else "LIMITED",
            "multilingualEmbeddingProvider": (
                "AVAILABLE" if available and not fixture else
                "FIXTURE_ONLY" if fixture else "NOT_CONFIGURED"
            ),
            "providerId": str(getattr(provider, "provider_id", "unavailable")),
            "providerVersion": str(getattr(provider, "provider_version", "")),
            "modelHash": str(getattr(provider, "model_hash", "")),
            "fixtureProvider": fixture,
        }

    @staticmethod
    def _same_provider(job: dict[str, Any], capability: dict[str, Any]) -> bool:
        previous = job.get("providerCapability") or {}
        return all(
            previous.get(key) == capability.get(key)
            for key in (
                "semanticRetrieval", "multilingualEmbeddingProvider", "providerId",
                "providerVersion", "modelHash", "fixtureProvider",
            )
        )

    def bind_runtime(self, runtime: Any) -> int:
        """Bind persisted jobs and recover workers lost on a prior restart."""
        project_id = runtime.project_id
        with self._lock:
            active_ids = tuple(
                job_id for job_id, control in self._jobs.items()
                if control.payload["projectId"] == project_id
                and control.payload["overallStatus"] not in TERMINAL
            )
        recovered = runtime.repository.recover_analysis_jobs(
            project_id, active_job_ids=active_ids,
        )
        for payload in runtime.repository.recent_analysis_jobs(project_id, book=runtime.book, limit=100):
            self._repositories[payload["jobId"]] = runtime.repository
        return recovered

    @classmethod
    def _resolve_scope(cls, runtime: Any, requested: dict[str, Any]) -> dict[str, Any]:
        kind = str(requested.get("kind") or "").upper()
        if kind not in {
            "CURRENT_PASSAGE", "CURRENT_CHAPTER", "CURRENT_BOOK", "SELECTED_RANGE", "AFFECTED",
        }:
            raise AnalysisJobError("Unknown analysis scope")

        chapter = str(requested.get("startChapter") or requested.get("chapter") or "")
        verse = str(requested.get("startVerse") or requested.get("verse") or "")
        end_chapter = str(requested.get("endChapter") or "")
        end_verse = str(requested.get("endVerse") or "")

        if kind == "CURRENT_CHAPTER":
            if not chapter:
                raise AnalysisJobError("Current chapter is required")
            verses = [value for value in runtime.project.verses(chapter) if str(value).isdigit()]
            if not verses:
                raise AnalysisJobError("The selected chapter has no numbered verses")
            verse, end_chapter, end_verse = verses[0], chapter, verses[-1]
        elif kind == "CURRENT_BOOK":
            chapters = [value for value in runtime.project.chapters() if str(value).isdigit()]
            if not chapters:
                raise AnalysisJobError("The current book has no numbered chapters")
            chapter, end_chapter = chapters[0], chapters[-1]
            first = [value for value in runtime.project.verses(chapter) if str(value).isdigit()]
            last = [value for value in runtime.project.verses(end_chapter) if str(value).isdigit()]
            if not first or not last:
                raise AnalysisJobError("The current book has no numbered verses")
            verse, end_verse = first[0], last[-1]
        elif kind == "CURRENT_PASSAGE":
            if not chapter or not verse:
                raise AnalysisJobError("Current passage reference is required")
            structural = runtime.rebuild_current_passage(chapter, verse)
            displayed = list(structural.get("displayedTargetReferences") or ())
            if not displayed:
                raise AnalysisJobError("The current structural passage is unavailable")
            chapter, verse = _reference_parts(displayed[0])
            end_chapter, end_verse = _reference_parts(displayed[-1])
        elif kind == "AFFECTED":
            chapter, verse, end_chapter, end_verse = cls._resolve_affected(
                runtime, requested, chapter, verse, end_chapter, end_verse,
            )
        elif not all((chapter, verse, end_chapter, end_verse)):
            raise AnalysisJobError("Selected range requires start and end references")

        passage = runtime.rebuild_current_passage(chapter, verse, end_chapter, end_verse)
        displayed = list(passage.get("displayedTargetReferences") or ())
        if not displayed:
            raise AnalysisJobError("The requested analysis range is empty")
        return {
            "kind": kind,
            "startChapter": chapter, "startVerse": verse,
            "endChapter": end_chapter or chapter, "endVerse": end_verse or verse,
            "displayedReferences": displayed,
            "canonicalReferences": list(passage.get("canonicalReferences") or ()),
            "rangeKey": f"{displayed[0]}..{displayed[-1]}",
            "targetContentHash": str(passage["targetContentHash"]),
            "targetHashes": {
                reference: _text_hash(text)
                for reference, text in (passage.get("targetTextByDisplayedReference") or {}).items()
            },
        }

    @classmethod
    def _resolve_affected(
        cls, runtime: Any, requested: dict[str, Any], chapter: str, verse: str,
        end_chapter: str, end_verse: str,
    ) -> tuple[str, str, str, str]:
        base = dict(requested)
        base["kind"] = str(requested.get("baseKind") or "SELECTED_RANGE")
        resolved = cls._resolve_scope(runtime, base)
        recent = runtime.repository.recent_analysis_jobs(
            runtime.project_id, book=runtime.book, limit=100,
        )
        prior = next((item for item in recent if item.get("rangeKey") == resolved["rangeKey"]), None)
        if prior is None:
            return (
                resolved["startChapter"], resolved["startVerse"],
                resolved["endChapter"], resolved["endVerse"],
            )
        changed = [
            reference for reference, digest in resolved["targetHashes"].items()
            if (prior.get("targetHashes") or {}).get(reference) != digest
        ]
        if not changed:
            return (
                resolved["startChapter"], resolved["startVerse"],
                resolved["endChapter"], resolved["endVerse"],
            )
        structural_refs: list[str] = []
        for reference in changed:
            ch, vs = _reference_parts(reference)
            passage = runtime.rebuild_current_passage(ch, vs)
            structural_refs.extend(passage.get("displayedTargetReferences") or ())
        ordered = cls._project_reference_order(runtime)
        positions = [ordered.index(ref) for ref in dict.fromkeys(structural_refs) if ref in ordered]
        if not positions:
            first, last = changed[0], changed[-1]
        else:
            first, last = ordered[min(positions)], ordered[max(positions)]
        return (*_reference_parts(first), *_reference_parts(last))

    @staticmethod
    def _project_reference_order(runtime: Any) -> list[str]:
        result: list[str] = []
        for chapter in runtime.project.chapters():
            for verse in runtime.project.verses(chapter):
                if str(chapter).isdigit() and str(verse).isdigit():
                    result.append(f"{runtime.book} {chapter}:{verse}")
        return result

    @classmethod
    def new_job_payload(cls, runtime: Any, requested_scope: dict[str, Any]) -> dict[str, Any]:
        resolved = cls._resolve_scope(runtime, requested_scope)
        source_lock = runtime.repository.source_lock(runtime.project_id, runtime.book) or {}
        capability = cls.provider_capability(runtime)
        warnings: list[dict[str, str]] = []
        if capability["fixtureProvider"]:
            warnings.append({
                "code": "FIXTURE_EMBEDDING_PROVIDER",
                "message": "Semantic retrieval used an explicitly enabled fixture provider; this is not production analysis.",
            })
        elif capability["semanticRetrieval"] != "FULL":
            warnings.append({
                "code": "MULTILINGUAL_EMBEDDING_PROVIDER_NOT_CONFIGURED",
                "message": "Semantic retrieval is limited because no production multilingual embedding provider is configured.",
            })
        now = _now()
        stages = {
            stage: {"status": "NOT_STARTED", "runId": "", "cacheStatus": "", "elapsedSeconds": None}
            for stage in STAGES
        }
        return {
            "jobId": str(uuid.uuid4()), "projectId": runtime.project_id, "book": runtime.book,
            "requestedScope": {
                **{key: value for key, value in requested_scope.items() if value not in (None, "")},
                "kind": resolved["kind"],
                "resolvedStartChapter": resolved["startChapter"],
                "resolvedStartVerse": resolved["startVerse"],
                "resolvedEndChapter": resolved["endChapter"],
                "resolvedEndVerse": resolved["endVerse"],
            },
            "rangeKey": resolved["rangeKey"],
            "displayedReferences": resolved["displayedReferences"],
            "canonicalReferences": resolved["canonicalReferences"],
            "targetContentHash": resolved["targetContentHash"],
            "targetHashes": resolved["targetHashes"],
            "sourceResourceHash": str(source_lock.get("resource_hash") or "unavailable"),
            "createdAt": now, "startedAt": None, "completedAt": None,
            "currentStage": "", "overallStatus": "QUEUED",
            "stageStatuses": stages,
            "stageProgress": {"completedStages": 0, "totalStages": len(STAGES)},
            "reusedRunIds": [], "createdRunIds": [], "warnings": warnings,
            "failures": [], "cancellationRequested": False,
            "providerCapability": capability, "timings": {}, "qaFindingCount": None,
            "searchIncomplete": False,
        }

    def start(self, runtime: Any, *, requested_scope: dict[str, Any]) -> dict[str, Any]:
        if self.provider_capability(runtime)["fixtureProvider"] and not self._allow_fixture_provider:
            raise AnalysisJobError(
                "Fixture semantic providers cannot run in the normal Bridge analysis workflow"
            )
        payload = self.new_job_payload(runtime, requested_scope)
        project_id = runtime.project_id
        with self._lock:
            active_id = self._active_by_project.get(project_id, "")
            active = self._jobs.get(active_id)
            if active and active.payload["overallStatus"] not in TERMINAL:
                raise AnalysisJobConflict(f"Analysis job {active_id} is already running")
            try:
                payload = runtime.repository.create_analysis_job(payload)
            except FoundationConflict as exc:
                raise AnalysisJobConflict(str(exc)) from exc
            control = _Control(runtime, payload)
            self._jobs[payload["jobId"]] = control
            self._repositories[payload["jobId"]] = runtime.repository
            self._active_by_project[project_id] = payload["jobId"]
        threading.Thread(
            target=self._run, args=(control,),
            name=f"bridge-analysis-{payload['jobId'][:8]}", daemon=True,
        ).start()
        return control.snapshot()

    def status(self, job_id: str = "") -> dict[str, Any]:
        with self._lock:
            if not job_id and self._active_by_project:
                job_id = next(reversed(self._active_by_project.values()))
            control = self._jobs.get(job_id)
            repository = self._repositories.get(job_id)
        if control:
            return control.snapshot()
        if repository:
            return repository.analysis_job(job_id)
        raise AnalysisJobNotFound(f"Unknown analysis job '{job_id}'")

    def cancel(self, job_id: str = "") -> dict[str, Any]:
        with self._lock:
            if not job_id and self._active_by_project:
                job_id = next(reversed(self._active_by_project.values()))
            control = self._jobs.get(job_id)
        if control is None:
            raise AnalysisJobNotFound(f"Unknown or inactive analysis job '{job_id}'")
        with control.lock:
            if control.payload["overallStatus"] not in TERMINAL:
                control.cancel.set()
                control.payload["cancellationRequested"] = True
                control.persist()
        return control.snapshot()

    def get_recent(self, runtime: Any, limit: int = 20) -> list[dict[str, Any]]:
        return runtime.repository.recent_analysis_jobs(
            runtime.project_id, book=runtime.book, limit=limit,
        )

    def get_scope_status(self, runtime: Any, requested_scope: dict[str, Any]) -> dict[str, Any]:
        resolved = self._resolve_scope(runtime, requested_scope)
        recent = runtime.repository.recent_analysis_jobs(
            runtime.project_id, book=runtime.book, limit=100,
        )
        source_lock = runtime.repository.source_lock(runtime.project_id, runtime.book) or {}
        current_source_hash = str(source_lock.get("resource_hash") or "unavailable")
        current_capability = self.provider_capability(runtime)
        exact = next((item for item in recent if item.get("rangeKey") == resolved["rangeKey"]), None)
        if exact is None:
            partial = any(
                item.get("overallStatus") in {"COMPLETED", "COMPLETED_WITH_WARNINGS"}
                and str(item.get("sourceResourceHash") or "") == current_source_hash
                and self._same_provider(item, current_capability)
                and any(
                    (item.get("targetHashes") or {}).get(reference) == digest
                    for reference, digest in resolved["targetHashes"].items()
                )
                for item in recent
            )
            return self._scope_status_payload(
                "PARTIALLY_ANALYZED" if partial else "NOT_ANALYZED",
                resolved,
                None,
                [],
                current_capability,
            )
        current_hashes = resolved["targetHashes"]
        old_hashes = exact.get("targetHashes") or {}
        affected = [ref for ref, digest in current_hashes.items() if old_hashes.get(ref) != digest]
        source_changed = str(exact.get("sourceResourceHash") or "") != current_source_hash
        provider_changed = not self._same_provider(exact, current_capability)
        status = exact.get("overallStatus")
        if status in {"QUEUED", "RUNNING"}:
            state = "RUNNING"
        elif affected or source_changed or provider_changed:
            if source_changed or provider_changed:
                affected = list(resolved["displayedReferences"])
                state = "STALE"
            else:
                # A stale-only run intentionally has a smaller range key than
                # the original chapter/book job. Compose it with unchanged
                # content-addressed results instead of leaving the parent
                # scope permanently marked stale.
                replacement_jobs: list[dict[str, Any]] = []
                unresolved: list[str] = []
                for reference in affected:
                    replacement = next((
                        item for item in recent
                        if item.get("jobId") != exact.get("jobId")
                        and item.get("overallStatus") in {"COMPLETED", "COMPLETED_WITH_WARNINGS"}
                        and str(item.get("sourceResourceHash") or "") == current_source_hash
                        and self._same_provider(item, current_capability)
                        and (item.get("targetHashes") or {}).get(reference) == current_hashes[reference]
                    ), None)
                    if replacement is None:
                        unresolved.append(reference)
                    else:
                        replacement_jobs.append(replacement)
                affected = unresolved
                if not affected:
                    state = (
                        "SEARCH_INCOMPLETE"
                        if any(item.get("searchIncomplete") for item in replacement_jobs)
                        else "CURRENT"
                    )
                else:
                    state = "STALE"
        elif status == "FAILED":
            state = "FAILED"
        elif exact.get("searchIncomplete"):
            state = "SEARCH_INCOMPLETE"
        elif status in {"COMPLETED", "COMPLETED_WITH_WARNINGS"}:
            state = "CURRENT"
        else:
            state = "NOT_ANALYZED"
        return self._scope_status_payload(
            state, resolved, exact, affected, current_capability,
        )

    def _scope_status_payload(
        self, state: str, resolved: dict[str, Any], job: dict[str, Any] | None,
        affected: list[str], provider_capability: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "state": state, "rangeKey": resolved["rangeKey"],
            "displayedReferences": resolved["displayedReferences"],
            "canonicalReferences": resolved["canonicalReferences"],
            "affectedReferences": affected,
            "latestJob": job,
            "providerCapability": provider_capability,
        }

    @staticmethod
    def _cancelled(control: _Control) -> bool:
        if not control.cancel.is_set():
            return False
        with control.lock:
            control.payload["overallStatus"] = "CANCELLED"
            control.payload["currentStage"] = ""
            control.payload["completedAt"] = _now()
            current = next((s for s in STAGES if control.payload["stageStatuses"][s]["status"] == "RUNNING"), "")
            if current:
                control.payload["stageStatuses"][current]["status"] = "CANCELLED"
            control.persist()
        return True

    def _run(self, control: _Control) -> None:
        runtime = control.runtime
        scope = control.payload["requestedScope"]
        args = (
            scope["resolvedStartChapter"], scope["resolvedStartVerse"],
            scope["resolvedEndChapter"], scope["resolvedEndVerse"],
        )
        with control.lock:
            control.payload["overallStatus"] = "RUNNING"
            control.payload["startedAt"] = _now()
            control.persist()
        results: dict[str, dict[str, Any]] = {}
        operations = (
            ("SOURCE_INVENTORY", lambda: runtime.source_semantic.build_range(*args)),
            ("TARGET_INVENTORY", lambda: runtime.target_semantic.build_range(*args)),
            ("LOCATION", lambda: runtime.semantic_location.run_range(*args)),
            ("MEANING", lambda: runtime.meaning_analysis.run_range(
                *args, location_run_id=results["LOCATION"]["id"],
            )),
            ("QA", lambda: runtime.qa_audit.run_range(
                *args, meaning_run_id=results["MEANING"]["id"],
            )),
        )
        try:
            for stage, operation in operations:
                if self._cancelled(control):
                    return
                with control.lock:
                    control.payload["currentStage"] = stage
                    control.payload["stageStatuses"][stage]["status"] = "RUNNING"
                    control.persist()
                started = time.perf_counter()
                try:
                    result = operation()
                except Exception as exc:
                    elapsed = time.perf_counter() - started
                    with control.lock:
                        control.payload["stageStatuses"][stage].update({
                            "status": "FAILED", "elapsedSeconds": elapsed,
                        })
                        control.payload["timings"][stage] = elapsed
                        control.payload["failures"].append({
                            "stage": stage, "code": type(exc).__name__, "message": str(exc),
                        })
                        control.payload["overallStatus"] = "FAILED"
                        control.payload["currentStage"] = ""
                        control.payload["completedAt"] = _now()
                        control.persist()
                    return
                elapsed = time.perf_counter() - started
                results[stage] = result
                cache = str(result.get("cacheStatus") or "MISS")
                run_id = str(result.get("id") or "")
                with control.lock:
                    control.payload["stageStatuses"][stage].update({
                        "status": "REUSED" if cache == "HIT" else "COMPLETED",
                        "runId": run_id, "cacheStatus": cache, "elapsedSeconds": elapsed,
                    })
                    control.payload["timings"][stage] = elapsed
                    control.payload["stageProgress"]["completedStages"] += 1
                    if run_id:
                        key = "reusedRunIds" if cache == "HIT" else "createdRunIds"
                        control.payload[key].append(run_id)
                    if stage == "QA":
                        control.payload["qaFindingCount"] = len(result.get("findings") or ())
                        control.payload["stage8PhaseTimings"] = result.get("phaseProfile") or {}
                    control.persist()
            if self._cancelled(control):
                return
            location_diagnostics = results["LOCATION"].get("diagnostics") or {}
            incomplete = int(location_diagnostics.get("searchIncomplete") or 0)
            with control.lock:
                if incomplete:
                    control.payload["searchIncomplete"] = True
                    control.payload["warnings"].append({
                        "code": "SEARCH_INCOMPLETE",
                        "message": f"Semantic search was incomplete for {incomplete} source meanings; no omission was inferred from them.",
                    })
                control.payload["overallStatus"] = (
                    "COMPLETED_WITH_WARNINGS" if control.payload["warnings"] else "COMPLETED"
                )
                control.payload["currentStage"] = ""
                control.payload["completedAt"] = _now()
                control.persist()
        finally:
            with self._lock:
                if self._active_by_project.get(runtime.project_id) == control.payload["jobId"]:
                    self._active_by_project.pop(runtime.project_id, None)
