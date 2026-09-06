"""Stage 9B.3b strict, explicit-human correction application orchestration."""
from __future__ import annotations

from datetime import datetime, timezone
import threading
from typing import Any, Callable

from .correction_application_recovery import CorrectionApplicationRecoveryCoordinator
from .passage_semantic_models import (
    ActorType,
    CorrectionApplicationActor,
    CorrectionApplicationIntent,
    CorrectionApplicationState,
    LifecycleStatus,
    ReviewStatus,
    StrictScriptureEditContext,
)
from .passage_semantic_repository import FoundationConflict, FoundationValidationError


class CorrectionApplicationService:
    """Coordinates metadata and the existing canonical Scripture writer.

    It never writes chapter JSON itself. The injected writer must be
    ``BridgeEngine.edit_verse`` and ultimately
    ``TranslationCoreProject.apply_scripture_edit``.
    """

    def __init__(self, runtime: Any, writer: Callable[..., dict[str, Any]]):
        self.runtime = runtime
        self.repository = runtime.repository
        self.writer = writer
        self._lock = threading.RLock()

    @staticmethod
    def _parts(reference: str) -> tuple[str, str, str]:
        book, separator, location = reference.rpartition(" ")
        if not separator or ":" not in location:
            raise FoundationValidationError(f"Invalid correction target reference: {reference}")
        chapter, verse = location.split(":", 1)
        return book.upper(), chapter, verse

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def get_status(self, application_id: str) -> dict[str, Any]:
        application = self.repository.application_intent(application_id)
        if application["projectId"] != self.runtime.project_id:
            raise FoundationValidationError("Correction application belongs to another project")
        return application

    def apply(
        self, *, proposal_id: str, expected_proposal_revision: int,
        finding_id: str, expected_finding_revision: int,
        application_id: str, actor: dict[str, Any],
    ) -> dict[str, Any]:
        if str(actor.get("actorType") or "").upper() != ActorType.HUMAN.value:
            raise FoundationValidationError("Correction application requires explicit human action")
        actor_id = str(actor.get("actorId") or "").strip()
        if not actor_id:
            raise FoundationValidationError("Correction application requires a human actor id")
        if not application_id:
            raise FoundationValidationError("Correction application requires an idempotency identity")
        if bool(self.runtime.application_recovery.get("correctionWritesBlocked")):
            raise FoundationValidationError(
                "Correction writes are blocked until application recovery is resolved"
            )

        with self._lock:
            existing = self.repository.find_application_by_proposal_revision(
                proposal_id, expected_proposal_revision,
            )
            if existing is not None:
                if existing["findingId"] != finding_id:
                    raise FoundationConflict("Correction application finding identity conflict")
                if existing["applicationState"] in {
                    CorrectionApplicationState.APPLIED_SCRIPTURE.value,
                    CorrectionApplicationState.INVALIDATED.value,
                }:
                    return CorrectionApplicationRecoveryCoordinator(self.runtime).reconcile_one(existing)
                if existing["applicationState"] in {
                    CorrectionApplicationState.COMPLETED.value,
                    CorrectionApplicationState.FAILED.value,
                    CorrectionApplicationState.RECOVERY_REQUIRED.value,
                }:
                    return existing
                # PREPARED/APPLYING is resumed below from the durable snapshot.
                application = existing
            else:
                application = self._prepare(
                    proposal_id=proposal_id,
                    expected_proposal_revision=expected_proposal_revision,
                    finding_id=finding_id,
                    expected_finding_revision=expected_finding_revision,
                    application_id=application_id,
                    actor_id=actor_id,
                )
            return self._execute(application)

    def _validated_snapshot(
        self, proposal_id: str, expected_proposal_revision: int,
        finding_id: str, expected_finding_revision: int,
    ) -> tuple[dict[str, Any], dict[str, Any], str, str]:
        proposal = self.repository.correction_proposal(proposal_id)
        finding = self.repository.qa_finding(finding_id)
        if proposal.get("qaFindingId") != finding_id:
            raise FoundationValidationError("Correction proposal does not own the requested finding")
        if int(proposal.get("revision") or 0) != expected_proposal_revision:
            raise FoundationConflict("REVISION_CONFLICT: correction proposal revision changed")
        if int(finding.get("revision") or 0) != expected_finding_revision:
            raise FoundationConflict("REVISION_CONFLICT: QA finding revision changed")
        if int(proposal.get("proposalSchemaVersion") or 0) < 2 or not proposal.get("applicable"):
            raise FoundationValidationError("Legacy or incomplete correction proposals cannot be applied")
        if proposal.get("lifecycleStatus") != LifecycleStatus.ACTIVE.value:
            raise FoundationValidationError("Only an active current proposal may be applied")
        if proposal.get("reviewStatus") not in {
            ReviewStatus.HUMAN_MODIFIED.value, ReviewStatus.HUMAN_APPROVED.value,
        }:
            raise FoundationValidationError("Correction wording must be reviewed by a human before Apply")
        eligibility = self.runtime.correction_eligibility.evaluate(
            finding_id, ignore_proposal_ids=(proposal_id,),
        )
        if not eligibility.eligible:
            detail = "; ".join(reason.detail for reason in eligibility.reasons)
            raise FoundationValidationError(f"Correction is not eligible: {detail}")
        span = proposal["intent"]["affectedTargetSpan"]
        reference = str(span["displayedReference"])
        canonical = tuple(str(x) for x in span.get("canonicalReferences") or ())
        if not canonical:
            raise FoundationValidationError("Correction application requires a canonical target scope")
        validation = self.runtime.correction_eligibility.validate_current_text(
            displayed_reference=reference,
            expected_target_revision=str(span["targetTextRevision"]),
            expected_target_content_hash=str(span["targetContentHash"]),
            expected_span_text=str(span.get("originalText") or ""),
            start_code_point=int(span["startCodePoint"]),
            end_code_point=int(span["endCodePoint"]),
        )
        if not validation.valid:
            raise FoundationConflict("REVISION_CONFLICT: " + "; ".join(r.detail for r in validation.reasons))
        current = self.runtime.correction_eligibility.current_text_snapshot()[reference]
        return proposal, finding, reference, current

    def _prepare(self, **request: Any) -> dict[str, Any]:
        proposal, finding, reference, current = self._validated_snapshot(
            request["proposal_id"], request["expected_proposal_revision"],
            request["finding_id"], request["expected_finding_revision"],
        )
        span = proposal["intent"]["affectedTargetSpan"]
        start, end = int(span["startCodePoint"]), int(span["endCodePoint"])
        replacement = str(proposal.get("proposedText") or "")
        final = current[:start] + replacement + current[end:]
        final_hash = self.runtime.text_hash(final)
        source_refs = self._source_provenance_references(proposal, finding)
        now = self._now()
        intent = CorrectionApplicationIntent(
            application_id=request["application_id"], proposal_id=request["proposal_id"],
            finding_id=request["finding_id"], project_id=self.runtime.project_id,
            expected_proposal_revision=request["expected_proposal_revision"],
            expected_finding_revision=request["expected_finding_revision"],
            target_displayed_reference=reference,
            canonical_references=tuple(str(x) for x in span["canonicalReferences"]),
            source_provenance_references=source_refs,
            expected_target_revision=str(span["targetTextRevision"]),
            expected_target_content_hash=str(span["targetContentHash"]),
            expected_start_code_point=start, expected_end_code_point=end,
            expected_original_text=str(span.get("originalText") or ""),
            replacement_text_snapshot=replacement,
            intended_final_verse_hash=final_hash,
            pending_invalidation_id=f"correction-invalidation-{request['application_id']}",
            translation_core_journal_transaction_id="",
            actor=CorrectionApplicationActor(actor_type=ActorType.HUMAN, actor_id=request["actor_id"]),
            created_at=now, updated_at=now,
            application_state=CorrectionApplicationState.PREPARED, state_revision=1,
        )
        application = self.repository.prepare_application_intent(
            intent, previous_text_hash=str(span["targetContentHash"]),
        )
        return self.repository.record_application_backup(
            application["applicationId"],
            backup_root=self.repository.path.parent / "correction-application-backups",
            expected_state_revision=int(application["stateRevision"]),
        )

    def _source_provenance_references(
        self, proposal: dict[str, Any], finding: dict[str, Any],
    ) -> tuple[str, ...]:
        """Resolve source provenance independently from the editable target.

        Proposal v2 historically overloaded ``affectedReferences`` with target
        coordinates.  Source semantic-unit identities are the durable authority
        and preserve cross-verse provenance for both new and already persisted
        proposals.  The affected-reference fallback is retained only for legacy
        records that predate semantic-unit linkage.
        """
        intent = proposal.get("intent") or {}
        source_unit_ids = tuple(
            str(item) for item in intent.get("affectedSourceSemanticUnitIds") or ()
            if str(item).strip()
        ) or tuple(
            str(item) for item in finding.get("sourceSemanticUnitIds") or ()
            if str(item).strip()
        )
        references: list[str] = []
        for unit_id in source_unit_ids:
            unit = self.repository.semantic_unit(unit_id)
            if unit.get("projectId") != self.runtime.project_id:
                raise FoundationValidationError(
                    f"Source semantic unit belongs to another project: {unit_id}"
                )
            if unit.get("side") != "SOURCE":
                raise FoundationValidationError(
                    f"Correction provenance unit is not SOURCE: {unit_id}"
                )
            values = unit.get("canonicalReferences") or unit.get("displayedReferences") or ()
            references.extend(str(item) for item in values if str(item).strip())
        if references:
            return tuple(dict.fromkeys(references))

        span = intent.get("affectedTargetSpan") or {}
        target_references = {
            str(span.get("displayedReference") or ""),
            *(str(item) for item in span.get("canonicalReferences") or ()),
        }
        return tuple(dict.fromkeys(
            str(item) for item in proposal.get("affectedReferences") or ()
            if str(item).strip() and str(item) not in target_references
        ))

    def _execute(self, application: dict[str, Any]) -> dict[str, Any]:
        if application["applicationState"] == CorrectionApplicationState.APPLYING.value:
            # A durable APPLYING state is resolved from hashes, never blindly re-written.
            return CorrectionApplicationRecoveryCoordinator(self.runtime).reconcile_one(application)
        if application["applicationState"] != CorrectionApplicationState.PREPARED.value:
            return application
        proposal, _finding, reference, current = self._validated_snapshot(
            application["proposalId"], int(application["expectedProposalRevision"]),
            application["findingId"], int(application["expectedFindingRevision"]),
        )
        span = proposal["intent"]["affectedTargetSpan"]
        start, end = int(span["startCodePoint"]), int(span["endCodePoint"])
        final = current[:start] + application["replacementTextSnapshot"] + current[end:]
        if self.runtime.text_hash(final) != application["intendedFinalVerseHash"]:
            raise FoundationConflict("REVISION_CONFLICT: intended correction text changed")
        strict = StrictScriptureEditContext(
            expected_target_revision=application["expectedTargetRevision"],
            expected_target_content_hash=application["expectedTargetContentHash"],
            expected_original_verse_text=current,
            expected_start_code_point=start, expected_end_code_point=end,
            expected_original_span_text=application["expectedOriginalText"],
            intended_final_verse_text=final,
            pending_invalidation_id=application["pendingInvalidationId"],
            application_id=application["applicationId"],
        )

        def journal_ready(transaction_id: str) -> None:
            nonlocal application
            application = self.repository.transition_application_state(
                application["applicationId"], expected_state=application["applicationState"],
                expected_state_revision=int(application["stateRevision"]),
                new_state=CorrectionApplicationState.APPLYING,
                translation_core_journal_transaction_id=transaction_id,
            )

        _book, chapter, verse = self._parts(reference)
        try:
            result = self.writer(
                chapter, verse, final, strict_context=strict,
                journal_prepared_callback=journal_ready,
                journal_metadata={
                    "applicationId": application["applicationId"],
                    "proposalId": application["proposalId"],
                    "proposalRevision": application["expectedProposalRevision"],
                    "intendedFinalVerseHash": application["intendedFinalVerseHash"],
                },
            )
        except Exception as exc:
            if "REVISION_CONFLICT" in str(exc):
                raise FoundationConflict(str(exc)) from exc
            raise
        actual = str(self.runtime.project.target_verse_text(chapter, verse))
        actual_hash = self.runtime.text_hash(actual)
        if actual_hash != application["intendedFinalVerseHash"]:
            return self.repository.record_recovery_required(
                application["applicationId"],
                expected_state_revision=int(application["stateRevision"]),
                failure_code="POST_WRITE_HASH_MISMATCH",
                recovery_metadata={"actualTargetContentHash": actual_hash},
            )
        application = self.repository.transition_application_state(
            application["applicationId"], expected_state=application["applicationState"],
            expected_state_revision=int(application["stateRevision"]),
            new_state=CorrectionApplicationState.APPLIED_SCRIPTURE,
            result_metadata={"canonicalEdit": result},
        )
        self.repository.apply_target_invalidation(
            application["pendingInvalidationId"], actual_text_hash=actual_hash,
            text_revision=self.runtime.text_revision(reference, actual_hash),
        )
        application = self.repository.transition_application_state(
            application["applicationId"], expected_state=application["applicationState"],
            expected_state_revision=int(application["stateRevision"]),
            new_state=CorrectionApplicationState.INVALIDATED,
        )
        return CorrectionApplicationRecoveryCoordinator(self.runtime).reconcile_one(application)
