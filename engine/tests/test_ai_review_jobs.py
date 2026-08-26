import threading
import time

from ai_review_jobs import AIReviewJobManager, AIReviewJobSpec


def _wait(manager, job_id, timeout=2):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        snapshot = manager.status(job_id)
        if snapshot["state"] in {"succeeded", "failed", "cancelled"}:
            return snapshot
        time.sleep(0.01)
    raise AssertionError("AI review manager did not reach a terminal state")


def _spec():
    return AIReviewJobSpec(
        scope="chapter", mode="basic", project_path="C:/project",
        chapters=("1",), chapter_verses={"1": ["1", "2"]},
    )


def test_cancel_waits_for_inflight_request_and_discards_automatic_result():
    manager = AIReviewJobManager()
    entered = threading.Event()
    release = threading.Event()

    def run_verse(chapter, verse, mode, progress, cancel_event):
        entered.set()
        assert release.wait(1)
        return {"summary": "finished remotely", "appliedSelections": [{"checkId": "unsafe"}]}

    started = manager.start(_spec(), run_verse=run_verse)
    assert entered.wait(1)
    cancelling = manager.cancel(started["jobId"])
    assert cancelling["state"] == "cancelling"
    release.set()
    terminal = _wait(manager, started["jobId"])

    assert terminal["state"] == "cancelled"
    assert terminal["results"] == {}
    assert terminal["latestResult"] is None


def test_failed_job_retains_compact_status_and_can_retry_from_same_spec():
    manager = AIReviewJobManager()

    def fail_first(chapter, verse, mode, progress, cancel_event):
        if verse == "1":
            raise RuntimeError("provider unavailable")
        return {"summary": "second verse", "checkReviews": [], "appliedSelections": []}

    started = manager.start(_spec(), run_verse=fail_first)
    failed = _wait(manager, started["jobId"])
    assert failed["state"] == "failed"
    assert failed["results"]["1:1"]["error"] == "provider unavailable"
    assert "checkReviews" not in failed["results"]["1:2"]
    assert failed["latestResult"]["result"]["checkReviews"] == []

    retry_spec = manager.spec_for_retry(started["jobId"])
    retried = manager.start(
        retry_spec,
        run_verse=lambda chapter, verse, mode, progress, cancel: {
            "summary": "ok", "checkReviews": [], "appliedSelections": [],
        },
    )
    succeeded = _wait(manager, retried["jobId"])
    assert succeeded["state"] == "succeeded"
    assert succeeded["completedVerses"] == 1
    assert succeeded["totalVerses"] == 1
    assert succeeded["skippedCurrentVerses"] == 1
    assert succeeded["resumeOf"] == started["jobId"]
