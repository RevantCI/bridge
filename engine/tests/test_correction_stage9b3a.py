"""Stage 9B.3a — persistence/recovery foundation, still no correction writer."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3

import pytest
import bridge_service
from bridge_service import BridgeEngine
from greek_room_engine.protocol import EngineRequest
from tc_ai_bridge.correction_application_recovery import CorrectionApplicationRecoveryCoordinator
from tc_ai_bridge.passage_semantic_models import (
    ActorType,
    AffectedTargetSpan,
    CorrectionApplicationActor,
    CorrectionApplicationIntent,
    CorrectionApplicationState,
    CorrectionCreationMode,
    CorrectionIntent,
    CorrectionProposalV2,
    CoverageDimension,
    LifecycleStatus,
    PolicyBinding,
    ReviewStatus,
    StrictScriptureEditContext,
    TokenInstance,
    TokenKind,
    TokenLayer,
    TokenLineage,
    TokenSide,
    SemanticUnitProvenance,
    to_wire,
)
from tc_ai_bridge import passage_semantic_repository as repository_module
from tc_ai_bridge.passage_semantic_repository import (
    DATABASE_SCHEMA_VERSION,
    FoundationConflict,
    FoundationRepository,
    FoundationValidationError,
)
from tc_ai_bridge.passage_semantic_runtime import PassageSemanticRuntime
from tc_ai_bridge.secret_store import AppSettings
from tc_ai_bridge.tc_project import TranslationCoreProject


REFERENCE = "PHP 1:6"
BEFORE = "நான் என் தேவனை நினைக்கிறேன்."
REPLACEMENT = "கர்த்தராகிய என் தேவனை"


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _proposal(proposal_id: str = "proposal-1") -> CorrectionProposalV2:
    start = BEFORE.index("என்")
    original = "என் தேவனை"
    return CorrectionProposalV2(
        id=proposal_id, qa_finding_id="finding-1", project_id="project-1",
        intent=CorrectionIntent(
            failed_dimension=CoverageDimension.PARTICIPANT,
            observed_meaning="the target lacks the required source relationship",
            required_meaning="my God", affected_source_semantic_unit_ids=(),
            affected_target_span=AffectedTargetSpan(
                displayed_reference=REFERENCE, canonical_references=(REFERENCE,),
                start_code_point=start, end_code_point=start + len(original),
                original_text=original, target_text_revision="target-revision-1",
                target_content_hash=_hash(BEFORE),
            ),
        ),
        affected_references=("PHP 1:3", REFERENCE), current_text=original,
        proposed_text=REPLACEMENT, explanation="Preserve the source relationship.",
        evidence_ids=(), semantic_relationship_ids=(), meaning_assessment_ids=(),
        created_by="Reviewer", created_at="2026-09-05T00:00:00Z",
        creation_mode=CorrectionCreationMode.HUMAN_AUTHORED,
        policy_binding=PolicyBinding.foundation_v1(),
        review_status=ReviewStatus.HUMAN_MODIFIED,
        lifecycle_status=LifecycleStatus.ACTIVE,
    )


def _intent(
    *, application_id: str = "application-1", proposal_id: str = "proposal-1",
    state: CorrectionApplicationState = CorrectionApplicationState.PREPARED,
    start: int | None = None, end: int | None = None,
    original: str | None = None, replacement: str = REPLACEMENT,
) -> CorrectionApplicationIntent:
    proposal = _proposal(proposal_id)
    span = proposal.intent.affected_target_span
    start = span.start_code_point if start is None else start
    end = span.end_code_point if end is None else end
    original = span.original_text if original is None else original
    final = BEFORE[:start] + replacement + BEFORE[end:]
    return CorrectionApplicationIntent(
        application_id=application_id, proposal_id=proposal_id, finding_id="finding-1",
        project_id="project-1", expected_proposal_revision=1,
        expected_finding_revision=1, target_displayed_reference=REFERENCE,
        canonical_references=(REFERENCE,), source_provenance_references=("PHP 1:3",),
        expected_target_revision="target-revision-1",
        expected_target_content_hash=_hash(BEFORE),
        expected_start_code_point=start, expected_end_code_point=end,
        expected_original_text=original, replacement_text_snapshot=replacement,
        intended_final_verse_hash=_hash(final),
        pending_invalidation_id=f"pending-{application_id}",
        translation_core_journal_transaction_id="",
        actor=CorrectionApplicationActor(actor_type=ActorType.HUMAN, actor_id="Reviewer"),
        created_at="2026-09-05T00:00:00Z", updated_at="2026-09-05T00:00:00Z",
        application_state=state, state_revision=1,
    )


def _repository(tmp_path: Path) -> FoundationRepository:
    repo = FoundationRepository(tmp_path / "semantic.sqlite3")
    repo.bind_project_metadata(
        project_id="project-1", identity_fingerprint="identity-1", book="PHP",
        target_language_id="tam", resource_id="irv", path=str(tmp_path / "project"),
    )
    repo.create_qa_finding("finding-1", "project-1")
    repo.save_correction_proposal_v2(_proposal())
    repo.establish_target_revision(
        project_id="project-1", book="PHP", displayed_reference=REFERENCE,
        text_hash=_hash(BEFORE), text_revision="target-revision-1",
    )
    return repo


def test_v12_to_v13_migration_preserves_database_and_adds_exact_attempt_columns(tmp_path: Path) -> None:
    database = tmp_path / "semantic.sqlite3"
    conn = sqlite3.connect(database)
    for version in range(1, 13):
        conn.executescript(getattr(repository_module, f"_MIGRATION_V{version}"))
        conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY,schema_id TEXT NOT NULL,applied_at TEXT NOT NULL)")
        conn.execute("INSERT INTO schema_migrations VALUES(?,?,?)", (version, repository_module.SCHEMA_ID, "2026-09-05T00:00:00Z"))
    policy_id = "legacy-policy"
    conn.execute(
        "INSERT INTO policy_bindings VALUES(?,?,?,?)",
        (policy_id, "confidence-v1", "calibration-v1", "audit-v1"),
    )
    finding_payload = {
        "id": "legacy-finding", "projectId": "project-1",
        "qaDisposition": "CONFIRMED_TRANSLATION_ERROR",
        "reviewStatus": "HUMAN_APPROVED", "lifecycleStatus": "ACTIVE",
        "revision": 2,
    }
    conn.execute(
        "INSERT INTO qa_findings"
        "(id,project_id,qa_disposition,policy_binding_id,review_status,lifecycle_status,revision,payload_json) "
        "VALUES(?,?,?,?,?,?,?,?)",
        ("legacy-finding", "project-1", "CONFIRMED_TRANSLATION_ERROR",
         policy_id, "HUMAN_APPROVED", "ACTIVE", 2, json.dumps(finding_payload)),
    )
    proposal_payload = {
        "id": "legacy-proposal", "qaFindingId": "legacy-finding",
        "projectId": "project-1", "proposedText": "replacement",
        "affectedReferences": ["PHP 1:3", "PHP 1:6"],
        "intent": {"affectedTargetSpan": {
            "displayedReference": "PHP 1:6",
            "canonicalReferences": ["PHP 1:6"],
            "startCodePoint": 0, "endCodePoint": 1,
            "targetContentHash": "before-hash",
        }},
        "reviewStatus": "HUMAN_MODIFIED", "lifecycleStatus": "ACTIVE",
        "revision": 1,
    }
    conn.execute(
        "INSERT INTO correction_proposals VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("legacy-proposal", "project-1", "legacy-finding", "target-r1", None,
         policy_id, "HUMAN_MODIFIED", "ACTIVE", 1, json.dumps(proposal_payload),
         2, "NOT_RUN", 1),
    )
    legacy_application_payload = {
        "applicationId": "legacy-application", "proposalId": "legacy-proposal",
        "projectId": "project-1", "expectedCorrectionRevision": 1,
        "expectedFindingRevision": 2, "expectedTargetRevision": "target-r1",
        "expectedTargetContentHashes": ["before-hash"],
        "expectedOriginalText": "x", "state": "PREPARED",
    }
    conn.execute(
        "INSERT INTO correction_application_intents VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("legacy-application", "legacy-proposal", "project-1", 1, 2,
         "target-r1", "x", "PREPARED", "2026-09-05T00:00:00Z", None,
         "", "", 0, json.dumps(legacy_application_payload)),
    )
    conn.commit(); conn.close()
    repo = FoundationRepository(database)
    assert repo.schema_version() == DATABASE_SCHEMA_VERSION == 13
    with sqlite3.connect(database) as migrated:
        columns = {row[1] for row in migrated.execute("PRAGMA table_info(correction_application_intents)")}
        assert {
            "application_id", "proposal_id", "finding_id", "expected_proposal_revision",
            "expected_finding_revision", "target_displayed_reference",
            "canonical_references_json", "source_provenance_references_json",
            "expected_target_revision", "expected_target_content_hash",
            "expected_start_code_point", "expected_end_code_point",
            "expected_original_text", "replacement_text_snapshot",
            "intended_final_verse_hash", "pending_invalidation_id",
            "translation_core_journal_transaction_id", "actor_json", "created_at",
            "updated_at", "application_state", "state_revision", "failure_code",
            "recovery_metadata_json", "result_metadata_json",
        } <= columns
    migrated_application = repo.application_intent("legacy-application")
    assert migrated_application["applicationState"] == "RECOVERY_REQUIRED"
    assert migrated_application["failureCode"] == "MIGRATED_INCOMPLETE_APPLICATION_SNAPSHOT"
    assert migrated_application["recoveryMetadata"]["legacyPayload"] == legacy_application_payload
    assert repo.correction_proposal("legacy-proposal")["reviewStatus"] == "HUMAN_MODIFIED"
    assert (tmp_path / "backups").is_dir()


def test_application_create_is_idempotent_by_proposal_revision(tmp_path: Path) -> None:
    repo = _repository(tmp_path)
    first = repo.prepare_application_intent(_intent(), previous_text_hash=_hash(BEFORE))
    duplicate = repo.prepare_application_intent(
        _intent(application_id="application-duplicate"), previous_text_hash=_hash(BEFORE))
    assert duplicate == first
    assert repo.find_application_by_proposal_revision("proposal-1", 1) == first
    assert len(repo.list_incomplete_applications("project-1")) == 1


def test_application_intent_round_trips_every_recovery_identity_field(tmp_path: Path) -> None:
    repo = _repository(tmp_path)
    intent = _intent()
    intent = CorrectionApplicationIntent(**{
        **intent.__dict__,
        "translation_core_journal_transaction_id": "tc-journal-1",
        "recovery_metadata": {"preparedBy": "focused-test"},
        "result_metadata": {"affectedAnalysisStarted": False},
    })
    stored = repo.prepare_application_intent(intent, previous_text_hash=_hash(BEFORE))
    assert stored == repo.get_application_intent("application-1")
    assert stored["findingId"] == "finding-1"
    assert stored["sourceProvenanceReferences"] == ["PHP 1:3"]
    assert stored["canonicalReferences"] == ["PHP 1:6"]
    assert stored["translationCoreJournalTransactionId"] == "tc-journal-1"
    assert stored["actor"] == {"actorType": "HUMAN", "actorId": "Reviewer"}
    assert stored["recoveryMetadata"] == {"preparedBy": "focused-test"}
    assert stored["resultMetadata"] == {"affectedAnalysisStarted": False}


@pytest.mark.parametrize("terminal_state", [
    CorrectionApplicationState.PREPARED,
    CorrectionApplicationState.APPLYING,
    CorrectionApplicationState.APPLIED_SCRIPTURE,
    CorrectionApplicationState.COMPLETED,
])
def test_duplicate_request_returns_same_attempt_in_every_durable_state(
    tmp_path: Path, terminal_state: CorrectionApplicationState,
) -> None:
    repo = _repository(tmp_path)
    current = repo.prepare_application_intent(_intent(), previous_text_hash=_hash(BEFORE))
    path = [
        CorrectionApplicationState.APPLYING,
        CorrectionApplicationState.APPLIED_SCRIPTURE,
        CorrectionApplicationState.INVALIDATED,
        CorrectionApplicationState.COMPLETED,
    ]
    for next_state in path:
        if current["applicationState"] == terminal_state.value:
            break
        current = repo.transition_application_state(
            "application-1", expected_state=current["applicationState"],
            expected_state_revision=current["stateRevision"], new_state=next_state)
    duplicate = repo.prepare_application_intent(
        _intent(application_id="must-not-be-created"), previous_text_hash=_hash(BEFORE))
    assert duplicate["applicationId"] == "application-1"
    assert duplicate["applicationState"] == terminal_state.value


def test_application_state_transition_requires_cas_and_valid_edge(tmp_path: Path) -> None:
    repo = _repository(tmp_path)
    repo.prepare_application_intent(_intent(), previous_text_hash=_hash(BEFORE))
    applying = repo.transition_application_state(
        "application-1", expected_state=CorrectionApplicationState.PREPARED,
        expected_state_revision=1, new_state=CorrectionApplicationState.APPLYING)
    assert applying["applicationState"] == "APPLYING"
    assert applying["stateRevision"] == 2
    with pytest.raises(FoundationConflict, match="revision conflict"):
        repo.transition_application_state(
            "application-1", expected_state=CorrectionApplicationState.APPLYING,
            expected_state_revision=1, new_state=CorrectionApplicationState.APPLIED_SCRIPTURE)
    with pytest.raises(FoundationConflict, match="Invalid correction application transition"):
        repo.transition_application_state(
            "application-1", expected_state=CorrectionApplicationState.APPLYING,
            expected_state_revision=2, new_state=CorrectionApplicationState.COMPLETED)


@pytest.mark.parametrize(("state", "next_state"), [
    (CorrectionApplicationState.PREPARED, CorrectionApplicationState.APPLYING),
    (CorrectionApplicationState.APPLYING, CorrectionApplicationState.APPLIED_SCRIPTURE),
    (CorrectionApplicationState.APPLIED_SCRIPTURE, CorrectionApplicationState.INVALIDATED),
    (CorrectionApplicationState.INVALIDATED, CorrectionApplicationState.COMPLETED),
])
def test_valid_application_state_edges_are_distinct(state, next_state) -> None:
    assert CorrectionApplicationIntent.can_transition(state, next_state)


def test_prepared_invalidation_failure_creates_no_mutation_ready_attempt(tmp_path: Path) -> None:
    repo = _repository(tmp_path)
    with pytest.raises(FoundationConflict, match="target snapshot"):
        repo.prepare_application_intent(_intent(), previous_text_hash="wrong-before-hash")
    assert repo.list_incomplete_applications("project-1") == []
    assert repo.pending_invalidations("project-1") == []


def test_non_human_actor_cannot_prepare_a_correction_application(tmp_path: Path) -> None:
    repo = _repository(tmp_path)
    intent = _intent()
    intent = CorrectionApplicationIntent(**{
        **intent.__dict__,
        "actor": CorrectionApplicationActor(actor_type=ActorType.AI, actor_id="provider"),
    })
    with pytest.raises(FoundationValidationError, match="explicit human action"):
        repo.prepare_application_intent(intent, previous_text_hash=_hash(BEFORE))
    assert repo.list_incomplete_applications("project-1") == []
    assert repo.pending_invalidations("project-1") == []


@pytest.mark.parametrize(("text", "start", "end", "replacement"), [
    ("கொடுத்தார்", 0, 2, "த"),
    ("דָּבָר֙", 0, 4, "אֵל"),
    ("χάρις χάρις", 0, 5, "θεός"),
    ("𐐷word😀", 0, 1, "𐐀"),
    ("வசனம்", 2, 2, " புதிய "),
])
def test_unicode_application_snapshot_round_trips_exact_code_points(tmp_path: Path, text: str, start: int, end: int, replacement: str) -> None:
    original = text[start:end]
    intended = text[:start] + replacement + text[end:]
    app = _intent(start=start, end=end, original=original, replacement=replacement)
    app = CorrectionApplicationIntent(**{
        **app.__dict__, "expected_target_content_hash": _hash(text),
        "intended_final_verse_hash": _hash(intended),
    })
    wire = to_wire(app)
    assert wire["expectedStartCodePoint"] == start
    assert wire["expectedEndCodePoint"] == end
    assert wire["expectedOriginalText"] == original
    assert wire["replacementTextSnapshot"] == replacement
    assert wire["intendedFinalVerseHash"] == _hash(intended)


def test_application_and_strict_context_validate_against_canonical_schema() -> None:
    schema = json.loads(
        (Path(__file__).parents[2] / "schemas" / "bridge-passage-semantic-v1.schema.json")
        .read_text(encoding="utf-8")
    )
    intent = to_wire(_intent())
    strict_context = to_wire(StrictScriptureEditContext(
        expected_target_revision="r1", expected_target_content_hash=_hash("verse"),
        expected_original_verse_text="verse", expected_start_code_point=0,
        expected_end_code_point=0, expected_original_span_text="",
        intended_final_verse_text="new verse", pending_invalidation_id="pending-1",
        application_id="application-1",
    ))
    assert set(intent) == set(schema["$defs"]["CorrectionApplicationIntent"]["required"])
    assert set(strict_context) == set(schema["$defs"]["StrictScriptureEditContext"]["required"])
    assert intent["applicationState"] in schema["$defs"]["CorrectionApplicationState"]["enum"]
    assert intent["actor"]["actorType"] in schema["$defs"]["ActorType"]["enum"]
    root = Path(__file__).parents[2]
    typescript = (root / "src" / "lib" / "types" / "correctionReview.ts").read_text(
        encoding="utf-8"
    )
    rust = (root / "src-tauri" / "src" / "passage_semantic_wire.rs").read_text(
        encoding="utf-8"
    )
    for field_name in schema["$defs"]["CorrectionApplicationIntent"]["required"]:
        assert f"{field_name}:" in typescript
    for rust_field in (
        "application_id", "expected_proposal_revision", "expected_start_code_point",
        "replacement_text_snapshot", "application_state", "state_revision",
        "recovery_metadata", "result_metadata",
    ):
        assert f"pub {rust_field}:" in rust


def test_strict_future_writer_context_is_defined_but_not_executed() -> None:
    contract = StrictScriptureEditContext(
        expected_target_revision="r1", expected_target_content_hash=_hash("original verse"),
        expected_original_verse_text="original verse", expected_start_code_point=2,
        expected_end_code_point=4, expected_original_span_text="ig",
        intended_final_verse_text="orXXinal verse", pending_invalidation_id="pending-1",
        application_id="application-1")
    assert to_wire(contract)["pendingInvalidationId"] == "pending-1"
    import inspect
    assert "strict_context" not in inspect.signature(TranslationCoreProject.apply_scripture_edit).parameters


def _write_project(root: Path) -> Path:
    alignment = root / ".apps" / "translationCore" / "alignmentData" / "php"
    alignment.mkdir(parents=True); (root / "php").mkdir(parents=True)
    (root / "manifest.json").write_text(json.dumps({
        "project": {"id": "php", "name": "Philippians"},
        "target_language": {"id": "tam", "name": "Tamil"},
        "resource": {"id": "irv", "name": "IRVTam"}, "tc_version": "8",
    }), encoding="utf-8")
    (root / "php" / "1.json").write_text(json.dumps({"6": BEFORE}, ensure_ascii=False), encoding="utf-8")
    (alignment / "1.json").write_text(json.dumps({"6": {"alignments": [], "wordBank": []}}), encoding="utf-8")
    (root / "php.usfm").write_text("\\id PHP\n\\c 1\n\\p\n\\v 6 OLD IMPORTED WORDING\n", encoding="utf-8")
    return root


def _guarded_digests(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in root.rglob("*"):
        if not path.is_file(): continue
        relative = path.relative_to(root).as_posix()
        if relative == "php/1.json" or path.suffix.lower() in {".usfm", ".sfm"} or "alignmentData" in relative:
            result[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def test_all_stage9b3a_operations_leave_scripture_and_tc_files_byte_identical(tmp_path: Path) -> None:
    root = _write_project(tmp_path / "project")
    project = TranslationCoreProject(root)
    runtime = PassageSemanticRuntime(project, "project-1")
    project.attach_passage_semantic_runtime(runtime)
    runtime.repository.create_qa_finding("finding-1", "project-1")
    runtime.repository.save_correction_proposal_v2(_proposal())
    before = _guarded_digests(root)
    intent = _intent()
    current = runtime.repository.current_target_revision("project-1", "PHP", REFERENCE)
    intent = CorrectionApplicationIntent(**{
        **intent.__dict__, "expected_target_revision": current["textRevision"],
    })
    runtime.repository.prepare_application_intent(intent, previous_text_hash=_hash(BEFORE))
    assert _guarded_digests(root) == before
    runtime.repository.record_application_backup(
        intent.application_id, backup_root=tmp_path / "semantic-backups",
        expected_state_revision=1)
    assert _guarded_digests(root) == before
    CorrectionApplicationRecoveryCoordinator(runtime).reconcile_incomplete()
    assert _guarded_digests(root) == before
    assert runtime.repository.application_intent("application-1")["applicationState"] == "FAILED"


def _runtime_with_application(tmp_path: Path) -> tuple[Path, PassageSemanticRuntime]:
    root = _write_project(tmp_path / "project")
    project = TranslationCoreProject(root)
    runtime = PassageSemanticRuntime(project, "project-1")
    project.attach_passage_semantic_runtime(runtime)
    runtime.repository.create_qa_finding("finding-1", "project-1")
    runtime.repository.save_correction_proposal_v2(_proposal())
    current = runtime.repository.current_target_revision("project-1", "PHP", REFERENCE)
    intent = CorrectionApplicationIntent(**{
        **_intent().__dict__, "expected_target_revision": current["textRevision"],
    })
    runtime.repository.prepare_application_intent(intent, previous_text_hash=_hash(BEFORE))
    return root, runtime


def _simulate_target_text(root: Path, text: str) -> None:
    path = root / "php" / "1.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["6"] = text
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_recovery_with_intended_after_hash_never_reapplies_and_completes_metadata(tmp_path: Path) -> None:
    root, runtime = _runtime_with_application(tmp_path)
    app = runtime.repository.application_intent("application-1")
    app = runtime.repository.transition_application_state(
        app["applicationId"], expected_state=app["applicationState"],
        expected_state_revision=app["stateRevision"],
        new_state=CorrectionApplicationState.APPLYING)
    span = _proposal().intent.affected_target_span
    intended = BEFORE[:span.start_code_point] + REPLACEMENT + BEFORE[span.end_code_point:]
    _simulate_target_text(root, intended)
    restarted = PassageSemanticRuntime(TranslationCoreProject(root), "project-1")
    recovered = restarted.repository.application_intent("application-1")
    assert recovered["applicationState"] == "COMPLETED"
    assert recovered["resultMetadata"]["scriptureAlreadyMatchedIntendedFinalHash"] is True
    assert recovered["resultMetadata"]["affectedAnalysisStarted"] is False
    assert restarted.repository.target_invalidation("pending-application-1")["state"] == "APPLIED"
    proposal = restarted.repository.correction_proposal("proposal-1")
    assert proposal["appliedTargetRevision"] == restarted.repository.current_target_revision(
        "project-1", "PHP", REFERENCE)["textRevision"]
    assert proposal["verificationStatus"] == "PENDING"
    assert restarted.repository.qa_finding("finding-1")["qaDisposition"] != "CORRECTED"
    assert restarted.application_recovery["correctionWritesBlocked"] is False


def test_recovery_with_neither_hash_enters_recovery_required_read_mode(tmp_path: Path) -> None:
    root, _runtime = _runtime_with_application(tmp_path)
    _simulate_target_text(root, "a different editor's text")
    restarted = PassageSemanticRuntime(TranslationCoreProject(root), "project-1")
    application = restarted.repository.application_intent("application-1")
    assert application["applicationState"] == "RECOVERY_REQUIRED"
    assert application["failureCode"] == "TARGET_HASH_AMBIGUOUS"
    assert restarted.status()["correctionWritesBlocked"] is True


def test_recovery_after_invalidation_before_finalization_completes_without_writer(tmp_path: Path) -> None:
    root, runtime = _runtime_with_application(tmp_path)
    span = _proposal().intent.affected_target_span
    intended = BEFORE[:span.start_code_point] + REPLACEMENT + BEFORE[span.end_code_point:]
    _simulate_target_text(root, intended)
    after_hash = _hash(intended)
    runtime.repository.apply_target_invalidation(
        "pending-application-1", actual_text_hash=after_hash,
        text_revision=runtime.text_revision(REFERENCE, after_hash))
    app = runtime.repository.application_intent("application-1")
    for next_state in (
        CorrectionApplicationState.APPLYING,
        CorrectionApplicationState.APPLIED_SCRIPTURE,
        CorrectionApplicationState.INVALIDATED,
    ):
        app = runtime.repository.transition_application_state(
            app["applicationId"], expected_state=app["applicationState"],
            expected_state_revision=app["stateRevision"], new_state=next_state)
    restarted = PassageSemanticRuntime(TranslationCoreProject(root), "project-1")
    assert restarted.repository.application_intent("application-1")["applicationState"] == "COMPLETED"


def test_recovery_after_proposal_metadata_before_ledger_finalization_is_idempotent(tmp_path: Path) -> None:
    root, runtime = _runtime_with_application(tmp_path)
    span = _proposal().intent.affected_target_span
    intended = BEFORE[:span.start_code_point] + REPLACEMENT + BEFORE[span.end_code_point:]
    _simulate_target_text(root, intended)
    after_hash = _hash(intended)
    runtime.repository.apply_target_invalidation(
        "pending-application-1", actual_text_hash=after_hash,
        text_revision=runtime.text_revision(REFERENCE, after_hash))
    app = runtime.repository.application_intent("application-1")
    for next_state in (
        CorrectionApplicationState.APPLYING,
        CorrectionApplicationState.APPLIED_SCRIPTURE,
        CorrectionApplicationState.INVALIDATED,
    ):
        app = runtime.repository.transition_application_state(
            app["applicationId"], expected_state=app["applicationState"],
            expected_state_revision=app["stateRevision"], new_state=next_state)
    stale_proposal = runtime.repository.correction_proposal("proposal-1")
    target_revision = runtime.repository.current_target_revision(
        "project-1", "PHP", REFERENCE)["textRevision"]
    runtime.repository.record_correction_application_metadata(
        "proposal-1", actor_type="HUMAN", actor_id="Reviewer",
        applied_target_revision=target_revision,
        expected_revision=stale_proposal["revision"],
    )

    restarted = PassageSemanticRuntime(TranslationCoreProject(root), "project-1")
    recovered = restarted.repository.application_intent("application-1")
    assert recovered["applicationState"] == "COMPLETED"
    assert restarted.repository.correction_proposal("proposal-1")["revision"] == (
        stale_proposal["revision"] + 1
    )


def test_unrecoverable_semantic_invalidation_blocks_correction_writes(tmp_path: Path) -> None:
    root, runtime = _runtime_with_application(tmp_path)
    runtime.repository.cancel_target_invalidation("pending-application-1", "simulated failure")
    span = _proposal().intent.affected_target_span
    intended = BEFORE[:span.start_code_point] + REPLACEMENT + BEFORE[span.end_code_point:]
    _simulate_target_text(root, intended)
    restarted = PassageSemanticRuntime(TranslationCoreProject(root), "project-1")
    application = restarted.repository.application_intent("application-1")
    assert application["applicationState"] == "RECOVERY_REQUIRED"
    assert application["failureCode"] == "SEMANTIC_INVALIDATION_NOT_RECOVERABLE"


def test_completed_attempt_is_not_changed_by_restart_or_analysis_state(tmp_path: Path) -> None:
    repo = _repository(tmp_path)
    app = repo.prepare_application_intent(_intent(), previous_text_hash=_hash(BEFORE))
    for next_state in (
        CorrectionApplicationState.APPLYING,
        CorrectionApplicationState.APPLIED_SCRIPTURE,
        CorrectionApplicationState.INVALIDATED,
        CorrectionApplicationState.COMPLETED,
    ):
        app = repo.transition_application_state(
            app["applicationId"], expected_state=app["applicationState"],
            expected_state_revision=app["stateRevision"], new_state=next_state,
            result_metadata={"affectedAnalysisStatus": "RUNNING"} if next_state == CorrectionApplicationState.COMPLETED else None)
    assert repo.list_incomplete_applications("project-1") == []
    assert repo.application_intent("application-1") == app


def test_semantic_backup_records_application_checksum_and_timestamp(tmp_path: Path) -> None:
    repo = _repository(tmp_path)
    repo.prepare_application_intent(_intent(), previous_text_hash=_hash(BEFORE))
    updated = repo.record_application_backup(
        "application-1", backup_root=tmp_path / "backups", expected_state_revision=1)
    metadata = updated["recoveryMetadata"]["semanticDatabaseBackup"]
    manifest = json.loads((Path(metadata["path"]) / "backup-manifest.json").read_text(encoding="utf-8"))
    assert metadata["applicationId"] == manifest["applicationId"] == "application-1"
    assert metadata["sha256"] == manifest["sha256"]
    assert metadata["createdAt"]


def test_stage9b3a_exposes_no_apply_api_ui_or_scripture_writer() -> None:
    root = Path(__file__).parents[2]
    service_source = (root / "engine" / "bridge_service.py").read_text(encoding="utf-8")
    assert "CORRECTION_APPLY_PROPOSAL =" not in service_source
    assert "Methods.CORRECTION_APPLY_PROPOSAL" not in service_source
    assert "correction_apply_proposal" not in (root / "src-tauri" / "src" / "commands.rs").read_text(encoding="utf-8")
    assert "Apply correction" not in (root / "src" / "lib" / "components" / "CorrectionReviewPanel.svelte").read_text(encoding="utf-8")
    recovery_source = (root / "engine" / "tc_ai_bridge" / "correction_application_recovery.py").read_text(encoding="utf-8")
    for forbidden in ("write_text(", "apply_scripture_edit(", "json.dump("):
        assert forbidden not in recovery_source


def _call(engine: BridgeEngine, method: str, params: dict) -> dict:
    return engine.handle_request(EngineRequest(id="9b3a", method=method, params=params)).to_dict()


def test_startup_recovers_tc_journal_before_semantic_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _write_project(tmp_path / "project")
    project = TranslationCoreProject(root); chapter = root / "php" / "1.json"
    transaction = project.journal.begin("scriptureEdit", [chapter]); project.journal.mark_writing(transaction)
    chapter.write_text(json.dumps({"6": "PARTIAL WRITE"}), encoding="utf-8")
    observed: list[str] = []; real_runtime = bridge_service.PassageSemanticRuntime
    class ObservingRuntime(real_runtime):
        def __init__(self, candidate, project_id):
            observed.append(candidate.target_verse_text("1", "6")); super().__init__(candidate, project_id)
    monkeypatch.setattr(bridge_service, "PassageSemanticRuntime", ObservingRuntime)
    opened = _call(BridgeEngine(settings=AppSettings(path=tmp_path / "settings.json")), "project.open", {"path": str(root)})
    assert opened["success"] is True
    assert observed == [BEFORE]


def test_failed_tc_rollback_blocks_semantic_runtime_and_correction_writes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _write_project(tmp_path / "project")
    project = TranslationCoreProject(root); chapter = root / "php" / "1.json"
    transaction = project.journal.begin("scriptureEdit", [chapter]); project.journal.mark_writing(transaction)
    for backup in transaction.backup_root.rglob("1.json"): backup.unlink()
    chapter.write_text(json.dumps({"6": "PARTIAL WRITE"}), encoding="utf-8")
    class ForbiddenRuntime:
        def __init__(self, *_args, **_kwargs): raise AssertionError("semantic runtime opened before journal recovery")
    monkeypatch.setattr(bridge_service, "PassageSemanticRuntime", ForbiddenRuntime)
    opened = _call(BridgeEngine(settings=AppSettings(path=tmp_path / "settings.json")), "project.open", {"path": str(root)})
    assert opened["success"] is True
    assert opened["result"]["passageSemantic"]["state"] == "RECOVERY_REQUIRED"
    assert opened["result"]["passageSemantic"]["correctionWritesBlocked"] is True


def test_target_tokens_and_units_stale_while_source_token_history_survives(tmp_path: Path) -> None:
    root = _write_project(tmp_path / "project")
    runtime = PassageSemanticRuntime(TranslationCoreProject(root), "project-1")
    target = runtime.target_semantic.build_range("1", "6", "1", "6")
    target_token = target["tokens"][0]["id"]; target_unit = target["units"][0]["id"]
    source_lineage = TokenLineage(
        id="source-lineage", side=TokenSide.SOURCE, project_id=None,
        logical_resource_id="el-x-koine/ugnt", book="PHP",
        canonical_reference_scope=("PHP 1:3",), token_layer=TokenLayer.ORTHOGRAPHIC,
        upstream_identity="ugnt:PHP:1:3:1", created_at="2026-09-05T00:00:00Z",
        provenance=SemanticUnitProvenance.CANONICAL_RESOURCE)
    runtime.repository.save_token_lineage(source_lineage)
    runtime.repository.save_token_instance(TokenInstance(
        id="source-token", lineage_id=source_lineage.id, side=TokenSide.SOURCE,
        project_id=None, resource_id="el-x-koine/ugnt", resource_version="1",
        resource_hash="source-hash", text_revision=None, book="PHP",
        displayed_reference="PHP 1:3", canonical_references=("PHP 1:3",), index=0,
        occurrence=1, occurrences=1, span=None, raw_form="θεῷ", normalized_form="θεῷ",
        normalization_profile="nfc", tokenization_version="fixture",
        token_layer=TokenLayer.ORTHOGRAPHIC, token_kind=TokenKind.WORD,
        parent_instance_id=None, instance_fingerprint="source-instance"))
    pending = runtime.repository.prepare_target_invalidation(
        project_id="project-1", book="PHP", displayed_reference=REFERENCE,
        previous_text_hash=_hash(BEFORE), expected_text_hash=_hash("changed"))
    runtime.repository.apply_target_invalidation(pending, actual_text_hash=_hash("changed"), text_revision="target-revision-2")
    assert runtime.repository.token_instance(target_token)["lifecycleStatus"] == "STALE"
    assert runtime.repository.semantic_unit(target_unit)["lifecycleStatus"] == "STALE"
    assert runtime.repository.token_instance("source-token")["lifecycleStatus"] == "ACTIVE"


def test_php_cross_verse_application_snapshot_keeps_source_and_target_distinct(tmp_path: Path) -> None:
    repo = _repository(tmp_path)
    with sqlite3.connect(repo.path) as conn:
        before_groups = conn.execute("SELECT COUNT(*) FROM lexical_groups").fetchone()[0]
    stored = repo.prepare_application_intent(_intent(), previous_text_hash=_hash(BEFORE))
    assert stored["sourceProvenanceReferences"] == ["PHP 1:3"]
    assert stored["targetDisplayedReference"] == "PHP 1:6"
    assert stored["canonicalReferences"] == ["PHP 1:6"]
    with sqlite3.connect(repo.path) as conn:
        after_groups = conn.execute("SELECT COUNT(*) FROM lexical_groups").fetchone()[0]
    assert after_groups == before_groups
