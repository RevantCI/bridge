"""Bridge integration helpers for Stage 3 semantic passage mapping.

This module is deliberately target-language neutral.  It never writes target
USFM and never forces a cross-verse semantic relationship into translationCore's
verse-local checkData.  Rich mappings live under Bridge's companion directory.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys
from typing import Any, Sequence

from .semantic_mapping import (
    SemanticMappingEngine, SemanticMappingError, SemanticMappingStore,
    SemanticSourceRepository, SourceSemanticUnit, mapping_state_for_review,
)
from .usfm_passages import UsfmPassageIndex

_SOURCE_DB_NAME = "bridge_semantic_source_v0.3.sqlite"


def default_semantic_source_db_path() -> Path:
    """Resolve the bundled semantic source DB in dev and frozen sidecar builds.

    Same resolution order as resource_materializer.bundled_resources_source()
    / original_language_resources.bundled_resources_root(): this ~125MB tree
    is not bundled into bridge-engine.spec's onefile archive (the PyInstaller
    bootloader would re-extract it on every launch), so Tauri ships
    engine/resources separately via bundle.resources and passes its install
    location to the sidecar as `--resources-dir`, which main.py turns into
    BRIDGE_BUNDLED_RESOURCES_DIR — see src-tauri/src/sidecar.rs. That must be
    checked before sys._MEIPASS, which no longer holds this tree.
    """
    override = os.environ.get("BRIDGE_SEMANTIC_SOURCE_DB", "").strip()
    if override:
        return Path(override)
    candidates: list[Path] = []
    bundled = os.environ.get("BRIDGE_BUNDLED_RESOURCES_DIR", "").strip()
    if bundled:
        candidates.append(Path(bundled) / "semantic_mapping" / _SOURCE_DB_NAME)
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "resources" / "semantic_mapping" / _SOURCE_DB_NAME)
    # tc_ai_bridge/semantic_mapping_bridge.py -> engine/
    candidates.append(Path(__file__).resolve().parent.parent / "resources" / "semantic_mapping" / _SOURCE_DB_NAME)
    candidates.append(Path.cwd() / "engine" / "resources" / "semantic_mapping" / _SOURCE_DB_NAME)
    candidates.append(Path.cwd() / "resources" / "semantic_mapping" / _SOURCE_DB_NAME)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    # Return canonical dev path so callers get a useful diagnostic.
    return candidates[0] if candidates else Path("resources/semantic_mapping") / _SOURCE_DB_NAME


def project_passage_index(project: Any) -> UsfmPassageIndex:
    path = project.usfm_path()
    if path is not None and Path(path).exists():
        return UsfmPassageIndex.from_path(path, book_hint=str(project.book_id).upper())

    # Raw translationCore projects can have no USFM after import. Build a minimal
    # synthetic USFM from canonical target chapter JSON. This loses paragraph
    # boundaries but remains safe because windows are retrieval hints only and
    # adaptive expansion never treats a search boundary as an omission verdict.
    lines = [f"\\id {str(project.book_id).upper()}"]
    for chapter in project.chapters():
        lines.append(f"\\c {chapter}")
        for verse in project.verses(chapter):
            if verse == "front":
                continue
            lines.append(f"\\v {verse} {project.target_verse_text(chapter, verse)}")
    return UsfmPassageIndex.from_text("\n".join(lines), book_hint=str(project.book_id).upper())


def _context_for_check(c: dict[str, Any]) -> dict[str, Any]:
    return c.get("contextId", {}) if isinstance(c, dict) and isinstance(c.get("contextId"), dict) else {}


def _numeric_verses(verse: str) -> list[str]:
    raw = str(verse or "").strip().replace("–", "-")
    if raw.isdigit():
        return [raw]
    if "-" in raw:
        a, b = raw.split("-", 1)
        if a.isdigit() and b.isdigit() and int(a) <= int(b):
            return [str(n) for n in range(int(a), int(b) + 1)]
    return [raw] if raw else []


def checks_for_seed_passage(project: Any, target_index: UsfmPassageIndex, chapter: str, verse: str) -> list[dict[str, Any]]:
    """Collect native tN/tW checks for the initial structural passage once.

    This is the main Stage 3 cost optimization: every source check in one target
    passage is mapped in a single Structured-Output request and then reused from
    the content fingerprint cache when the reviewer opens another verse in that
    same passage.  Verse ranges are expanded to their canonical numeric anchors.
    """
    window = target_index.window_for_source_reference(chapter, verse)
    if window is None:
        return list(project.checks_for_verse(chapter, verse))
    requested: list[tuple[str, str]] = []
    for seg in window.segments:
        for v in _numeric_verses(seg.verse):
            requested.append((seg.chapter, v))
        # Some imported projects may index a bridge/range literally. Try it too.
        if "-" in seg.verse or "–" in seg.verse:
            requested.append((seg.chapter, seg.verse))
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for ch, v in requested:
        try:
            rows = project.checks_for_verse(ch, v)
        except Exception:
            continue
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            ctx = _context_for_check(row)
            key = (
                str(ctx.get("tool") or row.get("tool") or ""),
                str(ctx.get("checkId") or row.get("checkId") or ""),
                str(ctx.get("groupId") or row.get("groupId") or ""),
                str(ctx.get("quoteString") or row.get("source_quote") or ""),
            )
            if key in seen:
                continue
            seen.add(key); out.append(row)
    return out


def units_for_tc_checks(
    source_repo: SemanticSourceRepository, project: Any, chapter: str, verse: str,
    checks: Sequence[dict[str, Any]], *, tolerate_unresolved: bool = False,
) -> tuple[list[SourceSemanticUnit], list[dict[str, Any]]] | list[SourceSemanticUnit]:
    """Resolve native tN/tW checks to canonical UHB/UGNT semantic units.

    A single stale/malformed help anchor must not make the whole verse unusable.
    When `tolerate_unresolved=True`, unresolved anchors are returned as explicit
    review diagnostics while resolvable checks continue through Stage 3.
    """
    units: list[SourceSemanticUnit] = []
    unresolved: list[dict[str, Any]] = []
    seen: set[str] = set()
    for c in checks:
        ctx = _context_for_check(c)
        ref = ctx.get("reference", {}) if isinstance(ctx.get("reference"), dict) else {}
        tool = str(ctx.get("tool") or c.get("tool") or "")
        check_id = str(ctx.get("checkId") or c.get("checkId") or "")
        group_id = str(ctx.get("groupId") or c.get("groupId") or "")
        quote = str(ctx.get("quoteString") or c.get("source_quote") or "")
        try:
            occurrence = int(ctx.get("occurrence") or c.get("occurrence") or 1)
        except (TypeError, ValueError):
            occurrence = 1
        try:
            unit = source_repo.unit_for_check(
                book=str(project.book_id).upper(), chapter=str(ref.get("chapter") or chapter),
                verse=str(ref.get("verse") or verse), tool=tool, check_id=check_id,
                group_id=group_id, source_quote=quote, occurrence=occurrence,
            )
        except SemanticMappingError as exc:
            if not tolerate_unresolved:
                raise
            unresolved.append({
                "checkId": check_id, "tool": tool, "groupId": group_id,
                "sourceQuote": quote, "state": "source_anchor_unresolved",
                "detail": str(exc),
            })
            continue
        if unit.id not in seen:
            units.append(unit)
            seen.add(unit.id)
    if tolerate_unresolved:
        return units, unresolved
    return units


def prepare_semantic_mappings_for_review(
    *, project: Any, client: Any, source_db_path: str | Path | None = None,
    chapter: str, verse: str, checks: Sequence[dict[str, Any]] | None = None,
    max_neighbor_windows: int = 2, force: bool = False,
) -> dict[str, Any]:
    """Resolve tN/tW source units across the target passage before verse AI review.

    This function intentionally returns an `unavailable` state instead of
    crashing the normal Bridge manual-review workflow if the bundled resource DB
    is absent or unreadable.  Mapping failures are explicit and never silently
    converted into omissions / Nothing-to-Select decisions.
    """
    db_path = Path(source_db_path) if source_db_path is not None else default_semantic_source_db_path()
    if not db_path.exists():
        return {
            "state": "unavailable", "mappings": [], "unresolved": [], "checkStates": [],
            "searchedWindows": [], "diagnostic": f"Semantic source database not found: {db_path}",
        }
    try:
        source_repo = SemanticSourceRepository(db_path)
        target_index = project_passage_index(project)
    except Exception as exc:
        return {
            "state": "unavailable", "mappings": [], "unresolved": [], "checkStates": [],
            "searchedWindows": [], "diagnostic": f"Semantic mapping initialization failed: {exc}",
        }

    # If callers do not force a current-verse check list, batch all checks in
    # the initial structural passage.  That makes a later verse in the same
    # passage a fingerprint/cache hit instead of another model request.
    checks = list(checks if checks is not None else checks_for_seed_passage(project, target_index, chapter, verse))
    units, anchor_unresolved = units_for_tc_checks(
        source_repo, project, chapter, verse, checks, tolerate_unresolved=True,
    )
    if not units:
        return {
            "state": "no_checks" if not anchor_unresolved else "needs_review",
            "mappings": [], "unresolved": anchor_unresolved, "checkStates": anchor_unresolved,
            "searchedWindows": [],
        }

    store = SemanticMappingStore(project.companion_dir())
    try:
        run = SemanticMappingEngine(source_repo, client, max_neighbor_windows=max_neighbor_windows).map_units(
            target_index=target_index, source_units=units, store=store, force=force,
        )
    except Exception as exc:
        # Fail closed to review, not to a semantic conclusion. Do not hide the
        # diagnostic because model/schema/resource mismatches need developer eyes.
        #
        # A failure here means the whole batch's model call didn't produce a
        # usable result (schema/validation/transport error) -- it is not
        # limited to whichever unit's data happened to trigger it. Every unit
        # in this batch must therefore get an explicit mapping_error check
        # state, not just the ones already in anchor_unresolved (units that
        # were found in the source DB never reached anchor_unresolved, so
        # omitting this would silently drop them back to ordinary,
        # non-Stage-3 review with no visible sign anything failed).
        detail = str(exc)
        check_states = list(anchor_unresolved) + [
            {
                "sourceUnitId": unit.id, "checkId": unit.check_id, "tool": unit.tool,
                "groupId": unit.group_id, "state": "mapping_error", "selectable": False,
                "targetSpans": [], "meaningStatus": "UNCERTAIN", "relationships": ["UNCERTAIN"],
                "detail": detail,
            }
            for unit in units
        ]
        return {
            "state": "needs_review", "mappings": [],
            "unresolved": anchor_unresolved + [{"state": "mapping_error", "detail": detail}],
            "checkStates": check_states, "searchedWindows": [],
            "diagnostic": f"Semantic mapping failed: {detail}",
        }

    origin = f"{str(project.book_id).upper()} {chapter}:{verse}"
    by_unit = {m["source_unit_id"]: m for m in run.result["mappings"]}
    unresolved_by_unit = {u.get("source_unit_id"): u for u in run.result["unresolved_source_units"]}
    check_states: list[dict[str, Any]] = list(anchor_unresolved)
    for unit in units:
        mapping = by_unit.get(unit.id)
        if mapping:
            state = mapping_state_for_review(mapping, origin)
        else:
            pending = unresolved_by_unit.get(unit.id, {})
            state = {
                "state": "needs_passage_review", "selectable": False, "targetSpans": [],
                "meaningStatus": "UNCERTAIN", "relationships": ["UNCERTAIN"],
                "detail": str(pending.get("detail") or "Target realization was not securely located."),
            }
        check_states.append({
            "sourceUnitId": unit.id, "checkId": unit.check_id, "tool": unit.tool,
            "groupId": unit.group_id, **state,
        })
    unresolved_all: list[dict[str, Any]] = list(anchor_unresolved) + list(run.result["unresolved_source_units"])
    return {
        "state": "ready" if not unresolved_all else "needs_review",
        "fingerprint": run.fingerprint, "cacheHit": run.cache_hit,
        "searchedWindows": list(run.searched_windows),
        "mappings": run.result["mappings"], "unresolved": unresolved_all,
        "checkStates": check_states,
        "sourceDb": str(db_path), "engineVersion": "3.0.0-beta14-stage3",
    }


def semantic_state_by_check(pack: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Index a Stage 3 pack by native translationCore check ID."""
    if not isinstance(pack, dict):
        return {}
    return {
        str(row.get("checkId")): row
        for row in pack.get("checkStates", [])
        if isinstance(row, dict) and row.get("checkId")
    }


def mapping_by_source_unit(pack: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not isinstance(pack, dict):
        return {}
    return {
        str(row.get("source_unit_id")): row
        for row in pack.get("mappings", [])
        if isinstance(row, dict) and row.get("source_unit_id")
    }


def attach_semantic_state_to_review(review: Any, check_state: dict[str, Any] | None, mapping: dict[str, Any] | None) -> Any:
    """Attach rich state to either a dataclass review or a mutable dict.

    Cross-verse/split/implicit mappings are *not* legacy Nothing-to-Select.
    Native tC write policy remains a later human-confirmed interoperability step.
    """
    state = str((check_state or {}).get("state") or "")
    if isinstance(review, dict):
        review["selection_state"] = state
        review["semantic_mapping"] = mapping
        if state in {"found_another_verse", "split_across_verses", "represented_implicitly"}:
            review["nothing_to_select"] = False
        return review
    try:
        review.selection_state = state
        review.semantic_mapping = mapping
        if state in {"found_another_verse", "split_across_verses", "represented_implicitly"}:
            review.nothing_to_select = False
    except Exception:
        pass
    return review
