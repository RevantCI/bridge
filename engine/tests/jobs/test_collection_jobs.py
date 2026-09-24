"""collection.runChecks (layered-rules Phase 4.4): every book of a collection,
resumable, pausable, cancellable, with one whole-collection stage at the end."""
import json
import threading
import time

import pytest

from bridge_service import BridgeEngine
from collection_jobs import CollectionJobConflict, CollectionJobManager, CollectionJobSpec
from tc_ai_bridge.language_qa_jobs import LanguageQaManager
from tc_ai_bridge.project_import import collection_qa_runs
from tests.service.test_bridge_service import _write_minimal_book, call
from tests.support.waits import job_timeout


# ---- the manager, with stand-in work ------------------------------------------

def books(*ids):
    return tuple({"bookId": b, "bookName": b.upper(), "path": f"/x/{b}"} for b in ids)


def wait_done(manager, job_id, timeout=5.0):
    deadline = time.monotonic() + job_timeout(timeout)
    while time.monotonic() < deadline:
        snapshot = manager.status(job_id)
        if snapshot["state"] in {"succeeded", "failed", "cancelled"}:
            return snapshot
        time.sleep(0.01)
    raise AssertionError("collection run did not finish")


def test_runs_every_book_in_order_records_each_and_runs_the_final_stage_once():
    ran, recorded, finals = [], [], []
    manager = CollectionJobManager()
    started = manager.start(
        CollectionJobSpec("/x/rut", books("rut", "gen", "exo"), ("languageQa",)),
        run_book=lambda book, cancel: ran.append(book["bookId"]) or {
            "state": "succeeded", "jobId": f"j-{book['bookId']}", "findingsByCategory": {"sandhi": 1}},
        record_run=recorded.append,
        final_stage=lambda done, cancel: finals.append([b["bookId"] for b in done]) or {"ok": True},
        book_hash=lambda book: f"h-{book['bookId']}")
    snapshot = wait_done(manager, started["jobId"])
    assert snapshot["state"] == "succeeded" and ran == ["rut", "gen", "exo"]
    assert [r["bookId"] for r in recorded] == ["rut", "gen", "exo"]
    assert recorded[0]["contentHash"] == "h-rut" and recorded[0]["findingsByCategory"] == {"sandhi": 1}
    assert finals == [["rut", "gen", "exo"]] and snapshot["finalStage"] == {"ok": True}
    assert all(b["state"] == "done" and b["elapsedSeconds"] is not None for b in snapshot["books"])


def test_resumes_by_skipping_books_whose_content_is_unchanged():
    ran = []
    previous = {"rut": {"state": "done", "contentHash": "h-rut", "checks": ["languageQa"],
                        "findingsByCategory": {"typo": 2}},
                "gen": {"state": "done", "contentHash": "old", "checks": ["languageQa"]}}
    manager = CollectionJobManager()
    started = manager.start(
        CollectionJobSpec("/x/rut", books("rut", "gen"), ("languageQa",), previous_runs=previous),
        run_book=lambda book, cancel: ran.append(book["bookId"]) or {"state": "succeeded"},
        record_run=lambda entry: None, book_hash=lambda book: f"h-{book['bookId']}")
    snapshot = wait_done(manager, started["jobId"])
    assert ran == ["gen"]  # rut unchanged since its last completed run; gen changed
    assert [b["state"] for b in snapshot["books"]] == ["skipped", "done"]
    assert snapshot["books"][0]["findingsByCategory"] == {"typo": 2}
    # A previous run with fewer checks does not count; nor does force.
    for spec in (CollectionJobSpec("/x/rut", books("rut"), ("languageQa", "local"), previous_runs=previous),
                 CollectionJobSpec("/x/rut", books("rut"), ("languageQa",), previous_runs=previous, force=True)):
        ran.clear()
        wait_done(manager, manager.start(spec, run_book=lambda book, cancel: ran.append(1) or {"state": "succeeded"},
                                         record_run=lambda e: None, book_hash=lambda b: "h-rut")["jobId"])
        assert ran == [1]


def test_cancel_records_nothing_for_the_book_in_flight_and_skips_the_final_stage():
    gate, recorded, finals = threading.Event(), [], []

    def run_book(book, cancel):
        gate.set()
        cancel.wait(5)
        return {"state": "cancelled"}

    manager = CollectionJobManager()
    started = manager.start(CollectionJobSpec("/x/rut", books("rut", "gen"), ("languageQa",)),
                            run_book=run_book, record_run=recorded.append,
                            final_stage=lambda done, cancel: finals.append(1) or {}, book_hash=lambda b: "h")
    gate.wait(5)
    manager.cancel(started["jobId"])
    snapshot = wait_done(manager, started["jobId"])
    assert snapshot["state"] == "cancelled" and recorded == [] and finals == []
    assert [b["state"] for b in snapshot["books"]] == ["pending", "pending"]


def test_pause_holds_the_next_book_until_resumed_and_one_run_at_a_time():
    started_books, first_done = [], threading.Event()

    def run_book(book, cancel):
        started_books.append(book["bookId"])
        if book["bookId"] == "rut":
            first_done.wait(5)
        return {"state": "succeeded"}

    manager = CollectionJobManager()
    started = manager.start(CollectionJobSpec("/x/rut", books("rut", "gen"), ("languageQa",)),
                            run_book=run_book, record_run=lambda e: None, book_hash=lambda b: "")
    with pytest.raises(CollectionJobConflict):
        manager.start(CollectionJobSpec("/x/rut", books("rut"), ("languageQa",)),
                      run_book=run_book, record_run=lambda e: None)
    assert manager.pause(True, started["jobId"])["paused"] is True
    first_done.set()
    time.sleep(0.2)
    assert started_books == ["rut"]  # paused between books
    manager.pause(False, started["jobId"])
    assert wait_done(manager, started["jobId"])["state"] == "succeeded" and started_books == ["rut", "gen"]


def test_one_failing_book_does_not_stop_the_others():
    def run_book(book, cancel):
        if book["bookId"] == "gen":
            raise RuntimeError("broken book")
        return {"state": "succeeded"}

    manager = CollectionJobManager()
    snapshot = wait_done(manager, manager.start(
        CollectionJobSpec("/x/rut", books("rut", "gen", "exo"), ("languageQa",)),
        run_book=run_book, record_run=lambda e: None, book_hash=lambda b: "")["jobId"])
    assert snapshot["state"] == "failed" and [b["state"] for b in snapshot["books"]] == ["done", "failed", "done"]
    assert snapshot["books"][1]["error"] == "broken book"


# ---- through the real engine, over a three-book collection ---------------------

@pytest.fixture
def three_book_collection(tmp_path):
    rut, gen, exo = tmp_path / "rut", tmp_path / "gen", tmp_path / "exo"
    _write_minimal_book(rut, "rut", "அந்த காகம் பறந்தது.")
    _write_minimal_book(gen, "gen", "இந்த பெண் வந்தாள்.")
    _write_minimal_book(exo, "exo", "அவன் தேவன் பேசினார்.")
    collection = {"projects": [{"directoryName": d, "bookId": d, "bookName": d.upper()} for d in ("rut", "gen", "exo")]}
    for root in (rut, gen, exo):
        (root / ".bridge").mkdir(parents=True)
        (root / ".bridge" / "collection.json").write_text(json.dumps(collection), encoding="utf-8")
    return rut


def run_collection(engine, **params):
    started = call(engine, "collection.runChecks", params)
    assert started["success"], started
    deadline = time.monotonic() + job_timeout(60)
    while time.monotonic() < deadline:
        snapshot = call(engine, "collection.qaStatus", {"jobId": started["result"]["jobId"]})["result"]
        if snapshot["state"] in {"succeeded", "failed", "cancelled"}:
            return snapshot
        time.sleep(0.05)
    raise AssertionError("collection run did not finish")


def test_a_collection_run_checks_every_book_records_qa_runs_and_resumes(three_book_collection):
    engine = BridgeEngine()
    engine._language_qa = LanguageQaManager(debounce=0, yield_seconds=0)
    try:
        assert call(engine, "project.open", {"path": str(three_book_collection)})["success"]
        first = run_collection(engine, checks=["languageQa"])
        assert first["state"] == "succeeded", first
        assert [b["state"] for b in first["books"]] == ["done", "done", "done"]
        assert first["books"][0]["findingsByCategory"].get("languageQa", 0) >= 1
        runs = collection_qa_runs(three_book_collection)
        assert set(runs) == {"rut", "gen", "exo"} and all(r["contentHash"] for r in runs.values())
        # Each book's rollup now holds its Language QA findings, written by the
        # book's own job -- without the editor's project or Language QA changing.
        assert str(engine.project.path) == str(three_book_collection)
        stage = first["finalStage"]
        assert [c["bookId"] for c in stage["termbaseCoverage"]] == ["rut", "gen", "exo"]
        assert stage["houseStylePropagation"]["available"] is False
        # A second run skips every unchanged book; an edited one runs again.
        (three_book_collection.parent / "gen" / "gen" / "1.json").write_text(
            json.dumps({"1": "இந்தப் பெண் வந்தாள்."}, ensure_ascii=False), encoding="utf-8")
        second = run_collection(engine, checks=["languageQa"])
        assert [b["state"] for b in second["books"]] == ["skipped", "done", "skipped"]
        assert json.loads((three_book_collection / ".bridge" / "collection.json").read_text(
            encoding="utf-8"))["qaFinalStage"]["completedAt"]
    finally:
        engine._language_qa.unbind()


def test_checks_start_is_refused_while_a_collection_run_is_active(three_book_collection):
    engine = BridgeEngine()
    engine._language_qa = LanguageQaManager(debounce=0, yield_seconds=0)
    try:
        assert call(engine, "project.open", {"path": str(three_book_collection)})["success"]
        release = threading.Event()
        original = engine._run_collection_book
        engine._run_collection_book = lambda book, checks, cancel: release.wait(5) and original(book, checks, cancel)
        assert call(engine, "collection.runChecks", {"checks": ["languageQa"]})["success"]
        refused = call(engine, "checks.start", {"scope": "book", "checks": ["languageQa"]})
        assert not refused["success"] and refused["error"]["code"] == "job_conflict"
        call(engine, "collection.cancelChecks", {})
        release.set()
    finally:
        engine._language_qa.unbind()
