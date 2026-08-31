"""
Tests for issue #20: the AI review job (`ai.review.start`, driving
`ReviewPanel.svelte`'s "This verse" / "Chapter" / "Whole book" buttons) now
auto-applies the same gap_fill alignment proposal `prepare_verse_review`
already computes internally, instead of only returning it as a discarded
`alignmentProposal` field.

`prepare_verse_review` itself (the alignment-proposal half) already has
real coverage in test_ai_alignment_propose.py and test_ai_explain.py; a
full end-to-end run additionally needs a translationCore-shaped
`resources/en/translationHelps` install for `TranslationHelpsKnowledgeBase`,
which is unrelated to what's new here. So `prepare_verse_review` itself is
monkeypatched to call the real `propose_alignment` (same fake-HTTP-transport
seam as test_ai_alignment_propose.py) for a real gap-fill proposal, then
return a stubbed-empty tN/tW review — isolating the one thing this issue
actually changes: whether `_run_ai_review_for_project` now saves that
proposal instead of discarding it.
"""
import json
from pathlib import Path

import pytest

from bridge_service import BridgeEngine
from greek_room_engine.protocol import EngineRequest
from tc_ai_bridge.ai_client import OpenAIResponsesClient
from tc_ai_bridge.alignment_engine import apply_proposal, validate_preparation_proposal
from tc_ai_bridge.secret_store import AppSettings


def call(engine, method, params=None):
    return engine.handle_request(EngineRequest(id="t", method=method, params=params or {})).to_dict()


def _tok(word, strong="H430", occurrence=1, occurrences=1):
    return {"word": word, "strong": strong, "occurrence": occurrence, "occurrences": occurrences}


def _tok_b(word, occurrence=1, occurrences=1):
    return {"word": word, "occurrence": occurrence, "occurrences": occurrences, "type": "bottomWord"}


def _write_book(root: Path, book_id: str, chapter: str, verse: str, text: str, alignment: dict) -> None:
    align_dir = root / ".apps" / "translationCore" / "alignmentData" / book_id
    align_dir.mkdir(parents=True, exist_ok=True)
    (root / book_id).mkdir(parents=True, exist_ok=True)
    (root / "manifest.json").write_text(json.dumps({
        "project": {"id": book_id, "name": book_id.upper()},
        "target_language": {"id": "tam", "name": "Tamil"},
        "tc_version": "8", "tc_edit_version": "3.7.0",
    }), encoding="utf-8")
    (align_dir / f"{chapter}.json").write_text(
        json.dumps({verse: alignment}, ensure_ascii=False), encoding="utf-8",
    )
    (root / book_id / f"{chapter}.json").write_text(
        json.dumps({verse: text}, ensure_ascii=False), encoding="utf-8",
    )
    (root / f"{book_id}.usfm").write_text(f"\\id {book_id.upper()}\n", encoding="utf-8")


@pytest.fixture
def fixture_project(tmp_path):
    """One verse: an established (protected) group, one unresolved source
    token (empty-bottom group), and one unresolved target token in the
    word bank — same shape as test_ai_alignment_propose.py's fixture, real
    surface for gap_fill mode to have work to do."""
    root = tmp_path / "rut"
    alignment = {
        "alignments": [
            {"topWords": [_tok("אֱלֹהִ֑ים", "H430")], "bottomWords": [_tok_b("தேவன்")]},
            {"topWords": [_tok("בָּרָא", "H1254")], "bottomWords": []},
        ],
        "wordBank": [_tok_b("படைத்தார்")],
    }
    _write_book(root, "rut", "1", "1", "தேவன் படைத்தார்", alignment)
    return root


def _fake_transport(links):
    payload = {"links": links, "implicit_top_ids": [], "target_only_ids": [], "review_notes": []}

    def transport(url, headers, body, timeout):
        response = {
            "output_text": json.dumps(payload),
            "usage": {
                "input_tokens": 120, "output_tokens": 40, "total_tokens": 160,
                "input_tokens_details": {"cached_tokens": 0},
            },
        }
        return 200, json.dumps(response).encode("utf-8")

    return transport


def _stub_prepare_verse_review(monkeypatch):
    """Real gap_fill proposal + real apply/validate, fake (empty) tN/tW half —
    see module docstring for why the evidence-review half is out of scope here."""
    def fake(self, project, chapter, verse, alignment, knowledge_base=None, progress_callback=None):
        proposal = self.propose_alignment(project, chapter, verse, alignment, mode="gap_fill")
        review_alignment = alignment
        if proposal is not None:
            validate_preparation_proposal(alignment, proposal)
            review_alignment = apply_proposal(alignment, proposal)
        return proposal, review_alignment, [], [], "", {"model": self.model}

    monkeypatch.setattr(OpenAIResponsesClient, "prepare_verse_review", fake)


def _wait_for_ai_job(engine, job_id, timeout=10):
    import time
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = call(engine, "ai.review.status", {"jobId": job_id})
        assert status["success"] is True, status
        snapshot = status["result"]
        if snapshot["state"] in {"succeeded", "failed", "cancelled"}:
            return snapshot
        time.sleep(0.02)
    raise AssertionError("AI review job did not finish")


def test_ai_review_auto_applies_gap_fill_alignment(fixture_project, tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    settings = AppSettings(path=tmp_path / "settings.json")
    settings.set_api_key("sk-test-123")
    _stub_prepare_verse_review(monkeypatch)
    # H002 = "בָּרָא" (the unresolved source token), T002 = "படைத்தார்" (the
    # unresolved target token) — same H00N/T00N ordering as
    # test_ai_alignment_propose.py's equivalent fixture.
    transport = _fake_transport(links=[
        {"top_id": "H002", "bottom_id": "T002", "confidence": 0.9, "reason": "created"},
    ])
    engine = BridgeEngine(settings=settings, ai_transport=transport)
    call(engine, "project.open", {"path": str(fixture_project)})

    started = call(engine, "ai.review.start", {
        "scope": "verse", "chapter": "1", "verse": "1", "mode": "advanced",
    })
    assert started["success"] is True, started
    snapshot = _wait_for_ai_job(engine, started["result"]["jobId"])
    assert snapshot["state"] == "succeeded", snapshot

    context = call(engine, "alignment.get", {"chapter": "1", "verse": "1"})["result"]
    # The AI review job applied the gap-fill proposal directly — no manual
    # "Ask AI to propose alignment" / "Apply proposal" round trip needed.
    assert context["alignment"]["wordBank"] == []
    new_group = next(
        g for g in context["groups"]
        if "படைத்தார்" in [
            item["word"] for item in context["bottomTokens"] if item["id"] in g["bottomIds"]
        ]
    )
    assert new_group is not None
    protected = next(
        g for g in context["groups"]
        if "தேவன்" in [
            item["word"] for item in context["bottomTokens"] if item["id"] in g["bottomIds"]
        ]
    )
    assert protected is not None  # the established group survived untouched
    assert context["status"] == "complete"


def test_ai_review_leaves_already_complete_alignment_untouched(tmp_path, monkeypatch):
    """A verse with nothing left to fill must not get a spurious auto-align
    save (no-op history entry) on every review run."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    settings = AppSettings(path=tmp_path / "settings.json")
    settings.set_api_key("sk-test-123")
    _stub_prepare_verse_review(monkeypatch)
    root = tmp_path / "rut"
    alignment = {
        "alignments": [
            {"topWords": [_tok("אֱלֹהִ֑ים", "H430")], "bottomWords": [_tok_b("தேவன்")]},
        ],
        "wordBank": [],
    }
    _write_book(root, "rut", "1", "1", "தேவன்", alignment)

    transport = _fake_transport(links=[])
    engine = BridgeEngine(settings=settings, ai_transport=transport)
    call(engine, "project.open", {"path": str(root)})
    history_before = len(
        call(engine, "alignment.get", {"chapter": "1", "verse": "1"})["result"]["history"]
    )

    started = call(engine, "ai.review.start", {
        "scope": "verse", "chapter": "1", "verse": "1", "mode": "advanced",
    })
    snapshot = _wait_for_ai_job(engine, started["result"]["jobId"])
    assert snapshot["state"] == "succeeded", snapshot

    context = call(engine, "alignment.get", {"chapter": "1", "verse": "1"})["result"]
    assert len(context["history"]) == history_before
