"""Stage 9B.3a correction-attempt recovery; deliberately contains no writer."""
from __future__ import annotations

from typing import Any

from .passage_semantic_models import CorrectionApplicationState


class CorrectionApplicationRecoveryCoordinator:
    """Reconcile persisted attempts from exact hashes after tC journal recovery.

    This component never writes chapter JSON and never invokes
    ``apply_scripture_edit``. It can only move the application ledger forward,
    finish a previously prepared semantic invalidation, or fail closed.
    """

    def __init__(self, runtime: Any):
        self.runtime = runtime
        self.repository = runtime.repository
        self.project = runtime.project

    @staticmethod
    def _reference_parts(reference: str) -> tuple[str, str]:
        _, separator, location = reference.rpartition(" ")
        if not separator or ":" not in location:
            raise ValueError(f"Invalid target displayed reference: {reference}")
        chapter, verse = location.split(":", 1)
        return chapter, verse

    def _current_hash(self, application: dict[str, Any]) -> str:
        chapter, verse = self._reference_parts(application["targetDisplayedReference"])
        text = str(self.project.target_verse_text(chapter, verse))
        return self.runtime.text_hash(text)

    def _transition(
        self, application: dict[str, Any], target: CorrectionApplicationState,
        *, failure_code: str = "", recovery_metadata: dict[str, Any] | None = None,
        result_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.repository.transition_application_state(
            application["applicationId"],
            expected_state=application["applicationState"],
            expected_state_revision=int(application["stateRevision"]),
            new_state=target, failure_code=failure_code,
            recovery_metadata=recovery_metadata,
            result_metadata=result_metadata,
        )

    def _recovery_required(
        self, application: dict[str, Any], code: str, metadata: dict[str, Any],
    ) -> dict[str, Any]:
        if application["applicationState"] == CorrectionApplicationState.RECOVERY_REQUIRED.value:
            return application
        return self.repository.record_recovery_required(
            application["applicationId"],
            expected_state_revision=int(application["stateRevision"]),
            failure_code=code, recovery_metadata=metadata,
        )

    def _finalize_applied_metadata(
        self, application: dict[str, Any], evidence: dict[str, Any],
    ) -> dict[str, Any]:
        """Finish domain bookkeeping for an edit that is already durable.

        Proposal metadata and the application ledger are separate durable
        records. A crash may therefore happen after either update. Re-entry is
        deliberately idempotent: an already-stamped proposal is never stamped
        twice, and a proposal changed for any reason other than the target
        invalidation fails closed for review.
        """
        proposal = self.repository.correction_proposal(application["proposalId"])
        current_target = self.repository.current_target_revision(
            application["projectId"], self.runtime.book,
            application["targetDisplayedReference"],
        )
        if current_target is None:
            return self._recovery_required(
                application, "TARGET_REVISION_NOT_RECORDED", evidence,
            )
        applied_revision = str(proposal.get("appliedTargetRevision") or "")
        if applied_revision:
            if applied_revision != current_target["textRevision"]:
                return self._recovery_required(
                    application, "PROPOSAL_FINALIZATION_CONFLICT", {
                        **evidence,
                        "proposalAppliedTargetRevision": applied_revision,
                        "currentTargetRevision": current_target["textRevision"],
                    },
                )
        else:
            expected_revision = int(application["expectedProposalRevision"])
            current_revision = int(proposal["revision"])
            allowed_invalidation_revision = (
                current_revision == expected_revision + 1
                and proposal.get("lifecycleStatus") == "STALE"
            )
            if current_revision != expected_revision and not allowed_invalidation_revision:
                return self._recovery_required(
                    application, "PROPOSAL_FINALIZATION_CONFLICT", {
                        **evidence,
                        "expectedProposalRevision": expected_revision,
                        "currentProposalRevision": current_revision,
                        "currentProposalLifecycle": proposal.get("lifecycleStatus"),
                    },
                )
            actor = application.get("actor") or {}
            if actor.get("actorType") != "HUMAN":
                return self._recovery_required(
                    application, "APPLICATION_ACTOR_NOT_HUMAN", evidence,
                )
            self.repository.record_correction_application_metadata(
                application["proposalId"], actor_type="HUMAN",
                actor_id=str(actor.get("actorId") or "human"),
                applied_target_revision=current_target["textRevision"],
                expected_revision=current_revision,
            )

        return self._transition(
            application, CorrectionApplicationState.COMPLETED,
            recovery_metadata=evidence,
            result_metadata={
                "recovered": True,
                "scriptureAlreadyMatchedIntendedFinalHash": True,
                "verificationStatus": "PENDING",
                "affectedAnalysisStarted": False,
            },
        )

    def reconcile_one(self, application: dict[str, Any]) -> dict[str, Any]:
        state = CorrectionApplicationState(application["applicationState"])
        if state in {CorrectionApplicationState.COMPLETED, CorrectionApplicationState.FAILED}:
            return application
        if state == CorrectionApplicationState.RECOVERY_REQUIRED:
            return application

        actual_hash = self._current_hash(application)
        before_hash = application["expectedTargetContentHash"]
        after_hash = application["intendedFinalVerseHash"]
        journal_id = application.get("translationCoreJournalTransactionId") or ""
        journal = self.project.journal.get(journal_id)
        journal_status = str((journal or {}).get("status") or "NOT_RECORDED")
        evidence = {
            "actualTargetContentHash": actual_hash,
            "expectedBeforeHash": before_hash,
            "intendedAfterHash": after_hash,
            "translationCoreJournalStatus": journal_status,
        }
        if journal_status == "recovery_required":
            return self._recovery_required(
                application, "TRANSLATIONCORE_ROLLBACK_INCOMPLETE", evidence,
            )
        if actual_hash not in {before_hash, after_hash}:
            return self._recovery_required(
                application, "TARGET_HASH_AMBIGUOUS", evidence,
            )
        if actual_hash == before_hash:
            if state in {CorrectionApplicationState.PREPARED, CorrectionApplicationState.APPLYING}:
                if journal_status == "committed":
                    return self._recovery_required(
                        application, "JOURNAL_HASH_CONTRADICTION", evidence,
                    )
                return self._transition(
                    application, CorrectionApplicationState.FAILED,
                    failure_code="NO_COMMITTED_SCRIPTURE_EDIT",
                    recovery_metadata=evidence,
                )
            return self._recovery_required(
                application, "RECORDED_APPLY_WITH_BEFORE_HASH", evidence,
            )

        if journal_status in {"rolled_back", "recovered_rollback"}:
            return self._recovery_required(
                application, "JOURNAL_HASH_CONTRADICTION", evidence,
            )

        # The intended final text already exists. Catch the durable state up;
        # never invoke a writer and therefore never risk a duplicate insertion.
        if state == CorrectionApplicationState.PREPARED:
            application = self._transition(
                application, CorrectionApplicationState.APPLYING,
                recovery_metadata=evidence,
            )
            state = CorrectionApplicationState.APPLYING
        if state == CorrectionApplicationState.APPLYING:
            application = self._transition(
                application, CorrectionApplicationState.APPLIED_SCRIPTURE,
                recovery_metadata=evidence,
            )
            state = CorrectionApplicationState.APPLIED_SCRIPTURE

        invalidation = self.repository.target_invalidation(
            application["pendingInvalidationId"]
        )
        if state == CorrectionApplicationState.APPLIED_SCRIPTURE:
            if invalidation is None or invalidation["state"] not in {"PREPARED", "APPLIED"}:
                return self._recovery_required(
                    application, "SEMANTIC_INVALIDATION_NOT_RECOVERABLE", {
                        **evidence,
                        "pendingInvalidationState": None if invalidation is None else invalidation["state"],
                    },
                )
            if invalidation["state"] == "PREPARED":
                reference = application["targetDisplayedReference"]
                self.repository.apply_target_invalidation(
                    application["pendingInvalidationId"],
                    actual_text_hash=actual_hash,
                    text_revision=self.runtime.text_revision(reference, actual_hash),
                )
            application = self._transition(
                application, CorrectionApplicationState.INVALIDATED,
                recovery_metadata={**evidence, "pendingInvalidationState": "APPLIED"},
            )
            state = CorrectionApplicationState.INVALIDATED

        if state == CorrectionApplicationState.INVALIDATED:
            application = self._finalize_applied_metadata(application, evidence)
        return application

    def reconcile_incomplete(self) -> dict[str, Any]:
        results: list[dict[str, Any]] = []
        for application in self.repository.list_incomplete_applications(
            self.runtime.project_id
        ):
            results.append(self.reconcile_one(application))
        blocked = any(
            item["applicationState"] == CorrectionApplicationState.RECOVERY_REQUIRED.value
            for item in results
        )
        return {
            "checked": len(results), "results": results,
            "correctionWritesBlocked": blocked,
        }
