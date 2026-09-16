"""
Tests for `alignment.getRange` (#116): the alignment.get context for several
verses of one chapter in one round-trip, plus the per-verse `gaps` counts that
the cross-verse view needs. Real TranslationCoreProject fixtures on disk, real
BridgeEngine dispatch -- no mocks except the call-counting spy in
`test_get_range_computes_chapter_status_once`.
"""
import json
from pathlib import Path
from unittest import mock

import pytest

from bridge_service import BridgeEngine
from greek_room_engine.protocol import EngineRequest


def call(engine, method, params=None):
    return engine.handle_request(EngineRequest(id="t", method=method, params=params or {})).to_dict()


def _write_book(root: Path, book_id: str, chapters: dict, lang_id: str = "tam") -> None:
    """chapters: {chapter: {verse: {"text": str, "alignment": dict, "complete": bool}}}"""
    align_dir = root / ".apps" / "translationCore" / "alignmentData" / book_id
    align_dir.mkdir(parents=True, exist_ok=True)
    (root / book_id).mkdir(parents=True, exist_ok=True)
    (root / "manifest.json").write_text(json.dumps({
        "project": {"id": book_id, "name": book_id.upper()},
        "target_language": {"id": lang_id, "name": "Tamil"},
        "tc_version": "8", "tc_edit_version": "3.7.0",
    }), encoding="utf-8")

    for chapter, verses in chapters.items():
        align_chapter = {}
        text_chapter = {}
        for verse, data in verses.items():
            align_chapter[verse] = data["alignment"]
            text_chapter[verse] = data["text"]
            if data.get("complete"):
                completed_dir = (
                    root / ".apps" / "translationCore" / "tools" / "wordAlignment" / "completed" / str(chapter)
                )
                completed_dir.mkdir(parents=True, exist_ok=True)
                (completed_dir / f"{verse}.json").write_text(
                    json.dumps({"username": "tester", "modifiedTimestamp": "2026-01-01T00:00:00.000Z"}),
                    encoding="utf-8",
                )
        (align_dir / f"{chapter}.json").write_text(
            json.dumps(align_chapter, ensure_ascii=False), encoding="utf-8",
        )
        (root / book_id / f"{chapter}.json").write_text(
            json.dumps(text_chapter, ensure_ascii=False), encoding="utf-8",
        )
    (root / f"{book_id}.usfm").write_text(f"\\id {book_id.upper()}\n", encoding="utf-8")


def _top(word: str, strong: str) -> dict:
    return {"word": word, "strong": strong, "occurrence": 1, "occurrences": 1}


def _bottom(word: str) -> dict:
    return {"word": word, "occurrence": 1, "occurrences": 1}


def _group(top_words: list[dict], bottom_words: list[dict]) -> dict:
    return {"topWords": top_words, "bottomWords": bottom_words}


ELOHIM = _top("אֱלֹהִ֑ים", "H430")
BARA = _top("בָּרָ֣א", "H1254")

# "3-4" is a verse bridge -- real, already-seen input (CLAUDE.md gotcha 12).
BRIDGE_TOP_TOKEN_COUNT = 2
BRIDGE_WORD_BANK_SIZE = 3


@pytest.fixture
def fixture_project(tmp_path):
    root = tmp_path / "rut"
    _write_book(root, "rut", {
        "1": {
            # Fully aligned: one group holding both a source and a target word.
            "1": {
                "text": "தேவன்",
                "alignment": {"alignments": [_group([ELOHIM], [_bottom("தேவன்")])], "wordBank": []},
                "complete": True,
            },
            # Two target words, only one aligned; a second source token sits in a
            # group with no target words at all -> sourceUnmatched 1, targetUnmatched 1.
            "2": {
                "text": "தேவன் படைத்தார்",
                "alignment": {
                    "alignments": [
                        _group([ELOHIM], [_bottom("தேவன்")]),
                        _group([BARA], []),
                    ],
                    "wordBank": [_bottom("படைத்தார்")],
                },
                "complete": False,
            },
            # Bridge verse with an empty alignment: every source token in a group
            # with no target words, every target word still in the wordBank.
            "3-4": {
                "text": "ஆதியிலே தேவன் படைத்தார்",
                "alignment": {
                    "alignments": [_group([ELOHIM], []), _group([BARA], [])],
                    "wordBank": [_bottom("ஆதியிலே"), _bottom("தேவன்"), _bottom("படைத்தார்")],
                },
                "complete": False,
            },
            # Untouched.
            "5": {
                "text": "ஆதியிலே",
                "alignment": {"alignments": [], "wordBank": [_bottom("ஆதியிலே")]},
                "complete": False,
            },
        },
    })
    return root


@pytest.fixture
def engine(fixture_project):
    engine = BridgeEngine()
    opened = call(engine, "project.open", {"path": str(fixture_project)})
    assert opened["success"] is True, opened
    return engine


def _get_range(engine, chapter, verses):
    return call(engine, "alignment.getRange", {"chapter": chapter, "verses": verses})


def test_get_range_returns_one_context_per_verse_in_caller_order(engine):
    requested = ["2", "1", "3-4"]
    response = _get_range(engine, "1", requested)
    assert response["success"] is True, response
    result = response["result"]

    assert result["chapter"] == "1"
    assert [ctx["verse"] for ctx in result["verses"]] == requested
    assert all(ctx["chapter"] == "1" for ctx in result["verses"])

    for ctx in result["verses"]:
        single = call(engine, "alignment.get", {"chapter": "1", "verse": ctx["verse"]})
        assert single["success"] is True, single
        assert set(ctx.keys()) == set(single["result"].keys())
        # Same content too, not just the same shape.
        assert ctx == single["result"]

    status = call(engine, "alignment.status", {"chapter": "1"})
    assert status["success"] is True, status
    assert result["chapterStatus"] == status["result"]["counts"]
    assert result["chapterStatus"] == {"complete": 1, "partial": 1, "untouched": 2, "invalid": 0}
    for ctx in result["verses"]:
        assert ctx["chapterStatus"] == result["chapterStatus"]


def test_get_range_gap_counts(engine):
    result = _get_range(engine, "1", ["1", "2", "3-4"])["result"]
    by_verse = {ctx["verse"]: ctx for ctx in result["verses"]}

    assert by_verse["1"]["gaps"] == {"sourceUnmatched": 0, "targetUnmatched": 0}
    assert by_verse["2"]["gaps"] == {"sourceUnmatched": 1, "targetUnmatched": 1}

    bridge = by_verse["3-4"]
    assert len(bridge["topTokens"]) == BRIDGE_TOP_TOKEN_COUNT
    assert len(bridge["alignment"]["wordBank"]) == BRIDGE_WORD_BANK_SIZE
    assert bridge["gaps"] == {
        "sourceUnmatched": BRIDGE_TOP_TOKEN_COUNT,
        "targetUnmatched": BRIDGE_WORD_BANK_SIZE,
    }


def test_get_range_preserves_bridge_and_lettered_verse_strings(engine):
    result = _get_range(engine, "1", ["3-4"])["result"]
    assert len(result["verses"]) == 1
    assert result["verses"][0]["verse"] == "3-4"
    assert result["verses"][0]["alignment"]["wordBank"]


def test_get_range_deduplicates_while_preserving_first_occurrence(engine):
    result = _get_range(engine, "1", ["2", "1", "2", "5", "1"])["result"]
    assert [ctx["verse"] for ctx in result["verses"]] == ["2", "1", "5"]


def test_get_range_rejects_unknown_verse_and_chapter(engine):
    unknown_verse = _get_range(engine, "1", ["1", "99"])
    assert unknown_verse["success"] is False
    assert unknown_verse["error"]["code"] == "project_error"
    assert "1:99" in unknown_verse["error"]["message"]

    unknown_chapter = _get_range(engine, "7", ["1"])
    assert unknown_chapter["success"] is False
    assert unknown_chapter["error"]["code"] == "project_error"
    assert "Chapter 7" in unknown_chapter["error"]["message"]

    empty = _get_range(engine, "1", [])
    assert empty["success"] is False
    assert empty["error"]["code"] == "project_error"


def test_get_range_computes_chapter_status_once(engine):
    with mock.patch.object(
        engine, "alignment_status", wraps=engine.alignment_status,
    ) as spy:
        response = _get_range(engine, "1", ["1", "2", "5"])
    assert response["success"] is True, response
    assert len(response["result"]["verses"]) == 3
    assert spy.call_count == 1


def test_alignment_get_still_includes_gaps(engine):
    response = call(engine, "alignment.get", {"chapter": "1", "verse": "2"})
    assert response["success"] is True, response
    assert response["result"]["gaps"] == {"sourceUnmatched": 1, "targetUnmatched": 1}
