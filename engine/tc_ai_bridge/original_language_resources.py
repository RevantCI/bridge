from __future__ import annotations

import copy
import gzip
import hashlib
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any


TOKEN_PACK_SCHEMA = 'bridge-original-language-token-pack/v1'
RESOURCE_OWNER = 'unfoldingWord'

OT_BOOKS = frozenset({
    'gen', 'exo', 'lev', 'num', 'deu', 'jos', 'jdg', 'rut', '1sa', '2sa',
    '1ki', '2ki', '1ch', '2ch', 'ezr', 'neh', 'est', 'job', 'psa', 'pro',
    'ecc', 'sng', 'isa', 'jer', 'lam', 'ezk', 'dan', 'hos', 'jol', 'amo',
    'oba', 'jon', 'mic', 'nam', 'hab', 'zep', 'hag', 'zec', 'mal',
})
NT_BOOKS = frozenset({
    'mat', 'mrk', 'luk', 'jhn', 'act', 'rom', '1co', '2co', 'gal', 'eph',
    'php', 'col', '1th', '2th', '1ti', '2ti', 'tit', 'phm', 'heb', 'jas',
    '1pe', '2pe', '1jn', '2jn', '3jn', 'jud', 'rev',
})


@dataclass(frozen=True)
class OriginalLanguageResource:
    language_id: str
    resource_id: str
    version: str
    owner: str
    commit: str
    release: str
    provenance_sha256: str
    license_sha256: str
    path: Path

    def to_dict(self, *, include_path: bool = False) -> dict[str, Any]:
        out: dict[str, Any] = {
            'languageId': self.language_id,
            'resourceId': self.resource_id,
            'version': self.version,
            'owner': self.owner,
            'commit': self.commit,
            'release': self.release,
            'license': 'CC BY-SA 4.0',
            'provenanceSha256': self.provenance_sha256,
            'licenseSha256': self.license_sha256,
        }
        if include_path:
            out['path'] = str(self.path)
        return out


_PINNED = {
    'uhb': {
        'language_id': 'hbo',
        'resource_id': 'uhb',
        'version': '3.0.0',
        'owner': RESOURCE_OWNER,
        'commit': '74022f0fed012a3ef169886f595dd98e7b200543',
        'release': 'https://git.door43.org/unfoldingWord/hbo_uhb/releases/tag/v3.0.0',
        'provenance_sha256': 'e9c25908058a4ad0cd4fdfd0aaac67ce3439f86ccae39225aa3c8e84a56be346',
        'license_sha256': '7b2cab3a85b83aa599635f53b62fd9a16f8e46d6ad796e865ad906ed0c751d41',
    },
    'ugnt': {
        'language_id': 'el-x-koine',
        'resource_id': 'ugnt',
        'version': '0.34',
        'owner': RESOURCE_OWNER,
        'commit': 'fc95b2b8aad08bb65ab54628ab685413a1139e97',
        'release': 'https://git.door43.org/unfoldingWord/el-x-koine_ugnt/releases/tag/v0.34',
        'provenance_sha256': '319eaef950cd855aae56a293483223cee6240df03e72e5364ee674e05eee8472',
        'license_sha256': 'c5ddc53db325a35e7b023ba1e24c0da21ad9672b50b043c97eb73bd2a17e882e',
    },
}


class OriginalLanguageResourceError(RuntimeError):
    pass


def bundled_resources_root() -> Path:
    """Return committed resources in source mode or PyInstaller's payload."""
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        return Path(sys._MEIPASS) / 'resources'
    return Path(__file__).resolve().parent.parent / 'resources'


def resource_key_for_book(book_id: str) -> str | None:
    book = str(book_id or '').lower()
    if book in OT_BOOKS:
        return 'uhb'
    if book in NT_BOOKS:
        return 'ugnt'
    return None


def resource_for_book(
    book_id: str, resources_root: str | Path | None = None,
) -> OriginalLanguageResource | None:
    key = resource_key_for_book(book_id)
    if key is None:
        return None
    config = _PINNED[key]
    root = Path(resources_root).resolve() if resources_root else bundled_resources_root()
    path = (
        root / config['language_id'] / 'bibles' / config['resource_id'] /
        f"v{config['version']}_{config['owner']}"
    )
    if not path.is_dir():
        return None
    return OriginalLanguageResource(path=path, **config)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


@lru_cache(maxsize=80)
def _load_pack(path_text: str, expected_artifact_sha256: str) -> dict[str, Any]:
    path = Path(path_text)
    if _sha256(path) != expected_artifact_sha256:
        raise OriginalLanguageResourceError(f'Original-language token pack failed checksum: {path}')
    try:
        with gzip.open(path, 'rt', encoding='utf-8') as handle:
            pack = json.load(handle)
    except (OSError, ValueError) as exc:
        raise OriginalLanguageResourceError(f'Cannot read original-language token pack: {path}') from exc
    if not isinstance(pack, dict) or pack.get('schema') != TOKEN_PACK_SCHEMA:
        raise OriginalLanguageResourceError(f'Unsupported original-language token pack: {path}')
    return pack


@lru_cache(maxsize=4)
def _load_provenance(path_text: str, expected_sha256: str) -> dict[str, Any]:
    path = Path(path_text)
    if _sha256(path) != expected_sha256:
        raise OriginalLanguageResourceError(
            f'Original-language provenance failed checksum: {path}'
        )
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise OriginalLanguageResourceError(f'Cannot read original-language provenance: {path}') from exc
    if not isinstance(value, dict) or not isinstance(value.get('artifacts'), dict):
        raise OriginalLanguageResourceError(f'Invalid original-language provenance: {path}')
    return value


def _validated_pack(resource: OriginalLanguageResource, book_id: str) -> dict[str, Any]:
    book = str(book_id).lower()
    provenance = _load_provenance(
        str(resource.path / 'PROVENANCE.json'), resource.provenance_sha256,
    )
    artifact = provenance['artifacts'].get(book)
    if not isinstance(artifact, dict) or not artifact.get('artifactSha256'):
        raise OriginalLanguageResourceError(
            f'{resource.resource_id.upper()} {resource.version} has no token pack for {book.upper()}'
        )
    pack = _load_pack(
        str(resource.path / str(artifact.get('artifact') or f'{book}.json.gz')),
        str(artifact['artifactSha256']),
    )
    expected = {
        'languageId': resource.language_id,
        'resourceId': resource.resource_id,
        'version': resource.version,
        'owner': resource.owner,
        'sourceCommit': resource.commit,
        'bookId': book,
    }
    mismatches = [key for key, value in expected.items() if pack.get(key) != value]
    if mismatches:
        raise OriginalLanguageResourceError(
            f'Original-language token pack metadata mismatch for {book.upper()}: {", ".join(mismatches)}'
        )
    return pack


def _renumber_occurrences(tokens: list[dict[str, Any]]) -> list[dict[str, Any]]:
    totals = Counter(str(token.get('word') or '') for token in tokens)
    seen: Counter[str] = Counter()
    out: list[dict[str, Any]] = []
    for raw in tokens:
        token = copy.deepcopy(raw)
        word = str(token.get('word') or '')
        seen[word] += 1
        token['occurrence'] = seen[word]
        token['occurrences'] = totals[word]
        out.append(token)
    return out


def source_tokens_for_verse(
    book_id: str,
    chapter: str | int,
    verse: str | int,
    resources_root: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Load translationCore-compatible original-language tokens for a verse.

    Verse bridges are combined in source order and their occurrences are
    recalculated across the combined span, matching wordAlignment's source
    chapter baseline behavior. Segments are not guessed: if the exact source
    reference is unavailable, the caller gets an empty list.
    """
    resource = resource_for_book(book_id, resources_root)
    if resource is None:
        return []
    pack = _validated_pack(resource, book_id)
    chapter_data = pack.get('chapters', {}).get(str(chapter), {})
    if not isinstance(chapter_data, dict):
        return []
    verse_ref = str(verse)
    exact = chapter_data.get(verse_ref)
    if isinstance(exact, list):
        return copy.deepcopy(exact)
    span = re.fullmatch(r'(\d+)-(\d+)', verse_ref)
    if not span:
        return []
    low, high = int(span.group(1)), int(span.group(2))
    if low <= 0 or high < low:
        return []
    combined: list[dict[str, Any]] = []
    for number in range(low, high + 1):
        source = chapter_data.get(str(number))
        if not isinstance(source, list):
            return []
        combined.extend(source)
    return _renumber_occurrences(combined)


def blank_source_alignments(tokens: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {'topWords': [copy.deepcopy(token)], 'bottomWords': []}
        for token in tokens
    ]


def resource_inventory(
    book_id: str, resources_root: str | Path | None = None,
) -> dict[str, Any]:
    resource = resource_for_book(book_id, resources_root)
    if resource is None:
        key = resource_key_for_book(book_id)
        return {
            'available': False,
            'resourceId': key or '',
            'message': 'No bundled original-language resource is available for this book.',
        }
    provenance_path = resource.path / 'PROVENANCE.json'
    license_path = resource.path / 'LICENSE.md'
    if _sha256(provenance_path) != resource.provenance_sha256:
        raise OriginalLanguageResourceError(
            f'Original-language provenance failed checksum: {provenance_path}'
        )
    if _sha256(license_path) != resource.license_sha256:
        raise OriginalLanguageResourceError(
            f'Original-language license failed checksum: {license_path}'
        )
    return {
        'available': True,
        **resource.to_dict(),
        'attribution': (
            f'The original work by unfoldingWord is available from {resource.release}'
        ),
    }
