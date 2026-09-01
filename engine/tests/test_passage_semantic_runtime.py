from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

import bridge_service
from bridge_service import BridgeEngine
from greek_room_engine.protocol import EngineRequest
from tc_ai_bridge.passage_semantic_models import (
    LifecycleStatus,
    QaDisposition,
    ReviewStatus,
)
from tc_ai_bridge.passage_semantic_repository import FoundationConflict, FoundationRepository
from tc_ai_bridge.passage_semantic_runtime import (
    PassageSemanticRuntime,
    _canonical_reference,
    build_current_text_overlay,
    tokenize_target_text,
)
from tc_ai_bridge.secret_store import AppSettings
from tc_ai_bridge.tc_project import TranslationCoreProject


def _call(engine: BridgeEngine, method: str, params: dict | None = None) -> dict:
    return engine.handle_request(
        EngineRequest(id="stage4", method=method, params=params or {})
    ).to_dict()


def _write_project(root: Path, *, usfm: bool = True) -> Path:
    align_dir = root / ".apps" / "translationCore" / "alignmentData" / "rut"
    align_dir.mkdir(parents=True)
    (root / "rut").mkdir(parents=True)
    (root / "manifest.json").write_text(json.dumps({
        "project": {"id": "rut", "name": "Ruth"},
        "target_language": {"id": "tam", "name": "Tamil"},
        "resource": {"id": "irv", "name": "IRVTam"},
        "tc_version": "8",
    }), encoding="utf-8")
    (root / "rut" / "1.json").write_text(json.dumps({
        "1": "புதிய தற்போதைய வசனம்.",
        "2-3": "பாலமாக உள்ள தற்போதைய வசனம்.",
    }, ensure_ascii=False), encoding="utf-8")
    (root / "rut" / "2.json").write_text(json.dumps({
        "1": "அடுத்த அதிகாரத்தின் தற்போதைய வசனம்.",
    }, ensure_ascii=False), encoding="utf-8")
    alignment = {
        "1": {
            "alignments": [{
                "topWords": [{"word": "דָּבָר", "occurrence": 1, "occurrences": 1}],
                "bottomWords": [{"word": "புதிய", "occurrence": 1, "occurrences": 1}],
            }],
            "wordBank": [],
        },
        "2-3": {"alignments": [], "wordBank": []},
    }
    (align_dir / "1.json").write_text(
        json.dumps(alignment, ensure_ascii=False), encoding="utf-8"
    )
    (align_dir / "2.json").write_text(json.dumps({
        "1": {"alignments": [], "wordBank": []},
    }), encoding="utf-8")
    if usfm:
        (root / "rut.usfm").write_text(
            "\\id RUT\n"
            "\\h Old heading wording\n"
            "\\c 1\n"
            "\\s Old section heading\n"
            "\\p\n"
            "\\v 1 OLD IMPORTED SCRIPTURE \\f + \\ft old footnote words\\f* "
            "\\x + \\xt old cross reference words\\x* \\add wrapper\\add*\n"
            "\\q1\n"
            "\\v 2-3 OLD BRIDGE WORDING\n"
            "\\c 2\n"
            "\\v 1 OLD CHAPTER TWO WORDING\n",
            encoding="utf-8",
        )
    return root


@pytest.fixture
def stage4_project(tmp_path: Path) -> Path:
    return _write_project(tmp_path / "project")


def _engine(tmp_path: Path) -> BridgeEngine:
    return BridgeEngine(settings=AppSettings(path=tmp_path / "settings.json"))


def test_first_open_initializes_companion_and_second_open_is_idempotent(
    tmp_path: Path, stage4_project: Path,
) -> None:
    engine = _engine(tmp_path)
    first = _call(engine, "project.open", {"path": str(stage4_project)})
    assert first["success"] is True
    assert first["result"]["passageSemantic"]["state"] == "READY"
    database = stage4_project / ".apps" / "translationCoreAI" / "passageSemantic" / "bridge-semantic.sqlite3"
    assert database.is_file()
    project_id = first["result"]["projectId"]

    second = _call(engine, "project.open", {"path": str(stage4_project)})
    assert second["success"] is True
    assert second["result"]["projectId"] == project_id
    assert second["result"]["passageSemantic"]["recovery"]["ok"] is True
    status = _call(engine, "passageSemantic.status")
    assert status["result"]["state"] == "READY"
    passage = _call(engine, "passageSemantic.getCurrentPassage", {
        "chapter": "1", "verse": "1",
    })
    assert passage["success"] is True
    assert passage["result"]["targetTextByDisplayedReference"]["RUT 1:1"] == "புதிய தற்போதைய வசனம்."


def test_moved_project_retains_identity_but_live_copy_is_rejected(
    tmp_path: Path, stage4_project: Path,
) -> None:
    engine = _engine(tmp_path)
    opened = _call(engine, "project.open", {"path": str(stage4_project)})
    project_id = opened["result"]["projectId"]

    copy = tmp_path / "live-copy"
    shutil.copytree(stage4_project, copy)
    ambiguous = _call(engine, "project.open", {"path": str(copy)})
    assert ambiguous["success"] is False
    assert "two accessible paths" in ambiguous["error"]["message"]

    shutil.rmtree(copy)
    moved = tmp_path / "moved-project"
    shutil.move(str(stage4_project), moved)
    reopened = _call(engine, "project.open", {"path": str(moved)})
    assert reopened["success"] is True
    assert reopened["result"]["projectId"] == project_id


def test_companion_failure_does_not_block_scripture_access(
    tmp_path: Path, stage4_project: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BrokenRuntime:
        def __init__(self, *_args, **_kwargs):
            raise RuntimeError("damaged companion database")

    monkeypatch.setattr(bridge_service, "PassageSemanticRuntime", BrokenRuntime)
    engine = _engine(tmp_path)
    opened = _call(engine, "project.open", {"path": str(stage4_project)})
    assert opened["success"] is True
    assert opened["result"]["passageSemantic"]["state"] == "RECOVERY_REQUIRED"
    verse = _call(engine, "verse.get", {"chapter": "1", "verse": "1"})
    assert verse["success"] is True
    assert verse["result"]["text"] == "புதிய தற்போதைய வசனம்."


def test_real_bridge_edit_is_authoritative_and_old_usfm_words_never_return(
    tmp_path: Path, stage4_project: Path,
) -> None:
    engine = _engine(tmp_path)
    _call(engine, "project.open", {"path": str(stage4_project)})
    edited = "திருத்தப்பட்ட தற்போதைய வசனம்."
    result = _call(engine, "verse.edit", {
        "chapter": "1", "verse": "1", "newText": edited,
    })
    assert result["success"] is True
    passage = engine.passage_semantic_runtime.get_current_passage("1", "1", "2", "1")
    all_text = " ".join(passage["targetTextByDisplayedReference"].values())
    assert edited in all_text
    assert "OLD IMPORTED SCRIPTURE" not in all_text
    assert "old footnote words" not in all_text
    assert "old cross reference words" not in all_text
    assert "Old section heading" not in all_text


def test_structure_overlay_preserves_markers_not_old_scripture_and_crosses_chapters(
    stage4_project: Path,
) -> None:
    project = TranslationCoreProject(stage4_project)
    overlay = build_current_text_overlay(project)
    assert [segment.reference for segment in overlay.index.segments] == [
        "RUT 1:1", "RUT 1:2-3", "RUT 2:1",
    ]
    assert [segment.text for segment in overlay.index.segments] == [
        "புதிய தற்போதைய வசனம்.",
        "பாலமாக உள்ள தற்போதைய வசனம்.",
        "அடுத்த அதிகாரத்தின் தற்போதைய வசனம்.",
    ]
    kinds = {marker.kind.value for marker in overlay.structure_markers}
    assert {"PARAGRAPH", "POETRY", "VERSE_BRIDGE", "HEADING", "NOTE", "CROSS_REFERENCE", "INLINE_MARKUP"} <= kinds


def test_project_without_preserved_usfm_uses_current_text_only(tmp_path: Path) -> None:
    root = _write_project(tmp_path / "without-usfm", usfm=False)
    overlay = build_current_text_overlay(TranslationCoreProject(root))
    assert overlay.structure_resource_id == "current-chapter-json-only"
    assert "புதிய தற்போதைய வசனம்." in overlay.index.segments[0].text


@pytest.mark.parametrize("text", [
    "தமிழ் கொ",                     # Tamil combining character sequence
    "בְּרֵאשִׁ֖ית",                  # Hebrew niqqud/cantillation
    "Ἰησοῦς Ι\u0307ησους",           # precomposed and combining Greek
    "word \U0001F642 word",           # supplementary Unicode scalar
])
def test_companion_tokenizer_emits_valid_codepoint_and_grapheme_spans(text: str) -> None:
    tokens = tokenize_target_text(text)
    assert tokens
    for token in tokens:
        assert text[token["start"]:token["end"]] == token["raw"]
        assert token["startGrapheme"] <= token["endGrapheme"]


def test_human_review_is_preserved_when_dependent_record_becomes_stale(
    tmp_path: Path, stage4_project: Path,
) -> None:
    engine = _engine(tmp_path)
    _call(engine, "project.open", {"path": str(stage4_project)})
    runtime = engine.passage_semantic_runtime
    runtime.repository.create_qa_finding("qa-direct", runtime.project_id)
    runtime.repository.update_qa_disposition(
        "qa-direct", QaDisposition.ACCEPTABLE_TRANSLATION, 1, "Reviewer",
    )
    dependency = runtime.repository.target_dependency_id(runtime.project_id, "RUT", "RUT 1:1")
    runtime.repository.add_record_dependency("QA_FINDING", "qa-direct", "TARGET_REFERENCE", dependency)

    _call(engine, "verse.edit", {
        "chapter": "1", "verse": "1", "newText": "மறுபடியும் திருத்தப்பட்ட வசனம்.",
    })
    finding = runtime.repository.qa_finding("qa-direct")
    assert finding["reviewStatus"] == ReviewStatus.HUMAN_APPROVED.value
    assert finding["lifecycleStatus"] == LifecycleStatus.STALE.value


def test_invalidation_is_dependency_bounded(
    tmp_path: Path, stage4_project: Path,
) -> None:
    engine = _engine(tmp_path)
    _call(engine, "project.open", {"path": str(stage4_project)})
    runtime = engine.passage_semantic_runtime
    for finding_id, reference in (("qa-searched", "RUT 1:1"), ("qa-unrelated", "RUT 2:1")):
        runtime.repository.create_qa_finding(finding_id, runtime.project_id)
        runtime.repository.add_record_dependency(
            "QA_FINDING", finding_id, "TARGET_REFERENCE",
            runtime.repository.target_dependency_id(runtime.project_id, "RUT", reference),
        )

    _call(engine, "verse.edit", {
        "chapter": "1", "verse": "1", "newText": "சார்பு மாற்றப்பட்ட வசனம்.",
    })
    assert runtime.repository.qa_finding("qa-searched")["lifecycleStatus"] == "STALE"
    assert runtime.repository.qa_finding("qa-unrelated")["lifecycleStatus"] == "ACTIVE"


def test_invalidation_propagates_through_passage_dependency(
    tmp_path: Path, stage4_project: Path,
) -> None:
    engine = _engine(tmp_path)
    _call(engine, "project.open", {"path": str(stage4_project)})
    runtime = engine.passage_semantic_runtime
    passage = runtime.rebuild_current_passage("1", "1")
    runtime.repository.create_qa_finding("qa-via-passage", runtime.project_id)
    runtime.repository.add_record_dependency(
        "QA_FINDING", "qa-via-passage", "PASSAGE_RECORD", passage["id"],
    )
    _call(engine, "verse.edit", {
        "chapter": "1", "verse": "1", "newText": "தொடர் சார்பு மாற்றம்.",
    })
    assert runtime.repository.passage_record(passage["id"])["lifecycleStatus"] == "STALE"
    assert runtime.repository.qa_finding("qa-via-passage")["lifecycleStatus"] == "STALE"


def test_interrupted_invalidation_replays_on_restart(
    tmp_path: Path, stage4_project: Path,
) -> None:
    engine = _engine(tmp_path)
    opened = _call(engine, "project.open", {"path": str(stage4_project)})
    runtime = engine.passage_semantic_runtime
    runtime.repository.create_qa_finding("qa-replay", runtime.project_id)
    runtime.repository.add_record_dependency(
        "QA_FINDING", "qa-replay", "TARGET_REFERENCE",
        runtime.repository.target_dependency_id(runtime.project_id, "RUT", "RUT 1:1"),
    )
    new_text = "விபத்துக்குப் பிறகு மீட்டெடுக்கப்பட்ட வசனம்."
    runtime.prepare_target_edit("1", "1", "புதிய தற்போதைய வசனம்.", new_text)
    chapter_path = stage4_project / "rut" / "1.json"
    chapter = json.loads(chapter_path.read_text(encoding="utf-8"))
    chapter["1"] = new_text
    chapter_path.write_text(json.dumps(chapter, ensure_ascii=False), encoding="utf-8")

    restarted = _engine(tmp_path)
    result = _call(restarted, "project.open", {
        "path": str(stage4_project), "projectId": opened["result"]["projectId"],
    })
    assert result["success"] is True
    assert restarted.passage_semantic_runtime.replayed_invalidations == 1
    assert restarted.passage_semantic_runtime.repository.qa_finding("qa-replay")["lifecycleStatus"] == "STALE"


def test_open_edit_rebuild_reopen_smoke_preserves_stale_review_state(
    tmp_path: Path, stage4_project: Path,
) -> None:
    engine = _engine(tmp_path)
    opened = _call(engine, "project.open", {"path": str(stage4_project)})
    runtime = engine.passage_semantic_runtime
    before = runtime.rebuild_current_passage("1", "1")
    runtime.repository.create_qa_finding("qa-smoke", runtime.project_id)
    runtime.repository.update_qa_disposition(
        "qa-smoke", QaDisposition.ACCEPTABLE_TRANSLATION, 1, "Reviewer",
    )
    runtime.repository.add_record_dependency(
        "QA_FINDING", "qa-smoke", "PASSAGE_RECORD", before["id"],
    )
    edited_text = "முழு சுற்றுச் சோதனை வசனம்."
    assert _call(engine, "verse.edit", {
        "chapter": "1", "verse": "1", "newText": edited_text,
    })["success"] is True
    after = runtime.rebuild_current_passage("1", "1")
    assert before["targetContentHash"] != after["targetContentHash"]
    assert set(before["targetTokenInstanceIds"]).isdisjoint(after["targetTokenInstanceIds"])

    restarted = _engine(tmp_path)
    reopened = _call(restarted, "project.open", {
        "path": str(stage4_project), "projectId": opened["result"]["projectId"],
    })
    assert reopened["success"] is True
    finding = restarted.passage_semantic_runtime.repository.qa_finding("qa-smoke")
    assert finding["reviewStatus"] == "HUMAN_APPROVED"
    assert finding["lifecycleStatus"] == "STALE"
    current = restarted.passage_semantic_runtime.get_current_passage("1", "1")
    assert current["targetTextByDisplayedReference"]["RUT 1:1"] == edited_text


def test_target_edits_create_new_instances_and_only_lineage_candidates(
    tmp_path: Path, stage4_project: Path,
) -> None:
    engine = _engine(tmp_path)
    _call(engine, "project.open", {"path": str(stage4_project)})
    runtime = engine.passage_semantic_runtime
    before = runtime.rebuild_current_passage("1", "1")
    before_ids = set(before["targetTokenInstanceIds"])
    _call(engine, "verse.edit", {
        "chapter": "1", "verse": "1", "newText": "புதிய சொல் தற்போதைய வசனம்.",
    })
    after = runtime.rebuild_current_passage("1", "1")
    after_ids = set(after["targetTokenInstanceIds"])
    assert before_ids.isdisjoint(after_ids)
    candidates = runtime.repository.token_lineage_candidates(runtime.project_id)
    assert candidates
    assert {item["relation"] for item in candidates} == {"POSSIBLE_SUCCESSOR"}


def test_source_lock_change_stales_only_declared_dependents(tmp_path: Path) -> None:
    repo = FoundationRepository(tmp_path / "semantic.sqlite3")
    repo.bind_project_metadata(
        project_id="p", identity_fingerprint="identity", book="RUT",
        target_language_id="tam", resource_id="irv", path=str(tmp_path),
    )
    repo.synchronize_source_lock(
        project_id="p", book="RUT", resource_id="UHB", resource_version="1", resource_hash="old",
    )
    repo.create_qa_finding("qa-source", "p")
    repo.create_qa_finding("qa-other", "p")
    repo.add_record_dependency("QA_FINDING", "qa-source", "SOURCE_RESOURCE", "p\u241fRUT\u241fold")
    changed = repo.synchronize_source_lock(
        project_id="p", book="RUT", resource_id="UHB", resource_version="2", resource_hash="new",
    )
    assert changed == {"changed": True, "staled": 1, "resourceId": "UHB", "resourceVersion": "2", "resourceHash": "new"}
    assert repo.qa_finding("qa-source")["lifecycleStatus"] == "STALE"
    assert repo.qa_finding("qa-other")["lifecycleStatus"] == "ACTIVE"


def test_pending_invalidation_uses_current_revision_cas(tmp_path: Path) -> None:
    repo = FoundationRepository(tmp_path / "semantic.sqlite3")
    repo.bind_project_metadata(
        project_id="p", identity_fingerprint="identity", book="RUT",
        target_language_id="tam", resource_id="irv", path=str(tmp_path),
    )
    repo.establish_target_revision(
        project_id="p", book="RUT", displayed_reference="RUT 1:1",
        text_hash="old", text_revision="revision-old",
    )
    first = repo.prepare_target_invalidation(
        project_id="p", book="RUT", displayed_reference="RUT 1:1",
        previous_text_hash="old", expected_text_hash="first",
    )
    competing = repo.prepare_target_invalidation(
        project_id="p", book="RUT", displayed_reference="RUT 1:1",
        previous_text_hash="old", expected_text_hash="second",
    )
    repo.apply_target_invalidation(
        first, actual_text_hash="first", text_revision="revision-first",
    )
    with pytest.raises(FoundationConflict, match="revision changed"):
        repo.apply_target_invalidation(
            competing, actual_text_hash="second", text_revision="revision-second",
        )


@pytest.mark.parametrize(("decision", "expected"), [
    ("confirmed", ReviewStatus.HUMAN_APPROVED),
    ("corrected", ReviewStatus.HUMAN_MODIFIED),
    ("edited", ReviewStatus.HUMAN_MODIFIED),
    ("rejected", ReviewStatus.HUMAN_REJECTED),
    ("unsure", ReviewStatus.NEEDS_DISCUSSION),
    ("unconfirmed", ReviewStatus.AI_PROPOSED),
])
def test_legacy_review_state_mapping_is_conservative(
    tmp_path: Path, stage4_project: Path, decision: str, expected: ReviewStatus,
) -> None:
    project = TranslationCoreProject(stage4_project)
    runtime = PassageSemanticRuntime(project, "legacy-test")
    assert runtime._legacy_review_status({"decision": decision}) == expected


def test_legacy_validation_is_history_only_and_hash_mismatch_is_stale(
    tmp_path: Path, stage4_project: Path,
) -> None:
    legacy = (
        stage4_project / ".apps" / "translationCoreAI" / "semanticValidation" /
        "irvtam-v0.1.json"
    )
    legacy.parent.mkdir(parents=True)
    legacy.write_text(json.dumps({
        "schema": "bridge.semantic_mapping_validation_audit.v0.1",
        "targetContentHash": "definitely-not-current",
        "decisions": {
            "candidate-1": {
                "decision": "confirmed", "reviewer": "Corpus Reviewer",
                "updatedAt": "2026-08-31T12:00:00+00:00",
            },
        },
    }), encoding="utf-8")

    engine = _engine(tmp_path)
    _call(engine, "project.open", {"path": str(stage4_project)})
    report = engine.passage_semantic_runtime.migration_report()
    imported = next(
        run for run in report["runs"]
        if run["sourceSchema"] == "bridge.semantic_mapping_validation_audit.v0.1"
    )
    assert imported["report"]["reviewStatus"] == "HUMAN_APPROVED"
    assert imported["report"]["lifecycleStatus"] == "STALE"
    evidence_id = imported["report"]["evidenceId"]
    history = engine.passage_semantic_runtime.repository.review_records(
        "EVIDENCE_RECORD", evidence_id,
    )
    assert any(
        item["actorId"] == "Corpus Reviewer"
        and "candidate-1: confirmed" in item["note"]
        for item in history
    )
    assert not engine.passage_semantic_runtime.repository.token_lineage_candidates(
        engine.passage_semantic_runtime.project_id
    )


def test_legacy_record_is_current_only_when_source_and_target_hashes_match(
    tmp_path: Path, stage4_project: Path,
) -> None:
    engine = _engine(tmp_path)
    _call(engine, "project.open", {"path": str(stage4_project)})
    runtime = engine.passage_semantic_runtime
    lock = runtime.repository.source_lock(runtime.project_id, "RUT")
    target = {"RUT 1:1": "புதிய தற்போதைய வசனம்."}
    payload = {
        "sourceResourceHash": lock["resource_hash"],
        "targetContentHash": runtime.repository.target_content_hash(target),
        "result": {"mappings": [{
            "target_spans": [{"reference": "RUT 1:1", "quote": "புதிய"}],
        }]},
    }
    assert runtime._legacy_lifecycle(payload) == LifecycleStatus.ACTIVE
    payload["sourceResourceHash"] = "old-source"
    assert runtime._legacy_lifecycle(payload) == LifecycleStatus.STALE


def test_open_and_passage_rebuild_do_not_mutate_scripture_or_native_alignment(
    tmp_path: Path, stage4_project: Path,
) -> None:
    scripture = (stage4_project / "rut" / "1.json").read_bytes()
    alignment = (
        stage4_project / ".apps" / "translationCore" / "alignmentData" / "rut" / "1.json"
    ).read_bytes()
    engine = _engine(tmp_path)
    _call(engine, "project.open", {"path": str(stage4_project)})
    engine.passage_semantic_runtime.rebuild_current_passage("1", "1")
    assert (stage4_project / "rut" / "1.json").read_bytes() == scripture
    assert (
        stage4_project / ".apps" / "translationCore" / "alignmentData" / "rut" / "1.json"
    ).read_bytes() == alignment


def test_native_alignment_ambiguities_are_quarantined_without_rewrite(
    tmp_path: Path, stage4_project: Path,
) -> None:
    path = stage4_project / ".apps" / "translationCore" / "alignmentData" / "rut" / "1.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    duplicate = {"word": "புதிய", "occurrence": 1, "occurrences": 1}
    payload["1"]["alignments"] = [
        {"topWords": [{"word": "א", "occurrence": 1, "occurrences": 1}], "bottomWords": [duplicate]},
        {"topWords": [{"word": "ב", "occurrence": 1, "occurrences": 1}], "bottomWords": [duplicate]},
        {"topWords": [{"word": "ג", "occurrence": 1, "occurrences": 1}], "bottomWords": []},
    ]
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    original = path.read_bytes()
    engine = _engine(tmp_path)
    _call(engine, "project.open", {"path": str(stage4_project)})
    report = engine.passage_semantic_runtime.migration_report()
    assert report["quarantineByReason"]["DUPLICATE_ACTIVE_TOKEN_MEMBERSHIP"] == 1
    assert report["quarantineByReason"]["LEGACY_EMPTY_BOTTOM_WORDS_AMBIGUOUS"] == 1
    assert path.read_bytes() == original


@pytest.mark.parametrize(("book", "chapter", "verse", "mapped", "kind"), [
    ("RUT", "1", "1", {"mapping": "same", "orgRef": "RUT 1:1"}, "SAME"),
    ("RUT", "1", "1", {"mapping": "mapped", "orgRef": "RUT 1:2"}, "MAPPED"),
    ("RUT", "1", "1", {"mapping": "merge", "orgRef": "RUT 1:1"}, "MERGE"),
    ("RUT", "1", "1", {"mapping": "split", "splitInto": ["RUT 1:1", "RUT 1:2"]}, "SPLIT"),
    ("RUT", "1", "1", {"mapping": "mapped", "orgRef": "RUT 2:1"}, "CHAPTER_SHIFT"),
    ("PSA", "3", "1", {"mapping": "mapped", "orgRef": "PSA 3:0"}, "PSALM_TITLE"),
])
def test_versification_mapping_kinds_are_persistable(
    monkeypatch: pytest.MonkeyPatch,
    book: str,
    chapter: str,
    verse: str,
    mapped: dict,
    kind: str,
) -> None:
    monkeypatch.setattr(
        "tc_ai_bridge.passage_semantic_runtime.versification.to_org_ref",
        lambda *_args: mapped,
    )
    assert _canonical_reference(book, chapter, verse, "test")["mappingKind"] == kind


def test_verse_bridge_and_lettered_segment_are_deterministic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "tc_ai_bridge.passage_semantic_runtime.versification.to_org_ref",
        lambda book, chapter, verse, _schema: {
            "mapping": "same", "orgRef": f"{book} {chapter}:{verse}",
        },
    )
    assert _canonical_reference("RUT", "1", "2-3", "test")["mappingKind"] == "VERSE_BRIDGE"
    assert _canonical_reference("RUT", "1", "4a", "test")["mappingKind"] == "AMBIGUOUS_SEGMENT"
