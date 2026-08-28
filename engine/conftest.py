"""Global pytest isolation for Bridge's persistent application state."""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolate_bridge_app_data(tmp_path, monkeypatch):
    """Never let a default AppSettings()/BridgeEngine() touch real user data."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "app-data"))
    # semantic_mapping_bridge.default_semantic_source_db_path()'s dev-mode fallback
    # resolves relative to the checked-out source tree, so any test running from
    # source (not just Stage 3's own tests) would otherwise silently pick up the
    # real, full production semantic-source DB and exercise genuine Stage 3 review
    # policy -- not what most existing tests were written to cover. Point it at a
    # path that can never exist so prepare_semantic_mappings_for_review cleanly
    # reports "unavailable" (a real, supported state) by default. Stage 3's own
    # tests (test_semantic_mapping_stage3.py) construct SemanticSourceRepository/
    # SemanticMappingEngine directly with an explicit DB path and never go through
    # this resolver, so they are unaffected.
    monkeypatch.setenv("BRIDGE_SEMANTIC_SOURCE_DB", str(tmp_path / "no-semantic-source-db-in-tests.sqlite"))
