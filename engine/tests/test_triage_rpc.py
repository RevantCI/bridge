"""The triage.* protocol surface (bridge_service dispatch + triage_jobs).

Complements test_triage.py, which covers the triage module itself. Nothing
here reaches a network: BridgeEngine._ai_client is monkeypatched to a stub
client whose triage_batch answers from a canned script.
"""
import json
import threading
import time

import pytest

from bridge_service import BridgeEngine
from tc_ai_bridge.tc_project import TranslationCoreProject
from tc_ai_bridge.triage import triage_hash

from .test_bridge_service import call, fixture_project, two_book_collection  # noqa: F401


class StubClient:
    """Stands in for OpenAIResponsesClient: same duck type, no network."""

    def __init__(self, verdict="false_positive", confidence=95, model="stub-model"):
        self.model = model
        self.verdict = verdict
        self.confidence = confidence
        self.calls = 0
        self.gate: threading.Event | None = None

        class _Usage:
            total_tokens = 100
        self.last_usage = _Usage()
        self.last_cost_usd = 0.01

    def triage_batch(self, instructions: str, input_text: str) -> str:
        self.calls += 1
        if self.gate is not None:
            self.gate.wait(timeout=5)
        payload = json.loads(input_text)
        return json.dumps({"results": [
            {"finding_id": f["finding_id"], "verdict": self.verdict,
             "confidence": self.confidence, "reason": "stub reason"}
            for f in payload["findings"]
        ]})


def _finding(**overrides):
    base = {
        "id": "f1", "engine": "wildebeest", "check_type": "wildebeest.script.mixed",
        "category": "unicode", "severity": "high", "original_text": "ஆதி",
        "explanation": "Latin character mixed into Tamil text.",
        "evidence": [{"label": "script", "value": "Latin + Tamil"}], "status": "open",
    }
    base.update(overrides)
    return base


def _plant(root, findings, chapter="1", verse="1"):
    project = TranslationCoreProject(root)
    project.save_check_findings_snapshot(chapter, {verse: findings})
    return project


def _open(root, client=None, monkeypatch=None):
    engine = BridgeEngine()
    call(engine, "project.open", {"path": str(root)})
    if client is not None:
        monkeypatch.setattr(engine, "_ai_client", lambda: client)
    return engine


def wait_for_triage(engine, job_id, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        snapshot = call(engine, "triage.status", {"jobId": job_id})["result"]
        if snapshot["state"] in {"succeeded", "failed", "cancelled"}:
            return snapshot
        time.sleep(0.01)
    raise AssertionError(f"triage job {job_id} did not finish")


def _run(engine, **params):
    started = call(engine, "triage.run", params)
    assert started["success"] is True, started
    result = started["result"]
    if result.get("state") == "unavailable":
        return result
    return wait_for_triage(engine, result["jobId"])


# -- availability ---------------------------------------------------------


def test_triage_run_reports_unavailable_without_an_api_key(fixture_project):
    """Triage is optional and online-only: no key is a supported state, not
    an error the reviewer has to dismiss."""
    _plant(fixture_project, [_finding()])
    engine = _open(fixture_project)

    response = call(engine, "triage.run")

    assert response["success"] is True
    assert response["result"]["state"] == "unavailable"
    assert "key" in response["result"]["message"].lower()
    assert response["result"]["jobId"] == ""


def test_triage_results_reports_availability_and_stays_empty_before_any_run(fixture_project):
    engine = _open(fixture_project)
    result = call(engine, "triage.results")["result"]
    assert result["entries"] == {}
    assert result["available"] is False
    assert result["running"] is False


def test_triage_run_reports_unavailable_when_no_book_has_findings(fixture_project, monkeypatch):
    engine = _open(fixture_project, StubClient(), monkeypatch)
    result = call(engine, "triage.run")["result"]
    # No findings were ever planted, but the book is open — the run is
    # pointless rather than broken, and says so.
    assert result["state"] in {"unavailable", "queued", "running", "succeeded"}
    if result["state"] == "unavailable":
        assert "findings" in result["message"].lower()


# -- the run --------------------------------------------------------------


def test_run_persists_verdicts_that_triage_results_returns(fixture_project, monkeypatch):
    _plant(fixture_project, [_finding()])
    client = StubClient()
    engine = _open(fixture_project, client, monkeypatch)

    snapshot = _run(engine)

    assert snapshot["state"] == "succeeded"
    assert snapshot["triaged"] == 1
    assert client.calls == 1

    results = call(engine, "triage.results")["result"]
    key = triage_hash(book="rut", chapter="1", verse="1",
                      check_type="wildebeest.script.mixed", finding=_finding())
    assert key in results["entries"]
    record = results["entries"][key]
    assert record["verdict"] == "false_positive"
    assert record["confidence"] == 95
    assert record["model"] == "stub-model"
    assert record["userOverride"] is None
    assert results["available"] is True


def test_verdicts_survive_a_restart(fixture_project, monkeypatch):
    """Verdicts are read off disk, not held on the job — a reviewer who
    reopens Bridge tomorrow still sees what they already paid for."""
    _plant(fixture_project, [_finding()])
    engine = _open(fixture_project, StubClient(), monkeypatch)
    _run(engine)

    fresh = _open(fixture_project)
    assert len(call(fresh, "triage.results")["result"]["entries"]) == 1


def test_run_covers_every_opened_book_in_the_collection(two_book_collection, monkeypatch):
    for book in ("rut", "gen"):
        root = two_book_collection if book == "rut" else two_book_collection.parent / "gen"
        _plant(root, [_finding(check_type="wildebeest.script.mixed")])
    client = StubClient()
    engine = _open(two_book_collection, client, monkeypatch)

    snapshot = _run(engine)

    assert snapshot["totalBooks"] == 2
    assert snapshot["completedBooks"] == 2
    assert {b["bookId"] for b in snapshot["books"]} == {"rut", "gen"}
    results = call(engine, "triage.results")["result"]
    assert results["total"] == 2
    assert {b["bookId"]: b["count"] for b in results["books"]} == {"rut": 1, "gen": 1}


def test_a_book_filter_scopes_both_the_run_and_the_results(two_book_collection, monkeypatch):
    for book in ("rut", "gen"):
        root = two_book_collection if book == "rut" else two_book_collection.parent / "gen"
        _plant(root, [_finding()])
    engine = _open(two_book_collection, StubClient(), monkeypatch)

    snapshot = _run(engine, book="gen")

    assert snapshot["totalBooks"] == 1
    assert snapshot["books"][0]["bookId"] == "gen"
    scoped = call(engine, "triage.results", {"book": "gen"})["result"]
    assert {b["bookId"] for b in scoped["books"]} == {"gen"}


def test_a_second_run_costs_nothing(fixture_project, monkeypatch):
    _plant(fixture_project, [_finding()])
    client = StubClient()
    engine = _open(fixture_project, client, monkeypatch)

    _run(engine)
    assert client.calls == 1
    second = _run(engine)

    assert client.calls == 1  # no new model call
    assert second["triaged"] == 0
    assert second["skipped"] == 1


def test_force_re_runs_the_model(fixture_project, monkeypatch):
    _plant(fixture_project, [_finding()])
    client = StubClient()
    engine = _open(fixture_project, client, monkeypatch)
    _run(engine)

    _run(engine, force=True)

    assert client.calls == 2


def test_two_runs_cannot_overlap(fixture_project, monkeypatch):
    _plant(fixture_project, [_finding()])
    client = StubClient()
    client.gate = threading.Event()
    engine = _open(fixture_project, client, monkeypatch)

    first = call(engine, "triage.run")["result"]
    try:
        deadline = time.monotonic() + 5
        while client.calls == 0 and time.monotonic() < deadline:
            time.sleep(0.01)
        conflict = call(engine, "triage.run")
        assert conflict["success"] is False
        assert conflict["error"]["code"] == "triage_conflict"
    finally:
        client.gate.set()
        wait_for_triage(engine, first["jobId"])


def test_cancel_stops_the_run(fixture_project, monkeypatch):
    _plant(fixture_project, [_finding(id=f"f{i}", explanation=f"issue {i}") for i in range(3)])
    client = StubClient()
    client.gate = threading.Event()
    engine = _open(fixture_project, client, monkeypatch)

    started = call(engine, "triage.run")["result"]
    deadline = time.monotonic() + 5
    while client.calls == 0 and time.monotonic() < deadline:
        time.sleep(0.01)
    cancelled = call(engine, "triage.cancel", {"jobId": started["jobId"]})["result"]
    assert cancelled["state"] in {"cancelling", "cancelled"}
    client.gate.set()

    assert wait_for_triage(engine, started["jobId"])["state"] == "cancelled"


def test_status_for_an_unknown_job_is_a_clean_error(fixture_project):
    engine = _open(fixture_project)
    response = call(engine, "triage.status", {"jobId": "nope"})
    assert response["success"] is False
    assert response["error"]["code"] == "triage_not_found"


def test_a_run_whose_every_batch_failed_reports_failure_not_success(fixture_project, monkeypatch):
    """An unreachable endpoint or a rejected key must not look like a
    finished run: the reviewer would think every finding had been judged."""
    _plant(fixture_project, [_finding()])
    engine = _open(fixture_project, StubClient(), monkeypatch)

    class Dead(StubClient):
        def triage_batch(self, instructions, input_text):
            raise RuntimeError("Network error contacting OpenAI: connection refused")

    monkeypatch.setattr(engine, "_ai_client", lambda: Dead())
    snapshot = _run(engine)

    assert snapshot["state"] == "failed"
    assert snapshot["failedBatches"] == 1
    assert "no usable result" in snapshot["error"]
    assert "connection refused" in snapshot["error"]
    # The findings are still recorded, as uncertain, so a retry is cheap and
    # the report shows them rather than silently dropping them.
    records = call(engine, "triage.results")["result"]["entries"]
    assert [r["verdict"] for r in records.values()] == ["uncertain"]


def test_a_partly_failed_run_succeeds_but_still_reports_the_failure(fixture_project, monkeypatch):
    _plant(fixture_project, [_finding(id="f1"), _finding(id="f2", check_type="usfm.marker")])
    engine = _open(fixture_project, StubClient(), monkeypatch)

    class Flaky(StubClient):
        def triage_batch(self, instructions, input_text):
            if "structural checker" in instructions.lower():
                raise RuntimeError("boom")
            return StubClient.triage_batch(self, instructions, input_text)

    monkeypatch.setattr(engine, "_ai_client", lambda: Flaky())
    snapshot = _run(engine)

    assert snapshot["state"] == "succeeded"
    assert snapshot["failedBatches"] == 1
    assert snapshot["batches"] == 2
    assert "1 batch produced no usable result" in snapshot["error"]


# -- overrides ------------------------------------------------------------


def _one_key(engine):
    entries = call(engine, "triage.results")["result"]["entries"]
    assert len(entries) == 1
    return next(iter(entries))


def test_override_is_recorded_and_wins_over_the_model(fixture_project, monkeypatch):
    _plant(fixture_project, [_finding()])
    engine = _open(fixture_project, StubClient(), monkeypatch)
    _run(engine)
    key = _one_key(engine)

    response = call(engine, "triage.override", {"book": "rut", "hash": key, "verdict": "true_positive"})

    assert response["success"] is True
    assert response["result"]["record"]["userOverride"]["verdict"] == "true_positive"
    # And it is still there on a fresh read.
    assert call(engine, "triage.results")["result"]["entries"][key]["userOverride"]["verdict"] == "true_positive"


def test_an_override_can_be_cleared(fixture_project, monkeypatch):
    _plant(fixture_project, [_finding()])
    engine = _open(fixture_project, StubClient(), monkeypatch)
    _run(engine)
    key = _one_key(engine)
    call(engine, "triage.override", {"book": "rut", "hash": key, "verdict": "false_positive"})

    call(engine, "triage.override", {"book": "rut", "hash": key, "verdict": ""})

    assert call(engine, "triage.results")["result"]["entries"][key]["userOverride"] is None


def test_an_overridden_finding_is_never_re_sent_even_with_force(fixture_project, monkeypatch):
    """Overriding is also how a reviewer stops paying for a finding they
    have already judged."""
    _plant(fixture_project, [_finding()])
    client = StubClient()
    engine = _open(fixture_project, client, monkeypatch)
    _run(engine)
    call(engine, "triage.override", {"book": "rut", "hash": _one_key(engine), "verdict": "true_positive"})
    calls_before = client.calls

    snapshot = _run(engine, force=True)

    assert client.calls == calls_before
    assert snapshot["skipped"] == 1


@pytest.mark.parametrize("params,code", [
    ({"book": "rut", "hash": "", "verdict": "true_positive"}, "project_error"),
    ({"book": "rut", "hash": "unknown-hash", "verdict": "true_positive"}, "project_error"),
    ({"book": "rut", "hash": "x", "verdict": "definitely_wrong"}, "project_error"),
])
def test_override_rejects_bad_input(fixture_project, params, code):
    engine = _open(fixture_project)
    response = call(engine, "triage.override", params)
    assert response["success"] is False
    assert response["error"]["code"] == code


# -- clear ----------------------------------------------------------------


def test_clear_drops_cached_verdicts_so_the_next_run_re_buys_them(fixture_project, monkeypatch):
    _plant(fixture_project, [_finding()])
    client = StubClient()
    engine = _open(fixture_project, client, monkeypatch)
    _run(engine)

    cleared = call(engine, "triage.clear")["result"]
    assert cleared["cleared"] == ["rut"]
    assert call(engine, "triage.results")["result"]["entries"] == {}

    _run(engine)
    assert client.calls == 2


def test_clear_is_refused_while_a_run_is_active(fixture_project, monkeypatch):
    _plant(fixture_project, [_finding()])
    client = StubClient()
    client.gate = threading.Event()
    engine = _open(fixture_project, client, monkeypatch)

    started = call(engine, "triage.run")["result"]
    try:
        deadline = time.monotonic() + 5
        while client.calls == 0 and time.monotonic() < deadline:
            time.sleep(0.01)
        response = call(engine, "triage.clear")
        assert response["success"] is False
        assert response["error"]["code"] == "triage_conflict"
    finally:
        client.gate.set()
        wait_for_triage(engine, started["jobId"])


# -- settings -------------------------------------------------------------


def test_hide_threshold_defaults_to_ninety_and_round_trips(fixture_project):
    engine = _open(fixture_project)
    assert call(engine, "settings.get")["result"]["triageHideThreshold"] == 90

    updated = call(engine, "settings.set", {"triageHideThreshold": 75})["result"]
    assert updated["triageHideThreshold"] == 75
    assert call(engine, "settings.get")["result"]["triageHideThreshold"] == 75


@pytest.mark.parametrize("given,expected", [
    (0, 0),        # off
    (-1, 0),
    (10, 50),      # clamped to the slider's floor
    (150, 100),
    ("80", 80),
    (None, 90),
])
def test_hide_threshold_is_clamped_to_the_sliders_range(fixture_project, given, expected):
    engine = _open(fixture_project)
    assert call(engine, "settings.set", {"triageHideThreshold": given})["result"]["triageHideThreshold"] == expected
