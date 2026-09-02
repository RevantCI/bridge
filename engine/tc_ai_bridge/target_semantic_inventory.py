"""Stage 6A target-only semantic inventory and bounded search foundation."""
from __future__ import annotations

from dataclasses import dataclass
from collections import Counter, defaultdict
import hashlib
import json
import unicodedata
from typing import Any, Iterable

from .passage_semantic_models import (
    AuditEligibility, ConfidenceScore, CoverageAccountingRole, CoverageDimension,
    LifecycleStatus, PolicyBinding, ReviewStatus, SemanticObligationStrength,
    SemanticUnitKind, SemanticUnitProvenance, TargetSemanticUnit, TokenKind,
    TokenSide,
)
from .passage_semantic_repository import FoundationValidationError


TARGET_INVENTORY_ENGINE_VERSION = "bridge-target-semantic-inventory-v1"
ANALYZER_REGISTRY_VERSION = "bridge-target-analyzers-v1"
SPAN_POLICY_VERSION = "bounded-target-span-lattice-v1-max4"
POLICY = PolicyBinding("confidence-v1", "calibration-v1", "target-inventory-audit-v1")
_LANGUAGE_ALIASES = {"tam": "ta", "eng": "en", "fra": "fr", "heb": "he", "jpn": "ja", "zho": "zh"}


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _json_hash(value: Any) -> str:
    return _sha(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def _language_key(value: str) -> str:
    base = value.lower().split("-", 1)[0]
    return _LANGUAGE_ALIASES.get(base, base)


@dataclass(frozen=True)
class TargetLanguageCapabilities:
    language_tag: str
    script: str
    direction: str
    tokenization: str
    morphology: str
    pos: str
    dependency_syntax: str
    sentence_boundary: str
    coreference: str
    semantic_roles: str
    tokenizer_profile: str
    normalization_profile: str
    providers: tuple[dict[str, str], ...]

    def to_wire(self) -> dict[str, Any]:
        return {
            "languageTag": self.language_tag, "script": self.script,
            "direction": self.direction, "tokenization": self.tokenization,
            "morphology": self.morphology, "pos": self.pos,
            "dependencySyntax": self.dependency_syntax,
            "sentenceBoundary": self.sentence_boundary,
            "coreference": self.coreference, "semanticRoles": self.semantic_roles,
            "tokenizerProfile": self.tokenizer_profile,
            "normalizationProfile": self.normalization_profile,
            "providers": list(self.providers),
        }


class TargetAnalyzerProvider:
    provider_id = "bridge-generic-baseline"
    version = "v1"

    def supports(self, language_tag: str) -> bool:
        return False

    def capabilities(self) -> dict[str, str]:
        return {}

    def analyze_token(self, token: dict[str, Any]) -> list[dict[str, Any]]:
        return []

    def subtoken_ranges(self, token: dict[str, Any]) -> list[tuple[int, int, str]]:
        return []


class LexicalTargetProvider(TargetAnalyzerProvider):
    provider_id = "bridge-lexical-target-rules"
    version = "v1"
    _NEGATION = {
        "ta": {"இல்லை", "அல்ல", "வேண்டாம்", "ஒருபோதும்"},
        "en": {"not", "no", "never", "neither", "nothing", "nobody"},
        "fr": {"ne", "pas", "non", "jamais", "rien"},
        "he": {"לא", "אַל", "אין"},
    }
    _QUANTIFIER = {
        "ta": {"அனைத்து", "அனைவரும்", "ஒவ்வொரு", "எல்லா", "முழு", "இரண்டு"},
        "en": {"all", "every", "each", "some", "many", "few", "only", "one", "both", "none"},
        "fr": {"tout", "tous", "chaque", "quelques", "plusieurs", "aucun"},
        "he": {"כל", "אחד", "שניים", "מעט", "רב"},
    }
    _PRONOUNS = {
        "ta": {"அவன்", "அவள்", "அவர்", "அவர்கள்", "நான்", "நீங்கள்", "நாம்"},
        "en": {"he", "she", "it", "they", "we", "you", "i"},
        "fr": {"il", "elle", "ils", "elles", "nous", "vous", "je"},
        "he": {"הוא", "היא", "הם", "אנחנו", "אני"},
    }

    def __init__(self, language_tag: str):
        self.language = _language_key(language_tag)

    def supports(self, language_tag: str) -> bool:
        return _language_key(language_tag) in self._NEGATION | self._QUANTIFIER

    def capabilities(self) -> dict[str, str]:
        return {"tokenization": "AVAILABLE"}

    def analyze_token(self, token: dict[str, Any]) -> list[dict[str, Any]]:
        value = str(token.get("normalizedForm") or "").casefold()
        out: list[dict[str, Any]] = []
        if value in {item.casefold() for item in self._NEGATION.get(self.language, set())}:
            out.append({"kind": "NEGATION", "dimension": "POLARITY", "interpretation": "NEGATIVE", "confidence": 1.0})
        quantifiers = {item.casefold() for item in self._QUANTIFIER.get(self.language, set())}
        if value in quantifiers or (self.language == "ta" and value.startswith(("அனை", "ஒவ்வொரு", "எல்லா"))):
            out.append({"kind": "QUANTIFIER", "dimension": "QUANTITY", "interpretation": "QUANTIFYING", "confidence": 0.95})
        if value in {item.casefold() for item in self._PRONOUNS.get(self.language, set())}:
            out.append({"kind": "REFERENT", "dimension": "REFERENT", "interpretation": "AMBIGUOUS_PRONOUN", "confidence": 0.5})
        return out

    def subtoken_ranges(self, token: dict[str, Any]) -> list[tuple[int, int, str]]:
        if self.language != "ta":
            return []
        value = str(token.get("rawForm") or "")
        for suffix in ("களுக்காகவும்", "களிலும்", "களுக்கு", "இருப்பதால்", "ஆலும்", "தால்"):
            if value.endswith(suffix) and len(value) > len(suffix):
                return [(0, len(value) - len(suffix), "STEM_CANDIDATE"),
                        (len(value) - len(suffix), len(value), "BOUND_SUFFIX_CANDIDATE")]
        return []


class TargetAnalyzerRegistry:
    def __init__(self, language_tag: str, providers: Iterable[TargetAnalyzerProvider] = ()):
        self.language_tag = language_tag or "und"
        built_in = LexicalTargetProvider(self.language_tag)
        self.providers = [provider for provider in (built_in, *providers) if provider.supports(self.language_tag)]

    def descriptor(self, text: str) -> TargetLanguageCapabilities:
        language = _language_key(self.language_tag)
        script = "Tamil" if language == "ta" else "Hebrew" if language in {"he", "yi"} else (
            "Han" if any("CJK" in unicodedata.name(ch, "") for ch in text) else "Latin"
        )
        direction = "RTL" if script == "Hebrew" else "LTR"
        tokenization = "AVAILABLE" if self.providers else "FALLBACK"
        merged: dict[str, str] = {}
        for provider in self.providers:
            merged.update(provider.capabilities())
        return TargetLanguageCapabilities(
            language_tag=self.language_tag, script=script, direction=direction,
            tokenization=merged.get("tokenization", tokenization),
            morphology=merged.get("morphology", "UNAVAILABLE"),
            pos=merged.get("pos", "UNAVAILABLE"),
            dependency_syntax=merged.get("dependencySyntax", "UNAVAILABLE"),
            sentence_boundary=merged.get("sentenceBoundary", "STRUCTURAL_FALLBACK"),
            coreference=merged.get("coreference", "UNAVAILABLE"),
            semantic_roles=merged.get("semanticRoles", "UNAVAILABLE"),
            tokenizer_profile="bridge-unicode-word-v1",
            normalization_profile="NFC-v1",
            providers=tuple({"id": p.provider_id, "version": p.version} for p in self.providers),
        )


class TargetSemanticInventory:
    def __init__(self, runtime: Any, providers: Iterable[TargetAnalyzerProvider] = ()):
        self.runtime = runtime
        self.repository = runtime.repository
        self.project_id = runtime.project_id
        self.book = runtime.book
        target = runtime.project.manifest.get("target_language")
        target = target if isinstance(target, dict) else {}
        self.language_tag = str(target.get("id") or "und")
        self.registry = TargetAnalyzerRegistry(self.language_tag, providers)

    def _unit(self, token: dict[str, Any], kind: SemanticUnitKind, dimension: CoverageDimension,
              interpretation: str, confidence: float, provider: TargetAnalyzerProvider | None) -> TargetSemanticUnit:
        provenance = SemanticUnitProvenance.LANGUAGE_ANALYZER if provider else SemanticUnitProvenance.DETERMINISTIC_RULE
        features = {
            "interpretation": interpretation,
            "providerId": provider.provider_id if provider else "bridge-target-baseline",
            "providerVersion": provider.version if provider else TARGET_INVENTORY_ENGINE_VERSION,
            "startCodePoint": str((token.get("span") or {}).get("startCodePoint", "")),
            "endCodePoint": str((token.get("span") or {}).get("endCodePoint", "")),
        }
        fingerprint = _json_hash({
            "token": token["id"], "kind": kind.value, "features": features,
            "targetRevision": token.get("textRevision"), "policy": POLICY.audit_policy_version,
        })
        unit_id = "target-unit-" + fingerprint[:32]
        ambiguous = interpretation == "AMBIGUOUS_PRONOUN"
        return TargetSemanticUnit(
            id=unit_id, side=TokenSide.TARGET, project_id=self.project_id, book=self.book,
            kind=kind, displayed_references=(token["displayedReference"],),
            canonical_references=tuple(token["canonicalReferences"]),
            token_instance_ids=(token["id"],), token_lineage_ids=(token["lineageId"],),
            raw_surface=token["rawForm"], normalized_surface=token["normalizedForm"],
            semantic_features=features,
            unit_confidence=ConfidenceScore(confidence, confidence, POLICY.confidence_policy_version, POLICY.calibration_version),
            provenance=provenance, evidence_ids=(), resource_validation_ids=(),
            audit_eligibility=AuditEligibility.REVIEW_ONLY if ambiguous else AuditEligibility.ELIGIBLE,
            semantic_obligation=SemanticObligationStrength.UNCERTAIN if ambiguous else SemanticObligationStrength.CONTEXT_DEPENDENT,
            accounting_role=CoverageAccountingRole.EVIDENCE_ONLY if ambiguous else CoverageAccountingRole.PRIMARY,
            audit_owner_unit_id=unit_id, coverage_dimension=dimension,
            semantic_fingerprint=fingerprint, policy_binding=POLICY,
            review_status=ReviewStatus.UNREVIEWED, lifecycle_status=LifecycleStatus.ACTIVE,
        )

    @staticmethod
    def _span(token_group: list[dict[str, Any]], text: str, kind: str, revision: str) -> dict[str, Any]:
        first, last = token_group[0], token_group[-1]
        start = int(first["span"]["startCodePoint"])
        end = int(last["span"]["endCodePoint"])
        quote = text[start:end]
        identity = _json_hash({"revision": revision, "reference": first["displayedReference"],
                               "tokens": [t["id"] for t in token_group], "start": start, "end": end, "kind": kind})
        return {
            "id": "target-span-" + identity[:32], "kind": kind,
            "displayedReference": first["displayedReference"],
            "tokenInstanceIds": [token["id"] for token in token_group],
            "startCodePoint": start, "endCodePoint": end, "quote": quote,
            "quoteSha256": _sha(quote), "targetRevision": revision,
            "spanPolicyVersion": SPAN_POLICY_VERSION,
        }

    def build_range(self, chapter: str, verse: str, end_chapter: str = "", end_verse: str = "") -> dict[str, Any]:
        passage = self.runtime.rebuild_current_passage(chapter, verse, end_chapter, end_verse)
        references = list(passage["targetTextByDisplayedReference"])
        range_key = f"{references[0]}..{references[-1]}"
        all_text = "\n".join(passage["targetTextByDisplayedReference"].values())
        capabilities = self.registry.descriptor(all_text)
        fingerprint = _json_hash({
            "targetContentHash": passage["targetContentHash"], "targetRevision": passage["targetRevision"],
            "language": capabilities.to_wire(), "engine": TARGET_INVENTORY_ENGINE_VERSION,
            "spanPolicy": SPAN_POLICY_VERSION, "canonicalReferences": passage["canonicalReferences"],
            "structureHash": passage["structureResourceHash"],
        })
        cached = self.repository.target_inventory_for_fingerprint(
            self.project_id, self.book, range_key, fingerprint,
        )
        if cached is not None:
            cached["cacheStatus"] = "HIT"
            return cached

        tokens = [self.repository.token_instance(item) for item in passage["targetTokenInstanceIds"]]
        unit_models: list[TargetSemanticUnit] = []
        by_ref: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for token in tokens:
            by_ref[token["displayedReference"]].append(token)
            if token["tokenKind"] == TokenKind.PUNCTUATION.value:
                continue
            unit_models.append(self._unit(
                token, SemanticUnitKind.LEXICAL, CoverageDimension.LEXICAL_CONTENT,
                "ORTHOGRAPHIC_TARGET_MATERIAL", 1.0, None,
            ))
            for provider in self.registry.providers:
                for finding in provider.analyze_token(token):
                    unit_models.append(self._unit(
                        token, SemanticUnitKind(finding["kind"]), CoverageDimension(finding["dimension"]),
                        finding["interpretation"], float(finding["confidence"]), provider,
                    ))
        units = self.repository.ensure_semantic_units(unit_models)

        spans: list[dict[str, Any]] = []
        subtoken_count = 0
        unknown_spans = 0
        for reference, ref_tokens in by_ref.items():
            text = passage["targetTextByDisplayedReference"][reference]
            lexical = [token for token in ref_tokens if token["tokenKind"] != TokenKind.PUNCTUATION.value]
            for token in ref_tokens:
                spans.append(self._span([token], text, "TOKEN", passage["targetRevision"]))
                for provider in self.registry.providers:
                    for start, end, label in provider.subtoken_ranges(token):
                        parent_start = int(token["span"]["startCodePoint"])
                        quote = token["rawForm"][start:end]
                        span = {
                            "id": "target-span-" + _json_hash({"token": token["id"], "start": start, "end": end, "provider": provider.version})[:32],
                            "kind": "SUBTOKEN", "displayedReference": reference,
                            "tokenInstanceIds": [token["id"]],
                            "startCodePoint": parent_start + start, "endCodePoint": parent_start + end,
                            "quote": quote, "quoteSha256": _sha(quote),
                            "targetRevision": passage["targetRevision"], "spanPolicyVersion": SPAN_POLICY_VERSION,
                            "analysis": label, "providerId": provider.provider_id, "providerVersion": provider.version,
                        }
                        spans.append(span); subtoken_count += 1
            for start in range(len(lexical)):
                for size in range(2, min(4, len(lexical) - start) + 1):
                    group = lexical[start:start + size]
                    # Phrases cannot jump punctuation: code-point material between
                    # adjacent tokens must contain only whitespace.
                    if any(text[int(a["span"]["endCodePoint"]):int(b["span"]["startCodePoint"])].strip()
                           for a, b in zip(group, group[1:])):
                        break
                    spans.append(self._span(group, text, "PHRASE", passage["targetRevision"]))
            if lexical:
                spans.append(self._span(lexical, text, "STRUCTURAL_SEGMENT", passage["targetRevision"]))
            if len(lexical) == 1 and len(lexical[0]["rawForm"]) > 4 and capabilities.tokenization == "FALLBACK":
                unknown_spans += 1

        neighborhoods: list[dict[str, Any]] = []
        for index, reference in enumerate(references):
            for scope in ("NORMALIZED_VERSE", "STRUCTURAL_SENTENCE"):
                neighborhoods.append({
                    "id": "target-neighborhood-" + _sha(f"{fingerprint}:{scope}:{reference}")[:32],
                    "scopeKind": scope, "displayedReferences": [reference],
                })
            adjacent = references[max(0, index - 1):min(len(references), index + 2)]
            neighborhoods.append({
                "id": "target-neighborhood-" + _sha(f"{fingerprint}:adjacent:{reference}")[:32],
                "scopeKind": "ADJACENT_STRUCTURAL_SEGMENT", "displayedReferences": adjacent,
            })
        neighborhoods.append({
            "id": "target-neighborhood-" + _sha(f"{fingerprint}:selected")[:32],
            "scopeKind": "SELECTED_PASSAGE", "displayedReferences": references,
        })
        if any(a.split(":")[0] != b.split(":")[0] for a, b in zip(references, references[1:])):
            neighborhoods.append({
                "id": "target-neighborhood-" + _sha(f"{fingerprint}:chapter-boundary")[:32],
                "scopeKind": "CHAPTER_BOUNDARY_CONTINUATION", "displayedReferences": references,
            })
        if any(marker["kind"] == "PARAGRAPH" for marker in passage["structureMarkers"]):
            neighborhoods.append({
                "id": "target-neighborhood-" + _sha(f"{fingerprint}:paragraph")[:32],
                "scopeKind": "PARAGRAPH", "displayedReferences": references,
            })

        kind_counts = Counter(unit["kind"] for unit in units)
        diagnostics = {
            "targetCharacters": sum(len(text) for text in passage["targetTextByDisplayedReference"].values()),
            "graphemeClusters": sum(len(__import__("regex").findall(r"\X", text)) for text in passage["targetTextByDisplayedReference"].values()),
            "orthographicTokens": len(tokens), "subtokensMorphemes": subtoken_count,
            "targetSemanticUnits": len(units), "lexicalUnits": kind_counts["LEXICAL"],
            "grammaticalUnits": kind_counts["MORPHOLOGICAL"] + kind_counts["IMPLICIT_GRAMMATICAL"],
            "negationUnits": kind_counts["NEGATION"], "quantifierUnits": kind_counts["QUANTIFIER"],
            "participantUnits": kind_counts["PARTICIPANT"] + kind_counts["REFERENT"],
            "predicateUnits": kind_counts["PREDICATE"], "clauses": kind_counts["CLAUSE"],
            "analyzerDerivedUnits": sum(unit["provenance"] == "LANGUAGE_ANALYZER" for unit in units),
            "reviewOnlyUnits": sum(unit["auditEligibility"] == "REVIEW_ONLY" for unit in units),
            "unknownUnsegmentedSpans": unknown_spans,
            "searchSpans": len(spans), "searchNeighborhoods": len(neighborhoods),
        }
        inventory_id = "target-inventory-" + fingerprint[:32]
        payload = {
            "id": inventory_id, "book": self.book, "rangeKey": range_key,
            "canonicalReferences": passage["canonicalReferences"], "fingerprint": fingerprint,
            "targetSemanticFingerprint": _json_hash([(u["kind"], u["semanticFingerprint"]) for u in units]),
            "targetRevision": passage["targetRevision"], "targetContentHash": passage["targetContentHash"],
            "targetInventoryEngineVersion": TARGET_INVENTORY_ENGINE_VERSION,
            "spanPolicyVersion": SPAN_POLICY_VERSION, "capabilities": capabilities.to_wire(),
            "tokens": tokens, "units": units, "searchSpans": spans,
            "searchNeighborhoods": neighborhoods,
            "structureMarkers": passage["structureMarkers"], "diagnostics": diagnostics,
            "cacheStatus": "MISS",
        }
        self.repository.save_target_inventory(
            inventory_id=inventory_id, project_id=self.project_id, book=self.book,
            range_key=range_key, fingerprint=fingerprint,
            target_revision=passage["targetRevision"], target_content_hash=passage["targetContentHash"],
            language_id=self.language_tag, tokenizer_version=capabilities.tokenizer_profile,
            analyzer_registry_version=ANALYZER_REGISTRY_VERSION,
            structure_hash=passage["structureResourceHash"], diagnostics=diagnostics,
            payload=payload, token_ids=[t["id"] for t in tokens], unit_ids=[u["id"] for u in units],
            spans=spans, neighborhoods=neighborhoods, references=references,
        )
        return payload

    def get_range(self, inventory_id: str) -> dict[str, Any]:
        return self.repository.target_inventory(inventory_id)

    def get_unit(self, unit_id: str) -> dict[str, Any]:
        unit = self.repository.semantic_unit(unit_id)
        if unit.get("side") != "TARGET":
            raise FoundationValidationError("Requested semantic unit is not a target unit")
        return unit

    def get_diagnostics(self, inventory_id: str) -> dict[str, Any]:
        return self.get_range(inventory_id)["diagnostics"]

    def get_search_spans(self, inventory_id: str) -> list[dict[str, Any]]:
        return self.get_range(inventory_id)["searchSpans"]

    def get_capabilities(self, inventory_id: str = "") -> dict[str, Any]:
        if inventory_id:
            return self.get_range(inventory_id)["capabilities"]
        return self.registry.descriptor("").to_wire()
