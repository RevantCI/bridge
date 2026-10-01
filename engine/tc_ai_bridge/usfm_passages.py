"""Language-neutral USFM passage indexing for Bridge semantic mapping.

This parser exists for semantic-retrieval context, not for rendering/editing USFM.
It deliberately treats verse numbers as anchors rather than semantic boundaries.
Continuation lines (poetry, lists, indented paragraphs, etc.) remain attached to
the active verse, including verse-range markers such as ``\\v 68-79``.

Passage windows are retrieval hints only. They are never used to conclude that a
meaning outside the initial window is absent; the semantic mapper can expand to
adjacent windows.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Iterable, Iterator

from .usfm_parser import UsfmParseError, parse_usfm, read_usfm_text
from .usfm_verse import plain_text

# Strong boundaries are structural hints. Poetry/list line markers are not
# boundaries by themselves; otherwise poetic passages would degenerate to one
# verse per window in many projects.
_STRONG_BOUNDARY_MARKERS = {
    "p", "m", "b", "s", "s1", "s2", "s3", "s4", "ms", "ms1", "ms2",
    "mr", "r", "sr", "cl", "cd", "qa",
}
_TERMINAL_PUNCT = tuple(".!?…।॥؟。！？")


def strip_usfm_inline(text: str) -> str:
    """Visible Scripture text of one verse string, whitespace collapsed.

    Since #91 Phase 3b this is the fragment reader (`usfm_verse.plain_text`),
    the same text checks, alignment and the reader show. The regex it replaced
    deleted the space after a *closing* style marker too (`\\wj text\\wj* more`
    read as "textmore"); the reader keeps it.
    """
    return plain_text(text)


def _verse_bounds(verse: str) -> tuple[int | None, int | None]:
    raw = str(verse).strip().replace("–", "-")
    if raw.isdigit():
        n = int(raw)
        return n, n
    if "-" in raw:
        a, b = raw.split("-", 1)
        if a.isdigit() and b.isdigit():
            return int(a), int(b)
    # Verse suffixes (e.g. 4a) are retained but not coerced.
    return None, None


@dataclass(frozen=True)
class TargetSegment:
    reference: str
    book: str
    chapter: str
    verse: str
    text: str
    ordinal: int

    def contains(self, chapter: str | int, verse: str | int) -> bool:
        if str(chapter) != self.chapter:
            return False
        lo, hi = _verse_bounds(self.verse)
        try:
            n = int(str(verse))
        except ValueError:
            return str(verse) == self.verse
        return lo is not None and hi is not None and lo <= n <= hi


@dataclass(frozen=True)
class PassageWindow:
    id: str
    book: str
    segments: tuple[TargetSegment, ...]
    ordinal: int

    @property
    def references(self) -> list[str]:
        return [s.reference for s in self.segments]

    @property
    def text(self) -> str:
        return " ".join(s.text for s in self.segments if s.text).strip()

    @property
    def fingerprint(self) -> str:
        payload = "\u241f".join(f"{s.reference}\u241e{s.text}" for s in self.segments)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class UsfmPassageIndex:
    """Parse one canonical book USFM/SFM file into retrieval passage windows."""

    def __init__(self, *, book: str, segments: list[TargetSegment], windows: list[PassageWindow]):
        self.book = book.upper()
        self.segments = segments
        self.windows = windows
        self._by_ref = {s.reference: s for s in segments}
        self._window_by_ref: dict[str, PassageWindow] = {}
        for window in windows:
            for segment in window.segments:
                self._window_by_ref[segment.reference] = window

    @classmethod
    def from_path(cls, path: str | Path, *, book_hint: str = "") -> "UsfmPassageIndex":
        return cls.from_text(read_usfm_text(path), book_hint=book_hint)

    @classmethod
    def from_text(cls, text: str, *, book_hint: str = "") -> "UsfmPassageIndex":
        r"""One segment per verse the document parser finds, windows from its
        structure (#91 Phase 3b).

        Where a verse starts and ends is `usfm_parser.parse_usfm`'s decision --
        the same one import makes, so a mid-line ``\q1 \v 1`` is a verse here
        too (the line regex this replaced folded it into the previous verse).
        A segment's text is what the verse shows (`usfm_verse.plain_text`),
        headings already cut out by the parser. A window boundary falls before
        the first verse of a chapter and before any verse preceded by a strong
        paragraph-level marker (`_STRONG_BOUNDARY_MARKERS`); a window also ends
        after a verse that ends in terminal punctuation.
        """
        try:
            parsed = parse_usfm(text)
        except UsfmParseError as exc:
            raise ValueError(f"USFM could not be parsed: {exc}") from exc
        book = (book_hint or parsed.book_code).upper().strip()
        if not book:
            raise ValueError("USFM has no \\id marker and no book_hint was supplied")

        # Boundaries come from the structure walk: a chapter or a strong marker
        # marks the next verse; the first verse of the book is always marked.
        boundary_before: dict[int, bool] = {}
        pending_boundary = True
        verse_index = 0
        for item in parsed.structure:
            if item.kind == "chapter" or (item.kind == "para" and item.marker in _STRONG_BOUNDARY_MARKERS):
                pending_boundary = True
            elif item.kind == "verse":
                boundary_before[verse_index] = pending_boundary
                pending_boundary = False
                verse_index += 1

        segments: list[TargetSegment] = []
        boundaries: list[bool] = []
        for i, verse in enumerate(parsed.verses):
            segments.append(TargetSegment(
                reference=f"{book} {verse.chapter}:{verse.verse}", book=book,
                chapter=verse.chapter, verse=verse.verse,
                text=plain_text(verse.text), ordinal=i,
            ))
            boundaries.append(boundary_before.get(i, i == 0))

        windows: list[PassageWindow] = []
        acc: list[TargetSegment] = []
        window_n = 0

        def flush() -> None:
            nonlocal acc, window_n
            if not acc:
                return
            window_n += 1
            windows.append(PassageWindow(
                id=f"{book}-PW3-{window_n:04d}", book=book,
                segments=tuple(acc), ordinal=window_n - 1,
            ))
            acc = []

        for i, segment in enumerate(segments):
            if acc and boundaries[i]:
                flush()
            acc.append(segment)
            # Punctuation is a retrieval optimization only. If it is wrong for a
            # language, adaptive neighboring-window expansion repairs the boundary.
            if segment.text.rstrip().endswith(_TERMINAL_PUNCT):
                flush()
        flush()
        return cls(book=book, segments=segments, windows=windows)

    def segment_for_source_reference(self, chapter: str | int, verse: str | int) -> TargetSegment | None:
        # Prefer exact, then target range containing the canonical source verse.
        exact = self._by_ref.get(f"{self.book} {chapter}:{verse}")
        if exact:
            return exact
        for segment in self.segments:
            if segment.contains(chapter, verse):
                return segment
        return None

    def window_for_source_reference(self, chapter: str | int, verse: str | int) -> PassageWindow | None:
        seg = self.segment_for_source_reference(chapter, verse)
        if seg:
            return self._window_by_ref.get(seg.reference)
        # Versification redistribution can remove the exact target reference.
        # Choose the nearest window in the same chapter as retrieval seed only.
        try:
            target_n = int(str(verse))
        except ValueError:
            return None
        candidates: list[tuple[int, TargetSegment]] = []
        for seg in self.segments:
            if seg.chapter != str(chapter):
                continue
            lo, hi = _verse_bounds(seg.verse)
            if lo is None:
                continue
            if lo <= target_n <= (hi or lo):
                dist = 0
            else:
                dist = min(abs(target_n - lo), abs(target_n - (hi or lo)))
            candidates.append((dist, seg))
        if not candidates:
            return None
        _, seg = min(candidates, key=lambda x: (x[0], x[1].ordinal))
        return self._window_by_ref.get(seg.reference)

    def expand(self, window: PassageWindow, *, before: int = 1, after: int = 1) -> list[PassageWindow]:
        """Return adjacent structural windows around ``window``.

        ``before``/``after`` are computational retrieval controls, never a
        linguistic claim about how many verses can realize a source meaning.
        """
        lo = max(0, window.ordinal - max(0, before))
        hi = min(len(self.windows), window.ordinal + max(0, after) + 1)
        return self.windows[lo:hi]

    def adjacent_window_layers(self, window: PassageWindow) -> Iterator[tuple[PassageWindow, ...]]:
        """Yield the seed passage, then increasingly distant structural layers.

        A layer contains the preceding/following structural passage at the same
        distance where available.  Consumers decide how many layers, segments,
        characters, or model calls their search budget permits.  Verse distance
        is intentionally absent: verse numbers remain reference anchors rather
        than semantic search boundaries.
        """
        yield (window,)
        distance = 1
        while window.ordinal - distance >= 0 or window.ordinal + distance < len(self.windows):
            layer: list[PassageWindow] = []
            before = window.ordinal - distance
            after = window.ordinal + distance
            if before >= 0:
                layer.append(self.windows[before])
            if after < len(self.windows):
                layer.append(self.windows[after])
            if layer:
                yield tuple(layer)
            distance += 1

    @staticmethod
    def segments_for_windows(windows: Iterable[PassageWindow]) -> list[TargetSegment]:
        seen: set[str] = set()
        out: list[TargetSegment] = []
        for window in windows:
            for seg in window.segments:
                if seg.reference not in seen:
                    seen.add(seg.reference)
                    out.append(seg)
        return sorted(out, key=lambda s: s.ordinal)
