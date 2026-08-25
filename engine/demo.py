"""
Standalone demo: run this to see BridgeEngine work end-to-end without
needing a real translationCore project. Builds a tiny fixture project in a
temp directory, then exercises the main protocol methods.

Usage:
    cd engine
    python demo.py
"""
import json
import tempfile
from pathlib import Path

from bridge_service import BridgeEngine
from greek_room_engine.protocol import EngineRequest


def build_fixture_project(root: Path) -> Path:
    project = root / "rut"
    align_dir = project / ".apps" / "translationCore" / "alignmentData" / "rut"
    align_dir.mkdir(parents=True)
    (project / "rut").mkdir(parents=True)

    (project / "manifest.json").write_text(json.dumps({
        "project": {"id": "rut", "name": "Ruth"},
        "target_language": {"id": "tam", "name": "Tamil"},
        "tc_version": "8", "tc_edit_version": "3.7.0",
    }))

    (align_dir / "1.json").write_text(json.dumps({
        "1": {
            "alignments": [{
                "topWords": [{"word": "אֱלֹהִ֑ים", "strong": "H430", "occurrence": 1, "occurrences": 1}],
                "bottomWords": [{"word": "தேவன்", "occurrence": 1, "occurrences": 1}],
            }],
            "wordBank": [],
        }
    }, ensure_ascii=False))

    (project / "rut" / "1.json").write_text(json.dumps({
        "1": "ஆதியிலே தேவன் வானத்தையும் பூமியையும் படைத்தார்."
    }, ensure_ascii=False))

    return project


def call(engine, method, params=None):
    resp = engine.handle_request(EngineRequest(id="demo", method=method, params=params or {}))
    print(f"\n>>> {method}({params or {}})")
    print(json.dumps(resp.to_dict(), indent=2, ensure_ascii=False))
    return resp.to_dict()


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as tmp:
        project_path = build_fixture_project(Path(tmp))
        engine = BridgeEngine()

        call(engine, "ping")
        call(engine, "project.open", {"path": str(project_path)})
        call(engine, "chapter.verses", {"chapter": "1"})
        call(engine, "verse.get", {"chapter": "1", "verse": "1"})
        call(engine, "verse.runChecks", {"chapter": "1", "verse": "1", "checks": ["local", "greekroom"]})
        call(engine, "verse.decide", {
            "chapter": "1", "verse": "1", "findingId": "demo-finding",
            "status": "accepted", "comment": "demo run",
        })
        print("\nNote: settings.get below reads your REAL machine settings")
        print("(%LOCALAPPDATA%/Bridge/data/settings.json or")
        print("$OPENAI_API_KEY). hasApiKey may show true if either exists —")
        print("that's correct behavior, not a bug.")
        call(engine, "settings.get")

        print("\nDone. Everything above was a real call through BridgeEngine —")
        print("the same code path Tauri will use once the frontend is wired up.")
