from __future__ import annotations

import gzip
import hashlib
import json
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any


LEXICON_SCHEMA = 'bridge-strongs-lexicon/v1'
RESOURCE_OWNER = 'Open Scriptures'

# Single-letter Hebrew proclitic codes that appear as compound `strong`
# segments (e.g. strong "b:H7225", "d:H0776") but have no Strong's number of
# their own — they're grammatical prefixes, not lexemes. Not vendored data:
# confirmed by cross-checking real UHB tokens across ~30 verses (Genesis 1-2,
# Psalm 119, Deuteronomy 6) against their paired morph codes (b/k/l/m always
# pair with a preposition morph "R"/"Rd"; c with conjunction "C"; d with
# definite-article particle "Td") — codes not observed in that scan are left
# out rather than guessed.
HEBREW_PREFIX_LABELS = {
    'b': 'Preposition (in/on/with)',
    'k': 'Preposition (like/as)',
    'l': 'Preposition (to/for)',
    'm': 'Preposition (from)',
    'c': 'Conjunction (and)',
    'd': 'Definite article (the)',
}

_PINNED = {
    'hbo': {
        'language_id': 'hbo',
        'resource_id': 'strongs',
        'version': '1.0.2',
        'owner': RESOURCE_OWNER,
        'commit': '0acd2f251c2d35ff8db2dece4e0593979d3ac223',
        'release': 'https://github.com/openscriptures/strongs',
        'provenance_sha256': '1d4de02baccc85154104af7006c58413e5316fc6a4fa662e767152707fa5b998',
    },
    'el-x-koine': {
        'language_id': 'el-x-koine',
        'resource_id': 'strongs',
        'version': '1.0.2',
        'owner': RESOURCE_OWNER,
        'commit': '0acd2f251c2d35ff8db2dece4e0593979d3ac223',
        'release': 'https://github.com/openscriptures/strongs',
        'provenance_sha256': '04d8a239352fc562556bf64dc24c937e94a801d27ebea9ab50a7f22400d1ed4e',
    },
}


class LexiconResourceError(RuntimeError):
    pass


@dataclass(frozen=True)
class LexiconResource:
    language_id: str
    resource_id: str
    version: str
    owner: str
    commit: str
    release: str
    provenance_sha256: str
    path: Path


def bundled_resources_root() -> Path:
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        return Path(sys._MEIPASS) / 'resources'
    return Path(__file__).resolve().parent.parent / 'resources'


def resource_for_language(
    language_id: str, resources_root: str | Path | None = None,
) -> LexiconResource | None:
    config = _PINNED.get(language_id)
    if config is None:
        return None
    root = Path(resources_root).resolve() if resources_root else bundled_resources_root()
    path = (
        root / config['language_id'] / 'lexicons' / config['resource_id'] /
        f"v{config['version']}_openscriptures"
    )
    if not path.is_dir():
        return None
    return LexiconResource(path=path, **config)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


@lru_cache(maxsize=4)
def _load_provenance(path_text: str, expected_sha256: str) -> dict[str, Any]:
    path = Path(path_text)
    if _sha256(path) != expected_sha256:
        raise LexiconResourceError(f"Strong's lexicon provenance failed checksum: {path}")
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise LexiconResourceError(f'Cannot read Strong\'s lexicon provenance: {path}') from exc
    if not isinstance(value, dict) or not isinstance(value.get('artifacts'), dict):
        raise LexiconResourceError(f'Invalid Strong\'s lexicon provenance: {path}')
    return value


@lru_cache(maxsize=4)
def _load_index(path_text: str, expected_artifact_sha256: str) -> dict[str, Any]:
    path = Path(path_text)
    if _sha256(path) != expected_artifact_sha256:
        raise LexiconResourceError(f'Strong\'s lexicon artifact failed checksum: {path}')
    try:
        with gzip.open(path, 'rt', encoding='utf-8') as handle:
            pack = json.load(handle)
    except (OSError, ValueError) as exc:
        raise LexiconResourceError(f'Cannot read Strong\'s lexicon artifact: {path}') from exc
    if not isinstance(pack, dict) or pack.get('schema') != LEXICON_SCHEMA:
        raise LexiconResourceError(f'Unsupported Strong\'s lexicon artifact: {path}')
    return pack


def _entries_for_language(
    language_id: str, resources_root: str | Path | None = None,
) -> dict[str, Any] | None:
    resource = resource_for_language(language_id, resources_root)
    if resource is None:
        return None
    provenance = _load_provenance(
        str(resource.path / 'PROVENANCE.json'), resource.provenance_sha256,
    )
    artifact = provenance['artifacts'].get('entries')
    if not isinstance(artifact, dict) or not artifact.get('artifactSha256'):
        raise LexiconResourceError(f'Strong\'s lexicon {language_id} has no entries artifact')
    pack = _load_index(
        str(resource.path / str(artifact.get('artifact') or 'entries.json.gz')),
        str(artifact['artifactSha256']),
    )
    return pack.get('entries') or {}


def lexicon_entry_for_strong(
    strong: str, language_id: str, resources_root: str | Path | None = None,
) -> dict[str, Any] | None:
    """Look up one Strong's-numbered lexicon entry, or None if unresolved.

    `strong` is a single (non-compound) Strong's number as stored on a
    source token, e.g. "H776" or "G23160" — callers with a compound value
    (e.g. "b:H7225") should split on ":" and look up each part themselves.
    """
    entries = _entries_for_language(language_id, resources_root)
    if not entries:
        return None
    normalized = _normalize_strong(strong, language_id)
    if normalized is None:
        return None
    return entries.get(normalized)


def _normalize_strong(strong: str, language_id: str) -> str | None:
    """Map a token's raw strong value onto the classic Strong's dictionary key.

    Confirmed against real vendored data (not guessed): UHB numbers are
    inconsistently zero-padded ("H0430" vs "H7225") and occasionally carry a
    trailing homonym-disambiguation letter OSHB adds beyond classic Strong's
    ("H1254a") — both stripped here. UGNT numbers always carry one extra
    trailing "variant" digit beyond the 4-digit base ("G23160" -> base 2316)
    that classic Strong's numbering doesn't have.
    """
    text = str(strong or '').strip().upper()
    if len(text) < 2 or text[0] not in ('H', 'G'):
        return None
    digits = text[1:]
    if language_id == 'el-x-koine':
        if len(digits) < 2 or not digits.isdigit():
            return None
        digits = digits[:-1]
    else:
        digits = digits.rstrip('ABCDEFGHIJKLMNOPQRSTUVWXYZ')
        if not digits.isdigit():
            return None
    digits = digits.lstrip('0') or '0'
    return f'{text[0]}{digits}'
