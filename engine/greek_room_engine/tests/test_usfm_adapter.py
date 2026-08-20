"""
Tests for UsfmAdapter, which wraps the vendored Greek Room USFM checker
(engine/vendor/greekroom-usfm/, see NOTICE.md there) as a subprocess.

Split into two kinds of coverage:
  - _parse_report unit tests, against real captured report text (not
    synthetic guesses) — see docs/DEVELOPER_HANDOFF.md for how that text
    was obtained by actually running the checker against real broken USFM.
  - A real subprocess integration test, run against real broken USFM,
    confirming the whole pipeline (subprocess invocation, PYTHONPATH setup
    for the vendored ualign_utilities/general_util, report parsing) still
    works end to end. Skipped automatically if the vendored checker isn't
    present, though it's committed to the repo so this should never
    actually skip in a normal checkout.
"""
import subprocess

import pytest

from greek_room_engine.adapters.usfm_adapter import (
    UsfmAdapter,
    UsfmCheckerError,
    _checker_command,
    _parse_report,
)
from greek_room_engine.engine import GreekRoomEngine
from greek_room_engine.models.finding import Severity


# Captured verbatim from a real run of the vendored checker against a
# deliberately broken Titus sample (duplicate verse 1, missing verse 2,
# an unclosed \bd marker) — not hand-written, so it matches the tool's
# actual indentation/wording exactly.
REAL_REPORT_TEXT = """\
Tag statistics  (post-tag integers are counts)
    \\v       5  verse                           Surfs: \\v 5                   Children: \\bd 2

Report of 3 errors/warnings/alerts/infos:
    Severe errors (1)
        Verse info (1)
            Duplicate verse number (1)
                test_broken.usfm l.7 (TIT 1): Duplicate verse number 1
    Errors (2)
        Paired tags (1)
            Missing closing tag (1)
                Missing closing tag \\bd* (1)
                    TIT 2:2: \\v 2 An unclosed bold marker \\bd starts here but never closes.
        Verse info (1)
            Chapters with missing verses (1)
                test_broken.usfm (TIT 1): Missing verse: 2
"""


def test_parse_report_extracts_all_three_location_formats():
    issues = _parse_report(REAL_REPORT_TEXT)
    assert len(issues) == 3

    duplicate = next(i for i in issues if "Duplicate" in i["subcategory"])
    assert duplicate["book"] == "TIT"
    assert duplicate["chapter"] == "1"
    assert duplicate["verse"] == "1"  # extracted from the trailing "... number 1"
    assert duplicate["severity"] == Severity.HIGH

    unclosed = next(i for i in issues if "closing tag" in i["subcategory"].lower())
    assert unclosed["book"] == "TIT"
    assert unclosed["chapter"] == "2"
    assert unclosed["verse"] == "2"  # given directly as "TIT 2:2:"
    assert unclosed["severity"] == Severity.HIGH

    missing = next(i for i in issues if "missing verses" in i["subcategory"].lower())
    assert missing["book"] == "TIT"
    assert missing["chapter"] == "1"
    assert missing["verse"] == "2"  # extracted from "Missing verse: 2"
    assert missing["severity"] == Severity.HIGH


def test_parse_report_returns_nothing_for_clean_text():
    clean = """\
Tag statistics  (post-tag integers are counts)
    \\v       3  verse

Report of 0 errors/warnings/alerts/infos:
"""
    assert _parse_report(clean) == []


def _real_checker_available() -> bool:
    return UsfmAdapter().is_available()


@pytest.mark.skipif(not _real_checker_available(), reason="vendored usfm_check.py not present")
def test_real_subprocess_finds_issues_in_broken_usfm():
    usfm = (
        "\\id TIT\n\\h Titus\n\\toc1 The Letter to Titus\n\\c 1\n\\p\n"
        "\\v 1 Paul, a servant of God.\n"
        "\\v 1 Duplicate verse number here.\n"
        "\\v 3 Verse three, but verse two is missing.\n"
        "\\c 2\n"
        "\\v 1 But speak \\bd the things \\bd* that fit sound doctrine.\n"
        "\\v 2 An unclosed bold marker \\bd starts here but never closes.\n"
    )
    engine = GreekRoomEngine()
    findings = engine.check_book_usfm(project_id="p", book_id="tit", usfm_text=usfm)

    assert len(findings) >= 3
    assert all(f.engine == "usfm" for f in findings)
    assert all(f.book == "tit" for f in findings)
    assert any(f.check_type == "usfm.duplicate_verse_number" and f.chapter == 1 and f.verse == 1 for f in findings)
    assert any("closing_tag" in f.check_type and f.chapter == 2 and f.verse == 2 for f in findings)
    assert any("missing_verses" in f.check_type and f.chapter == 1 for f in findings)


@pytest.mark.skipif(not _real_checker_available(), reason="vendored usfm_check.py not present")
def test_real_subprocess_finds_nothing_in_clean_usfm():
    usfm = (
        "\\id TIT\n\\h Titus\n\\toc1 The Letter to Titus\n\\c 1\n\\p\n"
        "\\v 1 Paul, a servant of God.\n"
        "\\v 2 in hope of eternal life.\n"
    )
    engine = GreekRoomEngine()
    findings = engine.check_book_usfm(project_id="p", book_id="tit", usfm_text=usfm)
    assert findings == []


@pytest.mark.skipif(not _real_checker_available(), reason="vendored USFM checker dependencies not available")
def test_broken_subprocess_is_an_explicit_failure_not_a_clean_book(monkeypatch):
    from greek_room_engine.adapters import usfm_adapter

    def broken_run(*args, **kwargs):
        raise OSError("simulated subprocess failure")

    monkeypatch.setattr(usfm_adapter.subprocess, "run", broken_run)

    engine = GreekRoomEngine()
    with pytest.raises(UsfmCheckerError, match="could not start"):
        engine.check_book_usfm(project_id="p", book_id="tit", usfm_text="\\id TIT\n\\c 1\n\\v 1 Text.\n")


def test_success_without_report_is_an_explicit_failure(monkeypatch):
    from greek_room_engine.adapters import usfm_adapter

    monkeypatch.setattr(usfm_adapter, "_checker_command", lambda: ["fake-checker"])
    monkeypatch.setattr(
        usfm_adapter.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, "", "worker diagnostic"),
    )

    with pytest.raises(UsfmCheckerError, match="produced no report"):
        UsfmAdapter().check_book(project_id="p", book_id="tit", usfm_text="\\id TIT\n")


def test_nonzero_exit_is_an_explicit_failure(monkeypatch):
    from greek_room_engine.adapters import usfm_adapter

    monkeypatch.setattr(usfm_adapter, "_checker_command", lambda: ["fake-checker"])
    monkeypatch.setattr(
        usfm_adapter.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 7, "", "checker exploded"),
    )

    with pytest.raises(UsfmCheckerError, match="code 7.*checker exploded"):
        UsfmAdapter().check_book(project_id="p", book_id="tit", usfm_text="\\id TIT\n")


def test_frozen_mode_resolves_sibling_helper_not_bridge_engine(tmp_path, monkeypatch):
    from greek_room_engine.adapters import usfm_adapter

    engine = tmp_path / "bridge-engine.exe"
    helper = tmp_path / "bridge-usfm-checker.exe"
    engine.write_bytes(b"engine")
    helper.write_bytes(b"helper")
    monkeypatch.setattr(usfm_adapter.sys, "frozen", True, raising=False)
    monkeypatch.setattr(usfm_adapter.sys, "executable", str(engine))
    monkeypatch.delenv(usfm_adapter.CHECKER_OVERRIDE_ENV, raising=False)

    assert _checker_command() == [str(helper.resolve())]


def test_checker_override_is_explicit_path(tmp_path, monkeypatch):
    from greek_room_engine.adapters import usfm_adapter

    helper = tmp_path / "custom checker.exe"
    helper.write_bytes(b"helper")
    monkeypatch.setenv(usfm_adapter.CHECKER_OVERRIDE_ENV, str(helper))

    assert _checker_command() == [str(helper.resolve())]
