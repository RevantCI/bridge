"""
Tests for `alignment.gapScan` (#137): every verse of one chapter with its
alignment gaps named rather than merely counted.

The load-bearing test here is `test_gap_scan_names_exactly_what_get_range_counts`.
Before #137 the gap sets were computed in three places -- twice inside
`_alignment_context` (the first of them dead) and a third time client-side in
`alignmentGroups.ts` -- so the point of the shared helper is that a count and a
list can no longer disagree. That test is what would fail if someone
reintroduced a second definition.

Real TranslationCoreProject fixtures on disk, real BridgeEngine dispatch, no
mocks.
"""
import json
from pathlib import Path

import pytest

from bridge_service import BridgeEngine
from greek_room_engine.protocol import EngineRequest


def call(engine, method, params=None):
    return engine.handle_request(EngineRequest(id="t", method=method, params=params or {})).to_dict()


def _top(word: str, strong: str) -> dict:
    return {"word": word, "strong": strong, "occurrence": 1, "occurrences": 1}


def _bottom(word: str) -> dict:
    return {"word": word, "occurrence": 1, "occurrences": 1}


def _group(top_words: list[dict], bottom_words: list[dict]) -> dict:
    return {"topWords": top_words, "bottomWords": bottom_words}


ELOHIM = _top("אֱלֹהִ֑ים", "H430")
BARA = _top("בָּרָ֣א", "H1254")


def _write_book(root: Path, book_id: str, chapters: dict) -> None:
    align_dir = root / ".apps" / "translationCore" / "alignmentData" / book_id
    align_dir.mkdir(parents=True, exist_ok=True)
    (root / book_id).mkdir(parents=True, exist_ok=True)
    (root / "manifest.json").write_text(json.dumps({
        "project": {"id": book_id, "name": book_id.upper()},
        "target_language": {"id": "tam", "name": "Tamil"},
        "tc_version": "8", "tc_edit_version": "3.7.0",
    }), encoding="utf-8")
    for chapter, verses in chapters.items():
        align_chapter = {verse: data["alignment"] for verse, data in verses.items()}
        text_chapter = {verse: data["text"] for verse, data in verses.items()}
        (align_dir / f"{chapter}.json").write_text(
            json.dumps(align_chapter, ensure_ascii=False), encoding="utf-8",
        )
        (root / book_id / f"{chapter}.json").write_text(
            json.dumps(text_chapter, ensure_ascii=False), encoding="utf-8",
        )
    (root / f"{book_id}.usfm").write_text(f"\\id {book_id.upper()}\n", encoding="utf-8")


@pytest.fixture
def fixture_project(tmp_path):
    root = tmp_path / "rut"
    _write_book(root, "rut", {
        "1": {
            # Fully aligned: no gap on either side.
            "1": {
                "text": "தேவன்",
                "alignment": {"alignments": [_group([ELOHIM], [_bottom("தேவன்")])], "wordBank": []},
            },
            # One source token in a group with no target words, one target word
            # still in the bank -> one gap on each side.
            "2": {
                "text": "தேவன் படைத்தார்",
                "alignment": {
                    "alignments": [_group([ELOHIM], [_bottom("தேவன்")]), _group([BARA], [])],
                    "wordBank": [_bottom("படைத்தார்")],
                },
            },
            # A verse bridge -- real input, and its verse string must survive
            # the scan unparsed (CLAUDE.md gotcha 12).
            "3-4": {
                "text": "ஆதியிலே தேவன்",
                "alignment": {
                    "alignments": [_group([ELOHIM], []), _group([BARA], [])],
                    "wordBank": [_bottom("ஆதியிலே"), _bottom("தேவன்")],
                },
            },
            # Untouched: no groups at all, one word in the bank.
            "5": {
                "text": "ஆதியிலே",
                "alignment": {"alignments": [], "wordBank": [_bottom("ஆதியிலே")]},
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


def _scan(engine, chapter="1"):
    response = call(engine, "alignment.gapScan", {"chapter": chapter})
    assert response["success"] is True, response
    return response["result"]


def _by_verse(result):
    return {entry["verse"]: entry for entry in result["verses"]}


def test_gap_scan_names_exactly_what_get_range_counts(engine):
    """The anti-drift test: one definition of "gap", so the named list and the
    count that ships beside it can never disagree."""
    scanned = _by_verse(_scan(engine))
    verses = list(scanned)
    ranged = call(engine, "alignment.getRange", {"chapter": "1", "verses": verses})["result"]

    for context in ranged["verses"]:
        entry = scanned[context["verse"]]
        assert entry["gaps"] == context["gaps"], context["verse"]
        assert len(entry["sourceGaps"]) == context["gaps"]["sourceUnmatched"]
        assert len(entry["targetGaps"]) == context["gaps"]["targetUnmatched"]


def test_gap_scan_names_the_unaligned_tokens(engine):
    scanned = _by_verse(_scan(engine))

    assert scanned["1"]["gaps"] == {"sourceUnmatched": 0, "targetUnmatched": 0}
    assert scanned["1"]["sourceGaps"] == []

    assert scanned["2"]["gaps"] == {"sourceUnmatched": 1, "targetUnmatched": 1}
    assert [token["word"] for token in scanned["2"]["sourceGaps"]] == [BARA["word"]]
    assert [token["word"] for token in scanned["2"]["targetGaps"]] == ["படைத்தார்"]

    # An untouched verse: no group holds the source token, so it is a gap.
    assert scanned["5"]["gaps"]["targetUnmatched"] == 1


def test_gap_scan_carries_the_signature_the_link_store_keys_on(engine):
    """A caller that had to rebuild `word U+241F occurrence U+241F occurrences`
    by hand would be one typo from a link that resolves to nothing."""
    gap = _by_verse(_scan(engine))["2"]["sourceGaps"][0]
    assert gap["signature"] == f"{BARA['word']}␟1␟1"
    assert gap["id"].startswith("H")


def test_gap_scan_keeps_verse_bridges_opaque(engine):
    scanned = _by_verse(_scan(engine))
    assert "3-4" in scanned
    assert scanned["3-4"]["verse"] == "3-4"
    assert scanned["3-4"]["gaps"] == {"sourceUnmatched": 2, "targetUnmatched": 2}


def test_gap_scan_totals_add_up(engine):
    result = _scan(engine)
    totals = result["totals"]
    assert totals["sourceUnmatched"] == sum(e["gaps"]["sourceUnmatched"] for e in result["verses"])
    assert totals["targetUnmatched"] == sum(e["gaps"]["targetUnmatched"] for e in result["verses"])
    assert totals["verses"] == len(result["verses"])
    assert totals["versesWithGaps"] == sum(
        1 for e in result["verses"]
        if e["gaps"]["sourceUnmatched"] or e["gaps"]["targetUnmatched"]
    )


def test_an_active_cross_verse_link_closes_the_gap_on_both_ends(engine):
    """#117's rule, which the scan inherits through the shared helper: a source
    token realized in another verse and the target word realizing it are both
    spoken for, even though tC alignment cannot say so."""
    before = _by_verse(_scan(engine))
    source_id = before["2"]["sourceGaps"][0]["id"]
    target_id = before["5"]["targetGaps"][0]["id"]

    linked = call(engine, "alignment.crossVerse.link", {
        "source": {"chapter": "1", "verse": "2", "topId": source_id},
        "target": {"chapter": "1", "verse": "5", "bottomId": target_id},
    })
    assert linked["success"] is True, linked

    after = _by_verse(_scan(engine))
    assert after["2"]["gaps"]["sourceUnmatched"] == before["2"]["gaps"]["sourceUnmatched"] - 1
    assert after["5"]["gaps"]["targetUnmatched"] == before["5"]["gaps"]["targetUnmatched"] - 1
    assert after["2"]["crossVerseRealized"] == 1
    assert after["5"]["crossVerseAccounted"] == 1
    assert BARA["word"] not in [token["word"] for token in after["2"]["sourceGaps"]]


def test_gap_scan_survives_one_unreadable_verse(engine, fixture_project):
    """A chapter-wide view that dies on one bad verse is useless exactly when it
    is most needed."""
    chapter_path = (
        fixture_project / ".apps" / "translationCore" / "alignmentData" / "rut" / "1.json"
    )
    data = json.loads(chapter_path.read_text(encoding="utf-8"))
    data["2"] = "not an alignment object"
    chapter_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    scanned = _by_verse(_scan(engine))
    assert scanned["2"]["readable"] is False
    assert scanned["2"]["sourceGaps"] == []
    # The readable verses are still reported.
    assert scanned["1"]["readable"] is True
    assert scanned["5"]["gaps"]["targetUnmatched"] == 1


def test_gap_scan_rejects_an_unknown_chapter(engine):
    response = call(engine, "alignment.gapScan", {"chapter": "99"})
    assert response["success"] is False
    assert "99" in response["error"]["message"]
