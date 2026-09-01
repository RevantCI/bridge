"""
Tests for issue #24: the project report's exception queue used to be built
entirely from AI-review data (see analytics.py's exception_first_queue) and
never read local Greek Room findings (Wildebeest/USFM/Names) at all, even
though the coverage bar above it already counted them correctly — two
different pictures of the same data. `_local_findings_by_verse` now merges
them in, filtered to still-open status via the same progress rollup the
coverage bar reads.

`_local_findings_by_verse` reads checkCache.json's wildebeest/usfm/names
sections directly, whatever is already there — it never triggers
computation itself. BridgeEngine originally also warmed a whole-book
Wildebeest cache synchronously inside build_project_report so a
never-opened verse would have real data; that was reverted the same day
(see build_project_report's docstring) after it blocked the
single-threaded stdio dispatcher long enough on a real ~800-verse book to
time out an unrelated project.open. These tests inject a finding directly
into checkCache.json the way a real whole-book Wildebeest pass would have
left one behind, without exercising a real Wildebeest engine dependency.
"""
import hashlib
import json
from pathlib import Path

import pytest

from bridge_service import BridgeEngine
from greek_room_engine.protocol import EngineRequest


def call(engine, method, params=None):
    return engine.handle_request(EngineRequest(id="t", method=method, params=params or {})).to_dict()


@pytest.fixture
def fixture_project(tmp_path):
    root = tmp_path / "rut"
    align_dir = root / ".apps" / "translationCore" / "alignmentData" / "rut"
    align_dir.mkdir(parents=True)
    (root / "rut").mkdir(parents=True)

    (root / "manifest.json").write_text(json.dumps({
        "project": {"id": "rut", "name": "Ruth"},
        "target_language": {"id": "tam", "name": "Tamil"},
        "tc_version": "8", "tc_edit_version": "3.7.0",
    }), encoding="utf-8")

    verse_text = "ஆதியிலே தேவன் வானத்தையும் பூமியையும் படைத்தார்."
    (align_dir / "1.json").write_text(json.dumps({"1": {"alignments": [], "wordBank": []}}), encoding="utf-8")
    (root / "rut" / "1.json").write_text(json.dumps({"1": verse_text}, ensure_ascii=False), encoding="utf-8")
    (root / "rut.usfm").write_text(
        f"\\id RUT\n\\c 1\n\\v 1 {verse_text}\n", encoding="utf-8",
    )
    return root, verse_text


def _wildebeest_content_hash(chapter: str, verse: str, text: str) -> str:
    text_map = {f"{chapter}:{verse}": text}
    return hashlib.sha256(
        "\n".join(f"{k}={v}" for k, v in sorted(text_map.items())).encode("utf-8")
    ).hexdigest()


def _inject_wildebeest_finding(project, chapter: str, verse: str, text: str, finding_id: str) -> None:
    content_hash = _wildebeest_content_hash(chapter, verse, text)
    finding = {
        "id": finding_id, "project_id": str(project.summary.path), "run_id": "", "project_hash": "",
        "book": project.book_id, "chapter": int(chapter), "verse": int(verse),
        "start_offset": 0, "end_offset": 3, "original_text": text[:3],
        "engine": "wildebeest", "check_type": "wildebeest.script.mixed",
        "category": "unicode", "severity": "high", "confidence": 0.9,
        "suggested_replacement": None, "explanation": "Token contains a Latin character mixed into non-Latin script text.",
        "evidence": [], "engine_version": "", "resource_versions": {},
        "status": "open", "human_comment": None, "created_at": "2026-08-31T00:00:00+00:00", "resolved_at": None,
    }
    project.save_check_cache_section("wildebeest", content_hash, [finding])


def test_project_report_surfaces_local_finding_never_ai_reviewed(fixture_project):
    """A verse nobody has opened in the editor (no AI review, cache
    'missing') must still show its real local finding in the exception
    queue, not a blank row — this was the exact bug in the JDG 1:2-1:21
    screenshot."""
    root, verse_text = fixture_project
    engine = BridgeEngine()
    call(engine, "project.open", {"path": str(root)})
    _inject_wildebeest_finding(engine.project, "1", "1", verse_text, "wb-test-1")

    result = call(engine, "project.report")
    assert result["success"] is True
    row = next(r for r in result["result"]["exceptionQueue"] if r["chapter"] == "1" and r["verse"] == "1")
    assert row["high"] == 1
    assert row["localFindings"] == [{
        "engine": "wildebeest", "severity": "high", "checkType": "wildebeest.script.mixed",
        "explanation": "Token contains a Latin character mixed into non-Latin script text.",
    }]
    assert "Token contains a Latin character" in row["summary"]


def test_project_report_does_not_touch_the_cached_finding_on_disk(fixture_project):
    """build_project_report must not recompute or overwrite an existing
    checkCache.json section — it only reads whatever local findings are
    already there (see module docstring for why eager computation was
    reverted)."""
    root, verse_text = fixture_project
    engine = BridgeEngine()
    call(engine, "project.open", {"path": str(root)})
    _inject_wildebeest_finding(engine.project, "1", "1", verse_text, "wb-test-2")
    before = engine.project.load_check_cache().get("wildebeest")

    call(engine, "project.report")

    after = engine.project.load_check_cache().get("wildebeest")
    assert after == before
    assert after["findings"][0]["id"] == "wb-test-2"


def test_accepted_local_finding_drops_out_of_the_row(fixture_project):
    """A human decision on a local finding must be respected by the
    exception queue the same way it already is by the coverage bar —
    accepting it should stop it counting toward localFindings/severity."""
    root, verse_text = fixture_project
    engine = BridgeEngine()
    call(engine, "project.open", {"path": str(root)})
    _inject_wildebeest_finding(engine.project, "1", "1", verse_text, "wb-test-3")

    decided = call(engine, "verse.decide", {
        "chapter": "1", "verse": "1", "findingId": "wb-test-3", "status": "accepted",
    })
    assert decided["success"] is True

    result = call(engine, "project.report")
    row = next(
        (r for r in result["result"]["exceptionQueue"] if r["chapter"] == "1" and r["verse"] == "1"),
        None,
    )
    # The verse may still appear (AI cache is 'missing' by default,
    # independent of this issue's change) but must carry no local finding.
    if row is not None:
        assert row["localFindings"] == []
        assert row["high"] == 0
