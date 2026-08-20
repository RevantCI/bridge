"""Standalone entrypoint for Bridge's vendored Greek Room USFM checker.

This is intentionally a separate executable from ``bridge-engine``.  The
long-lived engine owns the JSON-over-stdio protocol, while this short-lived
worker owns the third-party CLI and its report files.  Keeping the process
boundary prevents checker stdout, crashes, or global state from corrupting
the sidecar protocol.
"""
from __future__ import annotations

import runpy
import sys
import traceback
from pathlib import Path

CHECKER_VERSION = "vendored-18ddcf0"


def bundled_vendor_root() -> Path:
    """Return the vendored checker root in source and PyInstaller modes."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "greekroom-usfm"
    return Path(__file__).resolve().parent / "vendor" / "greekroom-usfm"


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args == ["--version"]:
        print(f"bridge-usfm-checker {CHECKER_VERSION}")
        return 0

    vendor_root = bundled_vendor_root()
    checker_script = vendor_root / "usfm_check.py"
    if not checker_script.is_file():
        print(f"USFM checker payload is missing: {checker_script}", file=sys.stderr)
        return 2

    # The upstream CLI uses bare imports (``ualign_utilities`` and
    # ``greekroom.gr_utilities``), so its pinned vendor root must be first.
    sys.path.insert(0, str(vendor_root))
    old_argv = sys.argv
    try:
        sys.argv = [str(checker_script), *args]
        runpy.run_path(str(checker_script), run_name="__main__")
        return 0
    except SystemExit as exc:
        if exc.code is None:
            return 0
        if isinstance(exc.code, int):
            return exc.code
        print(str(exc.code), file=sys.stderr)
        return 2
    except Exception:  # noqa: BLE001 - worker must return a useful exit code
        traceback.print_exc(file=sys.stderr)
        return 2
    finally:
        sys.argv = old_argv


if __name__ == "__main__":
    raise SystemExit(main())
