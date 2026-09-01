"""Canonical Unicode code-point coordinate helpers for passage-semantic v1.

Persisted spans are half-open code-point offsets over raw, unnormalised text.
Python string indexes already use code points; the explicit helpers keep that
contract visible and provide the UTF-8/UTF-16 conversions needed at wire edges.
"""
from __future__ import annotations

import regex


class UnicodeCoordinateError(ValueError):
    pass


def _check_bounds(text: str, start: int, end: int) -> None:
    if not isinstance(start, int) or not isinstance(end, int) or start < 0 or end < start or end > len(text):
        raise UnicodeCoordinateError(f"Invalid code-point range [{start}, {end}) for length {len(text)}")


def codepoint_span(text: str, start: int, end: int) -> str:
    _check_bounds(text, start, end)
    return text[start:end]


def validate_codepoint_span(text: str, start: int, end: int, quote: str) -> None:
    actual = codepoint_span(text, start, end)
    if actual != quote:
        raise UnicodeCoordinateError("Persisted code-point span does not match its raw quote")


def codepoint_to_utf8_offset(text: str, offset: int) -> int:
    _check_bounds(text, offset, offset)
    return len(text[:offset].encode("utf-8"))


def codepoint_to_utf16_offset(text: str, offset: int) -> int:
    _check_bounds(text, offset, offset)
    return len(text[:offset].encode("utf-16-le")) // 2


def utf8_to_codepoint_offset(text: str, offset: int) -> int:
    encoded = text.encode("utf-8")
    if offset < 0 or offset > len(encoded):
        raise UnicodeCoordinateError("UTF-8 offset is outside the text")
    try:
        return len(encoded[:offset].decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise UnicodeCoordinateError("UTF-8 offset splits a Unicode scalar value") from exc


def utf16_to_codepoint_offset(text: str, offset: int) -> int:
    encoded = text.encode("utf-16-le")
    byte_offset = offset * 2
    if byte_offset < 0 or byte_offset > len(encoded):
        raise UnicodeCoordinateError("UTF-16 offset is outside the text")
    try:
        return len(encoded[:byte_offset].decode("utf-16-le"))
    except UnicodeDecodeError as exc:
        raise UnicodeCoordinateError("UTF-16 offset splits a surrogate pair") from exc


def grapheme_boundaries(text: str) -> tuple[int, ...]:
    positions = [0]
    for match in regex.finditer(r"\X", text):
        positions.append(match.end())
    return tuple(positions)


def validate_grapheme_boundary(text: str, offset: int) -> None:
    if offset not in grapheme_boundaries(text):
        raise UnicodeCoordinateError(f"Code-point offset {offset} splits a grapheme cluster")

