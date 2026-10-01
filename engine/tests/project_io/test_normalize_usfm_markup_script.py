"""scripts/normalize_usfm_markup.py (#203): dry run reports, --write repairs in
place with the file's encoding kept, and nothing but redundant style reopens
changes."""
from __future__ import annotations

import importlib.util

from tests.support.paths import SCRIPTS_DIR

SOURCE = (
    "\\id LUK\n\\c 4\n"
    "\\p\n\\v 27 \\wj And \\wj*\\wj there were many lepers\\wj*\\wj in Israel,\\wj*"
    " \\f + \\ft one\\f*\\f + \\ft two\\f*\n"
    "\\v 28 \\w who|strong=\"G3739\"\\w*\\w soever|strong=\"G1437\"\\w* believes.\n"
)
REPAIRED = SOURCE.replace("And \\wj*\\wj there", "And there").replace("lepers\\wj*\\wj in", "lepers in")


def _script():
    spec = importlib.util.spec_from_file_location("normalize_usfm_markup", SCRIPTS_DIR / "normalize_usfm_markup.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_dry_run_reports_and_changes_nothing(tmp_path, capsys):
    path = tmp_path / "43LUK.SFM"
    path.write_text(SOURCE, encoding="utf-8")
    assert _script().main([str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "2 redundant reopen(s), 1 glued to the previous word" in out
    assert "2 redundant reopen(s) found in 1 file(s); re-run with --write" in out
    assert path.read_text(encoding="utf-8") == SOURCE


def test_write_repairs_in_place_and_keeps_the_encoding(tmp_path):
    bom = tmp_path / "with-bom.usfm"
    bom.write_bytes(SOURCE.encode("utf-8-sig"))
    utf16 = tmp_path / "utf16.usfm"
    utf16.write_bytes(SOURCE.replace("\n", "\r\n").encode("utf-16"))
    no_bom = tmp_path / "no-bom.usfm"
    no_bom.write_bytes(SOURCE.encode("utf-8"))
    clean = tmp_path / "already-clean.usfm"
    clean.write_text(REPAIRED, encoding="utf-8")
    before = clean.stat().st_mtime_ns

    assert _script().main([str(bom), str(utf16), str(no_bom), str(clean), "--write"]) == 0

    assert bom.read_bytes().startswith(b"\xef\xbb\xbf")
    assert bom.read_bytes().decode("utf-8-sig") == REPAIRED
    # A file without a BOM must not gain one (the first run on the ESV did that).
    assert not no_bom.read_bytes().startswith(b"\xef\xbb\xbf")
    assert no_bom.read_bytes() == REPAIRED.encode("utf-8")
    assert utf16.read_bytes()[:2] in (b"\xff\xfe", b"\xfe\xff")
    assert utf16.read_bytes().decode("utf-16") == REPAIRED.replace("\n", "\r\n")
    assert clean.stat().st_mtime_ns == before  # untouched: nothing to repair
    # Notes and aligned words survived verbatim.
    assert "\\f*\\f +" in REPAIRED and "\\w*\\w soever" in REPAIRED
