"""Lazy, resumable migration of file-backed stores into the workbench DB.

#76 step 1. This module is the *runner* -- the mechanism that moves a
project's file-backed stores into ``bridge-workbench.sqlite3`` once, on first
open, and picks up where it left off if it is interrupted. The store moves
themselves are deliberately not here yet: ``REGISTRY`` is empty, so on a real
project this code does nothing at all until a later step registers the first
store. Landing the mechanism on its own is what lets it be reviewed against
the failure it exists for -- a migration killed halfway through, on a
translation team's only copy of months of work -- rather than as a footnote
to two thousand lines of store redirection.

Design: ``docs/TEAM_ARCHITECTURE.md`` ss3.5.

Three properties the rest of #76 depends on, each with a test:

*Never breaks project open.* A store that raises leaves the migration
incomplete and the project usable, reading from its files exactly as before.
There is no state in which a failed migration makes a project unopenable --
the whole point of keeping the source files is that falling back is always
possible, and a project that will not open is worse than one that has not
migrated.

*Resumable, not restartable.* Each store records itself as done the moment
it finishes. A run interrupted after the third of ten stores resumes at the
fourth; it does not redo the first three and it does not skip them.

*Idempotent at the row level.* Stores derive primary keys from natural keys
(:func:`~tc_ai_bridge.workbench_repository.natural_row_id`), so a store
interrupted *mid-way* -- after some of its rows but before it recorded
itself -- is safe to re-run: the rows it already wrote are overwritten with
the same values rather than duplicated. That is why per-store atomicity is
not required, and why ``_write``'s one-transaction-per-row is sufficient
here. It is also why a store migration must never append to a list it reads
from the database, only rewrite it from the file.

Source files are never deleted by any of this. Readers fall back to their
``_legacy_*`` file paths until a store reports complete.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import Any, Callable

from .workbench_repository import (
    WorkbenchError,
    WorkbenchRepository,
    natural_row_id,
)

#: ``project_state`` key holding migration progress for one project+book.
MIGRATION_STATE_KEY = "migration"

STATUS_IN_PROGRESS = "in_progress"
STATUS_COMPLETE = "complete"
STATUS_FAILED = "failed"


@dataclass(frozen=True)
class WorkbenchIdentity:
    """Who is writing, and to which project.

    Carried explicitly rather than read from global settings so that a
    migration, a background job and a user action are all attributable to
    the same identity without any of them reaching for app state. Every
    field lands verbatim on ``change_log`` rows that can never be edited
    afterwards, so this is deliberately a value object with no defaults --
    a caller has to say who it is.
    """

    project_id: str
    book_id: str | None
    actor_id: str
    device_id: str


@dataclass(frozen=True)
class StoreMigration:
    """One file-backed store's move into the workbench database.

    ``migrate`` receives the project, the repository and the identity, and
    returns how many records it moved (for the log; the count is not a
    correctness signal, since a re-run legitimately returns the same count).
    It must be safe to call twice.
    """

    name: str
    migrate: Callable[[Any, WorkbenchRepository, WorkbenchIdentity], int]


#: Ordered; runs front to back. Empty on purpose in this step -- see the
#: module docstring. Later steps append, they do not reorder: a project
#: part-way through a migration identifies its progress by store *name*.
REGISTRY: tuple[StoreMigration, ...] = ()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _state_row_id(identity: WorkbenchIdentity) -> str:
    return natural_row_id(identity.project_id, identity.book_id, MIGRATION_STATE_KEY)


def migration_state(
    workbench: WorkbenchRepository, identity: WorkbenchIdentity
) -> dict[str, Any]:
    """Read migration progress, tolerating a database that has none yet.

    A project opened before this landed has no state row; so does a brand
    new one. Both are "nothing done yet", not an error.
    """
    try:
        row = workbench.get("project_state", _state_row_id(identity))
    except WorkbenchError:
        return {"status": STATUS_IN_PROGRESS, "completedStores": [], "revision": None}
    if row is None:
        return {"status": STATUS_IN_PROGRESS, "completedStores": [], "revision": None}
    try:
        payload = json.loads(row["payload_json"])
    except (TypeError, ValueError, KeyError):
        # Unreadable state is treated as "not done" rather than as a hard
        # failure: re-running an idempotent migration is harmless, and the
        # alternative is a project that cannot be opened.
        return {"status": STATUS_IN_PROGRESS, "completedStores": [], "revision": None}
    completed = payload.get("completedStores")
    return {
        "status": str(payload.get("status") or STATUS_IN_PROGRESS),
        "completedStores": [str(x) for x in completed] if isinstance(completed, list) else [],
        "revision": row.get("revision"),
    }


def is_store_migrated(
    workbench: WorkbenchRepository, identity: WorkbenchIdentity, store_name: str
) -> bool:
    """Whether one store's records now live in the database.

    This is what a redirected reader asks before choosing between the
    workbench row and its ``_legacy_*`` file. Per store, not per project:
    stores land one at a time, and a reader for store A must not be held
    back because store B has not moved yet.
    """
    return store_name in migration_state(workbench, identity)["completedStores"]


def _record(
    workbench: WorkbenchRepository,
    identity: WorkbenchIdentity,
    *,
    status: str,
    completed: list[str],
    expected_revision: int | None,
    error: str = "",
) -> int:
    payload: dict[str, Any] = {
        "status": status,
        "completedStores": completed,
        "updatedAt": _now(),
    }
    if error:
        payload["lastError"] = error
    result = workbench._write(
        "project_state",
        _state_row_id(identity),
        project_id=identity.project_id,
        book_id=identity.book_id,
        payload=payload,
        actor_id=identity.actor_id,
        device_id=identity.device_id,
        expected_revision=expected_revision,
        op="migration",
        extra_columns={"key": MIGRATION_STATE_KEY},
    )
    return int(result["revision"])


def run_pending_migrations(
    project: Any,
    workbench: WorkbenchRepository,
    identity: WorkbenchIdentity,
    registry: tuple[StoreMigration, ...] | None = None,
) -> dict[str, Any]:
    """Run every store migration that has not run yet, in order.

    Returns a summary; never raises. Called from
    ``TranslationCoreProject.__init__`` after journal recovery, so anything
    that escapes here is a project the user cannot open.

    With an empty registry this writes nothing at all -- not even a
    "complete" state row. A project that has never had a store to migrate
    should be byte-identical to one opened before this module existed.
    """
    stores = REGISTRY if registry is None else registry
    if not stores:
        return {"status": STATUS_COMPLETE, "ran": [], "skipped": [], "failed": ""}

    state = migration_state(workbench, identity)
    completed = list(state["completedStores"])
    revision = state["revision"]
    if state["status"] == STATUS_COMPLETE and all(s.name in completed for s in stores):
        return {"status": STATUS_COMPLETE, "ran": [], "skipped": [s.name for s in stores], "failed": ""}

    ran: list[str] = []
    skipped = [s.name for s in stores if s.name in completed]

    for store in stores:
        if store.name in completed:
            continue
        try:
            store.migrate(project, workbench, identity)
        except Exception as error:  # noqa: BLE001 -- see the docstring
            # Stop rather than skipping ahead: a later store may depend on
            # an earlier one, and finishing out of order would record a
            # completion that is not true. The project stays readable from
            # its files, and the next open retries from exactly here.
            try:
                _record(
                    workbench, identity, status=STATUS_FAILED, completed=completed,
                    expected_revision=revision, error=f"{store.name}: {error}",
                )
            except Exception:  # noqa: BLE001
                pass
            return {
                "status": STATUS_FAILED, "ran": ran, "skipped": skipped,
                "failed": store.name, "error": str(error),
            }
        completed.append(store.name)
        ran.append(store.name)
        try:
            revision = _record(
                workbench, identity,
                status=STATUS_COMPLETE if len(completed) == len(stores) else STATUS_IN_PROGRESS,
                completed=completed, expected_revision=revision,
            )
        except Exception as error:  # noqa: BLE001
            # The rows are already written and the store is idempotent, so
            # the only cost of failing to record is that the next open
            # re-runs it. Not worth failing the open for.
            return {
                "status": STATUS_IN_PROGRESS, "ran": ran, "skipped": skipped,
                "failed": "", "error": str(error),
            }

    return {"status": STATUS_COMPLETE, "ran": ran, "skipped": skipped, "failed": ""}
