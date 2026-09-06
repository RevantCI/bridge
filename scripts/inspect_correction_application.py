"""Read-only installed-acceptance inspector for correction applications.

Bridge imports a selected project into its application-owned ``data/projects``
directory.  Passing the original source folder to a raw SQLite check can
therefore inspect the wrong physical database.  This tool resolves the stable
project identity through Bridge's registry first, then reports every matching
main semantic database without opening the writable repository layer.

Usage:
    python scripts/inspect_correction_application.py SOURCE_PROJECT FINDING_ID PROPOSAL_ID
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
from typing import Any


SEMANTIC_DB = Path(".apps/translationCoreAI/passageSemantic/bridge-semantic.sqlite3")


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _project_id(project_root: Path) -> str:
    identity = project_root / ".bridge" / "project.json"
    if identity.is_file():
        return str(_json(identity).get("projectId") or "")
    return ""


def _registry_entries(registry_path: Path) -> list[dict[str, Any]]:
    if not registry_path.is_file():
        return []
    payload = _json(registry_path)
    entries = payload if isinstance(payload, list) else payload.get("projects", [])
    if isinstance(entries, dict):
        entries = list(entries.values())
    return [dict(item) for item in entries if isinstance(item, dict)]


def resolve_runtime_projects(source_project: Path, bridge_data_root: Path) -> dict[str, Any]:
    source = source_project.resolve()
    project_id = _project_id(source)
    registry_path = bridge_data_root / "project-registry.json"
    matches = [
        item for item in _registry_entries(registry_path)
        if project_id and str(item.get("projectId") or "") == project_id
    ]
    roots = [source]
    roots.extend(Path(str(item["path"])).resolve() for item in matches if item.get("path"))
    unique = list(dict.fromkeys(roots))
    managed = [
        Path(str(item["path"])).resolve()
        for item in matches
        if item.get("managed") and item.get("path") and not item.get("missing")
    ]
    return {
        "requestedProjectRoot": str(source),
        "projectId": project_id,
        "registryPath": str(registry_path),
        "authoritativeRuntimeProjectRoot": str(managed[0]) if len(managed) == 1 else None,
        "candidateProjectRoots": [str(path) for path in unique],
    }


def _row(connection: sqlite3.Connection, sql: str, values: tuple[Any, ...]) -> dict[str, Any] | None:
    result = connection.execute(sql, values).fetchone()
    return None if result is None else dict(result)


def inspect_database(
    project_root: Path, finding_id: str, proposal_id: str,
) -> dict[str, Any]:
    database = project_root / SEMANTIC_DB
    report: dict[str, Any] = {
        "projectRoot": str(project_root),
        "databasePath": str(database),
        "databaseExists": database.is_file(),
    }
    if not database.is_file():
        return report
    report["databaseModifiedAt"] = datetime.fromtimestamp(
        database.stat().st_mtime, timezone.utc
    ).isoformat()
    connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        report["schemaVersion"] = int(connection.execute("PRAGMA user_version").fetchone()[0])
        report["finding"] = _row(
            connection,
            "SELECT id,project_id,qa_disposition,review_status,lifecycle_status,revision "
            "FROM qa_findings WHERE id=?",
            (finding_id,),
        )
        report["proposal"] = _row(
            connection,
            "SELECT id,project_id,qa_finding_id,revision,applied_target_revision,"
            "review_status,lifecycle_status,verification_status "
            "FROM correction_proposals WHERE id=?",
            (proposal_id,),
        )
        report["applications"] = [dict(item) for item in connection.execute(
            "SELECT application_id,expected_proposal_revision,application_state,state_revision,"
            "target_displayed_reference,source_provenance_references_json,"
            "translation_core_journal_transaction_id,created_at,updated_at,completed_at "
            "FROM correction_application_intents WHERE proposal_id=? "
            "ORDER BY created_at,application_id",
            (proposal_id,),
        )]
    finally:
        connection.close()
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_project", type=Path)
    parser.add_argument("finding_id")
    parser.add_argument("proposal_id")
    default_data = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "Bridge/data"
    parser.add_argument("--bridge-data-root", type=Path, default=default_data)
    args = parser.parse_args()

    resolution = resolve_runtime_projects(args.source_project, args.bridge_data_root.resolve())
    resolution["databases"] = [
        inspect_database(Path(path), args.finding_id, args.proposal_id)
        for path in resolution["candidateProjectRoots"]
    ]
    print(json.dumps(resolution, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
