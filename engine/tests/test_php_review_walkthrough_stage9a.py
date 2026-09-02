"""Stage 9A - the Philippians 1:3-6 review walkthrough.

Exercises the review APIs against the reordered IRV Tamil passage, where the
Greek and Tamil verse orders differ:

    Greek 1:3 -> Tamil 1:6      Greek 1:5 -> Tamil 1:3
    Greek 1:4 -> Tamil 1:4      Greek 1:6 -> Tamil 1:5

The point is not that Bridge finds this mapping - Stage 6B's own golden
fixture already pins that - but that a *reviewer* can work the passage
without the reordering being misreported as missing translation.

This also exercises `scripts/seed_review_fixture.py`, so the fixture a human
opens in the desktop app is the same one asserted on here.
"""
from __future__ import annotations

from pathlib import Path
import sys

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent.parent / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from seed_review_fixture import build_project, seed  # noqa: E402

from tc_ai_bridge.passage_semantic_repository import FoundationConflict  # noqa: E402
from tc_ai_bridge.passage_semantic_runtime import PassageSemanticRuntime  # noqa: E402
from tc_ai_bridge.tc_project import TranslationCoreProject  # noqa: E402


EXPECTED_MAPPING = {
    "PHP 1:3": "PHP 1:6",
    "PHP 1:4": "PHP 1:4",
    "PHP 1:5": "PHP 1:3",
    "PHP 1:6": "PHP 1:5",
}


@pytest.fixture(scope="module")
def seeded(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict]:
    root = build_project(tmp_path_factory.mktemp("php-review") / "php-review-fixture")
    return root, seed(root)


@pytest.fixture()
def runtime(seeded: tuple[Path, dict]) -> PassageSemanticRuntime:
    root, summary = seeded
    # The seeder registers the fixture exactly as the desktop app does. Reopen
    # it with that persisted identity; a hardcoded id correctly trips the
    # companion database's cross-project merge protection.
    return PassageSemanticRuntime(TranslationCoreProject(root), summary["projectId"])


# --- The fixture itself -----------------------------------------------------

def test_the_seeder_produces_a_reordered_passage_with_findings(
    seeded: tuple[Path, dict],
) -> None:
    _, summary = seeded
    assert summary["reordered"] is True
    assert summary["crossVerse"] > 0
    assert summary["relationships"] > 0
    assert summary["queueTotal"] > 0, "a reviewer needs something to review"


def test_the_seeded_project_is_openable_as_a_real_project(
    seeded: tuple[Path, dict],
) -> None:
    root, _ = seeded
    project = TranslationCoreProject(root)
    assert project.manifest["target_language"]["id"] == "ta"
    assert (root / "php" / "1.json").is_file()
    assert (root / "php.usfm").is_file()


# --- Reordering must not read as missing translation -----------------------

def test_verse_reordering_is_discovered(runtime: PassageSemanticRuntime) -> None:
    run = runtime.repository.semantic_location_run(
        runtime.repository.qa_audit_run(
            next(iter(_qa_run_ids(runtime)))
        )["locationRunId"]
    )
    candidates = {item["id"]: item for item in run["candidates"]}
    source_units = {
        unit["id"]: unit
        for unit in runtime.source_semantic.build_range("1", "3", "1", "6")["units"]
    }
    votes: dict[str, dict[str, int]] = {}
    for relationship in run["relationships"]:
        selected = candidates.get(relationship.get("selectedCandidateId"))
        if not selected:
            continue
        target_reference = selected["targetDisplayedReferences"][0]
        for unit_id in relationship["sourceSemanticUnitIds"]:
            source_reference = source_units[unit_id]["canonicalReferences"][0]
            counts = votes.setdefault(source_reference, {})
            counts[target_reference] = counts.get(target_reference, 0) + 1

    winner = {
        reference: max(counts.items(), key=lambda item: item[1])[0]
        for reference, counts in votes.items()
    }
    assert winner == EXPECTED_MAPPING


def test_no_omission_is_raised_merely_because_a_verse_moved(
    runtime: PassageSemanticRuntime,
) -> None:
    """The core false-positive guard for a reordered passage.

    A source meaning realized in a different target verse is located, not
    missing. Every omission finding must therefore correspond to a source
    unit with no located realization at all - never to one that was simply
    found somewhere else in the passage.
    """
    located_source_units: set[str] = set()
    for run_id in _location_run_ids(runtime):
        run = runtime.repository.semantic_location_run(run_id)
        for relationship in run["relationships"]:
            if relationship.get("locationOutcome") == "LOCATED":
                located_source_units.update(relationship.get("sourceSemanticUnitIds", []))

    omissions = runtime.qa_review.get_queue(
        kinds=("POSSIBLE_OMISSION",), limit=200)["findings"]
    for finding in omissions:
        detail = runtime.qa_review.get_finding(finding["id"])
        for unit in detail["source"]:
            assert unit["id"] not in located_source_units, (
                f"{finding['kind']} raised for {unit.get('rawSurface')} "
                f"({finding['displayedReferences']}) even though it was located - "
                "reordering must not be reported as missing translation"
            )


def test_cross_verse_realization_is_visible_to_the_reviewer(
    runtime: PassageSemanticRuntime,
) -> None:
    cross_verse = []
    for run_id in _location_run_ids(runtime):
        run = runtime.repository.semantic_location_run(run_id)
        cross_verse.extend(
            relationship for relationship in run["relationships"]
            if "CROSS_VERSE" in (relationship.get("properties") or [])
        )
    assert cross_verse, "the reordered passage must expose cross-verse relationships"
    assert all(item.get("locationOutcome") == "LOCATED" for item in cross_verse), (
        "a cross-verse realization is located, not a failure to locate"
    )


# --- Location and meaning stay independently inspectable -------------------

def test_location_and_meaning_are_reported_separately(
    runtime: PassageSemanticRuntime,
) -> None:
    detail = _first_with_meaning(runtime)
    assert detail["location"], "the reviewer must be able to see where Bridge looked"
    assert detail["meaning"], "and, separately, how it judged the meaning there"
    location = detail["location"][0]["location"]
    assessment = detail["meaning"][0]["assessment"]
    assert location["locationOutcome"] in {
        "LOCATED", "AMBIGUOUS", "NOT_LOCATED", "SEARCH_INCOMPLETE", "UNSUPPORTED_ANALYSIS",
    }
    assert assessment["meaningStatus"] in {
        "PRESERVED", "PRESERVED_WITH_RESTRUCTURING", "PARTIAL", "OVERTRANSLATED",
        "UNDERTRANSLATED", "MEANING_SHIFT", "CONTRADICTED", "UNVERIFIABLE",
    }
    # Two records, two verdicts: neither field leaks into the other.
    assert "meaningStatus" not in location
    assert "locationOutcome" not in assessment


def test_completion_and_continuation_evidence_can_be_inspected(
    runtime: PassageSemanticRuntime,
) -> None:
    """PHP 1:6's "will carry it on to completion" is the passage's aspect claim."""
    dimensions: set[str] = set()
    for summary in runtime.qa_review.get_queue(limit=200)["findings"]:
        detail = runtime.qa_review.get_finding(summary["id"])
        for entry in detail["meaning"]:
            for component in entry["components"]:
                dimensions.add(str(component.get("coverageDimension")))
    assert dimensions, "meaning components must be inspectable per dimension"


def test_every_finding_exposes_its_evidence_layers(
    runtime: PassageSemanticRuntime,
) -> None:
    for summary in runtime.qa_review.get_queue(limit=200)["findings"]:
        detail = runtime.qa_review.get_finding(summary["id"])
        for section in ("finding", "source", "target", "location", "meaning",
                        "coverage", "resources", "history"):
            assert section in detail, f"{summary['id']} is missing {section}"


# --- The reviewer can actually decide --------------------------------------

def test_a_reviewer_can_accept_reject_and_defer(runtime: PassageSemanticRuntime) -> None:
    queue = runtime.qa_review.get_queue(dispositions=("UNRESOLVED",), limit=200)["findings"]
    assert len(queue) >= 3, "need three undecided findings to exercise three outcomes"

    accepted, rejected, deferred = queue[0], queue[1], queue[2]

    runtime.qa_review.decide_finding(
        accepted["id"], "ACCEPTABLE_TRANSLATION", expected_revision=accepted["revision"],
        note="Tamil reorders the clause; the meaning is intact.")
    runtime.qa_review.decide_finding(
        rejected["id"], "FALSE_POSITIVE", expected_revision=rejected["revision"],
        note="Bridge should not have raised this.")
    runtime.qa_review.decide_finding(
        deferred["id"], "NEEDS_DISCUSSION", expected_revision=deferred["revision"],
        note="Ask the translation team.")

    assert runtime.repository.qa_finding(accepted["id"])["qaDisposition"] == "ACCEPTABLE_TRANSLATION"
    assert runtime.repository.qa_finding(rejected["id"])["reviewStatus"] == "HUMAN_REJECTED"
    assert runtime.repository.qa_finding(deferred["id"])["reviewStatus"] == "NEEDS_DISCUSSION"

    # Each decision carries its reason into structured history, not Scripture.
    for finding in (accepted, rejected, deferred):
        history = runtime.repository.review_records("QA_FINDING", finding["id"])
        assert history and history[-1]["note"]


def test_deciding_twice_against_a_stale_revision_is_refused(
    runtime: PassageSemanticRuntime,
) -> None:
    finding = runtime.qa_review.get_queue(
        dispositions=("UNRESOLVED",), limit=200)["findings"][-1]
    runtime.qa_review.decide_finding(
        finding["id"], "CONFIRMED_TRANSLATION_ERROR", expected_revision=finding["revision"])
    with pytest.raises(FoundationConflict):
        runtime.qa_review.decide_finding(
            finding["id"], "FALSE_POSITIVE", expected_revision=finding["revision"])


def test_reviewing_the_passage_never_changes_its_scripture(
    seeded: tuple[Path, dict], runtime: PassageSemanticRuntime,
) -> None:
    """Stage 9A classifies; it must not touch the text."""
    root, _ = seeded
    chapter = root / "php" / "1.json"
    usfm = root / "php.usfm"
    before = (chapter.read_text(encoding="utf-8"), usfm.read_text(encoding="utf-8"))

    for summary in runtime.qa_review.get_queue(limit=5)["findings"]:
        runtime.qa_review.get_finding(summary["id"])
        runtime.qa_review.add_note("QA_FINDING", summary["id"], "inspected")

    assert (chapter.read_text(encoding="utf-8"), usfm.read_text(encoding="utf-8")) == before


# --- helpers ----------------------------------------------------------------

def _qa_run_ids(runtime: PassageSemanticRuntime) -> list[str]:
    with runtime.repository._connect() as conn:
        return [row[0] for row in conn.execute("SELECT id FROM qa_audit_runs ORDER BY created_at")]


def _location_run_ids(runtime: PassageSemanticRuntime) -> list[str]:
    with runtime.repository._connect() as conn:
        return [row[0] for row in conn.execute("SELECT id FROM semantic_location_runs")]


def _first_with_meaning(runtime: PassageSemanticRuntime) -> dict:
    for summary in runtime.qa_review.get_queue(limit=200)["findings"]:
        detail = runtime.qa_review.get_finding(summary["id"])
        if detail["meaning"] and detail["location"]:
            return detail
    raise AssertionError("the fixture produced no located, assessed finding")
