"""SQLite persistence for Bridge's app-level workspace store.

Skeleton only (#75): a ``devices`` table holding one generated, stable
device id per installation, so every workbench write has a real
``device_id`` to stamp before identity work (#78) exists. Users, the
project registry, settings and the per-project rollup cache
(``docs/TEAM_ARCHITECTURE.md`` section 4) land in a later step once there is
a user to attach them to.

This lives at the app level (``%LOCALAPPDATA%\\Bridge\\data\\workspace.sqlite3``
on Windows), not inside any project folder -- callers decide the path;
this module only opens whatever path it is given.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import Iterator
import uuid


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

    def _migrate(self) -> None:
        with self._connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS devices("
                "device_id TEXT PRIMARY KEY, machine_id TEXT, os_user TEXT, created_at TEXT NOT NULL)"
            )
            conn.commit()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

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
