import json
import os
import threading
import time
import unicodedata
from types import SimpleNamespace

import pytest

from tc_ai_bridge.language_qa import (
    WORDLIST_COMMON_MIN, WORDLIST_MIN_LENGTH, WORDLIST_RARE_MAX, WORDLIST_RATIO_MIN,
    detect_language, scan_text, text_hash, wordlist_findings,
)
from tc_ai_bridge.language_qa_jobs import LanguageQaManager, MAX_CHAPTER_BYTES, MAX_BOOK_FINDINGS
from tests.service.test_bridge_service import fixture_project, call
from bridge_service import BridgeEngine


def scan(text, tamil=True):
    return scan_text(text, book="php", chapter="2", verse="3-4", tamil=tamil)


@pytest.mark.parametrize("text", [
    "தமிழ் மொழி", "கொ கோ கௌ ஔ", "க்ஷேத்திரம் ஸ்ரீ ஜீவன் ஹோசன்னா ஷ ஶ்ரீ",
    "அவர் இல்லை.", "ர ற ல ள ழ ந ன ண", "௧௨௩ ௐ ஃ",
    "க\u0bc6\u0bbe க\u0bc7\u0bbe க\u0bc6\u0bd7 ஒ\u0bd7",
])
def test_legal_tamil_signs_and_conjuncts(text):
    assert not [f for f in scan(text)["findings"] if f["rule"] == "tamil.dependent-sign"]


@pytest.mark.parametrize("text", ["ாக", "க்்", "குீ", "அா", " ் ", "கைா"])
def test_broken_dependent_signs_have_exact_raw_spans(text):
    findings = scan(text)["findings"]
    assert any(f["rule"] == "tamil.dependent-sign" for f in findings)
    for finding in findings:
        assert text[finding["start"]:finding["end"]] == finding["originalText"]
        assert finding["verse"] == "3-4"
        assert finding["textHash"] == text_hash(text)


def test_normalization_is_advisory_and_input_is_preserved():
    raw = unicodedata.normalize("NFD", "கொடுத்தார்.")
    assert scan(raw)["findings"][0]["rule"] == "unicode.nfc"
    assert all(f["severity"] == "low" for f in scan(raw)["findings"])
    assert raw != unicodedata.normalize("NFC", raw)


def test_identity_survives_unrelated_text_shift_but_hash_changes():
    one = next(f for f in scan("அவர் �")["findings"] if f["rule"] == "unicode.corruption")
    two = next(f for f in scan("😀 அவர் �")["findings"] if f["rule"] == "unicode.corruption")
    assert one["id"] == two["id"]
    assert one["textHash"] != two["textHash"]
    assert two["start"] == 7  # Python code points, not UTF-16 units.


def test_review_candidates_and_explicit_omissions():
    result = scan("மெல்ல மெல்ல தமிழ்a  ,,,\u200d\ue001")
    rules = {f["rule"] for f in result["findings"]}
    assert {"tamil.repeated-word", "tamil.mixed-word", "punctuation.repeated",
            "spacing.extra", "unicode.invisible", "unicode.private-use"} <= rules
    assert all(f["status"] == "review-needed" for f in result["findings"])
    assert scan("\\wj அவர்\\wj*")["limitations"]
    assert scan("அ" * 20_001)["limitations"]
    assert len(scan("�" * 200)["findings"]) == 100
    assert scan("�" * 200)["limitations"]
    assert not scan("என்ன?! ... …", tamil=False)["findings"]


@pytest.mark.parametrize("text,flagged,initial", [
    ("அந்த காகம்", "அந்த", "க"), ("அந்த பெண்", "அந்த", "ப"),
    ("இந்த செய்தி", "இந்த", "ச"), ("இந்த தலைமுறை", "இந்த", "த"),
    ("எந்த பக்கம்", "எந்த", "ப"), ("எந்த காரணம்", "எந்த", "க"),
])
def test_vallinam_missing_link_is_flagged(text, flagged, initial):
    findings = [f for f in scan(text)["findings"] if f["rule"] == "tamil.vallinam-missing"]
    assert len(findings) == 1
    finding = findings[0]
    assert finding["severity"] == "medium" and finding["status"] == "review-needed"
    assert finding["originalText"] == text
    assert flagged in finding["message"] and f"{flagged}{initial}்" in finding["message"]


@pytest.mark.parametrize("text", [
    "அந்தக் காகம்", "அந்தப் பெண்", "இந்தச் செய்தி",
    "இந்தத் தலைமுறை", "எந்தப் பக்கம்", "எந்தக் காரணம்",
])
def test_vallinam_correct_forms_are_not_flagged(text):
    assert not [f for f in scan(text)["findings"] if f["rule"] == "tamil.vallinam-missing"]


@pytest.mark.parametrize("text", ["அந்த வீடு", "இந்த மனிதன்", "எந்த ஊர்"])
def test_vallinam_ignores_non_trigger_initials(text):
    assert not [f for f in scan(text)["findings"] if f["rule"] == "tamil.vallinam-missing"]


@pytest.mark.parametrize("text", ["அந்த, காகம்", "அந்த. காகம்", "அந்த; காகம்"])
def test_vallinam_ignores_a_punctuation_boundary(text):
    assert not [f for f in scan(text)["findings"] if f["rule"] == "tamil.vallinam-missing"]


@pytest.mark.parametrize("text", ["சிந்த காகம்", "அந்தநாள் காகம்"])
def test_vallinam_requires_an_exact_token_match(text):
    assert not [f for f in scan(text)["findings"] if f["rule"] == "tamil.vallinam-missing"]


@pytest.mark.parametrize("text", ["அது காகம்", "இது சோலை", "எது தண்ணீர்"])
def test_vallinam_does_not_generalize_to_adhu_idhu_edhu(text):
    assert not [f for f in scan(text)["findings"] if f["rule"] == "tamil.vallinam-missing"]


# Part B2: same rule, same mechanism, a second closed-class trigger set
# (அப்படி/இப்படி/எப்படி, manner-adverbs, rather than B1's demonstratives).
# See VALLINAM_TRIGGERS's own comment in language_qa.py for why one shared
# mechanism covers both without any new logic.


@pytest.mark.parametrize("text,flagged,initial", [
    ("அப்படி கூறினான்", "அப்படி", "க"), ("அப்படி செய்தான்", "அப்படி", "ச"),
    ("அப்படி திரும்பினான்", "அப்படி", "த"), ("அப்படி பேசினான்", "அப்படி", "ப"),
    ("இப்படி காட்டினான்", "இப்படி", "க"), ("இப்படி சொன்னான்", "இப்படி", "ச"),
    ("இப்படி தெரியும்", "இப்படி", "த"), ("இப்படி பார்த்தான்", "இப்படி", "ப"),
    ("எப்படி கண்டாய்", "எப்படி", "க"), ("எப்படி செய்வாய்", "எப்படி", "ச"),
    ("எப்படி தெரியும்", "எப்படி", "த"), ("எப்படி பேசுவாய்", "எப்படி", "ப"),
])
def test_vallinam_b2_missing_link_is_flagged(text, flagged, initial):
    findings = [f for f in scan(text)["findings"] if f["rule"] == "tamil.vallinam-missing"]
    assert len(findings) == 1
    finding = findings[0]
    assert finding["severity"] == "medium" and finding["status"] == "review-needed"
    assert finding["originalText"] == text
    assert flagged in finding["message"] and f"{flagged}{initial}்" in finding["message"]
    assert text[finding["start"]:finding["end"]] == finding["originalText"]


@pytest.mark.parametrize("text", [
    "அப்படிக் கூறினான்", "அப்படிச் செய்தான்", "அப்படித் திரும்பினான்", "அப்படிப் பேசினான்",
    "இப்படிக் காட்டினான்", "இப்படிச் சொன்னான்", "இப்படித் தெரியும்", "இப்படிப் பார்த்தான்",
    "எப்படிக் கண்டாய்", "எப்படிச் செய்வாய்", "எப்படித் தெரியும்", "எப்படிப் பேசுவாய்",
])
def test_vallinam_b2_correct_forms_are_not_flagged(text):
    assert not [f for f in scan(text)["findings"] if f["rule"] == "tamil.vallinam-missing"]


@pytest.mark.parametrize("text", ["அப்படி நடந்தது", "இப்படி வந்தான்", "எப்படி முடியும்", "அப்படி எழுதினான்"])
def test_vallinam_b2_ignores_non_trigger_initials(text):
    assert not [f for f in scan(text)["findings"] if f["rule"] == "tamil.vallinam-missing"]


@pytest.mark.parametrize("text", ["அப்படி, கூறினான்", "இப்படி; சொன்னான்", "எப்படி? தெரியும்"])
def test_vallinam_b2_ignores_a_punctuation_boundary(text):
    assert not [f for f in scan(text)["findings"] if f["rule"] == "tamil.vallinam-missing"]


@pytest.mark.parametrize("text", [
    "அப்படித்தான் கூறினான்", "இப்படியும் சொன்னான்", "எப்படியோ தெரியும்",
    "அப்படியான செயல்", "இப்படிப்பட்ட மனிதன்",
])
def test_vallinam_b2_does_not_generalize_to_lookalike_suffixed_forms(text):
    # அப்படித்தான்/இப்படியும்/எப்படியோ/அப்படியான/இப்படிப்பட்ட tokenize as one
    # word each (letters+marks with no whitespace inside), so none of them
    # equal a bare trigger -- the same exact-match mechanism that keeps this
    # rule from generalizing for B1's அது/இது/எது, with no separate
    # exclusion list needed.
    assert not [f for f in scan(text)["findings"] if f["rule"] == "tamil.vallinam-missing"]


@pytest.mark.parametrize("text", ["அப்படி", "இப்படி.", "எப்படி?"])
def test_vallinam_b2_trigger_at_end_of_verse_does_not_crash_or_flag(text):
    assert not [f for f in scan(text)["findings"] if f["rule"] == "tamil.vallinam-missing"]


def test_vallinam_b2_ignores_inline_usfm():
    # scan_text() abstains on the whole verse when raw USFM markers are
    # present -- a genuine cross-verse boundary can never occur inside one
    # scan_text() call, since it always receives exactly one verse's text.
    assert scan("\\wj அப்படி கூறினான்\\wj*")["limitations"]


def test_vallinam_b2_matches_nfd_decomposed_trigger_text():
    nfd_text = unicodedata.normalize("NFD", "அப்படி கூறினான்")
    findings = [f for f in scan(nfd_text)["findings"] if f["rule"] == "tamil.vallinam-missing"]
    assert len(findings) == 1
    assert findings[0]["originalText"] == nfd_text  # raw span, never rewritten to NFC


def test_vallinam_b2_finding_identity_is_stable_across_repeated_scans():
    first = next(f for f in scan("அப்படி கூறினான்")["findings"] if f["rule"] == "tamil.vallinam-missing")
    second = next(f for f in scan("அப்படி கூறினான்")["findings"] if f["rule"] == "tamil.vallinam-missing")
    assert first["id"] == second["id"]


def test_vallinam_b2_never_mutates_the_input_text():
    text = "அப்படி கூறினான்"
    scan(text)
    assert text == "அப்படி கூறினான்"


def test_vallinam_b2_coexists_with_b1_triggers_in_the_same_verse():
    result = scan("அந்த காகம் அப்படி கூறினான்.")
    findings = [f for f in result["findings"] if f["rule"] == "tamil.vallinam-missing"]
    assert {f["originalText"] for f in findings} == {"அந்த காகம்", "அப்படி கூறினான்"}


def test_vallinam_b1_regression_is_unaffected_by_b2():
    # B1's own tests above are untouched; this is a direct check that adding
    # the B2 trigger words did not change B1's existing behavior.
    findings = [f for f in scan("அந்த காகம்")["findings"] if f["rule"] == "tamil.vallinam-missing"]
    assert len(findings) == 1 and findings[0]["originalText"] == "அந்த காகம்"


def test_detection_metadata_conflicts_shared_scripts_and_mixed_input():
    tamil = "தமிழ் மொழியில் எழுதப்பட்ட உரை. " * 10
    assert detect_language(tamil)["pack"] == "tamil"
    assert detect_language(tamil, "ta-IN")["language"] == "tam"
    assert detect_language(tamil, "hin")["basis"] == "metadata-conflict"
    assert detect_language(tamil, "hin")["pack"] == "common"
    assert detect_language("देवनागरी " * 20)["language"] == "und"
    assert detect_language("देवनागरी " * 20, "mar")["language"] == "mar"
    assert detect_language("hello world " * 20, "ta-Latn")["pack"] == "common"
    assert detect_language("தமிழ் abcde " * 20)["basis"] == "mixed-script"
    assert detect_language("123")["language"] == "und"


def test_wordlist_findings_flags_a_rare_pulli_variant_of_a_common_word():
    common, rare = "தமிழ்", "தமிழ"  # differ by exactly one pulli
    assert len(common) >= WORDLIST_MIN_LENGTH and len(rare) >= WORDLIST_MIN_LENGTH
    counts = {common: WORDLIST_COMMON_MIN, rare: 1}
    first_seen = {
        common: ("1", "1", 0, len(common), common, "hash-common"),
        rare: ("1", "2", 3, 3 + len(rare), rare, "hash-rare"),
    }
    findings = wordlist_findings("php", counts, first_seen)
    assert len(findings) == 1
    finding = findings[0]
    assert finding["rule"] == "tamil.wordlist-variant"
    assert finding["severity"] == "low" and finding["status"] == "review-needed"
    assert finding["chapter"] == "1" and finding["verse"] == "2"
    assert finding["start"] == 3 and finding["end"] == 3 + len(rare)
    assert finding["originalText"] == rare  # the raw span, not the NFC counting key
    assert finding["textHash"] == "hash-rare"
    assert common in finding["message"] and str(WORDLIST_COMMON_MIN) in finding["message"]


def test_wordlist_findings_never_flags_rarity_alone():
    rare = "தமிழக"  # length >= WORDLIST_MIN_LENGTH, no similar word present at all
    counts = {rare: 1}
    first_seen = {rare: ("1", "1", 0, len(rare), rare, "hash")}
    assert wordlist_findings("php", counts, first_seen) == []


def test_wordlist_findings_never_flags_similarity_alone():
    a, b = "தமிழ்", "தமிழ"
    counts = {a: WORDLIST_COMMON_MIN, b: WORDLIST_COMMON_MIN}  # both common, neither rare
    first_seen = {
        a: ("1", "1", 0, len(a), a, "hash-a"),
        b: ("1", "2", 0, len(b), b, "hash-b"),
    }
    assert wordlist_findings("php", counts, first_seen) == []


def test_wordlist_findings_ignores_words_shorter_than_the_minimum():
    common, rare = "தமி", "தம"
    assert len(common) < WORDLIST_MIN_LENGTH and len(rare) < WORDLIST_MIN_LENGTH
    counts = {common: WORDLIST_COMMON_MIN, rare: 1}
    first_seen = {
        common: ("1", "1", 0, len(common), common, "hash-common"),
        rare: ("1", "2", 0, len(rare), rare, "hash-rare"),
    }
    assert wordlist_findings("php", counts, first_seen) == []


def test_wordlist_findings_tie_break_is_deterministic():
    rare = "தமிழ"
    higher_count, lower_count = "தமிழ்", "தமிள"  # insertion vs. substitution, both edit-distance-1
    counts = {rare: 1, higher_count: WORDLIST_COMMON_MIN + 6, lower_count: WORDLIST_COMMON_MIN + 2}
    first_seen = {
        rare: ("1", "1", 0, len(rare), rare, "hash-rare"),
        higher_count: ("1", "2", 0, len(higher_count), higher_count, "hash-a"),
        lower_count: ("1", "3", 0, len(lower_count), lower_count, "hash-b"),
    }
    findings = wordlist_findings("php", counts, first_seen)
    assert len(findings) == 1
    assert higher_count in findings[0]["message"]  # higher count wins over lexical order
    # Equal counts: lexicographically smaller string wins instead.
    counts[higher_count] = counts[lower_count]
    findings = wordlist_findings("php", counts, first_seen)
    assert lower_count in findings[0]["message"]
    assert lower_count < higher_count


def project_at(root, text="தமிழ் தமிழ்  ", book="php", verses=None, terminology=None, decisions=None):
    folder = root / book
    folder.mkdir(parents=True)
    (folder / "1.json").write_text(json.dumps(verses or {"3a": text}, ensure_ascii=False), encoding="utf-8")
    namespace = SimpleNamespace(path=root, book_id=book, book_dir=folder,
                                manifest={"target_language": {"id": "tam"}})
    if terminology is not None:
        namespace.terminology_rules = terminology if callable(terminology) else (lambda: terminology)
    if decisions is not None:
        namespace.project_qa_decisions = decisions if callable(decisions) else (lambda: decisions)
    return namespace


def wait(manager, state="completed"):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        status = manager.status(limit=100)
        if status["state"] == state:
            return status
        assert status["state"] != "failed", status
        time.sleep(.005)
    pytest.fail(f"Language QA did not reach {state}: {manager.status()}")


def test_wordlist_audit_end_to_end_via_manager(tmp_path):
    project = project_at(tmp_path, verses={"1": "தமிழ்", "2": "தமிழ்", "3": "தமிழ்"})
    (project.book_dir / "2.json").write_text(json.dumps(
        {"1": "தமிழ்", "2": "தமிழ்", "3": "தமிழ்", "4": "தமிழ"}, ensure_ascii=False), encoding="utf-8")
    manager = LanguageQaManager(debounce=0, yield_seconds=0)
    manager.bind(project)
    result = wait(manager)
    variants = [f for f in result["findings"] if f["rule"] == "tamil.wordlist-variant"]
    assert len(variants) == 1
    assert variants[0]["chapter"] == "2" and variants[0]["verse"] == "4"
    assert variants[0]["originalText"] == "தமிழ"


def test_wordlist_audit_excludes_words_from_verses_with_limitations(tmp_path):
    # An inline-USFM verse ("\\" present) produces a verse-level limitation and
    # must not contribute its words to the book-wide wordlist audit.
    verses = {str(n): "தமிழ்" for n in range(1, 7)}  # 6 occurrences: satisfies WORDLIST_COMMON_MIN
    verses["7"] = "\\wj தமிழ\\wj*"
    project = project_at(tmp_path, verses=verses)
    manager = LanguageQaManager(debounce=0, yield_seconds=0)
    manager.bind(project)
    result = wait(manager)
    assert not [f for f in result["findings"] if f["rule"] == "tamil.wordlist-variant"]


def test_wordlist_audit_skips_when_book_scan_is_truncated(tmp_path):
    project = project_at(tmp_path, verses={str(n): "�" * 100 for n in range(100)})
    manager = LanguageQaManager(debounce=0, yield_seconds=0)
    manager.bind(project)
    result = wait(manager)
    assert result["totalFindings"] == MAX_BOOK_FINDINGS
    assert any("Wordlist audit skipped: book scan was truncated." in m for m in result["limitations"])


def test_wordlist_finding_id_is_stable_when_its_anchor_occurrence_moves(tmp_path):
    project = project_at(tmp_path, verses={"1": "தமிழ"})
    (project.book_dir / "2.json").write_text(json.dumps(
        {"1": "தமிழ்", "2": "தமிழ்", "3": "தமிழ்", "4": "தமிழ்", "5": "தமிழ்", "6": "தமிழ்"},
        ensure_ascii=False), encoding="utf-8")
    manager = LanguageQaManager(debounce=0, yield_seconds=0)
    manager.bind(project)
    first = wait(manager)
    before = next(f for f in first["findings"] if f["rule"] == "tamil.wordlist-variant")
    assert before["chapter"] == "1" and before["verse"] == "1"
    # Move the rare word's only occurrence to a different verse in the same chapter.
    (project.book_dir / "1.json").write_text(
        json.dumps({"1": "புதிய வரி", "2": "தமிழ"}, ensure_ascii=False), encoding="utf-8")
    manager.invalidate("1")
    after = wait(manager)
    after_finding = next(f for f in after["findings"] if f["rule"] == "tamil.wordlist-variant")
    assert after_finding["verse"] == "2"
    assert after_finding["id"] == before["id"]


def test_background_external_edits_and_no_writes(tmp_path):
    project = project_at(tmp_path)
    manager = LanguageQaManager(debounce=0, yield_seconds=0)
    source = project.book_dir / "1.json"
    before = source.read_bytes()
    manager.bind(project)
    first = wait(manager)
    assert first["totalFindings"] == 2
    assert first["findings"][0]["verse"] == "3a"
    assert source.read_bytes() == before
    assert list(tmp_path.rglob("*")) == [project.book_dir, source]
    source.write_text('{"3a":"clean"}', encoding="utf-8")
    manager._last_scan = 0
    assert manager.status()["state"] == "queued"
    assert wait(manager)["totalFindings"] == 0


def test_completed_scan_stays_completed_when_idle_refresh_finds_no_change(tmp_path):
    project = project_at(tmp_path)
    manager = LanguageQaManager(debounce=0, yield_seconds=0)
    manager.bind(project)
    completed = wait(manager)
    generation = completed["generation"]
    manager._last_scan = 0
    refreshed = manager.status(limit=100)
    assert refreshed["state"] == "completed"
    assert refreshed["generation"] == generation
    assert manager._thread is None


def test_idle_refresh_rechecks_an_ordinary_external_edit(tmp_path):
    project = project_at(tmp_path, text="a  b")
    manager = LanguageQaManager(debounce=0, yield_seconds=0)
    manager.bind(project)
    assert wait(manager)["totalFindings"] == 1
    path = project.book_dir / "1.json"
    path.write_text('{"3a":"clean"}', encoding="utf-8")
    manager._last_scan = 0
    assert manager.status()["state"] == "queued"
    assert wait(manager)["totalFindings"] == 0


def test_pause_keeps_results_visible_and_resume_with_no_changes_skips_rescan(tmp_path):
    project = project_at(tmp_path)
    manager = LanguageQaManager(debounce=0, yield_seconds=0)
    manager.bind(project)
    completed = wait(manager)
    manager.pause(True)
    paused = manager.status(limit=100)
    assert paused["state"] == "paused"
    assert paused["findings"] == completed["findings"]
    # A book where every chapter carries a per-verse limitation (e.g. inline
    # USFM) never populates _scan's chapter cache, so an unconditional
    # reschedule on resume would redo that same, unchanged pass and look
    # like the whole book restarting from zero.
    resumed = manager.pause(False)
    assert resumed["state"] == "completed"  # returned synchronously: no rescan thread ran
    assert manager.status(limit=100)["findings"] == completed["findings"]
    assert manager._thread is None


def test_resume_after_an_external_edit_made_while_paused_rescans(tmp_path):
    project = project_at(tmp_path)
    manager = LanguageQaManager(debounce=0, yield_seconds=0)
    manager.bind(project)
    wait(manager)
    manager.pause(True)
    (project.book_dir / "1.json").write_text('{"3a":"clean"}', encoding="utf-8")
    resumed = manager.pause(False)
    assert resumed["state"] == "queued"
    assert wait(manager)["totalFindings"] == 0


def test_edit_switch_and_pause_discard_inflight_results(tmp_path, monkeypatch):
    from tc_ai_bridge import language_qa_jobs as jobs
    original = jobs.scan_text
    entered, release = threading.Event(), threading.Event()
    def blocked(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)
    monkeypatch.setattr(jobs, "scan_text", blocked)
    first = project_at(tmp_path / "first")
    second = project_at(tmp_path / "second", text="சரியான உரை")
    manager = LanguageQaManager(debounce=0, yield_seconds=0)
    manager.bind(first)
    assert entered.wait(5)
    worker = manager._thread
    start = time.perf_counter()
    manager.pause(True)
    assert manager.status()["state"] == "paused"
    manager.bind(second)
    assert manager._thread is worker  # Never spawn a second worker.
    manager.invalidate("1")
    assert manager.status()["findings"] == []
    assert time.perf_counter() - start < .25
    release.set()
    final = wait(manager)
    assert final["projectPath"] == str(second.path)
    assert final["totalFindings"] == 0


def test_paused_edits_remain_pending_until_resume(tmp_path):
    manager = LanguageQaManager(debounce=.05, yield_seconds=0)
    project = project_at(tmp_path)
    manager.bind(project)
    manager.pause(True)
    manager.invalidate("1")
    time.sleep(.06)
    assert manager.status()["state"] == "paused"
    manager.pause(False)
    assert wait(manager)["totalFindings"] == 2


@pytest.mark.parametrize("payload", [b"{bad json", b"\xff", b"[]", b" " * (MAX_CHAPTER_BYTES + 1),
                                    b'{"1":"first", "1":"duplicate"}'],
                         ids=["bad-json", "bad-utf8", "wrong-shape", "oversize", "duplicate-verse"])
def test_unreadable_chapter_is_incomplete_not_clean(tmp_path, payload):
    project = project_at(tmp_path)
    (project.book_dir / "1.json").write_bytes(payload)
    manager = LanguageQaManager(debounce=0, yield_seconds=0)
    manager.bind(project)
    result = wait(manager)
    assert result["incomplete"] and result["limitations"]
    assert result["checkedVerses"] == 0


def test_book_limits_and_status_page_are_bounded(tmp_path):
    project = project_at(tmp_path, verses={str(n): "�" * 100 for n in range(100)})
    manager = LanguageQaManager(debounce=0, yield_seconds=0)
    manager.bind(project)
    result = wait(manager)
    assert result["totalFindings"] == 3000
    assert result["incomplete"]
    assert len(manager.status(limit=10000)["findings"]) == 100
    assert manager.status()["findings"] == []
    assert manager.status(offset=5000, limit=100)["findings"] == []


def test_real_dispatcher_auto_open_edit_and_project_guard(fixture_project):
    engine = BridgeEngine()
    engine._language_qa = LanguageQaManager(debounce=0, yield_seconds=0)
    try:
        assert call(engine, "project.open", {"path": str(fixture_project)})["success"]
        assert wait(engine._language_qa)["language"]["pack"] == "tamil"
        wrong = call(engine, "languageQa.pause", {"projectPath": "other", "paused": True})
        assert not wrong["success"]
        assert call(engine, "verse.edit", {"chapter": "1", "verse": "1", "newText": "தமிழ் �"})["success"]
        assert wait(engine._language_qa)["totalFindings"] == 1
        response = call(engine, "languageQa.status", {"projectPath": str(fixture_project), "limit": 10})
        assert response["result"]["findings"][0]["rule"] == "unicode.corruption"
        assert call(engine, "ping")["success"]
    finally:
        engine._language_qa.unbind()


def test_recovery_block_cannot_be_resumed(tmp_path):
    manager = LanguageQaManager(debounce=0, yield_seconds=0)
    project = project_at(tmp_path)
    manager.bind(project, blocked_reason="Recovery required")
    assert manager.pause(False)["state"] == "failed"
    assert manager.status()["projectPath"] == str(project.path)
    assert manager._thread is None


def test_continuous_foreground_polling_does_not_starve_worker(tmp_path):
    project = project_at(tmp_path, verses={str(n): "சரியான உரை" for n in range(50)})
    manager = LanguageQaManager(debounce=0, yield_seconds=.001)
    manager.bind(project)
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        manager.touch()
        result = manager.status()
        if result["state"] == "completed":
            assert result["checkedVerses"] == 50
            break
        time.sleep(.005)
    else:
        pytest.fail("Frequent foreground requests starved Language QA")


def test_invalidated_edit_with_preserved_timestamp_and_size_is_not_cached(tmp_path):
    project = project_at(tmp_path, text="a  b")
    manager = LanguageQaManager(debounce=0, yield_seconds=0)
    manager.bind(project)
    assert wait(manager)["totalFindings"] == 1
    path = project.book_dir / "1.json"
    previous = path.stat()
    path.write_text(path.read_text(encoding="utf-8").replace("a  b", "a. b"), encoding="utf-8")
    os.utime(path, ns=(previous.st_atime_ns, previous.st_mtime_ns))
    assert path.stat().st_size == previous.st_size
    manager.invalidate("1")
    assert wait(manager)["totalFindings"] == 0


def test_escaped_json_surrogate_is_reported_without_breaking_utf8_protocol(tmp_path):
    project = project_at(tmp_path)
    (project.book_dir / "1.json").write_text('{"1":"\\ud800"}', encoding="utf-8")
    manager = LanguageQaManager(debounce=0, yield_seconds=0)
    manager.bind(project)
    status = wait(manager)
    assert status["incomplete"]
    assert "U+D800" in status["limitations"][0]
    assert json.dumps(status, ensure_ascii=False).encode("utf-8")
