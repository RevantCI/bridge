"""Stage 9B.0 backend-owned correction eligibility.

One authoritative answer to "may a correction be proposed for this finding?".

The frontend must never infer this. Eligibility depends on the QA disposition,
the review status, the lifecycle, the *current* Scripture on disk, the location
evidence quality, whether a human rejected the mapping or overrode the meaning,
and whether another correction already owns this finding. A UI that reproduced
even part of that would drift, and the failure mode of drift here is a
correction offered against text the reviewer never confirmed.

This module reads. It never edits Scripture, never generates wording, and never
changes a disposition -- all of that is 9B.1 and later.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .passage_semantic_models import (
    LifecycleStatus,
    LocationOutcome,
    MeaningStatus,
    QaDisposition,
    ReviewStatus,
)
from .passage_semantic_repository import FoundationValidationError


ELIGIBILITY_ENGINE_VERSION = "bridge-correction-eligibility-v1"


class CorrectionEligibilityCode(StrEnum):
    """Why a correction may or may not be proposed.

    Returned as structured reasons rather than a bare boolean so the UI can say
    *what* to fix -- "confirm this finding first" is actionable, "not eligible"
    is not -- and so tests assert on the actual rule that fired.
    """

    ELIGIBLE = "ELIGIBLE"
    FINDING_NOT_FOUND = "FINDING_NOT_FOUND"
    DISPOSITION_NOT_CONFIRMED = "DISPOSITION_NOT_CONFIRMED"
    REVIEW_STATUS_NOT_HUMAN_APPROVED = "REVIEW_STATUS_NOT_HUMAN_APPROVED"
    LIFECYCLE_NOT_ACTIVE = "LIFECYCLE_NOT_ACTIVE"
    FINDING_STALE = "FINDING_STALE"
    TARGET_TEXT_CHANGED = "TARGET_TEXT_CHANGED"
    TARGET_REFERENCE_MISSING = "TARGET_REFERENCE_MISSING"
    SPAN_TEXT_MISMATCH = "SPAN_TEXT_MISMATCH"
    LOCATION_EVIDENCE_UNUSABLE = "LOCATION_EVIDENCE_UNUSABLE"
    MAPPING_HUMAN_REJECTED = "MAPPING_HUMAN_REJECTED"
    MEANING_OVERRIDDEN_PRESERVED = "MEANING_OVERRIDDEN_PRESERVED"
    CONFLICTING_CORRECTION = "CONFLICTING_CORRECTION"
    RESOURCE_CONFLICT_REQUIRES_REVIEW = "RESOURCE_CONFLICT_REQUIRES_REVIEW"


# Location outcomes that cannot ground a correction.
#
# NOT_LOCATED is deliberately absent: a confirmed genuine omission *is* a
# NOT_LOCATED source unit, and it is precisely the case a correction should be
# able to fix by inserting text. The three below are different -- each means the
# search did not reach a conclusion, so there is no defensible span to correct.
_UNUSABLE_LOCATION_OUTCOMES = {
    LocationOutcome.AMBIGUOUS,
    LocationOutcome.SEARCH_INCOMPLETE,
    LocationOutcome.UNSUPPORTED_ANALYSIS,
}

# A correction already owns a finding when it is live or has been written.
_CONFLICTING_LIFECYCLES = {LifecycleStatus.ACTIVE, LifecycleStatus.INACTIVE}


@dataclass(frozen=True)
class EligibilityReason:
    code: CorrectionEligibilityCode
    detail: str
    entity_type: str = ""
    entity_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code.value, "detail": self.detail,
            "entityType": self.entity_type, "entityId": self.entity_id,
        }


@dataclass(frozen=True)
class CurrentTextValidation:
    """Whether a finding still describes the Scripture that is on disk now.

    Stage 9A compared a submitted hash against the finding's own snapshot, which
    only proves the reviewer saw what the finding recorded. It cannot detect that
    the verse was edited afterwards. Eligibility additionally re-reads the
    authoritative chapter JSON, so a correction can never be grounded on text
    that no longer exists.
    """

    valid: bool
    reasons: tuple[EligibilityReason, ...] = ()
    current_target_revision: str = ""
    current_target_content_hash: str = ""
    observed_span_text: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "reasons": [reason.to_dict() for reason in self.reasons],
            "currentTargetRevision": self.current_target_revision,
            "currentTargetContentHash": self.current_target_content_hash,
            "observedSpanText": self.observed_span_text,
        }


@dataclass(frozen=True)
class CorrectionEligibility:
    finding_id: str
    eligible: bool
    reasons: tuple[EligibilityReason, ...] = ()
    finding_revision: int = 0
    current_target_content_hash: str = ""
    displayed_references: tuple[str, ...] = ()
    engine_version: str = ELIGIBILITY_ENGINE_VERSION
    existing_proposal_ids: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "findingId": self.finding_id,
            "eligible": self.eligible,
            "reasons": [reason.to_dict() for reason in self.reasons],
            "findingRevision": self.finding_revision,
            "currentTargetContentHash": self.current_target_content_hash,
            "displayedReferences": list(self.displayed_references),
            "engineVersion": self.engine_version,
            "existingProposalIds": list(self.existing_proposal_ids),
        }


class CorrectionEligibilityService:
    """The single authority on correction eligibility."""

    def __init__(self, runtime: Any):
        self.runtime = runtime
        self.repository = runtime.repository
        self.project_id = runtime.project_id
        self.book = runtime.book
        self.project = runtime.project

    # --- Current-text validation -------------------------------------------

    def current_text_snapshot(self) -> dict[str, str]:
        """Authoritative current Scripture, keyed by displayed reference."""
        # Imported here, not at module scope: the runtime constructs this
        # service, so a top-level import would be a cycle.
        from .passage_semantic_runtime import current_target_text

        return current_target_text(self.project)

    def validate_current_text(
        self,
        *,
        displayed_reference: str,
        expected_target_revision: str = "",
        expected_target_content_hash: str = "",
        expected_span_text: str | None = None,
        start_code_point: int | None = None,
        end_code_point: int | None = None,
        current_text: dict[str, str] | None = None,
    ) -> CurrentTextValidation:
        """Compare expectations against the chapter JSON as it stands now.

        Exact comparison only. There is deliberately no fuzzy or normalized
        matching anywhere in this path: if the text moved, the honest answer is
        that the correction must be re-grounded, not that Bridge found something
        close enough to edit.
        """
        texts = self.current_text_snapshot() if current_text is None else current_text
        reasons: list[EligibilityReason] = []
        if displayed_reference not in texts:
            return CurrentTextValidation(
                valid=False,
                reasons=(EligibilityReason(
                    CorrectionEligibilityCode.TARGET_REFERENCE_MISSING,
                    f"{displayed_reference} is not present in current Scripture.",
                    "TARGET_REFERENCE", displayed_reference,
                ),),
            )
        verse_text = texts[displayed_reference]
        actual_hash = self.runtime.text_hash(verse_text)
        actual_revision = self.runtime.text_revision(displayed_reference, actual_hash)

        if expected_target_content_hash and expected_target_content_hash != actual_hash:
            reasons.append(EligibilityReason(
                CorrectionEligibilityCode.TARGET_TEXT_CHANGED,
                f"{displayed_reference} has been edited since this was recorded.",
                "TARGET_REFERENCE", displayed_reference,
            ))
        if expected_target_revision and expected_target_revision != actual_revision:
            reasons.append(EligibilityReason(
                CorrectionEligibilityCode.TARGET_TEXT_CHANGED,
                f"{displayed_reference} is at a different target revision.",
                "TARGET_REFERENCE", displayed_reference,
            ))

        observed: str | None = None
        if start_code_point is not None and end_code_point is not None:
            if not 0 <= start_code_point <= end_code_point <= len(verse_text):
                reasons.append(EligibilityReason(
                    CorrectionEligibilityCode.SPAN_TEXT_MISMATCH,
                    f"Span [{start_code_point}, {end_code_point}) lies outside "
                    f"{displayed_reference} ({len(verse_text)} code points).",
                    "TARGET_REFERENCE", displayed_reference,
                ))
            else:
                # Python string indices are code points, so this slice is the
                # code-point span the contract specifies -- not UTF-16 units.
                observed = verse_text[start_code_point:end_code_point]
                if expected_span_text is not None and observed != expected_span_text:
                    reasons.append(EligibilityReason(
                        CorrectionEligibilityCode.SPAN_TEXT_MISMATCH,
                        f"Span text in {displayed_reference} is {observed!r}, "
                        f"expected {expected_span_text!r}.",
                        "TARGET_REFERENCE", displayed_reference,
                    ))
        return CurrentTextValidation(
            valid=not reasons, reasons=tuple(reasons),
            current_target_revision=actual_revision,
            current_target_content_hash=actual_hash,
            observed_span_text=observed,
        )

    # --- Eligibility --------------------------------------------------------

    def evaluate(self, finding_id: str) -> CorrectionEligibility:
        """Every rule is evaluated; reasons accumulate rather than short-circuit.

        A reviewer fixing one blocker only to meet the next is a bad loop, so
        the answer names everything standing in the way at once.
        """
        try:
            finding = self.repository.qa_finding(finding_id)
        except FoundationValidationError as exc:
            return CorrectionEligibility(
                finding_id=finding_id, eligible=False,
                reasons=(EligibilityReason(
                    CorrectionEligibilityCode.FINDING_NOT_FOUND, str(exc),
                    "QA_FINDING", finding_id,
                ),),
            )

        reasons: list[EligibilityReason] = []
        reasons.extend(self._check_disposition(finding))
        reasons.extend(self._check_lifecycle(finding))
        reasons.extend(self._check_location_evidence(finding))
        reasons.extend(self._check_meaning_override(finding))
        reasons.extend(self._check_resource_conflicts(finding))

        displayed = tuple(str(x) for x in finding.get("displayedReferences") or ())
        current_hash, text_reasons = self._check_current_text(finding, displayed)
        reasons.extend(text_reasons)

        existing, conflict_reasons = self._check_existing_corrections(finding_id)
        reasons.extend(conflict_reasons)

        return CorrectionEligibility(
            finding_id=finding_id,
            eligible=not reasons,
            reasons=tuple(reasons) or (EligibilityReason(
                CorrectionEligibilityCode.ELIGIBLE,
                "Confirmed, human-approved, active finding grounded in current Scripture.",
                "QA_FINDING", finding_id,
            ),),
            finding_revision=int(finding.get("revision") or 0),
            current_target_content_hash=current_hash,
            displayed_references=displayed,
            existing_proposal_ids=existing,
        )

    def _check_disposition(self, finding: dict[str, Any]) -> list[EligibilityReason]:
        reasons: list[EligibilityReason] = []
        disposition = str(finding.get("qaDisposition") or "")
        finding_id = str(finding.get("id") or "")
        if disposition != QaDisposition.CONFIRMED_TRANSLATION_ERROR.value:
            # UNRESOLVED, ACCEPTABLE_TRANSLATION, FALSE_POSITIVE, NEEDS_DISCUSSION
            # and CORRECTED all land here. Only a human confirming an actual
            # translation error authorizes changing Scripture.
            reasons.append(EligibilityReason(
                CorrectionEligibilityCode.DISPOSITION_NOT_CONFIRMED,
                f"Disposition is {disposition or 'unset'}; a correction requires "
                f"{QaDisposition.CONFIRMED_TRANSLATION_ERROR.value}.",
                "QA_FINDING", finding_id,
            ))
        review_status = str(finding.get("reviewStatus") or "")
        if review_status != ReviewStatus.HUMAN_APPROVED.value:
            reasons.append(EligibilityReason(
                CorrectionEligibilityCode.REVIEW_STATUS_NOT_HUMAN_APPROVED,
                f"Review status is {review_status or 'unset'}; a correction requires "
                f"{ReviewStatus.HUMAN_APPROVED.value}.",
                "QA_FINDING", finding_id,
            ))
        return reasons

    def _check_lifecycle(self, finding: dict[str, Any]) -> list[EligibilityReason]:
        lifecycle = str(finding.get("lifecycleStatus") or "")
        finding_id = str(finding.get("id") or "")
        if lifecycle == LifecycleStatus.STALE.value:
            return [EligibilityReason(
                CorrectionEligibilityCode.FINDING_STALE,
                "The finding is stale: its inputs changed after it was produced. "
                "Re-run the analysis before correcting.",
                "QA_FINDING", finding_id,
            )]
        if lifecycle != LifecycleStatus.ACTIVE.value:
            return [EligibilityReason(
                CorrectionEligibilityCode.LIFECYCLE_NOT_ACTIVE,
                f"Lifecycle is {lifecycle or 'unset'}; a correction requires "
                f"{LifecycleStatus.ACTIVE.value}.",
                "QA_FINDING", finding_id,
            )]
        return []

    def _location_relationships(self, finding: dict[str, Any]) -> list[dict[str, Any]]:
        ids: list[str] = []
        for assessment_id in finding.get("meaningAssessmentIds") or []:
            try:
                assessment = self.repository.meaning_assessment(str(assessment_id))
            except FoundationValidationError:
                continue
            located = str(assessment.get("semanticLocationRelationshipId") or "")
            if located:
                ids.append(located)
        for account_id in finding.get("coverageAccountIds") or []:
            try:
                account = self.repository.coverage_account(str(account_id))
            except FoundationValidationError:
                continue
            ids.extend(str(item) for item in account.get("coveredByRelationshipIds") or [])
        out: list[dict[str, Any]] = []
        for relationship_id in dict.fromkeys(ids):
            try:
                out.append(self.repository.semantic_location_relationship(relationship_id))
            except FoundationValidationError:
                continue
        return out

    def _check_location_evidence(self, finding: dict[str, Any]) -> list[EligibilityReason]:
        reasons: list[EligibilityReason] = []
        for relationship in self._location_relationships(finding):
            relationship_id = str(relationship.get("id") or "")
            outcome = str(relationship.get("locationOutcome") or "")
            if outcome in {item.value for item in _UNUSABLE_LOCATION_OUTCOMES}:
                reasons.append(EligibilityReason(
                    CorrectionEligibilityCode.LOCATION_EVIDENCE_UNUSABLE,
                    f"Location outcome {outcome} does not identify a correctable span.",
                    "LOCATION_RELATIONSHIP", relationship_id,
                ))
            if str(relationship.get("reviewStatus") or "") == ReviewStatus.HUMAN_REJECTED.value:
                # A human said this mapping is wrong. Correcting the span it
                # points at would edit text on evidence already withdrawn.
                reasons.append(EligibilityReason(
                    CorrectionEligibilityCode.MAPPING_HUMAN_REJECTED,
                    "A reviewer rejected this location mapping.",
                    "LOCATION_RELATIONSHIP", relationship_id,
                ))
            if str(relationship.get("lifecycleStatus") or "") == LifecycleStatus.STALE.value:
                reasons.append(EligibilityReason(
                    CorrectionEligibilityCode.FINDING_STALE,
                    "The location evidence behind this finding is stale.",
                    "LOCATION_RELATIONSHIP", relationship_id,
                ))
        return reasons

    def _check_meaning_override(self, finding: dict[str, Any]) -> list[EligibilityReason]:
        reasons: list[EligibilityReason] = []
        for assessment_id in finding.get("meaningAssessmentIds") or []:
            try:
                assessment = self.repository.meaning_assessment(str(assessment_id))
            except FoundationValidationError:
                continue
            status = str(assessment.get("meaningStatus") or "")
            review_status = str(assessment.get("reviewStatus") or "")
            human_decided = review_status in {
                ReviewStatus.HUMAN_APPROVED.value, ReviewStatus.HUMAN_MODIFIED.value,
            }
            if human_decided and status == MeaningStatus.PRESERVED.value:
                # The reviewer has already said the meaning survives. Whatever
                # the machine flagged, there is no meaning failure left to fix.
                reasons.append(EligibilityReason(
                    CorrectionEligibilityCode.MEANING_OVERRIDDEN_PRESERVED,
                    "A reviewer judged this meaning PRESERVED; there is nothing to correct.",
                    "MEANING_ASSESSMENT", str(assessment_id),
                ))
            if str(assessment.get("lifecycleStatus") or "") == LifecycleStatus.STALE.value:
                reasons.append(EligibilityReason(
                    CorrectionEligibilityCode.FINDING_STALE,
                    "The meaning assessment behind this finding is stale.",
                    "MEANING_ASSESSMENT", str(assessment_id),
                ))
        return reasons

    def _check_resource_conflicts(self, finding: dict[str, Any]) -> list[EligibilityReason]:
        """Block while a source-variant / resource conflict is unresolved.

        A CONFLICTING resource means the sources disagree about what the target
        should say. Correcting toward one of them is a translation decision a
        human has to make first, not something eligibility may assume.
        """
        reasons: list[EligibilityReason] = []
        for evidence_id in finding.get("conflictingEvidenceIds") or []:
            reasons.append(EligibilityReason(
                CorrectionEligibilityCode.RESOURCE_CONFLICT_REQUIRES_REVIEW,
                "Conflicting evidence on this finding must be resolved before correcting.",
                "EVIDENCE_RECORD", str(evidence_id),
            ))
        for evidence_id in finding.get("resourceEvidenceIds") or []:
            try:
                evidence = self.repository.evidence_record(str(evidence_id))
            except (FoundationValidationError, AttributeError):
                continue
            if str(evidence.get("resourceValidationStatus") or "") == "CONFLICTING":
                reasons.append(EligibilityReason(
                    CorrectionEligibilityCode.RESOURCE_CONFLICT_REQUIRES_REVIEW,
                    "A resource validation conflict on this finding is unresolved.",
                    "EVIDENCE_RECORD", str(evidence_id),
                ))
        return reasons

    def _check_current_text(
        self, finding: dict[str, Any], displayed: tuple[str, ...],
    ) -> tuple[str, list[EligibilityReason]]:
        """Re-read Scripture and confirm the finding still describes it."""
        reasons: list[EligibilityReason] = []
        try:
            texts = self.current_text_snapshot()
        except FoundationValidationError as exc:
            return "", [EligibilityReason(
                CorrectionEligibilityCode.TARGET_TEXT_CHANGED,
                f"Current Scripture could not be read: {exc}",
                "QA_FINDING", str(finding.get("id") or ""),
            )]
        stored_hashes = [str(x) for x in finding.get("targetContentHashes") or ()]
        current_hashes: list[str] = []
        for index, reference in enumerate(displayed):
            if reference not in texts:
                reasons.append(EligibilityReason(
                    CorrectionEligibilityCode.TARGET_REFERENCE_MISSING,
                    f"{reference} is no longer present in current Scripture.",
                    "TARGET_REFERENCE", reference,
                ))
                continue
            actual = self.runtime.text_hash(texts[reference])
            current_hashes.append(actual)
            if index < len(stored_hashes) and stored_hashes[index] != actual:
                reasons.append(EligibilityReason(
                    CorrectionEligibilityCode.TARGET_TEXT_CHANGED,
                    f"{reference} has been edited since this finding was produced.",
                    "TARGET_REFERENCE", reference,
                ))
        return (current_hashes[0] if current_hashes else ""), reasons

    def _check_existing_corrections(
        self, finding_id: str,
    ) -> tuple[tuple[str, ...], list[EligibilityReason]]:
        try:
            proposals = self.repository.correction_proposals_for_finding(finding_id)
        except (FoundationValidationError, AttributeError):
            return (), []
        reasons: list[EligibilityReason] = []
        ids: list[str] = []
        for proposal in proposals:
            proposal_id = str(proposal.get("id") or "")
            ids.append(proposal_id)
            lifecycle = str(proposal.get("lifecycleStatus") or "")
            applied = bool(proposal.get("appliedTargetRevision"))
            if applied or lifecycle in {item.value for item in _CONFLICTING_LIFECYCLES}:
                reasons.append(EligibilityReason(
                    CorrectionEligibilityCode.CONFLICTING_CORRECTION,
                    "Another correction proposal already owns this finding "
                    f"(lifecycle {lifecycle or 'unset'}"
                    f"{', already applied' if applied else ''}).",
                    "CORRECTION_PROPOSAL", proposal_id,
                ))
        return tuple(ids), reasons
