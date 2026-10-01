"""Characterisation snapshot of the Stage 4 passage index (#91 Phase 3a).

Phases 3b/3c move `UsfmPassageIndex.from_text` and `build_current_text_overlay`
from their line regexes onto `usfm_parser`. Window boundaries feed Stage 6B's
structural scopes and the passage fingerprint, so a changed boundary would move
the Stage 6B golden. This file records what the *current* code produces --
windows, segment texts, structure markers, mismatches -- over both IRV fixtures
and three fixture-project shapes the runtime tests use, and asserts the same
after the swap. If it moves, that is a finding to report, not a file to rewrite.

The snapshot is NOT a golden: it lives beside the goldens but without `golden`
in its name, it is deleted in Phase 4, and regenerating it is a deliberate act:

    BRIDGE_WRITE_PASSAGE_SNAPSHOT=1 pytest tests/semantic/test_passage_windows_snapshot.py
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from tc_ai_bridge.passage_semantic_runtime import build_current_text_overlay
from tc_ai_bridge.tc_project import TranslationCoreProject
from tc_ai_bridge.usfm_passages import UsfmPassageIndex
from tests.support.paths import FIXTURES_DIR
from tests.support.semantic import TAMIL, semantic_runtime

SNAPSHOT = FIXTURES_DIR / "passage-windows-snapshot-v1.json"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _index_record(index: UsfmPassageIndex) -> dict:
    return {
        "book": index.book,
        "segments": [{"ref": s.reference, "text": _sha(s.text), "ordinal": s.ordinal} for s in index.segments],
        "windows": [{"id": w.id, "refs": w.references, "fingerprint": w.fingerprint[:16]} for w in index.windows],
    }


def _overlay_record(project_root: Path) -> dict:
    overlay = build_current_text_overlay(TranslationCoreProject(project_root))
    record = _index_record(overlay.index)
    record["structure"] = [
        {"kind": str(m.kind), "marker": m.marker, "ref": m.displayed_reference, "order": m.source_order}
        for m in overlay.structure_markers
    ]
    record["mismatches"] = list(overlay.mismatches)
    return record


def _project_dir(tmp_path: Path, name: str, chapters: dict[str, dict[str, str]], usfm: str) -> Path:
    root = tmp_path / name
    (root / "php").mkdir(parents=True)
    alignment = root / ".apps" / "translationCore" / "alignmentData" / "php"
    alignment.mkdir(parents=True)
    (root / "manifest.json").write_text(json.dumps({
        "project": {"id": "php", "name": "PHP"}, "target_language": {"id": "ta"},
        "resource": {"id": "test"}, "tc_version": "8",
    }), encoding="utf-8")
    for chapter, verses in chapters.items():
        (root / "php" / f"{chapter}.json").write_text(json.dumps(verses, ensure_ascii=False), encoding="utf-8")
        (alignment / f"{chapter}.json").write_text(
            json.dumps({v: {"alignments": [], "wordBank": []} for v in verses}), encoding="utf-8",
        )
    (root / "php.usfm").write_text(usfm, encoding="utf-8")
    return root


def _current(tmp_path: Path, tamil_php_usfm: Path, tamil_luk_usfm: Path) -> dict:
    # The three project shapes the runtime tests exercise, built here rather
    # than imported from those test modules (tests never import tests).
    shared = semantic_runtime(tmp_path, project_prefix="snapshot").project.path
    stage6a = _project_dir(tmp_path, "stage6a-shape", {"1": TAMIL}, (
        "\\id PHP\n\\s OLD NON SCRIPTURE HEADING\n\\p\n\\q1\n\\c 1\n"
        + "".join(f"\\v {v} OLD IMPORTED WORDING\n" for v in TAMIL)
    ))
    marker_bearing = _project_dir(tmp_path, "marker-bearing", {"1": {
        "1": "पहला वचन,\n\\p",
        "2": "दूसरा वचन।\n\\s अनुभाग शीर्षक\n\\p",
        "3": "तीसरा वचन।",
    }}, "\\id PHP\n\\c 1\n\\p\n\\v 1 पुराना आयातित पाठ।\n\\v 2 पुराना आयातित पाठ।\n\\v 3 पुराना आयातित पाठ।\n")
    return {
        "irv-php": _index_record(UsfmPassageIndex.from_path(tamil_php_usfm)),
        "irv-luk": _index_record(UsfmPassageIndex.from_path(tamil_luk_usfm)),
        "overlay-shared-fixture": _overlay_record(shared),
        "overlay-stage6a-shape": _overlay_record(stage6a),
        "overlay-marker-bearing": _overlay_record(marker_bearing),
    }


def test_passage_windows_match_the_snapshot(tmp_path, tamil_php_usfm, tamil_luk_usfm):
    current = _current(tmp_path, tamil_php_usfm, tamil_luk_usfm)
    if os.environ.get("BRIDGE_WRITE_PASSAGE_SNAPSHOT") == "1":
        SNAPSHOT.write_text(json.dumps(current, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        pytest.skip(f"snapshot written to {SNAPSHOT}")
    assert SNAPSHOT.is_file(), "run once with BRIDGE_WRITE_PASSAGE_SNAPSHOT=1 to record the current behaviour"
    recorded = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    for name, expected in recorded.items():
        actual = current[name]
        assert actual["windows"] == expected["windows"], f"{name}: window boundaries moved"
        assert actual["segments"] == expected["segments"], f"{name}: segment texts moved"
        if "structure" in expected:
            assert actual["structure"] == expected["structure"], f"{name}: structure markers moved"
            assert actual["mismatches"] == expected["mismatches"], f"{name}: mismatches moved"
    assert set(current) == set(recorded)
