from __future__ import annotations

import json
import shutil

import pytest

from tc_ai_bridge.models import TokenRef
from tc_ai_bridge.original_language_resources import (
    NT_BOOKS,
    OT_BOOKS,
    OriginalLanguageResourceError,
    blank_source_alignments,
    resource_inventory,
    resource_for_book,
    source_tokens_for_verse,
)


def test_uhb_genesis_1_1_matches_translationcore_golden_tokens():
    tokens = source_tokens_for_verse('gen', '1', '1')

    assert len(tokens) == 7
    assert tokens[0] == {
        'word': 'בְּ\u2060רֵאשִׁ֖ית',
        'strong': 'b:H7225',
        'lemma': 'רֵאשִׁית',
        'morph': 'He,R:Ncfsa',
        'occurrence': 1,
        'occurrences': 1,
    }
    assert tokens[-1]['word'] == 'הָ\u2060אָֽרֶץ'
    assert len(blank_source_alignments(tokens)) == 7
    assert all(group['bottomWords'] == [] for group in blank_source_alignments(tokens))


def test_uhb_qere_footnote_is_excluded_and_ketiv_is_retained():
    tokens = source_tokens_for_verse('gen', '8', '17')
    words = [token['word'] for token in tokens]

    assert 'הוצא' in words  # Ketiv in the main verse body.
    assert 'הַיְצֵ֣א' not in words  # Qere is inside a USFM footnote.
    assert len(tokens) == 21


def test_ugnt_titus_1_1_preserves_repeated_word_occurrences():
    tokens = source_tokens_for_verse('tit', '1', '1')
    theou = [token for token in tokens if token['word'] == 'Θεοῦ']

    assert len(tokens) == 17
    assert [(token['occurrence'], token['occurrences']) for token in theou] == [(1, 2), (2, 2)]
    assert theou[0]['strong'] == 'G23160'
    assert theou[0]['lemma'] == 'θεός'


def test_verse_bridge_recalculates_occurrences_across_combined_source():
    one = source_tokens_for_verse('tit', '1', '1')
    two = source_tokens_for_verse('tit', '1', '2')
    span = source_tokens_for_verse('tit', '1', '1-2')

    assert [token['word'] for token in span] == [token['word'] for token in one + two]
    for word in {token['word'] for token in span}:
        occurrences = [token for token in span if token['word'] == word]
        assert [token['occurrence'] for token in occurrences] == list(range(1, len(occurrences) + 1))
        assert all(token['occurrences'] == len(occurrences) for token in occurrences)


def test_resource_inventory_exposes_license_version_and_provenance():
    inventory = resource_inventory('tit')

    assert inventory['available'] is True
    assert inventory['resourceId'] == 'ugnt'
    assert inventory['version'] == '0.34'
    assert inventory['license'] == 'CC BY-SA 4.0'
    assert inventory['provenanceSha256'] == '319eaef950cd855aae56a293483223cee6240df03e72e5364ee674e05eee8472'
    assert inventory['licenseSha256'] == 'c5ddc53db325a35e7b023ba1e24c0da21ad9672b50b043c97eb73bd2a17e882e'


def test_all_66_bundled_book_packs_pass_hash_and_metadata_validation():
    for book_id in sorted(OT_BOOKS | NT_BOOKS):
        tokens = source_tokens_for_verse(book_id, '1', '1')
        assert tokens, f'expected original-language tokens for {book_id.upper()} 1:1'

    uhb = resource_for_book('gen')
    ugnt = resource_for_book('tit')
    assert uhb is not None and ugnt is not None
    uhb_index = json.loads((uhb.path / 'index.json').read_text(encoding='utf-8'))
    ugnt_index = json.loads((ugnt.path / 'index.json').read_text(encoding='utf-8'))
    assert uhb_index['totals'] == {'books': 39, 'verses': 23145, 'tokens': 305141}
    assert ugnt_index['totals'] == {'books': 27, 'verses': 7958, 'tokens': 137990}


def test_provenance_checksum_is_anchored_outside_the_resource_directory(tmp_path):
    bundled = resource_for_book('tit')
    assert bundled is not None
    copied = (
        tmp_path / 'el-x-koine' / 'bibles' / 'ugnt' /
        'v0.34_unfoldingWord'
    )
    shutil.copytree(bundled.path, copied)
    provenance = copied / 'PROVENANCE.json'
    provenance.write_text(provenance.read_text(encoding='utf-8') + '\n', encoding='utf-8')

    with pytest.raises(OriginalLanguageResourceError, match='provenance failed checksum'):
        source_tokens_for_verse('tit', '1', '1', tmp_path)


def test_legacy_translationcore_strongs_key_is_accepted():
    token = TokenRef.from_dict({
        'word': 'λόγος', 'strongs': 'G30560', 'occurrence': 1, 'occurrences': 1,
    })

    assert token.strong == 'G30560'
    assert token.to_dict()['strong'] == 'G30560'
