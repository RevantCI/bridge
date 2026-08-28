"""Protect verse-local tC alignment from cross-verse semantic false links.

translationCore alignment groups are verse-local.  When Stage 3 has verified that
an original-language unit is overtly realized only in another target verse, the
current verse alignment proposal must not invent a local target link just to
achieve coverage.  Bridge retains the richer relationship in companion mapping
metadata while the native tC source group may remain empty/unresolved.
"""
from __future__ import annotations

import unicodedata
from pathlib import Path
from typing import Any

from .semantic_mapping import SemanticSourceRepository
from .semantic_mapping_bridge import default_semantic_source_db_path


def _norm(value: str) -> str:
    return unicodedata.normalize("NFC", str(value or "")).casefold().strip()


def cross_verse_canonical_token_ids(pack: dict[str, Any] | None, current_reference: str) -> set[str]:
    """Canonical source IDs whose overt realization is outside current target ref."""
    out: set[str] = set()
    if not isinstance(pack, dict):
        return out
    for mapping in pack.get("mappings", []):
        if not isinstance(mapping, dict):
            continue
        spans = [s for s in mapping.get("target_spans", []) if isinstance(s, dict)]
        rels = {str(x) for x in mapping.get("relationships", [])}
        if not spans:
            continue  # implicit/grammatical is not the same as cross-verse overt realization
        if all(str(s.get("reference") or "") != current_reference for s in spans) and (
            rels & {"CROSS_VERSE_MOVED", "CROSS_VERSE_REORDERED", "CLAUSE_MOVED", "CLAUSE_REORDERED", "SENTENCE_MOVED", "SENTENCE_REORDERED", "VERSIFICATION_DIFFERENCE"}
        ):
            out.update(str(x) for x in mapping.get("source_token_ids", []) if str(x))
    return out


def alignment_top_ids_for_canonical_tokens(
    source_repo: SemanticSourceRepository, alignment: Any, canonical_token_ids: set[str],
) -> tuple[set[str], set[str]]:
    """Map canonical UHB/UGNT token identities onto the current tC H### inventory.

    Matching is conservative: exact NFC word + occurrence first, then exact
    lemma/Strong's reinforcement.  Ambiguous/unmatched tokens are returned and
    are never guessed by ordinal alone.
    """
    from .alignment_engine import make_inventory
    inv = make_inventory(alignment)
    canonical = source_repo.tokens_by_ids(sorted(canonical_token_ids))
    matched: set[str] = set()
    unresolved: set[str] = set()
    used: set[str] = set()
    for src in canonical:
        candidates: list[tuple[int, str]] = []
        for hid, top in inv.top_ids.items():
            if hid in used:
                continue
            if _norm(top.word) != _norm(src.text) or int(top.occurrence or 1) != int(src.occurrence or 1):
                continue
            score = 10
            if src.lemma and _norm(top.lemma) == _norm(src.lemma):
                score += 3
            if src.strong and _norm(top.strong) == _norm(src.strong):
                score += 3
            if src.morph and _norm(top.morph) == _norm(src.morph):
                score += 1
            candidates.append((score, hid))
        if not candidates:
            unresolved.add(src.id)
            continue
        candidates.sort(reverse=True)
        best_score = candidates[0][0]
        best = [hid for score, hid in candidates if score == best_score]
        if len(best) != 1:
            unresolved.add(src.id)
            continue
        matched.add(best[0]); used.add(best[0])
    return matched, unresolved


def cross_verse_alignment_exclusions(
    *, alignment: Any, semantic_pack: dict[str, Any] | None, current_reference: str,
    source_db_path: str | Path | None = None,
) -> dict[str, Any]:
    canonical = cross_verse_canonical_token_ids(semantic_pack, current_reference)
    if not canonical:
        return {"top_ids": [], "canonical_token_ids": [], "unresolved_canonical_token_ids": []}
    db_path = Path(source_db_path) if source_db_path is not None else default_semantic_source_db_path()
    if not db_path.exists():
        return {
            "top_ids": [], "canonical_token_ids": sorted(canonical),
            "unresolved_canonical_token_ids": sorted(canonical),
            "diagnostic": f"Semantic source DB unavailable for alignment guard: {db_path}",
        }
    repo = SemanticSourceRepository(db_path)
    matched, unresolved = alignment_top_ids_for_canonical_tokens(repo, alignment, canonical)
    return {
        "top_ids": sorted(matched), "canonical_token_ids": sorted(canonical),
        "unresolved_canonical_token_ids": sorted(unresolved),
    }


def guard_alignment_response(raw: dict[str, Any], excluded_top_ids: set[str]) -> dict[str, Any]:
    """Remove model links/implicit claims for source IDs mapped overtly elsewhere."""
    if not excluded_top_ids or not isinstance(raw, dict):
        return raw
    clean = dict(raw)
    links = raw.get("links") if isinstance(raw.get("links"), list) else []
    clean["links"] = [
        dict(link) for link in links
        if isinstance(link, dict) and str(link.get("top_id") or "") not in excluded_top_ids
    ]
    implicit = raw.get("implicit_top_ids") if isinstance(raw.get("implicit_top_ids"), list) else []
    clean["implicit_top_ids"] = [str(x) for x in implicit if str(x) not in excluded_top_ids]
    notes = [str(x) for x in raw.get("review_notes", [])] if isinstance(raw.get("review_notes"), list) else []
    notes.append(
        f"Stage 3 protected {len(excluded_top_ids)} source token(s) from verse-local auto-alignment because their overt target realization is mapped in another verse."
    )
    clean["review_notes"] = notes
    return clean
