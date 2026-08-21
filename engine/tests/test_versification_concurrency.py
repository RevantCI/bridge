"""
Concurrency regression tests for tc_ai_bridge.versification.

Two real, independently-found bugs are guarded here, both only visible under
actual concurrent load — bridge-engine is a single long-lived sidecar
process that can field several protocol calls close together (e.g. the
frontend firing project.open immediately followed by a checks.start job),
so "only one caller at a time" is not a safe assumption to make silently.

1. Correctness: the vendored Versification.load_versifications() keeps
   CLASS-level state and crashes with AttributeError on a second real call
   in the same process (see engine/vendor/greekroom-versification/
   NOTICE.md). Fixed with a lock-guarded, load-once-per-process singleton
   (_ensure_loaded()) — but a lock only helps if every caller actually goes
   through it, including several threads racing the very first call.

2. Performance: detect_schema()'s VersificationMatch scan degrades
   CATASTROPHICALLY, not just proportionally, when run on several threads
   at once — measured directly (not assumed from general GIL folklore): a
   single-threaded scan of one schema takes ~0.5s; the same scan run on 16
   threads simultaneously took ~47s PER THREAD, not the ~8s naive linear
   scaling would predict. Fixed by serializing the scan with the same lock
   _ensure_loaded() uses. Without this, a burst of near-simultaneous
   versification.detect calls (e.g. quickly switching between several
   just-opened book tabs before each book's cache is warm) would look
   exactly like the sidecar hanging.

Both worker scripts run in a genuinely fresh subprocess (not
importlib.reload() inside the pytest process) so the vendored module's own
class-level state starts completely cold, the same as a real
bridge-engine.exe launch — reusing an already-imported copy in-process
would just re-trigger the OLD known bug via test-harness state pollution
rather than testing a real cold start.
"""
from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parent.parent

_MIXED_WORKLOAD_SCRIPT = textwrap.dedent("""
    import json
    import sys
    import threading

    from tc_ai_bridge import versification as vt

    N_THREADS = 16
    results = [None] * N_THREADS
    errors = [None] * N_THREADS
    start_gate = threading.Barrier(N_THREADS)

    # Deliberately not all identical calls: a real process fields different
    # protocol methods concurrently, not N copies of the same one.
    def call(i):
        try:
            start_gate.wait(timeout=10)  # maximize actual overlap
            if i % 3 == 0:
                results[i] = vt.detect_schema("PSA", {"3:1": "x", "3:2": "y"})
            elif i % 3 == 1:
                results[i] = vt.to_org_ref("PSA", "3", "1", "eng")
            else:
                results[i] = vt.back_versification_map("PSA", "eng")
        except BaseException as exc:  # noqa: BLE001 - report, don't hide
            errors[i] = f"{type(exc).__name__}: {exc}"

    threads = [threading.Thread(target=call, args=(i,)) for i in range(N_THREADS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)

    print(json.dumps({
        "errors": [e for e in errors if e],
        "org_ref_results": [results[i] for i in range(N_THREADS) if i % 3 == 1],
        "back_map_results": [results[i] for i in range(N_THREADS) if i % 3 == 2],
    }))
""")


def test_concurrent_first_load_from_multiple_threads_does_not_crash():
    completed = subprocess.run(
        [sys.executable, "-c", _MIXED_WORKLOAD_SCRIPT],
        cwd=str(ENGINE_ROOT), capture_output=True, text=True, timeout=90,
    )
    assert completed.returncode == 0, (
        f"worker subprocess crashed:\nstdout={completed.stdout}\nstderr={completed.stderr}"
    )
    payload = json.loads(completed.stdout.strip().splitlines()[-1])

    assert payload["errors"] == [], f"threads raised during concurrent first load: {payload['errors']}"

    # Every thread that ran to_org_ref concurrently must have gotten the
    # SAME correct real-world answer (the Psalm 3 descriptive-title shift),
    # not a half-initialized or torn result from racing the load.
    assert payload["org_ref_results"], "no orgRef results collected"
    for result in payload["org_ref_results"]:
        assert result["orgRef"] == "PSA 3:2"
        assert result["mapping"] == "mapped"

    assert payload["back_map_results"], "no backVersificationMap results collected"
    for back_map in payload["back_map_results"]:
        assert back_map["PSA 3:2"] == "PSA 3:1"


_DETECT_SCHEMA_TIMING_SCRIPT = textwrap.dedent("""
    import json
    import threading
    import time

    from tc_ai_bridge import versification as vt

    N_THREADS = 8
    durations = [None] * N_THREADS
    start_gate = threading.Barrier(N_THREADS)

    def call(i):
        start_gate.wait(timeout=10)
        t0 = time.monotonic()
        vt.detect_schema("PSA", {f"3:{n}": f"text {n}" for n in range(1, 10)})
        durations[i] = time.monotonic() - t0

    threads = [threading.Thread(target=call, args=(i,)) for i in range(N_THREADS)]
    t_start = time.monotonic()
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    total_wall_time = time.monotonic() - t_start

    print(json.dumps({"durations": durations, "total_wall_time": total_wall_time}))
""")


def test_concurrent_detect_schema_stays_fast_not_catastrophically_slow():
    """Regression test for the specific GIL-contention bug: before the fix
    (serializing VersificationMatch's scan with _lock), 16 concurrent
    detect_schema-style scans took ~47s EACH (not ~8s as naive linear
    scaling over a single-threaded ~0.5s baseline would predict) — a >90x
    blowup from real GIL thrashing under many simultaneous pure-Python
    scans over large verse_id_list data. With the fix, 8 concurrent
    detect_schema calls (each scanning up to 6 schemas) complete with total
    wall time in the same ballpark as running them one after another, not
    an order of magnitude worse. The bound below (30s) has generous margin
    over the observed ~8-18s fixed behavior while still failing fast if the
    catastrophic-slowdown regression ever comes back — the unfixed version
    would blow through it by 5-10x.
    """
    completed = subprocess.run(
        [sys.executable, "-c", _DETECT_SCHEMA_TIMING_SCRIPT],
        cwd=str(ENGINE_ROOT), capture_output=True, text=True, timeout=90,
    )
    assert completed.returncode == 0, (
        f"worker subprocess crashed:\nstdout={completed.stdout}\nstderr={completed.stderr}"
    )
    payload = json.loads(completed.stdout.strip().splitlines()[-1])

    assert all(d is not None for d in payload["durations"]), (
        f"not every thread finished within its own join timeout: {payload['durations']}"
    )
    assert payload["total_wall_time"] < 30.0, (
        f"detect_schema under concurrency took {payload['total_wall_time']:.1f}s total — "
        f"this is the exact shape of the catastrophic GIL-contention regression "
        f"this test guards against (per-thread durations: {payload['durations']})"
    )
