"""
Tests for Phase 7's AI alignment-proposal wiring
(alignment.aiPropose / alignment.aiApplyProposal in bridge_service.py).

tc_ai_bridge/ai_client.py's propose_alignment() and
tc_ai_bridge/alignment_reliability.py's compile_link_proposal() were real,
already-implemented scaffolding before this phase — see
docs/DEVELOPER_HANDOFF.md's Phase 7 section — but nothing in the protocol
called them and neither had any test coverage. These tests exercise the new
protocol methods end to end through BridgeEngine.handle_request, using a
fake HTTP transport (the same Transport dependency-injection seam
OpenAIResponsesClient already exposes, now threaded one level up via
BridgeEngine(ai_transport=...)) so no real OpenAI-compatible API key is
required.
"""
import json
from pathlib import Path

import pytest

from bridge_service import BridgeEngine
from greek_room_engine.protocol import EngineRequest
from tc_ai_bridge.secret_store import AppSettings


def call(engine, method, params=None):
    return engine.handle_request(EngineRequest(id="t", method=method, params=params or {})).to_dict()


def _tok(word, strong="H430", occurrence=1, occurrences=1):
    return {"word": word, "strong": strong, "occurrence": occurrence, "occurrences": occurrences}


def _tok_b(word, occurrence=1, occurrences=1):
    # Real on-disk alignment data always carries "type": "bottomWord" on every
    # bottom-side token (see TokenRef.to_dict(bottom=True)) — the save-conflict
    # check in tc_project.py's save_verse_alignment compares the raw on-disk dict
    # byte-for-byte against expectedOriginal, so omitting it here would make every
    # apply/save spuriously look like a stale-editor conflict.
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
    word bank — enough surface for gap_fill mode to have real work to do."""
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


def _fake_transport(links=None, implicit_top_ids=None, target_only_ids=None):
    payload = {
        "links": links or [],
        "implicit_top_ids": implicit_top_ids or [],
        "target_only_ids": target_only_ids or [],
        "review_notes": [],
    }

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


def _open(engine, fixture_project):
    call(engine, "project.open", {"path": str(fixture_project)})


def test_ai_propose_requires_configured_api_key(fixture_project, tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    settings = AppSettings(path=tmp_path / "settings.json")
    engine = BridgeEngine(settings=settings, ai_transport=_fake_transport())
    _open(engine, fixture_project)

    result = call(engine, "alignment.aiPropose", {"chapter": "1", "verse": "1"})

    assert result["success"] is False
    assert result["error"]["code"] == "ai_error"
    assert "API key" in result["error"]["message"]


def test_ai_propose_compiles_accepted_link_and_records_usage(fixture_project, tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    settings = AppSettings(path=tmp_path / "settings.json")
    settings.set_api_key("sk-test-123")
    # H002 = "בָּרָא" (the unresolved source token), T002 = "படைத்தார்" (the unresolved
    # target token) — see make_inventory's H00N/T00N ordering: group order, then wordBank.
    transport = _fake_transport(links=[
        {"top_id": "H002", "bottom_id": "T002", "confidence": 0.9, "reason": "created"},
    ])
    engine = BridgeEngine(settings=settings, ai_transport=transport)
    _open(engine, fixture_project)

    result = call(engine, "alignment.aiPropose", {"chapter": "1", "verse": "1"})
    assert result["success"] is True
    proposal = result["result"]["proposal"]
    assert proposal["requires_human_review"] is False
    assert proposal["mode"] == "gap_fill"
    compiled = [g for g in proposal["groups"] if g.get("origin") == "ai_compiled"]
    assert len(compiled) == 1
    assert compiled[0]["top_ids"] == ["H002"]
    assert compiled[0]["bottom_ids"] == ["T002"]
    protected = [g for g in proposal["groups"] if g.get("origin") == "existing"]
    assert len(protected) == 1  # the אֱלֹהִ֑ים/தேவன் group must survive untouched

    assert result["result"]["usage"]["totalTokens"] == 160
    # settings.record_ai_usage() was a real, already-implemented hook that nothing
    # called before this phase — confirm alignment.aiPropose actually calls it.
    totals = settings.get_ai_usage_totals()
    assert totals["tokens"] == 160
    assert totals["estimatedCostUSD"] > 0


def test_ai_propose_never_lets_ai_bridge_two_established_groups(tmp_path, monkeypatch):
    """A link between two DIFFERENT already-established/protected source-target
    pairs is a real conflict, not silently applied — alignment_reliability's own
    protection, exercised here through the actual protocol call for the first time."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    root = tmp_path / "rut"
    alignment = {
        "alignments": [
            {"topWords": [_tok("אֱלֹהִ֑ים", "H430")], "bottomWords": [_tok_b("தேவன்")]},
            {"topWords": [_tok("הָאָרֶץ", "H776")], "bottomWords": [_tok_b("பூமியை")]},
        ],
        "wordBank": [],
    }
    _write_book(root, "rut", "1", "1", "தேவன் பூமியை", alignment)

    settings = AppSettings(path=tmp_path / "settings.json")
    settings.set_api_key("sk-test-123")
    # H001 ("אֱלֹהִ֑ים") is already grouped with T001 ("தேவன்"); H002 ("הָאָרֶץ") is
    # already grouped with T002 ("பூமியை"). Ask the (fake) AI to cross-link H001 -> T002
    # — bridging two different established groups must never be auto-applied.
    transport = _fake_transport(links=[
        {"top_id": "H001", "bottom_id": "T002", "confidence": 0.95, "reason": "spurious cross-link"},
    ])
    engine = BridgeEngine(settings=settings, ai_transport=transport)
    _open(engine, root)

    result = call(engine, "alignment.aiPropose", {"chapter": "1", "verse": "1"})
    assert result["success"] is True
    proposal = result["result"]["proposal"]
    assert proposal["requires_human_review"] is True
    assert len(proposal["conflicts"]) == 1
    assert proposal["conflicts"][0]["type"] == "protected_alignment_conflict"
    # Both established groups must survive completely unchanged.
    protected = {tuple(g["top_ids"]): tuple(g["bottom_ids"]) for g in proposal["groups"] if g.get("origin") == "existing"}
    assert protected == {("H001",): ("T001",), ("H002",): ("T002",)}


def test_ai_apply_proposal_saves_through_the_normal_identity_checked_pipeline(fixture_project, tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    settings = AppSettings(path=tmp_path / "settings.json")
    settings.set_api_key("sk-test-123")
    transport = _fake_transport(links=[
        {"top_id": "H002", "bottom_id": "T002", "confidence": 0.9, "reason": "created"},
    ])
    engine = BridgeEngine(settings=settings, ai_transport=transport)
    _open(engine, fixture_project)

    proposed = call(engine, "alignment.aiPropose", {"chapter": "1", "verse": "1"})["result"]
    context_before = call(engine, "alignment.get", {"chapter": "1", "verse": "1"})["result"]

    applied = call(engine, "alignment.aiApplyProposal", {
        "chapter": "1", "verse": "1",
        "proposal": proposed["proposal"],
        "expectedOriginal": context_before["alignment"],
    })
    assert applied["success"] is True
    context_after = applied["result"]
    # Word bank is now empty: the AI-compiled group absorbed the previously
    # unresolved target token, and the previously-empty-bottom source group
    # gained a real target link.
    assert context_after["issues"] == [] or all(
        "missing" not in issue for issue in context_after["issues"]
    )
    groups = context_after["groups"]
    new_group = next(g for g in groups if "படைத்தார்" in [
        item["word"] for item in context_after["bottomTokens"] if item["id"] in g["bottomIds"]
    ])
    assert new_group is not None
