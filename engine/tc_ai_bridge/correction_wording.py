"""Stage 9B.1 correction wording proposals.

This module can create, edit, reject, and regenerate *proposal data*.  It has
no Scripture writer, no analysis runner, and no path to CORRECTED.  Optional
machine wording is behind a provider interface so persistence and offline
human authoring do not depend on OpenAI or any other vendor.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Protocol
import uuid

from .passage_semantic_models import (
    AffectedTargetSpan,
    CorrectionCreationMode,
    CorrectionIntent,
    CorrectionProposalV2,
    CorrectionProviderMetadata,
    CorrectionWordingAlternative,
    CoverageDimension,
    LifecycleStatus,
    PolicyBinding,
    ReviewStatus,
    to_wire,
)
from .passage_semantic_repository import FoundationConflict, FoundationValidationError
from .security import ai_payload_manifest


CORRECTION_WORDING_POLICY_VERSION = "correction-wording-v1"


@dataclass(frozen=True)
class CorrectionSuggestionResult:
    proposed_text: str
    explanation: str
    evidence_ids: tuple[str, ...] = ()
    alternatives: tuple[CorrectionWordingAlternative, ...] = ()
    provider_name: str = ""
    model: str = ""
    model_version_id: str = ""
    prompt_policy_version: str = CORRECTION_WORDING_POLICY_VERSION
    response_fingerprint: str = ""
    warnings: tuple[str, ...] = ()


class CorrectionSuggestionProvider(Protocol):
    @property
    def available(self) -> bool: ...

    def suggest(self, context: dict[str, Any]) -> CorrectionSuggestionResult: ...


class NoCorrectionSuggestionProvider:
    @property
    def available(self) -> bool:
        return False

    def suggest(self, context: dict[str, Any]) -> CorrectionSuggestionResult:
        raise FoundationValidationError("Correction suggestion provider is unavailable")


@dataclass
class FixtureCorrectionSuggestionProvider:
    """Deterministic, offline provider for contract and integration tests."""

    result: CorrectionSuggestionResult
    last_context: dict[str, Any] | None = None

    @property
    def available(self) -> bool:
        return True

    def suggest(self, context: dict[str, Any]) -> CorrectionSuggestionResult:
        self.last_context = context
        return self.result


class ConfiguredCorrectionSuggestionProvider:
    """Thin adapter over Bridge's configured Responses-compatible client.

    Only the supplied correction context is sent.  API credentials remain in
    the client/settings layer and are never returned or persisted here.
    """

    def __init__(self, client: Any, *, provider_name: str = "openai-compatible") -> None:
        self.client = client
        self.provider_name = provider_name

    @property
    def available(self) -> bool:
        return True

    def suggest(self, context: dict[str, Any]) -> CorrectionSuggestionResult:
        schema = {
            "type": "object",
            "additionalProperties": False,
            "required": ["proposedText", "explanation", "evidenceIds", "alternatives", "warnings"],
            "properties": {
                "proposedText": {"type": "string"},
                "explanation": {"type": "string"},
                "evidenceIds": {"type": "array", "items": {"type": "string"}},
                "warnings": {"type": "array", "items": {"type": "string"}},
                "alternatives": {
                    "type": "array", "maxItems": 3,
                    "items": {
                        "type": "object", "additionalProperties": False,
                        "required": ["proposedText", "explanation", "evidenceIds"],
                        "properties": {
                            "proposedText": {"type": "string"},
                            "explanation": {"type": "string"},
                            "evidenceIds": {"type": "array", "items": {"type": "string"}},
                        },
                    },
                },
            },
        }
        instructions = (
            "Propose target-language correction wording for the confirmed QA issue. "
            "Repair only the failed semantic dimension, preserve unaffected meaning, and "
            "make the smallest defensible change without stylistically rewriting the verse. "
            "Preserve the target language's natural grammar and word order; verse numbers "
            "are reference anchors, not semantic boundaries. Use only the supplied evidence. "
            "Do not claim to edit Scripture, approve the proposal, or change versification. "
            "If evidence is insufficient, return an empty proposedText and explain why."
        )
        reference = str(
            (context.get("currentTarget") or {}).get("displayedReference") or ""
        )
        self.client.last_privacy_manifest = ai_payload_manifest(reference, context)
        result = self.client._post_structured(
            instructions, json.dumps(context, ensure_ascii=False),
            "bridge_correction_wording_v1", schema,
        )
        fingerprint = hashlib.sha256(
            json.dumps(result, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        alternatives = tuple(CorrectionWordingAlternative(
            proposed_text=str(item.get("proposedText") or ""),
            explanation=str(item.get("explanation") or ""),
            evidence_ids=tuple(str(x) for x in item.get("evidenceIds") or ()),
        ) for item in result.get("alternatives") or ())
        return CorrectionSuggestionResult(
            proposed_text=str(result.get("proposedText") or ""),
            explanation=str(result.get("explanation") or ""),
            evidence_ids=tuple(str(x) for x in result.get("evidenceIds") or ()),
            alternatives=alternatives,
            provider_name=self.provider_name,
            model=str(getattr(self.client, "model", "")),
            prompt_policy_version=CORRECTION_WORDING_POLICY_VERSION,
            response_fingerprint=fingerprint,
            warnings=tuple(str(x) for x in result.get("warnings") or ()),
        )


class CorrectionWordingService:
    def __init__(
        self, runtime: Any,
        provider: CorrectionSuggestionProvider | None = None,
    ) -> None:
        self.runtime = runtime
        self.repository = runtime.repository
        self.eligibility = runtime.correction_eligibility
        self.provider = provider or NoCorrectionSuggestionProvider()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _require_eligible(result: Any) -> None:
        if result.eligible:
            return
        codes = {
            str(getattr(getattr(reason, "code", ""), "value", getattr(reason, "code", "")))
            for reason in result.reasons
        }
        details = "; ".join(
            str(getattr(reason, "detail", "")) for reason in result.reasons
        )
        if codes & {"TARGET_TEXT_CHANGED", "SPAN_TEXT_MISMATCH", "TARGET_REFERENCE_MISSING"}:
            raise FoundationConflict(
                f"Correction target revision conflict: {details or 'current target changed'}"
            )
        raise FoundationValidationError(
            f"Correction proposal is not eligible: {details or 'eligibility check failed'}"
        )

    def _validate_intent(self, finding_id: str, intent: CorrectionIntent) -> dict[str, Any]:
        span = intent.affected_target_span
        if len(span.canonical_references) != 1:
            raise FoundationValidationError(
                "Stage 9B.1 requires one exact target span; multi-reference or disjoint "
                "corrections need passage review."
            )
        current = self.eligibility.validate_current_text(
            displayed_reference=span.displayed_reference,
            expected_target_revision=span.target_text_revision,
            expected_target_content_hash=span.target_content_hash,
            expected_span_text=span.original_text,
            start_code_point=span.start_code_point,
            end_code_point=span.end_code_point,
        )
        if not current.valid:
            detail = "; ".join(reason.detail for reason in current.reasons)
            raise FoundationConflict(f"Correction target revision conflict: {detail}")
        context = self.runtime.qa_review.get_finding(finding_id)
        finding = context.get("finding") or {}
        allowed_units = set(str(x) for x in finding.get("sourceSemanticUnitIds") or ())
        supplied_units = set(intent.affected_source_semantic_unit_ids)
        if supplied_units - allowed_units:
            raise FoundationValidationError(
                "Correction intent refers to source semantic units outside the finding"
            )
        return context

    @staticmethod
    def _location_ids(context: dict[str, Any]) -> tuple[str, ...]:
        ids: list[str] = []
        for item in context.get("location") or ():
            relationship = item.get("location") if isinstance(item, dict) else None
            if isinstance(relationship, dict) and relationship.get("id"):
                ids.append(str(relationship["id"]))
        return tuple(dict.fromkeys(ids))

    @staticmethod
    def _meaning_ids(context: dict[str, Any]) -> tuple[str, ...]:
        ids: list[str] = []
        for item in context.get("meaning") or ():
            assessment = item.get("assessment") if isinstance(item, dict) else None
            if isinstance(assessment, dict) and assessment.get("id"):
                ids.append(str(assessment["id"]))
        return tuple(dict.fromkeys(ids))

    @staticmethod
    def _allowed_evidence_ids(context: dict[str, Any]) -> tuple[str, ...]:
        finding = context.get("finding") or {}
        ids = [str(x) for x in finding.get("evidenceIds") or ()]
        for key in ("supportingEvidence", "conflictingEvidence", "resources"):
            for item in context.get(key) or ():
                if isinstance(item, dict) and item.get("id"):
                    ids.append(str(item["id"]))
        return tuple(dict.fromkeys(ids))

    def _provider_context(
        self, finding_id: str, intent: CorrectionIntent, context: dict[str, Any],
    ) -> dict[str, Any]:
        span = intent.affected_target_span
        target_snapshot = self.eligibility.current_text_snapshot()
        finding = context.get("finding") or {}
        passage_references = tuple(
            str(item) for item in finding.get("displayedReferences") or ()
        )
        return {
            "findingId": finding_id,
            "intent": to_wire(intent),
            "currentTarget": {
                "displayedReference": span.displayed_reference,
                "verseText": target_snapshot.get(span.displayed_reference, ""),
                "affectedText": span.original_text,
                "startCodePoint": span.start_code_point,
                "endCodePoint": span.end_code_point,
            },
            "targetPassageContext": {
                reference: target_snapshot[reference]
                for reference in passage_references if reference in target_snapshot
            },
            "finding": finding,
            "sourceSemanticUnits": (
                context.get("sourceSemanticUnits") or context.get("source") or []
            ),
            "targetSemanticUnits": (
                context.get("targetSemanticUnits") or context.get("target") or []
            ),
            "locations": context.get("location") or [],
            "meaningAssessments": context.get("meaning") or [],
            "coverage": context.get("coverage") or [],
            "resourceEvidence": context.get("resources") or [],
            "supportingEvidence": context.get("supportingEvidence") or [],
            "conflictingEvidence": context.get("conflictingEvidence") or [],
            "policyVersion": CORRECTION_WORDING_POLICY_VERSION,
        }

    def _build_proposal(
        self, *, finding_id: str, intent: CorrectionIntent, context: dict[str, Any],
        human_proposed_text: str, explanation: str, request_suggestion: bool,
        actor_id: str, supersedes_proposal_id: str | None = None,
    ) -> CorrectionProposalV2:
        proposed_text = human_proposed_text
        result: CorrectionSuggestionResult | None = None
        warnings: list[str] = []
        if request_suggestion and self.provider.available:
            result = self.provider.suggest(self._provider_context(finding_id, intent, context))
            proposed_text = result.proposed_text
            explanation = result.explanation
            warnings.extend(result.warnings)
        elif request_suggestion:
            if not proposed_text:
                raise FoundationValidationError(
                    "Correction suggestion provider is unavailable and no human wording was supplied"
                )
            warnings.append("PROVIDER_UNAVAILABLE")
        if not proposed_text:
            raise FoundationValidationError("Correction proposal wording must not be empty")

        allowed_evidence_ids = self._allowed_evidence_ids(context)
        allowed_evidence = set(allowed_evidence_ids)
        evidence_ids = result.evidence_ids if result is not None else allowed_evidence_ids
        if set(evidence_ids) - allowed_evidence:
            raise FoundationValidationError(
                "Correction suggestion cited evidence outside the reviewed finding"
            )
        mode = (
            CorrectionCreationMode.MACHINE_SUGGESTED
            if result is not None else CorrectionCreationMode.HUMAN_AUTHORED
        )
        provider_metadata = None
        alternatives: tuple[CorrectionWordingAlternative, ...] = ()
        if result is not None:
            provider_metadata = CorrectionProviderMetadata(
                provider_name=result.provider_name, model=result.model,
                model_version_id=result.model_version_id,
                prompt_policy_version=result.prompt_policy_version,
                response_fingerprint=result.response_fingerprint,
            )
            alternatives = tuple(CorrectionWordingAlternative(
                proposed_text=item.proposed_text,
                explanation=item.explanation,
                evidence_ids=item.evidence_ids,
                creation_mode=CorrectionCreationMode.MACHINE_SUGGESTED,
                provider_metadata=provider_metadata,
            ) for item in result.alternatives)
            for alternative in alternatives:
                if set(alternative.evidence_ids) - allowed_evidence:
                    raise FoundationValidationError(
                        "Correction alternative cited evidence outside the reviewed finding"
                    )
        finding = context.get("finding") or {}
        span = intent.affected_target_span
        policy = finding.get("policyBinding") or {}
        policy_binding = (
            PolicyBinding(
                confidence_policy_version=str(policy["confidencePolicyVersion"]),
                calibration_version=str(policy["calibrationVersion"]),
                audit_policy_version=str(policy["auditPolicyVersion"]),
            )
            if all(key in policy for key in (
                "confidencePolicyVersion", "calibrationVersion", "auditPolicyVersion",
            ))
            else PolicyBinding.foundation_v1()
        )
        return CorrectionProposalV2(
            id=str(uuid.uuid4()), qa_finding_id=finding_id,
            project_id=self.runtime.project_id, intent=intent,
            affected_references=span.canonical_references,
            current_text=span.original_text, proposed_text=proposed_text,
            explanation=explanation,
            evidence_ids=tuple(evidence_ids),
            semantic_relationship_ids=tuple(
                str(x) for x in finding.get("semanticRelationshipIds") or ()),
            meaning_assessment_ids=self._meaning_ids(context),
            created_by=actor_id, created_at=self._now(), creation_mode=mode,
            policy_binding=policy_binding,
            review_status=(
                ReviewStatus.AI_PROPOSED if result is not None else ReviewStatus.UNREVIEWED
            ),
            lifecycle_status=LifecycleStatus.ACTIVE,
            alternatives=alternatives, provider_metadata=provider_metadata,
            warnings=tuple(warnings),
            original_suggested_text=(result.proposed_text if result is not None else None),
            location_relationship_ids=self._location_ids(context),
            supersedes_proposal_id=supersedes_proposal_id,
        )

    def create_proposal(
        self, *, finding_id: str, intent: CorrectionIntent,
        human_proposed_text: str = "", explanation: str = "",
        request_suggestion: bool = False, actor_id: str = "human",
    ) -> dict[str, Any]:
        self._require_eligible(self.eligibility.evaluate(finding_id))
        context = self._validate_intent(finding_id, intent)
        proposal = self._build_proposal(
            finding_id=finding_id, intent=intent, context=context,
            human_proposed_text=human_proposed_text, explanation=explanation,
            request_suggestion=request_suggestion, actor_id=actor_id,
        )
        # A provider call may take seconds. Re-check both eligibility and the
        # byte-exact span after it returns, immediately before persistence.
        self._require_eligible(self.eligibility.evaluate(finding_id))
        self._validate_intent(finding_id, intent)
        self.repository.save_correction_proposal_v2(proposal)
        return self.repository.correction_proposal(proposal.id)

    def edit_proposal(
        self, proposal_id: str, *, proposed_text: str, expected_revision: int,
        actor_id: str = "human", explanation: str = "",
    ) -> dict[str, Any]:
        if not proposed_text:
            raise FoundationValidationError("Correction proposal wording must not be empty")
        current = self.repository.correction_proposal(proposal_id)
        if str(current.get("lifecycleStatus") or "") != LifecycleStatus.ACTIVE.value:
            raise FoundationValidationError("Only an active current proposal may be edited")
        self._require_eligible(self.eligibility.evaluate(
            str(current["qaFindingId"]), ignore_proposal_ids=(proposal_id,),
        ))
        intent = self._intent_from_wire(current["intent"])
        self._validate_intent(str(current["qaFindingId"]), intent)
        previous_mode = str(current.get("creationMode") or "")
        mode = (
            CorrectionCreationMode.MACHINE_SUGGESTED_HUMAN_EDITED
            if previous_mode in {
                CorrectionCreationMode.MACHINE_SUGGESTED.value,
                CorrectionCreationMode.AI_GENERATED.value,
                CorrectionCreationMode.MACHINE_SUGGESTED_HUMAN_EDITED.value,
            }
            else CorrectionCreationMode.HUMAN_AUTHORED
        )
        return self.repository.update_correction_proposal_wording(
            proposal_id, proposed_text=proposed_text,
            explanation=explanation or str(current.get("explanation") or ""),
            creation_mode=mode.value, review_status=ReviewStatus.HUMAN_MODIFIED,
            expected_revision=expected_revision, actor_id=actor_id,
        )

    def reject_proposal(
        self, proposal_id: str, *, expected_revision: int,
        actor_id: str = "human", reason: str = "",
    ) -> dict[str, Any]:
        return self.repository.reject_correction_proposal(
            proposal_id, expected_revision=expected_revision,
            actor_id=actor_id, reason=reason,
        )

    def regenerate_proposal(
        self, proposal_id: str, *, expected_revision: int,
        actor_id: str = "human",
    ) -> dict[str, Any]:
        current = self.repository.correction_proposal(proposal_id)
        finding_id = str(current["qaFindingId"])
        self._require_eligible(self.eligibility.evaluate(
            finding_id, ignore_proposal_ids=(proposal_id,),
        ))
        intent = self._intent_from_wire(current["intent"])
        context = self._validate_intent(finding_id, intent)
        if not self.provider.available:
            raise FoundationValidationError("Correction suggestion provider is unavailable")
        replacement = self._build_proposal(
            finding_id=finding_id, intent=intent, context=context,
            human_proposed_text="", explanation="", request_suggestion=True,
            actor_id=actor_id, supersedes_proposal_id=proposal_id,
        )
        self._require_eligible(self.eligibility.evaluate(
            finding_id, ignore_proposal_ids=(proposal_id,),
        ))
        self._validate_intent(finding_id, intent)
        return self.repository.supersede_and_save_correction_proposal(
            proposal_id, expected_revision=expected_revision,
            replacement=replacement, actor_id=actor_id,
        )

    @staticmethod
    def _intent_from_wire(value: dict[str, Any]) -> CorrectionIntent:
        try:
            span = value["affectedTargetSpan"]
            return CorrectionIntent(
                failed_dimension=CoverageDimension(str(value["failedDimension"])),
                observed_meaning=str(value.get("observedMeaning") or ""),
                required_meaning=str(value.get("requiredMeaning") or ""),
                affected_source_semantic_unit_ids=tuple(
                    str(x) for x in value.get("affectedSourceSemanticUnitIds") or ()),
                affected_target_span=AffectedTargetSpan(
                    displayed_reference=str(span["displayedReference"]),
                    canonical_references=tuple(str(x) for x in span["canonicalReferences"]),
                    start_code_point=int(span["startCodePoint"]),
                    end_code_point=int(span["endCodePoint"]),
                    original_text=str(span.get("originalText") or ""),
                    target_text_revision=str(span["targetTextRevision"]),
                    target_content_hash=str(span["targetContentHash"]),
                ),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise FoundationValidationError(f"Invalid CorrectionIntent: {exc}") from exc
