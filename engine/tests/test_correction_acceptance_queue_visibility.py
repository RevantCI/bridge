"""Stage 9B.4 installed-acceptance queue-visibility regression.

The 0.9.4 installed candidate opened Case A correctly and still showed
"Showing 0 of 0 possible issues" in Alignment Review -> QA, even with
"Stale only" selected, while the read-only inspector proved the finding was
present and STALE in both the seeded folder and Bridge's managed copy.

The controlled A/B fixtures wrote the human-decided finding columns with raw
SQL on top of ``create_qa_finding``'s minimal row.  That left every schema-v8
Stage 9A queue index column at its empty create-time default (``book=''``,
``severity=''``, ``sort_chapter=0``, ``sort_verse=0``, ``displayed_reference=''``)
and wrote no ``qa_finding_scope_references`` rows at all, so
``query_qa_findings()`` could never return the finding under a real UI scope
even though ``qa_finding()``, the correction services and the inspector all
read it fine.

These tests drive the real Stage 9A ``qaReview.getQueue`` API through
``BridgeEngine``/``project.open`` -- never SQLite directly -- at the effective
UI scope the acceptance script uses (PHP 1:3-PHP 1:6, "Stale only"), against
both the seeded source folder and the authoritative managed application copy.
Run analysis is deliberately never invoked: A and B are controlled fixtures
that must be visible immediately after opening.
"""
from __future__ import annotations

from pathlib import Path
import shutil
import sys
from typing import Any

import pytest

from bridge_service import BridgeEngine
from greek_room_engine.protocol import EngineRequest
from tc_ai_bridge.secret_store import AppSettings


SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import seed_correction_acceptance as seeder  # noqa: E402


# The passage the acceptance script has selected when it opens Alignment
# Review -> QA: the source obligation in PHP 1:3 through its target
# realization in PHP 1:6.
UI_SCOPE = ["PHP 1:3", "PHP 1:4", "PHP 1:5", "PHP 1:6"]

CASES = {
    "A": ("A-passed-controlled", seeder.seed_case_a),
    "B": ("B-failed-controlled", seeder.seed_case_b),
}


def _call(engine: BridgeEngine, method: str, params: dict) -> dict:
    response = engine.handle_request(
        EngineRequest(id="stage9b4-queue", method=method, params=params)
    ).to_dict()
    assert response["success"] is True, response
    return response["result"]


def _seed(case: str, destination: Path) -> tuple[Path, dict[str, Any]]:
    name, seed = CASES[case]
    root = destination / name
    return root, seed(root)


def _engine(app_data: Path) -> BridgeEngine:
    return BridgeEngine(settings=AppSettings(path=app_data / "settings.json"))


def _assert_queue_visible(
    engine: BridgeEngine, summary: dict[str, Any], where: str,
) -> None:
    """The controlled fixture must be in the stale queue at the UI scope."""
    queue = _call(engine, "qaReview.getQueue", {
        "canonicalReferences": UI_SCOPE, "lifecycleStatuses": ["STALE"],
    })
    ids = [item["id"] for item in queue["findings"]]
    assert queue["totalCount"] >= 1, f"{where}: empty stale queue: {queue}"
    assert summary["findingId"] in ids, f"{where}: {ids}"

    finding = next(
        item for item in queue["findings"] if item["id"] == summary["findingId"]
    )
    assert finding["qaDisposition"] == "CONFIRMED_TRANSLATION_ERROR"
    assert finding["reviewStatus"] == "HUMAN_APPROVED"
    assert finding["lifecycleStatus"] == "STALE"

    # The correction detail behind the queue row must still open.
    detail = _call(engine, "qaReview.getFinding", {
        "findingId": summary["findingId"],
    })
    assert detail["finding"]["id"] == summary["findingId"]
    corrections = _call(engine, "correction.listForFinding", {
        "findingId": summary["findingId"],
    })
    proposals = [item["id"] for item in corrections["proposals"]]
    applications = [item["applicationId"] for item in corrections["applications"]]
    assert summary["proposalId"] in proposals, f"{where}: {proposals}"
    assert summary["applicationId"] in applications, f"{where}: {applications}"


@pytest.mark.parametrize("case", ["A", "B"])
def test_seeded_case_is_visible_in_the_stale_queue_after_open(
    case: str, tmp_path: Path,
) -> None:
    """Seed into a fresh folder, open it, and read the real Stage 9A queue."""
    root, summary = _seed(case, tmp_path / "seeded")
    engine = _engine(tmp_path / "Bridge" / "data")
    opened = _call(engine, "project.open", {"path": str(root)})
    assert Path(opened["path"]).resolve() == root.resolve()
    _assert_queue_visible(engine, summary, f"case {case} source folder")


@pytest.mark.parametrize("case", ["A", "B"])
def test_managed_application_copy_is_visible_in_the_stale_queue(
    case: str, tmp_path: Path,
) -> None:
    """The authoritative copy under the app's own projects root, not the source.

    Bridge imports a selected project into ``<app data>/projects``, and the
    installed report was read from that copy, so the regression has to assert
    the managed database rather than only the seeded folder.
    """
    source, summary = _seed(case, tmp_path / "seeded")
    app_data = tmp_path / "Bridge" / "data"
    managed = app_data / "projects" / source.name
    managed.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, managed)

    engine = _engine(app_data)
    opened = _call(engine, "project.open", {"path": str(managed)})
    assert Path(opened["path"]).resolve() == managed.resolve()
    entry = engine.project_registry.get(summary["projectId"])
    assert entry is not None and entry["managed"] is True, entry
    _assert_queue_visible(engine, summary, f"case {case} managed copy")


@pytest.mark.parametrize("case", ["A", "B"])
def test_seeded_finding_carries_every_stage_9a_queue_index_column(
    case: str, tmp_path: Path,
) -> None:
    """Guard the actual defect: the denormalized queue index, not the payload.

    ``qa_finding()`` read the fixture correctly the whole time.  Only the
    denormalized columns and the scope-reference rows were missing, so assert
    them explicitly -- a payload-only regression would otherwise pass.
    """
    root, summary = _seed(case, tmp_path / "seeded")
    engine = _engine(tmp_path / "Bridge" / "data")
    _call(engine, "project.open", {"path": str(root)})
    repository = engine.passage_semantic_runtime.repository
    with repository._connect() as conn:
        row = dict(conn.execute(
            "SELECT book,kind,direction,severity,severity_rank,sort_chapter,"
            "sort_verse,displayed_reference FROM qa_findings WHERE id=?",
            (summary["findingId"],),
        ).fetchone())
        scope = {
            (item["side"], item["canonical_reference"])
            for item in conn.execute(
                "SELECT side,canonical_reference FROM qa_finding_scope_references "
                "WHERE finding_id=?", (summary["findingId"],),
            )
        }
    assert row["book"] == "PHP"
    assert row["kind"] and row["direction"]
    assert row["severity"] and row["severity_rank"] != 99
    assert (row["sort_chapter"], row["sort_verse"]) == (1, 6)
    assert row["displayed_reference"] == "PHP 1:6"
    # SOURCE_COVERAGE findings join the queue on their source unit's canonical
    # reference, which is why the PHP 1:3 obligation shows in a 1:3-1:6 scope.
    assert ("SOURCE", "PHP 1:3") in scope, scope
