"""Regression coverage for the Stage 9B.4 installed-acceptance helpers."""
from __future__ import annotations

from io import BytesIO, TextIOWrapper
from pathlib import Path
import sys


SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import inspect_correction_application as inspector  # noqa: E402
import seed_correction_acceptance as seeder  # noqa: E402


def test_acceptance_seeder_prints_unicode_on_a_legacy_windows_stream(
    monkeypatch,
) -> None:
    """The completed seed must not crash while printing its Tamil summary."""
    output = BytesIO()
    stream = TextIOWrapper(output, encoding="cp1252")
    monkeypatch.setattr(seeder.sys, "stdout", stream)

    seeder._configure_console_output()
    print("என் தேவனையே", file=seeder.sys.stdout)
    stream.flush()

    assert stream.encoding.lower() == "utf-8"
    assert output.getvalue().decode("utf-8").strip() == "என் தேவனையே"


def test_acceptance_inspector_reports_word_alignment_markers(tmp_path: Path) -> None:
    reference = "PHP 1:6"
    pending = inspector._word_alignment_state(tmp_path, reference)
    assert pending["wordAlignmentState"] == "PENDING"

    completed = tmp_path / inspector.WORD_ALIGNMENT / "completed" / "1" / "6.json"
    completed.parent.mkdir(parents=True)
    completed.write_text("{}", encoding="utf-8")
    assert inspector._word_alignment_state(
        tmp_path, reference,
    )["wordAlignmentState"] == "COMPLETED"

    invalid = tmp_path / inspector.WORD_ALIGNMENT / "invalid" / "1" / "6.json"
    invalid.parent.mkdir(parents=True)
    invalid.write_text("{}", encoding="utf-8")
    state = inspector._word_alignment_state(tmp_path, reference)
    assert state["wordAlignmentState"] == "INVALID"
    assert state["invalidMarkerPath"] == str(invalid)
