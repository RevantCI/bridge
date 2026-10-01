"""USFM_REDUNDANT_MARKER (#203): a character style closed and reopened with
nothing between is flagged with a one-click fix, and applying that fix through
the ordinary verse.edit path clears it. Drives the RPCs, so it lives here."""
from __future__ import annotations

import json

from bridge_service import BridgeEngine
from tests.support.projects import _write_minimal_book, call

ESV_LUKE_4_27 = (
    "\\wj And \\wj*\\wj there were many lepers\\wj*\\wj in Israel in the time of the prophet Elisha, "
    "and none of them was cleansed, \\wj*\\wj but only Naaman the Syrian.”\\wj*"
)


def _open(tmp_path, text):
    root = tmp_path / "luk"
    _write_minimal_book(root, "luk", text, lang_id="eng", lang_name="English")
    engine = BridgeEngine()
    assert call(engine, "project.open", {"path": str(root)})["success"] is True
    return engine, root


def _redundant(result):
    return [f for f in result["findings"] if f["check_type"] == "USFM_REDUNDANT_MARKER"]


def test_each_redundant_reopen_is_a_finding_with_a_one_click_fix(tmp_path):
    engine, _ = _open(tmp_path, ESV_LUKE_4_27)
    result = call(engine, "verse.runChecks", {"chapter": "1", "verse": "1", "checks": ["local"]})
    findings = _redundant(result)
    assert len(findings) == 3
    for finding in findings:
        assert finding["original_text"] == "\\wj*\\wj "
        assert ESV_LUKE_4_27[finding["start_offset"]:finding["end_offset"]] == "\\wj*\\wj "
        assert finding["category"] == "structure"
    # The one glued to "lepers" keeps a space; the two after a space do not.
    assert sorted(f["suggested_replacement"] for f in findings) == ["", "", " "]
    glued = next(f for f in findings if f["suggested_replacement"] == " ")
    assert ESV_LUKE_4_27[glued["start_offset"] - 6:glued["start_offset"]] == "lepers"
    # Ids are stable across runs so a reviewer's decision survives a re-check.
    again = call(engine, "verse.runChecks", {"chapter": "1", "verse": "1", "checks": ["local"]})
    assert sorted(f["id"] for f in _redundant(again)) == sorted(f["id"] for f in findings)


def test_applying_the_fixes_through_verse_edit_clears_them(tmp_path):
    engine, root = _open(tmp_path, ESV_LUKE_4_27)
    text = ESV_LUKE_4_27
    # What applySuggestedFindingFix does on the frontend: splice at the raw
    # code-point span and save through verse.edit. Apply right-to-left so the
    # earlier offsets stay valid; the app re-runs checks after each save anyway.
    for finding in sorted(_redundant(
        call(engine, "verse.runChecks", {"chapter": "1", "verse": "1", "checks": ["local"]})
    ), key=lambda f: f["start_offset"], reverse=True):
        text = text[:finding["start_offset"]] + finding["suggested_replacement"] + text[finding["end_offset"]:]
        assert call(engine, "verse.edit", {"chapter": "1", "verse": "1", "newText": text})["success"] is True
    assert text == (
        "\\wj And there were many lepers in Israel in the time of the prophet Elisha, "
        "and none of them was cleansed, but only Naaman the Syrian.”\\wj*"
    )
    after = call(engine, "verse.runChecks", {"chapter": "1", "verse": "1", "checks": ["local"]})
    assert _redundant(after) == []
    assert not any(f["check_type"] == "USFM_BALANCE" for f in after["findings"])
    stored = json.loads((root / "luk" / "1.json").read_text(encoding="utf-8"))["1"]
    assert stored == text


def test_back_to_back_notes_are_not_flagged(tmp_path):
    engine, _ = _open(tmp_path, "Word\\f + \\ft one\\f*\\f + \\ft two\\f* more.")
    result = call(engine, "verse.runChecks", {"chapter": "1", "verse": "1", "checks": ["local"]})
    assert _redundant(result) == []
