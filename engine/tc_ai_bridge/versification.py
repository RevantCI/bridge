"""
Versification detection, org-normalization, and back-versification.

Wraps the vendored Greek Room versification tool
(engine/vendor/greekroom-versification/, see that directory's NOTICE.md for
provenance, license, and the real bugs found while integrating it). Unlike
the USFM checker, `versification.py` really is an importable library —
BibleStructure, Versification, VersifiedCorpus, VersificationMatch, and
BackVersification are genuine classes with real methods operating on
in-memory dicts, not a monolithic CLI script — so this module imports it
directly into the long-lived bridge-engine process instead of spawning a
subprocess.

CRITICAL: `Versification.load_versifications()` populates CLASS-level state
(`Versification.versification_d`, `Versification.org`) that is never reset.
A second real call in the same process logs a "Duplicate versification
schema" error and returns a half-constructed `Versification` with no
`verse_id_list` — the next line then crashes with AttributeError. Confirmed
by calling it twice against real data (see NOTICE.md). This module therefore
loads exactly once per process, guarded by a lock and a flag. Nothing
outside this module should import the vendored `versification` module or
call `load_versifications()` directly.

Also unlike the USFM checker's file-based CLI (corpus.txt + vref.txt line
pairs), this module builds `VersifiedCorpus.vref2verse` directly from
Bridge's own already-parsed chapter/verse text — never calling
`load_corpus`/`write_corpus`/`main()`. That sidesteps a real Windows
`UnicodeDecodeError` those file-based paths have (see NOTICE.md); it isn't
patched because Bridge's usage never reaches it.

CRITICAL (performance, not just correctness): `detect_schema()`'s scan over
each schema's full `verse_id_list` degrades CATASTROPHICALLY under thread
concurrency, not just proportionally — measured directly at 16 concurrent
callers taking ~47s EACH (a real GIL-contention effect on tight pure-Python
loops), versus ~8s total once serialized. `detect_schema()` therefore holds
`_lock` for its whole scan, the same lock `_ensure_loaded()` uses. See
NOTICE.md finding 4 and test_versification_concurrency.py for the
reproduction and the regression guard.
"""
from __future__ import annotations

import contextlib
import io
import sys
import threading
from pathlib import Path
from typing import Any


def _vendor_root() -> Path:
    """Where the vendored versification.py + data/ tree lives.

    Unlike the USFM checker (a separate helper executable resolved next to
    bridge-engine.exe), this module is imported directly into bridge-engine
    itself — so in a frozen build it must be resolved under sys._MEIPASS,
    the same pattern resource_materializer.bundled_resources_source() uses,
    not a path relative to this source file (which doesn't exist on disk
    inside a PyInstaller onefile bundle). See bridge-engine.spec's `datas`
    entry, which extracts this directory to that exact location.
    """
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "vendor" / "greekroom-versification"
    return Path(__file__).resolve().parent.parent / "vendor" / "greekroom-versification"


VENDOR_ROOT = _vendor_root()
DATA_DIR = VENDOR_ROOT / "data" / "standard_mappings"

# 'org' must stay first: Versification.load_versifications() sets
# Versification.org from whichever schema loads first, and every other
# schema's mapping is built relative to it.
SCHEMAS = ("org", "eng", "rsc", "rso", "vul", "lxx")

_lock = threading.Lock()
_loaded = False
_module = None
_bible = None


class VersificationUnavailable(RuntimeError):
    """The vendored versification tool or its data files are missing."""


def _ensure_loaded() -> None:
    global _loaded, _module, _bible
    if _loaded:
        return
    with _lock:
        if _loaded:
            return
        if not DATA_DIR.is_dir():
            raise VersificationUnavailable(
                f"versification data directory not found: {DATA_DIR}"
            )
        if str(VENDOR_ROOT) not in sys.path:
            sys.path.insert(0, str(VENDOR_ROOT))
        try:
            import versification as vmod  # the vendored module
        except ImportError as exc:
            raise VersificationUnavailable(
                f"vendored versification module could not be imported: {exc}"
            ) from exc

        bible = vmod.BibleStructure()
        log = io.StringIO()
        # VersificationMatch (used later, in detect_schema) writes debug
        # stats straight to sys.stderr unconditionally; load_versifications
        # itself doesn't, but redirect defensively so a future upstream sync
        # can't quietly make bridge-engine's stderr noisy on every load.
        with contextlib.redirect_stderr(io.StringIO()):
            vmod.Versification.load_versifications(bible, log, standard_mapping_dir=str(DATA_DIR))

        _module = vmod
        _bible = bible
        _loaded = True


def is_available() -> bool:
    try:
        _ensure_loaded()
    except VersificationUnavailable:
        return False
    return True


def schema_names() -> dict[str, str]:
    """Human-readable name for each of the six standard schemas."""
    _ensure_loaded()
    return dict(_bible.standard_versification_schemas)


def _book_chapter_verses(verses: dict[str, str], book_upper: str):
    """Build a vref2verse-shaped dict plus chapter verse counts from
    Bridge's own {"chapter:verse": text} map, without touching disk."""
    vref2verse: dict[str, str] = {}
    chapters: dict[tuple[str, str], int] = {}
    books: dict[str, int] = {}
    for ref, text in verses.items():
        if not text:
            continue
        chapter, _, verse = ref.partition(":")
        if not chapter or not verse:
            continue
        verse_id = f"{book_upper} {chapter}:{verse}"
        vref2verse[verse_id] = text
        key = (book_upper, chapter)
        if key not in chapters:
            chapters[key] = 0
            books[book_upper] = books.get(book_upper, 0) + 1
        chapters[key] += 1
    return vref2verse, chapters, books


def detect_schema(book_id: str, verses: dict[str, str]) -> dict[str, Any]:
    """Sniff the best-fitting versification schema for one book's verse text.

    `verses` uses Bridge's own "{chapter}:{verse}" key convention (see
    TranslationCoreProject.verses()/target_verse_text()) mapped to target
    text. Returns the best-fit schema plus every schema's match cost, so a
    caller can show how confident the detection is, not just a bare label.
    """
    _ensure_loaded()
    book_upper = book_id.upper()
    vref2verse, chapters, books = _book_chapter_verses(verses, book_upper)

    vc = _module.VersifiedCorpus(None)
    vc.vref2verse = vref2verse
    vc.chapters = chapters
    vc.books = books

    costs: dict[str, int] = {}
    best_schema: str | None = None
    best_cost: int | None = None
    # Real, measured bug: VersificationMatch.__init__ does a pure-Python scan
    # over each schema's full verse_id_list (tens of thousands of entries for
    # 'eng'/'org'). Under CPython's GIL, running several of these scans on
    # different threads AT ONCE doesn't just add up — it degrades
    # catastrophically (measured: a single-threaded scan for one schema takes
    # ~0.5s; the same scan run on 16 threads concurrently took ~47s PER
    # THREAD, not ~8s as naive linear scaling would suggest). Serializing
    # with the same lock _ensure_loaded() uses turns that into ~8s total for
    # all 16 threads combined, each waiting its turn instead of all thrashing
    # the GIL together. Confirmed by direct measurement, not assumed from
    # general GIL folklore — see test_versification_concurrency.py.
    with _lock, contextlib.redirect_stderr(io.StringIO()):
        for schema in SCHEMAS:
            v = _module.Versification.versification_d.get(schema)
            if v is None:
                continue
            match = _module.VersificationMatch(vc, v, _bible)
            costs[schema] = match.cost
            if best_cost is None or match.cost < best_cost:
                best_cost, best_schema = match.cost, schema

    return {
        "bestSchema": best_schema,
        "bestSchemaName": _bible.standard_versification_schemas.get(best_schema) if best_schema else None,
        "costBySchema": costs,
        "schemaNames": dict(_bible.standard_versification_schemas),
        "verseCount": len(vref2verse),
    }


def to_org_ref(book_id: str, chapter: str, verse: str, schema: str) -> dict[str, Any]:
    """Map one chapter:verse in `schema` to its 'org' (Hebrew/Greek) ref.

    `mapping` distinguishes the real shapes a cross-tradition ref change can
    take: 'same' (identity — not every verse moves), 'mapped' (1:1, e.g. the
    Psalm-3 descriptive-title shift), 'merge' (n source verses collapse to
    one org verse), 'split' (one source verse expands to several org
    verses). translationCore/USFM chapter:verse identity, not a free-text
    label — callers should branch on it rather than parsing orgRef.
    """
    _ensure_loaded()
    v = _module.Versification.versification_d.get(schema)
    if v is None:
        raise VersificationUnavailable(f"Unknown versification schema: {schema!r}")

    book_upper = book_id.upper()
    verse_id = f"{book_upper} {chapter}:{verse}"
    target = v.verse_id_mapping_to_org.get(verse_id)

    if target is None:
        return {"book": book_id, "chapter": str(chapter), "verse": str(verse),
                "orgRef": verse_id, "mapping": "same"}

    if isinstance(target, str):
        org_book, org_chapter, org_verse, _ = _module.Versification.split_verse_id(target)
        return {
            "book": book_id, "chapter": str(chapter), "verse": str(verse),
            "orgRef": target, "orgBook": org_book, "orgChapter": str(org_chapter),
            "orgVerse": str(org_verse), "mapping": "same" if target == verse_id else "mapped",
        }

    if isinstance(target, _module.MergeObject):
        return {
            "book": book_id, "chapter": str(chapter), "verse": str(verse),
            "orgRef": target.target_verse_id, "mapping": "merge",
            "mergedWith": target.source_verse_pprint,
        }

    if isinstance(target, _module.SplitObject):
        return {
            "book": book_id, "chapter": str(chapter), "verse": str(verse),
            "orgRef": target.target_verse_pprint, "mapping": "split",
            "splitInto": list(target.target_verse_ids),
        }

    return {"book": book_id, "chapter": str(chapter), "verse": str(verse),
            "orgRef": verse_id, "mapping": "same"}


def back_versification_map(book_id: str, schema: str) -> dict[str, str]:
    """org ref -> user-schema ref, for every org verse belonging to this book.

    Lets a caller show or export references in the schema a project actually
    uses, even though cross-project statistics/alignment work in 'org'.
    """
    _ensure_loaded()
    v = _module.Versification.versification_d.get(schema)
    if v is None:
        raise VersificationUnavailable(f"Unknown versification schema: {schema!r}")

    book_upper = book_id.upper()
    org_v = _module.Versification.org
    prefix = f"{book_upper} "
    result: dict[str, str] = {}
    for org_ref in org_v.verse_id_list:
        if not org_ref.startswith(prefix):
            continue
        source = v.verse_id_mapping_from_org.get(org_ref)
        if source is None:
            result[org_ref] = org_ref
        elif isinstance(source, str):
            result[org_ref] = source
        elif isinstance(source, _module.MergeObject):
            result[org_ref] = source.source_verse_pprint
        elif isinstance(source, _module.SplitObject):
            result[org_ref] = source.source_verse_id
    return result
