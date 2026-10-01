"""The one fragment reader: what a stored verse string shows (#91, Phase 1a).

`usfm_parser.parse_usfm` decides where a verse starts and ends in a whole book.
This module answers the other question every per-verse consumer asks of the
stored string it produced: *which of these code points are Scripture a reader
sees*, which are notes, which are markup, and where does each visible character
come from. The reader display, Language QA, the checks' tokeniser, the names
check's offsets and the aligned exporter all need the same answer, and until
this module they each had a regex of their own.

Design, and why it is not usfmtc:

- usfmtc reports positions for *elements* (paragraphs, verses, notes) but not
  for text nodes, and these readers run on hot paths -- every chapter open,
  every `alignment.get`, every save, every check -- thousands of times per
  book. So this is Bridge's own scanner, grown from `language_qa.lift_inline_usfm`
  and the frontend's `parseVerseNotes`, and it is bound to usfmtc by a parity
  test: for every stored verse of both IRV fixtures, `lift_verse(s).plain`
  tokenises identically to the plain text walked out of usfmtc's own parse of
  that verse (`tests/project_io/test_usfm_verse.py`). The USJ walker lives in
  the test, never here.
- **Deletion only.** `plain` is `raw` with ranges removed, never rewritten or
  reordered, so `raw_index`/`map_offset` are exact and a span of plain text
  that crosses no removed range is byte-identical to the raw span it maps to.
  That is what lets a finding computed on the raw stored string land on the
  right displayed word, and a fix made on the display be written back.
- **Total.** It never refuses a verse: the best-effort `plain` is always
  returned, and anything the markup got wrong is in `warnings`. Language QA
  keeps declining to scan a verse with warnings; the reader cannot decline to
  show one.

Marker classes -- the one list the parity test guards:

- **Notes**, removed with their content and recorded in `notes`: `\\f`, `\\fe`,
  `\\ef` (footnote kinds) and `\\x`, `\\ex` (cross-reference kinds), each from
  its opener to its own closer. One adjacent space goes with the note (the
  frontend's swallow rule, pinned by `test_language_qa.py`'s lift table).
- **Non-Scripture character content**, removed with its content: alternate
  chapter/verse numbers `\\va`, `\\vp`, `\\ca`, `\\cp`, figures `\\fig`, and an
  inline quotation reference `\\rq`. None of it is a translation of any word.
- **Attributes**: the `|…` of `\\w word|lemma="…"\\w*` and of a milestone such
  as `\\zaln-s |x-strong="…"\\*`, up to the closing marker.
- **Every other marker token**: character styles (`\\nd`, `\\wj`, `\\it`, nested
  `\\+nd` …) and their closers, `\\w`/`\\w*`, milestones and their bare `\\*`,
  and the paragraph/poetry markers chapter JSON keeps inside a verse
  (`…;\\n\\q2 …`). The marker goes, its content stays; an opener's one following
  space is marker syntax and goes with it, a closer's is text. A character
  style that opens and closes is recorded in `styles` so a reader can render
  it; the line break before a `\\q2` stays, as whitespace.
"""
from __future__ import annotations

import bisect
import re
from dataclasses import dataclass, field
from typing import Any

from .usfm import marker_balance_issues

# Notes: opener, one whitespace char, body, the same marker's closer.
_NOTE = re.compile(r"\\(fe|ef|ex|f|x)\s.*?\\\1\*", re.DOTALL)
_FOOTNOTE_KINDS = frozenset({"f", "fe", "ef"})
# A note-family marker anywhere outside a complete note is a problem, not text.
_NOTE_FAMILY = re.compile(r"\\(?!fig\b)[fx][A-Za-z]*\b")
# Character content that is not Scripture: alternate numbering, figures, an
# inline quotation reference. Removed with its content.
_NON_SCRIPTURE = re.compile(r"\\(va|vp|ca|cp|fig|rq)\s.*?\\\1\*", re.DOTALL)
# USFM 3 attributes: the bar up to the closing marker is not visible text.
_ATTRIBUTES = re.compile(r"\|[^\\]*(?=\\(?:\+?[A-Za-z0-9_-]+)?\*)")
# Any other marker token. Groups: 1 nesting plus, 2 name, 3 closer star,
# 4 a milestone's bare star, 5 one following space.
_MARKER = re.compile(r"\\(?:(\+?)([A-Za-z0-9_-]+)(\*)?|(\*))( )?")
# Inside a note body: `\fr 1.6 \fq quoted \ft body` into (marker, text) pairs.
_NOTE_PART = re.compile(r"\\([A-Za-z0-9+_-]+)\*?\s*(.*?)(?=\\[A-Za-z0-9+_-]+\*?|$)", re.DOTALL)
_FIRST_INNER_MARKER = re.compile(r"\\[A-Za-z0-9]")


@dataclass(frozen=True)
class VerseNote:
    kind: str                       # "footnote" or "xref"
    caller: str                     # the glyph after \f / \x, usually "+"
    reference: str                  # \fr (footnote) or \xo (xref) text, or ""
    parts: tuple[tuple[str, str], ...]  # (marker without backslash, text), in order
    text: str                       # everything but the reference, flattened
    position: int                   # index into `plain` where the note sat
    raw_start: int                  # the removed raw range, swallow rule applied
    raw_end: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind, "caller": self.caller, "reference": self.reference,
            "parts": [{"marker": marker, "text": text} for marker, text in self.parts],
            "text": self.text, "position": self.position,
        }


@dataclass(frozen=True)
class StyleSpan:
    marker: str   # without backslash or nesting plus: "nd", "wj", "it", "w" ...
    start: int    # into `plain`, code points
    end: int

    def to_dict(self) -> dict[str, Any]:
        return {"marker": self.marker, "start": self.start, "end": self.end}


@dataclass(frozen=True)
class LiftedVerse:
    raw: str
    plain: str
    raw_index: tuple[int, ...]            # raw_index[i] is the raw offset of plain[i]
    notes: tuple[VerseNote, ...] = ()
    styles: tuple[StyleSpan, ...] = ()
    warnings: tuple[str, ...] = ()
    removed: tuple[tuple[int, int], ...] = field(default=())  # raw ranges, merged

    def map_offset(self, raw_offset: int) -> int:
        """Where a raw offset lands in `plain`. An offset inside a removed range
        collapses to the position the removal left behind, so a span that lived
        entirely inside a note maps to a zero-length range."""
        if raw_offset <= 0:
            return 0
        if raw_offset >= len(self.raw):
            return len(self.plain)
        return bisect.bisect_left(self.raw_index, raw_offset)

    def raw_span(self, start: int, end: int) -> tuple[int, int] | None:
        """Raw half-open span for plain[start:end], or None when that span
        crosses removed markup (it would not be one contiguous piece of raw text)."""
        if not 0 <= start < end <= len(self.plain):
            return None
        raw_start, raw_end = self.raw_index[start], self.raw_index[end - 1] + 1
        return (raw_start, raw_end) if raw_end - raw_start == end - start else None

    def to_dict(self) -> dict[str, Any]:
        """The display payload the protocol carries (#91 Phase 2). Offsets are
        code points, as every engine finding's are."""
        return {
            "plain": self.plain,
            "notes": [note.to_dict() for note in self.notes],
            "removed": [[start, end] for start, end in self.removed],
            "styles": [span.to_dict() for span in self.styles],
            "warnings": list(self.warnings),
        }


# Character-style markers whose close-then-reopen with nothing between is
# never meant: `\wj And \wj*\wj there` is one run of red letters, and the
# space inside the reopened marker is syntax, so a faithful reader (this one,
# usfmtc) glues the words. Notes are not here (`\f*\f ` is two notes) and
# neither is `\w` (the KJV's `who\w*\w soever` is one word on purpose). #203.
STYLE_MARKERS = frozenset({
    "add", "bd", "bdit", "bk", "dc", "em", "it", "k", "lit", "nd", "no", "ord", "pn",
    "png", "qac", "qs", "qt", "rq", "sc", "sig", "sls", "sup", "tl", "wj",
})
_STYLE_REOPEN = re.compile(r"\\(?P<plus>\+?)(?P<marker>[A-Za-z]+)\*\\(?P=plus)(?P=marker) ")


@dataclass(frozen=True)
class MarkupFix:
    """One mechanical repair of the raw string: replace raw[start:end] with
    `replacement`. `original` is raw[start:end], so a stale fix is detectable."""
    marker: str
    start: int
    end: int
    original: str
    replacement: str


def redundant_style_reopens(raw: str) -> tuple[MarkupFix, ...]:
    """Every `\\X*\\X ` pair for a character-style X, with the repair: drop the
    pair, keeping one space when it is glued to the previous word (so
    `lepers\\wj*\\wj in` becomes `lepers in`, and `And \\wj*\\wj there` becomes
    `And there`)."""
    fixes = []
    for match in _STYLE_REOPEN.finditer(raw):
        marker = match.group("marker")
        if marker not in STYLE_MARKERS:
            continue
        start, end = match.span()
        glued = start > 0 and not raw[start - 1].isspace()
        fixes.append(MarkupFix(marker, start, end, raw[start:end], " " if glued else ""))
    return tuple(fixes)


def normalize_style_reopens(raw: str) -> str:
    """`raw` with every redundant style reopen repaired (see above)."""
    out: list[str] = []
    cursor = 0
    for fix in redundant_style_reopens(raw):
        out.append(raw[cursor:fix.start])
        out.append(fix.replacement)
        cursor = fix.end
    out.append(raw[cursor:])
    return "".join(out)


def _note(raw: str, match: re.Match[str], position: int, raw_start: int, raw_end: int) -> VerseNote:
    marker = match.group(1)
    kind = "footnote" if marker in _FOOTNOTE_KINDS else "xref"
    # Body sits between the opener (`\f` + one whitespace char) and the closer.
    body = raw[match.start() + len(marker) + 2:match.end() - len(marker) - 2].strip()
    first = _FIRST_INNER_MARKER.search(body)
    caller = (body if first is None else body[:first.start()]).strip() or "+"
    rest = "" if first is None else body[first.start():]
    parts = tuple(
        (part.group(1), part.group(2).strip())
        for part in _NOTE_PART.finditer(rest)
        if part.group(2).strip()
    )
    reference_marker = "fr" if kind == "footnote" else "xo"
    reference = next((text for name, text in parts if name == reference_marker), "")
    text = " ".join(text for name, text in parts if name != reference_marker).strip()
    return VerseNote(kind, caller, reference, parts, text, position, raw_start, raw_end)


def lift_verse(raw: str) -> LiftedVerse:
    """What the stored verse string shows, and where each visible code point
    came from. See the module docstring for the marker classes."""
    removed = bytearray(len(raw))

    def remove(start: int, end: int) -> None:
        removed[start:end] = b"\x01" * (end - start)

    warnings: list[str] = list(marker_balance_issues(raw))

    def swallow_one_space(start: int, end: int) -> tuple[int, int]:
        # Removing content between two spaces would leave a double space
        # behind. Swallow exactly one, and nothing else (the frontend's rule).
        if start == 0 or raw[start - 1].isspace():
            if end < len(raw) and raw[end].isspace():
                end += 1
        elif end == len(raw) and raw[start - 1].isspace():
            start -= 1
        return start, end

    note_matches: list[tuple[re.Match[str], int, int]] = []
    for match in _NOTE.finditer(raw):
        start, end = swallow_one_space(*match.span())
        remove(start, end)
        note_matches.append((match, start, end))
    for match in _NOTE_FAMILY.finditer(raw):
        if not removed[match.start()]:
            warnings.append(
                "Footnote or cross-reference markup outside a complete "
                "\\f … \\f* or \\x … \\x* note"
            )
            break
    for match in _NON_SCRIPTURE.finditer(raw):
        if not removed[match.start()]:
            remove(*swallow_one_space(*match.span()))
    for match in _ATTRIBUTES.finditer(raw):
        if not removed[match.start()]:
            remove(*match.span())

    # (name, raw offset of the opener) for character styles still open.
    open_styles: list[tuple[str, int]] = []
    style_ranges: list[tuple[str, int, int]] = []  # name, raw open, raw close
    for match in _MARKER.finditer(raw):
        if removed[match.start()]:
            continue
        end = match.end()
        closer = bool(match.group(3) or match.group(4))
        if match.group(5) and closer:
            end -= 1  # the space after a closer is text, not marker syntax
        remove(match.start(), end)
        name = match.group(2)
        if name is None:
            continue
        if match.group(3):
            for index in range(len(open_styles) - 1, -1, -1):
                if open_styles[index][0] == name:
                    _, opened_at = open_styles.pop(index)
                    style_ranges.append((name, opened_at, match.start()))
                    break
        else:
            open_styles.append((name, end))

    raw_index = tuple(i for i in range(len(raw)) if not removed[i])
    plain = "".join(raw[i] for i in raw_index)

    def plain_pos(raw_offset: int) -> int:
        return bisect.bisect_left(raw_index, raw_offset)

    stray = plain.find("\\")
    if stray != -1:
        warnings.append(f"Backslash that is not a USFM marker at code-point {raw_index[stray]}")
    bar = plain.find("|")
    if bar != -1:
        # Attributes whose marker never closes properly (seen for real: a custom
        # `\zsem-s |x-note="..."*` milestone ending in a bare `*`) would otherwise
        # leak glosses, Greek and notes into the visible text.
        warnings.append(f"Word attributes not closed by a USFM marker at code-point {raw_index[bar]}")

    notes = tuple(
        _note(raw, match, plain_pos(start), start, end) for match, start, end in note_matches
    )
    styles = tuple(
        StyleSpan(name, plain_pos(opened_at), plain_pos(closed_at))
        for name, opened_at, closed_at in sorted(style_ranges, key=lambda item: item[1])
    )
    ranges: list[tuple[int, int]] = []
    start = None
    for index, flag in enumerate(removed):
        if flag and start is None:
            start = index
        elif not flag and start is not None:
            ranges.append((start, index))
            start = None
    if start is not None:
        ranges.append((start, len(raw)))

    return LiftedVerse(
        raw=raw, plain=plain, raw_index=raw_index, notes=notes, styles=styles,
        warnings=tuple(warnings), removed=tuple(ranges),
    )
