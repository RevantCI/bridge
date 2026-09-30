"""The corpus lexicon, the Tamil confusion-set distance, and the lexicon rules
(layered-rules Phase 5), on the real bundled lexicon."""
import json
import time

import pytest

from tc_ai_bridge.language_packs import lexicon as lexicon_module
from tc_ai_bridge.language_packs.lexicon import (
    COMMON_MIN, MAX_SUGGESTIONS, RATIO_MIN, default_lexicon, deletion_keys, lexicon_findings,
)
from tc_ai_bridge.language_packs.tamil_distance import clusters, substitution_cost, tamil_distance
from tc_ai_bridge.language_qa import RULE_VERSION, rule_fields, suggestion, word_occurrences
from tc_ai_bridge.language_qa_jobs import LanguageQaManager
from tests.service.test_language_qa import project_at, wait
from tests.support.projects import fixture_project  # noqa: F401


# ---- 5.2 confusion-set distance -------------------------------------------------

@pytest.mark.parametrize("a,b", [
    ("கரம்", "கறம்"),                     # ர/ற
    ("கலம்", "களம்"), ("களம்", "கழம்"), ("கலம்", "கழம்"),   # ல/ள/ழ
    ("மணம்", "மனம்"), ("மனம்", "மநம்"),   # ண/ன/ந
    ("எழு", "ஏழு"), ("ஒடு", "ஓடு"), ("இரு", "ஈரு"), ("உண்", "ஊண்"),  # independent vowels
    ("பெண்", "பேண்"), ("கொடு", "கோடு"), ("கிளி", "கீளி"), ("குடி", "கூடி"),  # the signs
    ("ஐயா", "அய்யா"), ("ஔவை", "அவ்வை"),  # one cluster against two
    ("படம்", "படம"),                      # pulli
    ("கட", "காட"),                        # ா
])
def test_each_confusion_costs_half(a, b):
    assert tamil_distance(a, b) == 0.5 == tamil_distance(b, a)


def test_other_edits_cost_one_and_identical_words_nothing():
    assert tamil_distance("அவன்", "அவள்") == 1.0   # ன/ள are not a confusion pair
    assert tamil_distance("கடல்", "கல்") == 1.0     # a cluster deleted
    assert tamil_distance("வீடு", "வீடு") == 0.0
    assert substitution_cost("கா", "கி") == 1.0     # different vowel signs


def test_real_round_2_typos_are_within_reach():
    assert tamil_distance("உடன்பட்டிக்கையை", "உடன்படிக்கையை") == 1.0
    assert tamil_distance("ராஜ்யாபாரமும்", "ராஜ்யபாரமும்") == 0.5


def test_distance_is_over_grapheme_clusters_not_code_points():
    assert clusters("க்ஷேத்திரம்") == ["க்", "ஷே", "த்", "தி", "ர", "ம்"]
    assert deletion_keys("கடல்") == {"டல்", "கல்", "கட"}


# ---- 5.1 the lexicon ------------------------------------------------------------

def test_the_bundled_lexicon_is_bounded_and_precomputed():
    lexicon = default_lexicon()
    assert lexicon is not None and lexicon.corpus["books"] == 66
    assert lexicon.corpus["listedForms"] == len(lexicon.forms) < lexicon.corpus["distinctForms"]
    assert min(entry[0] for entry in lexicon.forms.values()) >= lexicon.corpus["minListedCount"]
    assert all(lexicon.count(w) >= COMMON_MIN for w in lexicon.common)
    # Deletion buckets are shipped, not rebuilt: a lookup is a dict read.
    assert "உடன்படிக்கையை" in lexicon.candidates("உடன்பட்டிக்கையை")


def test_the_curated_map_only_keeps_safe_pairs():
    lexicon = default_lexicon()
    assert lexicon.deprecated
    data = json.loads(lexicon_module.LEXICON_PATH.read_text(encoding="utf-8"))
    confirmed = set(data["humanConfirmed"])
    # The reviewer confirmed 43 pairs on 2026-09-28 and 4 more on 2026-09-29; all are in the map.
    assert len(confirmed) == 47 and confirmed <= set(lexicon.deprecated)
    # Every pair has a provenance, and the human ones are exactly the confirmed ones.
    assert set(lexicon.provenance) == set(lexicon.deprecated)
    assert {w for w, p in lexicon.provenance.items() if p == "human"} == confirmed
    for wrong, right in lexicon.deprecated.items():
        # A common word is never marked wrong from an AI review row; a person's
        # confirmation is the one exception (IRV repeats some misspellings).
        assert lexicon.count(wrong) <= 2 or wrong in confirmed, wrong
        assert wrong != right
    # The reviewer's false alarms are protected words: 21 rare-near-common (round 1),
    # 4 known-misspelling pairs that were meaning or style changes, and the 4
    # one-grapheme tokens judged a word, name or interjection (சீ, சோ, நோ, பை; round 2).
    assert len(lexicon.protected) == 29 and not (lexicon.protected & set(lexicon.deprecated))
    assert {"சீ", "சோ", "நோ", "பை"} <= lexicon.protected
    assert {"திடமனதாயிரு", "கவனிக்காதே", "பூட்டுக்களையும்", "பெருந்தொனியாய்"} <= lexicon.protected
    # Fragments are not words; real monosyllables are.
    assert lexicon.count("சு") == 0 and lexicon.count("நே") == 0 and lexicon.count("கை") > 0


def test_lexicon_loads_within_the_startup_budget():
    lexicon_module._LOADED.pop("ta-irv", None)
    started = time.perf_counter()
    assert default_lexicon() is not None
    assert time.perf_counter() - started < 0.5  # parse only; loaded lazily, off the dispatcher


# ---- 5.3 the rules ----------------------------------------------------------------

def book_counts(verses):
    counts, first_seen = {}, {}
    for verse, text in verses.items():
        for word, start, end in word_occurrences(text):
            counts[word] = counts.get(word, 0) + 1
            first_seen.setdefault(word, ("1", verse, start, end, text[start:end], "h"))
    return counts, first_seen


def findings_for(verses):
    counts, first_seen = book_counts(verses)
    return lexicon_findings("gen", counts, first_seen, default_lexicon(), rule_fields=rule_fields,
                            suggestion=suggestion, rule_version=RULE_VERSION)


def test_a_rare_word_near_a_common_one_gets_ranked_suggestions_with_evidence():
    # ர for ற in a word the corpus has 1,007 times: a typist confusion (0.5).
    [finding] = [f for f in findings_for({"1": "அவன் இஸ்றவேல் வந்தான்."})
                 if f["rule"] == "lexicon.rare-near-common"]
    assert finding["originalText"] == "இஸ்றவேல்" and finding["category"] == "typo"
    assert finding["confidence"] == "medium" and finding["inline"] is False
    top = finding["suggestions"][0]
    assert top["text"] == "இஸ்ரவேல்" and top["source"] == "lexicon"
    assert "in the corpus" in top["rationale"] and len(finding["suggestions"]) <= MAX_SUGGESTIONS
    ranks = [s["rank"] for s in finding["suggestions"]]
    assert ranks == sorted(ranks)


def test_a_word_common_in_the_corpus_is_never_flagged():
    assert not findings_for({"1": "யெகோவா இஸ்ரவேல் தேவன்."})


def test_a_misspelling_is_high_confidence_and_inline_only_when_a_human_confirmed_it():
    lexicon = default_lexicon()
    human = next(w for w, p in lexicon.provenance.items() if p == "human")
    ai = next(w for w, p in lexicon.provenance.items() if p == "ai-review")
    for wrong, confidence, inline, provenance in ((human, "high", True, "human"), (ai, "medium", False, "ai-review")):
        [finding] = [f for f in findings_for({"1": f"அவன் {wrong} வந்தான்."})
                     if f["rule"] == "lexicon.known-misspelling"]
        assert (finding["confidence"], finding["inline"], finding["provenance"]) == (confidence, inline, provenance)
        assert finding["severity"] == "medium" and finding["suggestions"][0]["text"] == lexicon.deprecated[wrong]
    assert "awaits human confirmation" in [f for f in findings_for({"1": f"அவன் {ai} வந்தான்."})
                                           if f["rule"] == "lexicon.known-misspelling"][0]["message"]


def test_known_splits_are_curated_pairs_found_in_the_verse():
    """lexicon.known-split (2026-09-29): only the pairs a reviewer judged SPLIT,
    joined as the reviewer wrote them; names and interjections are left alone."""
    from tc_ai_bridge.language_qa import scan_text
    assert default_lexicon().splits == {"சு வரை": "சுவரை", "நே போ": "நேபோ"}

    def splits(text):
        return [(f["originalText"], f["suggestedReplacement"], f["inline"], f["category"])
                for f in scan_text(text, book="x", chapter="1", verse="1", tamil=True)["findings"]
                if f["ruleId"] == "ta-irv/lexicon.known-split"]
    assert splits("அதின் சு வரை கவனித்து") == [("சு வரை", "சுவரை", True, "word-joining")]
    assert splits("நே போ மலையின்மேல்") == [("நே போ", "நேபோ", True, "word-joining")]
    for text in ("சீ என்று சொல்", "நோ பட்டணம்", "சோ என்பவனிடத்திற்கு", "பை இருக்கும்"):
        assert splits(text) == [], text


def test_the_ratio_guard_holds():
    lexicon = default_lexicon()
    for f in findings_for({"1": "அவன் இஸ்றவேல் வந்தான்."}):
        for s in f["suggestions"]:
            assert lexicon.count(s["text"]) >= COMMON_MIN * 1 and lexicon.count(s["text"]) >= RATIO_MIN


@pytest.mark.subprocess
def test_the_feedback_report_lists_lexicon_decisions_and_changes_nothing(fixture_project, tmp_path):
    import csv
    import subprocess
    import sys
    from tests.support.paths import REPO_ROOT
    from tc_ai_bridge.tc_project import TranslationCoreProject
    project = TranslationCoreProject(fixture_project)
    project.record_qa_decision("1", "1", issue_key="lex-1", decision="accepted", issue={
        "source": "languageQa", "rule": "lexicon.rare-near-common", "originalText": "உடன்பட்டிக்கையை",
        "chosenSuggestion": "உடன்படிக்கையை", "suggestedReplacement": "உடன்படிக்கையை"})
    project.record_qa_decision("1", "1", issue_key="gr-1", decision="ignored", issue={"source": "greekRoom"})
    before = lexicon_module.LEXICON_PATH.read_bytes()
    out = tmp_path / "feedback.csv"
    done = subprocess.run([sys.executable, str(REPO_ROOT / "scripts" / "lexicon_feedback_report.py"),
                           str(fixture_project), "--out", str(out)], capture_output=True, text=True, encoding="utf-8")
    assert done.returncode == 0, done.stderr
    [row] = list(csv.DictReader(out.open(encoding="utf-8-sig")))
    assert (row["rule"], row["decision"], row["chosen"]) == ("lexicon.rare-near-common", "accepted", "உடன்படிக்கையை")
    assert lexicon_module.LEXICON_PATH.read_bytes() == before


def test_the_manager_uses_the_lexicon_for_a_tamil_book(tmp_path, monkeypatch):
    verses = {"1": "அவன் இஸ்றவேல் வந்தான்.", "2": "தேவன் பேசினார்."}

    def rules_found(root):
        manager = LanguageQaManager(debounce=0, yield_seconds=0)
        manager.bind(project_at(root, verses=verses))
        findings = wait(manager)["findings"]
        manager.unbind()
        return {f["rule"] for f in findings}
    # Disabled by default (2026-09-28 review, 0 of 21), and never the wordlist fallback.
    rules = rules_found(tmp_path / "default")
    assert "lexicon.rare-near-common" not in rules and "tamil.wordlist-variant" not in rules
    # Enabled in code, the manager still uses the corpus lexicon for it.
    from dataclasses import replace
    from tc_ai_bridge import language_qa
    monkeypatch.setitem(language_qa.RULES, "lexicon.rare-near-common",
                        replace(language_qa.RULES["lexicon.rare-near-common"], enabled=True))
    assert "lexicon.rare-near-common" in rules_found(tmp_path / "enabled")
