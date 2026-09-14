"""SQLite persistence for Bridge's app-level workspace store.

A ``devices`` table holding one generated, stable device id per
installation, and a ``users`` table holding one stable local ``user_id``
(#76), so every workbench write has a real ``actor_id``/``device_id`` pair
to stamp. The project registry, settings and the per-project rollup cache
(``docs/TEAM_ARCHITECTURE.md`` section 4) land in a later step.

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
            conn.execute(
                "CREATE TABLE IF NOT EXISTS users("
                "user_id TEXT PRIMARY KEY, display_name TEXT NOT NULL, created_at TEXT NOT NULL, "
                "updated_at TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1)"
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
