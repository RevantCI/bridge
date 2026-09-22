"""Reproducible read-only Language QA timing and source/frozen protocol smoke.

Creates only a throwaway project. No translator data or installed app is used.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import queue
import statistics
import subprocess
import sys
import tempfile
import threading
import time

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "engine"))

from tc_ai_bridge.language_qa import scan_text


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", type=Path, help="Frozen executable; default runs source")
    args = parser.parse_args()
    text = ("ஆதியிலே தேவன் வானத்தையும் பூமியையும் படைத்தார். " * 4).strip()
    timings = []
    for _ in range(1000):
        start = time.perf_counter()
        assert not scan_text(text, book="php", chapter="1", verse="1", tamil=True)["findings"]
        timings.append((time.perf_counter() - start) * 1000)
    measurements = {"pureScanMedianMs": statistics.median(timings),
                    "pureScanP95Ms": sorted(timings)[949], "pureScanMaxMs": max(timings)}
    with tempfile.TemporaryDirectory(prefix="bridge-language-qa-") as temp:
        root = Path(temp)
        project = root / "project"
        book_dir = project / "php"
        alignment_dir = project / ".apps" / "translationCore" / "alignmentData" / "php"
        book_dir.mkdir(parents=True)
        alignment_dir.mkdir(parents=True)
        (project / "manifest.json").write_text(json.dumps({
            "project": {"id": "php", "name": "Philippians"},
            "target_language": {"id": "tam", "name": "Tamil"}, "tc_version": "8",
        }), encoding="utf-8")
        # 400 synthetic verses, enough to keep the default yielding worker busy.
        for chapter in range(1, 5):
            verses = {str(v): text for v in range(1, 101)}
            if chapter == 1:
                verses["3-4"] = "தமிழ் �"
            (book_dir / f"{chapter}.json").write_text(json.dumps(verses, ensure_ascii=False), encoding="utf-8")
            (alignment_dir / f"{chapter}.json").write_text(json.dumps({
                verse: {"alignments": [], "wordBank": []} for verse in verses
            }), encoding="utf-8")
        original = {p: p.read_bytes() for p in book_dir.glob("*.json")}
        env = {**os.environ, "LOCALAPPDATA": str(root / "app-data"),
               "BRIDGE_SEMANTIC_SOURCE_DB": str(root / "absent.sqlite")}
        command = [str(args.engine.resolve())] if args.engine else [sys.executable, str(REPO / "engine" / "main.py")]
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True, encoding="utf-8", env=env)
        frames: queue.Queue[dict] = queue.Queue()
        def read_frames():
            for line in process.stdout:
                frames.put(json.loads(line))
        def drain_errors():
            for _ in process.stderr:
                pass
        threading.Thread(target=read_frames, daemon=True).start()
        threading.Thread(target=drain_errors, daemon=True).start()
        sequence = 0
        def request(method, params=None):
            nonlocal sequence
            sequence += 1
            request_id = str(sequence)
            process.stdin.write(json.dumps({"id": request_id, "method": method, "params": params or {}}) + "\n")
            process.stdin.flush()
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                frame = frames.get(timeout=max(.01, deadline - time.monotonic()))
                if frame.get("id") == request_id:
                    assert frame["success"], frame
                    return frame["result"]
            raise AssertionError(f"Timeout: {method}")
        try:
            request("project.open", {"path": str(project)})
            latencies = []
            started = time.monotonic()
            while time.monotonic() - started < 45:
                before = time.perf_counter()
                assert request("ping") == {"pong": True}
                latencies.append((time.perf_counter() - before) * 1000)
                status = request("languageQa.status", {"projectPath": str(project), "limit": 100})
                if status["state"] == "completed":
                    break
                assert status["state"] != "failed", status
                time.sleep(.1)
            assert status["state"] == "completed", status
            assert status["totalFindings"] == 1, status
            assert status["findings"][0]["verse"] == "3-4", status
            assert status["language"]["pack"] == "tamil", status
            assert all(p.read_bytes() == raw for p, raw in original.items())
            assert max(latencies) < 250, latencies
            measurements.update(mode="frozen" if args.engine else "source",
                                backgroundSeconds=status["elapsedSeconds"],
                                pingSamples=len(latencies), pingMedianMs=statistics.median(latencies),
                                pingMaxMs=max(latencies), checkedVerses=status["checkedVerses"])
            paused = request("languageQa.pause", {"projectPath": str(project), "paused": True})
            assert paused["state"] == "paused"
            request("verse.edit", {"chapter": "1", "verse": "3-4", "newText": "தமிழ் உரை"})
            assert request("languageQa.status", {"projectPath": str(project)})["state"] == "paused"
            request("languageQa.pause", {"projectPath": str(project), "paused": False})
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                status = request("languageQa.status", {"projectPath": str(project), "limit": 10})
                if status["state"] == "completed":
                    break
                time.sleep(.2)
            assert status["state"] == "completed" and status["totalFindings"] == 0, status
            measurements["editRecheckReusedChapters"] = status["reusedChapters"]
        finally:
            process.stdin.close()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
        print(json.dumps(measurements, indent=2))


if __name__ == "__main__":
    main()
