"""SQLite persistence for Bridge's app-level workspace store.

One database per installation (``%LOCALAPPDATA%\\Bridge\\data\\workspace.sqlite3``
on Windows; callers decide the path, this module only opens what it is
given), holding what is *about* projects rather than *inside* one:

- ``devices`` -- one generated, stable device id per installation;
- ``users`` -- one stable local ``user_id`` (#76), so every workbench write
  has a real ``actor_id``/``device_id`` pair to stamp;
- ``projects`` -- the project registry (#77; formerly ``project-registry.json``);
- ``settings_kv`` -- non-secret application settings (#77; DPAPI-wrapped
  secrets stay in ``settings.json``, see ``secret_store.py``);
- ``project_progress_cache`` -- one cached progress rollup per project, so the
  multi-book dashboard reads one table instead of opening every sibling's
  per-project workbench database (#77, ``docs/TEAM_ARCHITECTURE.md`` section 4).

Why the ``user_id`` exists before #78 builds real identity: ``change_log``
is append-only and its ``BEFORE UPDATE``/``BEFORE DELETE`` triggers reject
every column but ``synced_at``, so whatever ``actor_id`` a workbench write
stamps is permanent and cannot be backfilled later. The only identity that
existed before this was ``AppSettings.reviewer_name`` -- a *display name*
the user can change in Settings at any time (and which V11-005 reseeds), so
stamping it would mean one person's history splits irreversibly into two
un-linkable sets of immutable rows the first time they rename themselves.
The id here is stable and the display name hangs off it, which is the shape
section 5 specifies ("every workbench write carries ``actor_id = user_id``;
display names resolve at read time"). Roles, ``authorize()`` and real
multi-user remain #78's.

Schema changes are migrations here too (CLAUDE.md). This is the third
versioned ladder, independent of both the semantic database
(``DATABASE_SCHEMA_VERSION``) and the workbench (``WORKBENCH_SCHEMA_VERSION``):
a bump here is never a bump there. ``_MIGRATION_V1`` is deliberately what the
first version of this module created with ``CREATE TABLE IF NOT EXISTS`` and
no version number at all, so a database made by that code is adopted as v1
-- its device and user ids are already stamped on immutable workbench rows
and must survive -- rather than treated as unversioned. Every later change
is a new forward block.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Iterator
import uuid


WORKSPACE_SCHEMA_VERSION = 2
WORKSPACE_SCHEMA_ID = "bridge-workspace"

# v1: exactly the two tables the unversioned first cut of this module created.
# IF NOT EXISTS is correct *here and only here*: the block has to adopt an
# existing database as much as build a fresh one.
_MIGRATION_V1 = r"""
CREATE TABLE IF NOT EXISTS devices(
    device_id TEXT PRIMARY KEY,
    machine_id TEXT,
    os_user TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS users(
    user_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1
);
"""

# v2 (#77): the project registry, non-secret settings and the per-project
# progress rollup cache. `entry_json` on `projects` keeps the registry entry
# exactly as `project-registry.json` held it, so `ProjectRegistry` returns the
# same dict shape it always did; the lifted columns are the ones it looks rows
# up by. `project_progress_cache.source_seq` is the workbench `change_log.seq`
# of the progress_totals write the cached totals came from, which is what lets
# a project open detect a cache that lags (or predates a re-import) and repair
# it -- see TranslationCoreProject.sync_progress_cache.
_MIGRATION_V2 = r"""
CREATE TABLE projects(
    project_id TEXT PRIMARY KEY,
    collection_id TEXT,
    path TEXT NOT NULL,
    path_key TEXT NOT NULL,
    managed INTEGER NOT NULL DEFAULT 0,
    missing INTEGER NOT NULL DEFAULT 0,
    last_opened_at TEXT,
    position INTEGER NOT NULL,
    entry_json TEXT NOT NULL
);
CREATE INDEX ix_projects_path_key ON projects(path_key);
CREATE INDEX ix_projects_collection ON projects(collection_id);

CREATE TABLE settings_kv(
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE project_progress_cache(
    path_key TEXT PRIMARY KEY,
    project_path TEXT NOT NULL,
    project_id TEXT NOT NULL,
    book_id TEXT NOT NULL,
    totals_json TEXT NOT NULL,
    updated_at TEXT,
    source_seq INTEGER NOT NULL,
    refreshed_at TEXT NOT NULL
);
"""

_MIGRATIONS: tuple[tuple[int, str], ...] = (
    (1, _MIGRATION_V1),
    (2, _MIGRATION_V2),
)


class WorkspaceError(RuntimeError):
    pass


class WorkspaceRepository:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._migrate()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.path), timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA synchronous = FULL")
        conn.execute("PRAGMA journal_mode = WAL")
        if conn.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
            conn.close()
            raise WorkspaceError("SQLite foreign-key enforcement could not be enabled")
        try:
            yield conn
        finally:
            conn.close()

    # -- schema ladder, same discipline as WorkbenchRepository ---------------

    def _migrate(self) -> None:
        with self._connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations("
                "version INTEGER PRIMARY KEY, schema_id TEXT NOT NULL, applied_at TEXT NOT NULL)"
            )
            current = int(conn.execute(
                "SELECT COALESCE(MAX(version),0) FROM schema_migrations"
            ).fetchone()[0])
            if current > WORKSPACE_SCHEMA_VERSION:
                raise WorkspaceError(
                    f"Workspace schema {current} is newer than supported v{WORKSPACE_SCHEMA_VERSION}"
                )
            # Decided once, before the ladder runs: a fresh database gains
            # tables at v1, and backing it up before v2 would copy nothing
            # anyone wrote. A database written by the unversioned first cut
            # has current == 0 but real rows, so this tests for tables, not
            # for a version above zero.
            pre_existing = bool(conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name <> 'schema_migrations'"
            ).fetchone()[0])
            for version, script in _MIGRATIONS:
                if version <= current:
                    continue
                if pre_existing:
                    self._backup_before_migration(conn, current, version)
                self._apply_migration(conn, version, script)
                current = version

    def _backup_before_migration(self, conn: sqlite3.Connection, current: int, target: int) -> None:
        """Create a consistent, inspectable backup before upgrading an existing DB.

        Only called for a database that held tables before this open began
        (see `_migrate`), so there is always something worth copying.
        """
        root = self.path.parent / "backups"
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        directory = root / f"pre-workspace-v{target}-{stamp}"
        directory.mkdir(parents=True, exist_ok=False)
        backup_db = directory / self.path.name
        destination = sqlite3.connect(str(backup_db))
        try:
            conn.backup(destination)
        finally:
            destination.close()
        digest = hashlib.sha256(backup_db.read_bytes()).hexdigest()
        manifest = {
            "reason": f"automatic backup before workspace schema migration v{current} to v{target}",
            "schemaId": WORKSPACE_SCHEMA_ID,
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
        schema_id = WORKSPACE_SCHEMA_ID.replace("'", "''")
        applied_at = self._now().replace("'", "''")
        conn.executescript(
            "BEGIN IMMEDIATE;\n"
            + script
            + f"\nINSERT INTO schema_migrations(version,schema_id,applied_at) "
              f"VALUES({version},'{schema_id}','{applied_at}');\n"
            + f"PRAGMA user_version = {version};\nCOMMIT;"
        )

    def schema_version(self) -> int:
        with self._connect() as conn:
            return int(
                conn.execute("SELECT COALESCE(MAX(version),0) FROM schema_migrations").fetchone()[0]
            )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    # -- devices and users ----------------------------------------------------

    def get_or_create_device_id(self) -> str:
        """Return this installation's device id, minting one on first call.

        One workspace database is one installation, so the first row wins;
        machine_id/os_user population is #78's job, not this one's.
        """
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT device_id FROM devices ORDER BY created_at LIMIT 1"
            ).fetchone()
            if row is not None:
                conn.commit()
                return str(row["device_id"])
            device_id = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO devices(device_id, machine_id, os_user, created_at) VALUES(?,?,?,?)",
                (device_id, None, None, self._now()),
            )
            conn.commit()
            return device_id

    def get_or_create_local_user(self, display_name: str) -> dict[str, str]:
        """Return this installation's local user, minting one on first call.

        The ``user_id`` is stable for the life of the workspace database and
        is what every workbench write stamps. ``display_name`` is refreshed
        from the caller on every call -- renaming yourself in Settings must
        change how you are shown everywhere, past rows included, *without*
        detaching you from the history you already wrote. That is the whole
        reason the two are separate columns.

        One workspace database is one installation, so the first (oldest)
        active row wins. Choosing between several users is #78's job.
        """
        name = str(display_name or "").strip() or "Unnamed Reviewer"
        now = self._now()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT user_id, display_name FROM users WHERE active=1 ORDER BY created_at LIMIT 1"
            ).fetchone()
            if row is not None:
                user_id = str(row["user_id"])
                if str(row["display_name"]) != name:
                    conn.execute(
                        "UPDATE users SET display_name=?, updated_at=? WHERE user_id=?",
                        (name, now, user_id),
                    )
                conn.commit()
                return {"userId": user_id, "displayName": name}
            user_id = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO users(user_id, display_name, created_at, updated_at, active) "
                "VALUES(?,?,?,?,1)",
                (user_id, name, now, now),
            )
            conn.commit()
            return {"userId": user_id, "displayName": name}
