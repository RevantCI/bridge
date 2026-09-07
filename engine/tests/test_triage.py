"""AI triage of Greek Room findings (tc_ai_bridge/triage.py + triage_prompts.py).

Covers the three properties the module exists to guarantee -- a cached
verdict is never re-bought, a malformed response never fails a run, and a
human override always wins and is never clobbered -- plus the hash contract
the report screen's merge depends on.

No test here touches a network: every model call goes through an injected
`call_model` callable, and the one client-level test drives
OpenAIResponsesClient with a fake transport.
"""
import json
import threading

import pytest

from tc_ai_bridge.ai_client import OpenAIResponsesClient
from tc_ai_bridge.tc_project import TranslationCoreProject, read_triage_records
from tc_ai_bridge.triage import (
    MAX_BATCH, build_batches, build_items, build_batch_input, canonical_evidence,
    effective_verdict, finding_context, is_cached, parse_triage_response,
    run_book_triage, strip_fences, triable_findings, triage_hash,
)
from tc_ai_bridge.triage_prompts import FAMILIES, family_for, instructions_for

from .test_bridge_service import fixture_project  # noqa: F401


def _finding(**overrides):
    base = {
        "id": "f1",
        "engine": "wildebeest",
        "check_type": "wildebeest.script.mixed",
        "category": "unicode",
        "severity": "high",
        "original_text": "ஆதி",
        "suggested_replacement": None,
        "explanation": "Latin character mixed into Tamil text.",
        "evidence": [{"label": "script", "value": "Latin + Tamil"}],
        "status": "open",
    }
    base.update(overrides)
    return base


def _hash(finding, *, book="rut", chapter="1", verse="1"):
    return triage_hash(book=book, chapter=chapter, verse=verse,
                       check_type=str(finding.get("check_type", "")), finding=finding)


# -- hash contract --------------------------------------------------------


def test_hash_is_stable_across_offset_only_changes():
    """A finding shifting position because an earlier word was edited is the
    same judgement; re-buying every verdict in a verse after any edit would
    make the cache nearly useless."""
    a = _finding(start_offset=0, end_offset=3)
    b = _finding(start_offset=17, end_offset=20)
    assert _hash(a) == _hash(b)


def test_hash_ignores_fields_that_do_not_change_the_judgement():
    assert _hash(_finding(id="f1", status="open")) == _hash(_finding(id="f2", status="accepted"))


@pytest.mark.parametrize("change", [
    {"original_text": "வேறு"},
    {"explanation": "Something else entirely."},
    {"evidence": [{"label": "script", "value": "Devanagari + Tamil"}]},
    {"suggested_replacement": "ஆதியிலே"},
])
def test_hash_changes_when_evidence_changes(change):
    """The whole point: a verdict about evidence that changed is worthless."""
    assert _hash(_finding()) != _hash(_finding(**change))


def test_hash_separates_books_chapters_and_verses():
    finding = _finding()
    base = _hash(finding)
    assert _hash(finding, book="gen") != base
    assert _hash(finding, chapter="2") != base
    assert _hash(finding, verse="2") != base


def test_hash_keeps_bridged_and_segmented_verses_distinct():
    """USFM verse bridges ('3-4') and segments ('3a') are real input; the
    hash must use the row key, not a collapsed integer (CLAUDE.md gotcha 12)."""
    finding = _finding()
    assert len({_hash(finding, verse=v) for v in ("3", "3-4", "3a")}) == 3


def test_canonical_evidence_normalizes_whitespace_but_not_content():
    assert canonical_evidence(_finding(explanation="a   b\n c")) == \
        canonical_evidence(_finding(explanation="a b c"))
    assert canonical_evidence(_finding(explanation="a b")) != \
        canonical_evidence(_finding(explanation="a c"))


# -- prompt families ------------------------------------------------------


@pytest.mark.parametrize("check_type,category,expected", [
    ("wildebeest.script.mixed", "unicode", "mechanical"),
    ("wildebeest.zero_width", "unicode", "mechanical"),
    ("TA_REPEAT_WORD", "repetition", "mechanical"),
    ("LANG_DOUBLE_SPACE", "unicode", "mechanical"),
    ("usfm.unclosed_marker", "structure", "structure"),
    ("USFM_BALANCE", "structure", "structure"),
    ("ALIGN_DUP_TOP", "alignment", "structure"),
    ("names.spelling_similarity", "names", "consistency"),
    ("alignment.inconsistent_rendering", "consistency", "lexical"),
])
def test_family_routing_matches_the_check_types_the_engines_emit(check_type, category, expected):
    assert family_for(check_type, category) == expected


def test_every_family_is_reachable_and_has_instructions():
    """A family with no route is dead prompt text nobody tunes."""
    routed = {
        family_for(c, cat) for c, cat in [
            ("wildebeest.script.mixed", "unicode"), ("usfm.x", "structure"),
            ("names.spelling_similarity", "names"), ("alignment.inconsistent_rendering", "consistency"),
        ]
    }
    assert routed == set(FAMILIES)
    for family in FAMILIES:
        assert "STRICT JSON" in instructions_for(family)


def test_category_is_the_fallback_when_check_type_is_unknown():
    assert family_for("", "names") == "consistency"
    assert family_for("something.unrecognised", "alignment") == "lexical"


# -- batching -------------------------------------------------------------


def _items(count, *, chapter="1", check_type="wildebeest.script.mixed"):
    findings_by_verse = {}
    for i in range(count):
        verse = str(i + 1)
        findings_by_verse[(chapter, verse)] = {
            f"f{i}": _finding(id=f"f{i}", check_type=check_type, explanation=f"issue {i}")
        }
    return build_items("rut", findings_by_verse)


def test_batches_are_capped_at_max_batch():
    batches = build_batches(_items(MAX_BATCH * 2 + 3))
    assert all(len(b) <= MAX_BATCH for b in batches)
    assert sum(len(b) for b in batches) == MAX_BATCH * 2 + 3


def test_a_batch_never_mixes_families_or_chapters():
    """One prompt per batch, and one unparseable response must be able to
    spoil at most one chapter's worth of one family."""
    items = _items(3, chapter="1") + _items(3, chapter="2") \
        + _items(2, chapter="1", check_type="names.spelling_similarity")
    for batch in build_batches(items):
        assert len({i.chapter for i in batch}) == 1
        assert len({i.family for i in batch}) == 1


def test_batches_are_deterministically_ordered():
    items = _items(5, chapter="2") + _items(5, chapter="10") + _items(5, chapter="1")
    chapters = [b[0].chapter for b in build_batches(items)]
    assert chapters == ["1", "2", "10"]  # numeric, not lexicographic


# -- response parsing -----------------------------------------------------


_CLEAN = json.dumps({"results": [
    {"finding_id": "f0", "verdict": "false_positive", "confidence": 95, "reason": "Danda is correct here."}
]})


@pytest.mark.parametrize("raw", [
    _CLEAN,
    f"```json\n{_CLEAN}\n```",
    f"```\n{_CLEAN}\n```",
    json.dumps([{"finding_id": "f0", "verdict": "false_positive", "confidence": 95, "reason": "x"}]),
    json.dumps({"findings": [{"finding_id": "f0", "verdict": "false_positive", "confidence": 95, "reason": "x"}]}),
])
def test_parser_accepts_the_shapes_providers_actually_return(raw):
    parsed = parse_triage_response(raw)
    assert parsed and parsed[0]["finding_id"] == "f0"
    assert parsed[0]["verdict"] == "false_positive"


@pytest.mark.parametrize("raw", [
    "", "   ", "I think this finding is fine, actually.",
    "{not json at all", json.dumps({"results": {"f0": "false_positive"}}),
    json.dumps({"results": [{"finding_id": "f0", "verdict": "probably_fine", "confidence": 9, "reason": "x"}]}),
    json.dumps({"results": [{"verdict": "false_positive", "confidence": 9, "reason": "no id"}]}),
])
def test_parser_returns_none_rather_than_raising_on_anything_unusable(raw):
    assert parse_triage_response(raw) is None


def test_strip_fences_leaves_unfenced_text_alone():
    assert strip_fences('{"a": 1}') == '{"a": 1}'
    assert strip_fences('```json\n{"a": 1}\n```') == '{"a": 1}'


@pytest.mark.parametrize("given,expected", [
    (95, 95), ("80", 80), (0.95, 95), (1.0, 1), (0, 0), (200, 100), (-5, 0), (None, 0), ("nonsense", 0),
])
def test_confidence_is_clamped_and_probability_style_answers_rescaled(given, expected):
    raw = json.dumps({"results": [
        {"finding_id": "f0", "verdict": "uncertain", "confidence": given, "reason": "x"}
    ]})
    assert parse_triage_response(raw)[0]["confidence"] == expected


# -- override semantics ---------------------------------------------------


def test_user_override_wins_over_the_model_verdict():
    record = {"verdict": "false_positive", "confidence": 99,
              "userOverride": {"verdict": "true_positive", "timestamp": "now"}}
    assert effective_verdict(record) == "true_positive"


def test_effective_verdict_falls_back_to_the_model_and_then_to_uncertain():
    assert effective_verdict({"verdict": "false_positive"}) == "false_positive"
    assert effective_verdict({}) == "uncertain"
    assert effective_verdict({"verdict": "false_positive", "userOverride": None}) == "false_positive"


def test_is_cached_covers_verdicts_and_overrides_but_not_junk():
    assert is_cached({"verdict": "uncertain"})
    assert is_cached({"userOverride": {"verdict": "true_positive"}})
    assert not is_cached({"verdict": "nonsense"})
    assert not is_cached({})
    assert not is_cached(None)


# -- store round-trip -----------------------------------------------------


def test_triage_store_round_trips(fixture_project):
    project = TranslationCoreProject(fixture_project)
    assert project.load_triage_records() == {}  # missing file is not an error
    project.save_triage_records({"abc": {"verdict": "false_positive", "confidence": 90}})
    assert project.load_triage_records()["abc"]["confidence"] == 90
    assert project.clear_triage_records() is True
    assert project.load_triage_records() == {}
    assert project.clear_triage_records() is False


def test_corrupt_triage_file_reads_as_empty_rather_than_crashing(fixture_project):
    project = TranslationCoreProject(fixture_project)
    path = project.triage_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ this is not json", encoding="utf-8")
    assert project.load_triage_records() == {}


def test_read_triage_records_works_without_constructing_a_project(fixture_project):
    """triage.results must be able to report a lazy sibling as simply having
    no verdicts -- constructing a project there would fail on the manifest."""
    project = TranslationCoreProject(fixture_project)
    assert read_triage_records(fixture_project, "rut") is None
    project.save_triage_records({"abc": {"verdict": "uncertain", "confidence": 0}})
    assert list(read_triage_records(fixture_project, "rut")) == ["abc"]
    assert read_triage_records(fixture_project, "gen") is None


# -- context building -----------------------------------------------------


def _plant_findings(project, findings_by_verse, chapter="1"):
    project.save_check_findings_snapshot(chapter, findings_by_verse)


def test_context_includes_neighbouring_verses_and_aligned_source_words(fixture_project):
    (fixture_project / "rut" / "1.json").write_text(json.dumps({
        "1": "verse one", "2": "verse two", "3": "verse three", "4": "verse four",
    }, ensure_ascii=False), encoding="utf-8")
    # verses() reads alignmentData, which is the canonical verse list for a
    # chapter throughout tc_project -- extending only the target text would
    # leave the project with a one-verse chapter.
    align = fixture_project / ".apps" / "translationCore" / "alignmentData" / "rut" / "1.json"
    align.write_text(json.dumps({
        v: {"alignments": [], "wordBank": []} for v in ("1", "2", "3", "4")
    }), encoding="utf-8")
    project = TranslationCoreProject(fixture_project)

    items = build_items("rut", {("1", "2"): {"f1": _finding()}})
    context = finding_context(project, items[0])

    refs = [v["ref"] for v in context["target_verses"]]
    assert refs == ["1:1", "1:2", "1:3"]  # the finding's verse plus one either side
    assert [v for v in context["target_verses"] if v.get("isFindingVerse")][0]["ref"] == "1:2"
    assert context["check_type"] == "wildebeest.script.mixed"
    assert context["evidence"] == [{"label": "script", "value": "Latin + Tamil"}]


def test_context_carries_the_projects_own_alignment_source_words(fixture_project):
    """The zaln/w data translationCore wrote is preferred over the bundled
    original-language tokens -- it is what this project is actually aligned to."""
    project = TranslationCoreProject(fixture_project)
    items = build_items("rut", {("1", "1"): {"f1": _finding(check_type="alignment.inconsistent_rendering")}})
    context = finding_context(project, items[0])
    words = context.get("source_words") or []
    assert any(w["word"] == "אֱלֹהִ֑ים" for w in words)
    assert any(w.get("alignedTo") == "தேவன்" for w in words)


def test_context_at_a_chapter_edge_does_not_invent_verses(fixture_project):
    project = TranslationCoreProject(fixture_project)
    items = build_items("rut", {("1", "1"): {"f1": _finding()}})
    context = finding_context(project, items[0])
    assert [v["ref"] for v in context["target_verses"]] == ["1:1"]


def test_batch_input_is_json_the_model_can_read(fixture_project):
    project = TranslationCoreProject(fixture_project)
    items = build_items("rut", {("1", "1"): {"f1": _finding()}})
    payload = json.loads(build_batch_input(project, items))
    assert payload["book"] == "RUT"
    assert payload["target_language"] == "Tamil"
    assert payload["findings"][0]["finding_id"] == "f1"


# -- the run --------------------------------------------------------------


class FakeModel:
    """Answers every finding in the batch it is given, and records calls."""

    def __init__(self, verdict="false_positive", confidence=95):
        self.calls: list[tuple[str, str]] = []
        self.verdict = verdict
        self.confidence = confidence
        self.gate: threading.Event | None = None

    def __call__(self, instructions: str, input_text: str) -> str:
        self.calls.append((instructions, input_text))
        if self.gate is not None:
            self.gate.wait(timeout=5)
        payload = json.loads(input_text)
        return json.dumps({"results": [
            {"finding_id": f["finding_id"], "verdict": self.verdict,
             "confidence": self.confidence, "reason": "because"}
            for f in payload["findings"]
        ]})


def _run(project, model, **kwargs):
    return run_book_triage(project, call_model=model, model="fake-model",
                           lock=threading.RLock(), **kwargs)


def test_end_to_end_batch_persists_a_verdict_per_finding(fixture_project):
    project = TranslationCoreProject(fixture_project)
    _plant_findings(project, {"1": [_finding(id="f1"), _finding(id="f2", check_type="usfm.marker",
                                                               explanation="Unclosed marker.")]})
    model = FakeModel()

    summary = _run(project, model)

    assert summary["findings"] == 2
    assert summary["triaged"] == 2
    assert summary["skipped"] == 0
    # Two families -> two batches, never one mixed prompt.
    assert len(model.calls) == 2
    records = project.load_triage_records()
    assert len(records) == 2
    assert {r["verdict"] for r in records.values()} == {"false_positive"}
    assert {r["model"] for r in records.values()} == {"fake-model"}
    assert all(r["reason"] == "because" for r in records.values())


def test_a_second_run_over_unchanged_findings_makes_zero_model_calls(fixture_project):
    project = TranslationCoreProject(fixture_project)
    _plant_findings(project, {"1": [_finding(id="f1")]})
    first = FakeModel()
    _run(project, first)
    assert len(first.calls) == 1

    second = FakeModel()
    summary = _run(project, second)

    assert second.calls == []
    assert summary["triaged"] == 0
    assert summary["skipped"] == 1


def test_force_re_triages_but_never_discards_a_human_override(fixture_project):
    project = TranslationCoreProject(fixture_project)
    _plant_findings(project, {"1": [_finding(id="f1"), _finding(id="f2", explanation="other")]})
    _run(project, FakeModel())

    records = project.load_triage_records()
    overridden = _hash(_finding(id="f1"))
    records[overridden]["userOverride"] = {"verdict": "true_positive", "timestamp": "t"}
    project.save_triage_records(records)

    model = FakeModel(verdict="uncertain", confidence=0)
    summary = _run(project, model, force=True)

    after = project.load_triage_records()
    assert after[overridden]["userOverride"] == {"verdict": "true_positive", "timestamp": "t"}
    assert effective_verdict(after[overridden]) == "true_positive"
    assert summary["skipped"] == 1  # the overridden one was never re-sent
    assert summary["triaged"] == 1  # the other one was


def test_an_override_recorded_mid_run_is_not_clobbered_by_the_worker(fixture_project):
    """The worker loads the store before its request and writes after it. If
    it merged into that stale copy, an override recorded while the request was
    in flight would be lost -- the same lost-update class progress.json has."""
    project = TranslationCoreProject(fixture_project)
    _plant_findings(project, {"1": [_finding(id="f1")]})
    lock = threading.RLock()
    model = FakeModel()
    model.gate = threading.Event()
    target = _hash(_finding(id="f1"))

    worker = threading.Thread(target=lambda: run_book_triage(
        project, call_model=model, model="fake-model", lock=lock,
    ))
    worker.start()
    try:
        # Wait until the worker is inside the model call, then override.
        deadline = threading.Event()
        while not model.calls and not deadline.wait(0.01):
            pass
        with lock:
            records = project.load_triage_records()
            records[target] = {"verdict": "uncertain", "confidence": 0, "reason": "",
                               "userOverride": {"verdict": "true_positive", "timestamp": "t"}}
            project.save_triage_records(records)
    finally:
        model.gate.set()
        worker.join(timeout=5)

    assert project.load_triage_records()[target]["userOverride"]["verdict"] == "true_positive"


def test_an_unparseable_response_marks_the_batch_uncertain_and_keeps_going(fixture_project):
    project = TranslationCoreProject(fixture_project)
    _plant_findings(project, {"1": [_finding(id="f1"), _finding(id="f2", check_type="usfm.marker")]})

    def flaky(instructions, input_text):
        if "usfm" in instructions.lower() and "structural checker" in instructions.lower():
            return "Sorry, I can't help with that."
        payload = json.loads(input_text)
        return json.dumps({"results": [
            {"finding_id": f["finding_id"], "verdict": "false_positive",
             "confidence": 90, "reason": "fine"} for f in payload["findings"]
        ]})

    summary = _run(project, flaky)

    records = project.load_triage_records()
    assert summary["failedBatches"] == 1
    assert len(records) == 2  # both findings still have a record
    verdicts = {r["verdict"] for r in records.values()}
    assert verdicts == {"false_positive", "uncertain"}
    unreadable = [r for r in records.values() if r["verdict"] == "uncertain"][0]
    assert unreadable["confidence"] == 0


def test_a_raising_client_degrades_the_batch_instead_of_ending_the_run(fixture_project):
    project = TranslationCoreProject(fixture_project)
    _plant_findings(project, {"1": [_finding(id="f1")]})

    def boom(instructions, input_text):
        raise RuntimeError("network went away")

    summary = _run(project, boom)

    assert summary["failedBatches"] == 1
    assert all(r["verdict"] == "uncertain" for r in project.load_triage_records().values())


def test_a_finding_missing_from_the_response_is_marked_uncertain_not_dropped(fixture_project):
    project = TranslationCoreProject(fixture_project)
    _plant_findings(project, {"1": [_finding(id="f1"), _finding(id="f2", explanation="second")]})

    def partial(instructions, input_text):
        first = json.loads(input_text)["findings"][0]
        return json.dumps({"results": [
            {"finding_id": first["finding_id"], "verdict": "false_positive",
             "confidence": 95, "reason": "ok"}
        ]})

    _run(project, partial)

    records = project.load_triage_records()
    assert len(records) == 2
    assert {r["verdict"] for r in records.values()} == {"false_positive", "uncertain"}


def test_records_for_findings_whose_evidence_changed_are_pruned(fixture_project):
    project = TranslationCoreProject(fixture_project)
    _plant_findings(project, {"1": [_finding(id="f1", explanation="original")]})
    _run(project, FakeModel())
    assert len(project.load_triage_records()) == 1

    _plant_findings(project, {"1": [_finding(id="f1", explanation="edited since")]})
    summary = _run(project, FakeModel())

    records = project.load_triage_records()
    assert summary["pruned"] == 1
    assert len(records) == 1  # the stale verdict is gone, the fresh one remains
    assert list(records) == [_hash(_finding(id="f1", explanation="edited since"))]


def test_cancelling_stops_the_run_and_skips_the_prune(fixture_project):
    """A cancelled run has an incomplete picture of which hashes are live;
    pruning against it would delete verdicts it simply never reached."""
    project = TranslationCoreProject(fixture_project)
    _plant_findings(project, {"1": [_finding(id=f"f{i}", explanation=f"issue {i}") for i in range(3)]})
    project.save_triage_records({"stale-key": {"verdict": "false_positive", "confidence": 50}})

    cancel = threading.Event()
    cancel.set()
    summary = _run(project, FakeModel(), cancel=cancel)

    assert summary["cancelled"] is True
    assert summary["pruned"] == 0
    assert "stale-key" in project.load_triage_records()


def test_only_greek_room_findings_are_triaged(fixture_project):
    """tN/tW rows are workflow state read live from translationCore's index,
    and alignment-category rows are completion marks -- neither is a 'the
    checker may have cried wolf' judgement worth a model call."""
    project = TranslationCoreProject(fixture_project)
    _plant_findings(project, {"1": [
        _finding(id="gr", category="unicode"),
        _finding(id="tn", category="translation_note", check_type="tn-1"),
        _finding(id="tw", category="translation_word", check_type="tw-1"),
        _finding(id="wa", category="alignment", check_type="WA_INVALID"),
    ]})

    triable = triable_findings(project, ["1"])
    assert set(triable[("1", "1")]) == {"gr"}

    _run(project, FakeModel())
    assert len(project.load_triage_records()) == 1


def test_progress_is_reported_per_batch(fixture_project):
    project = TranslationCoreProject(fixture_project)
    _plant_findings(project, {"1": [_finding(id=f"f{i}", explanation=f"issue {i}") for i in range(3)]})
    seen = []
    _run(project, FakeModel(), progress=lambda done, skipped, chapter: seen.append((done, skipped, chapter)))
    assert seen[0] == (0, 0, "")
    assert seen[-1][0] == 3


# -- client wiring (fake transport, no network) ---------------------------


def test_triage_batch_sends_the_schema_and_returns_raw_text():
    """triage_batch must return the model's raw text -- not parsed JSON --
    so triage.py can strip fences a compatible endpoint may have added."""
    requests = []

    def transport(url, headers, body, timeout):
        requests.append(json.loads(body.decode("utf-8")))
        fenced = '```json\n{"results": []}\n```'
        return 200, json.dumps({
            "output": [{"content": [{"text": fenced}]}],
            "usage": {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12},
        }).encode("utf-8")

    client = OpenAIResponsesClient("sk-test", model="gpt-4o-mini", transport=transport)
    raw = client.triage_batch("instructions", '{"findings": []}')

    assert raw == '```json\n{"results": []}\n```'
    assert parse_triage_response(raw) is None  # empty results -> unusable, by design
    schema = requests[0]["text"]["format"]
    assert schema["name"] == "finding_triage"
    assert schema["strict"] is True
    # gpt-4o-mini is not a reasoning model: the guard must omit the parameter.
    assert "reasoning" not in requests[0]


def test_post_structured_still_parses_json_after_the_text_split():
    """_post_structured was refactored to go through _post_text; every
    existing caller must keep getting a parsed dict and a hard error on junk."""
    def transport(url, headers, body, timeout):
        return 200, json.dumps({
            "output": [{"content": [{"text": '{"ok": true}'}]}],
            "usage": {},
        }).encode("utf-8")

    client = OpenAIResponsesClient("sk-test", model="gpt-4o-mini", transport=transport)
    assert client._post_structured("i", "t", "n", {"type": "object"}) == {"ok": True}
