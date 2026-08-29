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
import re
from pathlib import Path
from typing import Iterable, Iterator

_VERSE_RE = re.compile(r"^\\v\s+([^\s]+)\s*(.*)$")
_CHAPTER_RE = re.compile(r"^\\c\s+([^\s]+)")
_ID_RE = re.compile(r"^\\id\s+([^\s]+)")
_MARKER_RE = re.compile(r"^\\([A-Za-z0-9]+)\*?\s*(.*)$")
_FOOTNOTE_RE = re.compile(r"\\f\s+.*?\\f\*", re.DOTALL)
_XREF_RE = re.compile(r"\\x\s+.*?\\x\*", re.DOTALL)
_W_RE = re.compile(r"\\w\s+([^|\\]+?)(?:\|[^\\]*?)?\\w\*")
_INLINE_MARKER_RE = re.compile(r"\\[A-Za-z0-9]+\*?(?:\s+)?")
_WS_RE = re.compile(r"\s+")

# Strong boundaries are structural hints. Poetry/list line markers are not
# boundaries by themselves; otherwise poetic passages would degenerate to one
# verse per window in many projects.
_STRONG_BOUNDARY_MARKERS = {
    "p", "m", "b", "s", "s1", "s2", "s3", "s4", "ms", "ms1", "ms2",
    "mr", "r", "sr", "cl", "cd", "qa",
}
_NON_SCRIPTURE_MARKERS = {
    "id", "ide", "h", "h1", "h2", "h3", "toc1", "toc2", "toc3",
    "mt", "mt1", "mt2", "mt3", "mte", "mte1", "mte2", "rem",
    "s", "s1", "s2", "s3", "s4", "ms", "ms1", "ms2", "mr", "r", "sr",
}
_TERMINAL_PUNCT = tuple(".!?…।॥؟。！？")


def strip_usfm_inline(text: str) -> str:
    """Return visible Scripture text while dropping notes/xrefs/USFM markup."""
    value = _FOOTNOTE_RE.sub("", text)
    value = _XREF_RE.sub("", value)
    value = _W_RE.sub(lambda m: m.group(1), value)
    value = _INLINE_MARKER_RE.sub("", value)
    return _WS_RE.sub(" ", value).strip()


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
        return cls.from_text(Path(path).read_text(encoding="utf-8-sig"), book_hint=book_hint)

    @classmethod
    def from_text(cls, text: str, *, book_hint: str = "") -> "UsfmPassageIndex":
        book = book_hint.upper().strip()
        chapter = "0"
        raw_segments: list[dict[str, object]] = []
        current: dict[str, object] | None = None
        pending_boundary = True

        def finish_current() -> None:
            nonlocal current
            if current is None:
                return
            parts = [p for p in current.get("parts", []) if isinstance(p, str) and p.strip()]
            current["text"] = _WS_RE.sub(" ", " ".join(parts)).strip()
            raw_segments.append(current)
            current = None

        for raw_line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            line = raw_line.strip("\ufeff")
            if not line.strip():
                continue
            mid = _ID_RE.match(line)
            if mid:
                if not book:
                    book = mid.group(1).upper()
                continue
            mch = _CHAPTER_RE.match(line)
            if mch:
                finish_current()
                chapter = mch.group(1)
                pending_boundary = True
                continue
            mv = _VERSE_RE.match(line)
            if mv:
                finish_current()
                verse, body = mv.group(1), mv.group(2)
                current = {
                    "chapter": chapter,
                    "verse": verse,
                    "parts": [strip_usfm_inline(body)] if body.strip() else [],
                    "boundary_before": pending_boundary,
                }
                pending_boundary = False
                continue

            mm = _MARKER_RE.match(line)
            if mm:
                marker, body = mm.group(1).lower(), mm.group(2)
                if marker in _STRONG_BOUNDARY_MARKERS:
                    # Boundary affects the *next* verse. Text on a paragraph/poetry
                    # line after a verse marker still belongs to the active verse.
                    pending_boundary = True
                if current is not None and body.strip() and marker not in _NON_SCRIPTURE_MARKERS:
                    visible = strip_usfm_inline(body)
                    if visible:
                        current.setdefault("parts", []).append(visible)
                continue

            if current is not None:
                visible = strip_usfm_inline(line)
                if visible:
                    current.setdefault("parts", []).append(visible)

        finish_current()
        if not book:
            raise ValueError("USFM has no \\id marker and no book_hint was supplied")

        segments: list[TargetSegment] = []
        boundaries: list[bool] = []
        for i, item in enumerate(raw_segments):
            ch = str(item["chapter"])
            verse = str(item["verse"])
            segments.append(TargetSegment(
                reference=f"{book} {ch}:{verse}", book=book, chapter=ch, verse=verse,
                text=str(item.get("text") or ""), ordinal=i,
            ))
            boundaries.append(bool(item.get("boundary_before")))

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
