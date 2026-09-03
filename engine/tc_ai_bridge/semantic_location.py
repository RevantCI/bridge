"""Stage 6B passage-aware source-to-target location.

This module identifies probable current-target anchors. It deliberately does
not judge meaning preservation, omissions, additions, or corrections.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import hashlib
import json
import math
import time
import unicodedata
from typing import Any, Iterable

from .passage_semantic_models import (
    EmbeddingRole, LocationCalibrationStatus, LocationEvidenceKind, LocationOutcome,
    LocationRunStatus, Realization, RelationshipProperty,
)
from .passage_semantic_repository import FoundationValidationError


LOCATION_ENGINE_VERSION = "bridge-semantic-location-v1"
LOCATION_CONFIDENCE_POLICY_VERSION = "location-confidence-v1"
LOCATION_CALIBRATION_VERSION = "location-uncalibrated-v1"
LOCATION_SEARCH_POLICY_VERSION = "progressive-passage-search-v1"


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _json_hash(value: Any) -> str:
    return _sha(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def _normalized(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value).casefold().split())


def _cosine(left: list[float], right: list[float]) -> float:
    if not left or len(left) != len(right):
        return 0.0
    denominator = math.sqrt(sum(v * v for v in left)) * math.sqrt(sum(v * v for v in right))
    if denominator == 0:
        return 0.0
    return max(0.0, min(1.0, sum(a * b for a, b in zip(left, right)) / denominator))


@dataclass(frozen=True)
class LocationSearchPolicy:
    located_minimum: float = 0.36
    credible_minimum: float = 0.20
    ambiguity_margin: float = 0.07
    retained_candidates: int = 5
    split_seed_candidates: int = 5
    max_split_pairs_per_source: int = 10
    max_candidate_evaluations: int = 25_000
    version: str = LOCATION_SEARCH_POLICY_VERSION


class SemanticEmbeddingProvider:
    """Optional multilingual retrieval provider; never a meaning judge."""

    provider_id = "unavailable"
    provider_version = "v1"
    model_id = "none"
    model_hash = "none"
    dimensions = 0
    normalization = "NONE"
    languages: tuple[str, ...] = ()
    offline = True
    available = False
    fixture_only = False

    def embed(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("Semantic embedding provider is unavailable")

    def descriptor(self) -> dict[str, Any]:
        return {
            "providerId": self.provider_id,
            "providerVersion": self.provider_version,
            "modelId": self.model_id,
            "modelHash": self.model_hash,
            "dimensions": self.dimensions,
            "normalization": self.normalization,
            "languageCapabilities": list(self.languages),
            "offline": self.offline,
            "available": self.available,
            "fixtureOnly": self.fixture_only,
            "role": EmbeddingRole.CANDIDATE_RETRIEVAL_ONLY.value,
        }


class SemanticLocationEngine:
    def __init__(
        self, runtime: Any, embedding_provider: SemanticEmbeddingProvider | None = None,
        policy: LocationSearchPolicy | None = None,
    ):
        self.runtime = runtime
        self.repository = runtime.repository
        self.project_id = runtime.project_id
        self.book = runtime.book
        self.embedding_provider = embedding_provider or SemanticEmbeddingProvider()
        self.policy = policy or LocationSearchPolicy()
        self._embedding_hits = 0
        self._embedding_misses = 0
        self._embedding_failure = ""
        self._identity_context = ""

    def _embedding_map(self, texts: Iterable[str]) -> dict[str, list[float]]:
        provider = self.embedding_provider
        unique = list(dict.fromkeys(_normalized(text) for text in texts if _normalized(text)))
        if not provider.available or not unique or self._embedding_failure:
            return {}
        hashes = {_sha(text): text for text in unique}
        cached = self.repository.embedding_vectors(list(hashes), provider.model_hash)
        self._embedding_hits += len(cached)
        missing = {digest: text for digest, text in hashes.items() if digest not in cached}
        if missing:
            try:
                vectors = provider.embed(list(missing.values()))
            except Exception as error:  # provider failures are a search outcome, not NOT_LOCATED
                self._embedding_failure = f"{type(error).__name__}: {error}"
                return {text: cached[digest] for digest, text in hashes.items() if digest in cached}
            if len(vectors) != len(missing):
                raise FoundationValidationError("Embedding provider returned the wrong vector count")
            additions = dict(zip(missing, vectors))
            if any(len(vector) != provider.dimensions for vector in additions.values()):
                raise FoundationValidationError("Embedding provider returned invalid dimensions")
            self.repository.save_embedding_vectors(
                model_hash=provider.model_hash, dimensions=provider.dimensions,
                normalization=provider.normalization, vectors=additions,
            )
            cached.update(additions)
            self._embedding_misses += len(additions)
        return {text: cached[digest] for digest, text in hashes.items()}

    @staticmethod
    def _source_text(unit: dict[str, Any]) -> str:
        features = unit.get("semanticFeatures") or {}
        return str(
            features.get("lemma") or features.get("quantifierLemma")
            or unit.get("normalizedSurface") or unit.get("rawSurface") or ""
        )

    @staticmethod
    def _span_target_units(
        span: dict[str, Any], target_units_by_token: dict[str, list[dict[str, Any]]],
    ) -> list[dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for token_id in span["tokenInstanceIds"]:
            for unit in target_units_by_token.get(token_id, []):
                result[unit["id"]] = unit
        return list(result.values())

    def _validate_span(
        self, span: dict[str, Any], target_inventory: dict[str, Any],
        current_text_by_reference: dict[str, str],
    ) -> None:
        if span["targetRevision"] != target_inventory["targetRevision"]:
            raise FoundationValidationError("Target span revision does not match target inventory")
        if _sha(span["quote"]) != span["quoteSha256"]:
            raise FoundationValidationError("Target span quote hash is invalid")
        reference = span["displayedReference"]
        current = current_text_by_reference.get(reference, "")
        start, end = int(span["startCodePoint"]), int(span["endCodePoint"])
        if current[start:end] != span["quote"]:
            raise FoundationValidationError("Target span does not anchor exact current Scripture text")

    @staticmethod
    def _lexical_score(source: str, target: str) -> float:
        source, target = _normalized(source), _normalized(target)
        if not source or not target:
            return 0.0
        if source == target:
            return 1.0
        source_words, target_words = set(source.split()), set(target.split())
        overlap = len(source_words & target_words) / max(1, len(source_words | target_words))
        if source.isnumeric() and target.isnumeric() and source == target:
            return 1.0
        return overlap

    @staticmethod
    def _concept_score(source_unit: dict[str, Any], target_units: list[dict[str, Any]]) -> float:
        kind = source_unit.get("kind")
        dimension = source_unit.get("coverageDimension")
        if any(unit.get("kind") == kind for unit in target_units):
            return 0.95 if kind in {"NEGATION", "QUANTIFIER"} else 0.75
        if any(unit.get("coverageDimension") == dimension for unit in target_units):
            return 0.55
        return 0.0

    @staticmethod
    def _structural_score(source_unit: dict[str, Any], span: dict[str, Any]) -> float:
        source_refs = set(source_unit.get("canonicalReferences") or ())
        target_refs = set(span.get("_canonicalReferences") or ())
        return 0.8 if source_refs & target_refs else 0.0

    @staticmethod
    def _progressive_scope(
        source_unit: dict[str, Any], span: dict[str, Any],
        target_tokens: dict[str, dict[str, Any]], references: list[str],
    ) -> tuple[int, str]:
        """Place a candidate in the bounded structural search progression.

        Verse references are priors only.  The selected passage remains fully
        searchable, including chapter-boundary continuations.
        """
        source_canonical = set(source_unit.get("canonicalReferences") or ())
        target_canonical = {
            reference for token_id in span["tokenInstanceIds"]
            for reference in target_tokens[token_id].get("canonicalReferences", [])
        }
        if source_canonical & target_canonical:
            return 0, "NORMALIZED_VERSE"
        source_displayed = set(source_unit.get("displayedReferences") or ())
        target_reference = span["displayedReference"]
        if target_reference in source_displayed:
            return 1, "STRUCTURAL_SENTENCE"
        indexes = {reference: index for index, reference in enumerate(references)}
        source_indexes = [indexes[item] for item in source_displayed if item in indexes]
        if source_indexes and target_reference in indexes and min(
            abs(indexes[target_reference] - item) for item in source_indexes
        ) <= 1:
            return 2, "ADJACENT_STRUCTURAL_SEGMENT"
        source_chapters = {
            item.split(" ", 1)[1].split(":", 1)[0]
            for item in source_displayed if " " in item and ":" in item
        }
        target_chapter = (
            target_reference.split(" ", 1)[1].split(":", 1)[0]
            if " " in target_reference and ":" in target_reference else ""
        )
        if source_chapters and target_chapter not in source_chapters:
            return 4, "CHAPTER_BOUNDARY_CONTINUATION"
        return 3, "SELECTED_PASSAGE"

    @staticmethod
    def _realization(target_units: list[dict[str, Any]]) -> Realization:
        kinds = {unit.get("kind") for unit in target_units}
        if kinds & {"MORPHOLOGICAL", "IMPLICIT_GRAMMATICAL"}:
            return Realization.GRAMMATICALLY_REALIZED
        if "REFERENT" in kinds:
            return Realization.PRONOMINALIZED
        if "CONSTRUCTION" in kinds and not kinds & {"LEXICAL", "MORPHOLOGICAL"}:
            return Realization.IMPLICIT
        return Realization.LEXICALLY_REALIZED

    def _score_candidate(
        self, source_unit: dict[str, Any], span: dict[str, Any],
        target_units: list[dict[str, Any]], source_vector: list[float] | None,
        target_vector: list[float] | None, precedents: list[dict[str, Any]],
    ) -> tuple[float, list[dict[str, Any]]]:
        source_text = self._source_text(source_unit)
        lexical = self._lexical_score(source_text, span["quote"])
        semantic = _cosine(source_vector or [], target_vector or [])
        concept = self._concept_score(source_unit, target_units)
        morphology = 0.9 if (
            source_unit.get("kind") in {"MORPHOLOGICAL", "IMPLICIT_GRAMMATICAL"}
            and any(unit.get("kind") in {"MORPHOLOGICAL", "IMPLICIT_GRAMMATICAL"}
                    for unit in target_units)
        ) else 0.0
        structural = self._structural_score(source_unit, span)
        search_scope = str(span.get("_searchScope") or "SELECTED_PASSAGE")
        source_tokens = set(source_unit.get("tokenInstanceIds") or ())
        target_tokens = set(span["tokenInstanceIds"])
        human = 0.0
        for precedent in precedents:
            if source_tokens & set(precedent.get("sourceTokenInstanceIds") or ()) and (
                target_tokens & set(precedent.get("targetTokenInstanceIds") or ())
            ):
                human = 1.0
                break
        components = [
            (LocationEvidenceKind.SEMANTIC_SIMILARITY, semantic, 0.42,
             self.embedding_provider.provider_id if semantic else "unavailable"),
            (LocationEvidenceKind.LEXICAL, lexical, 0.38, "bridge-lexical-v1"),
            (LocationEvidenceKind.CONCEPT, concept, 0.15, "target-unit-kind-v1"),
            (LocationEvidenceKind.MORPHOLOGY, morphology, 0.12, "target-analyzer-v1"),
            (LocationEvidenceKind.STRUCTURAL_PROXIMITY, structural, 0.05,
             f"progressive-passage-v1:{search_scope}"),
            (LocationEvidenceKind.HUMAN_PRECEDENT, human, 0.65,
             "project-local-human-v1"),
            (LocationEvidenceKind.EXACT_SPAN, 1.0, 0.01, "exact-current-span-v1"),
        ]
        raw = min(1.0, sum(value * weight for _, value, weight, _ in components))
        return raw, [
            {"kind": kind.value, "rawScore": value, "weight": weight,
             "weightedScore": value * weight, "provenance": provenance}
            for kind, value, weight, provenance in components if value > 0
        ]

    def _candidate(
        self, source_unit: dict[str, Any], spans: list[dict[str, Any]],
        raw_score: float, components: list[dict[str, Any]], realization: Realization,
        target_units: list[dict[str, Any]], target_tokens: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        span_ids = [span["id"] for span in spans]
        candidate_id = "location-candidate-" + _json_hash({
            "source": source_unit["id"], "spans": span_ids,
            "engine": LOCATION_ENGINE_VERSION,
            "embeddingModel": self.embedding_provider.model_hash,
            "searchPolicy": self.policy.version,
            "runContext": self._identity_context,
        })[:32]
        token_ids = list(dict.fromkeys(
            token_id for span in spans for token_id in span["tokenInstanceIds"]
        ))
        displayed_refs = list(dict.fromkeys(span["displayedReference"] for span in spans))
        canonical_refs = list(dict.fromkeys(
            reference for token_id in token_ids
            for reference in target_tokens[token_id].get("canonicalReferences", [])
        ))
        properties: list[str] = []
        if len(spans) > 1:
            properties.extend([RelationshipProperty.SPLIT.value, RelationshipProperty.DISCONTIGUOUS.value])
        source_canonical = set(source_unit.get("canonicalReferences") or ())
        target_canonical = set(canonical_refs)
        source_displayed = set(source_unit.get("displayedReferences") or ())
        if source_canonical and target_canonical and source_canonical.isdisjoint(target_canonical):
            properties.append(RelationshipProperty.CROSS_VERSE.value)
        elif source_displayed.isdisjoint(displayed_refs) and source_canonical & target_canonical:
            properties.append(RelationshipProperty.VERSIFICATION_DIFFERENCE.value)
        return {
            "id": candidate_id,
            "sourceOwnerUnitId": source_unit["id"],
            "sourceSemanticUnitIds": [source_unit["id"]],
            "targetSemanticUnitIds": list(dict.fromkeys(unit["id"] for unit in target_units)),
            "targetSpanIds": span_ids,
            "targetTokenInstanceIds": token_ids,
            "targetDisplayedReferences": displayed_refs,
            "targetCanonicalReferences": canonical_refs,
            "quotes": [{"spanId": span["id"], "quote": span["quote"],
                        "quoteSha256": span["quoteSha256"]} for span in spans],
            "realization": realization.value,
            "properties": list(dict.fromkeys(properties)),
            "rawScore": raw_score,
            "evidenceComponents": components,
            "rank": 0,
        }

    def _unsupported(self, source_unit: dict[str, Any], capabilities: dict[str, Any]) -> bool:
        if source_unit.get("kind") in {"MORPHOLOGICAL", "IMPLICIT_GRAMMATICAL"}:
            return capabilities.get("morphology") != "AVAILABLE"
        if source_unit.get("kind") in {"CLAUSE", "SEMANTIC_ROLE", "PREDICATE"}:
            return capabilities.get("dependencySyntax") != "AVAILABLE"
        return False

    def _relationship(
        self, source_unit: dict[str, Any], candidates: list[dict[str, Any]],
        complete: bool, unsupported: bool,
    ) -> dict[str, Any]:
        selected: dict[str, Any] | None = None
        if unsupported:
            outcome = LocationOutcome.UNSUPPORTED_ANALYSIS
        elif not complete:
            outcome = LocationOutcome.SEARCH_INCOMPLETE
        elif not candidates or candidates[0]["rawScore"] < self.policy.credible_minimum:
            outcome = LocationOutcome.NOT_LOCATED
        else:
            top = candidates[0]
            margin = top["rawScore"] - (candidates[1]["rawScore"] if len(candidates) > 1 else 0.0)
            if top["rawScore"] >= self.policy.located_minimum and margin >= self.policy.ambiguity_margin:
                outcome, selected = LocationOutcome.LOCATED, top
            else:
                outcome = LocationOutcome.AMBIGUOUS
        confidence_raw = selected["rawScore"] if selected else (
            candidates[0]["rawScore"] if candidates else 0.0
        )
        relationship_id = "location-relationship-" + _json_hash({
            "source": source_unit["id"], "selected": selected["id"] if selected else None,
            "outcome": outcome.value, "engine": LOCATION_ENGINE_VERSION,
            "embeddingModel": self.embedding_provider.model_hash,
            "searchPolicy": self.policy.version,
            "runContext": self._identity_context,
        })[:32]
        return {
            "id": relationship_id,
            "sourceOwnerUnitId": source_unit["id"],
            "sourceSemanticUnitIds": [source_unit["id"]],
            "targetSemanticUnitIds": selected["targetSemanticUnitIds"] if selected else [],
            "targetSpanIds": selected["targetSpanIds"] if selected else [],
            "targetTokenInstanceIds": selected["targetTokenInstanceIds"] if selected else [],
            "locationOutcome": outcome.value,
            "realization": selected["realization"] if selected else Realization.UNCERTAIN.value,
            "properties": selected["properties"] if selected else [],
            "locationConfidence": {
                "rawScore": confidence_raw,
                "calibratedValue": confidence_raw,
                "confidencePolicyVersion": LOCATION_CONFIDENCE_POLICY_VERSION,
                "calibrationVersion": LOCATION_CALIBRATION_VERSION,
                "calibrationStatus": LocationCalibrationStatus.UNCALIBRATED_INTERNAL.value,
            },
            "selectedCandidateId": selected["id"] if selected else None,
            "alternativeCandidateIds": [item["id"] for item in candidates if item is not selected],
            "reviewStatus": "AI_PROPOSED",
            "lifecycleStatus": "ACTIVE",
            "revision": 1,
        }

    @staticmethod
    def _mark_reordering(relationships: list[dict[str, Any]], source_units: dict[str, dict[str, Any]]) -> bool:
        sequence: list[tuple[str, str, dict[str, Any]]] = []
        for relationship in relationships:
            if relationship["locationOutcome"] != LocationOutcome.LOCATED.value:
                continue
            source = source_units[relationship["sourceSemanticUnitIds"][0]]
            source_ref = (source.get("canonicalReferences") or [""])[0]
            target_ref = (relationship.get("targetSpanIds") or [""])[0]
            sequence.append((source_ref, target_ref, relationship))
        # Span IDs are content hashes, so use target displayed refs supplied by
        # candidates through a temporary field when present.
        ordered = [item for item in relationships if item.get("_targetReference")]
        inversion = any(
            left["_sourceReference"] < right["_sourceReference"]
            and left["_targetReference"] > right["_targetReference"]
            for index, left in enumerate(ordered) for right in ordered[index + 1:]
        )
        if inversion:
            for relationship in ordered:
                relationship["properties"] = list(dict.fromkeys(
                    [*relationship["properties"], RelationshipProperty.REORDERED.value]
                ))
        for relationship in relationships:
            relationship.pop("_sourceReference", None)
            relationship.pop("_targetReference", None)
        return inversion

    def _merge_shared_realizations(
        self,
        relationships: list[dict[str, Any]], source_units: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        grouped: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
        remainder: list[dict[str, Any]] = []
        for relationship in relationships:
            key = tuple(relationship.get("targetTokenInstanceIds") or ())
            if relationship["locationOutcome"] == "LOCATED" and key:
                grouped[key].append(relationship)
            else:
                remainder.append(relationship)
        for target_tokens, members in grouped.items():
            if len(members) == 1:
                remainder.append(members[0])
                continue
            source_token_sets = [
                set(source_units[item["sourceSemanticUnitIds"][0]].get("tokenInstanceIds") or ())
                for item in members
            ]
            if any(left & right for index, left in enumerate(source_token_sets)
                   for right in source_token_sets[index + 1:]):
                remainder.extend(members)
                continue
            composite = dict(members[0])
            composite["sourceSemanticUnitIds"] = [
                unit_id for item in members for unit_id in item["sourceSemanticUnitIds"]
            ]
            composite["properties"] = list(dict.fromkeys(
                [*composite["properties"], RelationshipProperty.MERGED.value]
            ))
            composite["alternativeCandidateIds"] = list(dict.fromkeys(
                candidate_id for item in members
                for candidate_id in item["alternativeCandidateIds"]
            ))
            composite["id"] = "location-relationship-" + _json_hash({
                "sources": composite["sourceSemanticUnitIds"], "targetTokens": target_tokens,
                "property": "MERGED", "engine": LOCATION_ENGINE_VERSION,
                "embeddingModel": self.embedding_provider.model_hash,
                "searchPolicy": self.policy.version,
                "runContext": self._identity_context,
            })[:32]
            remainder.append(composite)
        return sorted(remainder, key=lambda item: item["sourceOwnerUnitId"])

    @staticmethod
    def _annotate_strong_anchor_context(
        candidates: list[dict[str, Any]], relationships: list[dict[str, Any]],
        source_units: dict[str, dict[str, Any]],
    ) -> int:
        """Persist non-circular passage-graph support from strong first-pass anchors.

        Context does not change raw scores in v1. It records auditable support
        for later calibrated policies, and only already-strong independent
        anchors may support peers from the same source structural reference.
        """
        by_id = {candidate["id"]: candidate for candidate in candidates}
        anchors: list[tuple[str, set[str], str, str]] = []
        for relationship in relationships:
            selected_id = relationship.get("selectedCandidateId")
            if not selected_id or relationship["locationOutcome"] != LocationOutcome.LOCATED.value:
                continue
            selected = by_id[selected_id]
            alternatives = [by_id[item] for item in relationship["alternativeCandidateIds"] if item in by_id]
            margin = selected["rawScore"] - max(
                (item["rawScore"] for item in alternatives), default=0.0,
            )
            if selected["rawScore"] < 0.40 or margin < 0.07:
                continue
            source_reference = (
                source_units[relationship["sourceOwnerUnitId"]].get("canonicalReferences") or [""]
            )[0]
            anchors.append((
                source_reference, set(selected["targetCanonicalReferences"]),
                relationship["id"], relationship["sourceOwnerUnitId"],
            ))
        edges = 0
        for candidate in candidates:
            source_reference = (
                source_units[candidate["sourceOwnerUnitId"]].get("canonicalReferences") or [""]
            )[0]
            target_references = set(candidate["targetCanonicalReferences"])
            supporters = [
                relationship_id
                for anchor_source, anchor_targets, relationship_id, anchor_owner in anchors
                if anchor_owner != candidate["sourceOwnerUnitId"]
                and anchor_source == source_reference and anchor_targets & target_references
            ]
            if not supporters:
                continue
            candidate["evidenceComponents"].append({
                "kind": LocationEvidenceKind.PASSAGE_COHERENCE.value,
                "rawScore": 1.0, "weight": 0.0, "weightedScore": 0.0,
                "provenance": "strong-first-pass:" + ",".join(sorted(supporters)),
            })
            edges += len(supporters)
        return edges

    def run_range(
        self, chapter: str, verse: str, end_chapter: str = "", end_verse: str = "",
        *, max_candidate_evaluations: int | None = None,
    ) -> dict[str, Any]:
        source_inventory = self.runtime.source_semantic.build_range(
            chapter, verse, end_chapter, end_verse,
        )
        target_inventory = self.runtime.target_semantic.build_range(
            chapter, verse, end_chapter, end_verse,
        )
        range_key = source_inventory["rangeKey"]
        budget = max_candidate_evaluations or self.policy.max_candidate_evaluations
        provider_descriptor = self.embedding_provider.descriptor()
        fingerprint = _json_hash({
            "sourceInventory": source_inventory["fingerprint"],
            "targetInventory": target_inventory["fingerprint"],
            "targetRevision": target_inventory["targetRevision"],
            "sourceResource": source_inventory["sourceResource"],
            "engine": LOCATION_ENGINE_VERSION,
            "embedding": provider_descriptor,
            "confidencePolicy": LOCATION_CONFIDENCE_POLICY_VERSION,
            "calibration": LOCATION_CALIBRATION_VERSION,
            "searchPolicy": self.policy.version,
            "budget": budget,
        })
        cached = self.repository.semantic_location_for_fingerprint(
            self.project_id, self.book, range_key, fingerprint,
        )
        if cached is not None:
            cached["cacheStatus"] = "HIT"
            return cached
        self._identity_context = fingerprint
        self._embedding_hits = 0
        self._embedding_misses = 0
        self._embedding_failure = ""

        started = time.perf_counter()
        units_by_id = {unit["id"]: unit for unit in source_inventory["units"]}
        primary = [
            units_by_id[account["auditOwnerUnitId"]]
            for account in source_inventory["coverageAccounts"]
        ]
        target_tokens = {token["id"]: token for token in target_inventory["tokens"]}
        target_units_by_token: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for unit in target_inventory["units"]:
            for token_id in unit["tokenInstanceIds"]:
                target_units_by_token[token_id].append(unit)
        # Spans are content-addressed against parsed, marker-stripped verse
        # text (build_current_text_overlay via rebuild_current_passage) --
        # the same source target_semantic.build_range used to build them.
        # Slicing the raw stored verse string here instead breaks on any
        # embedded markup (a leading italics marker, an inline footnote
        # quoting the verse text, a cross reference): the raw string is
        # longer than the clean text the span's code points were measured
        # against, so every offset from that point on drifts.
        current_text_by_reference = self.runtime.rebuild_current_passage(
            chapter, verse, end_chapter, end_verse,
        )["targetTextByDisplayedReference"]
        spans = target_inventory["searchSpans"]
        for span in spans:
            self._validate_span(span, target_inventory, current_text_by_reference)

        embedding_started = time.perf_counter()
        source_texts = [self._source_text(unit) for unit in primary]
        target_texts = [span["quote"] for span in spans]
        vectors = self._embedding_map([*source_texts, *target_texts])
        embedding_seconds = time.perf_counter() - embedding_started
        precedents = self.repository.human_approved_lexical_precedents(self.project_id)

        evaluated = 0
        scope_evaluations: Counter[str] = Counter()
        retrieval_started = time.perf_counter()
        ranking_seconds = 0.0
        all_candidates: list[dict[str, Any]] = []
        relationships: list[dict[str, Any]] = []
        for source_unit in primary:
            unsupported = self._unsupported(source_unit, target_inventory["capabilities"])
            unit_candidates: list[dict[str, Any]] = []
            complete = not self._embedding_failure
            if not unsupported:
                source_text = _normalized(self._source_text(source_unit))
                ordered_spans: list[dict[str, Any]] = []
                for span in spans:
                    scope_rank, scope = self._progressive_scope(
                        source_unit, span, target_tokens,
                        list(target_inventory.get("canonicalReferences") or ()),
                    )
                    target_canonical = list(dict.fromkeys(
                        reference for token_id in span["tokenInstanceIds"]
                        for reference in target_tokens[token_id].get("canonicalReferences", [])
                    ))
                    ordered_spans.append({
                        **span, "_searchScopeRank": scope_rank,
                        "_searchScope": scope, "_canonicalReferences": target_canonical,
                    })
                ordered_spans.sort(key=lambda item: (
                    item["_searchScopeRank"], item["displayedReference"],
                    item["startCodePoint"], item["endCodePoint"], item["id"],
                ))
                for span in ordered_spans:
                    if evaluated >= budget:
                        complete = False
                        break
                    evaluated += 1
                    scope_evaluations[span["_searchScope"]] += 1
                    span_units = self._span_target_units(span, target_units_by_token)
                    raw, components = self._score_candidate(
                        source_unit, span, span_units, vectors.get(source_text),
                        vectors.get(_normalized(span["quote"])), precedents,
                    )
                    if raw < self.policy.credible_minimum / 2:
                        continue
                    unit_candidates.append(self._candidate(
                        source_unit, [span], raw, components,
                        self._realization(span_units), span_units, target_tokens,
                    ))

                # Split candidates are deliberately bounded to pairs drawn
                # from the strongest independently retrieved spans.
                seeds = sorted(
                    unit_candidates,
                    key=lambda item: (-item["rawScore"], len(item["targetTokenInstanceIds"])),
                )[:self.policy.split_seed_candidates]
                split_pairs = 0
                for left_index, left in enumerate(seeds):
                    for right in seeds[left_index + 1:]:
                        if split_pairs >= self.policy.max_split_pairs_per_source:
                            break
                        if evaluated >= budget:
                            complete = False
                            break
                        if set(left["targetTokenInstanceIds"]) & set(right["targetTokenInstanceIds"]):
                            continue
                        evaluated += 1
                        split_pairs += 1
                        left_span = next(item for item in spans if item["id"] == left["targetSpanIds"][0])
                        right_span = next(item for item in spans if item["id"] == right["targetSpanIds"][0])
                        combined_text = f"{left_span['quote']} … {right_span['quote']}"
                        combined_vectors = self._embedding_map([combined_text])
                        combined_units = self._span_target_units(left_span, target_units_by_token)
                        combined_units.extend(
                            unit for unit in self._span_target_units(right_span, target_units_by_token)
                            if unit not in combined_units
                        )
                        pseudo = dict(left_span)
                        pseudo["quote"] = combined_text
                        pseudo["tokenInstanceIds"] = [
                            *left_span["tokenInstanceIds"], *right_span["tokenInstanceIds"],
                        ]
                        pseudo["_searchScope"] = "SPLIT_PAIR"
                        pseudo["_canonicalReferences"] = list(dict.fromkeys(
                            reference for token_id in pseudo["tokenInstanceIds"]
                            for reference in target_tokens[token_id].get("canonicalReferences", [])
                        ))
                        raw, components = self._score_candidate(
                            source_unit, pseudo, combined_units, vectors.get(source_text),
                            combined_vectors.get(_normalized(combined_text)), precedents,
                        )
                        if raw >= self.policy.credible_minimum:
                            unit_candidates.append(self._candidate(
                                source_unit, [left_span, right_span], raw, components,
                                self._realization(combined_units), combined_units, target_tokens,
                            ))
                    if not complete:
                        break

            ranking_started = time.perf_counter()
            unit_candidates.sort(key=lambda item: (-item["rawScore"], len(item["targetSpanIds"]), item["id"]))
            # TOKEN and STRUCTURAL_SEGMENT can denote the identical target
            # occurrence. Candidate competition is between locations, not
            # duplicate lattice representations of one location.
            distinct_locations: dict[tuple[str, ...], dict[str, Any]] = {}
            for candidate in unit_candidates:
                key = tuple(candidate["targetTokenInstanceIds"])
                distinct_locations.setdefault(key, candidate)
            retained = list(distinct_locations.values())[:self.policy.retained_candidates]
            for rank, candidate in enumerate(retained, 1):
                candidate["rank"] = rank
                alternative = next(
                    (item for item in retained if item["id"] != candidate["id"]), None,
                )
                margin = abs(candidate["rawScore"] - alternative["rawScore"]) if alternative else candidate["rawScore"]
                candidate["evidenceComponents"].append({
                    "kind": LocationEvidenceKind.CANDIDATE_COMPETITION.value,
                    "rawScore": margin, "weight": 0.0, "weightedScore": 0.0,
                    "provenance": f"{LOCATION_CONFIDENCE_POLICY_VERSION}:margin-only",
                })
            relationship = self._relationship(source_unit, retained, complete, unsupported)
            if relationship["selectedCandidateId"]:
                selected = next(item for item in retained if item["id"] == relationship["selectedCandidateId"])
                relationship["_sourceReference"] = (source_unit.get("canonicalReferences") or [""])[0]
                relationship["_targetReference"] = (selected.get("targetCanonicalReferences") or [""])[0]
            all_candidates.extend(retained)
            relationships.append(relationship)
            ranking_seconds += time.perf_counter() - ranking_started
        retrieval_seconds = max(0.0, time.perf_counter() - retrieval_started - ranking_seconds)

        context_edges = self._annotate_strong_anchor_context(
            all_candidates, relationships, units_by_id,
        )
        reordered = self._mark_reordering(relationships, units_by_id)
        relationships = self._merge_shared_realizations(relationships, units_by_id)
        outcome_counts = Counter(item["locationOutcome"] for item in relationships)
        property_counts = Counter(
            prop for item in relationships for prop in item["properties"]
        )
        realization_counts = Counter(item["realization"] for item in relationships)
        located_obligations = sum(
            len(item["sourceSemanticUnitIds"]) for item in relationships
            if item["locationOutcome"] == LocationOutcome.LOCATED.value
        )
        diagnostics = {
            "sourcePrimaryObligations": len(primary),
            "locationsFound": located_obligations,
            "ambiguous": outcome_counts[LocationOutcome.AMBIGUOUS.value],
            "notLocated": outcome_counts[LocationOutcome.NOT_LOCATED.value],
            "searchIncomplete": outcome_counts[LocationOutcome.SEARCH_INCOMPLETE.value],
            "unsupportedAnalysis": outcome_counts[LocationOutcome.UNSUPPORTED_ANALYSIS.value],
            "sameVerse": sum(
                item["locationOutcome"] == "LOCATED"
                and RelationshipProperty.CROSS_VERSE.value not in item["properties"]
                for item in relationships
            ),
            "crossVerse": property_counts[RelationshipProperty.CROSS_VERSE.value],
            "split": property_counts[RelationshipProperty.SPLIT.value],
            "merged": property_counts[RelationshipProperty.MERGED.value],
            "reordered": reordered,
            "grammatical": realization_counts[Realization.GRAMMATICALLY_REALIZED.value],
            "pronominalized": realization_counts[Realization.PRONOMINALIZED.value],
            "implicit": realization_counts[Realization.IMPLICIT.value],
            "averageCandidateCount": (
                len(all_candidates) / len(primary) if primary else 0.0
            ),
            "candidateEvaluations": evaluated,
            "candidateBudget": budget,
            "progressiveSearchScopeEvaluations": dict(scope_evaluations),
            "contextualSupportEdges": context_edges,
            "retrievalSeconds": retrieval_seconds,
            "rankingSeconds": ranking_seconds,
            "embeddingSeconds": embedding_seconds,
            "embeddingCacheHits": self._embedding_hits,
            "embeddingCacheMisses": self._embedding_misses,
            "embeddingFailure": self._embedding_failure or None,
            "embeddingCacheHitRate": (
                self._embedding_hits / (self._embedding_hits + self._embedding_misses)
                if self._embedding_hits + self._embedding_misses else 0.0
            ),
        }
        run_id = "location-run-" + fingerprint[:32]
        payload = {
            "id": run_id, "book": self.book, "rangeKey": range_key,
            "fingerprint": fingerprint, "sourceInventoryId": source_inventory["id"],
            "sourceInventoryFingerprint": source_inventory["fingerprint"],
            "targetInventoryId": target_inventory["id"],
            "targetInventoryFingerprint": target_inventory["fingerprint"],
            "passageFingerprint": target_inventory["targetContentHash"],
            "locationEngineVersion": LOCATION_ENGINE_VERSION,
            "embeddingProvider": provider_descriptor,
            "confidencePolicyVersion": LOCATION_CONFIDENCE_POLICY_VERSION,
            "calibrationVersion": LOCATION_CALIBRATION_VERSION,
            "searchPolicyVersion": self.policy.version,
            "runStatus": LocationRunStatus.COMPLETE.value,
            "relationships": relationships, "candidates": all_candidates,
            "diagnostics": diagnostics,
            "elapsedSeconds": time.perf_counter() - started,
            "cacheStatus": "MISS",
        }
        self.repository.save_semantic_location_run(
            run_id=run_id, project_id=self.project_id, book=self.book,
            range_key=range_key, fingerprint=fingerprint,
            source_inventory_id=source_inventory["id"],
            target_inventory_id=target_inventory["id"],
            run_status=LocationRunStatus.COMPLETE.value, payload=payload,
            candidates=all_candidates, relationships=relationships,
        )
        return payload

    def status(self, run_id: str) -> dict[str, Any]:
        run = self.repository.semantic_location_run(run_id)
        return {
            "id": run["id"], "runStatus": run["runStatus"],
            "diagnostics": run["diagnostics"], "cacheStatus": run.get("cacheStatus", "MISS"),
        }

    def get_range(self, run_id: str) -> dict[str, Any]:
        return self.repository.semantic_location_run(run_id)

    def get_relationship(self, relationship_id: str) -> dict[str, Any]:
        return self.repository.semantic_location_relationship(relationship_id)

    def get_candidates(self, run_id: str, source_owner_unit_id: str = "") -> list[dict[str, Any]]:
        return self.repository.semantic_location_candidates(run_id, source_owner_unit_id)

    def get_diagnostics(self, run_id: str) -> dict[str, Any]:
        return self.get_range(run_id)["diagnostics"]
