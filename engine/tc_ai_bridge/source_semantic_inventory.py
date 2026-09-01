"""Deterministic Stage 5 inventory of UHB/UGNT source contributions.

This module is deliberately source-only. It never reads target Scripture and
does not perform alignment, retrieval, omission/addition QA, or correction.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path
import re
import unicodedata
from typing import Any, Iterable

from .original_language_resources import (
    OriginalLanguageResource,
    bundled_resources_root,
    resource_for_book,
    source_tokens_for_verse,
)
from .passage_semantic_models import (
    AuditDirection,
    AuditEligibility,
    ConfidenceScore,
    CoverageAccountingRole,
    CoverageDimension,
    EvidenceKind,
    EvidenceRecord,
    LifecycleStatus,
    PolicyBinding,
    ResourceValidationStatus,
    ReviewStatus,
    SemanticCoverageAccount,
    SemanticObligationStrength,
    SemanticUnitKind,
    SemanticUnitProvenance,
    SourceSemanticUnit,
    TokenInstance,
    TokenKind,
    TokenLayer,
    TokenLineage,
    TokenSide,
)
from .passage_semantic_repository import (
    FoundationRepository,
    FoundationValidationError,
)
from .resource_materializer import _category_from_twlink, _term_from_twlink


INVENTORY_ENGINE_VERSION = "bridge-source-semantic-inventory-v1"
SOURCE_TOKENIZATION_VERSION = "pinned-original-language-token-pack-v1"
AUDIT_POLICY_VERSION = "source-inventory-audit-v1"
POLICY = PolicyBinding("confidence-v1", "calibration-v1", AUDIT_POLICY_VERSION)

_GREEK_NEGATION = {"οὐ", "οὐκ", "οὐχ", "μή", "μηδέ", "οὐδέ"}
_SEMITIC_NEGATION = {"לֹא", "אַל", "אַיִן", "אֵין", "בְּלִי", "לָא"}
_GREEK_QUANTIFIERS = {"πᾶς", "ἅπας", "πολύς", "ὀλίγος", "εἷς", "δύο", "μόνος", "ἀμφότεροι"}
_SEMITIC_QUANTIFIERS = {"כֹּל", "כֹּל", "רַב", "מְעַט", "אֶחָד", "שְׁנַיִם", "שְׁנֵי"}
_GREEK_FUNCTION = {"ὁ", "καί", "δέ", "τε", "γάρ", "μέν", "εἰ", "ἐν", "εἰς", "ἐπί", "ἀπό", "πρός"}
_SEMITIC_FUNCTION = {"ו", "ב", "כ", "ל", "מִן", "אֵת", "ה"}
_TEMPORAL_LEMMAS = {"ἡμέρα", "ἀρχή", "νῦν", "χρόνος", "יוֹם", "עֵת"}


def _sha(value: str | bytes) -> str:
    raw = value if isinstance(value, bytes) else value.encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _json_hash(value: Any) -> str:
    return _sha(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def _file_hash(path: Path | None) -> str:
    return _sha(path.read_bytes()) if path is not None and path.is_file() else "unavailable"


def _normalized(value: str) -> str:
    return unicodedata.normalize("NFC", value.replace("\u2060", "").strip())


def _quote_form(value: str) -> str:
    # UHB/UGNT token packs contain lexical tokens, while tN quotes may retain
    # adjacent source punctuation. Removing Unicode punctuation on both sides
    # preserves an exact lexical sequence without fuzzy semantic matching.
    return "".join(
        char for char in _normalized(value)
        if not unicodedata.category(char).startswith("P")
    )


def _language_id(resource: OriginalLanguageResource, morphology: str) -> str:
    return "arc" if morphology.startswith("Ar,") else resource.language_id


def _is_verb(morphology: str) -> bool:
    tail = morphology.split(",", 1)[-1]
    return bool(re.search(r"(?:^|:)V", tail)) or morphology.startswith("Gr,V")


def _is_pronoun(morphology: str) -> bool:
    return morphology.startswith("Gr,R") or bool(re.search(r"(?:^|:)P[prd]?", morphology.split(",", 1)[-1]))


def _encodes_person_number(morphology: str) -> bool:
    if not _is_verb(morphology):
        return False
    return bool(
        re.search(r",V,[A-Z]*[123],,[SPD],", morphology)
        or re.search(r",[123][A-Z]?,,[SPD],", morphology)
        or re.search(r"V[^,:]*[123][mfc]?[sdp]", morphology, re.IGNORECASE)
    )


def _is_function_word(lemma: str, morphology: str) -> bool:
    if lemma in _GREEK_FUNCTION or lemma in _SEMITIC_FUNCTION:
        return True
    return morphology.startswith(("Gr,E", "Gr,C", "Gr,P", "Gr,D", "Gr,T"))


def _confidence(value: float = 1.0) -> ConfidenceScore:
    return ConfidenceScore(value, value, POLICY.confidence_policy_version, POLICY.calibration_version)


def _range_refs(start_chapter: str, start_verse: str, end_chapter: str, end_verse: str) -> list[tuple[str, str]]:
    sc, ec = int(start_chapter), int(end_chapter or start_chapter)
    sv, ev = int(start_verse), int(end_verse or start_verse)
    if (ec, ev) < (sc, sv):
        raise FoundationValidationError("Invalid source semantic range")
    result: list[tuple[str, str]] = []
    for chapter in range(sc, ec + 1):
        low = sv if chapter == sc else 1
        high = ev if chapter == ec else 200
        result.extend((str(chapter), str(verse)) for verse in range(low, high + 1))
    return result


class SourceSemanticInventory:
    def __init__(self, runtime: Any):
        self.runtime = runtime
        self.repository: FoundationRepository = runtime.repository
        self.project_id = runtime.project_id
        self.book = runtime.book
        self.resource = resource_for_book(self.book)
        if self.resource is None:
            raise FoundationValidationError(
                f"No pinned UHB/UGNT source resource is available for {self.book}"
            )

    def _help_paths(self) -> tuple[Path | None, Path | None, Path | None]:
        root = bundled_resources_root() / "en" / "translationHelps"
        tn = root / "translationNotes" / "v90_unfoldingWord" / f"tn_{self.book}.tsv"
        twl = root / "translationWordsLinks" / "v90_unfoldingWord" / f"twl_{self.book}.tsv"
        tw_manifest = root / "translationWords" / "v90_unfoldingWord" / "manifest.yaml"
        return (tn if tn.is_file() else None, twl if twl.is_file() else None,
                tw_manifest if tw_manifest.is_file() else None)

    def _fingerprint(self, canonical_refs: list[str]) -> str:
        tn, twl, tw = self._help_paths()
        return _json_hash({
            "resourceId": self.resource.resource_id,
            "resourceVersion": self.resource.version,
            "resourceHash": self.resource.provenance_sha256,
            "tokenizationVersion": SOURCE_TOKENIZATION_VERSION,
            "inventoryEngineVersion": INVENTORY_ENGINE_VERSION,
            "auditPolicyVersion": AUDIT_POLICY_VERSION,
            "translationNotesHash": _file_hash(tn),
            "translationWordsLinksHash": _file_hash(twl),
            "translationWordsManifestHash": _file_hash(tw),
            "canonicalReferences": canonical_refs,
        })

    @staticmethod
    def _read_tsv(path: Path | None) -> list[dict[str, str]]:
        if path is None:
            return []
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle, delimiter="\t"))

    def _ensure_token(
        self, *, chapter: str, verse: str, index: int, raw: dict[str, Any],
    ) -> tuple[dict[str, Any], str, str]:
        displayed = f"{self.book} {chapter}:{verse}"
        canonical = displayed
        morphology = str(raw.get("morph") or "")
        language = _language_id(self.resource, morphology)
        upstream = "/".join((
            self.resource.resource_id, self.resource.version, self.book,
            f"{chapter}:{verse}", str(index), str(raw.get("occurrence") or 1),
        ))
        lineage_id = "source-lineage-" + _sha("\u241f".join((
            self.resource.resource_id, self.resource.version, self.resource.provenance_sha256,
            self.book, canonical, upstream, TokenLayer.ORTHOGRAPHIC.value,
        )))[:32]
        instance_id = "source-token-" + _sha("\u241f".join((
            lineage_id, str(raw.get("word") or ""), str(raw.get("lemma") or ""),
            str(raw.get("strong") or ""), morphology, SOURCE_TOKENIZATION_VERSION,
        )))[:32]
        try:
            self.repository.token_instance(instance_id)
        except FoundationValidationError:
            lineage = TokenLineage(
                id=lineage_id, side=TokenSide.SOURCE, project_id=None,
                logical_resource_id=f"{self.resource.owner}/{self.resource.resource_id}",
                book=self.book, canonical_reference_scope=(canonical,),
                token_layer=TokenLayer.ORTHOGRAPHIC, upstream_identity=upstream,
                created_at="resource-pinned", provenance=SemanticUnitProvenance.CANONICAL_RESOURCE,
            )
            try:
                self.repository.save_token_lineage(lineage)
            except Exception:
                # A content-addressed lineage may already have been created by
                # an overlapping source range in this same companion DB.
                pass
            instance = TokenInstance(
                id=instance_id, lineage_id=lineage_id, side=TokenSide.SOURCE,
                project_id=None, resource_id=self.resource.resource_id,
                resource_version=self.resource.version,
                resource_hash=self.resource.provenance_sha256, text_revision=None,
                book=self.book, displayed_reference=displayed,
                canonical_references=(canonical,), index=index,
                occurrence=int(raw.get("occurrence") or 1),
                occurrences=int(raw.get("occurrences") or 1), span=None,
                raw_form=str(raw.get("word") or ""),
                normalized_form=_normalized(str(raw.get("word") or "")),
                normalization_profile="NFC-remove-word-joiner-v1",
                tokenization_version=SOURCE_TOKENIZATION_VERSION,
                token_layer=TokenLayer.ORTHOGRAPHIC, token_kind=TokenKind.WORD,
                parent_instance_id=None, instance_fingerprint=_sha(instance_id),
                lemma=str(raw.get("lemma") or "") or None,
                strong=str(raw.get("strong") or "") or None,
                morphology=morphology or None,
                morphological_features={"languageId": language, "rawMorphology": morphology},
            )
            self.repository.save_token_instance(instance)
        wire = self.repository.token_instance(instance_id)
        wire["languageId"] = language
        wire["upstreamIdentity"] = upstream
        return wire, language, upstream

    @staticmethod
    def _match_quote(tokens: list[dict[str, Any]], quote: str, occurrence: int) -> list[dict[str, Any]]:
        pieces = [_quote_form(item) for item in quote.split() if _quote_form(item)]
        if not pieces:
            return []
        matches: list[list[dict[str, Any]]] = []
        forms = [_quote_form(str(token.get("rawForm") or "")) for token in tokens]
        for index in range(0, len(forms) - len(pieces) + 1):
            if forms[index:index + len(pieces)] == pieces:
                matches.append(tokens[index:index + len(pieces)])
        selected = occurrence - 1
        return matches[selected] if 0 <= selected < len(matches) else []

    def _save_evidence(
        self, *, kind: EvidenceKind, resource_id: str, resource_version: str,
        resource_hash: str, occurrence_id: str, reference: str, content: str,
        status: ResourceValidationStatus,
    ) -> str:
        evidence_id = "source-evidence-" + _sha("\u241f".join((
            kind.value, resource_id, resource_version, resource_hash, occurrence_id,
        )))[:32]
        try:
            self.repository.evidence_record(evidence_id)
            return evidence_id
        except FoundationValidationError:
            pass
        record = EvidenceRecord(
            id=evidence_id, project_id=self.project_id, book=self.book, kind=kind,
            resource_id=resource_id, resource_version=resource_version,
            resource_hash=resource_hash, occurrence_id=occurrence_id,
            displayed_references=(reference,), canonical_references=(reference,),
            content=content, content_hash=_sha(content), validation_status=status,
            source_semantic_unit_ids=(), target_semantic_unit_ids=(),
            policy_binding=POLICY, review_status=ReviewStatus.UNREVIEWED,
            lifecycle_status=LifecycleStatus.ACTIVE,
        )
        self.repository.save_evidence_record(record)
        return evidence_id

    def _enrichment(
        self, refs: set[str], by_ref: dict[str, list[dict[str, Any]]],
    ) -> tuple[dict[str, list[str]], list[dict[str, Any]], list[dict[str, Any]]]:
        tn_path, twl_path, _ = self._help_paths()
        attached: dict[str, list[str]] = defaultdict(list)
        evidence: list[dict[str, Any]] = []
        interpretations: list[dict[str, Any]] = []
        tw_root = bundled_resources_root() / "en" / "translationHelps" / "translationWords" / "v90_unfoldingWord" / "bible"
        for row in self._read_tsv(twl_path):
            reference = f"{self.book} {row.get('Reference', '')}"
            if reference not in refs:
                continue
            matched = self._match_quote(
                by_ref[reference], row.get("OrigWords", ""), int(row.get("Occurrence") or 1),
            )
            status = ResourceValidationStatus.SUPPORTING if matched else ResourceValidationStatus.CONFLICTING
            twl_id = self._save_evidence(
                kind=EvidenceKind.TRANSLATION_WORD_LIST, resource_id="en_twl",
                resource_version="v90_unfoldingWord", resource_hash=_file_hash(twl_path),
                occurrence_id=f"{self.book}:{row.get('ID', '')}", reference=reference,
                content=json.dumps(row, ensure_ascii=False, sort_keys=True), status=status,
            )
            evidence.append(self.repository.evidence_record(twl_id))
            category = _category_from_twlink(row.get("TWLink", ""))
            concept = _term_from_twlink(row.get("TWLink", ""))
            tw_path = tw_root / category / f"{concept}.md"
            tw_content = tw_path.read_text(encoding="utf-8") if tw_path.is_file() else ""
            tw_id = self._save_evidence(
                kind=EvidenceKind.TRANSLATION_WORD, resource_id=f"en_tw:{category}/{concept}",
                resource_version="v90_unfoldingWord", resource_hash=_file_hash(tw_path),
                occurrence_id=f"{category}/{concept}", reference=reference,
                content=tw_content, status=status,
            )
            evidence.append(self.repository.evidence_record(tw_id))
            for token in matched:
                attached[token["id"]].extend((twl_id, tw_id))
                token.setdefault("translationWordConceptIds", []).append(f"{category}/{concept}")
                if category == "names":
                    interpretations.append({
                        "kind": "PARTICIPANT", "tokens": [token], "evidenceIds": [twl_id, tw_id],
                        "feature": {"conceptId": f"{category}/{concept}"},
                    })
        for row in self._read_tsv(tn_path):
            reference = f"{self.book} {row.get('Reference', '')}"
            if reference not in refs:
                continue
            matched = self._match_quote(
                by_ref[reference], row.get("Quote", ""), int(row.get("Occurrence") or 1),
            )
            status = ResourceValidationStatus.SUPPORTING if matched else ResourceValidationStatus.CONFLICTING
            evidence_id = self._save_evidence(
                kind=EvidenceKind.TRANSLATION_NOTE, resource_id="en_tn",
                resource_version="v90_unfoldingWord", resource_hash=_file_hash(tn_path),
                occurrence_id=f"{self.book}:{row.get('ID', '')}", reference=reference,
                content=json.dumps(row, ensure_ascii=False, sort_keys=True), status=status,
            )
            evidence.append(self.repository.evidence_record(evidence_id))
            if matched:
                for token in matched:
                    attached[token["id"]].append(evidence_id)
                support = row.get("SupportReference", "")
                slug = support.rstrip("/").rsplit("/", 1)[-1]
                if slug.startswith("grammar-connect"):
                    kind = "CLAUSE_RELATION"
                elif "idiom" in slug:
                    kind = "IDIOM"
                elif slug in {"figs-explicit", "figs-ellipsis"}:
                    kind = "IMPLICIT_GRAMMATICAL"
                else:
                    kind = "CONSTRUCTION"
                interpretations.append({
                    "kind": kind, "tokens": matched, "evidenceIds": [evidence_id],
                    "feature": {"supportReference": row.get("SupportReference", ""), "noteId": row.get("ID", "")},
                })
        unique = {item["id"]: item for item in evidence}
        return attached, list(unique.values()), interpretations

    def _unit(
        self, *, kind: SemanticUnitKind, tokens: list[dict[str, Any]], suffix: str,
        obligation: SemanticObligationStrength, eligibility: AuditEligibility,
        role: CoverageAccountingRole, dimension: CoverageDimension,
        owner_id: str | None = None, provenance: SemanticUnitProvenance = SemanticUnitProvenance.DETERMINISTIC_RULE,
        evidence_ids: Iterable[str] = (), features: dict[str, str] | None = None,
    ) -> SourceSemanticUnit:
        token_ids = tuple(token["id"] for token in tokens)
        semantic_features = {**(features or {}), "inventoryRule": suffix}
        semantic_fingerprint = _json_hash({
            "kind": kind.value, "tokens": token_ids, "suffix": suffix,
            "features": semantic_features, "policy": AUDIT_POLICY_VERSION,
        })
        unit_id = "source-unit-" + semantic_fingerprint[:32]
        return SourceSemanticUnit(
            id=unit_id, side=TokenSide.SOURCE, project_id=self.project_id, book=self.book,
            kind=kind, displayed_references=tuple(dict.fromkeys(t["displayedReference"] for t in tokens)),
            canonical_references=tuple(dict.fromkeys(r for t in tokens for r in t["canonicalReferences"])),
            token_instance_ids=token_ids,
            token_lineage_ids=tuple(dict.fromkeys(t["lineageId"] for t in tokens)),
            raw_surface=" ".join(str(t["rawForm"]) for t in tokens),
            normalized_surface=" ".join(str(t["normalizedForm"]) for t in tokens),
            semantic_features=semantic_features, unit_confidence=_confidence(), provenance=provenance,
            evidence_ids=tuple(dict.fromkeys(evidence_ids)), resource_validation_ids=(),
            audit_eligibility=eligibility, semantic_obligation=obligation,
            accounting_role=role, audit_owner_unit_id=owner_id or unit_id,
            coverage_dimension=dimension, semantic_fingerprint=semantic_fingerprint,
            policy_binding=POLICY, review_status=ReviewStatus.UNREVIEWED,
            lifecycle_status=LifecycleStatus.ACTIVE,
        )

    def _save_unit(self, unit: SourceSemanticUnit) -> dict[str, Any]:
        try:
            existing = self.repository.semantic_unit(unit.id)
            if existing.get("semanticFingerprint") != unit.semantic_fingerprint:
                raise FoundationValidationError("Source semantic unit fingerprint collision")
            return existing
        except FoundationValidationError as exc:
            if "fingerprint collision" in str(exc):
                raise
        self.repository.save_semantic_unit(unit)
        return self.repository.semantic_unit(unit.id)

    def build_range(
        self, start_chapter: str, start_verse: str,
        end_chapter: str = "", end_verse: str = "",
    ) -> dict[str, Any]:
        refs_and_raw: list[tuple[str, str, list[dict[str, Any]]]] = []
        for chapter, verse in _range_refs(start_chapter, start_verse, end_chapter, end_verse):
            raw = source_tokens_for_verse(self.book, chapter, verse)
            if raw:
                refs_and_raw.append((chapter, verse, raw))
        if not refs_and_raw:
            raise FoundationValidationError("The pinned source resource contains no tokens for this range")
        canonical_refs = [f"{self.book} {chapter}:{verse}" for chapter, verse, _ in refs_and_raw]
        range_key = f"{canonical_refs[0]}..{canonical_refs[-1]}"
        fingerprint = self._fingerprint(canonical_refs)
        cached = self.repository.source_inventory_for_fingerprint(
            self.project_id, self.book, range_key, fingerprint,
        )
        if cached is not None:
            cached["cacheStatus"] = "HIT"
            return cached

        lock = self.repository.source_lock(self.project_id, self.book)
        if lock is None or lock["resource_hash"] != self.resource.provenance_sha256:
            raise FoundationValidationError("Pinned source resource does not match project source resource lock")

        tokens: list[dict[str, Any]] = []
        by_ref: dict[str, list[dict[str, Any]]] = defaultdict(list)
        token_rows: list[tuple[str, str, str]] = []
        for chapter, verse, raw_tokens in refs_and_raw:
            for index, raw in enumerate(raw_tokens):
                token, language, upstream = self._ensure_token(
                    chapter=chapter, verse=verse, index=index, raw=raw,
                )
                tokens.append(token); by_ref[token["displayedReference"]].append(token)
                token_rows.append((token["id"], language, upstream))

        attached, evidence, interpretations = self._enrichment(set(canonical_refs), by_ref)
        units: list[dict[str, Any]] = []
        lexical_owner: dict[str, str] = {}
        dependency_rows: list[tuple[str, str, str]] = []
        for token in tokens:
            lemma = _normalized(str(token.get("lemma") or ""))
            morph = str(token.get("morphology") or "")
            function = _is_function_word(lemma, morph)
            lexical = self._unit(
                kind=SemanticUnitKind.LEXICAL, tokens=[token], suffix="lexical",
                obligation=(SemanticObligationStrength.CONTEXT_DEPENDENT if function
                            else SemanticObligationStrength.REQUIRED),
                eligibility=(AuditEligibility.CONDITIONAL if function else AuditEligibility.ELIGIBLE),
                role=CoverageAccountingRole.PRIMARY, dimension=CoverageDimension.LEXICAL_CONTENT,
                provenance=SemanticUnitProvenance.CANONICAL_RESOURCE,
                evidence_ids=attached.get(token["id"], ()),
                features={"lemma": lemma, "strong": str(token.get("strong") or ""),
                          "languageId": str(token.get("languageId") or "")},
            )
            lexical_wire = self._save_unit(lexical); units.append(lexical_wire)
            lexical_owner[token["id"]] = lexical.id

            if morph:
                morphological = self._unit(
                    kind=SemanticUnitKind.MORPHOLOGICAL, tokens=[token], suffix="morphology",
                    obligation=SemanticObligationStrength.GRAMMATICAL,
                    eligibility=AuditEligibility.CONDITIONAL, role=CoverageAccountingRole.COMPONENT,
                    dimension=(CoverageDimension.TEMPORAL_ASPECTUAL if _is_verb(morph)
                               else CoverageDimension.OTHER), owner_id=lexical.id,
                    features={"morphology": morph, "languageId": str(token["languageId"])},
                )
                units.append(self._save_unit(morphological))
                dependency_rows.append((lexical.id, morphological.id, "CONTAINS"))

            if lemma in _GREEK_NEGATION or lemma in _SEMITIC_NEGATION:
                negation = self._unit(
                    kind=SemanticUnitKind.NEGATION, tokens=[token], suffix="explicit-negation",
                    obligation=SemanticObligationStrength.REQUIRED,
                    eligibility=AuditEligibility.ELIGIBLE, role=CoverageAccountingRole.PRIMARY,
                    dimension=CoverageDimension.POLARITY,
                    features={"polarity": "NEGATIVE", "lemma": lemma},
                )
                units.append(self._save_unit(negation))
                dependency_rows.append((lexical.id, negation.id, "REFINES"))

            if lemma in _GREEK_QUANTIFIERS or lemma in _SEMITIC_QUANTIFIERS:
                quantifier = self._unit(
                    kind=SemanticUnitKind.QUANTIFIER, tokens=[token], suffix="explicit-quantifier",
                    obligation=SemanticObligationStrength.REQUIRED,
                    eligibility=AuditEligibility.ELIGIBLE, role=CoverageAccountingRole.PRIMARY,
                    dimension=CoverageDimension.QUANTITY, features={"quantifierLemma": lemma},
                )
                units.append(self._save_unit(quantifier))
                dependency_rows.append((lexical.id, quantifier.id, "REFINES"))

            if _is_pronoun(morph):
                referent = self._unit(
                    kind=SemanticUnitKind.REFERENT, tokens=[token], suffix="pronoun-referent",
                    obligation=SemanticObligationStrength.CONTEXT_DEPENDENT,
                    eligibility=AuditEligibility.CONDITIONAL, role=CoverageAccountingRole.COMPONENT,
                    dimension=CoverageDimension.REFERENT, owner_id=lexical.id,
                    features={"referentStatus": "UNRESOLVED_PRONOUN"},
                )
                units.append(self._save_unit(referent))
                dependency_rows.append((lexical.id, referent.id, "CONTAINS"))

            if _is_verb(morph):
                predicate = self._unit(
                    kind=SemanticUnitKind.PREDICATE, tokens=[token], suffix="verbal-predicate",
                    obligation=SemanticObligationStrength.DERIVED,
                    eligibility=AuditEligibility.AGGREGATE_ONLY, role=CoverageAccountingRole.AGGREGATE,
                    dimension=CoverageDimension.PREDICATION, owner_id=lexical.id,
                    features={"predicateBasis": "CANONICAL_VERBAL_MORPHOLOGY"},
                )
                units.append(self._save_unit(predicate))
                dependency_rows.append((predicate.id, lexical.id, "DERIVED_FROM"))

            if _encodes_person_number(morph):
                grammatical = self._unit(
                    kind=SemanticUnitKind.IMPLICIT_GRAMMATICAL, tokens=[token],
                    suffix="verb-person-number",
                    obligation=SemanticObligationStrength.GRAMMATICAL,
                    eligibility=AuditEligibility.CONDITIONAL,
                    role=CoverageAccountingRole.COMPONENT,
                    dimension=CoverageDimension.PARTICIPANT, owner_id=lexical.id,
                    features={"contribution": "VERB_PERSON_NUMBER", "morphology": morph},
                )
                units.append(self._save_unit(grammatical))
                dependency_rows.append((lexical.id, grammatical.id, "CONTAINS"))

            if token.get("languageId") in {"hbo", "arc"} and ":" in morph:
                construction = self._unit(
                    kind=SemanticUnitKind.CONSTRUCTION, tokens=[token],
                    suffix="semitic-clitic-bundle",
                    obligation=SemanticObligationStrength.GRAMMATICAL,
                    eligibility=AuditEligibility.CONDITIONAL,
                    role=CoverageAccountingRole.COMPONENT,
                    dimension=CoverageDimension.OTHER, owner_id=lexical.id,
                    features={"construction": "SEMITIC_CLITIC_BUNDLE", "morphology": morph},
                )
                units.append(self._save_unit(construction))
                dependency_rows.append((lexical.id, construction.id, "CONTAINS"))

            if lemma in _TEMPORAL_LEMMAS:
                temporal = self._unit(
                    kind=SemanticUnitKind.TEMPORAL, tokens=[token], suffix="lexical-temporal",
                    obligation=SemanticObligationStrength.CONTEXT_DEPENDENT,
                    eligibility=AuditEligibility.CONDITIONAL, role=CoverageAccountingRole.COMPONENT,
                    dimension=CoverageDimension.TEMPORAL_ASPECTUAL, owner_id=lexical.id,
                    features={"temporalLemma": lemma},
                )
                units.append(self._save_unit(temporal))
                dependency_rows.append((lexical.id, temporal.id, "CONTAINS"))

        for item in interpretations:
            item_tokens = item["tokens"]
            owner = lexical_owner[item_tokens[0]["id"]]
            kind = SemanticUnitKind(item["kind"])
            enriched = self._unit(
                kind=kind, tokens=item_tokens,
                suffix="resource:" + _json_hash(item["feature"])[:12],
                obligation=SemanticObligationStrength.UNCERTAIN,
                eligibility=AuditEligibility.REVIEW_ONLY,
                role=CoverageAccountingRole.EVIDENCE_ONLY,
                dimension=(CoverageDimension.PARTICIPANT if kind == SemanticUnitKind.PARTICIPANT
                           else CoverageDimension.OTHER), owner_id=owner,
                provenance=SemanticUnitProvenance.RESOURCE_ENRICHED,
                evidence_ids=item["evidenceIds"], features=item["feature"],
            )
            units.append(self._save_unit(enriched))
            dependency_rows.append((owner, enriched.id, "CONTAINS"))

        for parent, child, relation in dependency_rows:
            try:
                self.repository.add_dependency(parent, child, relation)
            except Exception as exc:
                if "UNIQUE constraint failed" not in str(exc):
                    raise

        # One active account per independent owner/dimension/fingerprint.
        primary_units = [
            unit for unit in units
            if unit["accountingRole"] == "PRIMARY" and unit["auditEligibility"] == "ELIGIBLE"
        ]
        coverage: list[dict[str, Any]] = []
        inventory_id = "source-inventory-" + fingerprint[:32]
        for unit in primary_units:
            account_fingerprint = _json_hash({
                "owner": unit["auditOwnerUnitId"], "dimension": unit["coverageDimension"],
                "semantic": unit["semanticFingerprint"], "policy": AUDIT_POLICY_VERSION,
            })
            account = SemanticCoverageAccount(
                id="source-coverage-" + _sha(inventory_id + account_fingerprint)[:32],
                project_id=self.project_id, passage_id=inventory_id,
                direction=AuditDirection.SOURCE_COVERAGE,
                audit_owner_unit_id=unit["auditOwnerUnitId"], member_unit_ids=(unit["id"],),
                coverage_dimension=CoverageDimension(unit["coverageDimension"]),
                semantic_fingerprint=account_fingerprint, covered_by_relationship_ids=(),
                excluded_duplicate_unit_ids=tuple(
                    other["id"] for other in units
                    if other["auditOwnerUnitId"] == unit["auditOwnerUnitId"]
                    and other["id"] != unit["id"]
                ), finding_id=None, policy_binding=POLICY,
                review_status=ReviewStatus.UNREVIEWED, lifecycle_status=LifecycleStatus.ACTIVE,
            )
            self.repository.save_coverage_account(account)
            coverage.append({
                "id": account.id, "auditOwnerUnitId": account.audit_owner_unit_id,
                "memberUnitIds": list(account.member_unit_ids),
                "coverageDimension": account.coverage_dimension.value,
                "semanticFingerprint": account.semantic_fingerprint,
                "excludedDuplicateUnitIds": list(account.excluded_duplicate_unit_ids),
            })

        represented = {token_id for unit in units for token_id in unit["tokenInstanceIds"]}
        diagnostics = {
            "sourceTokenInstances": len(tokens),
            "sourceTokensRepresented": len(represented),
            "requiredSemanticObligations": sum(u["semanticObligation"] == "REQUIRED" and u["accountingRole"] == "PRIMARY" for u in units),
            "conditionalObligations": sum(u["semanticObligation"] == "CONTEXT_DEPENDENT" for u in units),
            "grammaticalObligations": sum(u["semanticObligation"] == "GRAMMATICAL" for u in units),
            "derivedAggregateUnits": sum(u["accountingRole"] == "AGGREGATE" for u in units),
            "excludedUnits": sum(u["auditEligibility"] == "EXCLUDED" for u in units),
            "reviewOnlyUnits": sum(u["auditEligibility"] == "REVIEW_ONLY" for u in units),
            "resourceEnrichedUnits": sum(u["provenance"] == "RESOURCE_ENRICHED" for u in units),
            "resourceConflicts": sum(e["validationStatus"] == "CONFLICTING" for e in evidence),
        }
        if diagnostics["sourceTokensRepresented"] != diagnostics["sourceTokenInstances"]:
            raise FoundationValidationError("Every canonical source token must be represented")
        source_semantic_fingerprint = _json_hash([
            (unit["kind"], unit["semanticFingerprint"]) for unit in units
        ])
        payload = {
            "id": inventory_id, "book": self.book, "rangeKey": range_key,
            "canonicalReferences": canonical_refs, "fingerprint": fingerprint,
            "sourceSemanticFingerprint": source_semantic_fingerprint,
            "sourceResource": self.resource.to_dict(),
            "inventoryEngineVersion": INVENTORY_ENGINE_VERSION,
            "sourceTokenizationVersion": SOURCE_TOKENIZATION_VERSION,
            "policyBinding": {
                "confidencePolicyVersion": POLICY.confidence_policy_version,
                "calibrationVersion": POLICY.calibration_version,
                "auditPolicyVersion": POLICY.audit_policy_version,
            },
            "tokens": tokens, "units": units, "coverageAccounts": coverage,
            "evidence": evidence, "diagnostics": diagnostics, "cacheStatus": "MISS",
        }
        self._validate_payload(payload)
        self.repository.save_source_inventory(
            inventory_id=inventory_id, project_id=self.project_id, book=self.book,
            range_key=range_key, fingerprint=fingerprint,
            source_resource_id=self.resource.resource_id,
            source_resource_version=self.resource.version,
            source_resource_hash=self.resource.provenance_sha256,
            audit_policy_version=AUDIT_POLICY_VERSION, diagnostics=diagnostics,
            payload=payload, token_rows=token_rows,
            unit_ids=[unit["id"] for unit in units], evidence_ids=[item["id"] for item in evidence],
        )
        return payload

    def get_range(self, inventory_id: str) -> dict[str, Any]:
        payload = self.repository.source_inventory(inventory_id)
        try:
            self._validate_payload(payload)
        except FoundationValidationError as exc:
            self.repository.quarantine_source_inventory(inventory_id, str(exc), payload)
            raise
        return payload

    def _validate_payload(self, payload: dict[str, Any]) -> None:
        tokens = payload.get("tokens") if isinstance(payload.get("tokens"), list) else []
        units = payload.get("units") if isinstance(payload.get("units"), list) else []
        accounts = payload.get("coverageAccounts") if isinstance(payload.get("coverageAccounts"), list) else []
        token_ids = {str(token.get("id") or "") for token in tokens if isinstance(token, dict)}
        unit_ids = {str(unit.get("id") or "") for unit in units if isinstance(unit, dict)}
        evidence_ids = {
            str(item.get("id") or "") for item in payload.get("evidence", [])
            if isinstance(item, dict)
        }
        if not token_ids or len(token_ids) != len(tokens):
            raise FoundationValidationError("Source inventory has missing or duplicate token identities")
        source = payload.get("sourceResource") if isinstance(payload.get("sourceResource"), dict) else {}
        for token in tokens:
            if (
                token.get("side") != "SOURCE"
                or token.get("resourceId") != source.get("resourceId")
                or token.get("resourceVersion") != source.get("version")
                or token.get("resourceHash") != source.get("provenanceSha256")
            ):
                raise FoundationValidationError("Source token does not match the inventory resource lock")
        represented: set[str] = set()
        for unit in units:
            try:
                SemanticUnitKind(str(unit["kind"]))
                AuditEligibility(str(unit["auditEligibility"]))
                SemanticObligationStrength(str(unit["semanticObligation"]))
                CoverageAccountingRole(str(unit["accountingRole"]))
                CoverageDimension(str(unit["coverageDimension"]))
            except (KeyError, ValueError) as exc:
                raise FoundationValidationError("Source inventory contains an uncontrolled semantic enum") from exc
            if unit.get("side") != "SOURCE":
                raise FoundationValidationError("Source inventory contains a non-source semantic unit")
            member_tokens = {str(item) for item in unit.get("tokenInstanceIds", [])}
            if not member_tokens <= token_ids:
                raise FoundationValidationError("Source semantic unit references an invalid token instance")
            represented.update(member_tokens)
            if str(unit.get("auditOwnerUnitId") or "") not in unit_ids:
                raise FoundationValidationError("Source semantic unit references an invalid audit owner")
            if not {str(item) for item in unit.get("evidenceIds", [])} <= evidence_ids:
                raise FoundationValidationError("Source semantic unit references missing resource evidence")
            features = unit.get("semanticFeatures") if isinstance(unit.get("semanticFeatures"), dict) else {}
            suffix = str(features.get("inventoryRule") or "")
            expected = _json_hash({
                "kind": unit["kind"], "tokens": list(unit.get("tokenInstanceIds", [])),
                "suffix": suffix, "features": features,
                "policy": payload.get("policyBinding", {}).get("auditPolicyVersion"),
            })
            if unit.get("semanticFingerprint") != expected:
                raise FoundationValidationError("Source semantic fingerprint is not reproducible")
        if represented != token_ids:
            raise FoundationValidationError("Every canonical source token must be represented")
        coverage_keys: set[tuple[str, str, str]] = set()
        for account in accounts:
            key = (
                str(account.get("auditOwnerUnitId") or ""),
                str(account.get("coverageDimension") or ""),
                str(account.get("semanticFingerprint") or ""),
            )
            if key in coverage_keys or key[0] not in unit_ids:
                raise FoundationValidationError("Source coverage accounts are duplicate or invalid")
            coverage_keys.add(key)

    def get_unit(self, unit_id: str) -> dict[str, Any]:
        return self.repository.semantic_unit(unit_id)

    def get_coverage_accounts(self, inventory_id: str) -> list[dict[str, Any]]:
        return self.get_range(inventory_id)["coverageAccounts"]

    def get_diagnostics(self, inventory_id: str) -> dict[str, Any]:
        return self.get_range(inventory_id)["diagnostics"]
