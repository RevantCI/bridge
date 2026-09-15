"""#77: non-secret settings are workspace rows; secrets stay in settings.json."""
from __future__ import annotations

import json

from tc_ai_bridge.secret_store import AppSettings
from tc_ai_bridge.workspace_repository import WorkspaceRepository


def test_settings_round_trip_through_the_workspace_database(tmp_path):
    settings = AppSettings(path=tmp_path / "settings.json")
    settings.model = "gpt-5.6-mini"
    settings.reviewer_mode = "advanced"
    settings.triage_hide_threshold = 75
    settings.set_setting("custom_flag", {"nested": [1, 2]})

    stored = WorkspaceRepository(tmp_path / "workspace.sqlite3").load_settings()
    assert stored["model"] == "gpt-5.6-mini"
    assert stored["custom_flag"] == {"nested": [1, 2]}

    reloaded = AppSettings(path=tmp_path / "settings.json")
    assert reloaded.model == "gpt-5.6-mini"
    assert reloaded.reviewer_mode == "advanced"
    assert reloaded.triage_hide_threshold == 75
    assert reloaded.get_setting("custom_flag") == {"nested": [1, 2]}


def test_settings_json_holds_only_dpapi_secrets(tmp_path, monkeypatch):
    monkeypatch.setattr("tc_ai_bridge.secret_store.dpapi_protect", lambda text: "wrapped:" + text)
    monkeypatch.setattr("tc_ai_bridge.secret_store.os.name", "nt")
    settings = AppSettings(path=tmp_path / "settings.json")
    settings.model = "gpt-5.6"
    settings.set_api_key("sk-secret")

    on_disk = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert on_disk == {"api_key_dpapi": "wrapped:sk-secret"}
    assert "model" not in on_disk
    assert "api_key_dpapi" not in WorkspaceRepository(tmp_path / "workspace.sqlite3").load_settings()


def test_a_pre_77_settings_file_is_adopted_once_and_rewritten_to_secrets_only(tmp_path):
    (tmp_path / "settings.json").write_text(json.dumps({
        "model": "gpt-legacy", "reviewer_mode": "advanced", "api_key_dpapi": "wrapped:legacy",
    }), encoding="utf-8")

    settings = AppSettings(path=tmp_path / "settings.json")
    assert settings.model == "gpt-legacy"
    assert settings.reviewer_mode == "advanced"

    on_disk = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert on_disk == {"api_key_dpapi": "wrapped:legacy"}
    stored = WorkspaceRepository(tmp_path / "workspace.sqlite3").load_settings()
    assert stored == {"model": "gpt-legacy", "reviewer_mode": "advanced"}

    # The database wins over a stale file value from then on.
    settings.model = "gpt-5.6"
    (tmp_path / "settings.json").write_text(json.dumps({"model": "gpt-older"}), encoding="utf-8")
    assert AppSettings(path=tmp_path / "settings.json").model == "gpt-5.6"


def test_the_engine_shares_one_workspace_between_settings_registry_and_projects(tmp_path):
    from bridge_service import BridgeEngine

    settings = AppSettings(path=tmp_path / "app" / "settings.json")
    engine = BridgeEngine(settings=settings)
    assert engine.workspace is settings.workspace
    assert engine.project_registry.workspace is settings.workspace
    assert engine.workspace.path == tmp_path / "app" / "workspace.sqlite3"
