"""Wall-clock budgets for tests that poll a background job to a terminal state.

Every such test has the same shape: start a job on a worker thread, then poll a
status method until it reports a terminal state, failing if the budget runs out.
Those budgets were written as small literals (1-10 s) chosen against a fast, idle,
serial developer machine -- which is the one condition neither CI nor a parallel
local run actually meets:

* under ``pytest -n auto`` the job thread competes with one worker process per
  core, so a job that finishes in milliseconds in isolation can be starved well
  past 10 s -- reproduced twice locally on different tests (#85);
* on a GitHub ``windows-latest`` runner the same 10 s budget expired *serially*
  (#85 again: CI run 34806216124, ``test_ai_explain.py``), so scaling by worker
  count alone is not enough -- the floor has to be generous in absolute terms.

Raising these budgets is close to free. Every one of these loops returns as soon
as the state is terminal, so a larger number is only ever *spent* on a run that
was going to fail anyway; all it buys is a slower report of a genuine hang, which
is the right trade for a gate that has to be trusted on every push to main.

Deliberately not covered here: waits that assert something stays *unfinished*,
and the ``threading.Event`` gates concurrency tests use to hold a lock open.
Those are testing the timeout itself, not tolerating it -- scaling them would
change what they assert.
"""
from __future__ import annotations

import os

#: pytest-xdist sets this in every worker process; it is absent on a serial run.
_WORKER_COUNT_ENV = "PYTEST_XDIST_WORKER_COUNT"

#: No background-job wait gets less than this, whatever base it asks for. Sized
#: against the observed *serial* CI failure at 10 s, not against a local run.
FLOOR_SECONDS = 60.0


def worker_count() -> int:
    """Number of xdist workers in this run; 1 when running serially."""
    try:
        return max(int(os.environ.get(_WORKER_COUNT_ENV, "1")), 1)
    except ValueError:  # malformed env var -- assume serial rather than crash
        return 1


def job_timeout(base: float) -> float:
    """Scale a background-job wait budget for the environment it runs in.

    ``base`` is the budget the test would need on an idle serial machine; the
    result is that budget multiplied by the worker count, never below
    :data:`FLOOR_SECONDS`.
    """
    return max(float(base) * worker_count(), FLOOR_SECONDS)
