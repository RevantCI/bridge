"""Stage 9A.0 — review-queue storage, schema v8 migration, reviewer notes.

These cover the data layer the human review queue is built on.  They do not
exercise any review API or UI: Stage 9A.0 only makes the storage able to
answer queue queries deterministically.
"""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3

import pytest

import tc_ai_bridge.passage_semantic_repository as repository_module
from tc_ai_bridge.passage_semantic_models import PolicyBinding, QaDisposition
from tc_ai_bridge.passage_semantic_repository import (
    DATABASE_SCHEMA_VERSION,
    FoundationConflict,
    FoundationRepository,
    FoundationValidationError,
)


SEVERITY_RANKS = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}


def _insert(repo: FoundationRepository, finding_id: str, *, book: str = "PHP",
            chapter: int = 1, verse: int = 3, kind: str = "POSSIBLE_OMISSION",
            severity: str = "MEDIUM", direction: str = "SOURCE_COVERAGE",
            disposition: str = "UNRESOLVED", review: str = "AI_PROPOSED",
            lifecycle: str = "ACTIVE", project_id: str = "proj",
            source_references: tuple[str, ...] = (),
            target_references: tuple[str, ...] = ()) -> None:
    """Insert a queue row directly.

    Stage 8 owns finding construction; these tests only need rows whose queue
    columns are populated, so they bypass save_qa_finding's referential checks.
    """
    policy_id = repo._ensure_policy(PolicyBinding.foundation_v1())
    with repo._connect() as conn:
        conn.execute(
            "INSERT INTO qa_findings(id,project_id,qa_disposition,policy_binding_id,"
            "review_status,lifecycle_status,revision,payload_json,book,kind,direction,"
            "severity,severity_rank,sort_chapter,sort_verse,displayed_reference) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (finding_id, project_id, disposition, policy_id, review, lifecycle, 1,
             json.dumps({"id": finding_id, "book": book, "kind": kind,
                         "direction": direction}), book, kind,
             direction, severity, SEVERITY_RANKS.get(severity, 99), chapter, verse,
             f"{book} {chapter}:{verse}"),
        )
        for side, references in (("SOURCE", source_references), ("TARGET", target_references)):
            conn.executemany(
                "INSERT INTO qa_finding_scope_references"
                "(finding_id,side,canonical_reference) VALUES(?,?,?)",
                ((finding_id, side, reference) for reference in references),
            )
        conn.commit()


@pytest.fixture()
def repo(tmp_path: Path) -> FoundationRepository:
    return FoundationRepository(tmp_path / "companion.sqlite3")


# --- Schema v8 queue indexes retained through later migrations -------------

def test_schema_v8_adds_queue_columns_and_indexes(repo: FoundationRepository) -> None:
    assert repo.schema_version() == DATABASE_SCHEMA_VERSION == 13
    with repo._connect() as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(qa_findings)")}
        indexes = {row[1] for row in conn.execute("PRAGMA index_list(qa_findings)")}
    assert {"book", "kind", "direction", "severity", "severity_rank",
            "sort_chapter", "sort_verse", "displayed_reference"} <= columns
    assert {"ix_qa_findings_queue", "ix_qa_findings_severity",
            "ix_qa_findings_filter"} <= indexes


def test_v7_database_upgrades_and_backfills_queue_columns(tmp_path: Path) -> None:
    """An existing v7 companion DB must upgrade without losing findings."""
    database = tmp_path / "legacy.sqlite3"
    conn = sqlite3.connect(str(database))
    conn.executescript(
        "CREATE TABLE IF NOT EXISTS schema_migrations"
        "(version INTEGER PRIMARY KEY, schema_id TEXT NOT NULL, applied_at TEXT NOT NULL);"
    )
    migrations = [getattr(repository_module, f"_MIGRATION_V{version}") for version in range(1, 8)]
    for version, script in enumerate(migrations, start=1):
        conn.executescript(script)
        conn.execute(
            "INSERT INTO schema_migrations VALUES(?,?,?)",
            (version, repository_module.SCHEMA_ID, "2026-09-02T00:00:00Z"),
        )
    conn.execute("INSERT INTO policy_bindings VALUES('pb','c-v1','cal-v1','audit-v1')")
    conn.execute(
        "INSERT INTO qa_findings VALUES(?,?,?,?,?,?,?,?)",
        ("legacy-1", "proj", "UNRESOLVED", "pb", "AI_PROPOSED", "ACTIVE", 1,
         json.dumps({"id": "legacy-1", "book": "PHP", "kind": "QUANTITY_PROBLEM",
                     "direction": "SOURCE_COVERAGE", "severity": "HIGH"})),
    )
    conn.commit()
    conn.close()

    upgraded = FoundationRepository(database)
    assert upgraded.schema_version() == DATABASE_SCHEMA_VERSION == 13
    with upgraded._connect() as conn:
        row = conn.execute(
            "SELECT book,kind,direction,severity,severity_rank FROM qa_findings WHERE id='legacy-1'"
        ).fetchone()
    assert (row["book"], row["kind"], row["severity"], row["severity_rank"]) == (
        "PHP", "QUANTITY_PROBLEM", "HIGH", 1)
    assert [f["id"] for f in upgraded.query_qa_findings("proj")["findings"]] == ["legacy-1"]
    assert list((database.parent / "backups").glob("pre-schema-v8-*")), (
        "migrating an existing database must leave a pre-migration backup")


def test_v9_database_upgrades_and_backfills_canonical_finding_scope(
    tmp_path: Path,
) -> None:
    database = tmp_path / "legacy-v9.sqlite3"
    conn = sqlite3.connect(str(database))
    conn.executescript(
        "CREATE TABLE IF NOT EXISTS schema_migrations"
        "(version INTEGER PRIMARY KEY, schema_id TEXT NOT NULL, applied_at TEXT NOT NULL);"
    )
    for version in range(1, 10):
        conn.executescript(getattr(repository_module, f"_MIGRATION_V{version}"))
        conn.execute(
            "INSERT INTO schema_migrations VALUES(?,?,?)",
            (version, repository_module.SCHEMA_ID, "2026-09-03T00:00:00Z"),
        )
    conn.execute("INSERT INTO policy_bindings VALUES('pb','c-v1','cal-v1','audit-v1')")
    unit_payload = json.dumps({"id": "source-3", "canonicalReferences": ["PHP 1:3"]})
    conn.execute(
        "INSERT INTO semantic_units VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("source-3", "proj", "SOURCE", "LEXICAL", "source-3", "ELIGIBLE",
         "REQUIRED", "PRIMARY", "LEXICAL_CONTENT", "semantic-source-3",
         "AI_PROPOSED", "ACTIVE", 1, unit_payload),
    )
    finding_payload = json.dumps({
        "id": "legacy-cross-verse", "book": "PHP", "kind": "POSSIBLE_OMISSION",
        "direction": "SOURCE_COVERAGE", "severity": "MEDIUM",
        "sourceSemanticUnitIds": ["source-3"], "targetSemanticUnitIds": [],
    })
    conn.execute(
        "INSERT INTO qa_findings(id,project_id,qa_disposition,policy_binding_id,"
        "review_status,lifecycle_status,revision,payload_json,book,kind,direction,"
        "severity,severity_rank,sort_chapter,sort_verse,displayed_reference) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("legacy-cross-verse", "proj", "UNRESOLVED", "pb", "AI_PROPOSED", "ACTIVE",
         1, finding_payload, "PHP", "POSSIBLE_OMISSION", "SOURCE_COVERAGE", "MEDIUM",
         2, 1, 6, "PHP 1:6"),
    )
    conn.commit()
    conn.close()

    upgraded = FoundationRepository(database)
    scoped = upgraded.query_qa_findings(
        "proj", canonical_references=("PHP 1:3",),
    )
    assert [finding["id"] for finding in scoped["findings"]] == ["legacy-cross-verse"]
    assert list((database.parent / "backups").glob("pre-schema-v10-*"))


# --- Queue ordering ---------------------------------------------------------

def test_canonical_order_follows_chapter_and_verse(repo: FoundationRepository) -> None:
    _insert(repo, "f-late", chapter=1, verse=6, severity="LOW")
    _insert(repo, "f-early", chapter=1, verse=3, severity="CRITICAL")
    _insert(repo, "f-mid", chapter=1, verse=4, severity="HIGH")
    result = repo.query_qa_findings("proj", order="CANONICAL")
    assert [f["id"] for f in result["findings"]] == ["f-early", "f-mid", "f-late"]
    assert result["totalCount"] == 3


def test_severity_order_is_review_priority_not_alphabetical(repo: FoundationRepository) -> None:
    _insert(repo, "f-low", verse=3, severity="LOW")
    _insert(repo, "f-critical", verse=4, severity="CRITICAL")
    _insert(repo, "f-info", verse=5, severity="INFO")
    _insert(repo, "f-high", verse=6, severity="HIGH")
    ordered = [f["id"] for f in repo.query_qa_findings("proj", order="SEVERITY")["findings"]]
    assert ordered == ["f-critical", "f-high", "f-low", "f-info"]


def test_order_is_deterministic_for_equal_sort_keys(repo: FoundationRepository) -> None:
    """Equal-priority findings must never swap places between identical calls."""
    for suffix in "dcba":
        _insert(repo, f"f-{suffix}", chapter=1, verse=3, severity="HIGH")
    first = [f["id"] for f in repo.query_qa_findings("proj")["findings"]]
    second = [f["id"] for f in repo.query_qa_findings("proj")["findings"]]
    assert first == second == ["f-a", "f-b", "f-c", "f-d"]


def test_unknown_order_is_rejected(repo: FoundationRepository) -> None:
    with pytest.raises(FoundationValidationError):
        repo.query_qa_findings("proj", order="BY_VIBES")


# --- Queue filtering --------------------------------------------------------

def test_filters_narrow_the_queue(repo: FoundationRepository) -> None:
    _insert(repo, "f-omission", verse=3, kind="POSSIBLE_OMISSION")
    _insert(repo, "f-addition", verse=4, kind="POSSIBLE_ADDITION", direction="TARGET_SUPPORT")
    _insert(repo, "f-stale", verse=5, kind="POSSIBLE_OMISSION", lifecycle="STALE")
    _insert(repo, "f-decided", verse=6, kind="POSSIBLE_OMISSION",
            disposition="FALSE_POSITIVE", review="HUMAN_APPROVED")

    by_kind = repo.query_qa_findings("proj", kinds=("POSSIBLE_ADDITION",))
    assert [f["id"] for f in by_kind["findings"]] == ["f-addition"]

    active = repo.query_qa_findings("proj", lifecycle_statuses=("ACTIVE",))
    assert "f-stale" not in [f["id"] for f in active["findings"]]

    unresolved = repo.query_qa_findings("proj", dispositions=("UNRESOLVED",))
    assert "f-decided" not in [f["id"] for f in unresolved["findings"]]

    stale_only = repo.query_qa_findings("proj", lifecycle_statuses=("STALE",))
    assert [f["id"] for f in stale_only["findings"]] == ["f-stale"]


def test_book_and_chapter_filters(repo: FoundationRepository) -> None:
    _insert(repo, "php-1", book="PHP", chapter=1, verse=3)
    _insert(repo, "php-2", book="PHP", chapter=2, verse=1)
    _insert(repo, "tit-1", book="TIT", chapter=1, verse=1)
    assert [f["id"] for f in repo.query_qa_findings("proj", book="TIT")["findings"]] == ["tit-1"]
    assert [f["id"] for f in repo.query_qa_findings(
        "proj", book="PHP", chapter=2)["findings"]] == ["php-2"]


def test_queue_is_scoped_to_its_project(repo: FoundationRepository) -> None:
    _insert(repo, "mine", project_id="proj")
    _insert(repo, "theirs", project_id="other")
    assert [f["id"] for f in repo.query_qa_findings("proj")["findings"]] == ["mine"]


def test_canonical_scope_keeps_previous_findings_persisted_but_out_of_current_queue(
    repo: FoundationRepository,
) -> None:
    _insert(repo, "previous-3", verse=3, source_references=("PHP 1:3",))
    _insert(repo, "previous-6", verse=6, source_references=("PHP 1:6",))
    _insert(repo, "current-1", verse=1, source_references=("PHP 1:1",))

    current = repo.query_qa_findings("proj", canonical_references=("PHP 1:1",))
    assert [finding["id"] for finding in current["findings"]] == ["current-1"]
    assert current["totalCount"] == 1

    # Scope filtering is a view, never deletion: switching back restores both rows.
    previous = repo.query_qa_findings(
        "proj", canonical_references=("PHP 1:3", "PHP 1:4", "PHP 1:5", "PHP 1:6"),
    )
    assert [finding["id"] for finding in previous["findings"]] == [
        "previous-3", "previous-6",
    ]
    assert repo.query_qa_findings("proj")["totalCount"] == 3


def test_canonical_scope_uses_source_units_for_cross_verse_source_coverage(
    repo: FoundationRepository,
) -> None:
    _insert(
        repo, "greek-1-3-to-tamil-1-6", verse=6, direction="SOURCE_COVERAGE",
        source_references=("PHP 1:3",), target_references=("PHP 1:6",),
    )
    assert [finding["id"] for finding in repo.query_qa_findings(
        "proj", canonical_references=("PHP 1:3",),
    )["findings"]] == ["greek-1-3-to-tamil-1-6"]
    assert repo.query_qa_findings(
        "proj", canonical_references=("PHP 1:6",),
    )["findings"] == []


def test_canonical_scope_uses_target_units_for_target_support(
    repo: FoundationRepository,
) -> None:
    _insert(
        repo, "target-addition", verse=6, direction="TARGET_SUPPORT",
        source_references=("PHP 1:3",), target_references=("PHP 1:6",),
    )
    assert repo.query_qa_findings(
        "proj", canonical_references=("PHP 1:3",),
    )["findings"] == []
    assert [finding["id"] for finding in repo.query_qa_findings(
        "proj", canonical_references=("PHP 1:6",),
    )["findings"]] == ["target-addition"]


def test_scoped_pagination_and_count_use_the_same_result_set(
    repo: FoundationRepository,
) -> None:
    for verse in range(1, 7):
        _insert(
            repo, f"in-scope-{verse}", verse=verse,
            source_references=(f"PHP 1:{verse}",),
        )
    for verse in range(7, 10):
        _insert(
            repo, f"outside-{verse}", verse=verse,
            source_references=(f"PHP 1:{verse}",),
        )
    selected = tuple(f"PHP 1:{verse}" for verse in range(1, 7))
    first = repo.query_qa_findings(
        "proj", canonical_references=selected, limit=2,
    )
    second = repo.query_qa_findings(
        "proj", canonical_references=selected, limit=2, cursor=first["nextCursor"],
    )
    assert first["totalCount"] == second["totalCount"] == 6
    assert all(finding["id"].startswith("in-scope-") for finding in [
        *first["findings"], *second["findings"],
    ])


def test_book_scope_is_not_limited_by_sqlite_parameter_count(
    repo: FoundationRepository,
) -> None:
    references = tuple(f"PHP 1:{verse}" for verse in range(1, 1201))
    _insert(repo, "late-book-finding", verse=1200, source_references=(references[-1],))
    page = repo.query_qa_findings("proj", canonical_references=references)
    assert [finding["id"] for finding in page["findings"]] == ["late-book-finding"]
    assert page["totalCount"] == 1


def test_cross_chapter_scope_filters_by_canonical_membership(
    repo: FoundationRepository,
) -> None:
    _insert(repo, "chapter-one", chapter=1, verse=6, source_references=("PHP 1:6",))
    _insert(repo, "chapter-two", chapter=2, verse=1, source_references=("PHP 2:1",))
    _insert(repo, "outside", chapter=2, verse=2, source_references=("PHP 2:2",))
    page = repo.query_qa_findings(
        "proj", canonical_references=("PHP 1:6", "PHP 2:1"),
    )
    assert [finding["id"] for finding in page["findings"]] == [
        "chapter-one", "chapter-two",
    ]


def test_scope_switch_preserves_human_decision_note_and_history(
    repo: FoundationRepository,
) -> None:
    _insert(repo, "reviewed-3", verse=3, source_references=("PHP 1:3",))
    _insert(repo, "current-1", verse=1, source_references=("PHP 1:1",))
    repo.update_qa_disposition(
        "reviewed-3", QaDisposition.ACCEPTABLE_TRANSLATION, expected_revision=1,
        reviewer="Reviewer", note="Tamil reordered the meaning naturally.",
    )
    assert [finding["id"] for finding in repo.query_qa_findings(
        "proj", canonical_references=("PHP 1:1",),
    )["findings"]] == ["current-1"]
    restored = repo.query_qa_findings(
        "proj", canonical_references=("PHP 1:3",),
    )["findings"]
    assert restored[0]["qaDisposition"] == "ACCEPTABLE_TRANSLATION"
    assert repo.review_records("QA_FINDING", "reviewed-3")[0]["note"] == (
        "Tamil reordered the meaning naturally."
    )


# --- Keyset pagination ------------------------------------------------------

def test_pagination_covers_every_finding_exactly_once(repo: FoundationRepository) -> None:
    for verse in range(1, 12):
        _insert(repo, f"f-{verse:02d}", verse=verse)
    seen: list[str] = []
    cursor = ""
    for _ in range(10):
        page = repo.query_qa_findings("proj", limit=4, cursor=cursor)
        seen.extend(f["id"] for f in page["findings"])
        cursor = page["nextCursor"]
        if not cursor:
            break
    assert seen == sorted(seen)
    assert len(seen) == len(set(seen)) == 11
    assert cursor == ""


def test_final_page_reports_no_cursor(repo: FoundationRepository) -> None:
    _insert(repo, "only", verse=3)
    page = repo.query_qa_findings("proj", limit=4)
    assert [f["id"] for f in page["findings"]] == ["only"]
    assert page["nextCursor"] == ""


def test_total_count_is_the_filtered_total_not_the_page_size(repo: FoundationRepository) -> None:
    for verse in range(1, 8):
        _insert(repo, f"f-{verse}", verse=verse)
    page = repo.query_qa_findings("proj", limit=2)
    assert len(page["findings"]) == 2
    assert page["totalCount"] == 7


def test_malformed_cursor_is_rejected(repo: FoundationRepository) -> None:
    _insert(repo, "f-1")
    with pytest.raises(FoundationValidationError):
        repo.query_qa_findings("proj", cursor="not-base64!!")


def test_cursor_from_a_different_ordering_is_rejected(repo: FoundationRepository) -> None:
    """A CANONICAL cursor has fewer key columns than a SEVERITY one."""
    for verse in (3, 4, 5):
        _insert(repo, f"f-{verse}", verse=verse)
    canonical = repo.query_qa_findings("proj", limit=1)["nextCursor"]
    with pytest.raises(FoundationValidationError):
        repo.query_qa_findings("proj", order="SEVERITY", cursor=canonical)


# --- Reviewer notes and concurrency ----------------------------------------

def test_reviewer_note_is_persisted_on_the_review_record(repo: FoundationRepository) -> None:
    repo.create_qa_finding("finding-1", "proj")
    repo.update_qa_disposition(
        "finding-1", QaDisposition.ACCEPTABLE_TRANSLATION, expected_revision=1,
        reviewer="human", note="Tamil restructures the clause; meaning is intact.",
    )
    history = repo.review_records("QA_FINDING", "finding-1")
    assert len(history) == 1
    assert history[0]["note"] == "Tamil restructures the clause; meaning is intact."
    assert history[0]["previousQaDisposition"] == "UNRESOLVED"
    assert history[0]["newQaDisposition"] == "ACCEPTABLE_TRANSLATION"
    assert history[0]["actorType"] == "HUMAN"


def test_note_defaults_to_empty_and_history_still_records_the_transition(
    repo: FoundationRepository,
) -> None:
    repo.create_qa_finding("finding-2", "proj")
    repo.update_qa_disposition(
        "finding-2", QaDisposition.NEEDS_DISCUSSION, expected_revision=1, reviewer="human")
    history = repo.review_records("QA_FINDING", "finding-2")
    assert history[0]["note"] == ""
    assert history[0]["newReviewStatus"] == "NEEDS_DISCUSSION"


def test_stale_revision_is_rejected_rather_than_overwriting(repo: FoundationRepository) -> None:
    """Human review must never be last-write-wins."""
    repo.create_qa_finding("finding-3", "proj")
    repo.update_qa_disposition(
        "finding-3", QaDisposition.CONFIRMED_TRANSLATION_ERROR, expected_revision=1,
        reviewer="human", note="first")
    with pytest.raises(FoundationConflict):
        repo.update_qa_disposition(
            "finding-3", QaDisposition.FALSE_POSITIVE, expected_revision=1,
            reviewer="human", note="stale write")
    assert repo.qa_finding("finding-3")["qaDisposition"] == "CONFIRMED_TRANSLATION_ERROR"
    assert len(repo.review_records("QA_FINDING", "finding-3")) == 1


# --- Recovery check must know every dependency type the engine writes -------

def test_recovery_check_knows_every_dependency_type_the_engine_registers(
    repo: FoundationRepository,
) -> None:
    """A dependency type this check does not recognise makes the DB read-only.

    Stage 8 registered QA_RUN edges without teaching recovery_check about
    them, so any project that had run a QA audit failed recovery on its next
    open, set read_only, and then threw "attempt to write a readonly
    database" on the next write -- which is every project open, since binding
    project metadata is a write. Asserting the two maps agree stops the next
    dependency type from doing the same.
    """
    with repo._connect() as conn:
        conn.execute(
            "INSERT INTO record_dependencies VALUES(?,?,?,?)",
            ("QA_RUN", "qa-run-1", "MEANING_RUN", "meaning-run-1"),
        )
        conn.commit()
    problems = repo.recovery_check()["problems"]
    assert not any("unknown-record-dependency-type" in problem for problem in problems), problems


@pytest.mark.parametrize("record_type", [
    "PASSAGE_RECORD", "EVIDENCE_RECORD", "SEMANTIC_RELATIONSHIP", "COVERAGE_ACCOUNT",
    "QA_FINDING", "LEXICAL_SOLUTION", "CORRECTION_PROPOSAL", "EXPORTABILITY",
    "SOURCE_INVENTORY", "TARGET_INVENTORY", "LOCATION_RUN", "LOCATION_RELATIONSHIP",
    "MEANING_RUN", "MEANING_ASSESSMENT", "QA_RUN",
])
def test_every_dependency_type_the_engine_writes_is_recognised(
    repo: FoundationRepository, record_type: str,
) -> None:
    """Only the *type* is under test here.

    A fabricated record id legitimately trips the dangling-reference check,
    so this asserts the narrower thing that actually matters: no type the
    engine writes is reported as unknown.
    """
    with repo._connect() as conn:
        conn.execute(
            "INSERT INTO record_dependencies VALUES(?,?,?,?)",
            (record_type, f"{record_type.lower()}-1", "TARGET_REFERENCE", "ref-1"),
        )
        conn.commit()
    problems = repo.recovery_check()["problems"]
    assert not any(problem.startswith("unknown-record-dependency-type") for problem in problems), (
        f"{record_type} is written by the engine but not recognised by recovery_check"
    )


def test_an_unknown_dependency_type_is_still_reported(repo: FoundationRepository) -> None:
    """The check must keep catching genuinely unknown types."""
    with repo._connect() as conn:
        conn.execute(
            "INSERT INTO record_dependencies VALUES(?,?,?,?)",
            ("NOT_A_REAL_TYPE", "x-1", "TARGET_REFERENCE", "ref-1"),
        )
        conn.commit()
    check = repo.recovery_check()
    assert check["ok"] is False
    assert any("NOT_A_REAL_TYPE" in problem for problem in check["problems"])
