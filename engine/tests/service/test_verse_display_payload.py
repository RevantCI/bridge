"""The `display` payload (#91 Phase 2a): every RPC that hands the frontend a
verse's text also hands it what the reader shows -- plain text, notes, style
spans and the removed raw ranges, in code points -- so the frontend never
parses USFM. Drives the RPCs, so it lives here."""
from __future__ import annotations

from bridge_service import BridgeEngine
from tests.support.projects import _write_minimal_book, call

PHP_1_6 = (
    "\\it இந்த\\it* நற்கிரியையை\\f + \\fr 1.6 \\fq நற்கிரியை \\ft தேவன் தொடங்கினார்.\\f* "
    "முடிப்பார் என்று \\nd கர்த்தர்\\nd* நம்புகிறேன்."
)


def _open(tmp_path, text):
    root = tmp_path / "php"
    _write_minimal_book(root, "php", text)
    engine = BridgeEngine()
    assert call(engine, "project.open", {"path": str(root)})["success"] is True
    return engine


def _check_display(display, raw):
    assert display["plain"] == "இந்த நற்கிரியையை முடிப்பார் என்று கர்த்தர் நம்புகிறேன்."
    [note] = display["notes"]
    assert note["kind"] == "footnote" and note["reference"] == "1.6"
    assert note["text"] == "நற்கிரியை தேவன் தொடங்கினார்."
    assert note["position"] == len("இந்த நற்கிரியையை")
    assert [s["marker"] for s in display["styles"]] == ["it", "nd"]
    it, nd = display["styles"]
    assert display["plain"][it["start"]:it["end"]] == "இந்த"
    assert display["plain"][nd["start"]:nd["end"]] == "கர்த்தர்"
    # Removed ranges cover exactly the markup: rebuilding plain from them works.
    kept = "".join(ch for i, ch in enumerate(raw) if not any(a <= i < b for a, b in display["removed"]))
    assert kept == display["plain"]
    assert display["warnings"] == []


def test_chapter_verse_data_carries_display_for_every_verse(tmp_path):
    engine = _open(tmp_path, PHP_1_6)
    result = call(engine, "chapter.verseData", {"chapter": "1"})["result"]
    row = result["verses"]["1"]
    assert row["text"] == PHP_1_6  # the raw string stays: the editor edits it
    _check_display(row["display"], PHP_1_6)


def test_verse_get_carries_the_same_display(tmp_path):
    engine = _open(tmp_path, PHP_1_6)
    result = call(engine, "verse.get", {"chapter": "1", "verse": "1"})["result"]
    _check_display(result["display"], PHP_1_6)


def test_verse_edit_returns_the_display_of_the_saved_text(tmp_path):
    engine = _open(tmp_path, "Old \\nd Lord\\nd* text.")
    new_text = "New \\f + \\ft note\\f* text with \\wj words\\wj*."
    result = call(engine, "verse.edit", {"chapter": "1", "verse": "1", "newText": new_text})
    assert result["success"] is True
    display = result["result"]["display"]
    assert display["plain"] == "New text with words."
    assert [n["text"] for n in display["notes"]] == ["note"]
    assert [s["marker"] for s in display["styles"]] == ["wj"]
    # And a later read agrees with what the edit returned.
    again = call(engine, "verse.get", {"chapter": "1", "verse": "1"})["result"]
    assert again["display"] == display


def test_a_verse_without_markup_has_an_identity_display(tmp_path):
    raw = "ஆதியிலே தேவன் வானத்தையும் பூமியையும் படைத்தார்."
    engine = _open(tmp_path, raw)
    display = call(engine, "verse.get", {"chapter": "1", "verse": "1"})["result"]["display"]
    assert display == {"plain": raw, "notes": [], "removed": [], "styles": [], "warnings": []}
