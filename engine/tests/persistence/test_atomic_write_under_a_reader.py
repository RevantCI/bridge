"""A Scripture write must survive a concurrent reader holding the file.

On Windows `os.replace` fails with `PermissionError` (WinError 5 / 32) if any
handle holds the destination open -- Python's `open()` does not request
FILE_SHARE_DELETE. Language QA's background pass reads every chapter of the book,
so a `verse.edit` landing inside that window was refused outright:

    [WinError 5] Access is denied: ...\\rut\\rut\\1.json

seen in CI on `test_job_path_and_live_path_produce_identical_findings` (#184).
The reader holds the file for only a few milliseconds; that is still enough.

These tests are meaningful on Windows and near-trivial elsewhere, where a replace
under an open handle simply succeeds. They are not skipped on POSIX: the retry
must be a no-op there, and asserting that is worth the second it costs.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from tc_ai_bridge.tc_project import _write_json_atomic


def test_a_write_waits_for_a_reader_to_let_go(tmp_path: Path) -> None:
    target = tmp_path / "1.json"
    _write_json_atomic(target, {"1": "before"})

    holding = threading.Event()
    release = threading.Event()

    def reader() -> None:
        with target.open("rb") as stream:
            stream.read()
            holding.set()
            release.wait(5)

    thread = threading.Thread(target=reader)
    thread.start()
    assert holding.wait(5), "reader never opened the file"

    # Let go shortly after the write starts, so the write has to retry at least
    # once on Windows rather than winning the race by luck.
    threading.Timer(0.2, release.set).start()
    _write_json_atomic(target, {"1": "after"})
    thread.join(5)

    assert json.loads(target.read_text(encoding="utf-8-sig")) == {"1": "after"}


def test_a_reader_that_never_lets_go_still_fails_loudly(tmp_path: Path) -> None:
    """The retry must not turn a real permission problem into a silent hang or a
    swallowed error. After the budget the original error is raised."""
    if not hasattr(__import__("os"), "startfile"):  # not Windows
        pytest.skip("replace under an open handle only fails on Windows")

    target = tmp_path / "1.json"
    _write_json_atomic(target, {"1": "before"})

    with target.open("rb") as stream:
        stream.read()
        started = time.monotonic()
        with pytest.raises(PermissionError):
            _write_json_atomic(target, {"1": "after"})
        elapsed = time.monotonic() - started

    # It gave the reader a chance, and it gave up rather than retrying forever.
    assert 1.0 < elapsed < 10.0, elapsed
    # The original content survived a refused write.
    assert json.loads(target.read_text(encoding="utf-8-sig")) == {"1": "before"}
