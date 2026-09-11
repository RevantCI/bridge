"""Repository paths for tests, independent of how deep a test module sits.

Test modules used to compute these with ``Path(__file__).parents[N]``; moving a file one
directory deeper silently broke every such site. Import from here instead.
"""
from __future__ import annotations

from pathlib import Path

TESTS_ROOT = Path(__file__).resolve().parents[1]  # engine/tests
ENGINE_ROOT = TESTS_ROOT.parent                    # engine
REPO_ROOT = ENGINE_ROOT.parent                     # repository root
SCRIPTS_DIR = REPO_ROOT / "scripts"
SCHEMAS_DIR = REPO_ROOT / "schemas"
FIXTURES_DIR = TESTS_ROOT / "fixtures"             # the Stage 5 / 6B goldens live here
