from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Any

from .models import TokenRef, VerseAlignment
from .usfm import whitespace_tokens


class AlignedUsfmError(ValueError):
    pass


_EXCLUDED_RE = re.compile(r"\\(?P<marker>f|x)\s.*?\\(?P=marker)\*", re.IGNORECASE | re.DOTALL)
_MARKER_RE = re.compile(r"\\[A-Za-z0-9+_-]+\*?")


@dataclass(frozen=True)
class _TokenSpan:
    token: TokenRef
    start: int
    end: int


def _target_tokens(text: str) -> list[TokenRef]:
    words = whitespace_tokens(text)
    totals = Counter(words)
    seen: Counter[str] = Counter()
    result: list[TokenRef] = []
    for word in words:
        seen[word] += 1
        result.append(TokenRef(word, seen[word], totals[word], type="bottomWord"))
    return result


def _masked_ranges(text: str) -> list[bool]:
    masked = [False] * len(text)
    for match in _EXCLUDED_RE.finditer(text):
        for index in range(match.start(), match.end()):
            masked[index] = True
    for match in _MARKER_RE.finditer(text):
        for index in range(match.start(), match.end()):
            masked[index] = True
    return masked


def _token_spans(text: str) -> list[_TokenSpan]:
    masked = _masked_ranges(text)
    cursor = 0
    spans: list[_TokenSpan] = []
    for token in _target_tokens(text):
        position = text.find(token.word, cursor)
        while position >= 0:
            end = position + len(token.word)
            if not any(masked[position:end]):
                spans.append(_TokenSpan(token, position, end))
                cursor = end
                break
            position = text.find(token.word, end)
        else:
            raise AlignedUsfmError(
                f"Could not locate target token {token.word!r} in the current verse text."
            )
    return spans


def _attribute(value: Any) -> str:
    return (
        str(value or "")
        .replace("&", "&amp;")
        .replace('"', "&quot;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _source_milestone(token: TokenRef) -> str:
    attributes = []
    if token.strong:
        attributes.append(("x-strong", token.strong))
    if token.lemma:
        attributes.append(("x-lemma", token.lemma))
    if token.morph:
        attributes.append(("x-morph", token.morph))
    attributes.extend((
        ("x-occurrence", token.occurrence),
        ("x-occurrences", token.occurrences),
        ("x-content", token.word),
    ))
    rendered = " ".join(f'{name}="{_attribute(value)}"' for name, value in attributes)
    return f"\\zaln-s |{rendered}\\*"


def _target_word(token: TokenRef, original: str) -> str:
    return (
        f'\\w {original}|x-occurrence="{token.occurrence}" '
        f'x-occurrences="{token.occurrences}"\\w*'
    )


def render_aligned_verse(text: str, alignment: VerseAlignment) -> str:
    """Render translationCore alignment data in unfoldingWord's USFM 3
    `zaln`/`w` extension convention while preserving target punctuation and
    inline USFM surrounding each target token.

    Multiple source tokens sharing a target span are represented by nested
    milestones. A target span must be contiguous because a single USFM
    milestone cannot represent a discontinuous set without changing meaning.
    """
    spans = _token_spans(text)
    expected = [span.token.signature for span in spans]
    actual = [token.signature for token in alignment.all_bottom()]
    if Counter(expected) != Counter(actual):
        raise AlignedUsfmError(
            "Alignment target tokens do not exactly match the current verse text. Recheck the verse before export."
        )
    if not alignment.all_top():
        raise AlignedUsfmError(
            "No original-language source tokens are available for aligned USFM export."
        )

    position_by_signature = {span.token.signature: index for index, span in enumerate(spans)}
    opens: dict[int, list[TokenRef]] = {}
    closes: dict[int, int] = {}
    represented_bottom: set[str] = set()
    for group_index, group in enumerate(alignment.alignments, 1):
        if not group.top_words:
            if group.bottom_words:
                raise AlignedUsfmError(f"Alignment group {group_index} has target words but no source words.")
            continue
        if not group.bottom_words:
            # An unresolved source token has no target span to serialize. It
            # remains explicitly incomplete in the project and is not falsely
            # attached to an unrelated target word.
            continue
        try:
            positions = sorted(position_by_signature[token.signature] for token in group.bottom_words)
        except KeyError as exc:
            raise AlignedUsfmError(
                f"Alignment group {group_index} contains a target token absent from the verse."
            ) from exc
        if positions != list(range(positions[0], positions[-1] + 1)):
            raise AlignedUsfmError(
                f"Alignment group {group_index} uses discontinuous target words and cannot be serialized safely."
            )
        for token in group.bottom_words:
            if token.signature in represented_bottom:
                raise AlignedUsfmError(
                    f"Target token {token.word!r} occurs in more than one alignment group."
                )
            represented_bottom.add(token.signature)
        opens.setdefault(positions[0], []).extend(group.top_words)
        closes[positions[-1]] = closes.get(positions[-1], 0) + len(group.top_words)

    pieces: list[str] = []
    cursor = 0
    for index, span in enumerate(spans):
        pieces.append(text[cursor:span.start])
        pieces.extend(_source_milestone(token) for token in opens.get(index, []))
        pieces.append(_target_word(span.token, text[span.start:span.end]))
        pieces.extend("\\zaln-e\\*" for _ in range(closes.get(index, 0)))
        cursor = span.end
    pieces.append(text[cursor:])
    return "".join(pieces)
