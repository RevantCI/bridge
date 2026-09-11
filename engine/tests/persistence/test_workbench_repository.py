"""#75: the workbench SQLite repository skeleton.

Covers exactly the issue's test list: schema creation, the change_log
triggers rejecting delete/update, a revision conflict on the generic write
path, one change_log row per write across every mutable table, and a
static guard that nothing in the module updates change_log except
`synced_at`.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import sqlite3

import pytest

from tc_ai_bridge.workbench_repository import (
    MUTABLE_TABLES,
    WorkbenchConflict,
    WorkbenchRepository,
    WorkbenchValidationError,
)
from tc_ai_bridge.workspace_repository import WorkspaceRepository

# Extra columns each table requires beyond the nine common ones, per
# TEAM_ARCHITECTURE.md ss3.1/3.2 -- only the NOT NULL ones need a value here.
_REQUIRED_EXTRA_COLUMNS = {
    "human_decisions": {"kind": "qa", "key": "k1"},
    "ai_review_results": {"chapter": "1", "verse": "1", "input_fingerprint": "fp", "generated_at": "now"},
    "semantic_mappings": {"fingerprint": "fp"},
    "semantic_validation_runs": {"suite_id": "s1"},
    "project_state": {"key": "k1"},
    "progress_chapters": {"chapter": "1"},
    "check_findings": {"chapter": "1"},
}


def _write(repo, table, row_id, *, project_id="proj-1", book_id="rut",
           payload=None, actor_id="human", device_id="dev-1",
           expected_revision=None, **kwargs):
    extra = dict(_REQUIRED_EXTRA_COLUMNS.get(table, {}))
    extra.update(kwargs.pop("extra_columns", {}) or {})
    return repo._write(
        table, row_id, project_id=project_id, book_id=book_id,
        payload=payload or {"note": "x"}, actor_id=actor_id, device_id=device_id,
        expected_revision=expected_revision, extra_columns=extra, **kwargs,
    )


def test_schema_creates_every_table_from_team_architecture(tmp_path):
    repo = WorkbenchRepository(tmp_path / "bridge-workbench.sqlite3")
    with repo._connect() as conn:
        names = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
    for table in MUTABLE_TABLES:
        assert table in names, table
    assert "change_log" in names
    assert repo.schema_version() == 1


def test_write_inserts_row_and_appends_one_change_log_entry(tmp_path):
    repo = WorkbenchRepository(tmp_path / "w.sqlite3")
    result = _write(repo, "check_cache", "c1", payload={"hit": False})
    assert result["revision"] == 1

    row = repo.get("check_cache", "c1")
    assert row is not None
    assert json.loads(row["payload_json"]) == {"hit": False}

    entries = repo.change_log_entries("proj-1")
    assert len(entries) == 1
    assert entries[0]["table_name"] == "check_cache"
    assert entries[0]["row_key"] == "c1"
    assert entries[0]["op"] == "upsert"
    assert entries[0]["base_revision"] is None
    assert entries[0]["new_revision"] == 1
    assert entries[0]["synced_at"] is None


def test_write_updates_row_and_appends_a_second_change_log_entry(tmp_path):
    repo = WorkbenchRepository(tmp_path / "w.sqlite3")
    _write(repo, "check_cache", "c1", payload={"hit": False})
    result = _write(repo, "check_cache", "c1", payload={"hit": True}, expected_revision=1)
    assert result["revision"] == 2

    row = repo.get("check_cache", "c1")
    assert json.loads(row["payload_json"]) == {"hit": True}
    assert row["revision"] == 2

    entries = repo.change_log_entries("proj-1")
    assert len(entries) == 2
    assert entries[1]["base_revision"] == 1
    assert entries[1]["new_revision"] == 2


def test_write_rejects_a_stale_expected_revision(tmp_path):
    repo = WorkbenchRepository(tmp_path / "w.sqlite3")
    _write(repo, "check_cache", "c1")
    _write(repo, "check_cache", "c1", expected_revision=1)  # now at revision 2
    with pytest.raises(WorkbenchConflict):
        _write(repo, "check_cache", "c1", expected_revision=1)  # stale: real revision is 2


def test_write_last_writer_wins_when_no_revision_expected(tmp_path):
    repo = WorkbenchRepository(tmp_path / "w.sqlite3")
    _write(repo, "check_cache", "c1")
    # expected_revision=None: no conflict even though the real revision is 1.
    result = _write(repo, "check_cache", "c1", payload={"hit": True})
    assert result["revision"] == 2


def test_write_rejects_unknown_table(tmp_path):
    repo = WorkbenchRepository(tmp_path / "w.sqlite3")
    with pytest.raises(WorkbenchValidationError):
        _write(repo, "not_a_real_table", "row-1")


@pytest.mark.parametrize("table", MUTABLE_TABLES)
def test_every_mutable_table_writes_exactly_one_change_log_row(tmp_path, table):
    repo = WorkbenchRepository(tmp_path / "w.sqlite3")
    _write(repo, table, "row-1")
    entries = repo.change_log_entries("proj-1")
    assert len(entries) == 1
    assert entries[0]["table_name"] == table
    assert entries[0]["row_key"] == "row-1"


def test_change_log_rejects_delete(tmp_path):
    repo = WorkbenchRepository(tmp_path / "w.sqlite3")
    _write(repo, "check_cache", "c1")
    with pytest.raises(sqlite3.IntegrityError):
        with repo._connect() as conn:
            conn.execute("DELETE FROM change_log")
            conn.commit()


def test_change_log_rejects_update_of_anything_but_synced_at(tmp_path):
    repo = WorkbenchRepository(tmp_path / "w.sqlite3")
    _write(repo, "check_cache", "c1")
    with pytest.raises(sqlite3.IntegrityError):
        with repo._connect() as conn:
            conn.execute("UPDATE change_log SET payload_json='{}'")
            conn.commit()


def test_change_log_allows_setting_synced_at(tmp_path):
    repo = WorkbenchRepository(tmp_path / "w.sqlite3")
    _write(repo, "check_cache", "c1")
    with repo._connect() as conn:
        conn.execute("UPDATE change_log SET synced_at=?", ("2026-09-11T00:00:00Z",))
        conn.commit()
    entries = repo.change_log_entries("proj-1")
    assert entries[0]["synced_at"] == "2026-09-11T00:00:00Z"


def test_no_source_site_updates_change_log_except_synced_at():
    """Static guard: `_write()` only ever INSERTs into change_log. If future
    code (#76+) adds a raw UPDATE against it, this fails unless the SET
    clause is synced_at-only, matching the trigger's own contract."""
    package_dir = Path(__file__).resolve().parents[2] / "tc_ai_bridge"
    pattern = re.compile(r"UPDATE\s+change_log\s+SET\s+([^\"']+)", re.IGNORECASE)
    offenders = []
    for path in package_dir.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for match in pattern.finditer(text):
            clause = match.group(1).strip()
            if not clause.lower().startswith("synced_at"):
                offenders.append(f"{path.name}: {match.group(0)!r}")
    assert offenders == []


def test_workspace_repository_device_id_is_stable_across_reopen(tmp_path):
    path = tmp_path / "workspace.sqlite3"
    first = WorkspaceRepository(path).get_or_create_device_id()
    second = WorkspaceRepository(path).get_or_create_device_id()
    assert first == second
    assert first  # non-empty


def _build_minimal_project(root: Path) -> Path:
    align_dir = root / ".apps" / "translationCore" / "alignmentData" / "rut"
    align_dir.mkdir(parents=True)
    (root / "rut").mkdir(parents=True)
    (root / "manifest.json").write_text(json.dumps({
        "project": {"id": "rut", "name": "Ruth"},
        "target_language": {"id": "tam", "name": "Tamil"},
        "tc_version": "8", "tc_edit_version": "3.7.0",
    }), encoding="utf-8")
    (align_dir / "1.json").write_text(
        json.dumps({"1": {"alignments": [], "wordBank": []}}), encoding="utf-8",
    )
    return root


def test_translation_core_project_creates_an_empty_workbench_db(tmp_path):
    from tc_ai_bridge.tc_project import TranslationCoreProject

    root = _build_minimal_project(tmp_path / "rut")
    project = TranslationCoreProject(root)

    workbench_path = root / ".apps" / "translationCoreAI" / "bridge-workbench.sqlite3"
    assert workbench_path.is_file()
    assert project.workbench.schema_version() == 1
    # Nothing has written into it yet -- an empty DB is the only change (#75).
    assert repo_is_empty(project.workbench)


def repo_is_empty(repo) -> bool:
    with repo._connect() as conn:
        for table in MUTABLE_TABLES:
            if conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] != 0:
                return False
        return conn.execute("SELECT COUNT(*) FROM change_log").fetchone()[0] == 0
