"""Packaged sidecar smoke test.

Build both executables first, then pass the frozen bridge-engine path.  The
test creates a temporary translationCore-shaped project whose source USFM has
balanced markers but duplicate/missing verses, so the legacy USFM_BALANCE
regex cannot make this test pass accidentally.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
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
        "1": "First verse.",
        "3": "Third verse.",
    })
    _write_json(project / ".apps" / "translationCore" / "alignmentData" / "tit" / "1.json", {
        "1": {"alignments": [], "wordBank": []},
        "3": {"alignments": [], "wordBank": []},
    })
    (project / "tit.usfm").write_text(
        "\\id TIT\n\\h Titus\n\\toc1 The Letter to Titus\n\\c 1\n\\p\n"
        "\\v 1 First verse.\n"
        "\\v 1 Duplicate verse number.\n"
        "\\v 3 Third verse, with verse two missing.\n",
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
        requests = [
            {"id": "open", "method": "project.open", "params": {"path": str(project)}},
            {"id": "structure", "method": "verse.runChecks", "params": {
                "chapter": "1", "verse": "1", "checks": ["usfm"],
            }},
        ]
        payload = "".join(json.dumps(request) + "\n" for request in requests)
        completed = subprocess.run(
            [str(engine)], input=payload, capture_output=True, text=True,
            encoding="utf-8", timeout=180, check=False,
        )
        if completed.returncode != 0:
            raise SystemExit(f"bridge-engine failed: {completed.stderr}")

        responses = {}
        for line in completed.stdout.splitlines():
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            responses[value.get("id")] = value

        for request_id in ("open", "structure"):
            response = responses.get(request_id)
            if not response or not response.get("success"):
                raise SystemExit(f"Request {request_id} failed: {response or completed.stderr}")

        check_types = {f["check_type"] for f in responses["structure"].get("findings", [])}
        if "usfm.duplicate_verse_number" not in check_types:
            raise SystemExit(f"Frozen checker missed duplicate verse: {sorted(check_types)}")
        if not any("missing_verses" in value for value in check_types):
            raise SystemExit(f"Frozen checker missed absent verse: {sorted(check_types)}")

    print("Frozen sidecar smoke test passed: real duplicate and missing-verse findings detected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
