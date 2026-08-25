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
   at once. Fixed by serializing the scan with the same lock _ensure_loaded()
   uses. The regression test instruments that expensive boundary and proves
   only one thread can enter it at a time. This is deterministic across fast
   and slow machines, unlike the old absolute wall-clock bound.

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


_DETECT_SCHEMA_SERIALIZATION_SCRIPT = textwrap.dedent("""
    import json
    import threading
    import time

    from tc_ai_bridge import versification as vt

    # Load the genuine module and schema data first, then replace only the
    # expensive matcher boundary with an instrumented stand-in. We are
    # testing Bridge's lock here, not vendored matching correctness (covered
    # by test_versification.py). A short sleep makes an absent lock overlap
    # reliably without turning machine speed into a test result.
    vt._ensure_loaded()
    state_lock = threading.Lock()
    active = 0
    max_active = 0
    match_calls = 0

    class InstrumentedMatch:
        def __init__(self, corpus, versification, bible):
            global active, max_active, match_calls
            with state_lock:
                active += 1
                max_active = max(max_active, active)
                match_calls += 1
            try:
                time.sleep(0.02)
                self.cost = 0
            finally:
                with state_lock:
                    active -= 1

    vt._module.VersificationMatch = InstrumentedMatch

    N_THREADS = 8
    errors = [None] * N_THREADS
    start_gate = threading.Barrier(N_THREADS)

    def call(i):
        try:
            start_gate.wait(timeout=10)
            vt.detect_schema("PSA", {f"3:{n}": f"text {n}" for n in range(1, 10)})
        except BaseException as exc:  # noqa: BLE001 - report, don't hide
            errors[i] = f"{type(exc).__name__}: {exc}"

    threads = [threading.Thread(target=call, args=(i,)) for i in range(N_THREADS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    print(json.dumps({
        "errors": [error for error in errors if error],
        "threads_alive": sum(thread.is_alive() for thread in threads),
        "max_active": max_active,
        "match_calls": match_calls,
        "expected_match_calls": N_THREADS * len(vt.SCHEMAS),
    }))
""")


def test_concurrent_detect_schema_serializes_expensive_scan():
    """Guard the exact fix for the GIL-contention regression.

    An absolute time limit made the previous test depend on CPU speed and
    background load: a healthy serialized scan takes ~52 seconds for eight
    callers on the current machine because one call itself takes ~6.2
    seconds. Instrumenting VersificationMatch proves the required invariant
    directly — concurrent callers may queue, but their expensive scans must
    never overlap.
    """
    completed = subprocess.run(
        [sys.executable, "-c", _DETECT_SCHEMA_SERIALIZATION_SCRIPT],
        cwd=str(ENGINE_ROOT), capture_output=True, text=True, timeout=30,
    )
    assert completed.returncode == 0, (
        f"worker subprocess crashed:\nstdout={completed.stdout}\nstderr={completed.stderr}"
    )
    payload = json.loads(completed.stdout.strip().splitlines()[-1])

    assert payload["errors"] == [], f"concurrent callers raised: {payload['errors']}"
    assert payload["threads_alive"] == 0, "not every detect_schema caller completed"
    assert payload["match_calls"] == payload["expected_match_calls"]
    assert payload["max_active"] == 1, (
        "VersificationMatch scans overlapped across threads; this restores the "
        f"catastrophic GIL-contention regression (max active: {payload['max_active']})"
    )
