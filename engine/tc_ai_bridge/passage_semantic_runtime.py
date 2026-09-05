"""Stage 4 runtime integration for the passage-semantic companion store.

This module builds structural passages exclusively from current editable
chapter JSON. Preserved imported USFM supplies markers and ordering hints only;
its Scripture wording is never copied into a semantic passage or token stream.
It does not perform semantic matching, QA audits, correction generation, or
translationCore projection.
"""
from __future__ import annotations

from bisect import bisect_left
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import unicodedata
from typing import Any, Iterable
import uuid

import regex

from .original_language_resources import resource_for_book
from .passage_semantic_models import (
    ActorType,
    CharacterSpan,
    EvidenceKind,
    EvidenceRecord,
    LifecycleStatus,
    PassageRecord,
    PassageStructureKind,
    PassageStructureMarker,
    PolicyBinding,
    ResourceValidationStatus,
    ReviewStatus,
    SemanticUnitProvenance,
    TokenInstance,
    TokenKind,
    TokenLayer,
    TokenLineage,
    TokenSide,
)
from .passage_semantic_repository import (
    DATABASE_SCHEMA_VERSION,
    FoundationConflict,
    FoundationRepository,
    FoundationValidationError,
)
from .unicode_coordinates import grapheme_boundaries
from .usfm_passages import PassageWindow, TargetSegment, UsfmPassageIndex
from . import versification
from .source_semantic_inventory import SourceSemanticInventory
from .target_semantic_inventory import TargetSemanticInventory
from .semantic_location import SemanticLocationEngine
from .meaning_analysis import MeaningAnalysisEngine
from .qa_audit import QaAuditEngine
from .correction_eligibility import CorrectionEligibilityService
from .correction_wording import CorrectionWordingService
from .qa_review import QaReviewService


RUNTIME_VERSION = "stage4-runtime-v1"
DEFAULT_TOKENIZER = "bridge-unicode-word-v1"
TC_COMPATIBILITY_TOKENIZER = "tc-whitespace-v1"
NORMALIZATION_PROFILE = "NFC-v1"

_CHAPTER = re.compile(r"^[ \t]*\\c\s+(\S+)", re.IGNORECASE)
_VERSE = re.compile(r"^[ \t]*\\v\s+(\S+)(.*)$", re.IGNORECASE)
_LINE_MARKER = re.compile(r"^[ \t]*\\([A-Za-z0-9]+)\*?\b(.*)$")
_INLINE_MARKER = re.compile(r"\\([A-Za-z0-9]+)\*?")
_BRIDGE = re.compile(r"^(\d+)[-–](\d+)$")
_LETTERED = re.compile(r"^\d+[A-Za-z]+$")

_PARAGRAPH = {"p", "m", "b", "pi", "pi1", "pi2", "mi", "nb", "pc", "pr"}
_POETRY = {"q", "q1", "q2", "q3", "q4", "qr", "qc", "qm", "qm1", "qm2"}
_HEADING = {
    "h", "h1", "h2", "h3", "toc1", "toc2", "toc3",
    "s", "s1", "s2", "s3", "s4", "ms", "ms1", "ms2", "mr", "r", "sr", "qa",
}
_NOTE = {"f", "fe", "ef"}
_XREF = {"x", "ex"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _json_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _sha256_text(payload)


def _read_usfm(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-16", "utf-16-le", "utf-16-be"):
        try:
            value = raw.decode(encoding)
        except UnicodeError:
            continue
        if "\\c" in value and "\\v" in value:
            return value.replace("\r\n", "\n").replace("\r", "\n")
    raise UnicodeError(f"Cannot decode structural USFM: {path}")


def _verse_key(value: str) -> tuple[int, int, str]:
    raw = str(value).replace("–", "-")
    if raw.isdigit():
        return (int(raw), int(raw), "")
    match = _BRIDGE.fullmatch(raw)
    if match:
        return (int(match.group(1)), int(match.group(2)), "")
    match = re.fullmatch(r"(\d+)([A-Za-z]+)", raw)
    if match:
        return (int(match.group(1)), int(match.group(1)), match.group(2).lower())
    return (10**9, 10**9, raw)


def _intersects(left: str, right: str) -> bool:
    l1, l2, _ = _verse_key(left)
    r1, r2, _ = _verse_key(right)
    return l1 != 10**9 and r1 != 10**9 and max(l1, r1) <= min(l2, r2)


def _structure_kind(marker: str) -> PassageStructureKind:
    value = marker.lower()
    if value == "c":
        return PassageStructureKind.CHAPTER
    if value == "v":
        return PassageStructureKind.VERSE
    if value in _PARAGRAPH:
        return PassageStructureKind.PARAGRAPH
    if value in _POETRY:
        return PassageStructureKind.POETRY
    if value in _HEADING:
        return PassageStructureKind.HEADING
    if value in _NOTE:
        return PassageStructureKind.NOTE
    if value in _XREF:
        return PassageStructureKind.CROSS_REFERENCE
    return PassageStructureKind.INLINE_MARKUP


def current_target_text(project: Any) -> dict[str, str]:
    """Return current editable Scripture only, keyed by full displayed ref."""
    book = str(project.book_id).upper()
    result: dict[str, str] = {}
    book_dir = getattr(project, "book_dir", None)
    if book_dir is not None and Path(book_dir).is_dir():
        chapter_paths = sorted(
            (path for path in Path(book_dir).glob("*.json") if path.stem.isdigit()),
            key=lambda path: int(path.stem),
        )
        for path in chapter_paths:
            try:
                chapter_data = json.loads(path.read_text(encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError) as exc:
                raise FoundationValidationError(
                    f"Cannot read authoritative current target chapter: {path}: {exc}"
                ) from exc
            if not isinstance(chapter_data, dict):
                raise FoundationValidationError(
                    f"Authoritative current target chapter is not an object: {path}"
                )
            for verse, text in chapter_data.items():
                if str(verse) != "front":
                    result[f"{book} {path.stem}:{verse}"] = str(text)
        return result
    # Compatibility for project-like test/read adapters without a book_dir.
    for chapter in project.chapters():
        for verse in project.verses(chapter):
            if str(verse) != "front":
                result[f"{book} {chapter}:{verse}"] = str(
                    project.target_verse_text(chapter, verse)
                )
    return result


@dataclass(frozen=True)
class CurrentTextOverlay:
    index: UsfmPassageIndex
    structure_markers: tuple[PassageStructureMarker, ...]
    mismatches: tuple[dict[str, Any], ...]
    structure_hash: str
    structure_resource_id: str


def _authoritative_current_segments(
    book: str, by_chapter: dict[str, dict[str, str]],
) -> dict[str, str]:
    r"""Parsed form of the current chapter JSON, via the same USFM parser.

    Chapter JSON legitimately stores trailing paragraph/section markers inside
    the verse string (``...text\n\p``, ``...text\n\s heading\n\p``) -- real
    imported projects are full of them. The parser correctly hoists those out
    of verse text, so comparing a parsed segment against the raw stored string
    reports perfectly good data as non-authoritative: 39 of 104 segments in a
    real Hindi Philippians failed that way, which blocked scope resolution and
    therefore Stage 9A.4 analysis for the whole book.

    Both sides are parsed identically instead. This is the same construction
    the no-preserved-USFM fallback above already treats as authoritative, so
    the guard still catches what it exists for: any source-USFM Scripture body
    leaking into a verse still parses differently from the current text.
    """
    lines = [f"\\id {book}"]
    for chapter in sorted(by_chapter, key=lambda item: _verse_key(item)[0]):
        lines.append(f"\\c {chapter}")
        for verse in sorted(by_chapter[chapter], key=_verse_key):
            lines.append(f"\\v {verse} {by_chapter[chapter][verse]}")
    index = UsfmPassageIndex.from_text("\n".join(lines) + "\n", book_hint=book)
    return {segment.reference: segment.text for segment in index.segments}


def build_current_text_overlay(project: Any) -> CurrentTextOverlay:
    """Overlay current chapter JSON onto a marker-only imported-USFM skeleton.

    No source-USFM Scripture body is ever appended to ``synthetic``. A mismatch
    records STRUCTURE_TEXT_MISMATCH and current verses are appended safely.
    """
    book = str(project.book_id).upper()
    by_chapter: dict[str, dict[str, str]] = {}
    for reference, text in current_target_text(project).items():
        cv = reference.split(" ", 1)[1]
        chapter, verse = cv.split(":", 1)
        by_chapter.setdefault(chapter, {})[verse] = text

    path = project.usfm_path()
    if path is None or not Path(path).is_file():
        lines = [f"\\id {book}"]
        markers: list[PassageStructureMarker] = []
        order = 0
        for chapter in sorted(by_chapter, key=lambda item: _verse_key(item)[0]):
            lines.append(f"\\c {chapter}")
            markers.append(PassageStructureMarker(
                PassageStructureKind.CHAPTER, "c", f"{book} {chapter}:front",
                None, None, order,
            )); order += 1
            for verse in sorted(by_chapter[chapter], key=_verse_key):
                lines.append(f"\\v {verse} {by_chapter[chapter][verse]}")
                markers.append(PassageStructureMarker(
                    PassageStructureKind.VERSE_BRIDGE if _BRIDGE.fullmatch(verse) else PassageStructureKind.VERSE,
                    "v", f"{book} {chapter}:{verse}", None, None, order,
                )); order += 1
        synthetic = "\n".join(lines) + "\n"
        return CurrentTextOverlay(
            UsfmPassageIndex.from_text(synthetic, book_hint=book), tuple(markers), (),
            _sha256_text("NO_PRESERVED_USFM"), "current-chapter-json-only",
        )

    source_path = Path(path)
    try:
        source = _read_usfm(source_path)
    except (OSError, UnicodeError) as exc:
        # Safe fallback still uses only current text.
        class NoUsfmProject:
            book_id = project.book_id

            @staticmethod
            def chapters() -> list[str]:
                return project.chapters()

            @staticmethod
            def verses(chapter_value: str) -> list[str]:
                return project.verses(chapter_value)

            @staticmethod
            def target_verse_text(chapter_value: str, verse_value: str) -> str:
                return project.target_verse_text(chapter_value, verse_value)

            @staticmethod
            def usfm_path() -> None:
                return None

        fallback = NoUsfmProject()
        overlay = build_current_text_overlay(fallback)
        mismatch = {"code": "STRUCTURE_TEXT_MISMATCH", "detail": str(exc)}
        return CurrentTextOverlay(
            overlay.index, overlay.structure_markers, (mismatch,),
            _sha256_text("UNREADABLE_PRESERVED_USFM"), str(source_path),
        )

    synthetic: list[str] = [f"\\id {book}"]
    markers: list[PassageStructureMarker] = []
    mismatches: list[dict[str, Any]] = []
    seen: dict[str, set[str]] = {chapter: set() for chapter in by_chapter}
    pending_marker_indexes: list[int] = []
    chapter = "0"
    order = 0

    def assign_pending(reference: str) -> None:
        nonlocal markers
        for index in pending_marker_indexes:
            marker = markers[index]
            markers[index] = PassageStructureMarker(
                marker.kind, marker.marker, reference,
                marker.start_code_point, marker.end_code_point, marker.source_order,
            )
        pending_marker_indexes.clear()

    def append_current(verse: str) -> None:
        nonlocal order
        if verse in seen.setdefault(chapter, set()):
            return
        text = by_chapter.get(chapter, {}).get(verse)
        if text is None:
            return
        reference = f"{book} {chapter}:{verse}"
        assign_pending(reference)
        synthetic.append(f"\\v {verse} {text}")
        markers.append(PassageStructureMarker(
            PassageStructureKind.VERSE_BRIDGE if _BRIDGE.fullmatch(verse) else PassageStructureKind.VERSE,
            "v", reference, None, None, order,
        )); order += 1
        seen[chapter].add(verse)

    def flush_unseen(active_chapter: str) -> None:
        for verse in sorted(by_chapter.get(active_chapter, {}), key=_verse_key):
            if verse not in seen.setdefault(active_chapter, set()):
                mismatches.append({
                    "code": "STRUCTURE_TEXT_MISMATCH",
                    "reference": f"{book} {active_chapter}:{verse}",
                    "detail": "Current target verse has no safely matching imported structural anchor.",
                })
                append_current(verse)

    for raw_line in source.split("\n"):
        chapter_match = _CHAPTER.match(raw_line)
        if chapter_match:
            if chapter != "0":
                flush_unseen(chapter)
            chapter = chapter_match.group(1)
            synthetic.append(f"\\c {chapter}")
            markers.append(PassageStructureMarker(
                PassageStructureKind.CHAPTER, "c", f"{book} {chapter}:front",
                None, None, order,
            )); order += 1
            continue
        verse_match = _VERSE.match(raw_line)
        if verse_match:
            structural_verse = verse_match.group(1)
            current_keys = list(by_chapter.get(chapter, {}))
            matches = [key for key in current_keys if key == structural_verse]
            if not matches:
                matches = [
                    key for key in current_keys
                    if key not in seen.setdefault(chapter, set()) and _intersects(key, structural_verse)
                ]
            if not matches:
                mismatches.append({
                    "code": "STRUCTURE_TEXT_MISMATCH",
                    "reference": f"{book} {chapter}:{structural_verse}",
                    "detail": "Imported structural verse has no current editable target text.",
                })
            for current_verse in sorted(matches, key=_verse_key):
                append_current(current_verse)
            if (
                _BRIDGE.fullmatch(structural_verse.replace("–", "-"))
                and matches and structural_verse not in matches
            ):
                markers.append(PassageStructureMarker(
                    PassageStructureKind.VERSE_BRIDGE, "v",
                    f"{book} {chapter}:{matches[0]}", None, None, order,
                )); order += 1
            for inline in _INLINE_MARKER.findall(verse_match.group(2)):
                markers.append(PassageStructureMarker(
                    _structure_kind(inline), inline.lower(),
                    f"{book} {chapter}:{matches[0]}" if matches else None,
                    None, None, order,
                )); order += 1
            continue
        marker_match = _LINE_MARKER.match(raw_line)
        if marker_match:
            marker = marker_match.group(1).lower()
            # Metadata/id text and every marker body are discarded. Only the
            # marker itself survives as structure.
            if marker not in {"id", "ide", "h", "h1", "h2", "h3", "toc1", "toc2", "toc3"}:
                synthetic.append(f"\\{marker}")
            markers.append(PassageStructureMarker(
                _structure_kind(marker), marker, None, None, None, order,
            )); pending_marker_indexes.append(len(markers) - 1); order += 1
            for inline in _INLINE_MARKER.findall(marker_match.group(2)):
                markers.append(PassageStructureMarker(
                    _structure_kind(inline), inline.lower(), None, None, None, order,
                )); pending_marker_indexes.append(len(markers) - 1); order += 1

    if chapter != "0":
        flush_unseen(chapter)
    for remaining in sorted(set(by_chapter) - set(seen), key=lambda item: _verse_key(item)[0]):
        chapter = remaining
        synthetic.append(f"\\c {chapter}")
        markers.append(PassageStructureMarker(
            PassageStructureKind.CHAPTER, "c", f"{book} {chapter}:front",
            None, None, order,
        )); order += 1
        flush_unseen(chapter)

    text = "\n".join(synthetic) + "\n"
    index = UsfmPassageIndex.from_text(text, book_hint=book)
    authoritative = _authoritative_current_segments(book, by_chapter)
    for segment in index.segments:
        if authoritative.get(segment.reference) != segment.text:
            raise FoundationValidationError(
                f"Current-text overlay produced non-authoritative text at {segment.reference}"
            )
    return CurrentTextOverlay(
        index, tuple(markers), tuple(mismatches), hashlib.sha256(source_path.read_bytes()).hexdigest(),
        str(source_path),
    )


def project_current_passage_index(project: Any) -> UsfmPassageIndex:
    return build_current_text_overlay(project).index


def _canonical_reference(
    book: str, chapter: str, verse: str, project_schema: str,
) -> dict[str, Any]:
    displayed = f"{book} {chapter}:{verse}"
    if _LETTERED.fullmatch(verse):
        return {
            "displayedReference": displayed, "projectVersification": project_schema,
            "canonicalReferences": [displayed], "mappingKind": "AMBIGUOUS_SEGMENT",
        }
    bridge = _BRIDGE.fullmatch(verse.replace("–", "-"))
    if bridge:
        refs: list[str] = []
        for number in range(int(bridge.group(1)), int(bridge.group(2)) + 1):
            mapped = _canonical_reference(book, chapter, str(number), project_schema)
            refs.extend(mapped["canonicalReferences"])
        return {
            "displayedReference": displayed, "projectVersification": project_schema,
            "canonicalReferences": list(dict.fromkeys(refs)), "mappingKind": "VERSE_BRIDGE",
        }
    try:
        mapped = versification.to_org_ref(book, chapter, verse, project_schema)
    except Exception:
        return {
            "displayedReference": displayed, "projectVersification": project_schema,
            "canonicalReferences": [displayed], "mappingKind": "SAME",
        }
    kind = str(mapped.get("mapping") or "same").upper()
    raw_refs: list[str]
    if kind == "SPLIT":
        raw_refs = [str(item) for item in mapped.get("splitInto") or []]
    else:
        raw_refs = [str(mapped.get("orgRef") or displayed)]
    mapping_kind = kind if kind in {"SAME", "MAPPED", "MERGE", "SPLIT"} else "MAPPED"
    if mapping_kind == "MAPPED" and any(
        ref.split(" ", 1)[-1].split(":", 1)[0] != str(chapter) for ref in raw_refs if ":" in ref
    ):
        mapping_kind = "CHAPTER_SHIFT"
    if book == "PSA" and str(verse) in {"0", "1"} and mapping_kind != "SAME":
        mapping_kind = "PSALM_TITLE"
    return {
        "displayedReference": displayed, "projectVersification": project_schema,
        "canonicalReferences": raw_refs, "mappingKind": mapping_kind,
    }


def tokenize_target_text(text: str, profile: str = DEFAULT_TOKENIZER) -> list[dict[str, Any]]:
    if profile == TC_COMPATIBILITY_TOKENIZER:
        matches = list(regex.finditer(r"\S+", text))
    elif profile == DEFAULT_TOKENIZER:
        matches = list(regex.finditer(
            r"\p{L}[\p{L}\p{M}\p{N}\p{Pc}\p{Pd}'’]*|\p{N}+|[^\p{Z}\p{C}\p{L}\p{M}\p{N}]",
            text,
        ))
    else:
        raise FoundationValidationError(f"Unknown companion tokenizer profile: {profile}")
    normalized = [unicodedata.normalize("NFC", match.group(0)) for match in matches]
    totals = Counter(normalized)
    seen: Counter[str] = Counter()
    boundaries = grapheme_boundaries(text)
    result: list[dict[str, Any]] = []
    for index, (match, norm) in enumerate(zip(matches, normalized)):
        seen[norm] += 1
        start, end = match.span()
        start_grapheme = bisect_left(boundaries, start)
        end_grapheme = bisect_left(boundaries, end)
        kind = TokenKind.WORD
        if regex.fullmatch(r"[^\p{L}\p{M}\p{N}]+", match.group(0)):
            kind = TokenKind.PUNCTUATION
        result.append({
            "index": index, "raw": match.group(0), "normalized": norm,
            "occurrence": seen[norm], "occurrences": totals[norm], "kind": kind,
            "start": start, "end": end,
            "startGrapheme": start_grapheme, "endGrapheme": end_grapheme,
        })
    return result


class PassageSemanticRuntime:
    def __init__(self, project: Any, project_id: str):
        self.project = project
        self.project_id = project_id
        self.book = str(project.book_id).upper()
        self.path = project.companion_dir() / "passageSemantic" / "bridge-semantic.sqlite3"
        self.repository = FoundationRepository(self.path)
        self.last_error = ""
        self.replayed_invalidations = 0
        self._versification_schema = ""
        self._bind_project()
        self.replayed_invalidations = self.replay_pending_invalidations()
        self.synchronize_current_text()
        self._synchronize_source_lock()
        self.source_semantic = SourceSemanticInventory(self)
        self.target_semantic = TargetSemanticInventory(self)
        self.semantic_location = SemanticLocationEngine(self)
        self.meaning_analysis = MeaningAnalysisEngine(self)
        self.qa_audit = QaAuditEngine(self)
        self.qa_review = QaReviewService(self)
        self.correction_eligibility = CorrectionEligibilityService(self)
        self.correction_wording = CorrectionWordingService(self)
        self._migrate_legacy_companions()

    def _identity_fingerprint(self) -> str:
        manifest = self.project.manifest
        target = manifest.get("target_language") if isinstance(manifest.get("target_language"), dict) else {}
        resource = manifest.get("resource") if isinstance(manifest.get("resource"), dict) else {}
        payload = {
            "projectId": self.project_id, "book": self.book,
            "targetLanguageId": str(target.get("id") or ""),
            "resourceId": str(resource.get("id") or ""),
        }
        return _json_hash(payload)

    def _bind_project(self) -> None:
        manifest = self.project.manifest
        target = manifest.get("target_language") if isinstance(manifest.get("target_language"), dict) else {}
        resource = manifest.get("resource") if isinstance(manifest.get("resource"), dict) else {}
        self.repository.bind_project_metadata(
            project_id=self.project_id, identity_fingerprint=self._identity_fingerprint(),
            book=self.book, target_language_id=str(target.get("id") or ""),
            resource_id=str(resource.get("id") or ""), path=str(self.project.path),
        )

    @staticmethod
    def reference(chapter: str | int, verse: str | int, book: str) -> str:
        return f"{book.upper()} {chapter}:{verse}"

    @staticmethod
    def text_hash(text: str) -> str:
        return _sha256_text(text)

    def text_revision(self, reference: str, text_hash: str) -> str:
        return _sha256_text("\u241f".join((self.project_id, self.book, reference, text_hash, RUNTIME_VERSION)))

    def synchronize_current_text(self) -> dict[str, int]:
        changed = 0
        established = 0
        current_text = current_target_text(self.project)
        for reference, text in current_text.items():
            actual_hash = self.text_hash(text)
            existing = self.repository.current_target_revision(self.project_id, self.book, reference)
            revision = self.text_revision(reference, actual_hash)
            if existing is None:
                self.repository.establish_target_revision(
                    project_id=self.project_id, book=self.book, displayed_reference=reference,
                    text_hash=actual_hash, text_revision=revision,
                )
                established += 1
            elif existing["textHash"] != actual_hash:
                intent = self.repository.prepare_target_invalidation(
                    project_id=self.project_id, book=self.book, displayed_reference=reference,
                    previous_text_hash=existing["textHash"], expected_text_hash=actual_hash,
                )
                self.repository.apply_target_invalidation(
                    intent, actual_text_hash=actual_hash, text_revision=revision,
                )
                changed += 1
        # External project changes can remove a reference without passing
        # through apply_scripture_edit(). Represent deletion as a tombstone
        # revision so its dependents cannot remain current or be served.
        empty_hash = self.text_hash("")
        for existing in self.repository.current_target_revisions(self.project_id, self.book):
            reference = str(existing["displayedReference"])
            if reference in current_text or existing["textHash"] == empty_hash:
                continue
            intent = self.repository.prepare_target_invalidation(
                project_id=self.project_id, book=self.book, displayed_reference=reference,
                previous_text_hash=existing["textHash"], expected_text_hash=empty_hash,
            )
            self.repository.apply_target_invalidation(
                intent, actual_text_hash=empty_hash,
                text_revision=self.text_revision(reference, empty_hash),
            )
            changed += 1
        return {"established": established, "changed": changed}

    def prepare_target_edit(self, chapter: str, verse: str, old_text: str, new_text: str) -> str:
        reference = self.reference(chapter, verse, self.book)
        existing = self.repository.current_target_revision(self.project_id, self.book, reference)
        return self.repository.prepare_target_invalidation(
            project_id=self.project_id, book=self.book, displayed_reference=reference,
            previous_text_hash=str(existing.get("textHash") if existing else self.text_hash(old_text)),
            expected_text_hash=self.text_hash(new_text),
        )

    def complete_target_edit(self, intent_id: str, chapter: str, verse: str) -> dict[str, Any]:
        reference = self.reference(chapter, verse, self.book)
        current = str(self.project.target_verse_text(chapter, verse))
        actual_hash = self.text_hash(current)
        return self.repository.apply_target_invalidation(
            intent_id, actual_text_hash=actual_hash,
            text_revision=self.text_revision(reference, actual_hash),
        )

    def cancel_target_edit(self, intent_id: str, reason: str) -> None:
        self.repository.cancel_target_invalidation(intent_id, reason)

    def replay_pending_invalidations(self) -> int:
        replayed = 0
        current = current_target_text(self.project)
        for intent in self.repository.pending_invalidations(self.project_id):
            reference = str(intent["displayed_reference"])
            text = current.get(reference)
            if text is None:
                empty_hash = self.text_hash("")
                if intent["expected_text_hash"] == empty_hash:
                    self.repository.apply_target_invalidation(
                        intent["id"], actual_text_hash=empty_hash,
                        text_revision=self.text_revision(reference, empty_hash),
                    )
                    replayed += 1
                else:
                    self.repository.cancel_target_invalidation(
                        intent["id"], "Target reference no longer exists",
                    )
                continue
            actual_hash = self.text_hash(text)
            if actual_hash == intent["expected_text_hash"]:
                self.repository.apply_target_invalidation(
                    intent["id"], actual_text_hash=actual_hash,
                    text_revision=self.text_revision(reference, actual_hash),
                )
                replayed += 1
            elif actual_hash == intent["previous_text_hash"]:
                self.repository.cancel_target_invalidation(intent["id"], "Scripture edit was not committed")
            else:
                self.repository.cancel_target_invalidation(intent["id"], "Superseded by a different target edit")
                fresh = self.repository.current_target_revision(self.project_id, self.book, reference)
                new_intent = self.repository.prepare_target_invalidation(
                    project_id=self.project_id, book=self.book, displayed_reference=reference,
                    previous_text_hash=str(fresh.get("textHash") if fresh else intent["previous_text_hash"]),
                    expected_text_hash=actual_hash,
                )
                self.repository.apply_target_invalidation(
                    new_intent, actual_text_hash=actual_hash,
                    text_revision=self.text_revision(reference, actual_hash),
                )
                replayed += 1
        return replayed

    def _project_versification(self) -> str:
        if self._versification_schema:
            return self._versification_schema
        try:
            verses = {
                reference.split(" ", 1)[1]: text
                for reference, text in current_target_text(self.project).items()
            }
            self._versification_schema = str(
                versification.detect_schema(self.book, verses).get("bestSchema") or "org"
            )
        except Exception:
            self._versification_schema = "org"
        return self._versification_schema

    def _synchronize_source_lock(self) -> dict[str, Any]:
        resource = resource_for_book(self.book)
        if resource is not None:
            return self.repository.synchronize_source_lock(
                project_id=self.project_id, book=self.book,
                resource_id=resource.resource_id, resource_version=resource.version,
                resource_hash=resource.provenance_sha256,
            )
        manifest_resource = self.project.manifest.get("bridge_original_language")
        value = manifest_resource if isinstance(manifest_resource, dict) else {}
        if not value:
            return {"available": False, "changed": False, "staled": 0}
        return self.repository.synchronize_source_lock(
            project_id=self.project_id, book=self.book,
            resource_id=str(value.get("resourceId") or "unknown"),
            resource_version=str(value.get("version") or "unknown"),
            resource_hash=str(value.get("provenanceSha256") or value.get("commit") or "unknown"),
        )

    def _segments_for_range(
        self, index: UsfmPassageIndex, chapter: str, verse: str,
        end_chapter: str = "", end_verse: str = "",
    ) -> list[TargetSegment]:
        start = index.segment_for_source_reference(chapter, verse)
        if start is None:
            raise FoundationValidationError(f"Current target reference is unavailable: {self.book} {chapter}:{verse}")
        if end_chapter and end_verse:
            end = index.segment_for_source_reference(end_chapter, end_verse)
            if end is None or end.ordinal < start.ordinal:
                raise FoundationValidationError("Invalid current passage range")
            return index.segments[start.ordinal:end.ordinal + 1]
        window = index.window_for_source_reference(chapter, verse)
        return list(window.segments if window is not None else (start,))

    def rebuild_current_passage(
        self, chapter: str, verse: str, end_chapter: str = "", end_verse: str = "",
        tokenizer_profile: str = DEFAULT_TOKENIZER,
    ) -> dict[str, Any]:
        self.synchronize_current_text()
        overlay = build_current_text_overlay(self.project)
        segments = self._segments_for_range(
            overlay.index, str(chapter), str(verse), str(end_chapter), str(end_verse),
        )
        project_schema = self._project_versification()
        references = [
            _canonical_reference(self.book, segment.chapter, segment.verse, project_schema)
            for segment in segments
        ]
        target_text = {segment.reference: segment.text for segment in segments}
        target_hash = self.repository.target_content_hash(target_text)
        passage_id = "passage-" + _sha256_text("\u241f".join((
            self.project_id, self.book, *target_text.keys(), target_hash, project_schema,
        )))[:32]
        canonical = tuple(dict.fromkeys(
            item for reference in references for item in reference["canonicalReferences"]
        ))
        resource = resource_for_book(self.book)
        source_id = resource.resource_id if resource else "unavailable"
        source_version = resource.version if resource else None
        source_hash = resource.provenance_sha256 if resource else "unavailable"
        selected_refs = set(target_text)
        selected_chapters = {
            reference.split(" ", 1)[1].split(":", 1)[0] for reference in selected_refs
        }
        selected_markers = tuple(marker for marker in overlay.structure_markers if (
            marker.displayed_reference in selected_refs
            or (
                marker.displayed_reference is not None
                and marker.displayed_reference.endswith(":front")
                and marker.displayed_reference.split(" ", 1)[1].split(":", 1)[0]
                in selected_chapters
            )
        ))
        passage = PassageRecord(
            id=passage_id, project_id=self.project_id, book=self.book,
            displayed_source_references=tuple(item["displayedReference"] for item in references),
            displayed_target_references=tuple(target_text), canonical_references=canonical,
            source_resource_id=source_id, source_resource_version=source_version,
            source_resource_hash=source_hash,
            target_revision=_sha256_text("\u241f".join(
                self.repository.current_target_revision(self.project_id, self.book, ref)["textRevision"]
                for ref in target_text
            )),
            target_content_hash=target_hash,
            structure_resource_id=overlay.structure_resource_id,
            structure_resource_version=None, structure_resource_hash=overlay.structure_hash,
            target_text_by_displayed_reference=target_text,
            structure_markers=selected_markers, policy_binding=PolicyBinding.foundation_v1(),
            lifecycle_status=LifecycleStatus.ACTIVE,
        )
        try:
            existing = self.repository.passage_record(passage_id)
        except FoundationValidationError:
            self.repository.save_passage_record(passage)
        else:
            if existing.get("targetContentHash") != target_hash:
                raise FoundationConflict(
                    "Content-addressed passage identity conflicts with stored target content"
                )
        self.repository.save_passage_references(passage_id, references)
        for reference in target_text:
            dependency_id = self.repository.target_dependency_id(self.project_id, self.book, reference)
            self.repository.add_record_dependency(
                "PASSAGE_RECORD", passage_id, "TARGET_REFERENCE", dependency_id,
            )
        self.repository.add_record_dependency(
            "PASSAGE_RECORD", passage_id, "SOURCE_RESOURCE",
            self.repository.source_dependency_id(self.project_id, self.book, source_hash),
        )
        token_ids = self._ensure_target_tokens(passage, references, tokenizer_profile)
        for mismatch in overlay.mismatches:
            self.repository.record_runtime_diagnostic(
                project_id=self.project_id, code="STRUCTURE_TEXT_MISMATCH",
                severity="WARNING", payload=mismatch,
            )
        return {
            **self.repository.passage_record(passage_id),
            "referenceMappings": self.repository.passage_references(passage_id),
            "targetTokenInstanceIds": token_ids,
            "structureStatus": "STRUCTURE_TEXT_MISMATCH" if overlay.mismatches else "CURRENT",
            "structureDiagnostics": list(overlay.mismatches),
            "tokenizerProfile": tokenizer_profile,
        }

    def get_current_passage(
        self, chapter: str, verse: str, end_chapter: str = "", end_verse: str = "",
    ) -> dict[str, Any]:
        # Rebuild is intentionally content-addressed. It validates current target
        # hashes on every read, so an interrupted invalidation cannot serve stale
        # passage content as current.
        return self.rebuild_current_passage(chapter, verse, end_chapter, end_verse)

    def _ensure_target_tokens(
        self, passage: PassageRecord, references: list[dict[str, Any]], profile: str,
    ) -> list[str]:
        reference_map = {item["displayedReference"]: item for item in references}
        result: list[str] = []
        for displayed_reference, text in passage.target_text_by_displayed_reference.items():
            current = self.repository.current_target_revision(
                self.project_id, self.book, displayed_reference,
            )
            if current is None:
                raise FoundationValidationError(f"Missing current revision for {displayed_reference}")
            text_revision = current["textRevision"]
            existing = self.repository.token_instances_for_reference(
                project_id=self.project_id, book=self.book,
                displayed_reference=displayed_reference, text_revision=text_revision,
            )
            if existing:
                result.extend(str(item["id"]) for item in existing)
                continue
            previous = self.repository.token_instances_for_reference(
                project_id=self.project_id, book=self.book,
                displayed_reference=displayed_reference,
            )
            previous = [item for item in previous if item.get("textRevision") != text_revision]
            lineages: list[TokenLineage] = []
            instances: list[TokenInstance] = []
            for token in tokenize_target_text(text, profile):
                identity = "\u241f".join((
                    self.project_id, self.book, displayed_reference, text_revision,
                    profile, str(token["index"]), token["raw"],
                ))
                lineage_id = "target-lineage-" + _sha256_text("lineage\u241f" + identity)[:32]
                instance_id = "target-token-" + _sha256_text("instance\u241f" + identity)[:32]
                span = CharacterSpan(
                    start_code_point=token["start"], end_code_point=token["end"],
                    start_grapheme=token["startGrapheme"], end_grapheme=token["endGrapheme"],
                    quote=token["raw"], quote_sha256=_sha256_text(token["raw"]),
                )
                lineages.append(TokenLineage(
                    id=lineage_id, side=TokenSide.TARGET, project_id=self.project_id,
                    logical_resource_id=self.project_id, book=self.book,
                    canonical_reference_scope=tuple(reference_map[displayed_reference]["canonicalReferences"]),
                    token_layer=TokenLayer.ORTHOGRAPHIC, upstream_identity=None,
                    created_at=_now(), provenance=SemanticUnitProvenance.DETERMINISTIC_RULE,
                ))
                instances.append(TokenInstance(
                    id=instance_id, lineage_id=lineage_id, side=TokenSide.TARGET,
                    project_id=self.project_id, resource_id=self.project_id,
                    resource_version=None, resource_hash=current["textHash"],
                    text_revision=text_revision, book=self.book,
                    displayed_reference=displayed_reference,
                    canonical_references=tuple(reference_map[displayed_reference]["canonicalReferences"]),
                    index=token["index"], occurrence=token["occurrence"],
                    occurrences=token["occurrences"], span=span, raw_form=token["raw"],
                    normalized_form=token["normalized"], normalization_profile=NORMALIZATION_PROFILE,
                    tokenization_version=profile, token_layer=TokenLayer.ORTHOGRAPHIC,
                    token_kind=token["kind"], parent_instance_id=None,
                    instance_fingerprint=_sha256_text(identity),
                ))
                result.append(instance_id)
            created = self.repository.save_target_token_batch(lineages, instances)
            self._suggest_lineage_candidates(previous, created)
        return result

    def _suggest_lineage_candidates(
        self, previous: list[dict[str, Any]], current: list[dict[str, Any]],
    ) -> None:
        old_by_signature: dict[tuple[str, int, int], list[dict[str, Any]]] = {}
        for item in previous:
            key = (
                str(item.get("normalizedForm") or ""), int(item.get("occurrence") or 1),
                int(item.get("occurrences") or 1),
            )
            old_by_signature.setdefault(key, []).append(item)
        for item in current:
            key = (
                str(item.get("normalizedForm") or ""), int(item.get("occurrence") or 1),
                int(item.get("occurrences") or 1),
            )
            matches = old_by_signature.get(key, [])
            if len(matches) != 1:
                continue
            old = matches[0]
            candidate_id = "lineage-candidate-" + _sha256_text(
                f"{old['id']}\u241f{item['id']}\u241fPOSSIBLE_SUCCESSOR"
            )[:32]
            self.repository.save_token_lineage_candidate(
                candidate_id=candidate_id, project_id=self.project_id,
                old_instance_id=str(old["id"]), new_instance_id=str(item["id"]),
                relation="POSSIBLE_SUCCESSOR", confidence=1.0,
                reason_code="EXACT_NORMALIZED_OCCURRENCE_SIGNATURE",
            )

    def _legacy_review_status(self, payload: dict[str, Any]) -> ReviewStatus:
        decisions: list[str] = []
        confirmations = payload.get("humanConfirmations")
        if isinstance(confirmations, dict):
            decisions.extend(str(item.get("decision") or "") for item in confirmations.values() if isinstance(item, dict))
        validation_decisions = payload.get("decisions")
        if isinstance(validation_decisions, dict):
            decisions.extend(
                str(item.get("decision") or item.get("status") or "")
                for item in validation_decisions.values() if isinstance(item, dict)
            )
        if isinstance(payload.get("decision"), str):
            decisions.append(str(payload["decision"]))
        normalized = {item.lower() for item in decisions}
        if normalized & {"corrected", "edited", "human_corrected"}:
            return ReviewStatus.HUMAN_MODIFIED
        if normalized & {"rejected", "human_rejected"}:
            return ReviewStatus.HUMAN_REJECTED
        if normalized & {"confirmed", "human_confirmed", "approved", "human_approved"}:
            return ReviewStatus.HUMAN_APPROVED
        if normalized & {"unsure", "needs_discussion"}:
            return ReviewStatus.NEEDS_DISCUSSION
        return ReviewStatus.AI_PROPOSED

    def _legacy_lifecycle(self, payload: dict[str, Any]) -> LifecycleStatus:
        old_hash = str(payload.get("targetContentHash") or payload.get("target_content_hash") or "")
        old_source_hash = str(
            payload.get("sourceResourceHash") or payload.get("source_resource_hash") or ""
        )
        refs = self._legacy_target_references(payload)
        lock = self.repository.source_lock(self.project_id, self.book)
        source_matches = bool(
            old_source_hash and lock is not None and old_source_hash == lock["resource_hash"]
        )
        current = current_target_text(self.project)
        selected = {reference: current[reference] for reference in sorted(refs) if reference in current}
        if source_matches and old_hash and selected and old_hash == self.repository.target_content_hash(selected):
            return LifecycleStatus.ACTIVE
        return LifecycleStatus.STALE

    @staticmethod
    def _legacy_target_references(payload: dict[str, Any]) -> set[str]:
        refs: set[str] = set()
        result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
        for mapping in result.get("mappings", []) if isinstance(result.get("mappings"), list) else []:
            for span in mapping.get("target_spans", []) if isinstance(mapping, dict) else []:
                if isinstance(span, dict) and span.get("reference"):
                    refs.add(str(span["reference"]))
        return refs

    def _import_legacy_file(self, path: Path, source_schema: str) -> dict[str, Any]:
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        existing = self.repository.migration_run_for(self.project_id, str(path), digest)
        if existing is not None:
            return {"status": "SKIPPED", "path": str(path)}
        started = _now()
        try:
            payload = json.loads(raw.decode("utf-8-sig"))
            if not isinstance(payload, dict):
                raise ValueError("legacy root is not an object")
            review = self._legacy_review_status(payload)
            lifecycle = self._legacy_lifecycle(payload)
            evidence_id = "legacy-evidence-" + digest[:32]
            content = raw.decode("utf-8-sig")
            evidence = EvidenceRecord(
                id=evidence_id, project_id=self.project_id, book=self.book,
                kind=EvidenceKind.AI_RATIONALE, resource_id=source_schema,
                resource_version=str(payload.get("schema") or source_schema), resource_hash=digest,
                occurrence_id=str(path), displayed_references=(), canonical_references=(),
                content=content, content_hash=_sha256_text(content),
                validation_status=ResourceValidationStatus.NOT_CHECKED,
                source_semantic_unit_ids=(), target_semantic_unit_ids=(),
                policy_binding=PolicyBinding.foundation_v1(), review_status=review,
                lifecycle_status=lifecycle,
            )
            self.repository.save_evidence_record(evidence)
            for reference in self._legacy_target_references(payload):
                self.repository.add_record_dependency(
                    "EVIDENCE_RECORD", evidence_id, "TARGET_REFERENCE",
                    self.repository.target_dependency_id(
                        self.project_id, self.book, reference,
                    ),
                )
            legacy_source_hash = str(
                payload.get("sourceResourceHash")
                or payload.get("source_resource_hash") or ""
            )
            if legacy_source_hash:
                self.repository.add_record_dependency(
                    "EVIDENCE_RECORD", evidence_id, "SOURCE_RESOURCE",
                    self.repository.source_dependency_id(
                        self.project_id, self.book, legacy_source_hash,
                    ),
                )
            actor = "migration"
            at = str(payload.get("updatedAt") or payload.get("createdAt") or started)
            audit = payload.get("reviewAudit") if isinstance(payload.get("reviewAudit"), list) else []
            if not audit and isinstance(payload.get("audit"), list):
                audit = payload["audit"]
            if audit:
                latest = audit[-1] if isinstance(audit[-1], dict) else {}
                actor = str(latest.get("reviewer") or actor)
                at = str(latest.get("at") or at)
            self.repository.import_review_record(
                record_id="legacy-review-" + digest[:32], entity_type="EVIDENCE_RECORD",
                entity_id=evidence_id, review_status=review, lifecycle_status=lifecycle,
                actor_type=ActorType.MIGRATION, actor_id=actor,
                note=f"Imported as history from {source_schema}; not promoted to alignment truth.",
                created_at=at,
            )
            validation_decisions = payload.get("decisions")
            if isinstance(validation_decisions, dict):
                for decision_id, decision_payload in validation_decisions.items():
                    if not isinstance(decision_payload, dict):
                        continue
                    decision_value = str(
                        decision_payload.get("decision") or decision_payload.get("status") or ""
                    )
                    decision_review = self._legacy_review_status({"decision": decision_value})
                    decision_actor = str(
                        decision_payload.get("reviewer") or decision_payload.get("actor") or "migration"
                    )
                    decision_at = str(
                        decision_payload.get("at") or decision_payload.get("updatedAt")
                        or decision_payload.get("createdAt") or at
                    )
                    decision_record_id = "legacy-review-" + _sha256_text(
                        f"{digest}\u241f{decision_id}\u241f{decision_value}"
                    )[:32]
                    self.repository.import_review_record(
                        record_id=decision_record_id, entity_type="EVIDENCE_RECORD",
                        entity_id=evidence_id, review_status=decision_review,
                        lifecycle_status=lifecycle, actor_type=ActorType.MIGRATION,
                        actor_id=decision_actor,
                        note=(
                            f"Imported validation decision {decision_id}: {decision_value}; "
                            "historical evidence only."
                        ),
                        created_at=decision_at,
                    )
            report = {"evidenceId": evidence_id, "reviewStatus": review.value, "lifecycleStatus": lifecycle.value}
            self.repository.save_migration_run(
                run_id=str(uuid.uuid4()), project_id=self.project_id,
                source_path=str(path), source_hash=digest, source_schema=source_schema,
                status="IMPORTED", started_at=started, report=report,
            )
            return {"status": "IMPORTED", "path": str(path), **report}
        except Exception as exc:
            self.repository.quarantine_migration_record(
                source_kind=source_schema, source_identity=str(path),
                reason_code="MALFORMED_LEGACY_RECORD",
                payload={
                    "sha256": digest, "error": str(exc),
                    "originalText": raw.decode("utf-8-sig", errors="replace"),
                },
            )
            report = {"error": str(exc), "reason": "MALFORMED_LEGACY_RECORD"}
            self.repository.save_migration_run(
                run_id=str(uuid.uuid4()), project_id=self.project_id,
                source_path=str(path), source_hash=digest, source_schema=source_schema,
                status="QUARANTINED", started_at=started, report=report,
            )
            return {"status": "QUARANTINED", "path": str(path), **report}

    def _migrate_legacy_companions(self) -> None:
        root = self.project.companion_dir()
        sources: list[tuple[Path, str]] = []
        sources.extend((path, "bridge.semantic_mapping.v0.4") for path in (root / "semanticMappings" / self.book.lower()).glob("*.json"))
        validation = root / "semanticValidation" / "irvtam-v0.1.json"
        if validation.is_file():
            sources.append((validation, "bridge.semantic_mapping_validation_audit.v0.1"))
        ai_root = root / "aiReview" / self.book.lower()
        if ai_root.exists():
            sources.extend((path, "bridge.ai_review.legacy") for path in ai_root.rglob("*.json"))
        for path, schema in sources:
            self._import_legacy_file(path, schema)
        self._scan_native_alignment_compatibility()

    @staticmethod
    def _legacy_token_signature(token: Any) -> tuple[str, int, int] | None:
        if not isinstance(token, dict):
            return None
        word = str(token.get("word") or "")
        try:
            occurrence = int(token.get("occurrence"))
            occurrences = int(token.get("occurrences"))
        except (TypeError, ValueError):
            return None
        if not word or occurrence < 1 or occurrences < occurrence:
            return None
        return word, occurrence, occurrences

    def _scan_native_alignment_compatibility(self) -> None:
        """Read-only scan; native tC groups are never imported or repaired here."""
        paths = sorted(self.project.alignment_dir.glob("*.json"))
        digest_builder = hashlib.sha256()
        for path in paths:
            digest_builder.update(path.name.encode("utf-8"))
            digest_builder.update(path.read_bytes())
        digest = digest_builder.hexdigest()
        source_path = str(self.project.alignment_dir)
        if self.repository.migration_run_for(self.project_id, source_path, digest) is not None:
            return
        started = _now()
        report = {
            "filesScanned": len(paths), "groupsScanned": 0, "quarantined": 0,
            "legacyEmptyBottomWords": 0, "duplicateMembership": 0,
            "malformedTokenIdentity": 0, "mutated": False,
        }
        for path in paths:
            try:
                chapter = json.loads(path.read_text(encoding="utf-8-sig"))
            except Exception as exc:
                self.repository.quarantine_migration_record(
                    source_kind="translationCore.alignmentData", source_identity=str(path),
                    reason_code="MALFORMED_LEGACY_ALIGNMENT_FILE",
                    payload={"originalText": path.read_text(encoding="utf-8-sig", errors="replace"), "error": str(exc)},
                )
                report["quarantined"] += 1
                continue
            if not isinstance(chapter, dict):
                continue
            for verse, verse_data in chapter.items():
                groups = verse_data.get("alignments", []) if isinstance(verse_data, dict) else []
                memberships: dict[tuple[str, str, int, int], list[int]] = {}
                for group_index, group in enumerate(groups if isinstance(groups, list) else []):
                    if not isinstance(group, dict):
                        continue
                    report["groupsScanned"] += 1
                    bottom = group.get("bottomWords")
                    if bottom == []:
                        report["legacyEmptyBottomWords"] += 1
                        report["quarantined"] += 1
                        self.repository.quarantine_migration_record(
                            source_kind="translationCore.alignmentData",
                            source_identity=f"{path}#{verse}/alignment/{group_index}",
                            reason_code="LEGACY_EMPTY_BOTTOM_WORDS_AMBIGUOUS",
                            payload={"originalRecord": group},
                        )
                        continue
                    for side, tokens in (
                        ("SOURCE", group.get("topWords")), ("TARGET", bottom),
                    ):
                        if not isinstance(tokens, list):
                            report["malformedTokenIdentity"] += 1
                            report["quarantined"] += 1
                            self.repository.quarantine_migration_record(
                                source_kind="translationCore.alignmentData",
                                source_identity=f"{path}#{verse}/alignment/{group_index}/{side}",
                                reason_code="MALFORMED_LEGACY_TOKEN_IDENTITY",
                                payload={"originalRecord": group},
                            )
                            continue
                        for token in tokens:
                            signature = self._legacy_token_signature(token)
                            if signature is None:
                                report["malformedTokenIdentity"] += 1
                                report["quarantined"] += 1
                                self.repository.quarantine_migration_record(
                                    source_kind="translationCore.alignmentData",
                                    source_identity=f"{path}#{verse}/alignment/{group_index}/{side}",
                                    reason_code="MALFORMED_LEGACY_TOKEN_IDENTITY",
                                    payload={"originalRecord": group},
                                )
                                continue
                            memberships.setdefault((side, *signature), []).append(group_index)
                for signature, group_indexes in memberships.items():
                    if len(set(group_indexes)) <= 1:
                        continue
                    report["duplicateMembership"] += 1
                    report["quarantined"] += 1
                    self.repository.quarantine_migration_record(
                        source_kind="translationCore.alignmentData",
                        source_identity=f"{path}#{verse}/{signature}",
                        reason_code="DUPLICATE_ACTIVE_TOKEN_MEMBERSHIP",
                        payload={
                            "tokenSignature": list(signature), "groupIndexes": group_indexes,
                            "originalVerseRecord": verse_data,
                        },
                    )
        self.repository.save_migration_run(
            run_id=str(uuid.uuid4()), project_id=self.project_id,
            source_path=source_path, source_hash=digest,
            source_schema="translationCore.alignmentData.compatibility-scan.v1",
            status="IMPORTED", started_at=started, report=report,
        )

    def status(self) -> dict[str, Any]:
        recovery = self.repository.recovery_check()
        return {
            "available": True, "readOnly": recovery["readOnly"],
            "databaseSchemaVersion": DATABASE_SCHEMA_VERSION,
            "databasePath": str(self.path), "projectId": self.project_id,
            "book": self.book, "replayedInvalidations": self.replayed_invalidations,
            "recovery": recovery,
        }

    def project_metadata(self) -> dict[str, Any]:
        result = self.repository.project_metadata(self.project_id)
        lock = self.repository.source_lock(self.project_id, self.book)
        result["sourceLock"] = None if lock is None else {
            "projectId": lock["project_id"], "book": lock["book"],
            "resourceId": lock["resource_id"], "resourceVersion": lock["resource_version"],
            "resourceHash": lock["resource_hash"],
            "lifecycleStatus": lock["lifecycle_status"], "revision": lock["revision"],
            "updatedAt": lock["updated_at"],
        }
        return result

    def stale_summary(self) -> dict[str, Any]:
        return self.repository.stale_summary(self.project_id)

    def migration_report(self) -> dict[str, Any]:
        return self.repository.migration_report(self.project_id)

    def build_source_semantic_range(
        self, chapter: str, verse: str, end_chapter: str = "", end_verse: str = "",
    ) -> dict[str, Any]:
        return self.source_semantic.build_range(chapter, verse, end_chapter, end_verse)

    def source_semantic_range(self, inventory_id: str) -> dict[str, Any]:
        return self.source_semantic.get_range(inventory_id)

    def source_semantic_unit(self, unit_id: str) -> dict[str, Any]:
        return self.source_semantic.get_unit(unit_id)

    def source_semantic_coverage_accounts(self, inventory_id: str) -> list[dict[str, Any]]:
        return self.source_semantic.get_coverage_accounts(inventory_id)

    def source_semantic_diagnostics(self, inventory_id: str) -> dict[str, Any]:
        return self.source_semantic.get_diagnostics(inventory_id)

    def build_target_semantic_range(
        self, chapter: str, verse: str, end_chapter: str = "", end_verse: str = "",
    ) -> dict[str, Any]:
        return self.target_semantic.build_range(chapter, verse, end_chapter, end_verse)

    def target_semantic_range(self, inventory_id: str) -> dict[str, Any]:
        return self.target_semantic.get_range(inventory_id)

    def target_semantic_unit(self, unit_id: str) -> dict[str, Any]:
        return self.target_semantic.get_unit(unit_id)

    def target_semantic_diagnostics(self, inventory_id: str) -> dict[str, Any]:
        return self.target_semantic.get_diagnostics(inventory_id)

    def target_semantic_search_spans(self, inventory_id: str) -> list[dict[str, Any]]:
        return self.target_semantic.get_search_spans(inventory_id)

    def target_semantic_capabilities(self, inventory_id: str = "") -> dict[str, Any]:
        return self.target_semantic.get_capabilities(inventory_id)

    def run_semantic_location_range(
        self, chapter: str, verse: str, end_chapter: str = "", end_verse: str = "",
        max_candidate_evaluations: int | None = None,
    ) -> dict[str, Any]:
        return self.semantic_location.run_range(
            chapter, verse, end_chapter, end_verse,
            max_candidate_evaluations=max_candidate_evaluations,
        )

    def semantic_location_status(self, run_id: str) -> dict[str, Any]:
        return self.semantic_location.status(run_id)

    def semantic_location_range(self, run_id: str) -> dict[str, Any]:
        return self.semantic_location.get_range(run_id)

    def semantic_location_relationship(self, relationship_id: str) -> dict[str, Any]:
        return self.semantic_location.get_relationship(relationship_id)

    def semantic_location_candidates(
        self, run_id: str, source_owner_unit_id: str = "",
    ) -> list[dict[str, Any]]:
        return self.semantic_location.get_candidates(run_id, source_owner_unit_id)

    def semantic_location_diagnostics(self, run_id: str) -> dict[str, Any]:
        return self.semantic_location.get_diagnostics(run_id)

    def run_meaning_analysis_range(
        self, chapter: str, verse: str, end_chapter: str = "", end_verse: str = "",
        location_run_id: str = "",
    ) -> dict[str, Any]:
        return self.meaning_analysis.run_range(
            chapter, verse, end_chapter, end_verse, location_run_id=location_run_id,
        )

    def meaning_analysis_status(self, run_id: str) -> dict[str, Any]:
        return self.meaning_analysis.status(run_id)

    def meaning_analysis_range(self, run_id: str) -> dict[str, Any]:
        return self.meaning_analysis.get_range(run_id)

    def meaning_assessment(self, assessment_id: str) -> dict[str, Any]:
        return self.meaning_analysis.get_assessment(assessment_id)

    def meaning_components(self, assessment_id: str) -> list[dict[str, Any]]:
        return self.meaning_analysis.get_components(assessment_id)

    def meaning_analysis_diagnostics(self, run_id: str) -> dict[str, Any]:
        return self.meaning_analysis.get_diagnostics(run_id)

    def run_qa_audit_range(
        self, chapter: str, verse: str, end_chapter: str = "", end_verse: str = "",
        meaning_run_id: str = "",
    ) -> dict[str, Any]:
        return self.qa_audit.run_range(
            chapter, verse, end_chapter, end_verse, meaning_run_id=meaning_run_id,
        )

    def qa_audit_status(self, run_id: str) -> dict[str, Any]:
        return self.qa_audit.status(run_id)

    def qa_audit_range(self, run_id: str) -> dict[str, Any]:
        return self.qa_audit.get_range(run_id)

    def qa_audit_source_coverage(self, run_id: str) -> list[dict[str, Any]]:
        return self.qa_audit.get_source_coverage(run_id)

    def qa_audit_target_support(self, run_id: str) -> list[dict[str, Any]]:
        return self.qa_audit.get_target_support(run_id)

    def qa_audit_finding(self, finding_id: str) -> dict[str, Any]:
        return self.qa_audit.get_finding(finding_id)

    def qa_audit_diagnostics(self, run_id: str) -> dict[str, Any]:
        return self.qa_audit.get_diagnostics(run_id)

    # -- Stage 9A human review (never re-runs analysis) --------------------

    def qa_review_queue(self, **filters: Any) -> dict[str, Any]:
        return self.qa_review.get_queue(**filters)

    def qa_review_finding(self, finding_id: str) -> dict[str, Any]:
        return self.qa_review.get_finding(finding_id)

    def qa_review_decide(self, finding_id: str, disposition: str, **options: Any) -> dict[str, Any]:
        return self.qa_review.decide_finding(finding_id, disposition, **options)

    def qa_review_add_note(self, entity_type: str, entity_id: str, note: str) -> dict[str, Any]:
        return self.qa_review.add_note(entity_type, entity_id, note)

    def correction_get_eligibility(self, finding_id: str) -> dict[str, Any]:
        return self.correction_eligibility.evaluate(finding_id).to_dict()

    def correction_get_proposal(self, proposal_id: str) -> dict[str, Any]:
        return self.repository.correction_proposal(proposal_id)

    def correction_list_for_finding(self, finding_id: str) -> dict[str, Any]:
        return {
            "findingId": finding_id,
            "proposals": self.repository.correction_proposals_for_finding(finding_id),
        }

    def correction_create_proposal(
        self, *, provider: Any = None, **options: Any,
    ) -> dict[str, Any]:
        service = CorrectionWordingService(self, provider) if provider is not None else self.correction_wording
        return service.create_proposal(**options)

    def correction_edit_proposal(self, proposal_id: str, **options: Any) -> dict[str, Any]:
        return self.correction_wording.edit_proposal(proposal_id, **options)

    def correction_reject_proposal(self, proposal_id: str, **options: Any) -> dict[str, Any]:
        return self.correction_wording.reject_proposal(proposal_id, **options)

    def correction_regenerate_proposal(
        self, proposal_id: str, *, provider: Any, **options: Any,
    ) -> dict[str, Any]:
        return CorrectionWordingService(self, provider).regenerate_proposal(
            proposal_id, **options,
        )

    def semantic_review_decide_location(
        self, relationship_id: str, decision: str, **options: Any,
    ) -> dict[str, Any]:
        return self.qa_review.decide_location(relationship_id, decision, **options)

    def semantic_review_decide_meaning(
        self, assessment_id: str, meaning_status: str, **options: Any,
    ) -> dict[str, Any]:
        return self.qa_review.decide_meaning(assessment_id, meaning_status, **options)

    def review_history(self, entity_type: str, entity_id: str) -> dict[str, Any]:
        return self.qa_review.get_entity_history(entity_type, entity_id)
