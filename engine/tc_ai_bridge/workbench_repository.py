"""SQLite persistence for Bridge's per-project workbench store.

Beside the v14 semantic-analysis companion database
(``passage_semantic_repository.py``, untouched by this module) each project
gets a second database, ``bridge-workbench.sqlite3``, for Bridge-private
state that is not an analysis record with a lifecycle: human decisions, QA
dispositions, progress rollups, and the rest of ``docs/TEAM_ARCHITECTURE.md``
section 3. See that document and ``docs/DECISIONS.md`` (2026-09-11, "second
per-project SQLite, not v15") for why this is a second database rather than
a v15 migration of the existing one.

This module is the repository skeleton (#75): schema, the append-only
``change_log``, and one generic revision-checked write path. No existing
file-based store is moved into it yet -- that is #76 (human-owned stores)
and #77 (derived stores, workspace rollup cache, sync readiness).
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Any, Iterator
import uuid


WORKBENCH_SCHEMA_VERSION = 1
WORKBENCH_SCHEMA_ID = "bridge-workbench-v1"

_IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9_]*$")

# The tables human decisions and derived caches move into, per
# TEAM_ARCHITECTURE.md ss3.1/3.2. `change_log` is deliberately not one of
# these -- it is never a `_write()` target, only ever appended to inside
# `_write()` itself.
MUTABLE_TABLES: tuple[str, ...] = (
    "human_decisions",
    "issue_resolutions",
    "ai_review_results",
    "alignment_history",
    "alignment_diagnostics",
    "team_members",
    "team_assignments",
    "semantic_mappings",
    "semantic_validation_runs",
    "project_state",
    "progress_chapters",
    "progress_findings",
    "progress_totals",
    "check_findings",
    "check_cache",
    "triage_verdicts",
    "metrics_events",
    "metrics_counters",
    "file_backups",
)


class WorkbenchError(RuntimeError):
    pass


class WorkbenchValidationError(WorkbenchError):
    pass


class WorkbenchConflict(WorkbenchError):
    pass


# Every mutable table carries the same nine columns first (id, project_id,
# book_id, revision, actor_id, device_id, created_at, updated_at,
# payload_json) so `_write()` can INSERT/UPDATE them generically; table-
# specific "lifted" columns come after, exactly the ones TEAM_ARCHITECTURE.md
# ss3.1/3.2 names for that table and no others -- `payload_json` already
# carries everything else unchanged.
_MIGRATION_V1 = r"""
CREATE TABLE human_decisions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    book_id TEXT,
    revision INTEGER NOT NULL DEFAULT 1 CHECK(revision >= 1),
    actor_id TEXT NOT NULL,
    device_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('check','qa','verse_status','terminology')),
    chapter TEXT,
    verse TEXT,
    key TEXT NOT NULL,
    decision TEXT,
    UNIQUE(project_id, book_id, kind, chapter, verse, key)
);
CREATE INDEX ix_human_decisions_scope ON human_decisions(project_id, book_id, kind);

CREATE TABLE issue_resolutions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    book_id TEXT,
    revision INTEGER NOT NULL DEFAULT 1 CHECK(revision >= 1),
    actor_id TEXT NOT NULL,
    device_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    status TEXT,
    recheck_status TEXT,
    paratext_status TEXT
);
CREATE INDEX ix_issue_resolutions_scope ON issue_resolutions(project_id, book_id);

CREATE TABLE ai_review_results (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    book_id TEXT,
    revision INTEGER NOT NULL DEFAULT 1 CHECK(revision >= 1),
    actor_id TEXT NOT NULL,
    device_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    chapter TEXT NOT NULL,
    verse TEXT NOT NULL,
    input_fingerprint TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    UNIQUE(project_id, book_id, chapter, verse)
);

CREATE TABLE alignment_history (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    book_id TEXT,
    revision INTEGER NOT NULL DEFAULT 1 CHECK(revision >= 1),
    actor_id TEXT NOT NULL,
    device_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    chapter TEXT,
    verse TEXT,
    backup_path TEXT
);
CREATE INDEX ix_alignment_history_scope ON alignment_history(project_id, book_id, chapter, verse);

CREATE TABLE alignment_diagnostics (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    book_id TEXT,
    revision INTEGER NOT NULL DEFAULT 1 CHECK(revision >= 1),
    actor_id TEXT NOT NULL,
    device_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    chapter TEXT,
    verse TEXT
);
CREATE INDEX ix_alignment_diagnostics_scope ON alignment_diagnostics(project_id, book_id, chapter, verse);

CREATE TABLE team_members (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    book_id TEXT,
    revision INTEGER NOT NULL DEFAULT 1 CHECK(revision >= 1),
    actor_id TEXT NOT NULL,
    device_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    payload_json TEXT NOT NULL
);

CREATE TABLE team_assignments (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    book_id TEXT,
    revision INTEGER NOT NULL DEFAULT 1 CHECK(revision >= 1),
    actor_id TEXT NOT NULL,
    device_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    payload_json TEXT NOT NULL
);

CREATE TABLE semantic_mappings (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    book_id TEXT,
    revision INTEGER NOT NULL DEFAULT 1 CHECK(revision >= 1),
    actor_id TEXT NOT NULL,
    device_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    UNIQUE(project_id, book_id, fingerprint)
);

CREATE TABLE semantic_validation_runs (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    book_id TEXT,
    revision INTEGER NOT NULL DEFAULT 1 CHECK(revision >= 1),
    actor_id TEXT NOT NULL,
    device_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    suite_id TEXT NOT NULL
);
CREATE INDEX ix_semantic_validation_runs_suite ON semantic_validation_runs(project_id, suite_id);

CREATE TABLE project_state (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    book_id TEXT,
    revision INTEGER NOT NULL DEFAULT 1 CHECK(revision >= 1),
    actor_id TEXT NOT NULL,
    device_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    key TEXT NOT NULL,
    UNIQUE(project_id, book_id, key)
);

CREATE TABLE progress_chapters (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    book_id TEXT,
    revision INTEGER NOT NULL DEFAULT 1 CHECK(revision >= 1),
    actor_id TEXT NOT NULL,
    device_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    chapter TEXT NOT NULL,
    UNIQUE(project_id, book_id, chapter)
);

CREATE TABLE progress_findings (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    book_id TEXT,
    revision INTEGER NOT NULL DEFAULT 1 CHECK(revision >= 1),
    actor_id TEXT NOT NULL,
    device_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    chapter TEXT
);
CREATE INDEX ix_progress_findings_scope ON progress_findings(project_id, book_id, chapter);

CREATE TABLE progress_totals (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    book_id TEXT,
    revision INTEGER NOT NULL DEFAULT 1 CHECK(revision >= 1),
    actor_id TEXT NOT NULL,
    device_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    UNIQUE(project_id, book_id)
);

CREATE TABLE check_findings (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    book_id TEXT,
    revision INTEGER NOT NULL DEFAULT 1 CHECK(revision >= 1),
    actor_id TEXT NOT NULL,
    device_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    chapter TEXT NOT NULL,
    UNIQUE(project_id, book_id, chapter)
);

CREATE TABLE check_cache (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    book_id TEXT,
    revision INTEGER NOT NULL DEFAULT 1 CHECK(revision >= 1),
    actor_id TEXT NOT NULL,
    device_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    payload_json TEXT NOT NULL
);

CREATE TABLE triage_verdicts (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    book_id TEXT,
    revision INTEGER NOT NULL DEFAULT 1 CHECK(revision >= 1),
    actor_id TEXT NOT NULL,
    device_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    UNIQUE(project_id, book_id)
);

CREATE TABLE metrics_events (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    book_id TEXT,
    revision INTEGER NOT NULL DEFAULT 1 CHECK(revision >= 1),
    actor_id TEXT NOT NULL,
    device_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE INDEX ix_metrics_events_scope ON metrics_events(project_id, book_id, created_at);

CREATE TABLE metrics_counters (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    book_id TEXT,
    revision INTEGER NOT NULL DEFAULT 1 CHECK(revision >= 1),
    actor_id TEXT NOT NULL,
    device_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    payload_json TEXT NOT NULL
);

CREATE TABLE file_backups (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    book_id TEXT,
    revision INTEGER NOT NULL DEFAULT 1 CHECK(revision >= 1),
    actor_id TEXT NOT NULL,
    device_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    payload_json TEXT NOT NULL
);

CREATE TABLE change_log (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    project_id TEXT NOT NULL,
    book_id TEXT,
    table_name TEXT NOT NULL,
    row_key TEXT NOT NULL,
    op TEXT NOT NULL,
    base_revision INTEGER,
    new_revision INTEGER,
    actor_id TEXT NOT NULL,
    device_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    journal_tx_id TEXT,
    synced_at TEXT
);
CREATE INDEX ix_change_log_project_seq ON change_log(project_id, seq);
CREATE INDEX ix_change_log_unsynced ON change_log(project_id, synced_at);

CREATE TRIGGER trg_change_log_no_delete
BEFORE DELETE ON change_log
BEGIN
    SELECT RAISE(ABORT, 'change_log is append-only: delete is not permitted');
END;

CREATE TRIGGER trg_change_log_no_update
BEFORE UPDATE ON change_log
WHEN NEW.seq IS NOT OLD.seq OR NEW.event_id IS NOT OLD.event_id
    OR NEW.project_id IS NOT OLD.project_id OR NEW.book_id IS NOT OLD.book_id
    OR NEW.table_name IS NOT OLD.table_name OR NEW.row_key IS NOT OLD.row_key
    OR NEW.op IS NOT OLD.op OR NEW.base_revision IS NOT OLD.base_revision
    OR NEW.new_revision IS NOT OLD.new_revision OR NEW.actor_id IS NOT OLD.actor_id
    OR NEW.device_id IS NOT OLD.device_id OR NEW.created_at IS NOT OLD.created_at
    OR NEW.payload_json IS NOT OLD.payload_json OR NEW.journal_tx_id IS NOT OLD.journal_tx_id
BEGIN
    SELECT RAISE(ABORT, 'change_log rows are immutable except synced_at');
END;
"""


class WorkbenchRepository:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.read_only = False
        self._migrate()

    # -- connection discipline, copied from FoundationRepository
    # (passage_semantic_repository.py:1070-1086) --------------------------
    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.path), timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA synchronous = FULL")
        conn.execute("PRAGMA journal_mode = WAL")
        if self.read_only:
            conn.execute("PRAGMA query_only = ON")
        if conn.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
            conn.close()
            raise WorkbenchError("SQLite foreign-key enforcement could not be enabled")
        try:
            yield conn
        finally:
            conn.close()

    def _migrate(self) -> None:
        with self._connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations("
                "version INTEGER PRIMARY KEY, schema_id TEXT NOT NULL, applied_at TEXT NOT NULL)"
            )
            current = conn.execute(
                "SELECT COALESCE(MAX(version),0) FROM schema_migrations"
            ).fetchone()[0]
            if current > WORKBENCH_SCHEMA_VERSION:
                raise WorkbenchError(
                    f"Workbench schema {current} is newer than supported v{WORKBENCH_SCHEMA_VERSION}"
                )
            if current < 1:
                self._backup_before_migration(conn, current, 1)
                self._apply_migration(conn, 1, _MIGRATION_V1)

    def _backup_before_migration(self, conn: sqlite3.Connection, current: int, target: int) -> None:
        """Create a consistent, inspectable backup before upgrading an existing DB.

        A no-op for the very first migration into a not-yet-existing file --
        there is nothing to back up yet.
        """
        if current <= 0 or not self.path.is_file():
            return
        root = self.path.parent / "backups"
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        directory = root / f"pre-workbench-v{target}-{stamp}"
        directory.mkdir(parents=True, exist_ok=False)
        backup_db = directory / "bridge-workbench.sqlite3"
        destination = sqlite3.connect(str(backup_db))
        try:
            conn.backup(destination)
        finally:
            destination.close()
        digest = hashlib.sha256(backup_db.read_bytes()).hexdigest()
        manifest = {
            "reason": f"automatic backup before workbench schema migration v{current} to v{target}",
            "schemaId": WORKBENCH_SCHEMA_ID,
            "schemaVersion": current,
            "source": str(self.path),
            "targetSchemaVersion": target,
            "sha256": digest,
            "createdAt": self._now(),
        }
        (directory / "backup-manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )

    def _apply_migration(self, conn: sqlite3.Connection, version: int, script: str) -> None:
        schema_id = WORKBENCH_SCHEMA_ID.replace("'", "''")
        applied_at = self._now().replace("'", "''")
        conn.executescript(
            "BEGIN IMMEDIATE;\n"
            + script
            + f"\nINSERT INTO schema_migrations(version,schema_id,applied_at) "
              f"VALUES({version},'{schema_id}','{applied_at}');\n"
            + f"PRAGMA user_version = {version};\nCOMMIT;"
        )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def schema_version(self) -> int:
        with self._connect() as conn:
            return int(
                conn.execute("SELECT COALESCE(MAX(version),0) FROM schema_migrations").fetchone()[0]
            )

    def get(self, table: str, row_id: str) -> dict[str, Any] | None:
        self._require_mutable_table(table)
        with self._connect() as conn:
            row = conn.execute(f"SELECT * FROM {table} WHERE id=?", (row_id,)).fetchone()
            return dict(row) if row is not None else None

    def change_log_entries(self, project_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM change_log WHERE project_id=? ORDER BY seq", (project_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    @staticmethod
    def _require_mutable_table(table: str) -> None:
        if table not in MUTABLE_TABLES:
            raise WorkbenchValidationError(f"Not a workbench-mutable table: {table}")

    def _write(
        self,
        table: str,
        row_id: str,
        *,
        project_id: str,
        book_id: str | None,
        payload: dict[str, Any],
        actor_id: str,
        device_id: str,
        expected_revision: int | None,
        op: str = "upsert",
        extra_columns: dict[str, Any] | None = None,
        journal_tx_id: str | None = None,
    ) -> dict[str, Any]:
        """Insert-or-update one row with an optimistic-concurrency check.

        ``expected_revision=None`` means last-writer-wins (what every file
        writer does today); a caller can start passing real revisions later
        without a schema change (TEAM_ARCHITECTURE.md ss3.3). The revision
        check and the change_log append happen in the same BEGIN IMMEDIATE
        transaction, following the pattern in
        passage_semantic_repository.py:3717-3733 -- callers never touch
        change_log directly.
        """
        self._require_mutable_table(table)
        extra_columns = extra_columns or {}
        for column in extra_columns:
            if not _IDENTIFIER_RE.match(column):
                raise WorkbenchValidationError(f"Unsafe column name: {column!r}")
        now = self._now()
        payload_text = json.dumps(payload, ensure_ascii=False)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(f"SELECT revision FROM {table} WHERE id=?", (row_id,)).fetchone()
            if row is None:
                if expected_revision not in (None, 0):
                    raise WorkbenchConflict(f"{table}:{row_id} does not exist yet")
                base_revision = None
                new_revision = 1
                columns = [
                    "id", "project_id", "book_id", "revision", "actor_id",
                    "device_id", "created_at", "updated_at", "payload_json",
                    *extra_columns.keys(),
                ]
                values = [
                    row_id, project_id, book_id, new_revision, actor_id,
                    device_id, now, now, payload_text, *extra_columns.values(),
                ]
                placeholders = ",".join("?" for _ in values)
                conn.execute(
                    f"INSERT INTO {table}({','.join(columns)}) VALUES({placeholders})", values,
                )
            else:
                base_revision = int(row["revision"])
                if expected_revision is not None and expected_revision != base_revision:
                    raise WorkbenchConflict(f"{table}:{row_id} revision conflict")
                new_revision = base_revision + 1
                assignments = ["revision=?", "actor_id=?", "device_id=?", "updated_at=?", "payload_json=?"]
                values: list[Any] = [new_revision, actor_id, device_id, now, payload_text]
                for column, value in extra_columns.items():
                    assignments.append(f"{column}=?")
                    values.append(value)
                values.extend([row_id, base_revision])
                changed = conn.execute(
                    f"UPDATE {table} SET {','.join(assignments)} WHERE id=? AND revision=?", values,
                ).rowcount
                if changed != 1:
                    raise WorkbenchConflict(f"{table}:{row_id} revision conflict")
            event_id = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO change_log(event_id,project_id,book_id,table_name,row_key,op,"
                "base_revision,new_revision,actor_id,device_id,created_at,payload_json,journal_tx_id) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    event_id, project_id, book_id, table, row_id, op,
                    base_revision, new_revision, actor_id, device_id, now, payload_text, journal_tx_id,
                ),
            )
            conn.commit()
        return {"id": row_id, "revision": new_revision, "eventId": event_id}
