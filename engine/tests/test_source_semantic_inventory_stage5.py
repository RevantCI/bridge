from __future__ import annotations

import json
from pathlib import Path

import pytest

import tc_ai_bridge.source_semantic_inventory as inventory_module
from bridge_service import BridgeEngine
from greek_room_engine.protocol import EngineRequest
from tc_ai_bridge.passage_semantic_models import PolicyBinding
from tc_ai_bridge.passage_semantic_repository import FoundationValidationError
from tc_ai_bridge.passage_semantic_runtime import PassageSemanticRuntime
from tc_ai_bridge.source_semantic_inventory import SourceSemanticInventory
from tc_ai_bridge.tc_project import TranslationCoreProject


def _project(root: Path, book: str, language: str = "tam") -> TranslationCoreProject:
    lower = book.lower()
    (root / lower).mkdir(parents=True)
    (root / ".apps" / "translationCore" / "alignmentData" / lower).mkdir(parents=True)
    (root / "manifest.json").write_text(json.dumps({
        "project": {"id": lower, "name": book},
        "target_language": {"id": language, "name": language},
        "resource": {"id": "test", "name": "Test"},
        "tc_version": "8",
    }), encoding="utf-8")
    (root / lower / "1.json").write_text(json.dumps({"1": "target text"}), encoding="utf-8")
    (root / ".apps" / "translationCore" / "alignmentData" / lower / "1.json").write_text(
        json.dumps({"1": {"alignments": [], "wordBank": []}}), encoding="utf-8",
    )
    return TranslationCoreProject(root)


def _inventory(tmp_path: Path, book: str, language: str = "tam") -> SourceSemanticInventory:
    project = _project(tmp_path / f"{book}-{language}", book, language)
    runtime = PassageSemanticRuntime(project, f"project-{book}-{language}")
    return SourceSemanticInventory(runtime)


def test_php_range_accounts_for_every_source_token_and_is_cached(tmp_path: Path) -> None:
    inventory = _inventory(tmp_path, "PHP")
    first = inventory.build_range("1", "3", "1", "6")
    second = inventory.build_range("1", "3", "1", "6")

    assert first["fingerprint"] == second["fingerprint"]
    assert second["cacheStatus"] == "HIT"
    assert first["diagnostics"]["sourceTokenInstances"] > 0
    assert first["diagnostics"]["sourceTokensRepresented"] == first["diagnostics"]["sourceTokenInstances"]
    assert first["diagnostics"]["requiredSemanticObligations"] > 0
    assert any(unit["kind"] == "QUANTIFIER" for unit in first["units"])
    assert any(unit["kind"] == "PREDICATE" for unit in first["units"])
    assert first["diagnostics"]["resourceEnrichedUnits"] > 0


def test_function_word_is_inventoried_but_not_automatically_an_independent_obligation(
    tmp_path: Path,
) -> None:
    result = _inventory(tmp_path, "PHP").build_range("1", "3")
    article_token = next(token for token in result["tokens"] if token["lemma"] == "ὁ")
    units = [unit for unit in result["units"] if article_token["id"] in unit["tokenInstanceIds"]]
    assert units
    assert not any(
        unit["semanticObligation"] == "REQUIRED" and unit["accountingRole"] == "PRIMARY"
        for unit in units
    )


def test_explicit_negation_and_quantifier_have_independent_coverage_dimensions(
    tmp_path: Path,
) -> None:
    # Greek Matthew 5:17 contains μὴ; Philippians 1:3 contains πάσῃ.
    negated = _inventory(tmp_path, "MAT").build_range("5", "17")
    quantified = _inventory(tmp_path, "PHP").build_range("1", "3")
    negation = next(unit for unit in negated["units"] if unit["kind"] == "NEGATION")
    quantifier = next(unit for unit in quantified["units"] if unit["kind"] == "QUANTIFIER")
    assert (negation["semanticObligation"], negation["coverageDimension"]) == ("REQUIRED", "POLARITY")
    assert (quantifier["semanticObligation"], quantifier["coverageDimension"]) == ("REQUIRED", "QUANTITY")
    assert negation["auditOwnerUnitId"] == negation["id"]
    assert quantifier["auditOwnerUnitId"] == quantifier["id"]


def test_morphology_and_pronoun_reference_are_conservative(tmp_path: Path) -> None:
    result = _inventory(tmp_path, "PHP").build_range("1", "3")
    morphology = [unit for unit in result["units"] if unit["kind"] == "MORPHOLOGICAL"]
    referents = [unit for unit in result["units"] if unit["kind"] == "REFERENT"]
    assert morphology and all(unit["semanticObligation"] == "GRAMMATICAL" for unit in morphology)
    assert referents and all(unit["auditEligibility"] in {"CONDITIONAL", "REVIEW_ONLY"} for unit in referents)
    assert any(unit["kind"] == "IMPLICIT_GRAMMATICAL" for unit in result["units"])


def test_hebrew_and_genuine_aramaic_tokens_preserve_language_and_morphology(tmp_path: Path) -> None:
    hebrew = _inventory(tmp_path, "GEN").build_range("1", "1")
    aramaic = _inventory(tmp_path, "DAN").build_range("2", "4")
    assert {token["languageId"] for token in hebrew["tokens"]} == {"hbo"}
    assert "arc" in {token["languageId"] for token in aramaic["tokens"]}
    aramaic_token = next(token for token in aramaic["tokens"] if token["languageId"] == "arc")
    assert aramaic_token["morphology"].startswith("Ar,")
    assert any(aramaic_token["id"] in unit["tokenInstanceIds"] for unit in aramaic["units"])
    assert any(
        unit["kind"] == "CONSTRUCTION"
        and unit["semanticFeatures"].get("construction") == "SEMITIC_CLITIC_BUNDLE"
        for unit in hebrew["units"]
    )


def test_inventory_is_target_language_independent(tmp_path: Path) -> None:
    tamil = _inventory(tmp_path, "PHP", "tam").build_range("1", "3", "1", "6")
    french = _inventory(tmp_path, "PHP", "fra").build_range("1", "3", "1", "6")
    assert tamil["sourceSemanticFingerprint"] == french["sourceSemanticFingerprint"]
    assert [(u["kind"], u["semanticFingerprint"]) for u in tamil["units"]] == [
        (u["kind"], u["semanticFingerprint"]) for u in french["units"]
    ]


def test_help_resources_enrich_but_do_not_define_canonical_units(tmp_path: Path) -> None:
    result = _inventory(tmp_path, "PHP").build_range("1", "3", "1", "6")
    kinds = {item["kind"] for item in result["evidence"]}
    assert "TRANSLATION_WORD_LIST" in kinds
    assert "TRANSLATION_WORD" in kinds
    assert "TRANSLATION_NOTE" in kinds
    assert all(unit["provenance"] != "RESOURCE_ENRICHED" for unit in result["units"] if unit["kind"] == "LEXICAL")
    assert any(
        unit["kind"] == "CLAUSE_RELATION" and unit["provenance"] == "RESOURCE_ENRICHED"
        for unit in result["units"]
    )


def test_coverage_accounts_are_unique_and_derived_units_do_not_duplicate_obligations(
    tmp_path: Path,
) -> None:
    result = _inventory(tmp_path, "PHP").build_range("1", "3", "1", "6")
    keys = [
        (account["auditOwnerUnitId"], account["coverageDimension"], account["semanticFingerprint"])
        for account in result["coverageAccounts"]
    ]
    assert len(keys) == len(set(keys))
    assert all(
        unit["accountingRole"] != "AGGREGATE" or unit["auditOwnerUnitId"] != unit["id"]
        for unit in result["units"]
    )


def test_dependency_dag_rejects_cycles_but_semantic_graph_allows_cycles(tmp_path: Path) -> None:
    inventory = _inventory(tmp_path, "PHP")
    result = inventory.build_range("1", "3")
    units = [unit for unit in result["units"] if unit["kind"] == "LEXICAL"][:2]
    repo = inventory.repository
    repo.add_dependency(units[0]["id"], units[1]["id"], "CONTAINS")
    with pytest.raises(FoundationValidationError, match="cycle"):
        repo.add_dependency(units[1]["id"], units[0]["id"], "DEPENDS_ON")
    repo.add_semantic_relation(units[0]["id"], units[1]["id"], "COEXTENSIVE_WITH")
    repo.add_semantic_relation(units[1]["id"], units[0]["id"], "COEXTENSIVE_WITH")


def test_source_lock_mismatch_never_serves_cached_inventory_as_current(tmp_path: Path) -> None:
    inventory = _inventory(tmp_path, "PHP")
    result = inventory.build_range("1", "3")
    inventory.repository.synchronize_source_lock(
        project_id=inventory.project_id, book="PHP", resource_id="ugnt",
        resource_version="changed", resource_hash="0" * 64,
    )
    with pytest.raises(FoundationValidationError, match="source resource lock"):
        inventory.get_range(result["id"])


def test_invalid_persisted_inventory_is_quarantined_not_deleted(tmp_path: Path) -> None:
    inventory = _inventory(tmp_path, "PHP")
    result = inventory.build_range("1", "3")
    damaged = dict(result)
    damaged["units"] = []
    with inventory.repository._connect() as conn:
        conn.execute(
            "UPDATE source_inventory_runs SET payload_json=? WHERE id=?",
            (json.dumps(damaged, ensure_ascii=False), result["id"]),
        )
        conn.commit()
    with pytest.raises(FoundationValidationError, match="Every canonical source token"):
        inventory.get_range(result["id"])
    with inventory.repository._connect() as conn:
        status = conn.execute(
            "SELECT lifecycle_status FROM source_inventory_runs WHERE id=?", (result["id"],),
        ).fetchone()[0]
    assert status == "QUARANTINED"


def test_resource_conflicts_are_preserved_as_review_evidence(tmp_path: Path) -> None:
    inventory = _inventory(tmp_path, "PHP")
    evidence_id = inventory._save_evidence(
        kind=inventory_module.EvidenceKind.TRANSLATION_NOTE,
        resource_id="test-tn", resource_version="v1", resource_hash="0" * 64,
        occurrence_id="PHP:unresolved", reference="PHP 1:3",
        content="An intentionally unresolved resource interpretation",
        status=inventory_module.ResourceValidationStatus.CONFLICTING,
    )
    conflict = inventory.repository.evidence_record(evidence_id)
    assert conflict["validationStatus"] == "CONFLICTING"
    assert conflict["reviewStatus"] == "UNREVIEWED"


def test_audit_policy_change_invalidates_cache_fingerprint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    inventory = _inventory(tmp_path, "PHP")
    first = inventory.build_range("1", "3")
    monkeypatch.setattr(inventory_module, "AUDIT_POLICY_VERSION", "source-inventory-audit-test-v2")
    monkeypatch.setattr(
        inventory_module, "POLICY",
        PolicyBinding("confidence-v1", "calibration-v1", "source-inventory-audit-test-v2"),
    )
    second = inventory.build_range("1", "3")
    assert second["cacheStatus"] == "MISS"
    assert second["fingerprint"] != first["fingerprint"]


def test_minimal_source_semantic_protocol_apis(tmp_path: Path) -> None:
    project = _project(tmp_path / "api-project", "PHP")
    engine = BridgeEngine()
    opened = engine.handle_request(EngineRequest(
        id="open", method="project.open", params={"path": str(project.path)},
    )).to_dict()
    assert opened["success"] is True
    built = engine.handle_request(EngineRequest(
        id="build", method="sourceSemantic.buildRange",
        params={"chapter": "1", "verse": "3", "endChapter": "1", "endVerse": "6"},
    )).to_dict()
    assert built["success"] is True
    inventory_id = built["result"]["id"]
    unit_id = built["result"]["units"][0]["id"]
    assert engine.handle_request(EngineRequest(
        id="get", method="sourceSemantic.getRange", params={"inventoryId": inventory_id},
    )).to_dict()["result"]["id"] == inventory_id
    assert engine.handle_request(EngineRequest(
        id="unit", method="sourceSemantic.getUnit", params={"unitId": unit_id},
    )).to_dict()["result"]["id"] == unit_id
    assert engine.handle_request(EngineRequest(
        id="coverage", method="sourceSemantic.getCoverageAccounts", params={"inventoryId": inventory_id},
    )).to_dict()["result"]
    assert engine.handle_request(EngineRequest(
        id="diagnostics", method="sourceSemantic.getDiagnostics", params={"inventoryId": inventory_id},
    )).to_dict()["result"]["sourceTokensRepresented"] > 0
