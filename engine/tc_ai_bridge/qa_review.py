"""Stage 9A human QA review: queue, evidence assembly, and disposition.

This module is the human-decision half of the passage-semantic pipeline. It
reads Stage 6B location, Stage 7 meaning and Stage 8 QA output and records
what a human decided about them. It never re-runs analysis, never edits
Scripture, and never generates correction wording -- that is Stage 9B.

Machine analysis and human decision are kept strictly apart: analysis APIs
(``qaAudit.*``, ``semanticLocation.*``, ``meaningAnalysis.*``) stay read-only
here, and every write goes through one of the review methods below so that
each decision leaves an auditable ReviewRecord.
"""
from __future__ import annotations

from typing import Any

from .passage_semantic_models import (
    LifecycleStatus,
    MeaningStatus,
    QaDisposition,
    ReviewStatus,
    SourceCoverage,
    TargetSupport,
)
from .passage_semantic_repository import (
    FoundationConflict,
    FoundationValidationError,
)


REVIEW_ENGINE_VERSION = "bridge-qa-review-v1"

# How a reviewer's conclusion maps onto the entity's review status.
#
# FALSE_POSITIVE is the one case where the human rejects the machine's
# claim outright, so it is the only disposition that yields HUMAN_REJECTED.
# ACCEPTABLE_TRANSLATION still counts as approving the observation -- the
# reviewer agrees something differs, and judges the difference legitimate --
# with the nuance carried by the disposition rather than the review status.
_DISPOSITION_REVIEW_STATUS = {
    QaDisposition.CONFIRMED_TRANSLATION_ERROR: ReviewStatus.HUMAN_APPROVED,
    QaDisposition.ACCEPTABLE_TRANSLATION: ReviewStatus.HUMAN_APPROVED,
    QaDisposition.FALSE_POSITIVE: ReviewStatus.HUMAN_REJECTED,
    QaDisposition.NEEDS_DISCUSSION: ReviewStatus.NEEDS_DISCUSSION,
    QaDisposition.UNRESOLVED: ReviewStatus.UNREVIEWED,
}

# Confirming a translation error is the *only* way POSSIBLY_MISSING becomes
# MISSING or POSSIBLY_UNSUPPORTED becomes UNSUPPORTED. Stage 8 deliberately
# never promotes these on its own, and merely opening a finding must not
# either -- promotion happens here, and only on an explicit decision.
_COVERAGE_PROMOTION = {
    SourceCoverage.POSSIBLY_MISSING.value: SourceCoverage.MISSING.value,
    TargetSupport.POSSIBLY_UNSUPPORTED.value: TargetSupport.UNSUPPORTED.value,
}

_DECIDABLE = {
    QaDisposition.CONFIRMED_TRANSLATION_ERROR, QaDisposition.ACCEPTABLE_TRANSLATION,
    QaDisposition.FALSE_POSITIVE, QaDisposition.NEEDS_DISCUSSION,
}


class QaReviewService:
    """Read the analysis, record the human decision. Never the reverse."""

    def __init__(self, runtime: Any, actor_id: str = "human"):
        self.runtime = runtime
        self.repository = runtime.repository
        self.project_id = runtime.project_id
        self.book = runtime.book
        self.actor_id = actor_id

    # --- Queue --------------------------------------------------------------

    def get_queue(
        self, *, book: str = "", chapter: int | None = None,
        kinds: tuple[str, ...] = (), severities: tuple[str, ...] = (),
        dispositions: tuple[str, ...] = (), review_statuses: tuple[str, ...] = (),
        lifecycle_statuses: tuple[str, ...] = (), order: str = "CANONICAL",
        limit: int = 50, cursor: str = "",
    ) -> dict[str, Any]:
        """One page of the review queue, in deterministic order."""
        page = self.repository.query_qa_findings(
            self.project_id, book=book or "", chapter=chapter, kinds=kinds,
            severities=severities, dispositions=dispositions,
            review_statuses=review_statuses, lifecycle_statuses=lifecycle_statuses,
            order=order, limit=limit, cursor=cursor,
        )
        page["findings"] = [self._summarize(finding) for finding in page["findings"]]
        return page

    @staticmethod
    def _summarize(finding: dict[str, Any]) -> dict[str, Any]:
        """The queue list needs enough to triage, not the full evidence graph."""
        return {
            "id": finding.get("id", ""), "kind": finding.get("kind", ""),
            "direction": finding.get("direction", ""),
            "severity": finding.get("severity", ""),
            "book": finding.get("book", ""),
            "displayedReferences": finding.get("displayedReferences") or [],
            "explanation": finding.get("explanation", ""),
            "qaDisposition": finding.get("qaDisposition", ""),
            "reviewStatus": finding.get("reviewStatus", ""),
            "lifecycleStatus": finding.get("lifecycleStatus", ""),
            "locationOutcomeSnapshot": finding.get("locationOutcomeSnapshot", ""),
            "meaningStatusSnapshot": finding.get("meaningStatusSnapshot", ""),
            "confidence": finding.get("confidence", {}),
            "revision": finding.get("revision", 1),
            # Possible-vs-confirmed is a property of the finding kind, not of
            # its severity; the UI must not style a possible issue as an error.
            "isPossible": str(finding.get("kind", "")).startswith("POSSIBL"),
        }

    # --- Evidence -----------------------------------------------------------

    def get_finding(self, finding_id: str) -> dict[str, Any]:
        """A finding with its evidence in layers, each independently inspectable.

        Location and meaning are returned as separate sections precisely so a
        reviewer can tell a mapping problem ("Bridge looked in the wrong
        place") from a translation problem ("Bridge found the right place and
        the meaning differs"). They must not be collapsed into one verdict.
        """
        finding = self.repository.qa_finding(finding_id)
        meanings = self._meanings(finding)
        inline = self._inline_evidence(meanings)
        return {
            "finding": finding,
            "source": self._units(finding.get("sourceSemanticUnitIds") or []),
            "target": self._units(finding.get("targetSemanticUnitIds") or []),
            "location": self._locations(finding),
            "meaning": meanings,
            "coverage": self._coverage(finding),
            "resources": self._evidence(finding.get("resourceEvidenceIds") or [], inline),
            "supportingEvidence": self._evidence(finding.get("supportingEvidenceIds") or [], inline),
            "conflictingEvidence": self._evidence(finding.get("conflictingEvidenceIds") or [], inline),
            "history": self.repository.review_records("QA_FINDING", finding_id),
            "isStale": finding.get("lifecycleStatus") == LifecycleStatus.STALE.value,
            "reviewEngineVersion": REVIEW_ENGINE_VERSION,
        }

    def _units(self, unit_ids: list[str]) -> list[dict[str, Any]]:
        return [self.repository.semantic_unit(unit_id) for unit_id in unit_ids]

    def _evidence(
        self, evidence_ids: list[str], inline: dict[str, dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """Resolve evidence ids from either store.

        Resource evidence (tN/tW/TWL) is a real ``evidence_records`` row, but
        Stage 7's per-component ``meaning-evidence-*`` ids are synthesized
        inside the assessment payload and were never written to that table.
        An id that resolves to neither is surfaced as UNRESOLVED rather than
        raising: a reviewer should see that a piece of evidence is missing,
        not be blocked from reviewing the finding at all.
        """
        inline = inline or {}
        resolved: list[dict[str, Any]] = []
        for evidence_id in evidence_ids:
            if evidence_id in inline:
                resolved.append({**inline[evidence_id], "evidenceSource": "MEANING_ASSESSMENT"})
                continue
            try:
                record = self.repository.evidence_record(evidence_id)
            except FoundationValidationError:
                resolved.append({"id": evidence_id, "evidenceSource": "UNRESOLVED"})
                continue
            resolved.append({**record, "evidenceSource": "EVIDENCE_RECORD"})
        return resolved

    def _inline_evidence(self, meanings: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        index: dict[str, dict[str, Any]] = {}
        for entry in meanings:
            for component in entry.get("components") or []:
                evidence = component.get("evidence") or {}
                evidence_id = str(evidence.get("id") or "")
                if evidence_id:
                    index[evidence_id] = {
                        **evidence,
                        "coverageDimension": component.get("coverageDimension", ""),
                        "status": component.get("status", ""),
                        "explanation": component.get("explanation", ""),
                    }
        return index

    def _location_relationship_ids(self, finding: dict[str, Any]) -> list[str]:
        """Resolve the Stage 6B locations behind a finding.

        The QA relationship id is a hash and carries no back-reference, so the
        link runs through the meaning assessment for meaning-failure findings
        and through the coverage account for coverage/support findings.
        """
        ids: list[str] = []
        for assessment_id in finding.get("meaningAssessmentIds") or []:
            try:
                assessment = self.repository.meaning_assessment(assessment_id)
            except FoundationValidationError:
                continue
            located = str(assessment.get("semanticLocationRelationshipId") or "")
            if located:
                ids.append(located)
        for account_id in finding.get("coverageAccountIds") or []:
            try:
                account = self.repository.coverage_account(account_id)
            except FoundationValidationError:
                continue
            ids.extend(str(item) for item in account.get("coveredByRelationshipIds") or [])
        return list(dict.fromkeys(ids))

    def _locations(self, finding: dict[str, Any]) -> list[dict[str, Any]]:
        """Stage 6B outcome plus the candidates it competed against.

        Alternatives are always returned when the engine retained them: the UI
        must not imply there was only one candidate for an AMBIGUOUS location.
        """
        locations: list[dict[str, Any]] = []
        for located_id in self._location_relationship_ids(finding):
            try:
                location = self.repository.semantic_location_relationship(located_id)
            except FoundationValidationError:
                continue
            alternatives: list[dict[str, Any]] = []
            try:
                alternatives = self.repository.semantic_location_candidates(
                    location.get("runId", ""), location.get("sourceOwnerUnitId", ""),
                )
            except FoundationValidationError:
                pass
            locations.append({"location": location, "alternatives": alternatives})
        return locations

    def _meanings(self, finding: dict[str, Any]) -> list[dict[str, Any]]:
        """Stage 7 status with its per-dimension components kept separate.

        A reviewer must be able to see "location: strong, quantity:
        contradicted" rather than one collapsed score.
        """
        meanings: list[dict[str, Any]] = []
        for assessment_id in finding.get("meaningAssessmentIds") or []:
            try:
                assessment = self.repository.meaning_assessment(assessment_id)
            except FoundationValidationError:
                continue
            meanings.append({
                "assessment": assessment,
                "components": self.repository.meaning_components(assessment_id),
            })
        return meanings

    def _coverage(self, finding: dict[str, Any]) -> list[dict[str, Any]]:
        accounts: list[dict[str, Any]] = []
        for account_id in finding.get("coverageAccountIds") or []:
            try:
                accounts.append(self.repository.coverage_account(account_id))
            except FoundationValidationError:
                continue
        return accounts

    # --- Decisions ----------------------------------------------------------

    def decide_finding(
        self, finding_id: str, disposition: str, *, expected_revision: int,
        expected_target_content_hashes: tuple[str, ...] = (), note: str = "",
        promote: bool = False,
    ) -> dict[str, Any]:
        """Record one human disposition against a QA finding.

        ``promote`` is the explicit opt-in that turns POSSIBLY_MISSING into
        MISSING (or POSSIBLY_UNSUPPORTED into UNSUPPORTED) on the finding's
        coverage accounts. It is never inferred from viewing or deciding
        alone, and only applies when the issue is confirmed.
        """
        try:
            value = QaDisposition(disposition)
        except ValueError as exc:
            raise FoundationValidationError(f"Unknown QA disposition: {disposition}") from exc
        if value not in _DECIDABLE:
            raise FoundationValidationError(
                f"{value.value} is not a reviewer decision; it is set by the system"
            )
        finding = self.repository.qa_finding(finding_id)
        self._check_target_hashes(finding, expected_target_content_hashes)

        self.repository.update_qa_disposition(
            finding_id, value, expected_revision, self.actor_id, note,
            review_status=_DISPOSITION_REVIEW_STATUS[value],
        )
        promoted: list[str] = []
        if promote and value == QaDisposition.CONFIRMED_TRANSLATION_ERROR:
            promoted = self._promote_coverage(finding, note)
        return {
            "finding": self.repository.qa_finding(finding_id),
            "promotedCoverageAccountIds": promoted,
            "history": self.repository.review_records("QA_FINDING", finding_id),
        }

    def _check_target_hashes(
        self, finding: dict[str, Any], expected: tuple[str, ...],
    ) -> None:
        """Reject a decision written against target text the reviewer never saw."""
        if not expected:
            return
        stored = tuple(finding.get("targetContentHashes") or ())
        if tuple(expected) != stored:
            raise FoundationConflict(
                "Target content changed since this finding was displayed"
            )

    def _promote_coverage(self, finding: dict[str, Any], note: str) -> list[str]:
        promoted: list[str] = []
        for account_id in finding.get("coverageAccountIds") or []:
            account = self.repository.coverage_account(account_id)
            target = _COVERAGE_PROMOTION.get(str(account.get("coverageStatus")))
            if target is None:
                continue
            self.repository.record_human_review(
                "COVERAGE_ACCOUNT", account_id, review_status=ReviewStatus.HUMAN_APPROVED,
                expected_revision=int(account["revision"]), actor_id=self.actor_id,
                note=note or "Promoted by explicit human confirmation.",
                payload_updates={"coverageStatus": target},
            )
            promoted.append(account_id)
        return promoted

    def add_note(self, entity_type: str, entity_id: str, note: str) -> dict[str, Any]:
        """Attach a reviewer note without changing any decision.

        Notes live in structured review history; they are never written into
        Scripture.
        """
        if not note.strip():
            raise FoundationValidationError("A reviewer note cannot be empty")
        self.repository.append_standalone_note(
            entity_type, entity_id, actor_id=self.actor_id, note=note)
        return {"history": self.repository.review_records(entity_type, entity_id)}

    def decide_location(
        self, relationship_id: str, decision: str, *, expected_revision: int,
        note: str = "", selected_candidate_id: str = "",
    ) -> dict[str, Any]:
        """Approve or reject a Stage 6B location.

        Rejecting a mapping is a different act from confirming a translation
        problem: it says Bridge looked in the wrong place. It marks the
        location HUMAN_MODIFIED/HUMAN_REJECTED and invalidates the Stage 7 and
        Stage 8 results derived from it, rather than rewriting their history.
        """
        if decision == "APPROVE":
            status = ReviewStatus.HUMAN_APPROVED
            updates: dict[str, Any] = {}
            invalidate = False
        elif decision == "REJECT":
            status = (
                ReviewStatus.HUMAN_MODIFIED if selected_candidate_id
                else ReviewStatus.HUMAN_REJECTED
            )
            updates = (
                {"selectedCandidateId": selected_candidate_id} if selected_candidate_id else {}
            )
            invalidate = True
        else:
            raise FoundationValidationError(f"Unknown mapping decision: {decision}")
        payload = self.repository.record_human_review(
            "LOCATION_RELATIONSHIP", relationship_id, review_status=status,
            expected_revision=expected_revision, actor_id=self.actor_id, note=note,
            payload_updates=updates, invalidate_dependents=invalidate,
        )
        return {
            "location": payload,
            "history": self.repository.review_records("LOCATION_RELATIONSHIP", relationship_id),
        }

    def decide_meaning(
        self, assessment_id: str, meaning_status: str, *, expected_revision: int,
        note: str = "",
    ) -> dict[str, Any]:
        """Override a Stage 7 meaning assessment.

        A reviewer who disagrees with the underlying meaning judgement is not
        forced to accept the QA conclusion built on it; the override
        invalidates the dependent Stage 8 findings so they can be recomputed.
        """
        try:
            status = MeaningStatus(meaning_status)
        except ValueError as exc:
            raise FoundationValidationError(
                f"Unknown meaning status: {meaning_status}") from exc
        payload = self.repository.record_human_review(
            "MEANING_ASSESSMENT", assessment_id, review_status=ReviewStatus.HUMAN_MODIFIED,
            expected_revision=expected_revision, actor_id=self.actor_id, note=note,
            payload_updates={"meaningStatus": status.value},
            invalidate_dependents=True,
        )
        return {
            "meaning": payload,
            "history": self.repository.review_records("MEANING_ASSESSMENT", assessment_id),
        }

    def get_entity_history(self, entity_type: str, entity_id: str) -> dict[str, Any]:
        return {
            "entityType": entity_type, "entityId": entity_id,
            "records": self.repository.review_records(entity_type, entity_id),
        }
