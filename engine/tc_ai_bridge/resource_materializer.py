from __future__ import annotations

import csv
import os
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .tc_project import _write_json_atomic


_VERSION_RE = re.compile(r'^v?(\d+)(?:\.(\d+))?')
_REF_RE = re.compile(r'^(\d+):(\d+)')

# Resources materialized here are gateway-language (English) checking helps
# applied against any target-language translation, mirroring how real
# translationCore uses tN/tW regardless of the project's own target
# language — so this is not parameterized by project language.
RESOURCE_LANGUAGE = 'en'


def _version_key(name: str) -> tuple[int, int, int, str]:
    """Same ordering as TranslationHelpsKnowledgeBase._version_key: prefer
    higher semantic version, then unfoldingWord as publisher on ties."""
    match = _VERSION_RE.match(name)
    major = int(match.group(1)) if match else -1
    minor = int(match.group(2) or 0) if match else 0
    provider_score = 2 if name.endswith('_unfoldingWord') else 1 if 'Door43-Catalog' in name else 0
    return (major, minor, provider_score, name)


def bundled_resources_source() -> Path:
    """Where the committed/packaged English tN/TWL/TW snapshot lives.

    Checked in this order: BRIDGE_BUNDLED_RESOURCES_DIR (set by main.py
    from a --resources-dir argument Tauri's sidecar spawner passes — see
    src-tauri/src/sidecar.rs), then the PyInstaller --add-data payload
    under sys._MEIPASS, then engine/resources for running from source.
    The env var exists because this ~45MB tree is no longer bundled INTO
    bridge-engine.spec's onefile archive (that made the PyInstaller
    bootloader re-extract all of it on every single launch, a large
    fraction of a ~30-60s cold start); Tauri now ships it separately via
    bundle.resources, installed once rather than re-extracted per launch.
    Either way this is read-only reference content, distinct from the
    app-owned resources root under application storage (see
    ensure_resources_installed).
    """
    override = os.environ.get('BRIDGE_BUNDLED_RESOURCES_DIR')
    if override:
        return Path(override)
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        return Path(sys._MEIPASS) / 'resources'
    return Path(__file__).resolve().parent.parent / 'resources'


def ensure_resources_installed(app_resources_root: Path) -> None:
    """Copy the bundled resource snapshot into application-owned storage.

    TranslationHelpsKnowledgeBase resolves resources relative to a project's
    own path (project.path.parent.parent / 'resources'), i.e. a sibling of
    the app's projects/ folder in application storage — not the repo/bundle
    location. This mirrors how project_root itself is a separate app-owned
    copy rather than something read directly out of the install directory.
    Idempotent and additive: only copies a resource/version folder that
    isn't already installed, never overwrites or deletes one that is.
    """
    source = bundled_resources_source()
    if not source.exists():
        return
    for resource in ('translationNotes', 'translationWordsLinks', 'translationWords', 'translationAcademy'):
        src_resource_dir = source / RESOURCE_LANGUAGE / 'translationHelps' / resource
        if not src_resource_dir.is_dir():
            continue
        dst_resource_dir = app_resources_root / RESOURCE_LANGUAGE / 'translationHelps' / resource
        for version_dir in src_resource_dir.iterdir():
            if not version_dir.is_dir():
                continue
            dst_version_dir = dst_resource_dir / version_dir.name
            if dst_version_dir.exists():
                continue
            shutil.copytree(version_dir, dst_version_dir)

    # Keep the same additive, versioned layout translationCore uses for its
    # original-language Bibles. Bridge's alignment loader reads the immutable
    # bundled copy and verifies its hashes, while this application-owned copy
    # makes licenses/provenance discoverable beside the installed tN/tW data
    # and leaves room for a future explicit resource upgrade workflow.
    for language_id, bible_id in (('hbo', 'uhb'), ('el-x-koine', 'ugnt')):
        src_bible_dir = source / language_id / 'bibles' / bible_id
        if not src_bible_dir.is_dir():
            continue
        dst_bible_dir = app_resources_root / language_id / 'bibles' / bible_id
        for version_dir in src_bible_dir.iterdir():
            if not version_dir.is_dir():
                continue
            dst_version_dir = dst_bible_dir / version_dir.name
            if dst_version_dir.exists():
                continue
            shutil.copytree(version_dir, dst_version_dir)

    # Deliberately NOT mirrored here for the Strong's lexicon: unlike the
    # bible token packs above, lexicon_resources.py always reads straight
    # from the bundled/source location (see its own bundled_resources_root())
    # regardless of what's installed here, so copying it into app storage on
    # every book's first materialization would only add I/O to an already
    # borderline-slow synchronous, single-threaded call path for no
    # functional benefit — it isn't a place worth spending that budget.


def _latest_version_dir(resources_root: Path, resource: str) -> Path | None:
    resource_dir = resources_root / RESOURCE_LANGUAGE / 'translationHelps' / resource
    if not resource_dir.is_dir():
        return None
    candidates = [p for p in resource_dir.iterdir() if p.is_dir()]
    if not candidates:
        return None
    return max(candidates, key=lambda p: _version_key(p.name))


def _parse_tsv(path: Path) -> list[dict[str, str]]:
    with path.open('r', encoding='utf-8-sig', newline='') as handle:
        return list(csv.DictReader(handle, delimiter='\t'))


def _split_reference(reference: str) -> tuple[str, str] | None:
    # TN/TWL also use non-verse references such as "front:intro" or
    # "1:intro" for book/chapter introductions, which don't correspond to
    # any real verse this project can key a check to — skip those rather
    # than guess. Verse bridges (e.g. "3-4") aren't split here; Reference
    # values for individual TSV rows are always single verses upstream.
    match = _REF_RE.match((reference or '').strip())
    if not match:
        return None
    return match.group(1), match.group(2)


def _term_from_twlink(link: str) -> str:
    return (link or '').rstrip('/').rsplit('/', 1)[-1]


_TWL_CATEGORIES = ('kt', 'names', 'other')


def _category_from_twlink(link: str) -> str:
    """TWLink is rc://*/tw/dict/bible/{category}/{term} — category is the
    second-to-last path segment. Falls back to 'other' for a malformed or
    unrecognized category rather than dropping the row, matching this
    resource's own only-three-real-categories shape (confirmed against the
    bundled TSVs, e.g. 'rc://*/tw/dict/bible/names/paul')."""
    parts = (link or '').rstrip('/').split('/')
    category = parts[-2] if len(parts) >= 2 else ''
    return category if category in _TWL_CATEGORIES else 'other'


def _group_from_support_reference(support_reference: str) -> str:
    slug = (support_reference or '').rstrip('/').rsplit('/', 1)[-1]
    return slug or 'other'


def _safe_filename(value: str) -> str:
    return re.sub(r'[^A-Za-z0-9._-]+', '-', value).strip('-') or 'group'


def _write_index_groups(index_dir: Path, groups: dict[str, list[dict[str, Any]]]) -> None:
    # Fully regenerated on every (re-)materialization. Safe to overwrite:
    # Bridge's own human review state (Accept/Reject/Ignore, tied to stable
    # finding ids) lives in the project's separate decisions/ companion
    # directory and is re-applied onto findings after checks run
    # (BridgeEngine.run_verse_checks), not stored inside these index files.
    if index_dir.exists():
        for existing in index_dir.glob('*.json'):
            existing.unlink()
    index_dir.mkdir(parents=True, exist_ok=True)
    for group_id, entries in groups.items():
        _write_json_atomic(index_dir / f'{_safe_filename(group_id)}.json', entries)


@dataclass(frozen=True)
class MaterializeResult:
    tool: str
    version: str
    checks: int
    groups: int


def materialize_translation_notes(project_root: Path, book_id: str, resources_root: Path) -> MaterializeResult | None:
    """Parse the bundled tn_<BOOK>.tsv into real per-verse translationNotes
    check entries. Returns None if no bundled resource/book TSV exists —
    the caller must not report tN as ready in that case."""
    version_dir = _latest_version_dir(resources_root, 'translationNotes')
    if version_dir is None:
        return None
    tsv_path = version_dir / f'tn_{book_id.upper()}.tsv'
    if not tsv_path.is_file():
        return None
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in _parse_tsv(tsv_path):
        parsed = _split_reference(row.get('Reference', ''))
        if not parsed:
            continue
        chapter, verse = parsed
        group_id = _group_from_support_reference(row.get('SupportReference', ''))
        entry = {
            'contextId': {
                'reference': {'bookId': book_id, 'chapter': chapter, 'verse': verse},
                'tool': 'translationNotes',
                'groupId': group_id,
                'checkId': row.get('ID', ''),
                'quoteString': row.get('Quote', ''),
                'occurrence': int(row.get('Occurrence') or 1),
                'occurrenceNote': row.get('Note', ''),
            },
            'selections': False,
            'nothingToSelect': False,
            'invalidated': False,
        }
        groups.setdefault(group_id, []).append(entry)
    index_dir = project_root / '.apps' / 'translationCore' / 'index' / 'translationNotes' / book_id
    _write_index_groups(index_dir, groups)
    return MaterializeResult('translationNotes', version_dir.name, sum(len(v) for v in groups.values()), len(groups))


def materialize_translation_words(project_root: Path, book_id: str, resources_root: Path) -> MaterializeResult | None:
    """Parse the bundled twl_<BOOK>.tsv (translationWordsLinks) into real
    per-verse translationWords check entries, one group per key-term slug."""
    version_dir = _latest_version_dir(resources_root, 'translationWordsLinks')
    if version_dir is None:
        return None
    tsv_path = version_dir / f'twl_{book_id.upper()}.tsv'
    if not tsv_path.is_file():
        return None
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in _parse_tsv(tsv_path):
        parsed = _split_reference(row.get('Reference', ''))
        if not parsed:
            continue
        chapter, verse = parsed
        group_id = _term_from_twlink(row.get('TWLink', ''))
        if not group_id:
            continue
        entry = {
            'contextId': {
                'reference': {'bookId': book_id, 'chapter': chapter, 'verse': verse},
                'tool': 'translationWords',
                'groupId': group_id,
                'checkId': row.get('ID', ''),
                'quoteString': row.get('OrigWords', ''),
                'occurrence': int(row.get('Occurrence') or 1),
                'occurrenceNote': '',
            },
            'selections': False,
            'nothingToSelect': False,
            'invalidated': False,
        }
        groups.setdefault(group_id, []).append(entry)
    index_dir = project_root / '.apps' / 'translationCore' / 'index' / 'translationWords' / book_id
    _write_index_groups(index_dir, groups)
    return MaterializeResult('translationWords', version_dir.name, sum(len(v) for v in groups.values()), len(groups))


def materialize_translation_words_links_index(book_id: str, app_resources_root: Path) -> MaterializeResult | None:
    """Parse the same bundled twl_<BOOK>.tsv into the SEPARATE, resource-level
    grouped-by-term layout TranslationHelpsKnowledgeBase.twl_occurrences()
    actually reads: translationWordsLinks/<version>/{kt,names,other}/groups/
    <book>/<term>.json — a real gap found while investigating Phase 7's
    ai.explain prerequisites (see docs/BUILD_LOG.md): this resource
    was bundled and materialize_translation_words() already parses the exact
    same TSV, but only into the project-level check-index shape
    (.apps/translationCore/index/translationWords/<book>/<group>.json),
    which knowledge_base.py's evidence-gathering never reads. This writes the
    second, resource-level shape from the same source data — not project
    data, so it's shared reference content under app_resources_root, not
    project_root, and (like ensure_resources_installed) is safe to
    regenerate freely since nothing else treats it as mutable state.

    Each entry's shape matches materialize_translation_words()'s own
    contextId shape exactly, since TranslationHelpsKnowledgeBase.twl_occurrences()
    reads x['contextId']['reference']['chapter'/'verse'] and
    x['contextId']['quoteString'] — verified by reading that method directly,
    not assumed from the TSV's own column names.
    """
    version_dir = _latest_version_dir(app_resources_root, 'translationWordsLinks')
    if version_dir is None:
        return None
    tsv_path = version_dir / f'twl_{book_id.upper()}.tsv'
    if not tsv_path.is_file():
        return None
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in _parse_tsv(tsv_path):
        parsed = _split_reference(row.get('Reference', ''))
        if not parsed:
            continue
        chapter, verse = parsed
        link = row.get('TWLink', '')
        term_id = _term_from_twlink(link)
        if not term_id:
            continue
        category = _category_from_twlink(link)
        entry = {
            'contextId': {
                'reference': {'bookId': book_id, 'chapter': chapter, 'verse': verse},
                'tool': 'translationWords',
                'groupId': term_id,
                'checkId': row.get('ID', ''),
                'quoteString': row.get('OrigWords', ''),
                'occurrence': int(row.get('Occurrence') or 1),
                'occurrenceNote': '',
            },
            'selections': False,
            'nothingToSelect': False,
            'invalidated': False,
        }
        groups.setdefault((category, term_id), []).append(entry)
    for category in _TWL_CATEGORIES:
        book_dir = version_dir / category / 'groups' / book_id
        if book_dir.exists():
            for existing in book_dir.glob('*.json'):
                existing.unlink()
    total_checks = 0
    for (category, term_id), entries in groups.items():
        book_dir = version_dir / category / 'groups' / book_id
        book_dir.mkdir(parents=True, exist_ok=True)
        _write_json_atomic(book_dir / f'{_safe_filename(term_id)}.json', entries)
        total_checks += len(entries)
    return MaterializeResult('translationWordsLinksIndex', version_dir.name, total_checks, len(groups))


def materialize_book_checks(project_root: Path, book_id: str, app_resources_root: Path) -> dict[str, Any]:
    """Materialize real translationNotes/translationWords project indexes
    for one imported book from the bundled English resource snapshot.

    Installs the bundled snapshot into application storage first (a no-op
    once already installed). Only covers books the upstream English tN/TWL
    resource has actually released — some Old Testament books are not
    currently published (see docs/BUILD_LOG.md); those come back
    with status "unavailable", the same as any other-language import, never
    a fabricated empty "ready".
    """
    ensure_resources_installed(app_resources_root)
    tn = materialize_translation_notes(project_root, book_id, app_resources_root)
    tw = materialize_translation_words(project_root, book_id, app_resources_root)
    # Resource-level index, not project-level — see that function's own
    # docstring. Parses the exact same TSV materialize_translation_words()
    # just parsed successfully, so this has no meaningfully distinct failure
    # mode from the two calls above it and isn't given special error handling
    # they don't also have.
    materialize_translation_words_links_index(book_id, app_resources_root)
    return {
        'translationNotes': {
            'status': 'ready' if tn and tn.checks else 'unavailable',
            'checks': tn.checks if tn else 0,
            'groups': tn.groups if tn else 0,
            'version': tn.version if tn else '',
        },
        'translationWords': {
            'status': 'ready' if tw and tw.checks else 'unavailable',
            'checks': tw.checks if tw else 0,
            'groups': tw.groups if tw else 0,
            'version': tw.version if tw else '',
        },
    }
