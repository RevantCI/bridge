"""Packaged sidecar smoke test.

Build both executables first, then pass the frozen bridge-engine path.  The
test creates a temporary translationCore-shaped project whose source USFM has
balanced markers but duplicate/missing verses, so the legacy USFM_BALANCE
regex cannot make this test pass accidentally.
"""
from __future__ import annotations

import argparse
import json
import queue
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def _fixture_project(root: Path) -> Path:
    project = root / "titus"
    _write_json(project / "manifest.json", {
        "project": {"id": "tit", "name": "Titus"},
        "target_language": {"id": "eng", "name": "English"},
        "tc_version": "8",
    })
    _write_json(project / "tit" / "1.json", {
        "1": "ପ୍ରଥମ ପଦ।",
        "3": "ତୃତୀୟ ପଦ।",
    })
    _write_json(project / ".apps" / "translationCore" / "alignmentData" / "tit" / "1.json", {
        "1": {"alignments": [], "wordBank": []},
        "3": {"alignments": [], "wordBank": []},
    })
    (project / "tit.usfm").write_text(
        "\\id TIT\n\\h Titus\n\\toc1 The Letter to Titus\n\\c 1\n\\p\n"
        "\\v 1 ପ୍ରଥମ ପଦ।\n"
        "\\v 1 ନକଲ ପଦ ସଂଖ୍ୟା।\n"
        "\\v 3 ତୃତୀୟ ପଦ; ଦ୍ୱିତୀୟ ପଦ ନାହିଁ।\n",
        encoding="utf-8",
    )
    return project


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("engine", type=Path, help="Path to frozen bridge-engine executable")
    args = parser.parse_args()
    engine = args.engine.resolve()
    extension = engine.suffix if sys.platform == "win32" else ""
    helper = engine.with_name(f"bridge-usfm-checker{extension}")
    if not engine.is_file() or not helper.is_file():
        raise SystemExit(f"Expected sibling executables: {engine} and {helper}")

    version = subprocess.run(
        [str(helper), "--version"], stdin=subprocess.DEVNULL,
        capture_output=True, text=True, encoding="utf-8", timeout=30, check=False,
    )
    if version.returncode != 0 or "vendored-18ddcf0" not in version.stdout:
        raise SystemExit(f"Helper health check failed: {version.stderr or version.stdout}")

    with tempfile.TemporaryDirectory(prefix="bridge-frozen-smoke-") as temp:
        project = _fixture_project(Path(temp))
        process = subprocess.Popen(
            [str(engine)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8",
        )
        frames: queue.Queue[dict] = queue.Queue()

        def read_stdout() -> None:
            assert process.stdout is not None
            for line in process.stdout:
                try:
                    frames.put(json.loads(line))
                except json.JSONDecodeError:
                    continue

        threading.Thread(target=read_stdout, daemon=True).start()

        def request(request_id: str, method: str, params: dict, timeout: float = 30) -> dict:
            assert process.stdin is not None
            process.stdin.write(json.dumps({"id": request_id, "method": method, "params": params}) + "\n")
            process.stdin.flush()
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                try:
                    response = frames.get(timeout=max(0.01, deadline - time.monotonic()))
                except queue.Empty:
                    break
                if response.get("id") == request_id:
                    return response
            raise SystemExit(f"Request {request_id} timed out")

        try:
            info = request("info", "engine.info", {})
            if not info.get("success"):
                raise SystemExit(f"Request info failed: {info}")
            wildebeest = (
                info.get("result", {})
                .get("greekRoom", {})
                .get("adapters", {})
                .get("wildebeest", {})
            )
            if not wildebeest.get("usingRealEngine"):
                raise SystemExit(
                    "Frozen engine is using the Wildebeest mock fallback: "
                    f"{wildebeest}"
                )

            opened = request("open", "project.open", {"path": str(project)})
            if not opened.get("success"):
                raise SystemExit(f"Request open failed: {opened}")

            started = request("start", "checks.start", {
                "scope": "chapter", "chapters": ["1"], "checks": ["usfm"],
            })
            if not started.get("success"):
                raise SystemExit(f"Request start failed: {started}")
            job_id = started["result"]["jobId"]

            snapshot = started["result"]
            deadline = time.monotonic() + 180
            attempt = 0
            while snapshot["state"] not in {"succeeded", "failed", "cancelled"}:
                if time.monotonic() >= deadline:
                    raise SystemExit(f"Frozen background job timed out: {snapshot}")
                time.sleep(0.1)
                attempt += 1
                status = request(f"status-{attempt}", "checks.status", {"jobId": job_id})
                if not status.get("success"):
                    raise SystemExit(f"Request status failed: {status}")
                snapshot = status["result"]

            if snapshot["state"] != "succeeded":
                raise SystemExit(f"Frozen background job failed: {snapshot}")
            check_types = {
                finding["check_type"]
                for result in snapshot["results"].values()
                for finding in result.get("findings", [])
            }
            if "usfm.duplicate_verse_number" not in check_types:
                raise SystemExit(f"Frozen checker missed duplicate verse: {sorted(check_types)}")
            if not any("missing_verses" in value for value in check_types):
                raise SystemExit(f"Frozen checker missed absent verse: {sorted(check_types)}")
        finally:
            process.terminate()
            try:
                process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate(timeout=5)

    print(
        "Frozen sidecar smoke test passed: real Wildebeest loaded and the "
        "background job returned duplicate and missing-verse findings."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
