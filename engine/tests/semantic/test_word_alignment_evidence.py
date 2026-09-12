"""V11-000a: Stage 6B word-alignment evidence -- source/target resolvers and
precedent projection. See docs/V11-000_STAGE6B_ALIGNMENT_SPIKE.md.

The target-resolver tests below are the tokenization-disagreement cases the
implementation prompt asked to write first, explicitly: a bare verse
reference ("3:16"), a word in inline quotes, a hyphenated and an
apostrophised word, a repeated word with punctuation between shifting the
occurrence count, and a bottomWord no longer present in the current text.
Confirmed against the real tokenizers (tc-whitespace-v1 vs.
bridge-unicode-word-v1) rather than assumed -- hyphenated/apostrophised
words turn out to agree between the two, so those are "still resolves"
checks, not disagreement checks.
"""
from __future__ import annotations

import json
from pathlib import Path

from tc_ai_bridge.models import TokenRef
from tc_ai_bridge.original_language_resources import resource_for_book
from tc_ai_bridge.passage_semantic_runtime import PassageSemanticRuntime
from tc_ai_bridge.tc_project import TranslationCoreProject
from tc_ai_bridge.word_alignment_evidence import (
    alignment_precedents_for_range, resolve_source_token_id, resolve_target_token_id,
)


# --- source resolver: real bundled UGNT tokens, PHP 1:3 --------------------

def test_resolves_a_real_ugnt_source_token_by_word_and_occurrence() -> None:
    resource = resource_for_book("PHP")
    assert resource is not None
    # Legacy classic-dictionary Strong's form (no trailing UGNT variant
    # digit) -- the pack itself stores "G23160" for this token.
    ref = TokenRef(word="Θεῷ", occurrence=1, occurrences=1, strong="G2316", lemma="θεός")
    instance_id = resolve_source_token_id(resource, "PHP", "1", "3", ref)
    assert instance_id is not None
    assert instance_id.startswith("source-token-")


def test_source_resolution_misses_when_occurrence_does_not_match() -> None:
    resource = resource_for_book("PHP")
    assert resource is not None
    ref = TokenRef(word="Θεῷ", occurrence=2, occurrences=1)
    assert resolve_source_token_id(resource, "PHP", "1", "3", ref) is None


def test_source_resolution_misses_an_unknown_word() -> None:
    resource = resource_for_book("PHP")
    assert resource is not None
    ref = TokenRef(word="not-a-real-greek-word", occurrence=1, occurrences=1)
    assert resolve_source_token_id(resource, "PHP", "1", "3", ref) is None


def test_source_resolution_ignores_strongs_five_digit_variant_padding() -> None:
    """G23160 (pack) and G2316 (classic dictionary) must resolve the same
    token -- word+occurrence already disambiguates, so this only confirms
    the reinforcement score never blocks a match on this difference."""
    resource = resource_for_book("PHP")
    assert resource is not None
    padded = TokenRef(word="Θεῷ", occurrence=1, occurrences=1, strong="G23160")
    classic = TokenRef(word="Θεῷ", occurrence=1, occurrences=1, strong="G2316")
    assert resolve_source_token_id(resource, "PHP", "1", "3", padded) \
        == resolve_source_token_id(resource, "PHP", "1", "3", classic)


# --- target resolver: tokenization-disagreement cases ----------------------

def _resolve(text: str, ref: TokenRef) -> str | None:
    return resolve_target_token_id(
        project_id="p1", book="PHP", displayed_reference="PHP 1:1",
        text_revision="rev-1", current_text=text, profile="bridge-unicode-word-v1",
        ref=ref,
    )


def test_target_resolution_matches_a_plain_word() -> None:
    ref = TokenRef(word="anchor", occurrence=1, occurrences=1)
    instance_id = _resolve("this is the anchor word", ref)
    assert instance_id is not None
    assert instance_id.startswith("target-token-")


def test_target_resolution_disagrees_on_a_bare_verse_reference() -> None:
    # tc-whitespace-v1 keeps "3:16" as one token; bridge-unicode-word-v1
    # splits it into "3", ":", "16" -- no single token equals "3:16".
    ref = TokenRef(word="3:16", occurrence=1, occurrences=1)
    assert _resolve("see John 3:16 today", ref) is None


def test_target_resolution_disagrees_on_a_word_in_inline_quotes() -> None:
    # tc-whitespace-v1 attaches the quote mark to the word ('"hello');
    # bridge-unicode-word-v1 emits the quote as its own punctuation token.
    ref = TokenRef(word='"hello', occurrence=1, occurrences=1)
    assert _resolve('he said "hello world" to me', ref) is None


def test_target_resolution_agrees_on_a_hyphenated_word() -> None:
    ref = TokenRef(word="well-known", occurrence=1, occurrences=1)
    assert _resolve("a well-known friend", ref) is not None


def test_target_resolution_agrees_on_an_apostrophised_word() -> None:
    ref = TokenRef(word="Peter’s", occurrence=1, occurrences=1)
    assert _resolve("it is Peter’s book", ref) is not None


def test_target_resolution_disagrees_when_interleaved_punctuation_shifts_occurrence_count() -> None:
    # Under tc-whitespace-v1, "love," and "love" are different normalized
    # forms, so tC's own bottomWord for the bare "love" would record
    # occurrences=2. bridge-unicode-word-v1 splits the comma off, so the
    # bare form "love" occurs 3 times in this text -- the counts disagree.
    ref = TokenRef(word="love", occurrence=1, occurrences=2)
    assert _resolve("love, love love", ref) is None


def test_target_resolution_returns_none_for_a_bottom_word_no_longer_in_the_text() -> None:
    ref = TokenRef(word="obsolete", occurrence=1, occurrences=1)
    assert _resolve("the verse was edited", ref) is None


# --- precedent projection: a real completed alignment, end to end ---------

# A single-word verse, like the pre-existing HUMAN_PRECEDENT test
# (test_human_approved_precedent_uses_revision_bound_token_identity) uses --
# a longer target text produces overlapping candidate spans that all touch
# the aligned token (e.g. a 2-word span containing "God" gets the same
# WORD_ALIGNMENT hit a 1-word "God" span does), which is a genuine, expected
# AMBIGUOUS outcome elsewhere, not what this fixture is testing.
PHP_1_3_EN = "God"


def _runtime_with_completed_alignment(tmp_path: Path) -> PassageSemanticRuntime:
    root = tmp_path / "php-en"
    (root / "php").mkdir(parents=True)
    alignment_dir = root / ".apps" / "translationCore" / "alignmentData" / "php"
    alignment_dir.mkdir(parents=True)
    (root / "manifest.json").write_text(json.dumps({
        "project": {"id": "php", "name": "Philippians"},
        "target_language": {"id": "en"}, "resource": {"id": "test"}, "tc_version": "8",
    }), encoding="utf-8")
    (root / "php" / "1.json").write_text(
        json.dumps({"3": PHP_1_3_EN}, ensure_ascii=False), encoding="utf-8",
    )
    # "Θεῷ" (occurrence 1 of 1, strong G2316, lemma θεός) -> "God".
    alignment_payload = {
        "3": {
            "alignments": [{
                "topWords": [{
                    "word": "Θεῷ", "occurrence": 1, "occurrences": 1,
                    "strong": "G2316", "lemma": "θεός", "morph": "Gr,N,,,,,DMS,",
                }],
                "bottomWords": [{"word": "God", "occurrence": 1, "occurrences": 1}],
            }],
            "wordBank": [],
        },
    }
    (alignment_dir / "1.json").write_text(json.dumps(alignment_payload), encoding="utf-8")
    completed_dir = root / ".apps" / "translationCore" / "tools" / "wordAlignment" / "completed" / "1"
    completed_dir.mkdir(parents=True)
    (completed_dir / "3.json").write_text(
        json.dumps({"username": "tester", "modifiedTimestamp": "2026-01-01T00:00:00.000Z"}),
        encoding="utf-8",
    )
    (root / "php.usfm").write_text("\\id PHP\n\\c 1\n\\p\n\\v 3 OLD IMPORTED\n", encoding="utf-8")
    return PassageSemanticRuntime(TranslationCoreProject(root), f"alignment-evidence-{tmp_path.name}")


def test_alignment_precedents_for_range_resolves_a_completed_group(tmp_path: Path) -> None:
    runtime = _runtime_with_completed_alignment(tmp_path)
    source = runtime.source_semantic.build_range("1", "3")
    target = runtime.target_semantic.build_range("1", "3")
    source_token_id = next(
        unit for unit in source["units"]
        if unit.get("semanticFeatures", {}).get("lemma") == "θεός"
    )["tokenInstanceIds"][0]
    target_token_id = next(token for token in target["tokens"] if token["rawForm"] == "God")["id"]

    precedents = alignment_precedents_for_range(runtime, "1", "3")

    assert precedents == [{
        "sourceTokenInstanceIds": [source_token_id],
        "targetTokenInstanceIds": [target_token_id],
    }]


def test_alignment_precedents_for_range_skips_a_verse_still_pending(tmp_path: Path) -> None:
    runtime = _runtime_with_completed_alignment(tmp_path)
    # Undo the "completed" marker written by the fixture: pending alignment
    # data must not become location evidence.
    completed = runtime.project.tc_dir / "tools" / "wordAlignment" / "completed" / "1" / "3.json"
    completed.unlink()
    assert alignment_precedents_for_range(runtime, "1", "3") == []


def test_alignment_precedents_for_range_skips_a_verse_marked_invalid(tmp_path: Path) -> None:
    runtime = _runtime_with_completed_alignment(tmp_path)
    completed = runtime.project.tc_dir / "tools" / "wordAlignment" / "completed" / "1" / "3.json"
    completed.unlink()
    invalid_dir = runtime.project.tc_dir / "tools" / "wordAlignment" / "invalid" / "1"
    invalid_dir.mkdir(parents=True)
    (invalid_dir / "3.json").write_text(
        json.dumps({"timestamp": "2026-01-01T00:00:00.000Z"}), encoding="utf-8",
    )
    assert alignment_precedents_for_range(runtime, "1", "3") == []


def test_completed_alignment_reaches_located_and_stage7_runs_against_it(tmp_path: Path) -> None:
    """Definition-of-done smoke test: a completed same-verse alignment is
    enough on its own (0.65 HUMAN_PRECEDENT-weight evidence, no embedding
    provider configured) to cross `located_minimum`, and Stage 7 can run
    against the resulting LOCATED relationship without erroring."""
    from tc_ai_bridge.meaning_analysis import MeaningAnalysisEngine
    from tc_ai_bridge.semantic_location import SemanticLocationEngine

    runtime = _runtime_with_completed_alignment(tmp_path)
    location = SemanticLocationEngine(runtime).run_range("1", "3")
    source_units = {
        unit["id"]: unit for unit in runtime.source_semantic.build_range("1", "3")["units"]
    }
    relationship = next(
        item for item in location["relationships"]
        if source_units[item["sourceSemanticUnitIds"][0]].get("semanticFeatures", {}).get("lemma")
        == "θεός"
    )
    assert relationship["locationOutcome"] == "LOCATED"
    candidate = next(
        item for item in location["candidates"] if item["id"] == relationship["selectedCandidateId"]
    )
    assert any(
        component["kind"] == "WORD_ALIGNMENT" and component["rawScore"] > 0
        for component in candidate["evidenceComponents"]
    )

    meaning = MeaningAnalysisEngine(runtime).run_range("1", "3", location_run_id=location["id"])
    assert meaning["assessments"]


def test_alignment_precedents_for_range_drops_a_group_with_an_unresolvable_target_word(
    tmp_path: Path,
) -> None:
    runtime = _runtime_with_completed_alignment(tmp_path)
    # Edit the alignment file in place (bypassing the normal save path, the
    # same way a hand-edited legacy project could) so the bottomWord no
    # longer occurs in the current verse text -- ALIGN_TARGET_MISMATCH shape.
    chapter_path = runtime.project.alignment_dir / "1.json"
    payload = json.loads(chapter_path.read_text(encoding="utf-8"))
    payload["3"]["alignments"][0]["bottomWords"][0]["word"] = "nonexistent"
    chapter_path.write_text(json.dumps(payload), encoding="utf-8")
    assert alignment_precedents_for_range(runtime, "1", "3") == []
