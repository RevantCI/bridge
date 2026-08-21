import pytest

from tc_ai_bridge.alignment_engine import realign
from tc_ai_bridge.models import AlignmentGroup, TokenRef, VerseAlignment


def _token(word, *, bottom=False):
    return TokenRef(word, type="bottomWord" if bottom else "")


def test_realign_keeps_source_group_order_stable():
    h1, h2, h3 = (_token("h1"), _token("h2"), _token("h3"))
    t1, t2, t3 = (_token("t1", bottom=True), _token("t2", bottom=True), _token("t3", bottom=True))
    verse = VerseAlignment([
        AlignmentGroup([h1], [t1]),
        AlignmentGroup([h2], [t2]),
        AlignmentGroup([h3], [t3]),
    ], [])

    changed = realign(verse, [h2], [t3])

    assert [group.top_words[0].word for group in changed.alignments] == ["h1", "h2", "h3"]
    assert changed.alignments[1].bottom_words[0].word == "t3"


@pytest.mark.parametrize("source_count,target_count", [(1, 1), (1, 2), (2, 1), (2, 2)])
def test_realign_supports_every_group_cardinality(source_count, target_count):
    source = [_token("h1"), _token("h2")]
    target = [_token("t1", bottom=True), _token("t2", bottom=True)]
    verse = VerseAlignment([
        AlignmentGroup([source[0]], [target[0]]),
        AlignmentGroup([source[1]], [target[1]]),
    ], [])

    changed = realign(verse, source[:source_count], target[:target_count])

    assert any(
        len(group.top_words) == source_count and len(group.bottom_words) == target_count
        and {token.signature for token in group.top_words}
        == {token.signature for token in source[:source_count]}
        and {token.signature for token in group.bottom_words}
        == {token.signature for token in target[:target_count]}
        for group in changed.alignments
    )
