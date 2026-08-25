from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shutil
import tempfile
import uuid
import zipfile
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from .tc_project import ProjectError, TranslationCoreProject, _write_json_atomic
from .usfm import whitespace_tokens


SCRIPTURE_EXTENSIONS = {".usfm", ".sfm", ".txt"}
ARCHIVE_EXTENSIONS = {".tcore", ".tstudio", ".zip"}

# USFM identifiers used by the 66-book Protestant canon. Other valid USFM
# identifiers are still accepted; their upper-case id is used as the name.
BOOK_NAMES = {
    "gen": "Genesis", "exo": "Exodus", "lev": "Leviticus", "num": "Numbers",
    "deu": "Deuteronomy", "jos": "Joshua", "jdg": "Judges", "rut": "Ruth",
    "1sa": "1 Samuel", "2sa": "2 Samuel", "1ki": "1 Kings", "2ki": "2 Kings",
    "1ch": "1 Chronicles", "2ch": "2 Chronicles", "ezr": "Ezra", "neh": "Nehemiah",
    "est": "Esther", "job": "Job", "psa": "Psalms", "pro": "Proverbs",
    "ecc": "Ecclesiastes", "sng": "Song of Songs", "isa": "Isaiah",
    "jer": "Jeremiah", "lam": "Lamentations", "ezk": "Ezekiel", "dan": "Daniel",
    "hos": "Hosea", "jol": "Joel", "amo": "Amos", "oba": "Obadiah",
    "jon": "Jonah", "mic": "Micah", "nam": "Nahum", "hab": "Habakkuk",
    "zep": "Zephaniah", "hag": "Haggai", "zec": "Zechariah", "mal": "Malachi",
    "mat": "Matthew", "mrk": "Mark", "luk": "Luke", "jhn": "John", "act": "Acts",
    "rom": "Romans", "1co": "1 Corinthians", "2co": "2 Corinthians",
    "gal": "Galatians", "eph": "Ephesians", "php": "Philippians",
    "col": "Colossians", "1th": "1 Thessalonians", "2th": "2 Thessalonians",
    "1ti": "1 Timothy", "2ti": "2 Timothy", "tit": "Titus", "phm": "Philemon",
    "heb": "Hebrews", "jas": "James", "1pe": "1 Peter", "2pe": "2 Peter",
    "1jn": "1 John", "2jn": "2 John", "3jn": "3 John", "jud": "Jude",
    "rev": "Revelation",
}

_ID_RE = re.compile(r"(?:^|\n)[ \t]*\\id\s+([A-Za-z0-9]{3})\b", re.IGNORECASE)
_ID_LINE_RE = re.compile(r"(?:^|\n)[ \t]*\\id\s+([^\r\n]+)", re.IGNORECASE)
_HEADER_RE = re.compile(r"(?:^|\n)[ \t]*\\(?P<tag>h|toc1|toc2|toc3)\s+(?P<value>[^\r\n]+)", re.IGNORECASE)
_CHAPTER_RE = re.compile(r"(?:^|\n)[ \t]*\\c\s+(?P<number>\S+)", re.IGNORECASE)
_VERSE_RE = re.compile(r"(?:^|\n)[ \t]*\\v\s+(?P<number>\S+)(?:[ \t]+)?", re.IGNORECASE)
_MILESTONE_RE = re.compile(
    r"\\zaln-s\s*\|(?P<attrs>.*?)\\\*(?P<body>.*?)\\zaln-e\\\*",
    re.IGNORECASE | re.DOTALL,
)
_WORD_RE = re.compile(r"\\w\s+(?P<word>[^|\\]+?)(?:\|(?P<attrs>.*?))?\\w\*", re.IGNORECASE | re.DOTALL)
_ALIGNMENT_EVENT_RE = re.compile(
    r"(?P<start>\\zaln-s\s*\|(?P<start_attrs>.*?)\\\*)"
    r"|(?P<end>\\zaln-e\\\*)"
    r"|(?P<word_event>\\w\s+(?P<event_word>[^|\\]+?)(?:\|(?P<word_attrs>.*?))?\\w\*)",
    re.IGNORECASE | re.DOTALL,
)
_ATTR_RE = re.compile(r"(?P<name>[A-Za-z0-9_-]+)\s*=\s*\"(?P<value>[^\"]*)\"")


@dataclass
class ParsedBook:
    source_path: Path
    book_id: str
    book_name: str
    headers: list[dict[str, str]]
    chapters: dict[str, dict[str, str]]
    language_id: str = ""
    language_name: str = ""
    language_direction: str = ""
    has_alignment_markers: bool = False
    alignment_warnings: int = 0

    @property
    def verse_count(self) -> int:
        return sum(len(verses) for verses in self.chapters.values())


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-16", "utf-16-le", "utf-16-be"):
        try:
            text = raw.decode(encoding)
            if "\\" in text:
                return text.replace("\r\n", "\n").replace("\r", "\n")
        except UnicodeError:
            continue
    raise ProjectError(f"{path.name} is not valid UTF-8/UTF-16 Scripture text. Convert it to Unicode before importing.")


def _attrs(value: str) -> dict[str, str]:
    return {m.group("name").lower(): m.group("value") for m in _ATTR_RE.finditer(value or "")}


def _integer(value: Any, default: int = 1) -> int:
    try:
        parsed = int(value)
        return parsed if parsed > 0 else default
    except (TypeError, ValueError):
        return default


def _token(word: str, attrs: dict[str, str], *, bottom: bool) -> dict[str, Any]:
    value: dict[str, Any] = {
        "word": word.strip(),
        "occurrence": _integer(attrs.get("x-occurrence") or attrs.get("occurrence")),
        "occurrences": _integer(attrs.get("x-occurrences") or attrs.get("occurrences")),
    }
    if bottom:
        value["type"] = "bottomWord"
    else:
        for source, target in (("x-strong", "strong"), ("x-lemma", "lemma"), ("x-morph", "morph")):
            if attrs.get(source):
                value[target] = attrs[source]
    return value


def _flatten_alignment_markup(value: str) -> str:
    # Preserve the target words but remove USFM 3 alignment milestones and
    # word attributes. Other inline USFM remains intact for lossless export.
    value = _WORD_RE.sub(lambda m: m.group("word").strip(), value)
    value = re.sub(r"\\zaln-[se]\s*(?:\|.*?)?\\\*", "", value, flags=re.IGNORECASE | re.DOTALL)
    return value.strip()


def _target_word_bank(text: str) -> list[dict[str, Any]]:
    words = whitespace_tokens(text)
    totals = Counter(words)
    seen: Counter[str] = Counter()
    result = []
    for word in words:
        seen[word] += 1
        result.append({
            "word": word,
            "occurrence": seen[word],
            "occurrences": totals[word],
            "type": "bottomWord",
        })
    return result


def _verse_alignment(raw_verse: str) -> tuple[str, dict[str, Any], bool]:
    flattened = _flatten_alignment_markup(raw_verse)
    word_bank = _target_word_bank(flattened)
    groups: list[dict[str, Any]] = []
    used: Counter[tuple[str, int, int]] = Counter()

    starts = len(re.findall(r"\\zaln-s\b", raw_verse, re.IGNORECASE))
    ends = len(re.findall(r"\\zaln-e\\\*", raw_verse, re.IGNORECASE))
    reliable = starts == ends
    stack: list[dict[str, Any]] = []
    top_order: list[tuple[str, int, int]] = []
    top_by_signature: dict[tuple[str, int, int], dict[str, Any]] = {}
    bottom_by_signature: dict[tuple[str, int, int], dict[str, Any]] = {}
    links: dict[tuple[str, int, int], set[tuple[str, int, int]]] = {}

    if reliable and starts:
        for event in _ALIGNMENT_EVENT_RE.finditer(raw_verse):
            if event.group("start"):
                attrs = _attrs(event.group("start_attrs") or "")
                word = attrs.get("x-content", "").strip()
                if not word:
                    reliable = False
                    break
                top = _token(word, attrs, bottom=False)
                signature = (top["word"], top["occurrence"], top["occurrences"])
                if signature not in top_by_signature:
                    top_order.append(signature)
                    top_by_signature[signature] = top
                    links[signature] = set()
                stack.append(top_by_signature[signature])
            elif event.group("end"):
                if not stack:
                    reliable = False
                    break
                stack.pop()
            elif event.group("word_event") and stack:
                bottom = _token(
                    event.group("event_word") or "",
                    _attrs(event.group("word_attrs") or ""),
                    bottom=True,
                )
                bottom_signature = (
                    bottom["word"], bottom["occurrence"], bottom["occurrences"],
                )
                bottom_by_signature[bottom_signature] = bottom
                for top in stack:
                    top_signature = (top["word"], top["occurrence"], top["occurrences"])
                    links[top_signature].add(bottom_signature)
        if stack:
            reliable = False

    if reliable and starts:
        target_order = {
            (token["word"], token["occurrence"], token["occurrences"]): index
            for index, token in enumerate(word_bank)
        }
        grouped_top: dict[tuple[tuple[str, int, int], ...], list[dict[str, Any]]] = {}
        group_order: list[tuple[tuple[str, int, int], ...]] = []
        for top_signature in top_order:
            bottoms = tuple(sorted(
                links[top_signature], key=lambda value: target_order.get(value, 10**9),
            ))
            if bottoms not in grouped_top:
                grouped_top[bottoms] = []
                group_order.append(bottoms)
            grouped_top[bottoms].append(top_by_signature[top_signature])
        for bottom_signatures in group_order:
            bottom_words = [bottom_by_signature[value] for value in bottom_signatures]
            groups.append({
                "topWords": grouped_top[bottom_signatures],
                "bottomWords": bottom_words,
            })
            for bottom in bottom_words:
                used[(bottom["word"], bottom["occurrence"], bottom["occurrences"])] += 1

    if not reliable:
        groups = []
        used.clear()

    remaining = []
    for token in word_bank:
        signature = (token["word"], token["occurrence"], token["occurrences"])
        if used[signature]:
            used[signature] -= 1
        else:
            remaining.append(token)
    return flattened, {"alignments": groups, "wordBank": remaining}, reliable


def _header_value(text: str, tag: str) -> str:
    for match in _HEADER_RE.finditer(text):
        if match.group("tag").lower() == tag:
            return match.group("value").strip()
    return ""


def _book_id_from_filename(path: Path) -> str:
    value = re.sub(r"[^a-z0-9]", "", path.stem.lower())
    candidates = [book_id for book_id in BOOK_NAMES if book_id in value]
    if candidates:
        return max(candidates, key=len)
    match = re.search(r"(?:^|\d)([1-3]?[a-z]{2,3})(?:$|\d)", value)
    return match.group(1) if match else ""


def parse_scripture_file(path: str | Path) -> ParsedBook:
    source = Path(path).resolve()
    text = _read_text(source)
    id_match = _ID_RE.search(text)
    id_line_match = _ID_LINE_RE.search(text)
    book_id = (id_match.group(1).lower() if id_match else _book_id_from_filename(source))
    if not book_id:
        raise ProjectError(f"Could not identify a USFM book id in {source.name}; add a \\id marker.")

    chapter_matches = list(_CHAPTER_RE.finditer(text))
    if not chapter_matches:
        raise ProjectError(f"No \\c chapter marker found in {source.name}.")

    chapters: dict[str, dict[str, str]] = {}
    for index, chapter_match in enumerate(chapter_matches):
        chapter = chapter_match.group("number")
        block_end = chapter_matches[index + 1].start() if index + 1 < len(chapter_matches) else len(text)
        block = text[chapter_match.end():block_end]
        verse_matches = list(_VERSE_RE.finditer(block))
        if not verse_matches:
            continue
        verses: dict[str, str] = {}
        for verse_index, verse_match in enumerate(verse_matches):
            verse = verse_match.group("number")
            verse_end = verse_matches[verse_index + 1].start() if verse_index + 1 < len(verse_matches) else len(block)
            content = block[verse_match.end():verse_end].strip()
            if verse in verses:
                raise ProjectError(f"Duplicate verse {chapter}:{verse} in {source.name}.")
            verses[verse] = content
        chapters[chapter] = verses

    if not any(chapters.values()):
        raise ProjectError(f"No \\v verse markers found in {source.name}.")

    headers = []
    first_chapter = chapter_matches[0].start()
    for line in text[:first_chapter].splitlines():
        marker = re.match(r"\s*\\(?P<tag>[A-Za-z0-9]+)\s*(?P<value>.*)", line)
        if marker:
            headers.append({"tag": marker.group("tag"), "content": marker.group("value").strip()})

    # translationCore's extended \\id convention may contain
    # langcode_LanguageName_ltr ... tc. Read it when present, but never guess.
    language_id = language_name = language_direction = ""
    id_line = id_line_match.group(1) if id_line_match else ""
    lang_match = re.search(r"\b([A-Za-z][A-Za-z0-9-]{1,11})_([^_\s]+)_(ltr|rtl)\b", id_line, re.IGNORECASE)
    if lang_match:
        language_id = lang_match.group(1).lower()
        language_name = lang_match.group(2).replace("⋅", " ")
        language_direction = lang_match.group(3).lower()

    book_name = _header_value(text, "h") or _header_value(text, "toc2") or BOOK_NAMES.get(book_id, book_id.upper())
    return ParsedBook(
        source_path=source,
        book_id=book_id,
        book_name=book_name,
        headers=headers,
        chapters=chapters,
        language_id=language_id,
        language_name=language_name,
        language_direction=language_direction,
        has_alignment_markers="\\zaln-s" in text and "\\w" in text,
    )


def _looks_like_scripture(path: Path) -> bool:
    if path.suffix.lower() not in SCRIPTURE_EXTENSIONS or not path.is_file():
        return False
    try:
        text = _read_text(path)[:65536]
        return bool(re.search(r"\\(?:id|c|v)\s+", text, re.IGNORECASE))
    except (OSError, ProjectError):
        return False


def _scripture_files(source: Path) -> list[Path]:
    if source.is_file():
        return [source] if _looks_like_scripture(source) else []
    files = []
    for path in source.rglob("*"):
        if any(part in {".git", ".apps", "node_modules"} for part in path.parts):
            continue
        if _looks_like_scripture(path):
            files.append(path)
    return sorted(files, key=lambda value: str(value).lower())


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _tc_project_root(source: Path) -> Path | None:
    if source.is_dir() and (source / "manifest.json").is_file():
        return source
    return None


def _archive_manifest(source: Path) -> tuple[str, dict[str, Any]]:
    try:
        with zipfile.ZipFile(source) as archive:
            names = [name for name in archive.namelist() if name.lower().endswith("manifest.json")]
            names.sort(key=lambda name: (name.count("/"), len(name)))
            for name in names:
                try:
                    value = json.loads(archive.read(name).decode("utf-8-sig"))
                except (KeyError, UnicodeError, ValueError):
                    continue
                if isinstance(value, dict) and isinstance(value.get("project"), dict):
                    return name, value
    except (OSError, zipfile.BadZipFile) as exc:
        raise ProjectError(f"Invalid translationCore/translationStudio archive: {source.name}") from exc
    raise ProjectError(f"No project manifest found in {source.name}.")


def _paratext_metadata(source: Path) -> dict[str, str]:
    settings = source / "Settings.xml" if source.is_dir() else source.parent / "Settings.xml"
    if not settings.is_file():
        return {}
    try:
        root = ElementTree.parse(settings).getroot()
    except (OSError, ElementTree.ParseError):
        return {}
    values: dict[str, str] = {}
    for child in root.iter():
        tag = child.tag.rsplit("}", 1)[-1].lower()
        text = (child.text or "").strip()
        if tag in {"name", "fullname", "languageisocode", "lefttoright"} and text:
            values[tag] = text
    return values


def _metadata_from_manifest(manifest: dict[str, Any]) -> dict[str, str]:
    language = manifest.get("target_language") if isinstance(manifest.get("target_language"), dict) else {}
    project = manifest.get("project") if isinstance(manifest.get("project"), dict) else {}
    resource = manifest.get("resource") if isinstance(manifest.get("resource"), dict) else {}
    return {
        "languageId": str(language.get("id") or ""),
        "languageName": str(language.get("name") or ""),
        "languageDirection": str(language.get("direction") or ""),
        "projectName": str(project.get("name") or ""),
        "bibleName": str(resource.get("name") or resource.get("id") or ""),
    }


def inspect_import(source_path: str | Path) -> dict[str, Any]:
    source = Path(source_path).resolve()
    if not source.exists():
        raise ProjectError(f"Import source does not exist: {source}")

    tc_root = _tc_project_root(source)
    if tc_root:
        manifest = _read_json(tc_root / "manifest.json")
        metadata = _metadata_from_manifest(manifest)
        project = manifest.get("project", {})
        return {
            "sourcePath": str(source), "kind": "translationCore", "metadata": metadata,
            "books": [{
                "bookId": str(project.get("id") or "").lower(),
                "bookName": str(project.get("name") or project.get("id") or ""),
                "sourceFile": str(source), "verseCount": None,
                "hasAlignments": (source / ".apps" / "translationCore" / "alignmentData").exists(),
            }],
            "missingFields": [key for key in ("languageId", "languageName", "projectName", "bibleName") if not metadata.get(key)],
            "warnings": [],
        }

    if source.is_file() and source.suffix.lower() in ARCHIVE_EXTENSIONS:
        _, manifest = _archive_manifest(source)
        metadata = _metadata_from_manifest(manifest)
        project = manifest.get("project", {})
        return {
            "sourcePath": str(source), "kind": "translationCoreArchive", "metadata": metadata,
            "books": [{"bookId": str(project.get("id") or "").lower(), "bookName": str(project.get("name") or ""),
                       "sourceFile": str(source), "verseCount": None, "hasAlignments": True}],
            "missingFields": [key for key in ("languageId", "languageName", "projectName", "bibleName") if not metadata.get(key)],
            "warnings": [],
        }

    files = _scripture_files(source)
    if not files:
        raise ProjectError("No USFM/SFM Scripture files were found. Supported extensions are .usfm, .sfm, and marker-based .txt files.")
    books = [parse_scripture_file(path) for path in files]
    duplicate_ids = [book_id for book_id, count in Counter(book.book_id for book in books).items() if count > 1]
    if duplicate_ids:
        raise ProjectError(f"More than one source file identifies the same book: {', '.join(duplicate_ids)}")

    paratext = _paratext_metadata(source if source.is_dir() else source.parent)
    language_ids = {book.language_id for book in books if book.language_id}
    language_names = {book.language_name for book in books if book.language_name}
    language_directions = {book.language_direction for book in books if book.language_direction}
    metadata = {
        "languageId": next(iter(language_ids)) if len(language_ids) == 1 else paratext.get("languageisocode", ""),
        "languageName": next(iter(language_names)) if len(language_names) == 1 else "",
        "languageDirection": next(iter(language_directions)) if len(language_directions) == 1 else ("ltr" if paratext.get("lefttoright", "").lower() == "true" else ""),
        "projectName": paratext.get("name", "") or source.stem,
        "bibleName": paratext.get("fullname", "") or _header_value(_read_text(files[0]), "toc1"),
    }
    warnings = []
    if len(books) > 1:
        warnings.append(f"{len(books)} books will be imported as separate compatible book projects in one collection.")
    if any(book.has_alignment_markers for book in books):
        warnings.append("USFM 3 alignment milestones will be preserved; unsupported nested milestones are left unaligned for review.")
    return {
        "sourcePath": str(source),
        "kind": "paratext" if paratext else ("usfmCollection" if len(books) > 1 else "usfm"),
        "metadata": metadata,
        "books": [{
            "bookId": book.book_id, "bookName": book.book_name, "sourceFile": str(book.source_path),
            "verseCount": book.verse_count, "hasAlignments": book.has_alignment_markers,
        } for book in books],
        "missingFields": [key for key in ("languageId", "languageName", "projectName", "bibleName") if not metadata.get(key)],
        "warnings": warnings,
    }


def _slug(value: str, fallback: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "").strip()).strip("-_.").lower()
    return normalized or fallback


def _available_destination(root: Path, name: str) -> Path:
    candidate = root / name
    number = 2
    while candidate.exists():
        candidate = root / f"{name}-{number}"
        number += 1
    return candidate


def _write_imported_book(project_root: Path, book: ParsedBook, metadata: dict[str, str]) -> None:
    language_id = metadata["languageId"]
    language_name = metadata["languageName"]
    language_direction = metadata.get("languageDirection") or "ltr"
    bible_name = metadata["bibleName"]
    resource_id = _slug(metadata.get("resourceId") or bible_name, "bible")[:24]
    now = datetime.now(timezone.utc).isoformat()
    source_hash = hashlib.sha256(book.source_path.read_bytes()).hexdigest()

    manifest = {
        "generator": {"name": "Bridge", "build": "0.8.0-beta.3"},
        "target_language": {
            "id": language_id, "name": language_name, "direction": language_direction,
            "book": {"name": book.book_name},
        },
        "project": {"id": book.book_id, "name": book.book_name},
        "type": {"id": "text", "name": "Text"},
        "source_translations": [{
            "language_id": "en", "resource_id": "ult", "checking_level": "",
            "date_modified": now, "version": "",
        }],
        "resource": {"id": resource_id, "name": bible_name},
        "translators": [], "checkers": [], "time_created": now, "tools": [], "repo": "",
        "tcInitialized": True, "tc_version": "0.8.0", "tc_edit_version": "0.8.0",
        "bridge_import": {
            "schemaVersion": 1, "sourcePath": str(book.source_path), "sourceSha256": source_hash,
            "sourceFormat": book.source_path.suffix.lower().lstrip("."), "importedAt": now,
            "projectName": metadata["projectName"], "bibleName": bible_name,
            "resourceIndexStatus": "required",
        },
        "bridge_project": {"name": metadata["projectName"], "schemaVersion": 1},
    }
    _write_json_atomic(project_root / "manifest.json", manifest)
    (project_root / f"{book.book_id}.usfm").write_bytes(book.source_path.read_bytes())
    _write_json_atomic(project_root / book.book_id / "headers.json", book.headers)

    alignment_root = project_root / ".apps" / "translationCore" / "alignmentData" / book.book_id
    unreliable = 0
    for chapter, verses in book.chapters.items():
        target_chapter: dict[str, str] = {}
        alignment_chapter: dict[str, dict[str, Any]] = {}
        for verse, raw_text in verses.items():
            target_text, alignment, reliable = _verse_alignment(raw_text)
            target_chapter[verse] = target_text
            alignment_chapter[verse] = alignment
            if book.has_alignment_markers and not reliable:
                unreliable += 1
        _write_json_atomic(project_root / book.book_id / f"{chapter}.json", target_chapter)
        _write_json_atomic(alignment_root / f"{chapter}.json", alignment_chapter)

    # translationCore creates the tN/tW contents later from installed resources.
    # These roots declare compatibility without inventing checks that do not exist.
    for tool in ("translationNotes", "translationWords"):
        (project_root / ".apps" / "translationCore" / "index" / tool / book.book_id).mkdir(parents=True, exist_ok=True)
    for state in ("selections", "invalidated", "comments", "verseEdits"):
        (project_root / ".apps" / "translationCore" / "checkData" / state / book.book_id).mkdir(parents=True, exist_ok=True)
    _write_json_atomic(project_root / ".bridge" / "import.json", {
        "schemaVersion": 1,
        "source": {"path": str(book.source_path), "sha256": source_hash},
        "scripture": {"bookId": book.book_id, "chapters": len(book.chapters), "verses": book.verse_count},
        "alignment": {
            "sourceHadMilestones": book.has_alignment_markers,
            "versesRequiringAlignmentReview": unreliable,
        },
        "capabilities": {
            "translationNotes": "requires-resource-index",
            "translationWords": "requires-resource-index",
            "wordAlignment": "ready" if book.has_alignment_markers and unreliable == 0 else "ready-for-alignment",
            "localQa": "ready",
        },
    })


def _safe_extract(source: Path, destination: Path) -> None:
    try:
        with zipfile.ZipFile(source) as archive:
            root = destination.resolve()
            for member in archive.infolist():
                member_path = (destination / member.filename).resolve()
                try:
                    member_path.relative_to(root)
                except ValueError as exc:
                    raise ProjectError(f"Archive contains an unsafe path: {member.filename}") from exc
            archive.extractall(destination)
    except zipfile.BadZipFile as exc:
        raise ProjectError(f"Invalid translationCore/translationStudio archive: {source.name}") from exc


def _find_extracted_project(root: Path) -> Path:
    manifests = sorted(root.rglob("manifest.json"), key=lambda path: len(path.parts))
    for manifest in manifests:
        value = _read_json(manifest)
        if isinstance(value.get("project"), dict):
            return manifest.parent
    raise ProjectError("The archive does not contain a translationCore/translationStudio project manifest.")


def _ensure_tc_project_compatible(project_root: Path, metadata: dict[str, str]) -> None:
    """Add the normalized data required by Bridge to older tC/tS projects.

    Modern translationCore projects already have alignmentData and pass
    through untouched. Older projects may have target chapter JSON but no
    word-alignment tool state; in that case create an unaligned word bank.
    If only USFM exists, use the same loss-preserving conversion as a raw
    USFM import while retaining the rest of the copied project directory.
    """
    manifest_path = project_root / "manifest.json"
    manifest = _read_json(manifest_path)
    project_data = manifest.get("project") if isinstance(manifest.get("project"), dict) else {}
    book_id = str(project_data.get("id") or "").lower()
    if not book_id:
        raise ProjectError("Imported project manifest has no project.id.")
    alignment_root = project_root / ".apps" / "translationCore" / "alignmentData" / book_id
    if any(alignment_root.glob("*.json")):
        return

    target_root = project_root / book_id
    target_chapters = sorted(path for path in target_root.glob("*.json") if path.stem.isdigit())
    if target_chapters:
        for chapter_path in target_chapters:
            raw = json.loads(chapter_path.read_text(encoding="utf-8-sig"))
            if not isinstance(raw, dict):
                continue
            alignment_chapter = {}
            for verse, verse_text in raw.items():
                flattened, alignment, _ = _verse_alignment(str(verse_text or ""))
                raw[str(verse)] = flattened
                alignment_chapter[str(verse)] = alignment
            _write_json_atomic(chapter_path, raw)
            _write_json_atomic(alignment_root / chapter_path.name, alignment_chapter)
        return

    scripture = _scripture_files(project_root)
    matching = [path for path in scripture if parse_scripture_file(path).book_id == book_id]
    if not matching:
        raise ProjectError(
            "This older translationStudio/translationCore project has neither target chapter JSON "
            "nor a matching USFM/SFM source, so it cannot be normalized safely."
        )
    original_manifest = copy.deepcopy(manifest)
    _write_imported_book(project_root, parse_scripture_file(matching[0]), metadata)
    _write_json_atomic(project_root / ".bridge" / "original-manifest.json", original_manifest)


def apply_resource_materialization(project_root: Path, materialization: dict[str, Any]) -> None:
    """Record real tN/tW capability status and pinned resource versions
    after resource_materializer has (re)built a raw import's check indexes.

    Never called for imported existing translationCore/translationStudio
    projects — those keep their own real indexes untouched, per the
    tN/tW design boundary in docs/IMPORTS.md.
    """
    manifest_path = project_root / "manifest.json"
    manifest = _read_json(manifest_path)
    tn = materialization.get("translationNotes", {}) if isinstance(materialization, dict) else {}
    tw = materialization.get("translationWords", {}) if isinstance(materialization, dict) else {}
    if tn.get("version"):
        manifest["tc_en_check_version_translationNotes"] = tn["version"]
    if tw.get("version"):
        manifest["tc_en_check_version_translationWords"] = tw["version"]
    _write_json_atomic(manifest_path, manifest)

    import_path = project_root / ".bridge" / "import.json"
    data = _read_json(import_path)
    capabilities = data.get("capabilities") if isinstance(data.get("capabilities"), dict) else {}
    capabilities["translationNotes"] = tn.get("status", "requires-resource-index")
    capabilities["translationWords"] = tw.get("status", "requires-resource-index")
    data["capabilities"] = capabilities
    data["resourceMaterialization"] = materialization
    _write_json_atomic(import_path, data)


_LAZY_IMPORT_PATH = Path(".bridge") / "lazy-import.json"
_COLLECTION_PATH = Path(".bridge") / "collection.json"


def _collection_projects(project_root: Path) -> list[dict[str, Any]]:
    """Return a persisted multi-book collection, correcting lazy state from disk.

    Schema 2 stores sibling directory names instead of absolute paths, so a
    collection survives moving its parent directory. Schema 1 absolute paths
    remain readable for projects created by Beta 2 and earlier.
    """
    data = _read_json(project_root / _COLLECTION_PATH)
    projects = data.get("projects") if isinstance(data.get("projects"), list) else []
    result: list[dict[str, Any]] = []
    for value in projects:
        if not isinstance(value, dict):
            continue
        entry = copy.deepcopy(value)
        directory_name = str(entry.get("directoryName") or "")
        if directory_name:
            sibling = (project_root.parent / directory_name).resolve(strict=False)
        elif entry.get("path"):
            sibling = Path(str(entry["path"])).resolve(strict=False)
        else:
            continue
        entry["path"] = str(sibling)
        lazy = (sibling / _LAZY_IMPORT_PATH).is_file()
        entry["lazy"] = lazy
        if not lazy and entry.get("checkIndexStatus") == "deferred":
            entry["checkIndexStatus"] = "requires-resource-index"
        result.append(entry)
    return result


def collection_projects(project_root: str | Path) -> list[dict[str, Any]]:
    """Public reader used by project.open to restore a collection after restart."""
    return _collection_projects(Path(project_root).resolve())


def materialize_lazy_project(project_root: str | Path) -> bool:
    """Normalize a lightweight imported book the first time it is opened.

    Collection import copies every source file into application storage up
    front, so this never depends on the original Paratext/USFM folder still
    existing. The descriptor is removed only after a complete successful
    conversion; an interrupted conversion is therefore safe to retry.
    """
    root = Path(project_root).resolve()
    descriptor_path = root / _LAZY_IMPORT_PATH
    if not descriptor_path.is_file():
        return False
    descriptor = _read_json(descriptor_path)
    source_copy = str(descriptor.get("sourceCopy") or "")
    if not source_copy:
        raise ProjectError(f"Deferred import descriptor is invalid: {descriptor_path}")
    source = (root / source_copy).resolve()
    try:
        source.relative_to(root)
    except ValueError as exc:
        raise ProjectError("Deferred import source points outside its project.") from exc
    if not source.is_file():
        raise ProjectError(f"Deferred Scripture source is missing: {source}")
    metadata = descriptor.get("metadata")
    if not isinstance(metadata, dict):
        raise ProjectError(f"Deferred import metadata is invalid: {descriptor_path}")
    book = parse_scripture_file(source)
    expected = str(descriptor.get("bookId") or "").lower()
    if expected and book.book_id != expected:
        raise ProjectError(
            f"Deferred Scripture source identifies {book.book_id.upper()}, expected {expected.upper()}."
        )
    _write_imported_book(root, book, {str(key): str(value) for key, value in metadata.items()})
    descriptor_path.unlink()
    return True


def import_source(source_path: str | Path, destination_root: str | Path, metadata: dict[str, Any]) -> dict[str, Any]:
    source = Path(source_path).resolve()
    destination = Path(destination_root).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    preview = inspect_import(source)
    combined = copy.deepcopy(preview.get("metadata", {}))
    combined.update({key: str(value).strip() for key, value in metadata.items() if value is not None})
    missing = [key for key in ("languageId", "languageName", "projectName", "bibleName") if not combined.get(key)]
    if missing:
        raise ProjectError(f"Import metadata is incomplete: {', '.join(missing)}")
    if combined.get("languageDirection") not in {"ltr", "rtl"}:
        combined["languageDirection"] = "ltr"

    imported: list[dict[str, Any]] = []
    staging = Path(tempfile.mkdtemp(prefix=".bridge-import-", dir=str(destination)))
    try:
        if preview["kind"] in {"translationCore", "translationCoreArchive"}:
            if preview["kind"] == "translationCoreArchive":
                extracted = staging / "extracted"
                extracted.mkdir()
                _safe_extract(source, extracted)
                project_source = _find_extracted_project(extracted)
            else:
                project_source = source
            manifest = _read_json(project_source / "manifest.json")
            language = manifest.setdefault("target_language", {})
            resource = manifest.setdefault("resource", {})
            language.update({"id": combined["languageId"], "name": combined["languageName"], "direction": combined["languageDirection"]})
            resource.update({"id": resource.get("id") or _slug(combined["bibleName"], "bible")[:24], "name": combined["bibleName"]})
            work = staging / "project"
            shutil.copytree(project_source, work, dirs_exist_ok=True)
            _write_json_atomic(work / "manifest.json", manifest)
            _ensure_tc_project_compatible(work, combined)
            name = _slug(f"{combined['languageId']}_{resource['id']}_{manifest.get('project', {}).get('id', 'project')}", "project")
            final = _available_destination(destination, name)
            os.replace(work, final)
            project = TranslationCoreProject(final)
            imported.append({"path": str(final), "bookId": project.book_id, "bookName": project.summary.book_name})
        else:
            # inspect_import already parsed and validated every source. A
            # whole Bible used to be parsed again and then expanded into
            # tens of thousands of small tC JSON files synchronously here,
            # which took minutes. Fully materialize only the primary book;
            # copy the remaining source files into lightweight, self-contained
            # project placeholders and normalize each one when it is opened.
            preview_books = preview["books"]
            resource_id = _slug(combined.get("resourceId") or combined["bibleName"], "bible")[:24]
            collection_id = str(uuid.uuid4()) if len(preview_books) > 1 else ""
            planned: list[dict[str, Any]] = []
            for index, book_info in enumerate(preview_books):
                book_id = str(book_info["bookId"]).lower()
                name = _slug(f"{combined['languageId']}_{resource_id}_{book_id}", book_id)
                final = _available_destination(destination, name)
                planned.append({
                    "path": str(final), "bookId": book_id,
                    "bookName": str(book_info["bookName"]), "chapters": [],
                    "checkIndexStatus": "deferred" if index else "requires-resource-index",
                    "lazy": index > 0,
                    "projectId": str(uuid.uuid4()),
                    "collectionId": collection_id,
                    "directoryName": final.name,
                })

            collection = {
                "schemaVersion": 2,
                "collectionId": collection_id,
                "sourcePath": str(source),
                "projectName": combined["projectName"],
                "bibleName": combined["bibleName"],
                "projects": [{key: value for key, value in entry.items() if key != "path"} for entry in planned],
            }
            for index, (book_info, entry) in enumerate(zip(preview_books, planned)):
                work = staging / f"book-{index:03d}-{entry['bookId']}"
                work.mkdir(parents=True)
                book_metadata = dict(combined)
                book_metadata["resourceId"] = resource_id
                source_file = Path(str(book_info["sourceFile"]))
                if index == 0:
                    book = parse_scripture_file(source_file)
                    _write_imported_book(work, book, book_metadata)
                    entry["chapters"] = list(book.chapters)
                else:
                    suffix = source_file.suffix.lower() or ".usfm"
                    source_copy = Path(".bridge") / f"source{suffix}"
                    (work / source_copy).parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source_file, work / source_copy)
                    _write_json_atomic(work / _LAZY_IMPORT_PATH, {
                        "schemaVersion": 1,
                        "sourceCopy": source_copy.as_posix(),
                        "originalSourceFile": str(source_file),
                        "bookId": entry["bookId"],
                        "bookName": entry["bookName"],
                        "metadata": book_metadata,
                    })
                _write_json_atomic(work / _COLLECTION_PATH, collection)
                final = Path(entry["path"])
                os.replace(work, final)
                imported.append(entry)
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    if not imported:
        raise ProjectError("The import completed without producing a project.")
    return {
        "sourcePath": str(source), "kind": preview["kind"], "projectName": combined["projectName"],
        "bibleName": combined["bibleName"], "projects": imported, "primaryProjectPath": imported[0]["path"],
    }
