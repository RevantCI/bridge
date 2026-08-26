"""
Tests for BridgeEngine — the unified dispatcher composing GreekRoomEngine
with real tc_ai_bridge business logic.

Uses a minimal but spec-accurate fixture translationCore project (built
directly from reading TranslationCoreProject's actual parsing code, not
guessed) rather than mocking tc_ai_bridge — the whole point of Phase 1 is
proving the real modules work behind the new protocol.
"""
import json
import shutil
import threading
import time
from pathlib import Path

import pytest

from bridge_service import BridgeEngine
from greek_room_engine.protocol import EngineRequest


@pytest.fixture
def fixture_project(tmp_path):
    root = tmp_path / "rut"
    align_dir = root / ".apps" / "translationCore" / "alignmentData" / "rut"
    align_dir.mkdir(parents=True)
    (root / "rut").mkdir(parents=True)

    (root / "manifest.json").write_text(json.dumps({
        "project": {"id": "rut", "name": "Ruth"},
        "target_language": {"id": "tam", "name": "Tamil"},
        "tc_version": "8", "tc_edit_version": "3.7.0",
    }), encoding="utf-8")

    (align_dir / "1.json").write_text(json.dumps({
        "1": {
            "alignments": [{
                "topWords": [{"word": "אֱלֹהִ֑ים", "strong": "H430", "occurrence": 1, "occurrences": 1}],
                "bottomWords": [{"word": "தேவன்", "occurrence": 1, "occurrences": 1}],
            }],
            "wordBank": [],
        }
    }, ensure_ascii=False), encoding="utf-8")

    (root / "rut" / "1.json").write_text(json.dumps({
        "1": "ஆதியிலே தேவன் வானத்தையும் பூமியையும் படைத்தார்."
    }, ensure_ascii=False), encoding="utf-8")

    (root / "rut.usfm").write_text(
        "\\id RUT\n\\c 1\n\\v 1 ஆதியிலே தேவன் வானத்தையும் பூமியையும் படைத்தார்.\n",
        encoding="utf-8",
    )

    return root


def call(engine, method, params=None):
    return engine.handle_request(EngineRequest(id="t", method=method, params=params or {})).to_dict()


def wait_for_job(engine, job_id, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        snapshot = call(engine, "checks.status", {"jobId": job_id})["result"]
        if snapshot["state"] in {"succeeded", "failed", "cancelled"}:
            return snapshot
        time.sleep(0.01)
    raise AssertionError(f"check job {job_id} did not finish")


def test_ping_and_info_work_without_a_project():
    engine = BridgeEngine()
    assert call(engine, "ping")["result"] == {"pong": True}
    info = call(engine, "engine.info")["result"]
    assert info["projectOpen"] is False
    assert "greekRoom" in info


def test_lexicon_get_entry_works_without_an_open_project():
    engine = BridgeEngine()
    result = call(engine, "lexicon.getEntry", {"strong": "H776", "morph": "He,Ncbsa"})["result"]

    assert result["languageId"] == "hbo"
    assert len(result["segments"]) == 1
    assert result["segments"][0]["lemma"] == "אֶרֶץ"
    assert result["segments"][0]["morphLabel"] == "Noun, Common, Both genders, Singular, Absolute"


def test_lexicon_get_entry_splits_compound_prefix_and_lexeme():
    engine = BridgeEngine()
    result = call(engine, "lexicon.getEntry", {"strong": "d:H0776", "morph": "He,Td:Ncbsa"})["result"]

    assert [s["strong"] for s in result["segments"]] == ["d", "H0776"]
    assert result["segments"][0]["meaning"] == "Definite article (the)"
    assert result["segments"][1]["lemma"] == "אֶרֶץ"


def test_open_real_fixture_project(fixture_project):
    engine = BridgeEngine()
    result = call(engine, "project.open", {"path": str(fixture_project)})
    assert result["success"] is True
    assert result["result"]["bookId"] == "rut"
    assert result["result"]["targetLanguage"] == "Tamil"
    assert result["result"]["chapters"] == ["1"]


def test_verse_get_returns_real_alignment_data(fixture_project):
    engine = BridgeEngine()
    call(engine, "project.open", {"path": str(fixture_project)})
    result = call(engine, "verse.get", {"chapter": "1", "verse": "1"})["result"]
    assert "தேவன்" in result["text"]
    assert result["alignment"]["alignments"][0]["bottomWords"][0]["word"] == "தேவன்"


def test_chapter_verse_data_returns_all_verses_in_one_call(fixture_project):
    """This is the fix for the 'app not responding for minutes' bug — a
    real project chapter with N verses used to mean N sequential Tauri
    round trips before the editor ever appeared. This proves the bulk
    endpoint returns the same data in one call."""
    engine = BridgeEngine()
    call(engine, "project.open", {"path": str(fixture_project)})
    result = call(engine, "chapter.verseData", {"chapter": "1"})["result"]
    assert result["chapter"] == "1"
    assert "1" in result["verses"]
    assert "தேவன்" in result["verses"]["1"]["text"]
    assert result["verses"]["1"]["alignment"]["alignments"][0]["bottomWords"][0]["word"] == "தேவன்"


def _write_alignment_work_fixture(fixture_project):
    path = fixture_project / ".apps" / "translationCore" / "alignmentData" / "rut" / "1.json"
    path.write_text(json.dumps({
        "1": {
            "alignments": [
                {
                    "topWords": [{
                        "word": "אֱלֹהִ֑ים", "strong": "H430", "lemma": "אֱלֹהִים",
                        "morph": "He,Ncmsa", "occurrence": 1, "occurrences": 1,
                    }],
                    "bottomWords": [{
                        "word": "தேவன்", "occurrence": 1, "occurrences": 1,
                        "type": "bottomWord",
                    }],
                },
                {
                    "topWords": [{
                        "word": "בָּרָא", "strong": "H1254", "lemma": "בָּרָא",
                        "morph": "He,Vqp3ms", "occurrence": 1, "occurrences": 1,
                    }],
                    "bottomWords": [],
                },
            ],
            "wordBank": [
                {"word": "ஆதியிலே", "occurrence": 1, "occurrences": 1, "type": "bottomWord"},
                {"word": "வானத்தையும்", "occurrence": 1, "occurrences": 1, "type": "bottomWord"},
                {"word": "பூமியையும்", "occurrence": 1, "occurrences": 1, "type": "bottomWord"},
                {"word": "படைத்தார்", "occurrence": 1, "occurrences": 1, "type": "bottomWord"},
            ],
        },
    }, ensure_ascii=False), encoding="utf-8")


def test_alignment_protocol_realigns_many_to_many_and_undo_survives_restart(fixture_project):
    _write_alignment_work_fixture(fixture_project)
    engine = BridgeEngine()
    call(engine, "project.open", {"path": str(fixture_project)})
    original = call(engine, "alignment.get", {"chapter": "1", "verse": "1"})["result"]

    assert original["sourceAvailable"] is True
    assert original["sourceDirection"] == "rtl"
    assert original["status"] == "partial"
    top_ids = [token["id"] for token in original["topTokens"]]
    bottom_ids = [token["id"] for token in original["bottomTokens"][:2]]
    changed = call(engine, "alignment.realign", {
        "chapter": "1", "verse": "1", "topIds": top_ids, "bottomIds": bottom_ids,
        "expectedOriginal": original["alignment"],
    })

    assert changed["success"] is True
    changed_context = changed["result"]
    assert any(
        len(group["topIds"]) == 2 and len(group["bottomIds"]) == 2
        for group in changed_context["groups"]
    )
    assert changed_context["history"][0]["operation"] == "realign"

    restarted = BridgeEngine()
    call(restarted, "project.open", {"path": str(fixture_project)})
    persisted = call(restarted, "alignment.get", {"chapter": "1", "verse": "1"})["result"]
    undone = call(restarted, "alignment.undo", {
        "chapter": "1", "verse": "1", "expectedOriginal": persisted["alignment"],
    })
    assert undone["success"] is True
    assert undone["result"]["alignment"] == original["alignment"]


def test_alignment_save_rejects_stale_editor_and_completion_requires_full_coverage(fixture_project):
    _write_alignment_work_fixture(fixture_project)
    engine = BridgeEngine()
    call(engine, "project.open", {"path": str(fixture_project)})
    original = call(engine, "alignment.get", {"chapter": "1", "verse": "1"})["result"]
    all_top = [token["id"] for token in original["topTokens"]]
    all_bottom = [token["id"] for token in original["bottomTokens"]]
    changed = call(engine, "alignment.realign", {
        "chapter": "1", "verse": "1", "topIds": all_top, "bottomIds": all_bottom,
        "expectedOriginal": original["alignment"],
    })["result"]

    stale = call(engine, "alignment.save", {
        "chapter": "1", "verse": "1", "alignment": original["alignment"],
        "expectedOriginal": original["alignment"],
    })
    assert stale["success"] is False
    assert stale["error"]["code"] == "project_error"

    completed = call(engine, "alignment.complete", {"chapter": "1", "verse": "1"})
    assert completed["success"] is True
    assert completed["result"]["status"] == "complete"
    assert completed["result"]["completionState"] == "completed"
    assert changed["canComplete"] is True
    restarted = BridgeEngine()
    call(restarted, "project.open", {"path": str(fixture_project)})
    persisted = call(restarted, "alignment.get", {"chapter": "1", "verse": "1"})["result"]
    assert persisted["completionState"] == "completed"
    status = call(restarted, "alignment.status", {"chapter": "1"})["result"]
    assert status["counts"]["complete"] == 1


def test_alignment_unalign_and_restore_selected_history_entry(fixture_project):
    _write_alignment_work_fixture(fixture_project)
    engine = BridgeEngine()
    call(engine, "project.open", {"path": str(fixture_project)})
    original = call(engine, "alignment.get", {"chapter": "1", "verse": "1"})["result"]
    aligned_target = next(
        token["id"] for token in original["bottomTokens"] if token["word"] == "தேவன்"
    )

    changed = call(engine, "alignment.unalign", {
        "chapter": "1", "verse": "1", "bottomIds": [aligned_target],
        "expectedOriginal": original["alignment"],
    })["result"]

    assert any(token["word"] == "தேவன்" for token in changed["alignment"]["wordBank"])
    history_id = changed["history"][0]["id"]
    restored = call(engine, "alignment.restore", {
        "chapter": "1", "verse": "1", "historyId": history_id,
        "expectedOriginal": changed["alignment"],
    })
    assert restored["success"] is True
    assert restored["result"]["alignment"] == original["alignment"]


def test_alignment_history_failure_rolls_back_chapter_write(fixture_project, monkeypatch):
    _write_alignment_work_fixture(fixture_project)
    engine = BridgeEngine()
    call(engine, "project.open", {"path": str(fixture_project)})
    original = call(engine, "alignment.get", {"chapter": "1", "verse": "1"})["result"]

    def fail_history(*_args, **_kwargs):
        raise OSError("simulated history write failure")

    monkeypatch.setattr(engine.project, "_record_alignment_history", fail_history)
    failed = call(engine, "alignment.realign", {
        "chapter": "1", "verse": "1",
        "topIds": [token["id"] for token in original["topTokens"]],
        "bottomIds": [token["id"] for token in original["bottomTokens"]],
        "expectedOriginal": original["alignment"],
    })

    assert failed["success"] is False
    assert engine.project.load_verse_alignment("1", "1").to_dict() == original["alignment"]
    assert engine.project.pending_transactions() == []


def test_alignment_reports_missing_original_language_source(fixture_project):
    path = fixture_project / ".apps" / "translationCore" / "alignmentData" / "rut" / "1.json"
    path.write_text(json.dumps({
        "1": {
            "alignments": [],
            "wordBank": [
                {"word": word, "occurrence": 1, "occurrences": 1, "type": "bottomWord"}
                for word in ["ஆதியிலே", "தேவன்", "வானத்தையும்", "பூமியையும்", "படைத்தார்"]
            ],
        },
    }, ensure_ascii=False), encoding="utf-8")
    engine = BridgeEngine()
    call(engine, "project.open", {"path": str(fixture_project)})

    context = call(engine, "alignment.get", {"chapter": "1", "verse": "1"})["result"]
    assert context["sourceAvailable"] is False
    assert "original-language source tokens" in context["sourceMessage"]
    completed = call(engine, "alignment.complete", {"chapter": "1", "verse": "1"})
    assert completed["success"] is False
    assert completed["error"]["code"] == "alignment_error"


def test_alignment_context_respects_rtl_target_metadata(fixture_project):
    _write_alignment_work_fixture(fixture_project)
    manifest_path = fixture_project / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["target_language"]["direction"] = "rtl"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    engine = BridgeEngine()
    call(engine, "project.open", {"path": str(fixture_project)})

    context = call(engine, "alignment.get", {"chapter": "1", "verse": "1"})["result"]

    assert context["sourceDirection"] == "rtl"
    assert context["targetDirection"] == "rtl"


def test_alignment_flags_non_adjacent_target_group_before_completion(fixture_project):
    _write_alignment_work_fixture(fixture_project)
    engine = BridgeEngine()
    call(engine, "project.open", {"path": str(fixture_project)})
    original = call(engine, "alignment.get", {"chapter": "1", "verse": "1"})["result"]

    changed = call(engine, "alignment.realign", {
        "chapter": "1", "verse": "1",
        "topIds": [original["topTokens"][0]["id"]],
        "bottomIds": [original["bottomTokens"][0]["id"], original["bottomTokens"][2]["id"]],
        "expectedOriginal": original["alignment"],
    })["result"]

    assert changed["canComplete"] is False
    assert any("non-adjacent target words" in issue for issue in changed["issues"])


def test_clean_verse_has_no_findings(fixture_project):
    engine = BridgeEngine()
    call(engine, "project.open", {"path": str(fixture_project)})
    result = call(engine, "verse.runChecks", {"chapter": "1", "verse": "1", "checks": ["local", "greekroom"]})
    assert result["findings"] == []


def test_versification_detect_and_org_ref_work_against_the_real_fixture(fixture_project):
    engine = BridgeEngine()
    call(engine, "project.open", {"path": str(fixture_project)})

    detection = call(engine, "versification.detect")["result"]
    assert detection["available"] is True
    assert set(detection["costBySchema"]) == {"org", "eng", "rsc", "rso", "vul", "lxx"}

    # Ruth is fully canonical across traditions — chapter:verse identity is
    # the correct, real result here, not a stub/placeholder value.
    ref = call(engine, "versification.orgRef", {"chapter": "1", "verse": "1"})["result"]
    assert ref["orgRef"] == "RUT 1:1"
    assert ref["mapping"] == "same"

    back_map = call(engine, "versification.backVersificationMap")["result"]
    assert back_map["schema"] in {"org", "eng", "rsc", "rso", "vul", "lxx"}
    assert all(ref.startswith("RUT ") for ref in back_map["map"])


@pytest.fixture
def psalms_fixture_project(tmp_path):
    """A minimal PSA project covering Psalm 3, whose Hebrew ('org') text
    numbers its descriptive title as verse 1 — a real, well-known
    cross-tradition numbering shift most English Bibles don't reproduce.
    Used to prove the versification protocol methods surface that real
    shift end to end, not just identity mappings like the Ruth fixture."""
    root = tmp_path / "psa"
    align_dir = root / ".apps" / "translationCore" / "alignmentData" / "psa"
    align_dir.mkdir(parents=True)
    (root / "psa").mkdir(parents=True)

    (root / "manifest.json").write_text(json.dumps({
        "project": {"id": "psa", "name": "Psalms"},
        "target_language": {"id": "en", "name": "English"},
        "tc_version": "8", "tc_edit_version": "3.7.0",
    }), encoding="utf-8")

    (align_dir / "3.json").write_text(json.dumps({
        "1": {"alignments": [], "wordBank": []},
        "2": {"alignments": [], "wordBank": []},
    }), encoding="utf-8")

    (root / "psa" / "3.json").write_text(json.dumps({
        "1": "LORD, how are they increased that trouble me!",
        "2": "Many there be which say of my soul,",
    }), encoding="utf-8")

    return root


def test_versification_org_ref_surfaces_the_real_psalm_3_shift(psalms_fixture_project):
    engine = BridgeEngine()
    call(engine, "project.open", {"path": str(psalms_fixture_project)})

    ref = call(engine, "versification.orgRef", {"chapter": "3", "verse": "1", "schema": "eng"})["result"]
    assert ref["orgRef"] == "PSA 3:2"
    assert ref["mapping"] == "mapped"

    back_map = call(engine, "versification.backVersificationMap", {"schema": "eng"})["result"]
    assert back_map["map"]["PSA 3:2"] == "PSA 3:1"


def test_chapter_check_job_reports_real_progress_and_results(fixture_project, monkeypatch):
    engine = BridgeEngine()
    call(engine, "project.open", {"path": str(fixture_project)})
    monkeypatch.setattr(
        engine, "_usfm_findings_for_book",
        lambda project=None, cancel_event=None: [],
    )

    started = call(engine, "checks.start", {
        "scope": "chapter", "chapters": ["1"], "checks": ["local", "greekroom"],
    })["result"]
    finished = wait_for_job(engine, started["jobId"])

    assert finished["state"] == "succeeded"
    assert finished["percent"] == 100
    assert finished["chapterVerses"] == {"1": ["1"]}
    assert finished["results"]["1:1"]["status"] == "succeeded"
    assert isinstance(finished["results"]["1:1"]["findings"], list)


def test_whole_book_job_checks_every_chapter_once(fixture_project):
    (fixture_project / "rut" / "2.json").write_text(json.dumps({
        "1": "இரண்டாம் அதிகாரம்.",
    }, ensure_ascii=False), encoding="utf-8")
    alignment_dir = fixture_project / ".apps" / "translationCore" / "alignmentData" / "rut"
    (alignment_dir / "2.json").write_text(json.dumps({
        "1": {"alignments": [], "wordBank": [{
            "word": "இரண்டாம்", "occurrence": 1, "occurrences": 1,
        }]},
    }, ensure_ascii=False), encoding="utf-8")
    engine = BridgeEngine()
    call(engine, "project.open", {"path": str(fixture_project)})

    started = call(engine, "checks.start", {
        "scope": "book", "checks": ["greekroom"],
    })["result"]
    finished = wait_for_job(engine, started["jobId"])

    assert finished["state"] == "succeeded"
    assert finished["chapterVerses"] == {"1": ["1"], "2": ["1"]}
    assert set(finished["results"]) == {"1:1", "2:1"}
    assert all(result["status"] == "succeeded" for result in finished["results"].values())


def test_check_job_can_cancel_and_retry(fixture_project, monkeypatch):
    engine = BridgeEngine()
    call(engine, "project.open", {"path": str(fixture_project)})
    entered = threading.Event()
    release = threading.Event()

    def slow_check(project, chapter, verse, checks):
        entered.set()
        release.wait(timeout=2)
        return []

    monkeypatch.setattr(engine, "_run_verse_checks_for_project", slow_check)
    started = call(engine, "checks.start", {
        "scope": "chapter", "chapters": ["1"], "checks": ["greekroom"],
    })["result"]
    assert entered.wait(timeout=1)

    cancelling = call(engine, "checks.cancel", {"jobId": started["jobId"]})["result"]
    assert cancelling["state"] == "cancelling"
    release.set()
    cancelled = wait_for_job(engine, started["jobId"])
    assert cancelled["state"] == "cancelled"

    retried = call(engine, "checks.retry", {"jobId": started["jobId"]})["result"]
    finished = wait_for_job(engine, retried["jobId"])
    assert finished["state"] == "succeeded"
    assert finished["jobId"] != started["jobId"]


def test_check_job_cancels_during_usfm_preflight(fixture_project, monkeypatch):
    from greek_room_engine.adapters.usfm_adapter import UsfmCheckerCancelled

    engine = BridgeEngine()
    call(engine, "project.open", {"path": str(fixture_project)})
    entered = threading.Event()

    def slow_preflight(project=None, cancel_event=None):
        entered.set()
        assert cancel_event is not None
        cancel_event.wait(timeout=2)
        raise UsfmCheckerCancelled("cancelled by test")

    monkeypatch.setattr(engine, "_usfm_findings_for_book", slow_preflight)
    started = call(engine, "checks.start", {
        "scope": "chapter", "chapters": ["1"], "checks": ["local"],
    })["result"]
    assert entered.wait(timeout=1)
    call(engine, "checks.cancel", {"jobId": started["jobId"]})

    cancelled = wait_for_job(engine, started["jobId"])
    assert cancelled["state"] == "cancelled"
    assert cancelled["finishedAt"] is not None


def test_check_job_rejects_a_second_active_job(fixture_project, monkeypatch):
    engine = BridgeEngine()
    call(engine, "project.open", {"path": str(fixture_project)})
    entered = threading.Event()
    release = threading.Event()

    def slow_check(project, chapter, verse, checks):
        entered.set()
        release.wait(timeout=2)
        return []

    monkeypatch.setattr(engine, "_run_verse_checks_for_project", slow_check)
    first = call(engine, "checks.start", {
        "scope": "chapter", "chapters": ["1"], "checks": ["greekroom"],
    })["result"]
    assert entered.wait(timeout=1)
    second = call(engine, "checks.start", {
        "scope": "chapter", "chapters": ["1"], "checks": ["greekroom"],
    })
    assert second["success"] is False
    assert second["error"]["code"] == "job_conflict"
    call(engine, "checks.cancel", {"jobId": first["jobId"]})
    release.set()
    wait_for_job(engine, first["jobId"])


def test_mixed_script_verse_is_flagged_by_greek_room(monkeypatch):
    # Force the mock adapter path — see test_wildebeest_real.py for
    # coverage of the real engine, skipped when it isn't installed.
    from greek_room_engine.adapters import wildebeest_adapter
    monkeypatch.setattr(wildebeest_adapter, "_WILDEBEEST_AVAILABLE", False)

    engine = BridgeEngine()
    findings = engine.greek_room.check_verse(
        project_id="p", lang_code="tam", ref="RUT 1:1", text="தேவன்aஆதி", checks=["wildebeest"],
    )
    assert any(f.check_type == "wildebeest.script.mixed" for f in findings)


def test_decide_verse_writes_real_qa_decision_file(fixture_project):
    engine = BridgeEngine()
    call(engine, "project.open", {"path": str(fixture_project)})
    result = call(engine, "verse.decide", {
        "chapter": "1", "verse": "1", "findingId": "test-finding",
        "status": "accepted", "comment": "looks fine",
    })["result"]
    written = Path(result["recordedAt"])
    assert written.exists()
    data = json.loads(written.read_text(encoding="utf-8"))
    assert data["decision"] == "accepted"
    assert data["issueKey"] == "test-finding"


def test_usfm_checks_run_once_per_book_not_once_per_verse(fixture_project):
    """The real checker spawns a subprocess loading a full tag database —
    calling it once per verse.runChecks call during a whole-book pass would
    be far too slow. Confirms the book-level cache actually caches, using a
    stub instead of the real vendored checker so this stays fast and
    independent of whether it's installed correctly in this environment."""
    engine = BridgeEngine()
    call(engine, "project.open", {"path": str(fixture_project)})

    call_count = 0

    def fake_check_book_usfm(*, project_id, book_id, usfm_text, cancel_event=None):
        nonlocal call_count
        call_count += 1
        from greek_room_engine.models.finding import QaFinding, FindingCategory, Severity
        return [QaFinding(
            project_id=project_id, book=book_id, chapter=1, verse=1,
            engine="usfm", check_type="usfm.fake_issue",
            category=FindingCategory.STRUCTURE, severity=Severity.HIGH,
            explanation="fake finding for the cache test",
        )]

    engine.greek_room.check_book_usfm = fake_check_book_usfm

    result1 = call(engine, "verse.runChecks", {"chapter": "1", "verse": "1", "checks": ["local"]})
    result2 = call(engine, "verse.runChecks", {"chapter": "1", "verse": "1", "checks": ["local"]})

    assert call_count == 1, "check_book_usfm should be cached, not re-run per verse.runChecks call"
    assert any(f["check_type"] == "usfm.fake_issue" for f in result1["findings"])
    assert any(f["check_type"] == "usfm.fake_issue" for f in result2["findings"])


def test_usfm_checker_failure_is_protocol_error_and_cached(fixture_project):
    """A checker crash must never be indistinguishable from a clean book."""
    from greek_room_engine.adapters.usfm_adapter import UsfmCheckerError

    engine = BridgeEngine()
    call(engine, "project.open", {"path": str(fixture_project)})
    call_count = 0

    def failed_check(**kwargs):
        nonlocal call_count
        call_count += 1
        raise UsfmCheckerError("helper failed")

    engine.greek_room.check_book_usfm = failed_check
    first = call(engine, "verse.runChecks", {"chapter": "1", "verse": "1", "checks": ["local"]})
    second = call(engine, "verse.runChecks", {"chapter": "1", "verse": "1", "checks": ["local"]})

    assert first["success"] is False
    assert first["error"]["code"] == "checker_error"
    assert second["error"]["code"] == "checker_error"
    assert call_count == 1


def test_usfm_finding_for_missing_verse_surfaces_on_first_existing_verse(fixture_project):
    """The UI cannot request a missing verse, so chapter-level structural
    findings must be attached to an existing display slot."""
    from greek_room_engine.models.finding import QaFinding, FindingCategory, Severity

    engine = BridgeEngine()
    call(engine, "project.open", {"path": str(fixture_project)})
    engine.greek_room.check_book_usfm = lambda **kwargs: [QaFinding(
        project_id="p", book="rut", chapter=1, verse=2,
        engine="usfm", check_type="usfm.chapters_with_missing_verses",
        category=FindingCategory.STRUCTURE, severity=Severity.HIGH,
        explanation="Missing verse: 2",
    )]

    result = call(engine, "verse.runChecks", {
        "chapter": "1", "verse": "1", "checks": ["usfm"],
    })
    assert result["success"] is True
    assert any("missing_verses" in f["check_type"] for f in result["findings"])


def test_edit_verse_creates_transaction_backup(fixture_project):
    engine = BridgeEngine()
    call(engine, "project.open", {"path": str(fixture_project)})
    result = call(engine, "verse.edit", {"chapter": "1", "verse": "1", "newText": "test"})
    assert result["result"]["committed"] is True
    tx_dir = fixture_project / ".apps" / "translationCoreAI" / "transactions"
    assert any(tx_dir.glob("*.json"))


def test_edit_verse_actually_writes_the_new_text_and_invalidates_alignment(fixture_project):
    """Guards against edit_verse regressing to its old stub, which committed
    a transaction but never wrote anything — verse.get would still show the
    pre-edit text. Also verifies the real tc_project.apply_scripture_edit()
    behavior this now calls: word alignment is marked invalid (its bottomWord
    tokens no longer match the new text) rather than silently kept stale."""
    engine = BridgeEngine()
    call(engine, "project.open", {"path": str(fixture_project)})
    call(engine, "verse.edit", {"chapter": "1", "verse": "1", "newText": "புதிய வார்த்தைகள்"})

    verse = call(engine, "verse.get", {"chapter": "1", "verse": "1"})["result"]
    assert verse["text"] == "புதிய வார்த்தைகள்"
    assert verse["alignment"]["alignments"][0]["bottomWords"] == []
    assert [t["word"] for t in verse["alignment"]["wordBank"]] == ["புதிய", "வார்த்தைகள்"]

    findings = call(engine, "verse.runChecks", {"chapter": "1", "verse": "1", "checks": ["local"]})["findings"]
    assert any(f["check_type"] == "WA_INVALID" for f in findings)


def test_edit_verse_with_unchanged_text_fails_gracefully(fixture_project):
    engine = BridgeEngine()
    call(engine, "project.open", {"path": str(fixture_project)})
    current = call(engine, "verse.get", {"chapter": "1", "verse": "1"})["result"]["text"]
    result = call(engine, "verse.edit", {"chapter": "1", "verse": "1", "newText": current})
    assert result["success"] is False
    assert result["error"]["code"] == "project_error"


def test_open_missing_project_fails_gracefully():
    engine = BridgeEngine()
    result = call(engine, "project.open", {"path": "/no/such/path"})
    assert result["success"] is False
    assert result["error"]["code"] == "project_error"


def test_verse_op_before_project_open_fails_gracefully():
    engine = BridgeEngine()
    result = call(engine, "chapter.verses", {"chapter": "1"})
    assert result["success"] is False
    assert result["error"]["code"] == "project_error"


def test_settings_get_has_safe_defaults(tmp_path, monkeypatch):
    # AppSettings() with no explicit path reads a real, persistent location
    # on the machine (and get_api_key() also checks $OPENAI_API_KEY) — that
    # is correct production behavior, but tests must not depend on or leak
    # into the real machine's settings. Isolate explicitly.
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    from tc_ai_bridge.secret_store import AppSettings
    isolated = AppSettings(path=tmp_path / "settings.json")
    engine = BridgeEngine(settings=isolated)
    result = call(engine, "settings.get")["result"]
    assert result["hasApiKey"] is False
    assert "model" in result
    assert result["reviewerMode"] == "basic"


def test_settings_persists_valid_reviewer_mode_and_rejects_invalid_mode(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    from tc_ai_bridge.secret_store import AppSettings

    settings_path = tmp_path / "settings.json"
    engine = BridgeEngine(settings=AppSettings(path=settings_path))
    changed = call(engine, "settings.set", {"reviewerMode": "advanced"})
    assert changed["success"] is True
    assert changed["result"]["reviewerMode"] == "advanced"

    restarted = BridgeEngine(settings=AppSettings(path=settings_path))
    assert call(restarted, "settings.get")["result"]["reviewerMode"] == "advanced"
    invalid = call(restarted, "settings.set", {"reviewerMode": "expert"})
    assert invalid["success"] is False


def test_settings_get_reflects_a_saved_api_key(tmp_path, monkeypatch):
    """Documents the real (correct) behavior: once a key is saved, hasApiKey
    flips to True. This is what you're seeing on a machine that already has
    a saved key or OPENAI_API_KEY set — not a bug."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    from tc_ai_bridge.secret_store import AppSettings
    isolated = AppSettings(path=tmp_path / "settings.json")
    engine = BridgeEngine(settings=isolated)
    call(engine, "settings.set", {"apiKey": "sk-test-123"})
    result = call(engine, "settings.get")["result"]
    assert result["hasApiKey"] is True
    persisted = (tmp_path / "settings.json").read_text(encoding="utf-8")
    assert "sk-test-123" not in persisted
    assert "_session_api_key" not in persisted


def test_settings_load_removes_legacy_plaintext_session_key(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    from tc_ai_bridge.secret_store import AppSettings

    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps({"model": "gpt-5.6", "_session_api_key": "sk-legacy-plaintext"}),
        encoding="utf-8",
    )

    settings = AppSettings(path=settings_path)

    assert settings.get_api_key() == "sk-legacy-plaintext"
    persisted = settings_path.read_text(encoding="utf-8")
    assert "sk-legacy-plaintext" not in persisted
    assert "_session_api_key" not in persisted


def test_qaissue_categorization_matches_real_local_checks_codes():
    """Locks in the code/title -> FindingCategory mapping against the
    ACTUAL codes local_checks.py produces (checked against source, not
    assumed) so the UI's tN/tW/Alignment color-coding stays correct."""
    from bridge_service import _categorize_qaissue
    from tc_ai_bridge.models import QAIssue
    from greek_room_engine.models.finding import FindingCategory

    cases = [
        (QAIssue("ALIGN_DUP_TOP", "critical", "x", "y"), FindingCategory.ALIGNMENT),
        (QAIssue("WA_INVALID", "high", "x", "y", "translationCore"), FindingCategory.ALIGNMENT),
        (QAIssue("USFM_BALANCE", "high", "x", "y", "local"), FindingCategory.STRUCTURE),
        (QAIssue("SRC_REPEAT_WORD", "medium", "x", "y"), FindingCategory.REPETITION),
        (QAIssue("TGT_HIDDEN_CHAR", "editorial", "x", "y"), FindingCategory.UNICODE),
        (QAIssue("TC_PENDING", "high", "translationWords: unchecked item", "y", "translationCore"), FindingCategory.TRANSLATION_WORD),
        (QAIssue("TC_INVALIDATED", "high", "translationNotes: recheck required", "y", "translationCore"), FindingCategory.TRANSLATION_NOTE),
        (QAIssue("TC_COMMENTS", "info", "Reviewer comments present", "y", "translationCore"), FindingCategory.CONSISTENCY),
    ]
    for issue, expected in cases:
        assert _categorize_qaissue(issue) == expected, f"{issue.code} -> expected {expected}"


def test_finding_ids_are_stable_across_repeated_check_runs():
    """The bug this fixes: findings used to get a random uuid4 id every
    time verse.runChecks ran, so a saved decision could never be matched
    back to 'the same' finding later. This proves ids are now stable."""
    from bridge_service import _stable_finding_id
    id1 = _stable_finding_id(chapter="1", verse="3", engine="wildebeest", check_type="wildebeest.script.mixed", disambiguator="7:8:a")
    id2 = _stable_finding_id(chapter="1", verse="3", engine="wildebeest", check_type="wildebeest.script.mixed", disambiguator="7:8:a")
    assert id1 == id2
    id3 = _stable_finding_id(chapter="1", verse="4", engine="wildebeest", check_type="wildebeest.script.mixed", disambiguator="7:8:a")
    assert id1 != id3  # different verse -> different id


def test_greek_room_finding_id_is_stable_across_repeated_check_runs(fixture_project):
    # overwrite verse 1 text with a mixed-script token so Greek Room flags it
    (fixture_project / "rut" / "1.json").write_text(
        '{"1": "\\u0ba4\\u0bc7\\u0bb5\\u0ba9a"}', encoding="utf-8"
    )
    engine = BridgeEngine()
    call(engine, "project.open", {"path": str(fixture_project)})
    findings1 = call(engine, "verse.runChecks", {"chapter": "1", "verse": "1", "checks": ["greekroom"]})["findings"]
    findings2 = call(engine, "verse.runChecks", {"chapter": "1", "verse": "1", "checks": ["greekroom"]})["findings"]
    assert len(findings1) >= 1 and len(findings2) >= 1
    assert findings1[0]["id"] == findings2[0]["id"]


def test_decision_persists_across_repeated_check_runs(fixture_project):
    """The actual feature: accept a finding, re-run checks (simulating
    reopening the project), and confirm the finding comes back already
    marked accepted instead of resetting to open."""
    (fixture_project / "rut" / "1.json").write_text(
        '{"1": "\\u0ba4\\u0bc7\\u0bb5\\u0ba9a"}', encoding="utf-8"
    )
    engine = BridgeEngine()
    call(engine, "project.open", {"path": str(fixture_project)})

    first_run = call(engine, "verse.runChecks", {"chapter": "1", "verse": "1", "checks": ["greekroom"]})["findings"]
    assert first_run[0]["status"] == "open"
    finding_id = first_run[0]["id"]

    call(engine, "verse.decide", {
        "chapter": "1", "verse": "1", "findingId": finding_id,
        "status": "accepted", "comment": "reviewed",
    })

    second_run = call(engine, "verse.runChecks", {"chapter": "1", "verse": "1", "checks": ["greekroom"]})["findings"]
    assert second_run[0]["id"] == finding_id
    assert second_run[0]["status"] == "accepted"
    assert second_run[0]["human_comment"] == "reviewed"

    restarted = BridgeEngine()
    call(restarted, "project.open", {"path": str(fixture_project)})
    after_restart = call(restarted, "verse.runChecks", {
        "chapter": "1", "verse": "1", "checks": ["greekroom"],
    })["findings"]
    assert after_restart[0]["id"] == finding_id
    assert after_restart[0]["status"] == "accepted"
    assert after_restart[0]["human_comment"] == "reviewed"


def test_settings_supports_any_provider_not_just_openai(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    from tc_ai_bridge.secret_store import AppSettings
    isolated = AppSettings(path=tmp_path / "settings.json")
    engine = BridgeEngine(settings=isolated)

    result = call(engine, "settings.set", {
        "provider": "anthropic",
        "apiBaseUrl": "https://api.anthropic.com/v1",
        "model": "claude-sonnet-5",
        "apiKey": "sk-ant-test",
    })["result"]
    assert result["provider"] == "anthropic"
    assert result["apiBaseUrl"] == "https://api.anthropic.com/v1"
    assert result["model"] == "claude-sonnet-5"
    assert result["hasApiKey"] is True


def test_export_non_aligned_writes_real_usfm_file(fixture_project, tmp_path):
    engine = BridgeEngine()
    call(engine, "project.open", {"path": str(fixture_project)})
    out_path = tmp_path / "export.usfm"
    result = call(engine, "export.nonAligned", {"outputPath": str(out_path)})["result"]
    assert result["written"] is True
    assert result["fidelity"] == "source-preserving"
    content = out_path.read_text(encoding="utf-8")
    assert "\\id RUT" in content
    assert "\\c 1" in content
    assert "\\v 1" in content
    assert "தேவன்" in content
    from tc_ai_bridge.project_import import inspect_import
    preview = inspect_import(out_path)
    assert preview["books"][0]["bookId"] == "rut"
    assert preview["books"][0]["verseCount"] == 1


@pytest.mark.parametrize("source_encoding", ["utf-8", "utf-16"])
def test_non_aligned_export_preserves_usfm_esfm_structure(tmp_path, source_encoding):
    source = tmp_path / "TIT.usfm"
    source.write_text(
        "\\id TIT\n"
        "\\usfm 3.0\n"
        "\\h Titus\n"
        "\\toc1 The Letter to Titus\n"
        "\\c 1\n"
        "\\s1 Greeting\n"
        "\\p\n"
        "\\v 1 Paul spoke. \\f + \\ft A footnote.\\f*\n"
        "\\q1 A poetry continuation.\n"
        "\\v 3-4 Bridged text. \\zbridge custom\\zbridge*\n",
        encoding=source_encoding,
    )
    engine = BridgeEngine()
    imported = call(engine, "project.import", {
        "path": str(source),
        "destinationRoot": str(tmp_path / "projects"),
        "metadata": {
            "languageId": "eng",
            "languageName": "English",
            "languageDirection": "ltr",
            "projectName": "Titus",
            "bibleName": "Test Bible",
        },
    })
    assert imported["success"] is True

    out_path = tmp_path / "exported.usfm"
    exported = call(engine, "export.nonAligned", {"outputPath": str(out_path)})["result"]
    content = out_path.read_text(encoding="utf-8")

    assert exported["fidelity"] == "source-preserving"
    for marker in ("\\usfm 3.0", "\\h Titus", "\\toc1", "\\s1 Greeting", "\\p",
                   "\\f +", "\\ft A footnote.", "\\q1", "\\v 3-4", "\\zbridge"):
        assert marker in content
    from tc_ai_bridge.project_import import inspect_import
    preview = inspect_import(out_path)
    assert preview["books"][0]["verseCount"] == 2


def test_non_aligned_export_has_explicit_fallback_without_source(fixture_project, tmp_path):
    (fixture_project / "rut.usfm").unlink()
    engine = BridgeEngine()
    call(engine, "project.open", {"path": str(fixture_project)})
    out_path = tmp_path / "fallback.usfm"

    result = call(engine, "export.nonAligned", {"outputPath": str(out_path)})["result"]

    assert result["fidelity"] == "simplified"
    assert "No source USFM was available" in result["note"]
    assert "\\v 1 " in out_path.read_text(encoding="utf-8")


def test_export_aligned_writes_real_json_with_alignment_and_decisions(fixture_project, tmp_path):
    engine = BridgeEngine()
    call(engine, "project.open", {"path": str(fixture_project)})
    call(engine, "verse.decide", {
        "chapter": "1", "verse": "1", "findingId": "some-finding",
        "status": "accepted", "comment": "ok",
    })
    out_path = tmp_path / "export.json"
    result = call(engine, "export.aligned", {"outputPath": str(out_path)})["result"]
    assert result["written"] is True
    import json as _json
    data = _json.loads(out_path.read_text(encoding="utf-8"))
    assert data["bookId"] == "rut"
    verse1 = data["chapters"]["1"]["1"]
    assert verse1["alignment"]["alignments"][0]["bottomWords"][0]["word"] == "தேவன்"
    assert "some-finding" in verse1["decisions"]


def test_export_aligned_usfm_round_trips_nested_many_to_many_alignment(fixture_project, tmp_path):
    _write_alignment_work_fixture(fixture_project)
    engine = BridgeEngine()
    call(engine, "project.open", {"path": str(fixture_project)})
    context = call(engine, "alignment.get", {"chapter": "1", "verse": "1"})["result"]
    context = call(engine, "alignment.realign", {
        "chapter": "1", "verse": "1",
        "topIds": [token["id"] for token in context["topTokens"]],
        "bottomIds": [token["id"] for token in context["bottomTokens"]],
        "expectedOriginal": context["alignment"],
    })["result"]
    assert call(engine, "alignment.complete", {"chapter": "1", "verse": "1"})["success"] is True

    output = tmp_path / "rut-aligned.usfm"
    exported = call(engine, "export.aligned", {"outputPath": str(output)})

    assert exported["success"] is True
    assert exported["result"]["format"] == "usfm3-aligned"
    content = output.read_text(encoding="utf-8")
    assert "\\usfm 3.0" in content
    assert content.count("\\zaln-s") == 2
    assert content.count("\\zaln-e\\*") == 2
    assert "\\w தேவன்|x-occurrence=\"1\" x-occurrences=\"1\"\\w*" in content

    from tc_ai_bridge.project_import import import_source
    from tc_ai_bridge.tc_project import TranslationCoreProject
    reimported = import_source(output, tmp_path / "reimported", {
        "languageId": "tam", "languageName": "Tamil", "languageDirection": "ltr",
        "projectName": "Round trip", "bibleName": "Round trip Bible",
    })
    project = TranslationCoreProject(reimported["primaryProjectPath"])
    round_trip = project.load_verse_alignment("1", "1")
    assert len(round_trip.alignments) == 1
    assert len(round_trip.alignments[0].top_words) == 2
    assert len(round_trip.alignments[0].bottom_words) == 5
    assert round_trip.word_bank == []


def _make_managed_book(managed_root: Path, book_id: str) -> Path:
    path = managed_root / book_id
    (path / book_id).mkdir(parents=True)
    (path / "manifest.json").write_text(json.dumps({
        "project": {"id": book_id, "name": book_id.upper()},
        "target_language": {"id": "tam", "name": "Tamil"},
    }), encoding="utf-8")
    (path / book_id / "1.json").write_text('{"1": "text"}', encoding="utf-8")
    return path


def test_delete_project_removes_a_managed_collection_from_disk_and_registry(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    from tc_ai_bridge.secret_store import AppSettings
    engine = BridgeEngine(settings=AppSettings(path=tmp_path / "settings.json"))

    tit_path = _make_managed_book(engine.project_root, "tit")
    phm_path = _make_managed_book(engine.project_root, "phm")
    tit_entry = engine.project_registry.register(tit_path, collection_id="collection-x")
    engine.project_registry.register(phm_path, collection_id="collection-x")

    result = call(engine, "project.delete", {"projectId": tit_entry["projectId"]})["result"]

    assert result == {"deleted": True, "managed": True}
    assert not tit_path.exists()
    assert not phm_path.exists()
    assert call(engine, "project.list")["result"]["projects"] == []


def test_delete_project_never_removes_files_for_an_unmanaged_project(tmp_path, monkeypatch, fixture_project):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    from tc_ai_bridge.secret_store import AppSettings
    engine = BridgeEngine(settings=AppSettings(path=tmp_path / "settings.json"))

    registered = engine.project_registry.register(fixture_project)
    assert registered["managed"] is False

    result = call(engine, "project.delete", {"projectId": registered["projectId"]})["result"]

    assert result == {"deleted": True, "managed": False}
    assert fixture_project.exists()
    assert call(engine, "project.list")["result"]["projects"] == []
