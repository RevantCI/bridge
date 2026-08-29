from pathlib import Path

from tc_ai_bridge.semantic_corpus_discovery import (
    candidates_from_run, propose_corpus_batches, rank_representative_candidates,
    structural_screen_candidates, validation_payload,
)
from tc_ai_bridge.semantic_mapping import (
    MappingRun, PassageSearchBudget, SemanticSourceRepository,
)


def test_irvtam_batch_selection_includes_php_regression(stage3_db, tamil_php_usfm, tamil_luk_usfm):
    repo=SemanticSourceRepository(stage3_db)
    batches=propose_corpus_batches(
        repo,[(tamil_luk_usfm,"LUK"),(tamil_php_usfm,"PHP")],max_batches=4,units_per_batch=6,
    )
    assert len(batches) == 4
    regression=[row for row in batches if row[1].book == "PHP" and "PHP 1:3" in row[2].references]
    assert regression and any(unit.check_id == "gjyv" for unit in regression[0][3])
    assert {row[1].book for row in batches} == {"LUK","PHP"}


def test_validation_candidates_remain_machine_proposed(stage3_db, tamil_php_usfm):
    repo=SemanticSourceRepository(stage3_db)
    unit=repo.unit_for_check(book="PHP",chapter=1,verse=3,tool="translationNotes",check_id="gjyv")
    mapping={
        "source_unit_id":unit.id,"source_token_ids":list(unit.source_token_ids),
        "source_reference":"PHP 1:3","target_spans":[{"reference":"PHP 1:6","quote":"என் தேவனை","start":12,"end":21}],
        "relationships":["CROSS_VERSE","CROSS_VERSE_REORDERED"],"meaning_status":"PRESERVED",
        "confidence":.98,"evidence":{"source":"τῷ θεῷ μου","target":"என் தேவனை","explanation":"meaning preserved"},
    }
    run=MappingRun((unit,),("PHP-PW3-0002",),{"mappings":[mapping],"unresolved_source_units":[],"passage_assessment":"MAPPED"},"abc")
    candidates=candidates_from_run(run)
    assert candidates[0]["proposalProvenance"] == "MACHINE_PROPOSED"
    assert candidates[0]["validationStatus"] == "UNCONFIRMED"
    assert candidates[0]["relationships"] == ["CROSS_VERSE","CROSS_VERSE_REORDERED"]


def test_representative_ranking_and_manifest(stage3_db, tamil_php_usfm, tamil_luk_usfm):
    rows=[]
    for index, relationship in enumerate(["SAME_VERSE","IMPLICIT","CROSS_VERSE_REORDERED"]):
        rows.append({
            "candidateId":str(index),"diagnosticScore":20+index*30,"relationships":[relationship],
            "sourceUnit":{"source_reference":f"{'PHP' if index == 2 else 'LUK'} 1:{index+1}"},
        })
    ranked=rank_representative_candidates(rows,limit=3)
    assert [row["relationships"][0] for row in ranked] == ["CROSS_VERSE_REORDERED","IMPLICIT","SAME_VERSE"]
    payload=validation_payload(
        candidates=ranked,corpora=[(tamil_luk_usfm,"LUK"),(tamil_php_usfm,"PHP")],
        source_db=stage3_db,model="test",budget=PassageSearchBudget(),
    )
    assert payload["languageSpecificRulesUsed"] is False
    assert payload["validationStatus"] == "UNCONFIRMED"
    assert len(payload["sourceDatabase"]["sha256"]) == 64


def test_representative_ranking_fills_requested_tail_after_diversity_caps():
    rows=[{
        "candidateId":str(index),"diagnosticScore":100-index,"relationships":["SAME_VERSE"],
        "sourceUnit":{"source_reference":f"LUK 1:{index+1}"},
    } for index in range(12)]
    ranked=rank_representative_candidates(rows,limit=10)
    assert len(ranked) == 10
    assert [row["rank"] for row in ranked] == list(range(1,11))


def test_local_structural_screen_is_explicitly_unconfirmed(stage3_db, tamil_php_usfm, tamil_luk_usfm):
    repo=SemanticSourceRepository(stage3_db)
    candidates=structural_screen_candidates(
        repo,[(tamil_luk_usfm,"LUK"),(tamil_php_usfm,"PHP")],limit=25,
    )
    assert len(candidates) == 25
    assert all(row["proposalProvenance"] == "MACHINE_PROPOSED" for row in candidates)
    assert all(row["validationStatus"] == "UNCONFIRMED" for row in candidates)
    sentinel=next(row for row in candidates if row["candidateId"] == "php-1-3-gjyv-cross-verse-regression")
    assert sentinel["targetSpans"][0]["quote"] == "என் தேவனை"
    assert "CROSS_VERSE_REORDERED" in sentinel["relationships"]
    structural=[row for row in candidates if row.get("proposalScope") == "STRUCTURAL_SCREEN"]
    assert structural and all(row["meaningStatus"] == "UNCERTAIN" and not row["targetSpans"] for row in structural)
