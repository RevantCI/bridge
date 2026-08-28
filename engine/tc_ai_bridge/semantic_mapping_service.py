"""Small service helpers for exposing Stage 3 companion mappings to Bridge UI."""
from __future__ import annotations

from typing import Any

from .semantic_mapping import SemanticMappingError, SemanticMappingStore, _literal_positions
from .semantic_mapping_bridge import project_passage_index


def semantic_mappings_for_verse(project: Any, chapter: str, verse: str) -> dict[str, Any]:
    book = str(project.book_id).upper()
    ref = f"{book} {chapter}:{verse}"
    store = SemanticMappingStore(project.companion_dir())
    records = store.records_for_reference(book, ref)
    return {
        "book": book, "chapter": str(chapter), "verse": str(verse),
        "reference": ref, "records": records,
    }


def confirm_semantic_mapping(
    project: Any, *, fingerprint: str, source_unit_id: str, decision: str,
    reviewer: str = "", note: str = "", edited_mapping: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if edited_mapping is not None:
        edited_mapping = _validate_human_mapping(project, edited_mapping)
    store = SemanticMappingStore(project.companion_dir())
    event = store.confirm(
        book=str(project.book_id).upper(), fingerprint=fingerprint,
        source_unit_id=source_unit_id, decision=decision, reviewer=reviewer,
        note=note, edited_mapping=edited_mapping,
    )
    return {"confirmed": True, "event": event}


def _validate_human_mapping(project: Any, mapping: dict[str, Any]) -> dict[str, Any]:
    """Literal validation for a human-edited mapping before persistence."""
    if not isinstance(mapping, dict):
        raise SemanticMappingError("Edited semantic mapping must be an object")
    idx = project_passage_index(project)
    by_ref = {s.reference: s for s in idx.segments}
    clean = dict(mapping)
    spans = mapping.get("target_spans")
    if not isinstance(spans, list):
        raise SemanticMappingError("Edited semantic mapping target_spans must be an array")
    clean_spans: list[dict[str, Any]] = []
    for span in spans:
        if not isinstance(span, dict):
            raise SemanticMappingError("Edited semantic mapping span must be an object")
        ref = str(span.get("reference") or "")
        quote = str(span.get("quote") or "")
        seg = by_ref.get(ref)
        if seg is None:
            raise SemanticMappingError(f"Edited target span references a verse/range not present in the imported project: {ref}")
        if not quote:
            raise SemanticMappingError(f"Edited target span has no exact target quote: {ref}")
        start = span.get("start"); end = span.get("end")
        if start is None and end is None:
            positions = _literal_positions(seg.text, quote)
            if len(positions) != 1:
                raise SemanticMappingError(f"Edited quote must occur exactly once when offsets are omitted: {ref} / {quote}")
            start, end = positions[0]
        if not isinstance(start, int) or not isinstance(end, int) or start < 0 or end < start or end > len(seg.text):
            raise SemanticMappingError(f"Edited mapping has invalid offsets: {ref}")
        if seg.text[start:end] != quote:
            raise SemanticMappingError(f"Edited target quote does not exactly match imported USFM at offsets: {ref}")
        clean_spans.append({"reference": ref, "quote": quote, "start": start, "end": end})
    clean["target_spans"] = clean_spans
    return clean
