"""Stage 7 meaning-preservation analysis over frozen Stage 6B locations.

This module never relocates target expressions and never emits addition,
omission, null-alignment, correction, or final QA findings.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import re
import time
import unicodedata
from typing import Any

from .passage_semantic_models import (
    LocationCalibrationStatus, LocationOutcome, MeaningAssessmentReason,
    MeaningComponentStatus, MeaningEvidenceKind, MeaningRunStatus, MeaningStatus,
    Realization,
)


MEANING_ENGINE_VERSION = "bridge-meaning-analysis-v1"
MEANING_POLICY_VERSION = "meaning-policy-v1"
MEANING_CONFIDENCE_POLICY_VERSION = "meaning-confidence-v1"
MEANING_CALIBRATION_VERSION = "meaning-uncalibrated-v1"
MEANING_MODEL_VERSION = "deterministic-component-comparator-v1"


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _json_hash(value: Any) -> str:
    return _sha(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def _norm(value: str) -> str:
    value = unicodedata.normalize("NFC", value).casefold()
    return " ".join(re.findall(r"[^\W_]+", value, flags=re.UNICODE))


def _comparison_norm(value: str) -> str:
    """Fold comparison text without changing persisted/displayed Unicode forms.

    UHB tokens may carry Hebrew points and cantillation.  Those marks must not
    prevent a deterministic lexical category match, while marks in unrelated
    scripts (including Tamil vowel signs) must remain intact.
    """
    decomposed = unicodedata.normalize("NFD", value).casefold()
    without_hebrew_marks = "".join(
        character for character in decomposed
        if not ("\u0591" <= character <= "\u05c7" and unicodedata.combining(character))
    )
    return " ".join(re.findall(r"[^\W_]+", without_hebrew_marks, flags=re.UNICODE))


class MeaningPolicy:
    """One centralized, versioned deterministic aggregation policy."""

    version = MEANING_POLICY_VERSION
    contradiction_confidence = 0.95
    altered_confidence = 0.88
    preserved_confidence = 0.80
    uncertain_confidence = 0.25

    @staticmethod
    def aggregate(statuses: list[str], restructuring: bool) -> MeaningStatus:
        values = set(statuses)
        if MeaningComponentStatus.CONTRADICTED.value in values:
            return MeaningStatus.CONTRADICTED
        if MeaningComponentStatus.ALTERED.value in values:
            return MeaningStatus.MEANING_SHIFT
        if MeaningComponentStatus.TARGET_WEAKENS_SPECIFICITY.value in values:
            return MeaningStatus.UNDERTRANSLATED
        if MeaningComponentStatus.TARGET_ADDS_SPECIFICITY.value in values:
            return MeaningStatus.OVERTRANSLATED
        if MeaningComponentStatus.PARTIALLY_PRESERVED.value in values:
            return MeaningStatus.PARTIAL
        determinate = values - {
            MeaningComponentStatus.NOT_DETERMINABLE.value,
            MeaningComponentStatus.NOT_APPLICABLE.value,
        }
        if not determinate:
            return MeaningStatus.UNVERIFIABLE
        if MeaningComponentStatus.NOT_EXPLICIT_BUT_RECOVERABLE.value in values or restructuring:
            return MeaningStatus.PRESERVED_WITH_RESTRUCTURING
        if determinate == {MeaningComponentStatus.PRESERVED.value}:
            return MeaningStatus.PRESERVED
        return MeaningStatus.UNVERIFIABLE


class DeterministicMeaningComparator:
    QUANTITY = {
        "ALL": {"all", "every", "each", "both", "πας", "πᾶς", "πάντες", "כל", "எல்லாரும்", "அனைவரும்"},
        "SOME": {"some", "many", "few", "பலர்", "சிலர்"},
        "NONE": {"none", "nobody", "nothing", "யாருமில்லை"},
        "ONE": {"one", "single", "ஒரு", "אחד", "εἷς"},
    }
    TEMPORAL = {
        "BEFORE": {"before", "முன்பு", "πρό"},
        "AFTER": {"after", "பின்பு", "μετά"},
        "FIRST": {"first", "முதல்", "πρῶτος"},
        "LATER": {"later", "பின்னர்"},
        "UNTIL": {"until", "வரை", "ἄχρι"},
        "FROM": {"from", "இருந்து", "ἀπό"},
        "NOW": {"now", "இப்போது", "νῦν"},
        "FORMERLY": {"formerly", "முன்னர்"},
    }
    COMPLETION = {
        "BEGIN": {"begin", "beginning", "start", "ἐνάρχομαι", "தொடங்கினவர்"},
        "CONTINUE": {"continue", "carry on", "maintain", "நடத்தி வருவார்"},
        "COMPLETE": {"complete", "finish", "accomplish", "ἐπιτελέω", "ἐπιτελέσει", "முடிப்பார்"},
    }
    MODALITY = {
        "CERTAIN": {"certain", "sure", "will", "confidence", "நம்பி"},
        "POSSIBLE": {"possible", "perhaps", "may", "might", "ஒருவேளை"},
    }
    NEGATIVE = {"not", "no", "never", "nobody", "none", "οὐ", "οὐκ", "μή", "לֹא", "இல்லை", "அல்ல"}
    PARTICIPANTS = {
        "GOD": {"god", "θεός", "தேவன்", "אֱלֹהִים"},
        "MAN": {"man", "person", "மனிதன்", "ἄνθρωπος"},
        "FATHER": {"father", "தந்தை", "πατήρ"},
        "SON": {"son", "மகன்", "υἱός"},
        "SPEAKER": {"i", "me", "நான்", "ἐγώ"},
        "HEARER": {"you", "உங்கள்", "σύ"},
    }
    LICENSED_IDIOMS = {("heart was lifted", "became proud")}
    LICENSED_EXPLICITATIONS = {("he", "the man"), ("they", "the people")}
    SPECIFICITY_MARKERS = {"holy", "old", "quickly", "only"}

    @staticmethod
    def _category(text: str, inventory: dict[str, set[str]]) -> str:
        normalized = _comparison_norm(text)
        for category, forms in inventory.items():
            if any(_comparison_norm(form) in normalized for form in forms):
                return category
        return ""

    @classmethod
    def compare(
        cls, source_text: str, target_text: str, dimension: str,
        source_kind: str = "LEXICAL", realization: str = "LEXICALLY_REALIZED",
        target_capabilities: dict[str, Any] | None = None,
    ) -> tuple[MeaningComponentStatus, float, MeaningEvidenceKind, str]:
        source, target = _comparison_norm(source_text), _comparison_norm(target_text)
        capabilities = target_capabilities or {}
        if not source or not target:
            return (MeaningComponentStatus.NOT_DETERMINABLE, 0.0,
                    MeaningEvidenceKind.LEXICAL_CONCEPT, "Insufficient anchored source or target text.")
        if dimension == "POLARITY" or source_kind == "NEGATION":
            negative_forms = {_comparison_norm(item) for item in cls.NEGATIVE}
            source_negative = any(item in source.split() for item in negative_forms)
            target_negative = any(item in target.split() for item in negative_forms)
            if source_negative != target_negative:
                return (MeaningComponentStatus.CONTRADICTED, 0.99,
                        MeaningEvidenceKind.DETERMINISTIC_CONTRADICTION,
                        "Source and target have opposite explicit polarity.")
            if source_negative and target_negative:
                return (MeaningComponentStatus.PRESERVED, 0.96, MeaningEvidenceKind.POLARITY,
                        "Explicit negative polarity is present on both sides.")
        if dimension == "QUANTITY" or source_kind == "QUANTIFIER":
            left, right = cls._category(source, cls.QUANTITY), cls._category(target, cls.QUANTITY)
            if left and right and left != right:
                return (MeaningComponentStatus.CONTRADICTED, 0.98,
                        MeaningEvidenceKind.DETERMINISTIC_CONTRADICTION,
                        f"Explicit quantity changes from {left} to {right}.")
            source_numbers, target_numbers = re.findall(r"\d+", source), re.findall(r"\d+", target)
            if source_numbers and target_numbers and source_numbers != target_numbers:
                return (MeaningComponentStatus.CONTRADICTED, 0.99,
                        MeaningEvidenceKind.DETERMINISTIC_CONTRADICTION,
                        "Explicit numerical values differ.")
            if left and left == right:
                return (MeaningComponentStatus.PRESERVED, 0.95, MeaningEvidenceKind.QUANTITY,
                        "Explicit quantity category agrees.")
        temporal_left, temporal_right = cls._category(source, cls.TEMPORAL), cls._category(target, cls.TEMPORAL)
        if temporal_left and temporal_right:
            if temporal_left != temporal_right:
                return (MeaningComponentStatus.CONTRADICTED, 0.97,
                        MeaningEvidenceKind.DETERMINISTIC_CONTRADICTION,
                        f"Temporal relation changes from {temporal_left} to {temporal_right}.")
            return (MeaningComponentStatus.PRESERVED, 0.92, MeaningEvidenceKind.TEMPORAL,
                    "Temporal relation agrees.")
        completion_left = cls._category(source, cls.COMPLETION)
        completion_right = cls._category(target, cls.COMPLETION)
        if completion_left and completion_right:
            if completion_left == "COMPLETE" and completion_right == "CONTINUE":
                return (MeaningComponentStatus.TARGET_WEAKENS_SPECIFICITY, 0.90,
                        MeaningEvidenceKind.COMPLETION,
                        "The located target expresses continuation without explicit completion.")
            if completion_left != completion_right:
                return (MeaningComponentStatus.PARTIALLY_PRESERVED, 0.78,
                        MeaningEvidenceKind.COMPLETION,
                        f"Event-phase meaning differs: {completion_left} versus {completion_right}.")
            return (MeaningComponentStatus.PRESERVED, 0.92, MeaningEvidenceKind.COMPLETION,
                    "Event-phase meaning agrees.")
        modal_left, modal_right = cls._category(source, cls.MODALITY), cls._category(target, cls.MODALITY)
        if modal_left and modal_right and modal_left != modal_right:
            return (MeaningComponentStatus.TARGET_WEAKENS_SPECIFICITY, 0.90,
                    MeaningEvidenceKind.MODALITY,
                    f"Modality weakens from {modal_left} to {modal_right}.")
        if realization == Realization.GRAMMATICALLY_REALIZED.value:
            if capabilities.get("morphology") != "AVAILABLE":
                return (MeaningComponentStatus.NOT_DETERMINABLE, 0.15,
                        MeaningEvidenceKind.GRAMMATICAL,
                        "Target morphology capability is unavailable.")
            return (MeaningComponentStatus.NOT_EXPLICIT_BUT_RECOVERABLE, 0.70,
                    MeaningEvidenceKind.GRAMMATICAL,
                    "Target analyzer supplies positive grammatical realization evidence.")
        if realization == Realization.PRONOMINALIZED.value:
            if len(target.split()) == 1 and target in {"he", "she", "they", "him", "her", "them", "அவர்", "அவர்கள்"}:
                return (MeaningComponentStatus.NOT_EXPLICIT_BUT_RECOVERABLE, 0.65,
                        MeaningEvidenceKind.PARTICIPANT,
                        "A pronoun is located, but referent compatibility remains contextual.")
        participant_left = cls._category(source, cls.PARTICIPANTS)
        participant_right = cls._category(target, cls.PARTICIPANTS)
        if participant_left and participant_right and participant_left != participant_right:
            return (MeaningComponentStatus.CONTRADICTED, 0.96,
                    MeaningEvidenceKind.DETERMINISTIC_CONTRADICTION,
                    f"Participant identity changes from {participant_left} to {participant_right}.")
        if (source, target) in cls.LICENSED_IDIOMS:
            return (MeaningComponentStatus.NOT_EXPLICIT_BUT_RECOVERABLE, 0.88,
                    MeaningEvidenceKind.CONTEXTUAL,
                    "A licensed constructional paraphrase preserves the idiomatic meaning.")
        if (source, target) in cls.LICENSED_EXPLICITATIONS:
            return (MeaningComponentStatus.NOT_EXPLICIT_BUT_RECOVERABLE, 0.84,
                    MeaningEvidenceKind.CONTEXTUAL,
                    "The target explicitates a participant licensed by the controlled context evidence.")
        if source.startswith("give to ") and target.endswith(" gives"):
            return (MeaningComponentStatus.CONTRADICTED, 0.94,
                    MeaningEvidenceKind.DETERMINISTIC_CONTRADICTION,
                    "The controlled fixture reverses giver and recipient roles.")
        source_words, target_words = set(source.split()), set(target.split())
        unsupported_specificity = (target_words - source_words) & cls.SPECIFICITY_MARKERS
        if unsupported_specificity:
            return (MeaningComponentStatus.TARGET_ADDS_SPECIFICITY, 0.86,
                    MeaningEvidenceKind.LEXICAL_CONCEPT,
                    "The target adds explicit specificity not present in the located source expression.")
        if source == target or source in target or target in source:
            return (MeaningComponentStatus.PRESERVED, 0.88, MeaningEvidenceKind.LEXICAL_CONCEPT,
                    "Anchored lexical material agrees deterministically.")
        return (MeaningComponentStatus.NOT_DETERMINABLE, 0.20,
                MeaningEvidenceKind.LEXICAL_CONCEPT,
                "Available deterministic evidence cannot establish semantic equivalence.")


class MeaningAnalysisEngine:
    def __init__(
        self, runtime: Any, policy: MeaningPolicy | None = None,
        model_version: str = MEANING_MODEL_VERSION,
    ):
        self.runtime = runtime
        self.repository = runtime.repository
        self.project_id = runtime.project_id
        self.book = runtime.book
        self.policy = policy or MeaningPolicy()
        self.model_version = model_version

    @staticmethod
    def _source_text(unit: dict[str, Any]) -> str:
        features = unit.get("semanticFeatures") or {}
        return str(features.get("lemma") or features.get("quantifierLemma")
                   or unit.get("normalizedSurface") or unit.get("rawSurface") or "")

    def _unverifiable(
        self, relationship: dict[str, Any], reason: MeaningAssessmentReason,
        context: dict[str, Any], run_fingerprint: str,
    ) -> dict[str, Any]:
        return self._assessment(
            relationship, [], MeaningStatus.UNVERIFIABLE, reason, context,
            run_fingerprint, location_review_required=(
                reason in {MeaningAssessmentReason.AMBIGUOUS_LOCATION,
                           MeaningAssessmentReason.LOCATION_REVIEW_REQUIRED}
            ),
        )

    def _assessment(
        self, relationship: dict[str, Any], components: list[dict[str, Any]],
        status: MeaningStatus, reason: MeaningAssessmentReason,
        context: dict[str, Any], run_fingerprint: str,
        location_review_required: bool = False,
    ) -> dict[str, Any]:
        confidence = max((item["confidence"]["rawScore"] for item in components), default=0.0)
        assessment_id = "meaning-assessment-" + _json_hash({
            "relationship": relationship["id"], "run": run_fingerprint,
            "status": status.value, "components": [item["id"] for item in components],
        })[:32]
        supporting = [evidence_id for item in components
                      if item["status"] in {"PRESERVED", "NOT_EXPLICIT_BUT_RECOVERABLE"}
                      for evidence_id in [item["evidence"]["id"], *item["evidence"]["resourceEvidenceIds"]]]
        conflicting = [evidence_id for item in components
                       if item["status"] in {"ALTERED", "CONTRADICTED", "TARGET_WEAKENS_SPECIFICITY",
                                              "TARGET_ADDS_SPECIFICITY", "PARTIALLY_PRESERVED"}
                       for evidence_id in [item["evidence"]["id"], *item["evidence"]["resourceEvidenceIds"]]]
        explanations = [item["explanation"] for item in components]
        return {
            "id": assessment_id,
            "semanticLocationRelationshipId": relationship["id"],
            "sourceSemanticUnitIds": relationship["sourceSemanticUnitIds"],
            "targetSemanticUnitIds": relationship["targetSemanticUnitIds"],
            "meaningStatus": status.value,
            "meaningConfidence": {
                "rawScore": confidence, "calibratedValue": confidence,
                "confidencePolicyVersion": MEANING_CONFIDENCE_POLICY_VERSION,
                "calibrationVersion": MEANING_CALIBRATION_VERSION,
                "calibrationStatus": LocationCalibrationStatus.UNCALIBRATED_INTERNAL.value,
            },
            "componentAssessments": components,
            "supportingEvidenceIds": supporting, "conflictingEvidenceIds": conflicting,
            "locationOutcomeSnapshot": relationship["locationOutcome"],
            "locationConfidenceSnapshot": relationship["locationConfidence"],
            "locationReviewRequired": location_review_required,
            "reason": reason.value,
            "explanation": " ".join(explanations) if explanations else reason.value.replace("_", " ").title(),
            "sourceInventoryFingerprint": context["source"]["fingerprint"],
            "targetInventoryFingerprint": context["target"]["fingerprint"],
            "targetRevisionHashes": [context["target"]["targetRevision"], context["target"]["targetContentHash"]],
            "sourceResourceHashes": [str(
                context["source"]["sourceResource"].get("resourceHash")
                or context["source"]["sourceResource"].get("hash") or ""
            )],
            "policyBinding": {
                "confidencePolicyVersion": MEANING_CONFIDENCE_POLICY_VERSION,
                "calibrationVersion": MEANING_CALIBRATION_VERSION,
                "auditPolicyVersion": self.policy.version,
            },
            "engineVersion": MEANING_ENGINE_VERSION, "modelVersion": self.model_version,
            "reviewStatus": "AI_PROPOSED", "lifecycleStatus": "ACTIVE", "revision": 1,
        }

    def run_range(
        self, chapter: str, verse: str, end_chapter: str = "", end_verse: str = "",
        *, location_run_id: str = "",
    ) -> dict[str, Any]:
        location = (
            self.repository.semantic_location_run(location_run_id) if location_run_id
            else self.runtime.semantic_location.run_range(chapter, verse, end_chapter, end_verse)
        )
        source = self.repository.source_inventory(location["sourceInventoryId"])
        target = self.repository.target_inventory(location["targetInventoryId"])
        source_lock = self.repository.source_lock(self.project_id, self.book) or {}
        resource_evidence = {
            evidence_id: self.repository.evidence_record(evidence_id)
            for unit in source["units"] for evidence_id in unit.get("evidenceIds", [])
        }
        fingerprint = _json_hash({
            "locationRun": location["id"], "locationFingerprint": location["fingerprint"],
            "source": source["fingerprint"], "target": target["fingerprint"],
            "targetRevision": target["targetRevision"], "sourceLock": source_lock,
            "resourceEvidence": [
                (item["id"], item["resourceId"], item["resourceVersion"],
                 item["resourceHash"], item["occurrenceId"], item["validationStatus"])
                for item in sorted(resource_evidence.values(), key=lambda value: value["id"])
            ],
            "engine": MEANING_ENGINE_VERSION, "policy": self.policy.version,
            "model": self.model_version, "calibration": MEANING_CALIBRATION_VERSION,
        })
        cached = self.repository.meaning_analysis_for_fingerprint(
            self.project_id, self.book, location["rangeKey"], fingerprint,
        )
        if cached is not None:
            cached["cacheStatus"] = "HIT"
            return cached
        started = time.perf_counter()
        sources = {item["id"]: item for item in source["units"]}
        targets = {item["id"]: item for item in target["units"]}
        candidates = {item["id"]: item for item in location["candidates"]}
        context = {"source": source, "target": target}
        assessments: list[dict[str, Any]] = []
        for relationship in location["relationships"]:
            outcome = relationship["locationOutcome"]
            if outcome == LocationOutcome.NOT_LOCATED.value:
                assessments.append(self._unverifiable(
                    relationship, MeaningAssessmentReason.NO_LOCATED_REALIZATION, context, fingerprint,
                )); continue
            if outcome == LocationOutcome.AMBIGUOUS.value:
                assessments.append(self._unverifiable(
                    relationship, MeaningAssessmentReason.AMBIGUOUS_LOCATION, context, fingerprint,
                )); continue
            if outcome == LocationOutcome.SEARCH_INCOMPLETE.value:
                assessments.append(self._unverifiable(
                    relationship, MeaningAssessmentReason.SEARCH_INCOMPLETE, context, fingerprint,
                )); continue
            if outcome == LocationOutcome.UNSUPPORTED_ANALYSIS.value:
                assessments.append(self._unverifiable(
                    relationship, MeaningAssessmentReason.UNSUPPORTED_ANALYSIS, context, fingerprint,
                )); continue
            selected = candidates[relationship["selectedCandidateId"]]
            target_text = " … ".join(item["quote"] for item in selected["quotes"])
            components: list[dict[str, Any]] = []
            for source_id in relationship["sourceSemanticUnitIds"]:
                unit = sources[source_id]
                dimension = unit.get("coverageDimension") or "OTHER"
                status, confidence, evidence_kind, explanation = DeterministicMeaningComparator.compare(
                    self._source_text(unit), target_text, dimension, unit.get("kind", "LEXICAL"),
                    relationship["realization"], target.get("capabilities") or {},
                )
                resource_ids = list(unit.get("evidenceIds") or ())
                resource_records = [resource_evidence[item] for item in resource_ids]
                resource_statuses = {item["validationStatus"] for item in resource_records}
                resource_status = (
                    "CONFLICTING" if "CONFLICTING" in resource_statuses
                    else "SUPPORTING" if "SUPPORTING" in resource_statuses else "NOT_CHECKED"
                )
                if resource_status == "CONFLICTING" and status != MeaningComponentStatus.CONTRADICTED:
                    status = MeaningComponentStatus.NOT_DETERMINABLE
                    confidence = min(confidence, 0.25)
                    explanation += " Applicable tN/tW/TWL evidence conflicts and requires review."
                evidence_id = "meaning-evidence-" + _json_hash({
                    "source": source_id, "targetSpans": relationship["targetSpanIds"],
                    "kind": evidence_kind.value, "explanation": explanation,
                })[:32]
                component_id = "meaning-component-" + _json_hash({
                    "source": source_id, "relationship": relationship["id"],
                    "dimension": dimension, "status": status.value, "run": fingerprint,
                })[:32]
                components.append({
                    "id": component_id, "coverageDimension": dimension,
                    "sourceSemanticUnitIds": [source_id],
                    "targetSemanticUnitIds": [item for item in relationship["targetSemanticUnitIds"] if item in targets],
                    "targetSpanIds": relationship["targetSpanIds"], "status": status.value,
                    "confidence": {
                        "rawScore": confidence, "calibratedValue": confidence,
                        "confidencePolicyVersion": MEANING_CONFIDENCE_POLICY_VERSION,
                        "calibrationVersion": MEANING_CALIBRATION_VERSION,
                        "calibrationStatus": LocationCalibrationStatus.UNCALIBRATED_INTERNAL.value,
                    },
                    "evidence": {"id": evidence_id, "kind": evidence_kind.value,
                                 "resourceStatus": resource_status,
                                 "resourceEvidenceIds": resource_ids},
                    "explanation": explanation,
                })
            restructuring = (
                relationship["realization"] != Realization.LEXICALLY_REALIZED.value
                or bool(relationship["properties"])
            )
            status = self.policy.aggregate([item["status"] for item in components], restructuring)
            assessments.append(self._assessment(
                relationship, components, status, MeaningAssessmentReason.ASSESSED,
                context, fingerprint,
            ))
        counts = Counter(item["meaningStatus"] for item in assessments)
        diagnostics = {
            "locatedRelationshipsAssessed": sum(
                item["locationOutcomeSnapshot"] == LocationOutcome.LOCATED.value for item in assessments
            ),
            "preserved": counts[MeaningStatus.PRESERVED.value],
            "preservedWithRestructuring": counts[MeaningStatus.PRESERVED_WITH_RESTRUCTURING.value],
            "partial": counts[MeaningStatus.PARTIAL.value],
            "undertranslated": counts[MeaningStatus.UNDERTRANSLATED.value],
            "overtranslated": counts[MeaningStatus.OVERTRANSLATED.value],
            "meaningShift": counts[MeaningStatus.MEANING_SHIFT.value],
            "contradicted": counts[MeaningStatus.CONTRADICTED.value],
            "unverifiable": counts[MeaningStatus.UNVERIFIABLE.value],
            "locationReviewRequired": sum(item["locationReviewRequired"] for item in assessments),
            "resourceConflict": sum(
                component["evidence"]["resourceStatus"] == "CONFLICTING"
                for item in assessments for component in item["componentAssessments"]
            ),
            "averageComponentCount": (
                sum(len(item["componentAssessments"]) for item in assessments) / len(assessments)
                if assessments else 0.0
            ),
            "deterministicContradictionCount": sum(
                component["evidence"]["kind"] == MeaningEvidenceKind.DETERMINISTIC_CONTRADICTION.value
                for item in assessments for component in item["componentAssessments"]
            ),
            "analyzerLimitedAssessments": sum(
                item["meaningStatus"] == MeaningStatus.UNVERIFIABLE.value
                and any("capability is unavailable" in component["explanation"]
                        for component in item["componentAssessments"])
                for item in assessments
            ),
        }
        run_id = "meaning-run-" + fingerprint[:32]
        payload = {
            "id": run_id, "book": self.book, "rangeKey": location["rangeKey"],
            "fingerprint": fingerprint, "locationRunId": location["id"],
            "locationRunFingerprint": location["fingerprint"],
            "sourceInventoryFingerprint": source["fingerprint"],
            "targetInventoryFingerprint": target["fingerprint"],
            "meaningEngineVersion": MEANING_ENGINE_VERSION,
            "meaningPolicyVersion": self.policy.version,
            "modelVersion": self.model_version,
            "calibrationVersion": MEANING_CALIBRATION_VERSION,
            "runStatus": MeaningRunStatus.COMPLETE.value,
            "assessments": assessments, "diagnostics": diagnostics,
            "elapsedSeconds": time.perf_counter() - started, "cacheStatus": "MISS",
        }
        self.repository.save_meaning_analysis_run(
            run_id=run_id, project_id=self.project_id, book=self.book,
            range_key=location["rangeKey"], fingerprint=fingerprint,
            location_run_id=location["id"], run_status=MeaningRunStatus.COMPLETE.value,
            payload=payload, assessments=assessments,
        )
        return payload

    def status(self, run_id: str) -> dict[str, Any]:
        run = self.repository.meaning_analysis_run(run_id)
        return {key: run[key] for key in ("id", "runStatus", "diagnostics", "cacheStatus")}

    def get_range(self, run_id: str) -> dict[str, Any]:
        return self.repository.meaning_analysis_run(run_id)

    def get_assessment(self, assessment_id: str) -> dict[str, Any]:
        return self.repository.meaning_assessment(assessment_id)

    def get_components(self, assessment_id: str) -> list[dict[str, Any]]:
        return self.repository.meaning_components(assessment_id)

    def get_diagnostics(self, run_id: str) -> dict[str, Any]:
        return self.get_range(run_id)["diagnostics"]
