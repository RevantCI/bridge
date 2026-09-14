"""The workbench migration runner (#76 step 1).

The registry is empty in production, so everything here drives the runner
with test-registered stores. That is the point of landing the mechanism on
its own: the behaviour worth reviewing is what happens when a migration is
interrupted or fails, and that is much harder to see once ten real store
moves are layered on top of it.
"""
from __future__ import annotations

import json

import pytest

from tc_ai_bridge.workbench_migration import (
    MIGRATION_STATE_KEY,
    STATUS_COMPLETE,
    STATUS_FAILED,
    STATUS_IN_PROGRESS,
    StoreMigration,
    WorkbenchIdentity,
    is_store_migrated,
    migration_state,
    run_pending_migrations,
)
from tc_ai_bridge.workbench_repository import WorkbenchRepository, natural_row_id
from tc_ai_bridge.workspace_repository import WorkspaceRepository


@pytest.fixture
def workbench(tmp_path):
    return WorkbenchRepository(tmp_path / "bridge-workbench.sqlite3")


@pytest.fixture
def identity():
    return WorkbenchIdentity(
        project_id="proj-1", book_id="php", actor_id="user-1", device_id="dev-1",
    )


def recorder(name, log, *, fails=False):
    """A store migration that records that it ran, optionally by failing."""
    def migrate(project, repo, ident):
        log.append(name)
        if fails:
            raise RuntimeError(f"{name} exploded")
        return 1
    return StoreMigration(name=name, migrate=migrate)


# --------------------------------------------------------------------------
# Inertness: nothing registered must mean nothing happens at all.
# --------------------------------------------------------------------------

def test_an_empty_registry_writes_nothing(workbench, identity):
    """A project with no store to migrate must be untouched, not marked done.

    Production ships an empty REGISTRY in this step, so this is the case
    every real project hits. Writing even a 'complete' marker would mean
    every project on every machine gains a row for a migration that has not
    been designed yet.
    """
    result = run_pending_migrations(None, workbench, identity, registry=())

    assert result["status"] == STATUS_COMPLETE
    assert result["ran"] == []
    assert workbench.change_log_entries("proj-1") == []
    assert workbench.get("project_state", natural_row_id("proj-1", "php", MIGRATION_STATE_KEY)) is None


def test_the_production_registry_is_still_empty():
    """Guards the claim in the module docstring and in #76's commit message.

    If a later step registers a store without meaning to, this fails and
    says so, rather than silently migrating real projects.
    """
    from tc_ai_bridge.workbench_migration import REGISTRY

    assert REGISTRY == ()


# --------------------------------------------------------------------------
# The happy path.
# --------------------------------------------------------------------------

def test_runs_every_store_in_registry_order(workbench, identity):
    log: list[str] = []
    stores = (recorder("a", log), recorder("b", log), recorder("c", log))

    result = run_pending_migrations(None, workbench, identity, registry=stores)

    assert log == ["a", "b", "c"]
    assert result["status"] == STATUS_COMPLETE
    assert result["ran"] == ["a", "b", "c"]
    assert migration_state(workbench, identity)["completedStores"] == ["a", "b", "c"]


def test_a_second_open_re_runs_nothing(workbench, identity):
    log: list[str] = []
    stores = (recorder("a", log), recorder("b", log))
    run_pending_migrations(None, workbench, identity, registry=stores)

    result = run_pending_migrations(None, workbench, identity, registry=stores)

    assert log == ["a", "b"], "a completed store must not run twice"
    assert result["ran"] == []
    assert result["skipped"] == ["a", "b"]


def test_each_store_reports_itself_separately(workbench, identity):
    """Readers switch off legacy files per store, not per project."""
    log: list[str] = []
    stores = (recorder("a", log), recorder("b", log, fails=True), recorder("c", log))

    run_pending_migrations(None, workbench, identity, registry=stores)

    assert is_store_migrated(workbench, identity, "a") is True
    assert is_store_migrated(workbench, identity, "b") is False
    assert is_store_migrated(workbench, identity, "c") is False


# --------------------------------------------------------------------------
# Interruption and failure. This is what the module exists for.
# --------------------------------------------------------------------------

def test_an_interrupted_run_resumes_where_it_stopped(workbench, identity):
    """Kill the process after the third store; reopen; it finishes the rest.

    The scenario from #76's own acceptance criteria. A resumed run must
    neither redo the first three stores nor skip the remaining ones.
    """
    first_log: list[str] = []
    all_names = ["s1", "s2", "s3", "s4", "s5"]

    def boom(project, repo, ident):
        raise KeyboardInterrupt("process killed mid-migration")

    interrupted = tuple(
        recorder(n, first_log) if n in {"s1", "s2", "s3"} else StoreMigration(name=n, migrate=boom)
        for n in all_names
    )
    with pytest.raises(KeyboardInterrupt):
        run_pending_migrations(None, workbench, identity, registry=interrupted)

    assert first_log == ["s1", "s2", "s3"]
    assert migration_state(workbench, identity)["completedStores"] == ["s1", "s2", "s3"]
    assert migration_state(workbench, identity)["status"] == STATUS_IN_PROGRESS

    second_log: list[str] = []
    resumed = tuple(recorder(n, second_log) for n in all_names)
    result = run_pending_migrations(None, workbench, identity, registry=resumed)

    assert second_log == ["s4", "s5"], "already-migrated stores must not re-run"
    assert result["status"] == STATUS_COMPLETE
    assert migration_state(workbench, identity)["completedStores"] == all_names


def test_a_failing_store_does_not_raise_and_does_not_mark_itself_done(workbench, identity):
    """A failed migration must leave a usable project, not an unopenable one."""
    log: list[str] = []
    stores = (recorder("a", log), recorder("b", log, fails=True), recorder("c", log))

    result = run_pending_migrations(None, workbench, identity, registry=stores)

    assert result["status"] == STATUS_FAILED
    assert result["failed"] == "b"
    assert "exploded" in result["error"]
    assert log == ["a", "b"], "stores after the failure must not run"
    assert migration_state(workbench, identity)["completedStores"] == ["a"]


def test_a_failure_is_retried_on_the_next_open(workbench, identity):
    log: list[str] = []
    flaky = {"fail": True}

    def migrate(project, repo, ident):
        log.append("b")
        if flaky["fail"]:
            raise RuntimeError("transient")
        return 1

    stores = (recorder("a", log), StoreMigration(name="b", migrate=migrate))
    assert run_pending_migrations(None, workbench, identity, registry=stores)["status"] == STATUS_FAILED

    flaky["fail"] = False
    result = run_pending_migrations(None, workbench, identity, registry=stores)

    assert result["status"] == STATUS_COMPLETE
    assert log == ["a", "b", "b"], "only the failed store retries; 'a' stays done"


def test_the_recorded_error_names_the_store_that_failed(workbench, identity):
    stores = (recorder("only", [], fails=True),)
    run_pending_migrations(None, workbench, identity, registry=stores)

    row = workbench.get("project_state", natural_row_id("proj-1", "php", MIGRATION_STATE_KEY))
    payload = json.loads(row["payload_json"])
    assert payload["status"] == STATUS_FAILED
    assert payload["lastError"].startswith("only:")


# --------------------------------------------------------------------------
# Bookkeeping the rest of #76 relies on.
# --------------------------------------------------------------------------

def test_unreadable_state_is_treated_as_not_migrated(workbench, identity):
    """Corrupt progress must re-run an idempotent migration, not block the open."""
    workbench._write(
        "project_state",
        natural_row_id("proj-1", "php", MIGRATION_STATE_KEY),
        project_id="proj-1", book_id="php", payload={}, actor_id="user-1",
        device_id="dev-1", expected_revision=None, extra_columns={"key": MIGRATION_STATE_KEY},
    )
    with workbench._connect() as conn:
        conn.execute("UPDATE project_state SET payload_json='{not json'")
        conn.commit()

    state = migration_state(workbench, identity)
    assert state["completedStores"] == []
    assert state["status"] == STATUS_IN_PROGRESS


def test_progress_is_scoped_per_book(workbench):
    """Bridge imports one project per book; PHP finishing says nothing about TIT."""
    php = WorkbenchIdentity("proj-1", "php", "user-1", "dev-1")
    tit = WorkbenchIdentity("proj-1", "tit", "user-1", "dev-1")
    run_pending_migrations(None, workbench, php, registry=(recorder("a", []),))

    assert is_store_migrated(workbench, php, "a") is True
    assert is_store_migrated(workbench, tit, "a") is False


def test_every_migration_step_is_recorded_in_the_change_log(workbench, identity):
    """change_log is the audit trail; a silent migration would defeat it."""
    stores = (recorder("a", []), recorder("b", []))
    run_pending_migrations(None, workbench, identity, registry=stores)

    entries = workbench.change_log_entries("proj-1")
    assert [e["op"] for e in entries] == ["migration", "migration"]
    assert {e["actor_id"] for e in entries} == {"user-1"}
    assert {e["device_id"] for e in entries} == {"dev-1"}


def test_the_database_is_still_sound_after_a_migration(workbench, identity):
    run_pending_migrations(None, workbench, identity, registry=(recorder("a", []),))

    with workbench._connect() as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_natural_row_id_is_stable_and_does_not_collide():
    assert natural_row_id("a", "b") == natural_row_id("a", "b")
    assert natural_row_id("a", "bc") != natural_row_id("ab", "c")
    assert natural_row_id("a", None) != natural_row_id("a", "None")
    assert natural_row_id("a", "") != natural_row_id("a", None)


# --------------------------------------------------------------------------
# Identity (#76's slice of #78).
# --------------------------------------------------------------------------

def test_the_local_user_id_is_stable_across_calls(tmp_path):
    workspace = tmp_path / "workspace.sqlite3"
    first = WorkspaceRepository(workspace).get_or_create_local_user("Revant")
    second = WorkspaceRepository(workspace).get_or_create_local_user("Revant")

    assert first["userId"] == second["userId"]


def test_renaming_yourself_keeps_the_same_user_id(tmp_path):
    """The reason this exists: change_log rows are immutable.

    If actor_id were the display name, renaming in Settings would split one
    person's history into two sets of rows that can never be re-linked.
    """
    workspace = tmp_path / "workspace.sqlite3"
    before = WorkspaceRepository(workspace).get_or_create_local_user("Revant")
    after = WorkspaceRepository(workspace).get_or_create_local_user("R. Idikulay")

    assert after["userId"] == before["userId"]
    assert after["displayName"] == "R. Idikulay"


def test_a_blank_display_name_falls_back_rather_than_writing_an_empty_actor(tmp_path):
    user = WorkspaceRepository(tmp_path / "workspace.sqlite3").get_or_create_local_user("   ")
    assert user["displayName"] == "Unnamed Reviewer"
    assert user["userId"]


def test_device_id_and_user_id_are_independent(tmp_path):
    repo = WorkspaceRepository(tmp_path / "workspace.sqlite3")
    assert repo.get_or_create_device_id() != repo.get_or_create_local_user("Revant")["userId"]
