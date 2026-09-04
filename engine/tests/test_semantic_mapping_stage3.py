from __future__ import annotations
import json, sqlite3
from pathlib import Path

from tc_ai_bridge.semantic_mapping import (
    PassageSearchBudget, SemanticMappingEngine,
    SemanticSourceRepository, SemanticMappingStore, mapping_state_for_review,
)
from tc_ai_bridge.usfm_passages import UsfmPassageIndex

class FakeClient:
    model="gpt-5.6-test"
    def __init__(self, outputs): self.outputs=list(outputs); self.calls=[]
    def _post_structured(self, instructions,input_text,schema_name,schema):
        self.calls.append(json.loads(input_text)); return self.outputs.pop(0)

def fixture_response(unit_id, token_ids, source_ref, target_ref, quote, rel="CROSS_VERSE_REORDERED"):
    return {"mappings":[{"source_unit_id":unit_id,"source_token_ids":token_ids,"source_reference":source_ref,
      "target_spans":[{"reference":target_ref,"quote":quote,"start":None,"end":None}],"relationships":[rel],
      "meaning_status":"PRESERVED","confidence":.98,"evidence":{"source":"source","target":quote,"explanation":"grounded"}}],
      "unresolved_source_units":[],"passage_assessment":"MAPPED"}

def test_php_cross_verse_mapping(stage3_db, tamil_php_usfm):
    repo=SemanticSourceRepository(stage3_db); unit=repo.unit_for_check(book="PHP",chapter=1,verse=3,tool="translationNotes",check_id="gjyv")
    idx=UsfmPassageIndex.from_path(tamil_php_usfm,book_hint="PHP")
    fake=FakeClient([fixture_response(unit.id,list(unit.source_token_ids),"PHP 1:3","PHP 1:6","என் தேவனை")])
    run=SemanticMappingEngine(repo,fake,max_neighbor_windows=1).map_units(target_index=idx,source_units=[unit])
    m=run.result["mappings"][0]
    assert m["target_spans"][0]["quote"] == "என் தேவனை"
    assert m["target_spans"][0]["reference"] == "PHP 1:6"
    assert mapping_state_for_review(m,"PHP 1:3")["state"] == "found_another_verse"


def test_cross_verse_sentence_reordering_is_classified_explicitly(stage3_db, tamil_php_usfm):
    repo=SemanticSourceRepository(stage3_db); unit=repo.unit_for_check(book="PHP",chapter=1,verse=3,tool="translationNotes",check_id="gjyv")
    idx=UsfmPassageIndex.from_path(tamil_php_usfm,book_hint="PHP")
    target=idx.segment_for_source_reference("1","6")
    assert target is not None
    response=fixture_response(
        unit.id,list(unit.source_token_ids),"PHP 1:3","PHP 1:6",
        target.text[34:43],rel="SENTENCE_REORDERED",
    )
    run=SemanticMappingEngine(repo,FakeClient([response]),max_neighbor_windows=1).map_units(
        target_index=idx,source_units=[unit],
    )
    relationships=run.result["mappings"][0]["relationships"]
    assert "CROSS_VERSE" in relationships
    assert "CROSS_VERSE_REORDERED" in relationships

def test_hallucinated_target_quote_is_rejected(stage3_db, tamil_php_usfm):
    repo=SemanticSourceRepository(stage3_db); unit=repo.unit_for_check(book="PHP",chapter=1,verse=3,tool="translationNotes",check_id="gjyv")
    idx=UsfmPassageIndex.from_path(tamil_php_usfm,book_hint="PHP")
    hallucinated=fixture_response(unit.id,list(unit.source_token_ids),"PHP 1:3","PHP 1:6","இந்த சொல் இல்லை")
    fake=FakeClient([hallucinated,hallucinated,hallucinated])
    run=SemanticMappingEngine(repo,fake,max_neighbor_windows=1).map_units(target_index=idx,source_units=[unit])
    # A quote that is not literally in the target segment never becomes a mapping;
    # the unit stays unresolved, which is review work, never an omission verdict.
    assert run.result["mappings"] == []
    assert run.result["unresolved_source_units"][0]["source_unit_id"] == unit.id
    assert run.result["passage_assessment"] == "NEEDS_REVIEW"


def test_one_rejected_row_does_not_discard_the_rest_of_the_batch(stage3_db, tamil_php_usfm):
    """A single bad row used to abort the whole verse's Stage 3 mapping.

    Every other check then reached the review policy as `mapping_error`, which
    clears its proposal -- so one hallucinated quote left an entire verse's tN/tW
    selections unapplied and showing "Pending".
    """
    repo=SemanticSourceRepository(stage3_db)
    good=repo.unit_for_check(book="PHP",chapter=1,verse=3,tool="translationNotes",check_id="gjyv")
    bad=repo.unit_for_check(book="PHP",chapter=1,verse=3,tool="translationWords",check_id="xpgk")
    assert good.id != bad.id
    idx=UsfmPassageIndex.from_path(tamil_php_usfm,book_hint="PHP")
    response={"mappings":[
        fixture_response(good.id,list(good.source_token_ids),"PHP 1:3","PHP 1:6","என் தேவனை")["mappings"][0],
        fixture_response(bad.id,list(bad.source_token_ids),"PHP 1:3","PHP 1:6","இந்த சொல் இல்லை")["mappings"][0],
      ],"unresolved_source_units":[],"passage_assessment":"MAPPED"}
    fake=FakeClient([response,response,response])
    run=SemanticMappingEngine(repo,fake,max_neighbor_windows=1).map_units(target_index=idx,source_units=[good,bad])
    mapped={m["source_unit_id"] for m in run.result["mappings"]}
    assert mapped == {good.id}
    unresolved={u["source_unit_id"] for u in run.result["unresolved_source_units"]}
    assert unresolved == {bad.id}

def test_unresolved_expands_and_never_becomes_omission(stage3_db, tamil_php_usfm):
    repo=SemanticSourceRepository(stage3_db); unit=repo.unit_for_check(book="PHP",chapter=1,verse=3,tool="translationNotes",check_id="gjyv")
    idx=UsfmPassageIndex.from_path(tamil_php_usfm,book_hint="PHP")
    unresolved={"mappings":[],"unresolved_source_units":[{"source_unit_id":unit.id,"reason":"NOT_LOCATED","detail":"not in initial window"}],"passage_assessment":"NEEDS_REVIEW"}
    fake=FakeClient([unresolved,unresolved])
    run=SemanticMappingEngine(repo,fake,max_neighbor_windows=1).map_units(target_index=idx,source_units=[unit])
    assert run.result["mappings"] == []
    assert run.result["unresolved_source_units"][0]["reason"] == "SEARCH_BUDGET_EXHAUSTED"
    assert run.result["passage_assessment"] == "NEEDS_REVIEW"
    assert len(fake.calls)==2
    assert run.search_budget_exhausted is True
    assert run.search_diagnostic


def test_structural_expansion_budget_is_not_a_verse_distance_rule(stage3_db, tamil_luk_usfm):
    repo=SemanticSourceRepository(stage3_db)
    unit=repo.unit_for_check(book="LUK",chapter=1,verse=68,tool="translationNotes",check_id="jx5n")
    idx=UsfmPassageIndex.from_path(tamil_luk_usfm,book_hint="LUK")
    seed=idx.window_for_source_reference("1","68")
    assert seed is not None and any(segment.verse == "68-79" for segment in seed.segments)
    unresolved={"mappings":[],"unresolved_source_units":[{"source_unit_id":unit.id,"reason":"AMBIGUOUS","detail":"competing passages"}],"passage_assessment":"NEEDS_REVIEW"}
    fake=FakeClient([unresolved])
    budget=PassageSearchBudget(max_model_calls=1,max_adjacent_layers=20,max_windows=50,max_segments=200,max_target_characters=100000)
    run=SemanticMappingEngine(repo,fake,search_budget=budget).map_units(target_index=idx,source_units=[unit])
    assert run.result["unresolved_source_units"][0]["reason"] == "SEARCH_BUDGET_EXHAUSTED"
    assert run.search_diagnostic == "model-call budget exhausted"


def test_usfm_is_byte_identical_after_mapping(stage3_db, tamil_php_usfm):
    original=Path(tamil_php_usfm).read_bytes()
    repo=SemanticSourceRepository(stage3_db); unit=repo.unit_for_check(book="PHP",chapter=1,verse=3,tool="translationNotes",check_id="gjyv")
    idx=UsfmPassageIndex.from_path(tamil_php_usfm,book_hint="PHP")
    response=fixture_response(unit.id,list(unit.source_token_ids),"PHP 1:3","PHP 1:6","என் தேவனை")
    SemanticMappingEngine(repo,FakeClient([response]),max_neighbor_windows=0).map_units(target_index=idx,source_units=[unit])
    assert Path(tamil_php_usfm).read_bytes() == original

def test_range_verse_keeps_continuation_poetry(tamil_luk_usfm):
    idx=UsfmPassageIndex.from_path(tamil_luk_usfm,book_hint="LUK")
    seg=idx.segment_for_source_reference("1","75")
    assert seg is not None and seg.verse == "68-79"
    assert len(seg.text) > 500
    assert "ஆபிரகாமுக்கு" in seg.text
    assert "இரட்சகரை" in seg.text

def test_fingerprint_changes_when_target_edited(stage3_db, tamil_php_usfm):
    repo=SemanticSourceRepository(stage3_db); unit=repo.unit_for_check(book="PHP",chapter=1,verse=3,tool="translationNotes",check_id="gjyv")
    idx=UsfmPassageIndex.from_path(tamil_php_usfm,book_hint="PHP")
    fake=FakeClient([fixture_response(unit.id,list(unit.source_token_ids),"PHP 1:3","PHP 1:6","என் தேவனை")])
    eng=SemanticMappingEngine(repo,fake,max_neighbor_windows=0); run1=eng.map_units(target_index=idx,source_units=[unit])
    text=Path(tamil_php_usfm).read_text(encoding="utf-8-sig").replace("என் தேவனை", "என் தேவனை மிகவும்")
    idx2=UsfmPassageIndex.from_text(text,book_hint="PHP")
    fake2=FakeClient([fixture_response(unit.id,list(unit.source_token_ids),"PHP 1:3","PHP 1:6","என் தேவனை")])
    run2=SemanticMappingEngine(repo,fake2,max_neighbor_windows=0).map_units(target_index=idx2,source_units=[unit])
    assert run1.fingerprint != run2.fingerprint

def test_companion_store_cache_round_trip(stage3_db, tamil_php_usfm, tmp_path):
    repo=SemanticSourceRepository(stage3_db); unit=repo.unit_for_check(book="PHP",chapter=1,verse=3,tool="translationNotes",check_id="gjyv")
    idx=UsfmPassageIndex.from_path(tamil_php_usfm,book_hint="PHP")
    response=fixture_response(unit.id,list(unit.source_token_ids),"PHP 1:3","PHP 1:6","என் தேவனை")
    store=SemanticMappingStore(tmp_path)
    fake=FakeClient([response]); r1=SemanticMappingEngine(repo,fake,max_neighbor_windows=0).map_units(target_index=idx,source_units=[unit],store=store)
    assert store.path_for("PHP",r1.fingerprint).exists()
    fake2=FakeClient([]); r2=SemanticMappingEngine(repo,fake2,max_neighbor_windows=0).map_units(target_index=idx,source_units=[unit],store=store)
    assert r2.cache_hit is True and not fake2.calls


def test_expanded_unresolved_cache_skips_all_repeat_model_calls(stage3_db, tamil_php_usfm, tmp_path):
    repo=SemanticSourceRepository(stage3_db); unit=repo.unit_for_check(book="PHP",chapter=1,verse=3,tool="translationNotes",check_id="gjyv")
    idx=UsfmPassageIndex.from_path(tamil_php_usfm,book_hint="PHP")
    unresolved={"mappings":[],"unresolved_source_units":[{"source_unit_id":unit.id,"reason":"AMBIGUOUS","detail":"competing candidates"}],"passage_assessment":"NEEDS_REVIEW"}
    store=SemanticMappingStore(tmp_path)
    first=FakeClient([unresolved,unresolved])
    r1=SemanticMappingEngine(repo,first,max_neighbor_windows=1).map_units(target_index=idx,source_units=[unit],store=store)
    assert len(first.calls) == 2 and r1.search_budget_exhausted
    second=FakeClient([])
    r2=SemanticMappingEngine(repo,second,max_neighbor_windows=1).map_units(target_index=idx,source_units=[unit],store=store)
    assert r2.cache_hit is True and r2.search_budget_exhausted is True
    assert second.calls == []

def test_alignment_guard_removes_cross_verse_false_links():
    from tc_ai_bridge.semantic_alignment_guard import guard_alignment_response
    raw={
      "links":[
        {"top_id":"H001","bottom_id":"T001","confidence":.99,"reason":"wrong local force"},
        {"top_id":"H002","bottom_id":"T002","confidence":.99,"reason":"valid local"},
      ],
      "implicit_top_ids":["H001"], "target_only_ids":[], "review_notes":[],
    }
    clean=guard_alignment_response(raw,{"H001"})
    assert [x["top_id"] for x in clean["links"]] == ["H002"]
    assert clean["implicit_top_ids"] == []
    assert "protected 1 source token" in clean["review_notes"][-1]


def test_source_anchor_failure_is_tolerated_per_check(stage3_db):
    from tc_ai_bridge.semantic_mapping_bridge import units_for_tc_checks
    class P:
        book_id="PHP"
    repo=SemanticSourceRepository(stage3_db)
    checks=[
      {"contextId":{"tool":"translationNotes","checkId":"gjyv","groupId":"figs-explicit","quoteString":"τῷ Θεῷ μου"}},
      {"contextId":{"tool":"translationNotes","checkId":"does-not-exist","groupId":"x","quoteString":"not-source-text"}},
    ]
    units, unresolved=units_for_tc_checks(repo,P(),"1","3",checks,tolerate_unresolved=True)
    assert any(u.check_id == "gjyv" for u in units)
    assert unresolved and unresolved[0]["state"] == "source_anchor_unresolved"

def test_review_policy_blocks_cross_verse_native_selection():
    from tc_ai_bridge.semantic_review_policy import apply_semantic_review_policy, native_tc_apply_allowed
    review={
      "check_id":"gjyv", "proposed_selection_ids":["T001"],
      "proposed_selection_text":["wrong local"],
      "proposed_selections":[{"text":"wrong local","occurrence":1,"occurrences":1}],
      "nothing_to_select":False, "verdict":"pass", "rationale":"model tried local selection",
    }
    pack={
      "checkStates":[{"checkId":"gjyv","sourceUnitId":"translationNotes:gjyv","state":"found_another_verse","targetSpans":[{"reference":"PHP 1:6","quote":"என் தேவனை"}]}],
      "mappings":[{"source_unit_id":"translationNotes:gjyv","source_reference":"PHP 1:3","target_spans":[{"reference":"PHP 1:6","quote":"என் தேவனை","start":34,"end":43}],"relationships":["CROSS_VERSE_REORDERED"],"meaning_status":"PRESERVED"}],
    }
    apply_semantic_review_policy(review,pack)
    assert review["selection_state"] == "found_another_verse"
    assert review["proposed_selections"] == []
    assert review["nothing_to_select"] is False
    assert native_tc_apply_allowed(review) is False
    assert "PHP 1:6" in review["rationale"]


def test_basic_native_apply_requires_exact_high_confidence_grounded_same_verse_mapping():
    from tc_ai_bridge.semantic_review_policy import native_tc_apply_allowed
    review={
      "selection_state":"found_this_verse", "verdict":"pass", "nothing_to_select":False,
      "proposed_selections":[{"text":"தேவன்","occurrence":1,"occurrences":1}],
      "semantic_mapping":{
        "meaning_status":"PRESERVED", "confidence":.95, "relationships":["SAME_VERSE"],
        "target_spans":[{"reference":"PHP 1:2","quote":"தேவன்","start":4,"end":9}],
      },
    }
    assert native_tc_apply_allowed(review) is True
    review["proposed_selections"]=[
      {"text":"என்","occurrence":1,"occurrences":1},
      {"text":"தேவனை","occurrence":1,"occurrences":1},
    ]
    review["semantic_mapping"]["target_spans"][0].update({"quote":"என் தேவனை","start":4,"end":13})
    assert native_tc_apply_allowed(review) is True
    review["semantic_mapping"]["confidence"] = .89
    assert native_tc_apply_allowed(review) is False
    review["semantic_mapping"]["confidence"] = .95
    review["proposed_selections"][0]["text"] = "வேறொரு சொல்"
    assert native_tc_apply_allowed(review) is False


def test_word_selections_inside_a_clause_span_are_applicable():
    """tC selects word tokens; Stage 3 verifies the clause they sit in.

    Demanding the two be equal refused every cleanly mapped check, so nothing was
    ever auto-selected. Containment inside a verified span is the real invariant,
    and it admits the compounded/suffixed target forms the review prompt asks for.
    """
    from tc_ai_bridge.semantic_review_policy import native_tc_apply_allowed
    review={
      "selection_state":"found_this_verse", "verdict":"pass", "nothing_to_select":False,
      "proposed_selections":[
        {"text":"यीशु","occurrence":1,"occurrences":1},
        {"text":"मसीह","occurrence":1,"occurrences":1},
      ],
      "semantic_mapping":{
        "meaning_status":"PRESERVED", "confidence":1.0, "relationships":["SAME_VERSE"],
        "target_spans":[{"reference":"PHP 1:19","quote":"यीशु मसीह की आत्माके दान के द्वारा,","start":48,"end":83}],
      },
    }
    assert native_tc_apply_allowed(review) is True
    # "आत्मा" is the tW token inside the compounded target form "आत्माके".
    review["proposed_selections"]=[{"text":"आत्मा","occurrence":1,"occurrences":1}]
    assert native_tc_apply_allowed(review) is True
    # A token from outside every verified span is still refused.
    review["proposed_selections"]=[{"text":"उद्धार","occurrence":1,"occurrences":1}]
    assert native_tc_apply_allowed(review) is False


def test_advanced_cross_verse_mapping_stays_companion_data():
    from tc_ai_bridge.semantic_review_policy import apply_semantic_review_policy, native_tc_apply_allowed
    review={
      "check_id":"x", "proposed_selections":[{"text":"local guess","occurrence":1,"occurrences":1}],
      "proposed_selection_ids":["B001"], "proposed_selection_text":["local guess"],
      "nothing_to_select":False, "verdict":"pass", "rationale":"",
    }
    pack={
      "checkStates":[{"checkId":"x","sourceUnitId":"translationNotes:x","state":"split_across_verses"}],
      "mappings":[{"source_unit_id":"translationNotes:x","target_spans":[
        {"reference":"LUK 1:2","quote":"a","start":0,"end":1},
        {"reference":"LUK 1:3","quote":"b","start":0,"end":1}],
        "relationships":["SPLIT_ACROSS_VERSES"],"meaning_status":"PRESERVED","confidence":.98}],
    }
    apply_semantic_review_policy(review,pack)
    assert review["proposed_selections"] == []
    assert review["nothing_to_select"] is False
    assert native_tc_apply_allowed(review) is False


def test_review_policy_unresolved_never_auto_omission():
    from tc_ai_bridge.semantic_review_policy import apply_semantic_review_policy
    review={"check_id":"x","proposed_selections":[],"proposed_selection_ids":[],"proposed_selection_text":[],"nothing_to_select":True,"verdict":"problem","rationale":"missing"}
    pack={"checkStates":[{"checkId":"x","sourceUnitId":"translationNotes:x","state":"needs_passage_review"}],"mappings":[]}
    apply_semantic_review_policy(review,pack)
    assert review["nothing_to_select"] is False
    assert review["verdict"] == "review"
    assert review["selection_state"] == "needs_passage_review"


def test_problem_plus_nothing_to_select_is_blocked_without_mapping():
    from tc_ai_bridge.semantic_review_policy import apply_semantic_review_policy, native_tc_apply_allowed
    review={"check_id":"x","proposed_selections":[],"nothing_to_select":True,"verdict":"problem","rationale":"problem"}
    apply_semantic_review_policy(review,None)
    assert review["nothing_to_select"] is False
    assert native_tc_apply_allowed(review) is False


def test_human_mapping_confirmation_audit(stage3_db, tamil_php_usfm, tmp_path):
    repo=SemanticSourceRepository(stage3_db); unit=repo.unit_for_check(book="PHP",chapter=1,verse=3,tool="translationNotes",check_id="gjyv")
    idx=UsfmPassageIndex.from_path(tamil_php_usfm,book_hint="PHP")
    response=fixture_response(unit.id,list(unit.source_token_ids),"PHP 1:3","PHP 1:6","என் தேவனை")
    store=SemanticMappingStore(tmp_path)
    run=SemanticMappingEngine(repo,FakeClient([response]),max_neighbor_windows=0).map_units(target_index=idx,source_units=[unit],store=store)
    event=store.confirm(book="PHP",fingerprint=run.fingerprint,source_unit_id=unit.id,decision="confirmed",reviewer="human")
    assert event["decision"] == "confirmed"
    payload=store.load("PHP",run.fingerprint)
    assert payload["humanConfirmations"][unit.id]["reviewer"] == "human"
    assert payload["reviewAudit"][-1]["sourceUnitId"] == unit.id

def test_seed_passage_batches_checks_across_verses(tamil_php_usfm):
    from tc_ai_bridge.semantic_mapping_bridge import checks_for_seed_passage
    class P:
        def checks_for_verse(self,ch,v):
            if str(ch)=="1" and str(v) in {"3","4","5","6"}:
                return [{"contextId":{"tool":"translationNotes","checkId":f"c{v}","groupId":"g","quoteString":f"q{v}"}}]
            return []
    idx=UsfmPassageIndex.from_path(tamil_php_usfm,book_hint="PHP")
    rows=checks_for_seed_passage(P(),idx,"1","3")
    assert {r["contextId"]["checkId"] for r in rows} == {"c3","c4","c5","c6"}
