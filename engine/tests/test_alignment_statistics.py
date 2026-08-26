"""
Tests for Phase 6's UAlign-style corpus statistics
(tc_ai_bridge/alignment_statistics.py) — real TranslationCoreProject
fixtures and real Uroman + vendored Smart Edit Distance, not mocks, matching
this project's own standing practice (see docs/BUILD_LOG.md).
"""
import json
import time
from pathlib import Path

import pytest

from bridge_service import BridgeEngine
from greek_room_engine.protocol import EngineRequest
from tc_ai_bridge import alignment_statistics as corpus_stats
from tc_ai_bridge.tc_project import TranslationCoreProject


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


def _group(top_word: str, bottom_word: str, strong: str = "H430") -> dict:
    return {
        "topWords": [{"word": top_word, "strong": strong, "occurrence": 1, "occurrences": 1}],
        "bottomWords": [{"word": bottom_word, "occurrence": 1, "occurrences": 1}],
    }


@pytest.fixture
def fixture_project(tmp_path):
    root = tmp_path / "rut"
    _write_book(root, "rut", {
        "1": {
            "1": {
                "text": "தேவன்",
                "alignment": {"alignments": [_group("אֱלֹהִ֑ים", "தேவன்")], "wordBank": []},
                "complete": True,
            },
            "2": {
                "text": "தேவன்",
                "alignment": {"alignments": [_group("אֱלֹהִ֑ים", "தேவன்")], "wordBank": []},
                "complete": False,  # NOT complete — must not be counted
            },
        },
    })
    return root


def test_build_corpus_stats_only_counts_completed_verses(fixture_project):
    project = TranslationCoreProject(fixture_project)
    table = corpus_stats.build_corpus_stats(project, include_collection=False)
    assert table.verses_scanned == 1
    assert table.pair_counts[("אֱלֹהִ֑ים", "தேவன்")] == 1
    assert table.source_counts["אֱלֹהִ֑ים"] == 1
    assert table.target_counts["தேவன்"] == 1


def test_pair_stats_probability_and_pmi_match_hand_computed_values():
    table = corpus_stats.CorpusStatsTable()
    # 3 instances of source "A": twice paired with target "x", once with "y".
    # 1 extra unrelated instance of target "x" paired with source "B".
    table.source_counts["A"] = 3
    table.source_counts["B"] = 1
    table.target_counts["x"] = 3
    table.target_counts["y"] = 1
    table.pair_counts[("A", "x")] = 2
    table.pair_counts[("A", "y")] = 1
    table.pair_counts[("B", "x")] = 1
    table.total_pairs = 4

    stats = table.pair_stats("A", "x", with_sed_boost=False)
    assert stats.joint_count == 2
    assert stats.source_count == 3
    assert stats.target_count == 3
    assert stats.translation_probability == pytest.approx(2 / 3)
    # PMI(A,x) = log((joint+1)/(expected+1)), expected = (3/4)*(3/4)*4 = 2.25
    assert stats.pmi == pytest.approx(__import__("math").log((2 + 1) / (2.25 + 1)))
    assert stats.sed_cost is None
    assert stats.sed_boosted_probability is None

    unseen = table.pair_stats("B", "y", with_sed_boost=False)
    assert unseen.joint_count == 0
    assert unseen.translation_probability == 0.0


def test_multi_book_collection_aggregates_normalized_siblings_and_skips_lazy(tmp_path):
    primary = tmp_path / "gen"
    _write_book(primary, "gen", {
        "1": {"1": {
            "text": "தேவன்", "alignment": {"alignments": [_group("אֱלֹהִ֑ים", "தேவன்")], "wordBank": []},
            "complete": True,
        }},
    })
    normalized_sibling = tmp_path / "exo"
    _write_book(normalized_sibling, "exo", {
        "1": {"1": {
            "text": "தேவன்", "alignment": {"alignments": [_group("אֱלֹהִ֑ים", "தேவன்")], "wordBank": []},
            "complete": True,
        }},
    })
    lazy_sibling = tmp_path / "lev"
    _write_book(lazy_sibling, "lev", {
        "1": {"1": {
            "text": "தேவன்", "alignment": {"alignments": [_group("אֱלֹהִ֑ים", "தேவன்")], "wordBank": []},
            "complete": True,
        }},
    })
    (lazy_sibling / ".bridge").mkdir(parents=True, exist_ok=True)
    (lazy_sibling / ".bridge" / "lazy-import.json").write_text(
        json.dumps({"sourceCopy": "source.usfm", "bookId": "lev", "metadata": {}}), encoding="utf-8",
    )

    collection = {
        "projects": [
            {"path": str(primary), "bookId": "gen"},
            {"path": str(normalized_sibling), "bookId": "exo"},
            {"path": str(lazy_sibling), "bookId": "lev"},
        ]
    }
    for project_dir in (primary, normalized_sibling, lazy_sibling):
        (project_dir / ".bridge").mkdir(parents=True, exist_ok=True)
        (project_dir / ".bridge" / "collection.json").write_text(json.dumps(collection), encoding="utf-8")

    project = TranslationCoreProject(primary)
    table = corpus_stats.build_corpus_stats(project, include_collection=True)

    assert sorted(table.books_scanned) == ["exo", "gen"]  # lev skipped: still lazy
    assert table.verses_scanned == 2
    assert table.pair_counts[("אֱלֹהִ֑ים", "தேவன்")] == 2


def test_corpus_stats_protocol_summary_and_for_verse(fixture_project):
    engine = BridgeEngine()
    call(engine, "project.open", {"path": str(fixture_project)})

    summary = call(engine, "alignment.corpusStats.summary")["result"]
    assert summary["versesScanned"] == 1
    assert summary["distinctPairs"] == 1
    assert summary["totalLinkInstances"] == 1

    for_verse = call(engine, "alignment.corpusStats.forVerse", {"chapter": "1", "verse": "1"})["result"]
    assert for_verse["pairs"][0]["sourceWord"] == "אֱלֹהִ֑ים"
    assert for_verse["pairs"][0]["targetWord"] == "தேவன்"
    assert for_verse["pairs"][0]["jointCount"] == 1
    assert for_verse["pairs"][0]["translationProbability"] == pytest.approx(1.0)


def test_corpus_stats_cache_invalidated_when_a_verse_is_newly_completed(tmp_path):
    root = tmp_path / "rut"
    _write_book(root, "rut", {
        "1": {
            "1": {
                "text": "தேவன்",
                "alignment": {"alignments": [_group("אֱלֹהִ֑ים", "தேவன்")], "wordBank": []},
                "complete": False,
            },
        },
    })
    engine = BridgeEngine()
    call(engine, "project.open", {"path": str(root)})

    before = call(engine, "alignment.corpusStats.summary")["result"]
    assert before["versesScanned"] == 0

    context = call(engine, "alignment.get", {"chapter": "1", "verse": "1"})["result"]
    completed = call(engine, "alignment.complete", {"chapter": "1", "verse": "1"})
    assert completed["success"] is True

    after = call(engine, "alignment.corpusStats.summary")["result"]
    assert after["versesScanned"] == 1
    assert after["totalLinkInstances"] == 1


def test_sed_boost_present_for_real_uroman_and_smart_edit_distance():
    """No mocks: real Uroman romanization + the real vendored Smart Edit
    Distance cost function, same as Phase 5's NamesAdapter tests. A Greek
    proper name (Ἰωάννης, romanizes to "Ioannes") aligned to a target
    spelling romanizing to "Ioanes" (a plausible one-letter transliteration
    slip, the exact shape of thing SED-boost exists to catch) should score
    a real, finite SED cost (verified directly: 0.02, well under the max
    cost of 1) and produce a boosted probability at least as high as the
    plain co-occurrence probability. Not every cross-script "same name"
    pair scores this low — verified separately that a real but more
    divergent romanization gap (Ἰωάννης "Ioannes" vs Tamil யோவான்
    "yoovaan") exceeds SED's max_cost=1 ceiling entirely (cost is None,
    handled by the None/None fallback below), which is expected: SED is
    tuned for near-duplicate spellings (Phase 5's own docstring), not open
    transliteration variance."""
    if corpus_stats._ensure_uroman() is None or corpus_stats._load_sed_module() is None:
        pytest.skip("uroman / vendored smart_edit_distance not available in this environment")

    table = corpus_stats.CorpusStatsTable()
    table.source_counts["Ἰωάννης"] = 1
    table.target_counts["Ioanes"] = 1
    table.pair_counts[("Ἰωάννης", "Ioanes")] = 1
    table.total_pairs = 1

    stats = table.pair_stats("Ἰωάννης", "Ioanes", with_sed_boost=True)
    assert stats.sed_cost is not None
    assert 0.0 <= stats.sed_cost < 1.0
    assert stats.sed_boosted_probability is not None
    assert stats.sed_boosted_probability >= stats.translation_probability


def test_build_corpus_stats_performance_over_a_realistically_sized_completed_corpus(tmp_path):
    """Per this project's own standing rule (measure, don't guess — see the
    Phase 5 bigram-blocking and Phase 4 concurrency investigations), this
    actually times a synthetic but realistically-shaped corpus rather than
    asserting the linear-scan design is fast. 50 chapters x 40 completed
    verses x ~6 token pairs = 2,000 completed verses, comparable to a
    heavily-aligned single large book."""
    root = tmp_path / "big"
    chapters = {}
    for c in range(1, 51):
        verses = {}
        for v in range(1, 41):
            pairs = [
                _group(f"src{c}_{v}_{i}", f"tgt{c}_{v}_{i}")
                for i in range(6)
            ]
            groups = []
            for p in pairs:
                groups.append(p)
            verses[str(v)] = {
                "text": " ".join(g["bottomWords"][0]["word"] for g in groups),
                "alignment": {"alignments": groups, "wordBank": []},
                "complete": True,
            }
        chapters[str(c)] = verses
    _write_book(root, "big", chapters)

    project = TranslationCoreProject(root)
    start = time.perf_counter()
    table = corpus_stats.build_corpus_stats(project, include_collection=False)
    elapsed = time.perf_counter() - start

    assert table.verses_scanned == 2000
    assert table.total_pairs == 2000 * 6
    # Generous ceiling, not a tight regression bound (no known-bad prior
    # implementation to compare against, unlike the bigram-blocking case) —
    # this is a linear scan over already-completed verses, dominated by
    # JSON parsing of 50 chapter files, not by any O(n^2) comparison.
    assert elapsed < 5.0, f"build_corpus_stats took {elapsed:.2f}s for 2000 completed verses"
