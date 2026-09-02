"""Stage 9A.1 — the review service over real Stage 6B/7/8 output.

Exercises human review against genuinely produced analysis rather than
hand-built rows: the queue, layered evidence, the four reviewer dispositions,
mapping and meaning review, notes, concurrency, promotion, and what a re-run
is allowed to do to a decision already recorded.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unicodedata

import pytest

from tc_ai_bridge.meaning_analysis import MeaningAnalysisEngine
from tc_ai_bridge.passage_semantic_repository import (
    FoundationConflict,
    FoundationValidationError,
)
from tc_ai_bridge.passage_semantic_runtime import PassageSemanticRuntime
from tc_ai_bridge.qa_audit import QaAuditEngine
from tc_ai_bridge.semantic_location import SemanticEmbeddingProvider, SemanticLocationEngine
from tc_ai_bridge.tc_project import TranslationCoreProject


TAMIL_PHP = {
    "3": "நற்செய்தி உங்களுக்கு அறிவிக்கப்பட்ட நாள் முதல் இதுவரைக்கும் நீங்கள் எங்களோடு ஊழியத்தில் ஐக்கியப்பட்டிருப்பதால்,",
    "4": "நான் பண்ணுகிற ஒவ்வொரு விண்ணப்பத்திலும் உங்கள் அனைவருக்காகவும் எப்பொழுதும் மகிழ்ச்சியோடு ஜெபம் செய்து,",
    "5": "உங்களில் நல்ல செயலைத் தொடங்கினவர் அதை இயேசு கிறிஸ்துவின் நாள் வரை நடத்தி வருவார் என்று நம்பி,",
    "6": "நான் உங்களை நினைக்கும் போதெல்லாம் என் தேவனை ஸ்தோத்திரிக்கிறேன்.",
}

PHP_PAIRS = [
    ("εὐχαριστέω", "ஸ்தோத்திரிக்கிறேன்"), ("θεός", "தேவனை"), ("μνεία", "நினைக்கும்"),
    ("πάντοτε", "எப்பொழுதும்"), ("δέησις", "விண்ணப்பத்திலும்"), ("χαρά", "மகிழ்ச்சியோடு"),
    ("ποιέω", "செய்து"), ("κοινωνία", "ஐக்கியப்பட்டிருப்பதால்"), ("εὐαγγέλιον", "நற்செய்தி"),
    ("πρῶτος", "முதல்"), ("ἡμέρα", "நாள்"), ("νῦν", "இதுவரைக்கும்"), ("πείθω", "நம்பி"),
    ("ἐνάρχομαι", "தொடங்கினவர்"), ("ἔργον", "செயலைத்"), ("ἀγαθός", "நல்ல"),
    ("ἐπιτελέω", "நடத்தி வருவார்"), ("χριστός", "கிறிஸ்துவின்"), ("Ἰησοῦς", "இயேசு"),
]


def _norm(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value).casefold().split())


class _FixtureEmbeddings(SemanticEmbeddingProvider):
    """The shipped app has no embedding provider; tests inject one."""

    provider_id = "stage9a-fixture"
    provider_version = "v1"
    model_id = "stage9a-fixture"
    normalization = "L2"
    languages = ("el", "hbo", "ta", "en")
    offline = True
    available = True

    def __init__(self, vectors: dict[str, list[float]]):
        self.vectors = {_norm(k): v for k, v in vectors.items()}
        self.dimensions = len(next(iter(vectors.values())))
        self.model_hash = hashlib.sha256(
            json.dumps(self.vectors, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self.vectors.get(_norm(text), [0.0] * self.dimensions) for text in texts]


def _paired(pairs: list[tuple[str, str]]) -> dict[str, list[float]]:
    out: dict[str, list[float]] = {}
    for index, (source, target) in enumerate(pairs):
        vector = [0.0] * len(pairs)
        vector[index] = 1.0
        out[source] = vector
        out[target] = vector
    return out


def _project(
    tmp_path: Path, chapters: dict[str, dict[str, str]], language: str,
) -> PassageSemanticRuntime:
    root = tmp_path / f"PHP-{language}"
    (root / "php").mkdir(parents=True)
    alignment = root / ".apps" / "translationCore" / "alignmentData" / "php"
    alignment.mkdir(parents=True)
    (root / "manifest.json").write_text(json.dumps({
        "project": {"id": "php", "name": "PHP"}, "target_language": {"id": language},
        "resource": {"id": "test"}, "tc_version": "8",
    }), encoding="utf-8")
    lines = ["\\id PHP"]
    for chapter, verses in chapters.items():
        (root / "php" / f"{chapter}.json").write_text(
            json.dumps(verses, ensure_ascii=False), encoding="utf-8")
        (alignment / f"{chapter}.json").write_text(json.dumps(
            {ref: {"alignments": [], "wordBank": []} for ref in verses}), encoding="utf-8")
        lines.extend([f"\\c {chapter}", "\\p"])
        lines.extend(f"\\v {verse} OLD IMPORTED" for verse in verses)
    (root / "php.usfm").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return PassageSemanticRuntime(
        TranslationCoreProject(root), f"stage9a-{language}-{tmp_path.name}")


def _run(
    runtime: PassageSemanticRuntime, provider: SemanticEmbeddingProvider | None,
    chapter: str, verse: str, end_chapter: str = "", end_verse: str = "",
) -> dict:
    location = SemanticLocationEngine(runtime, provider).run_range(
        chapter, verse, end_chapter, end_verse)
    meaning = MeaningAnalysisEngine(runtime).run_range(
        chapter, verse, end_chapter, end_verse, location_run_id=location["id"])
    return QaAuditEngine(runtime).run_range(
        chapter, verse, end_chapter, end_verse, meaning_run_id=meaning["id"])


@pytest.fixture()
def english(tmp_path: Path) -> PassageSemanticRuntime:
    runtime = _project(tmp_path, {"1": {"3": "unrelated words here"}}, "en")
    _run(runtime, None, "1", "3")
    return runtime


@pytest.fixture()
def tamil(tmp_path: Path) -> PassageSemanticRuntime:
    """The reordered IRV Tamil PHP 1:3-6 passage, which yields located findings."""
    runtime = _project(tmp_path, {"1": TAMIL_PHP}, "ta")
    _run(runtime, _FixtureEmbeddings(_paired(PHP_PAIRS)), "1", "3", "1", "6")
    return runtime


def _first(runtime: PassageSemanticRuntime, **filters) -> dict:
    return runtime.qa_review.get_queue(**filters)["findings"][0]


def _with_meaning(runtime: PassageSemanticRuntime) -> dict:
    for summary in runtime.qa_review.get_queue(limit=200)["findings"]:
        detail = runtime.qa_review.get_finding(summary["id"])
        if detail["meaning"] and detail["location"]:
            return detail
    raise AssertionError("fixture produced no located, assessed finding")


# --- Possible vs confirmed --------------------------------------------------

def test_machine_findings_start_unresolved_and_possible(english: PassageSemanticRuntime) -> None:
    """Nothing the machine produced may present as a confirmed error."""
    findings = english.qa_review.get_queue(limit=200)["findings"]
    assert findings
    for finding in findings:
        assert finding["qaDisposition"] == "UNRESOLVED"
        assert finding["reviewStatus"] == "AI_PROPOSED"
        assert finding["kind"] not in ("MISSING", "UNSUPPORTED", "OMISSION", "ADDITION")
    assert any(finding["isPossible"] for finding in findings)


# --- Evidence layers --------------------------------------------------------

def test_finding_detail_returns_layered_evidence(english: PassageSemanticRuntime) -> None:
    detail = english.qa_review.get_finding(_first(english)["id"])
    for section in ("finding", "source", "target", "location", "meaning", "coverage",
                    "resources", "supportingEvidence", "conflictingEvidence", "history"):
        assert section in detail, f"missing evidence section: {section}"
    assert detail["isStale"] is False


def test_location_and_meaning_are_separate_sections(tamil: PassageSemanticRuntime) -> None:
    """A mapping problem and a translation problem must stay distinguishable."""
    detail = _with_meaning(tamil)
    assert detail["location"][0]["location"]["locationOutcome"] == "LOCATED"
    assert detail["meaning"][0]["assessment"]["meaningStatus"]
    assert detail["meaning"][0]["components"], "component assessments must not be collapsed"
    # Location outcome and meaning status are reported from different records,
    # so a strong location can accompany a failed meaning assessment.
    assert "meaningStatus" not in detail["location"][0]["location"]


def test_unresolvable_evidence_is_surfaced_not_raised(tamil: PassageSemanticRuntime) -> None:
    """Stage 7 meaning evidence is inline, not an evidence_records row."""
    detail = _with_meaning(tamil)
    sources = {
        item["evidenceSource"]
        for item in detail["supportingEvidence"] + detail["conflictingEvidence"]
    }
    assert sources <= {"MEANING_ASSESSMENT", "EVIDENCE_RECORD", "UNRESOLVED"}
    assert "MEANING_ASSESSMENT" in sources


def test_alternatives_are_returned_when_the_engine_retained_them(
    tamil: PassageSemanticRuntime,
) -> None:
    """The UI must never imply there was only one candidate."""
    detail = _with_meaning(tamil)
    assert "alternatives" in detail["location"][0]
    assert isinstance(detail["location"][0]["alternatives"], list)


# --- Dispositions -----------------------------------------------------------

@pytest.mark.parametrize(("disposition", "expected_review"), [
    ("CONFIRMED_TRANSLATION_ERROR", "HUMAN_APPROVED"),
    ("ACCEPTABLE_TRANSLATION", "HUMAN_APPROVED"),
    ("FALSE_POSITIVE", "HUMAN_REJECTED"),
    ("NEEDS_DISCUSSION", "NEEDS_DISCUSSION"),
])
def test_each_reviewer_decision_maps_to_its_review_status(
    english: PassageSemanticRuntime, disposition: str, expected_review: str,
) -> None:
    finding = _first(english)
    result = english.qa_review.decide_finding(
        finding["id"], disposition, expected_revision=finding["revision"], note="decided")
    assert result["finding"]["qaDisposition"] == disposition
    assert result["finding"]["reviewStatus"] == expected_review
    assert len(result["history"]) == 1
    assert result["history"][0]["note"] == "decided"
    assert result["history"][0]["actorType"] == "HUMAN"


def test_system_only_dispositions_are_rejected(english: PassageSemanticRuntime) -> None:
    finding = _first(english)
    for disposition in ("CORRECTED", "UNRESOLVED"):
        with pytest.raises(FoundationValidationError):
            english.qa_review.decide_finding(
                finding["id"], disposition, expected_revision=finding["revision"])


def test_unknown_disposition_is_rejected(english: PassageSemanticRuntime) -> None:
    finding = _first(english)
    with pytest.raises(FoundationValidationError):
        english.qa_review.decide_finding(
            finding["id"], "LOOKS_FINE", expected_revision=finding["revision"])


def test_false_positive_preserves_machine_evidence(english: PassageSemanticRuntime) -> None:
    """A false positive is calibration evidence; it must not be suppressed."""
    finding = _first(english)
    before = english.repository.qa_finding(finding["id"])
    english.qa_review.decide_finding(
        finding["id"], "FALSE_POSITIVE", expected_revision=finding["revision"],
        note="This Greek particle needs no separate counterpart.")
    after = english.repository.qa_finding(finding["id"])
    assert after["explanation"] == before["explanation"]
    assert after["qaEngineVersion"] == before["qaEngineVersion"]
    assert after["qaPolicyVersion"] == before["qaPolicyVersion"]
    assert after["targetContentHashes"] == before["targetContentHashes"]
    assert after["sourceResourceHashes"] == before["sourceResourceHashes"]
    assert english.repository.review_records("QA_FINDING", finding["id"])[0]["note"]
    assert [f["id"] for f in english.qa_review.get_queue(
        dispositions=("FALSE_POSITIVE",))["findings"]] == [finding["id"]]


def test_acceptable_translation_keeps_the_finding_rather_than_deleting_it(
    english: PassageSemanticRuntime,
) -> None:
    finding = _first(english)
    english.qa_review.decide_finding(
        finding["id"], "ACCEPTABLE_TRANSLATION", expected_revision=finding["revision"],
        note="Legitimate explicitation.")
    stored = english.repository.qa_finding(finding["id"])
    assert stored["qaDisposition"] == "ACCEPTABLE_TRANSLATION"
    assert stored["explanation"], "the machine finding is retained, not discarded"


# --- Concurrency ------------------------------------------------------------

def test_stale_revision_is_rejected(english: PassageSemanticRuntime) -> None:
    finding = _first(english)
    english.qa_review.decide_finding(
        finding["id"], "CONFIRMED_TRANSLATION_ERROR", expected_revision=finding["revision"])
    with pytest.raises(FoundationConflict):
        english.qa_review.decide_finding(
            finding["id"], "FALSE_POSITIVE", expected_revision=finding["revision"])


def test_decision_against_changed_target_text_is_rejected(
    english: PassageSemanticRuntime,
) -> None:
    """Never accept a decision written against target text the reviewer never saw."""
    finding = _first(english)
    with pytest.raises(FoundationConflict):
        english.qa_review.decide_finding(
            finding["id"], "CONFIRMED_TRANSLATION_ERROR",
            expected_revision=finding["revision"],
            expected_target_content_hashes=("a-hash-from-an-older-render",))


def test_matching_target_hashes_are_accepted(english: PassageSemanticRuntime) -> None:
    finding = _first(english)
    stored = tuple(english.repository.qa_finding(finding["id"])["targetContentHashes"])
    result = english.qa_review.decide_finding(
        finding["id"], "ACCEPTABLE_TRANSLATION", expected_revision=finding["revision"],
        expected_target_content_hashes=stored)
    assert result["finding"]["qaDisposition"] == "ACCEPTABLE_TRANSLATION"


# --- Promotion --------------------------------------------------------------

def test_promotion_never_happens_without_an_explicit_request(
    english: PassageSemanticRuntime,
) -> None:
    """Opening or deciding a finding must not promote POSSIBLY_MISSING."""
    finding = _first(english, kinds=("POSSIBLE_OMISSION",))
    english.qa_review.get_finding(finding["id"])
    result = english.qa_review.decide_finding(
        finding["id"], "CONFIRMED_TRANSLATION_ERROR", expected_revision=finding["revision"])
    assert result["promotedCoverageAccountIds"] == []
    for account_id in english.repository.qa_finding(finding["id"])["coverageAccountIds"]:
        assert english.repository.coverage_account(account_id)["coverageStatus"] != "MISSING"


def test_explicit_promotion_confirms_possibly_missing(english: PassageSemanticRuntime) -> None:
    finding = _first(english, kinds=("POSSIBLE_OMISSION",))
    result = english.qa_review.decide_finding(
        finding["id"], "CONFIRMED_TRANSLATION_ERROR", expected_revision=finding["revision"],
        note="Confirmed omitted.", promote=True)
    assert result["promotedCoverageAccountIds"]
    for account_id in result["promotedCoverageAccountIds"]:
        account = english.repository.coverage_account(account_id)
        assert account["coverageStatus"] == "MISSING"
        assert account["reviewStatus"] == "HUMAN_APPROVED"


def test_promotion_is_skipped_when_the_issue_is_not_confirmed(
    english: PassageSemanticRuntime,
) -> None:
    finding = _first(english, kinds=("POSSIBLE_OMISSION",))
    result = english.qa_review.decide_finding(
        finding["id"], "ACCEPTABLE_TRANSLATION", expected_revision=finding["revision"],
        promote=True)
    assert result["promotedCoverageAccountIds"] == []


# --- Mapping and meaning review --------------------------------------------

def test_rejecting_a_mapping_is_not_a_translation_verdict(
    tamil: PassageSemanticRuntime,
) -> None:
    """Reject Mapping says Bridge looked in the wrong place, nothing more."""
    detail = _with_meaning(tamil)
    location = detail["location"][0]["location"]
    result = tamil.qa_review.decide_location(
        location["id"], "REJECT", expected_revision=location["revision"],
        note="This is the wrong target expression.")
    assert result["location"]["reviewStatus"] == "HUMAN_REJECTED"
    assert result["history"][0]["note"] == "This is the wrong target expression."
    # The QA disposition is untouched: a mapping verdict decides nothing about
    # whether the translation itself is wrong.
    assert tamil.repository.qa_finding(
        detail["finding"]["id"])["qaDisposition"] == "UNRESOLVED"


def test_selecting_an_alternative_records_human_modified(
    tamil: PassageSemanticRuntime,
) -> None:
    location = _with_meaning(tamil)["location"][0]["location"]
    result = tamil.qa_review.decide_location(
        location["id"], "REJECT", expected_revision=location["revision"],
        selected_candidate_id="candidate-chosen-by-reviewer")
    assert result["location"]["reviewStatus"] == "HUMAN_MODIFIED"
    assert result["location"]["selectedCandidateId"] == "candidate-chosen-by-reviewer"


def test_approving_a_mapping_leaves_downstream_active(tamil: PassageSemanticRuntime) -> None:
    detail = _with_meaning(tamil)
    location = detail["location"][0]["location"]
    tamil.qa_review.decide_location(
        location["id"], "APPROVE", expected_revision=location["revision"])
    assert tamil.repository.qa_finding(
        detail["finding"]["id"])["lifecycleStatus"] == "ACTIVE"


def test_unknown_mapping_decision_is_rejected(tamil: PassageSemanticRuntime) -> None:
    location = _with_meaning(tamil)["location"][0]["location"]
    with pytest.raises(FoundationValidationError):
        tamil.qa_review.decide_location(
            location["id"], "MAYBE", expected_revision=location["revision"])


def test_mapping_review_rejects_a_stale_revision(tamil: PassageSemanticRuntime) -> None:
    location = _with_meaning(tamil)["location"][0]["location"]
    tamil.qa_review.decide_location(
        location["id"], "APPROVE", expected_revision=location["revision"])
    with pytest.raises(FoundationConflict):
        tamil.qa_review.decide_location(
            location["id"], "REJECT", expected_revision=location["revision"])


def test_meaning_can_be_overridden_independently_of_qa(
    tamil: PassageSemanticRuntime,
) -> None:
    """A reviewer may disagree with Stage 7 without accepting Stage 8's synthesis."""
    assessment = _with_meaning(tamil)["meaning"][0]["assessment"]
    result = tamil.qa_review.decide_meaning(
        assessment["id"], "PRESERVED_WITH_RESTRUCTURING",
        expected_revision=assessment["revision"], note="Legitimate Tamil restructuring.")
    assert result["meaning"]["meaningStatus"] == "PRESERVED_WITH_RESTRUCTURING"
    assert result["meaning"]["reviewStatus"] == "HUMAN_MODIFIED"
    assert result["history"][0]["note"] == "Legitimate Tamil restructuring."


def test_unknown_meaning_status_is_rejected(tamil: PassageSemanticRuntime) -> None:
    assessment = _with_meaning(tamil)["meaning"][0]["assessment"]
    with pytest.raises(FoundationValidationError):
        tamil.qa_review.decide_meaning(
            assessment["id"], "MOSTLY_FINE", expected_revision=assessment["revision"])


# --- Notes and history ------------------------------------------------------

def test_a_note_records_history_without_deciding(english: PassageSemanticRuntime) -> None:
    finding = _first(english)
    english.qa_review.add_note("QA_FINDING", finding["id"], "Ask the translator about this.")
    stored = english.repository.qa_finding(finding["id"])
    assert stored["qaDisposition"] == "UNRESOLVED"
    assert stored["revision"] == finding["revision"], "commenting is not deciding"
    history = english.qa_review.get_entity_history("QA_FINDING", finding["id"])["records"]
    assert history[0]["note"] == "Ask the translator about this."


def test_empty_notes_are_rejected(english: PassageSemanticRuntime) -> None:
    finding = _first(english)
    with pytest.raises(FoundationValidationError):
        english.qa_review.add_note("QA_FINDING", finding["id"], "   ")


def test_notes_on_unreviewable_entities_are_rejected(english: PassageSemanticRuntime) -> None:
    with pytest.raises(FoundationValidationError):
        english.qa_review.add_note("SCRIPTURE_VERSE", "PHP 1:3", "not a review target")


def test_history_accumulates_in_order(english: PassageSemanticRuntime) -> None:
    finding = _first(english)
    english.qa_review.add_note("QA_FINDING", finding["id"], "first look")
    english.qa_review.decide_finding(
        finding["id"], "NEEDS_DISCUSSION", expected_revision=finding["revision"],
        note="raise with the team")
    records = english.qa_review.get_entity_history("QA_FINDING", finding["id"])["records"]
    assert [record["note"] for record in records] == ["first look", "raise with the team"]


# --- Staleness and re-runs --------------------------------------------------

def test_target_edit_makes_a_reviewed_finding_stale_but_keeps_the_decision(
    tmp_path: Path,
) -> None:
    runtime = _project(tmp_path, {"1": {"3": "unrelated words here"}}, "en")
    _run(runtime, None, "1", "3")
    finding = _first(runtime)
    runtime.qa_review.decide_finding(
        finding["id"], "CONFIRMED_TRANSLATION_ERROR", expected_revision=finding["revision"],
        note="confirmed")

    (tmp_path / "PHP-en" / "php" / "1.json").write_text(
        json.dumps({"3": "completely different target wording"}), encoding="utf-8")
    runtime.synchronize_current_text()

    stale = runtime.repository.qa_finding(finding["id"])
    assert stale["lifecycleStatus"] == "STALE"
    # A wording change is not evidence the issue was corrected; only a future
    # Stage 9B recheck may conclude that.
    assert stale["qaDisposition"] == "CONFIRMED_TRANSLATION_ERROR"
    assert stale["reviewStatus"] == "HUMAN_APPROVED"
    # Every finding anchored in the edited verse goes stale, not only the
    # reviewed one -- the whole verse's analysis is now against older text.
    stale_ids = {f["id"] for f in runtime.qa_review.get_queue(
        lifecycle_statuses=("STALE",), limit=200)["findings"]}
    assert finding["id"] in stale_ids
    assert not runtime.qa_review.get_queue(lifecycle_statuses=("ACTIVE",))["findings"]


def test_rerun_refreshes_analysis_without_overwriting_human_review(tmp_path: Path) -> None:
    """Finding ids are stable, so a re-run reaches the reviewed row."""
    runtime = _project(tmp_path, {"1": {"3": "unrelated words here"}}, "en")
    _run(runtime, None, "1", "3")
    finding = _first(runtime)
    runtime.qa_review.decide_finding(
        finding["id"], "CONFIRMED_TRANSLATION_ERROR", expected_revision=finding["revision"],
        note="confirmed")

    (tmp_path / "PHP-en" / "php" / "1.json").write_text(
        json.dumps({"3": "completely different target wording"}), encoding="utf-8")
    runtime.synchronize_current_text()
    rerun = _run(runtime, None, "1", "3")

    assert finding["id"] in {item["id"] for item in rerun["findings"]}, (
        "a re-run must reach the same finding identity, not mint a new one")
    after = runtime.repository.qa_finding(finding["id"])
    assert after["qaDisposition"] == "CONFIRMED_TRANSLATION_ERROR"
    assert after["reviewStatus"] == "HUMAN_APPROVED"
    assert after["lifecycleStatus"] == "ACTIVE", "a re-run re-evaluates a stale finding"
    actors = [
        record["actorType"]
        for record in runtime.repository.review_records("QA_FINDING", finding["id"])
    ]
    assert actors == ["HUMAN", "SYSTEM"], (
        "the machine refresh is recorded without replacing the human decision")


def test_finding_identity_is_stable_across_an_unchanged_rerun(tmp_path: Path) -> None:
    runtime = _project(tmp_path, {"1": {"3": "unrelated words here"}}, "en")
    first = _run(runtime, None, "1", "3")
    second = _run(runtime, None, "1", "3")
    assert {f["id"] for f in first["findings"]} == {f["id"] for f in second["findings"]}


# --- Protocol round trip ----------------------------------------------------

def _bridge(runtime: PassageSemanticRuntime):
    from bridge_service import BridgeEngine

    bridge = BridgeEngine()
    bridge.project = runtime.project
    bridge.passage_semantic_runtime = runtime
    return bridge


def _call(bridge, method: str, params: dict) -> dict:
    from greek_room_engine.protocol import EngineRequest

    return bridge.handle_request(
        EngineRequest(id="rq", method=method, params=params)).to_dict()


def test_review_apis_round_trip_over_the_protocol(english: PassageSemanticRuntime) -> None:
    bridge = _bridge(english)
    queue = _call(bridge, "qaReview.getQueue", {"limit": 2})
    assert queue["success"] is True, queue
    assert queue["result"]["totalCount"] >= 1
    finding = queue["result"]["findings"][0]

    detail = _call(bridge, "qaReview.getFinding", {"findingId": finding["id"]})
    assert detail["success"] is True
    assert "location" in detail["result"] and "meaning" in detail["result"]

    note = _call(bridge, "qaReview.addNote", {
        "entityType": "QA_FINDING", "entityId": finding["id"], "note": "second look"})
    assert note["success"] is True
    assert note["result"]["history"][0]["note"] == "second look"

    decided = _call(bridge, "qaReview.decideFinding", {
        "findingId": finding["id"], "disposition": "FALSE_POSITIVE",
        "expectedEntityRevision": finding["revision"], "note": "machine was wrong"})
    assert decided["success"] is True
    assert decided["result"]["finding"]["qaDisposition"] == "FALSE_POSITIVE"
    assert decided["result"]["finding"]["reviewStatus"] == "HUMAN_REJECTED"

    history = _call(bridge, "reviewHistory.getEntityHistory", {
        "entityType": "QA_FINDING", "entityId": finding["id"]})
    assert history["success"] is True
    assert [r["actorType"] for r in history["result"]["records"]] == ["HUMAN", "HUMAN"]


def test_a_stale_write_returns_revision_conflict_on_the_wire(
    english: PassageSemanticRuntime,
) -> None:
    """Human review is never last-write-wins, and the UI must be told why."""
    bridge = _bridge(english)
    finding = _call(bridge, "qaReview.getQueue", {"limit": 1})["result"]["findings"][0]
    first = _call(bridge, "qaReview.decideFinding", {
        "findingId": finding["id"], "disposition": "CONFIRMED_TRANSLATION_ERROR",
        "expectedEntityRevision": finding["revision"]})
    assert first["success"] is True
    second = _call(bridge, "qaReview.decideFinding", {
        "findingId": finding["id"], "disposition": "ACCEPTABLE_TRANSLATION",
        "expectedEntityRevision": finding["revision"]})
    assert second["success"] is False
    assert second["error"]["code"] == "revision_conflict"


def test_invalid_review_input_is_a_validation_error_not_a_crash(
    english: PassageSemanticRuntime,
) -> None:
    bridge = _bridge(english)
    response = _call(bridge, "semanticReview.decideMeaning", {
        "assessmentId": "does-not-exist", "meaningStatus": "PRESERVED",
        "expectedEntityRevision": 1})
    assert response["success"] is False
    assert response["error"]["code"] == "semantic_validation_error"


def test_analysis_apis_stay_read_only_under_review(english: PassageSemanticRuntime) -> None:
    """Review writes must not alter the Stage 6B/7 payloads they cite."""
    bridge = _bridge(english)
    finding = _call(bridge, "qaReview.getQueue", {"limit": 1})["result"]["findings"][0]
    before = json.dumps(english.repository.qa_finding(finding["id"])["explanation"])
    _call(bridge, "qaReview.decideFinding", {
        "findingId": finding["id"], "disposition": "ACCEPTABLE_TRANSLATION",
        "expectedEntityRevision": finding["revision"], "note": "fine as translated"})
    after = json.dumps(english.repository.qa_finding(finding["id"])["explanation"])
    assert before == after
