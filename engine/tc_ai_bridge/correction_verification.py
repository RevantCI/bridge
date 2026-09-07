"""Stage 9B.4 positive semantic verification of an applied correction.

The governing rule of this module is that a correction is **not** verified
because a finding disappeared.  Verification asks one question:

    Is the original failed semantic obligation now positively satisfied by
    CURRENT post-correction evidence?

Everything here is read-only with respect to Scripture.  The only durable
writes are the verification record itself, the proposal's independent
``verificationStatus`` field, and -- on a separate, explicit human
acknowledgement -- the QA finding's disposition.  No Scripture, no proposal
wording, no alignment, and no analysis job is ever changed from here.

Four states stay independent throughout and are never collapsed into one
field: the correction application state, the affected analysis state, the
semantic verification status, and the human QA disposition.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import threading
from typing import Any
import uuid

from .analysis_jobs import TERMINAL
from .meaning_analysis import (
    MEANING_ENGINE_VERSION,
    MEANING_POLICY_VERSION,
    DeterministicMeaningComparator,
)
from .passage_semantic_models import (
    ActorType,
    CoverageDimension,
    MeaningComponentStatus,
    MeaningStatus,
    QaDisposition,
    SourceCoverage,
    TargetSupport,
    VerificationStatus,
)
from .qa_audit import QA_ENGINE_VERSION, QA_POLICY_VERSION
from .semantic_location import LOCATION_ENGINE_VERSION
from .passage_semantic_repository import FoundationConflict, FoundationValidationError


VERIFICATION_ENGINE_VERSION = "bridge-correction-verification-v1"
VERIFICATION_POLICY_VERSION = "correction-verification-policy-v2"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


# --- Reason codes -----------------------------------------------------------
#
# Reason codes are part of the durable record and of the reviewer-facing
# explanation, so they name the *evidence*, never a bare verdict.

class ReasonCode:
    # Preconditions -- these keep verification PENDING; none of them is a
    # semantic failure.  A technical analysis problem must never read as
    # "the translation is still wrong".
    APPLICATION_NOT_COMPLETED = "APPLICATION_NOT_COMPLETED"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    ANALYSIS_NOT_RUN = "ANALYSIS_NOT_RUN"
    ANALYSIS_RUNNING = "ANALYSIS_RUNNING"
    ANALYSIS_FAILED = "ANALYSIS_FAILED"
    ANALYSIS_CANCELLED = "ANALYSIS_CANCELLED"
    ANALYSIS_NOT_CURRENT = "ANALYSIS_NOT_CURRENT"

    # Positive satisfaction
    DIMENSION_PRESERVED = "DIMENSION_PRESERVED"
    DIMENSION_PRESERVED_BY_RESTRUCTURING = "DIMENSION_PRESERVED_BY_RESTRUCTURING"
    COVERAGE_COVERED = "COVERAGE_COVERED"
    COVERAGE_COVERED_BY_RESTRUCTURING = "COVERAGE_COVERED_BY_RESTRUCTURING"

    # Positive failure
    DIMENSION_CONTRADICTED = "DIMENSION_CONTRADICTED"
    DIMENSION_ALTERED = "DIMENSION_ALTERED"
    DIMENSION_STILL_WEAKENED = "DIMENSION_STILL_WEAKENED"
    COVERAGE_STILL_MISSING = "COVERAGE_STILL_MISSING"

    # Insufficient / conflicting evidence
    COVERAGE_POSSIBLY_MISSING = "COVERAGE_POSSIBLY_MISSING"
    COVERAGE_UNRESOLVED = "COVERAGE_UNRESOLVED"
    LOCATION_AMBIGUOUS = "LOCATION_AMBIGUOUS"
    SEARCH_INCOMPLETE = "SEARCH_INCOMPLETE"
    RESOURCE_CONFLICT_UNRESOLVED = "RESOURCE_CONFLICT_UNRESOLVED"
    EVIDENCE_INSUFFICIENT = "EVIDENCE_INSUFFICIENT"
    CONFLICTING_CURRENT_ASSESSMENT = "CONFLICTING_CURRENT_ASSESSMENT"
    PROVIDER_LIMITED = "PROVIDER_LIMITED"
    TARGET_ADDS_SPECIFICITY = "TARGET_ADDS_SPECIFICITY"
    NEW_TARGET_SUPPORT_UNRESOLVED = "NEW_TARGET_SUPPORT_UNRESOLVED"
    NO_CURRENT_OBLIGATION_EVIDENCE = "NO_CURRENT_OBLIGATION_EVIDENCE"

    # Recorded as supporting context only -- never a verdict on its own.
    RECURRING_FINDING_SAME_DIMENSION = "RECURRING_FINDING_SAME_DIMENSION"


REASON_EXPLANATIONS: dict[str, str] = {
    ReasonCode.APPLICATION_NOT_COMPLETED:
        "The correction application has not reached COMPLETED.",
    ReasonCode.RECOVERY_REQUIRED:
        "Correction recovery must be resolved before verification can be trusted.",
    ReasonCode.ANALYSIS_NOT_RUN:
        "Affected passage analysis has not been run for this correction.",
    ReasonCode.ANALYSIS_RUNNING:
        "Affected passage analysis is still running.",
    ReasonCode.ANALYSIS_FAILED:
        "Affected passage analysis failed technically. That is not a semantic verdict.",
    ReasonCode.ANALYSIS_CANCELLED:
        "Affected passage analysis was cancelled. That is not a semantic verdict.",
    ReasonCode.ANALYSIS_NOT_CURRENT:
        "The affected analysis does not describe the current target text.",
    ReasonCode.DIMENSION_PRESERVED:
        "Current evidence shows the required meaning is expressed in the corrected text.",
    ReasonCode.DIMENSION_PRESERVED_BY_RESTRUCTURING:
        "Current evidence shows the required meaning is expressed through legitimate "
        "restructuring, grammar, a pronoun or implicit realization.",
    ReasonCode.COVERAGE_COVERED:
        "The source obligation is now positively covered in the current translation.",
    ReasonCode.COVERAGE_COVERED_BY_RESTRUCTURING:
        "The source obligation is now covered by legitimate restructuring.",
    ReasonCode.DIMENSION_CONTRADICTED:
        "Current evidence still contradicts the required meaning.",
    ReasonCode.DIMENSION_ALTERED:
        "Current evidence shows the required meaning is still altered.",
    ReasonCode.DIMENSION_STILL_WEAKENED:
        "The corrected text still weakens the required meaning.",
    ReasonCode.COVERAGE_STILL_MISSING:
        "The source obligation still has no located realization in the current translation.",
    ReasonCode.COVERAGE_POSSIBLY_MISSING:
        "The source obligation may still be uncovered, but the current analysis did not "
        "resolve it. A possible omission is not an established one.",
    ReasonCode.COVERAGE_UNRESOLVED:
        "The current analysis could not resolve whether the source obligation is covered.",
    ReasonCode.LOCATION_AMBIGUOUS:
        "The target realization is ambiguous, so preservation cannot be established.",
    ReasonCode.SEARCH_INCOMPLETE:
        "The semantic search over this passage was incomplete, so absence proves nothing.",
    ReasonCode.RESOURCE_CONFLICT_UNRESOLVED:
        "Applicable tN/tW/TWL evidence conflicts and has not been resolved.",
    ReasonCode.EVIDENCE_INSUFFICIENT:
        "Current evidence is insufficient to establish preservation or failure.",
    ReasonCode.CONFLICTING_CURRENT_ASSESSMENT:
        "Current semantic assessments disagree about this obligation.",
    ReasonCode.PROVIDER_LIMITED:
        "No production multilingual embedding provider is configured, which limits "
        "retrieval-based evidence.",
    ReasonCode.TARGET_ADDS_SPECIFICITY:
        "The corrected text adds specificity the located source expression does not carry.",
    ReasonCode.NEW_TARGET_SUPPORT_UNRESOLVED:
        "Support for wording the correction introduced is unresolved.",
    ReasonCode.NO_CURRENT_OBLIGATION_EVIDENCE:
        "No current semantic record covers the obligation this correction targeted.",
    ReasonCode.RECURRING_FINDING_SAME_DIMENSION:
        "A current QA finding names the same obligation and semantic dimension.",
}


# Component statuses that positively demonstrate the dimension survives.
_POSITIVE = {MeaningComponentStatus.PRESERVED.value}
# Positive, but realized non-lexically.  The legitimate 1 -> null realizations
# land here; they are preservation, not absence.
_POSITIVE_RESTRUCTURED = {MeaningComponentStatus.NOT_EXPLICIT_BUT_RECOVERABLE.value}
# Component statuses that positively demonstrate the original problem remains.
_NEGATIVE = {
    MeaningComponentStatus.CONTRADICTED.value,
    MeaningComponentStatus.ALTERED.value,
    MeaningComponentStatus.TARGET_WEAKENS_SPECIFICITY.value,
}
_NEGATIVE_REASON = {
    MeaningComponentStatus.CONTRADICTED.value: ReasonCode.DIMENSION_CONTRADICTED,
    MeaningComponentStatus.ALTERED.value: ReasonCode.DIMENSION_ALTERED,
    MeaningComponentStatus.TARGET_WEAKENS_SPECIFICITY.value: ReasonCode.DIMENSION_STILL_WEAKENED,
}

_POSITIVE_COVERAGE = {
    SourceCoverage.COVERED.value: ReasonCode.COVERAGE_COVERED,
    SourceCoverage.COVERED_BY_RESTRUCTURING.value: ReasonCode.COVERAGE_COVERED_BY_RESTRUCTURING,
}
# Coverage Stage 8 positively resolved as uncovered.  Only a resolved MISSING is
# a positive absence, and only it may support an absence-based FAILED.
_ABSENT_COVERAGE = {SourceCoverage.MISSING.value}
# Coverage Stage 8 looked at and could not resolve.  These are candidates
# awaiting a human, not conclusions: promoting POSSIBLY_MISSING to a failure
# here would be exactly the auto-promotion HANDOFF.md §39 forbids.  NOT_CHECKED
# is deliberately absent -- it means Stage 8 made no coverage claim at all, which
# must not veto positive dimension evidence.
_UNRESOLVED_COVERAGE = {
    SourceCoverage.POSSIBLY_MISSING.value: ReasonCode.COVERAGE_POSSIBLY_MISSING,
    SourceCoverage.UNCERTAIN.value: ReasonCode.COVERAGE_UNRESOLVED,
}

# A target unit introduced by the correction may legitimately have no direct
# source token.  The null -> 1 rule: these are support, not additions.
_LEGITIMATE_TARGET_SUPPORT = {
    TargetSupport.SOURCE_SUPPORTED.value,
    TargetSupport.CONTEXT_SUPPORTED.value,
    TargetSupport.GRAMMATICALLY_REQUIRED.value,
    TargetSupport.EXPLICITATION_SUPPORTED.value,
}

# Evidence kinds produced by the deterministic comparator rather than by
# retrieval similarity.  A limited embedding provider does not weaken these.
_DETERMINISTIC_EVIDENCE = {
    "POLARITY", "QUANTITY", "PARTICIPANT", "SEMANTIC_ROLE", "TEMPORAL",
    "COMPLETION", "MODALITY", "GRAMMATICAL", "LEXICAL_CONCEPT",
    "DETERMINISTIC_CONTRADICTION",
}

# A FAILED verdict resting on nothing but absence.  An incomplete search can
# invalidate this; it cannot invalidate a located contradiction.
_ABSENCE_BASED_FAILURE = {ReasonCode.COVERAGE_STILL_MISSING}

_LOCATED = "LOCATED"
_UNUSABLE_LOCATION = {
    "AMBIGUOUS": ReasonCode.LOCATION_AMBIGUOUS,
    "SEARCH_INCOMPLETE": ReasonCode.SEARCH_INCOMPLETE,
    "UNSUPPORTED_ANALYSIS": ReasonCode.EVIDENCE_INSUFFICIENT,
}


class CorrectionVerificationPolicy:
    """One versioned place deciding PASSED / FAILED / UNCERTAIN.

    It reads only current post-correction evidence and never consults whether
    the original finding still exists.  Finding recurrence enters at the
    aggregate level as *supporting* context, never as a verdict of its own.
    """

    version = VERIFICATION_POLICY_VERSION

    def verdict_for_obligation(
        self, *, dimension: str, components: list[dict[str, Any]],
        direct_recheck: tuple[str, float, str, str] | None,
        coverage_status: str, relationships: list[dict[str, Any]],
        assessments: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Decide one source obligation from current evidence alone."""
        reasons: list[str] = []
        located = [item for item in relationships if item.get("locationOutcome") == _LOCATED]
        unusable = [
            _UNUSABLE_LOCATION[str(item.get("locationOutcome"))]
            for item in relationships
            if str(item.get("locationOutcome")) in _UNUSABLE_LOCATION
        ]

        statuses = {str(item.get("status")) for item in components}
        conflicting_resource = any(
            str((item.get("evidence") or {}).get("resourceStatus")) == "CONFLICTING"
            for item in components
        )
        deterministic = any(
            str((item.get("evidence") or {}).get("kind")) in _DETERMINISTIC_EVIDENCE
            for item in components
        )
        confidence = max(
            (float((item.get("confidence") or {}).get("rawScore") or 0.0) for item in components),
            default=0.0,
        )

        negative = statuses & _NEGATIVE
        positive = statuses & _POSITIVE
        restructured = statuses & _POSITIVE_RESTRUCTURED

        # The dimension-targeted recheck (see the service) supplies evidence for
        # exactly the dimension the correction targeted.  It never overrides a
        # persisted component: disagreement becomes UNCERTAIN, not a silent win.
        recheck_status = str(direct_recheck[0]) if direct_recheck else ""
        recheck_kind = str(direct_recheck[2]) if direct_recheck else ""
        if direct_recheck:
            confidence = max(confidence, float(direct_recheck[1]))
            deterministic = deterministic or recheck_kind in _DETERMINISTIC_EVIDENCE

        if negative and recheck_status in (_POSITIVE | _POSITIVE_RESTRUCTURED):
            return self._verdict(
                "UNCERTAIN", [ReasonCode.CONFLICTING_CURRENT_ASSESSMENT], confidence, deterministic)
        if (positive or restructured) and recheck_status in _NEGATIVE:
            return self._verdict(
                "UNCERTAIN", [ReasonCode.CONFLICTING_CURRENT_ASSESSMENT], confidence, deterministic)

        if negative or recheck_status in _NEGATIVE:
            failing = sorted(negative) or [recheck_status]
            reasons = [_NEGATIVE_REASON[item] for item in failing if item in _NEGATIVE_REASON]
            # Search failure must never become a false absence, but a located
            # deterministic contradiction is unaffected by an incomplete search.
            if ReasonCode.SEARCH_INCOMPLETE in unusable and not deterministic:
                return self._verdict(
                    "UNCERTAIN", [ReasonCode.SEARCH_INCOMPLETE, *reasons], confidence, deterministic)
            return self._verdict("FAILED", reasons, confidence, deterministic)

        if MeaningComponentStatus.TARGET_ADDS_SPECIFICITY.value in statuses:
            return self._verdict(
                "UNCERTAIN", [ReasonCode.TARGET_ADDS_SPECIFICITY], confidence, deterministic)
        if conflicting_resource:
            return self._verdict(
                "UNCERTAIN", [ReasonCode.RESOURCE_CONFLICT_UNRESOLVED], confidence, deterministic)
        if unusable:
            return self._verdict("UNCERTAIN", sorted(set(unusable)), confidence, deterministic)

        if positive or recheck_status in _POSITIVE:
            reasons.append(ReasonCode.DIMENSION_PRESERVED)
        elif restructured or recheck_status in _POSITIVE_RESTRUCTURED:
            reasons.append(ReasonCode.DIMENSION_PRESERVED_BY_RESTRUCTURING)

        if coverage_status in _POSITIVE_COVERAGE:
            reasons.append(_POSITIVE_COVERAGE[coverage_status])
        elif coverage_status in _ABSENT_COVERAGE:
            # A 1 -> null obligation is a failure only when Stage 8 positively
            # concluded every relationship touching it is genuinely NOT_LOCATED.
            if ReasonCode.SEARCH_INCOMPLETE in unusable:
                return self._verdict(
                    "UNCERTAIN", [ReasonCode.SEARCH_INCOMPLETE], confidence, deterministic)
            if not reasons:
                return self._verdict(
                    "FAILED", [ReasonCode.COVERAGE_STILL_MISSING], confidence, deterministic)
            return self._verdict(
                "UNCERTAIN", [ReasonCode.CONFLICTING_CURRENT_ASSESSMENT], confidence, deterministic)
        elif coverage_status in _UNRESOLVED_COVERAGE:
            # Stage 8 did not resolve coverage.  Unresolved absence is not
            # absence: it can never reach FAILED on its own, and it cannot be
            # waved through as PASSED either, so it always abstains.  When
            # positive dimension evidence exists this is also a genuine
            # disagreement between two current assessments -- still UNCERTAIN.
            code = _UNRESOLVED_COVERAGE[coverage_status]
            if ReasonCode.SEARCH_INCOMPLETE in unusable:
                return self._verdict(
                    "UNCERTAIN", [ReasonCode.SEARCH_INCOMPLETE, code], confidence, deterministic)
            return self._verdict("UNCERTAIN", [code, *reasons], confidence, deterministic)

        if not reasons:
            if not relationships and not located:
                return self._verdict(
                    "UNCERTAIN", [ReasonCode.NO_CURRENT_OBLIGATION_EVIDENCE],
                    confidence, deterministic)
            return self._verdict(
                "UNCERTAIN", [ReasonCode.EVIDENCE_INSUFFICIENT], confidence, deterministic)

        # An overall meaning status still reporting a problem contradicts a
        # component-level pass; abstain rather than pick a side.
        overall = {str(item.get("meaningStatus")) for item in assessments}
        if overall & {MeaningStatus.CONTRADICTED.value, MeaningStatus.MEANING_SHIFT.value}:
            return self._verdict(
                "UNCERTAIN", [ReasonCode.CONFLICTING_CURRENT_ASSESSMENT], confidence, deterministic)
        return self._verdict("PASSED", reasons, confidence, deterministic)

    @staticmethod
    def _verdict(
        result: str, reasons: list[str], confidence: float, deterministic: bool,
    ) -> dict[str, Any]:
        return {
            "result": result, "reasonCodes": list(dict.fromkeys(reasons)),
            "confidence": round(float(confidence), 4), "deterministic": bool(deterministic),
        }

    def aggregate(
        self, verdicts: list[dict[str, Any]], *, provider_limited: bool, search_incomplete: bool,
    ) -> dict[str, Any]:
        """Combine obligation verdicts, then apply run-level caution."""
        if not verdicts:
            return self._verdict(
                "UNCERTAIN", [ReasonCode.NO_CURRENT_OBLIGATION_EVIDENCE], 0.0, False)
        reasons = [code for item in verdicts for code in item["reasonCodes"]]
        confidence = min(float(item["confidence"]) for item in verdicts)
        deterministic = all(bool(item["deterministic"]) for item in verdicts)
        results = {item["result"] for item in verdicts}
        result = "FAILED" if "FAILED" in results else (
            "UNCERTAIN" if "UNCERTAIN" in results else "PASSED"
        )

        if result == "PASSED" and search_incomplete:
            # An incomplete search cannot license a positive claim about the
            # whole obligation, even when each located component looked fine.
            return self._verdict(
                "UNCERTAIN", [ReasonCode.SEARCH_INCOMPLETE, *reasons], confidence, deterministic)
        if result == "FAILED" and search_incomplete and all(
            set(item["reasonCodes"]) <= _ABSENCE_BASED_FAILURE
            for item in verdicts if item["result"] == "FAILED"
        ):
            # Symmetrically, a run-level incomplete search cannot license a
            # negative claim that rests only on absence -- the realization may
            # simply lie in the part of the passage the search never reached. A
            # located contradiction is unaffected, so a mixed set still fails.
            return self._verdict(
                "UNCERTAIN", [ReasonCode.SEARCH_INCOMPLETE, *reasons], confidence, deterministic)
        if provider_limited:
            reasons.append(ReasonCode.PROVIDER_LIMITED)
            # A missing production embedding provider does not invalidate
            # deterministic evidence; it only limits retrieval-based evidence.
            if result == "PASSED" and not deterministic:
                return self._verdict("UNCERTAIN", reasons, confidence * 0.75, deterministic)
            confidence *= 0.9
        return self._verdict(result, reasons, confidence, deterministic)


class CorrectionVerificationService:
    """Backend-owned verification. The frontend never decides a verdict."""

    def __init__(
        self, runtime: Any, jobs: Any, policy: CorrectionVerificationPolicy | None = None,
    ):
        self.runtime = runtime
        self.repository = runtime.repository
        self.jobs = jobs
        self.policy = policy or CorrectionVerificationPolicy()
        self._lock = threading.RLock()

    # --- identity ---------------------------------------------------------

    def fingerprint(self) -> str:
        """Version identity of the verification algorithm and its inputs.

        Upstream engine/policy versions are included deliberately: a change to
        how Stage 6B locates, Stage 7 judges meaning or Stage 8 gates coverage
        changes what this verdict means, so a verification produced by older
        logic must not keep presenting itself as current after such a change.
        """
        return _json_hash({
            "engine": VERIFICATION_ENGINE_VERSION,
            "policy": self.policy.version,
            "location": LOCATION_ENGINE_VERSION,
            "meaning": MEANING_ENGINE_VERSION,
            "meaningPolicy": MEANING_POLICY_VERSION,
            "qa": QA_ENGINE_VERSION,
            "qaPolicy": QA_POLICY_VERSION,
        })

    @staticmethod
    def _parts(reference: str) -> tuple[str, str]:
        _, separator, location = str(reference).rpartition(" ")
        if not separator or ":" not in location:
            raise FoundationValidationError(f"Invalid target reference: {reference}")
        chapter, verse = location.split(":", 1)
        return chapter, verse

    def _current_target_hash(self, reference: str) -> str:
        chapter, verse = self._parts(reference)
        return self.runtime.text_hash(str(self.runtime.project.target_verse_text(chapter, verse)))

    # --- preconditions ----------------------------------------------------

    def _application(self, application_id: str) -> dict[str, Any]:
        application = self.repository.application_intent(application_id)
        if application.get("projectId") != self.runtime.project_id:
            raise FoundationValidationError("Correction application belongs to another project")
        return application

    def _analysis_job(self, application: dict[str, Any]) -> dict[str, Any] | None:
        metadata = application.get("resultMetadata") or {}
        attempts = list(metadata.get("affectedAnalysisAttempts") or ())
        job_id = str(attempts[-1].get("analysisJobId") or "") if attempts else str(
            metadata.get("affectedAnalysisJobId") or ""
        )
        if not job_id:
            return None
        try:
            return self.jobs.status(job_id)
        except Exception:
            try:
                return self.repository.analysis_job(job_id)
            except Exception:
                return None

    def _precondition_block(
        self, application: dict[str, Any], job: dict[str, Any] | None,
    ) -> list[str]:
        """Reasons verification cannot yet be concluded. All keep it PENDING."""
        reasons: list[str] = []
        if application.get("applicationState") != "COMPLETED":
            reasons.append(ReasonCode.APPLICATION_NOT_COMPLETED)
        if bool(self.runtime.application_recovery.get("correctionWritesBlocked")):
            reasons.append(ReasonCode.RECOVERY_REQUIRED)
        if job is None:
            reasons.append(ReasonCode.ANALYSIS_NOT_RUN)
            return reasons
        status = str(job.get("overallStatus") or "")
        if status not in TERMINAL:
            reasons.append(ReasonCode.ANALYSIS_RUNNING)
        elif status == "CANCELLED":
            reasons.append(ReasonCode.ANALYSIS_CANCELLED)
        elif status not in {"COMPLETED", "COMPLETED_WITH_WARNINGS"}:
            reasons.append(ReasonCode.ANALYSIS_FAILED)
        if reasons:
            return reasons
        reference = str(application["targetDisplayedReference"])
        recorded = str((job.get("targetHashes") or {}).get(reference) or "")
        if not recorded or recorded != self._current_target_hash(reference):
            reasons.append(ReasonCode.ANALYSIS_NOT_CURRENT)
        return reasons

    # --- evidence ---------------------------------------------------------

    @staticmethod
    def _source_text(unit: dict[str, Any]) -> str:
        features = unit.get("semanticFeatures") or {}
        return str(features.get("lemma") or features.get("quantifierLemma")
                   or unit.get("normalizedSurface") or unit.get("rawSurface") or "")

    def _obligation_units(
        self, proposal: dict[str, Any], finding: dict[str, Any],
    ) -> list[str]:
        intent = proposal.get("intent") or {}
        ids = [
            str(item) for item in intent.get("affectedSourceSemanticUnitIds") or ()
            if str(item).strip()
        ] or [
            str(item) for item in finding.get("sourceSemanticUnitIds") or ()
            if str(item).strip()
        ]
        for unit_id in ids:
            unit = self.repository.semantic_unit(unit_id)
            if unit.get("projectId") != self.runtime.project_id or unit.get("side") != "SOURCE":
                raise FoundationValidationError(
                    f"Correction obligation unit is invalid for this project: {unit_id}"
                )
        return list(dict.fromkeys(ids))

    def _current_runs(self, job: dict[str, Any]) -> dict[str, Any]:
        """Read the Stage 6B/7/8 records produced by this exact analysis job.

        Every reader refuses a non-ACTIVE run, so evidence superseded by a
        later edit can never be presented here as current.
        """
        stages = job.get("stageStatuses") or {}
        location_id = str((stages.get("LOCATION") or {}).get("runId") or "")
        meaning_id = str((stages.get("MEANING") or {}).get("runId") or "")
        qa_id = str((stages.get("QA") or {}).get("runId") or "")
        if not (location_id and meaning_id and qa_id):
            raise FoundationConflict("STALE_EVIDENCE: the affected analysis recorded no run ids")
        try:
            return {
                "location": self.repository.semantic_location_run(location_id),
                "meaning": self.repository.meaning_analysis_run(meaning_id),
                "qa": self.repository.qa_audit_run(qa_id),
            }
        except FoundationValidationError as exc:
            raise FoundationConflict(f"STALE_EVIDENCE: {exc}") from exc

    def _coverage_accounts(self, qa_run: dict[str, Any], key: str) -> list[dict[str, Any]]:
        accounts: list[dict[str, Any]] = []
        for account_id in qa_run.get(key) or ():
            try:
                accounts.append(self.repository.coverage_account(str(account_id)))
            except FoundationValidationError:
                continue
        return accounts

    def _gather(self, *, unit_id: str, dimension: str, runs: dict[str, Any]) -> dict[str, Any]:
        location, meaning, qa = runs["location"], runs["meaning"], runs["qa"]
        relationships = [
            item for item in location.get("relationships") or ()
            if unit_id in (item.get("sourceSemanticUnitIds") or ())
        ]
        relationship_ids = {str(item.get("id")) for item in relationships}
        assessments = [
            item for item in meaning.get("assessments") or ()
            if str(item.get("semanticLocationRelationshipId")) in relationship_ids
        ]
        components = [
            component for item in assessments
            for component in item.get("componentAssessments") or ()
            if str(component.get("coverageDimension")) == dimension
            and unit_id in (component.get("sourceSemanticUnitIds") or ())
        ]
        accounts = self._coverage_accounts(qa, "sourceCoverageAccountIds")
        coverage = ""
        for account in accounts:
            if (str(account.get("auditOwnerUnitId")) == unit_id
                    and str(account.get("coverageDimension")) == dimension):
                coverage = str(account.get("coverageStatus") or "")
                break
        if not coverage:
            # The reviewer may have corrected a dimension other than the unit's
            # own; that unit's account still says whether it is covered at all.
            for account in accounts:
                if str(account.get("auditOwnerUnitId")) == unit_id:
                    coverage = str(account.get("coverageStatus") or "")
                    break
        return {
            "relationships": relationships, "assessments": assessments,
            "components": components, "coverageStatus": coverage,
        }

    def _direct_recheck(
        self, *, unit_id: str, dimension: str, runs: dict[str, Any],
        relationships: list[dict[str, Any]],
    ) -> tuple[str, float, str, str] | None:
        """Re-apply the existing Stage 7 comparator for the corrected dimension.

        This adds no second meaning engine: it is the same versioned
        ``DeterministicMeaningComparator`` asked about the one dimension the
        correction targeted, over the current located source and target text.
        Stage 7 scores a source unit only on that unit's own coverage
        dimension, so without this a QUANTITY or POLARITY correction recorded
        against a LEXICAL_CONTENT unit would have no dimension-specific
        evidence at all.
        """
        located = [item for item in relationships if item.get("locationOutcome") == _LOCATED]
        if not located:
            return None
        inventory = self.repository.source_inventory(runs["location"]["sourceInventoryId"])
        unit = {item["id"]: item for item in inventory.get("units") or ()}.get(unit_id)
        if unit is None:
            return None
        candidates = {str(item.get("id")): item for item in runs["location"].get("candidates") or ()}
        target_inventory = self.repository.target_inventory(runs["location"]["targetInventoryId"])
        capabilities = target_inventory.get("capabilities") or {}
        for relationship in located:
            candidate = candidates.get(str(relationship.get("selectedCandidateId")))
            if candidate is None:
                continue
            target_text = " … ".join(
                str(item.get("quote") or "") for item in candidate.get("quotes") or ()
            )
            status, confidence, kind, explanation = DeterministicMeaningComparator.compare(
                self._source_text(unit), target_text, dimension,
                str(unit.get("kind") or "LEXICAL"),
                str(relationship.get("realization") or "LEXICALLY_REALIZED"),
                capabilities,
            )
            if status != MeaningComponentStatus.NOT_DETERMINABLE:
                return (status.value, float(confidence), kind.value, explanation)
        return None

    def _recurring_findings(
        self, *, unit_ids: list[str], dimension: str, runs: dict[str, Any],
        original_finding_id: str,
    ) -> list[dict[str, Any]]:
        """Current findings naming the same obligation and dimension.

        Deliberately matched on semantic identity -- source units plus coverage
        dimension -- not on the stable finding id.  The same id may legitimately
        recur, and a different id may describe the same failure.
        """
        wanted = set(unit_ids)
        accounts = {
            str(item.get("id")): item
            for item in self._coverage_accounts(runs["qa"], "sourceCoverageAccountIds")
        }
        matches: list[dict[str, Any]] = []
        for finding in runs["qa"].get("findings") or ():
            units = {str(item) for item in finding.get("sourceSemanticUnitIds") or ()}
            if not units & wanted:
                continue
            dimensions = {
                str(accounts[str(item)].get("coverageDimension"))
                for item in finding.get("coverageAccountIds") or ()
                if str(item) in accounts
            }
            if dimensions and dimension not in dimensions:
                continue
            matches.append({
                "findingId": str(finding.get("id")),
                "kind": str(finding.get("kind")),
                "sameStableIdentityAsOriginal": str(finding.get("id")) == original_finding_id,
            })
        return matches

    def _new_target_support(
        self, *, application: dict[str, Any], runs: dict[str, Any],
    ) -> list[str]:
        """Support state of target units inside the corrected span only.

        Wording the correction introduced is a null -> 1 case: it is not an
        addition merely because no source token maps to it.  Only an unresolved
        support state is reported, and only within the exact edited span.
        """
        reference = str(application["targetDisplayedReference"])
        start = int(application["expectedStartCodePoint"])
        end = start + len(str(application["replacementTextSnapshot"]))
        target_units = {
            item["id"]: item
            for item in (self.repository.target_inventory(runs["location"]["targetInventoryId"])
                         .get("units") or ())
        }
        unresolved: list[str] = []
        for account in self._coverage_accounts(runs["qa"], "targetSupportAccountIds"):
            unit = target_units.get(str(account.get("auditOwnerUnitId")))
            if unit is None or reference not in (unit.get("displayedReferences") or ()):
                continue
            features = unit.get("semanticFeatures") or {}
            try:
                unit_start = int(features.get("startCodePoint"))
                unit_end = int(features.get("endCodePoint"))
            except (TypeError, ValueError):
                continue
            if unit_end <= start or unit_start >= end:
                continue
            status = str(account.get("coverageStatus") or "")
            if status and status != "NOT_CHECKED" and status not in _LEGITIMATE_TARGET_SUPPORT:
                unresolved.append(str(account.get("auditOwnerUnitId")))
        return unresolved

    # --- public API -------------------------------------------------------

    def get(self, application_id: str) -> dict[str, Any]:
        """Read the current verification state without evaluating anything."""
        application = self._application(application_id)
        proposal = self.repository.correction_proposal(application["proposalId"])
        finding = self.repository.qa_finding(application["findingId"])
        job = self._analysis_job(application)
        blocking = self._precondition_block(application, job)
        record = self.repository.current_correction_verification(application_id)
        if record is None:
            # A later edit supersedes the record but must never erase it: a
            # CORRECTED acknowledgement stays discoverable as history, marked
            # not-current, rather than silently vanishing from the panel.
            history = self.repository.correction_verification_history(application_id)
            record = history[-1] if history else None
        return self._envelope(
            application, proposal, finding, job, record,
            self._is_current(record, application), blocking,
        )

    def _is_current(self, record: dict[str, Any] | None, application: dict[str, Any]) -> bool:
        if record is None or record.get("lifecycleStatus") != "ACTIVE":
            return False
        if str(record.get("verifierFingerprint")) != self.fingerprint():
            return False
        reference = str(application["targetDisplayedReference"])
        return str(record.get("targetContentHash")) == self._current_target_hash(reference)

    def _envelope(
        self, application: dict[str, Any], proposal: dict[str, Any], finding: dict[str, Any],
        job: dict[str, Any] | None, record: dict[str, Any] | None, current: bool,
        blocking: list[str],
    ) -> dict[str, Any]:
        if record is not None and current:
            status = str(record["result"])
            reasons = list(blocking) or list(record.get("reasonCodes") or ())
        else:
            status = VerificationStatus.PENDING.value
            reasons = list(blocking)
        acknowledged = bool(record and record.get("acknowledgedAt"))
        return {
            "applicationId": str(application["applicationId"]),
            "applicationState": str(application["applicationState"]),
            "affectedAnalysisState": self._analysis_state(job),
            "affectedAnalysisJobId": str((job or {}).get("jobId") or ""),
            "verificationStatus": status,
            "verificationId": str((record or {}).get("verificationId") or ""),
            "verificationCurrent": bool(current),
            "verificationRevision": int((record or {}).get("revision") or 0),
            "verificationReasonCodes": list(dict.fromkeys(reasons)),
            "reasonExplanations": [
                {"code": code, "detail": REASON_EXPLANATIONS.get(code, code)}
                for code in dict.fromkeys(reasons)
            ],
            "mayVerify": not blocking,
            "mayAcknowledgeCorrected": bool(
                current and record is not None and not blocking and not acknowledged
                and str(record.get("result")) == VerificationStatus.PASSED.value
                and str(finding.get("qaDisposition")) != QaDisposition.CORRECTED.value
            ),
            "qaDisposition": str(finding.get("qaDisposition") or ""),
            "findingId": str(finding.get("id") or ""),
            "findingRevision": int(finding.get("revision") or 0),
            "proposalId": str(proposal.get("id") or ""),
            "correctedAcknowledgement": None if not acknowledged else {
                "verificationId": str(record["verificationId"]),
                "acknowledgedBy": str(record.get("acknowledgedBy") or ""),
                "acknowledgedAt": str(record.get("acknowledgedAt") or ""),
                "note": str((record.get("payload") or {}).get("acknowledgementNote") or ""),
                "current": bool(current),
            },
            "verification": record,
            "verifierFingerprint": self.fingerprint(),
            "verifierEngineVersion": VERIFICATION_ENGINE_VERSION,
            "verifierPolicyVersion": self.policy.version,
            "history": self.repository.correction_verification_history(
                str(application["applicationId"])
            ),
        }

    @staticmethod
    def _analysis_state(job: dict[str, Any] | None) -> str:
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

    def verify(self, application_id: str, *, requested_by: str) -> dict[str, Any]:
        actor = str(requested_by or "").strip()
        if not actor:
            raise FoundationValidationError("Verification requires a requester")
        with self._lock:
            application = self._application(application_id)
            proposal = self.repository.correction_proposal(application["proposalId"])
            finding = self.repository.qa_finding(application["findingId"])
            job = self._analysis_job(application)
            blocking = self._precondition_block(application, job)
            if blocking:
                # Technical analysis failure is not semantic verification
                # failure: nothing is recorded and the status stays PENDING.
                return self._envelope(application, proposal, finding, job, None, False, blocking)

            existing = self.repository.correction_verification_for_inputs(
                application_id=application_id,
                analysis_job_id=str(job["jobId"]),
                target_content_hash=self._current_target_hash(
                    str(application["targetDisplayedReference"])
                ),
                verifier_fingerprint=self.fingerprint(),
            )
            record = existing if existing is not None else self._evaluate(
                application, proposal, finding, job, actor,
            )
            return self._envelope(
                application, proposal, finding, job, record,
                self._is_current(record, application), [],
            )

    def _evaluate(
        self, application: dict[str, Any], proposal: dict[str, Any],
        finding: dict[str, Any], job: dict[str, Any], actor: str,
    ) -> dict[str, Any]:
        runs = self._current_runs(job)
        intent = proposal.get("intent") or {}
        dimension = str(intent.get("failedDimension") or CoverageDimension.OTHER.value)
        unit_ids = self._obligation_units(proposal, finding)
        reference = str(application["targetDisplayedReference"])

        obligations: list[dict[str, Any]] = []
        verdicts: list[dict[str, Any]] = []
        source_references: list[str] = []
        for unit_id in unit_ids:
            unit = self.repository.semantic_unit(unit_id)
            # Source provenance stays the source unit's own reference. It is
            # never collapsed onto the edited target verse.
            source_references.extend(
                str(item) for item in
                (unit.get("canonicalReferences") or unit.get("displayedReferences") or ())
                if str(item).strip()
            )
            evidence = self._gather(unit_id=unit_id, dimension=dimension, runs=runs)
            recheck = self._direct_recheck(
                unit_id=unit_id, dimension=dimension, runs=runs,
                relationships=evidence["relationships"],
            )
            verdict = self.policy.verdict_for_obligation(
                dimension=dimension, components=evidence["components"],
                direct_recheck=recheck, coverage_status=evidence["coverageStatus"],
                relationships=evidence["relationships"], assessments=evidence["assessments"],
            )
            verdicts.append(verdict)
            obligations.append({
                "sourceSemanticUnitId": unit_id,
                "coverageDimension": dimension,
                "coverageStatus": evidence["coverageStatus"],
                "result": verdict["result"], "reasonCodes": verdict["reasonCodes"],
                "confidence": verdict["confidence"],
                "componentStatuses": [str(item.get("status")) for item in evidence["components"]],
                "directRecheck": None if recheck is None else {
                    "status": recheck[0], "confidence": round(float(recheck[1]), 4),
                    "evidenceKind": recheck[2], "explanation": recheck[3],
                },
                "relationshipIds": [str(item.get("id")) for item in evidence["relationships"]],
                "meaningAssessmentIds": [str(item.get("id")) for item in evidence["assessments"]],
                "targetReferences": list(dict.fromkeys(
                    str(value) for item in evidence["relationships"]
                    for value in item.get("displayedReferences") or ()
                )),
                "locationOutcomes": [
                    str(item.get("locationOutcome")) for item in evidence["relationships"]
                ],
                "realizations": [
                    str(item.get("realization")) for item in evidence["relationships"]
                ],
                "cardinalities": [
                    "{} → {}".format(
                        len(item.get("sourceSemanticUnitIds") or ()) or "null",
                        len(item.get("targetSemanticUnitIds") or ()) or "null",
                    )
                    for item in evidence["relationships"]
                ],
            })

        capability = job.get("providerCapability") or {}
        provider_limited = str(capability.get("semanticRetrieval") or "") != "FULL"
        search_incomplete = bool(job.get("searchIncomplete"))
        aggregate = self.policy.aggregate(
            verdicts, provider_limited=provider_limited, search_incomplete=search_incomplete,
        )

        recurrence = self._recurring_findings(
            unit_ids=unit_ids, dimension=dimension, runs=runs,
            original_finding_id=str(finding.get("id") or ""),
        )
        result = str(aggregate["result"])
        reasons = list(aggregate["reasonCodes"])
        if recurrence:
            reasons.append(ReasonCode.RECURRING_FINDING_SAME_DIMENSION)
            if result == "PASSED":
                # Current Stage 8 still names this obligation and dimension
                # while our reading says preserved. Two current assessments
                # disagree; abstain instead of asserting either.
                result = "UNCERTAIN"
                reasons.append(ReasonCode.CONFLICTING_CURRENT_ASSESSMENT)

        unresolved_support = self._new_target_support(application=application, runs=runs)
        if unresolved_support and result == "PASSED":
            result = "UNCERTAIN"
            reasons.append(ReasonCode.NEW_TARGET_SUPPORT_UNRESOLVED)

        payload = {
            "sourceSemanticUnitIds": unit_ids,
            "sourceReferences": list(dict.fromkeys(source_references)),
            "targetReferences": list(dict.fromkeys([
                reference,
                *(str(item) for item in application.get("canonicalReferences") or ()),
            ])),
            "failedCoverageDimension": dimension,
            "observedMeaning": str(intent.get("observedMeaning") or ""),
            "requiredMeaning": str(intent.get("requiredMeaning") or ""),
            "obligations": obligations,
            "recurringFindings": recurrence,
            "unresolvedTargetSupportUnitIds": unresolved_support,
            "providerLimited": provider_limited,
            "searchIncomplete": search_incomplete,
            "analysisWarnings": list(job.get("warnings") or ()),
            "locationRunId": str(runs["location"]["id"]),
            "meaningRunId": str(runs["meaning"]["id"]),
            "qaRunId": str(runs["qa"]["id"]),
            "evidenceReferences": {
                "relationshipIds": [
                    item for obligation in obligations for item in obligation["relationshipIds"]
                ],
                "meaningAssessmentIds": [
                    item for obligation in obligations
                    for item in obligation["meaningAssessmentIds"]
                ],
                "currentFindingIds": [item["findingId"] for item in recurrence],
            },
            "verifierEngineVersion": VERIFICATION_ENGINE_VERSION,
            "verifierPolicyVersion": self.policy.version,
            "requestedBy": actor,
        }
        return self.repository.save_correction_verification(
            verification_id="correction-verification-" + str(uuid.uuid4()),
            project_id=self.runtime.project_id,
            application_id=str(application["applicationId"]),
            proposal_id=str(proposal["id"]),
            proposal_revision=int(proposal.get("revision") or 0),
            finding_id=str(finding["id"]),
            analysis_job_id=str(job["jobId"]),
            target_revision=str(job.get("targetRevision") or application["expectedTargetRevision"]),
            target_content_hash=self._current_target_hash(reference),
            verifier_fingerprint=self.fingerprint(),
            result=result,
            confidence=float(aggregate["confidence"]),
            reason_codes=list(dict.fromkeys(reasons)),
            payload=payload,
            created_at=_now(),
        )

    # --- explicit human acknowledgement -----------------------------------

    def acknowledge_corrected(
        self, application_id: str, *, verification_id: str,
        expected_verification_revision: int, expected_finding_revision: int,
        actor: dict[str, Any], note: str = "",
    ) -> dict[str, Any]:
        """Promote the human QA disposition to CORRECTED.

        This is the only path to CORRECTED.  PASSED never sets it on its own,
        and every precondition is re-checked here rather than trusted from
        whatever the UI last rendered.
        """
        if str(actor.get("actorType") or "").upper() != ActorType.HUMAN.value:
            raise FoundationValidationError(
                "Marking a correction corrected requires explicit human action"
            )
        actor_id = str(actor.get("actorId") or "").strip()
        if not actor_id:
            raise FoundationValidationError("Acknowledgement requires a human actor id")
        with self._lock:
            application = self._application(application_id)
            proposal = self.repository.correction_proposal(application["proposalId"])
            finding = self.repository.qa_finding(application["findingId"])
            job = self._analysis_job(application)
            blocking = self._precondition_block(application, job)
            if blocking:
                raise FoundationConflict(
                    "Correction cannot be acknowledged: "
                    + "; ".join(REASON_EXPLANATIONS.get(code, code) for code in blocking)
                )
            record = self.repository.correction_verification(verification_id)
            if str(record.get("applicationId")) != application_id:
                raise FoundationValidationError(
                    "Verification does not belong to this correction application"
                )
            if str(record.get("projectId")) != self.runtime.project_id:
                raise FoundationValidationError("Verification belongs to another project")
            if str(record.get("findingId")) != str(finding["id"]):
                raise FoundationValidationError("Verification does not belong to this finding")
            if not self._is_current(record, application):
                raise FoundationConflict(
                    "Verification is no longer current for the present target text"
                )
            if str(record.get("result")) != VerificationStatus.PASSED.value:
                raise FoundationConflict(
                    "Only a PASSED verification may be acknowledged; this one is "
                    f"{record.get('result')}"
                )
            if record.get("acknowledgedAt"):
                return self._envelope(application, proposal, finding, job, record, True, [])

            self.repository.update_qa_disposition(
                str(finding["id"]), QaDisposition.CORRECTED,
                int(expected_finding_revision), actor_id,
                note=note or "Human acknowledged a PASSED correction verification.",
            )
            record = self.repository.acknowledge_correction_verification(
                verification_id, expected_revision=int(expected_verification_revision),
                actor_id=actor_id, note=note,
            )
            finding = self.repository.qa_finding(str(finding["id"]))
            return self._envelope(application, proposal, finding, job, record, True, [])
