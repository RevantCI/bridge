"""Stage 9B.3c correction-aware affected re-analysis orchestration.

This module resolves scope and links a correction application to the existing
Stage 9A.4 job manager. It contains no semantic pipeline of its own and never
writes Scripture or changes a semantic verification verdict.
"""
from __future__ import annotations

from datetime import datetime, timezone
import threading
from typing import Any

from .analysis_jobs import AnalysisJobManager, TERMINAL
from .passage_semantic_repository import FoundationConflict, FoundationValidationError
from .passage_semantic_runtime import _canonical_reference


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parts(reference: str) -> tuple[str, str, str]:
    book, separator, location = str(reference).strip().rpartition(" ")
    chapter, colon, verse = location.partition(":")
    if not separator or not colon or not chapter.isdigit() or not verse.isdigit():
        raise FoundationValidationError(f"Affected analysis requires a numbered reference: {reference}")
    return book.upper(), chapter, verse


class CorrectionAffectedScopeResolver:
    """Resolve the minimum safe range from durable source and target records."""

    def __init__(self, runtime: Any):
        self.runtime = runtime
        self.repository = runtime.repository

    def _source_references(
        self, application: dict[str, Any], proposal: dict[str, Any], finding: dict[str, Any],
    ) -> list[str]:
        references = [
            str(item) for item in application.get("sourceProvenanceReferences") or ()
            if str(item).strip()
        ]
        unit_ids = (
            (proposal.get("intent") or {}).get("affectedSourceSemanticUnitIds")
            or finding.get("sourceSemanticUnitIds") or ()
        )
        for unit_id in unit_ids:
            unit = self.repository.semantic_unit(str(unit_id))
            if unit.get("projectId") != self.runtime.project_id or unit.get("side") != "SOURCE":
                raise FoundationValidationError(
                    f"Affected correction source unit is invalid for this project: {unit_id}"
                )
            values = unit.get("canonicalReferences") or unit.get("displayedReferences") or ()
            references.extend(str(item) for item in values if str(item).strip())
        return list(dict.fromkeys(references))

    def _displayed_for_canonical(self, canonical_references: list[str]) -> list[str]:
        wanted = set(canonical_references)
        matched: list[str] = []
        project_schema = self.runtime._project_versification()
        for reference in AnalysisJobManager._project_reference_order(self.runtime):
            book, chapter, verse = _parts(reference)
            canonical = set(str(item) for item in _canonical_reference(
                book, chapter, verse, project_schema,
            ).get("canonicalReferences") or ())
            if reference in wanted or canonical & wanted:
                matched.append(reference)
        return matched

    def resolve(self, application_id: str) -> dict[str, Any]:
        application = self.repository.application_intent(application_id)
        if application.get("projectId") != self.runtime.project_id:
            raise FoundationValidationError("Correction application belongs to another project")
        if application.get("applicationState") != "COMPLETED":
            raise FoundationConflict("Affected analysis requires a COMPLETED correction application")
        if bool(self.runtime.application_recovery.get("correctionWritesBlocked")):
            raise FoundationConflict("Correction recovery must be healthy before affected analysis")

        proposal = self.repository.correction_proposal(application["proposalId"])
        finding = self.repository.qa_finding(application["findingId"])
        if proposal.get("verificationStatus") != "PENDING":
            raise FoundationConflict("Affected analysis requires PENDING semantic verification")

        source_references = self._source_references(application, proposal, finding)
        if not source_references:
            raise FoundationValidationError("Correction has no durable source semantic reference")
        target_references = list(dict.fromkeys([
            str(application.get("targetDisplayedReference") or ""),
            *(str(item) for item in application.get("canonicalReferences") or ()),
        ]))
        target_references = [item for item in target_references if item]
        if not target_references:
            raise FoundationValidationError("Correction has no durable target reference")

        books = {_parts(item)[0] for item in (*source_references, *target_references)}
        if books != {self.runtime.book.upper()}:
            raise FoundationValidationError("Affected analysis references do not belong to the open book")

        order = AnalysisJobManager._project_reference_order(self.runtime)
        semantic_displayed = self._displayed_for_canonical(source_references)
        exact_target = str(application["targetDisplayedReference"])
        if exact_target not in order:
            raise FoundationValidationError("The edited target reference is not in the current project")
        endpoint_references = list(dict.fromkeys([*semantic_displayed, exact_target]))
        if not semantic_displayed:
            raise FoundationValidationError(
                "Source semantic references could not be normalized into the current versification"
            )

        # Expand each endpoint through preserved structural metadata, while
        # rebuilding all wording from current editable chapter JSON.
        structural: list[str] = list(endpoint_references)
        for reference in endpoint_references:
            _book, chapter, verse = _parts(reference)
            passage = self.runtime.rebuild_current_passage(chapter, verse)
            structural.extend(str(item) for item in passage.get("displayedTargetReferences") or ())
        positions = [order.index(item) for item in dict.fromkeys(structural) if item in order]
        if not positions:
            raise FoundationValidationError("Affected structural passage could not be resolved")
        start, end = order[min(positions)], order[max(positions)]
        _book, start_chapter, start_verse = _parts(start)
        _book, end_chapter, end_verse = _parts(end)
        passage = self.runtime.rebuild_current_passage(
            start_chapter, start_verse, end_chapter, end_verse,
        )
        displayed = list(passage.get("displayedTargetReferences") or ())
        if exact_target not in displayed or not set(semantic_displayed) & set(displayed):
            raise FoundationValidationError("Resolved scope does not contain both semantic and edited targets")
        return {
            "applicationId": application_id,
            "resolvedSourceReferences": source_references,
            "resolvedTargetReferences": [exact_target],
            "sourceDisplayedReferences": semantic_displayed,
            "resolvedStructuralRange": {
                "startReference": displayed[0], "endReference": displayed[-1],
                "displayedReferences": displayed,
                "canonicalReferences": list(passage.get("canonicalReferences") or ()),
            },
            "startChapter": start_chapter, "startVerse": start_verse,
            "endChapter": end_chapter, "endVerse": end_verse,
        }


class CorrectionAffectedAnalysisService:
    """Idempotently attach explicit affected analysis to an applied correction."""

    def __init__(self, runtime: Any, jobs: AnalysisJobManager):
        self.runtime = runtime
        self.repository = runtime.repository
        self.jobs = jobs
        self.resolver = CorrectionAffectedScopeResolver(runtime)
        self._lock = threading.RLock()

    @staticmethod
    def _technical_state(job: dict[str, Any] | None) -> str:
        if not job:
            return "NOT_RUN"
        status = str(job.get("overallStatus") or "")
        if status in {"QUEUED", "RUNNING"}:
            return "RUNNING"
        if status == "COMPLETED_WITH_WARNINGS" and job.get("searchIncomplete"):
            return "SEARCH_INCOMPLETE"
        if status in {"COMPLETED", "COMPLETED_WITH_WARNINGS"}:
            return "COMPLETED"
        return status or "NOT_RUN"

    def _job(self, job_id: str) -> dict[str, Any] | None:
        if not job_id:
            return None
        try:
            return self.jobs.status(job_id)
        except Exception:
            try:
                return self.repository.analysis_job(job_id)
            except Exception:
                return None

    def _associated_jobs(self, application: dict[str, Any]) -> list[dict[str, Any]]:
        attempts = list((application.get("resultMetadata") or {}).get("affectedAnalysisAttempts") or ())
        known = {str(item.get("analysisJobId") or "") for item in attempts}
        # Recover the association if Bridge stopped after durable job creation
        # but before the application metadata CAS completed.
        for job in self.repository.recent_analysis_jobs(
            self.runtime.project_id, book=self.runtime.book, limit=100,
        ):
            requested = job.get("requestedScope") or {}
            if str(requested.get("correctionApplicationId") or "") == application["applicationId"]:
                if job["jobId"] not in known:
                    attempts.append({"analysisJobId": job["jobId"]})
                    known.add(job["jobId"])
        return attempts

    def status(self, application_id: str) -> dict[str, Any]:
        application = self.repository.application_intent(application_id)
        if application.get("projectId") != self.runtime.project_id:
            raise FoundationValidationError("Correction application belongs to another project")
        attempts = self._associated_jobs(application)
        latest = self._job(str(attempts[-1].get("analysisJobId") or "")) if attempts else None
        return {
            "applicationId": application_id,
            "applicationState": application["applicationState"],
            "verificationStatus": (
                self.repository.correction_proposal(application["proposalId"])
                .get("verificationStatus", "NOT_RUN")
            ),
            "affectedAnalysisState": self._technical_state(latest),
            "analysisJobId": str((latest or {}).get("jobId") or ""),
            "job": latest,
            "correctionWritesBlocked": bool(
                self.runtime.application_recovery.get("correctionWritesBlocked")
            ),
        }

    def start(
        self, application_id: str, *, requested_by: str, retry: bool = False,
    ) -> dict[str, Any]:
        actor = str(requested_by or "").strip()
        if not actor:
            raise FoundationValidationError("Affected analysis requires a human requester")
        with self._lock:
            application = self.repository.application_intent(application_id)
            scope = self.resolver.resolve(application_id)
            attempts = self._associated_jobs(application)
            latest = self._job(str(attempts[-1].get("analysisJobId") or "")) if attempts else None
            if latest:
                technical = self._technical_state(latest)
                if latest.get("overallStatus") not in TERMINAL:
                    return self._response(application_id, scope, latest)
                if technical == "COMPLETED":
                    return self._response(application_id, scope, latest)
                if technical in {"FAILED", "CANCELLED", "SEARCH_INCOMPLETE"} and not retry:
                    return self._response(application_id, scope, latest)

            job = self.jobs.start_correction_affected(
                self.runtime, application_id=application_id,
                start_chapter=scope["startChapter"], start_verse=scope["startVerse"],
                end_chapter=scope["endChapter"], end_verse=scope["endVerse"],
                resolved_source_references=scope["resolvedSourceReferences"],
                resolved_target_references=scope["resolvedTargetReferences"],
                requested_by=actor,
            )
            association = {
                "applicationId": application_id, "analysisJobId": job["jobId"],
                "requestedAt": _now(), "requestedBy": actor,
                "resolvedSourceReferences": scope["resolvedSourceReferences"],
                "resolvedTargetReferences": scope["resolvedTargetReferences"],
                "resolvedStructuralRange": scope["resolvedStructuralRange"],
                "targetRevision": job["targetRevision"],
                "targetContentHash": job["targetContentHash"],
                "analysisInputFingerprint": job["analysisFingerprint"],
            }
            self.repository.record_affected_analysis_association(
                application_id,
                expected_state_revision=int(application["stateRevision"]),
                association=association,
            )
            return self._response(application_id, scope, job)

    def _response(
        self, application_id: str, scope: dict[str, Any], job: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "applicationId": application_id, "analysisJobId": job["jobId"],
            "resolvedSourceReferences": scope["resolvedSourceReferences"],
            "resolvedTargetReferences": scope["resolvedTargetReferences"],
            "resolvedStructuralRange": scope["resolvedStructuralRange"],
            "jobState": self._technical_state(job), "job": job,
        }
