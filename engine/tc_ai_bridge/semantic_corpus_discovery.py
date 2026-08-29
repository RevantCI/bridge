"""Generate unconfirmed semantic-mapping validation candidates from a corpus.

This is an offline/developer corpus-analysis layer around the production Stage 3
mapper.  It never writes project USFM or translationCore checkData.  Every row
remains MACHINE_PROPOSED until a reviewer explicitly confirms it.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterable, Sequence

from .semantic_mapping import (
    MappingRun, PassageSearchBudget, SemanticMappingEngine,
    SemanticSourceRepository, SourceSemanticUnit,
)
from .usfm_passages import PassageWindow, UsfmPassageIndex

VALIDATION_SCHEMA = "bridge.semantic_mapping_validation_set.v0.1"
REQUESTED_VALIDATION_RELATIONSHIPS = (
    "CROSS_VERSE", "CROSS_VERSE_REORDERED", "SENTENCE_MOVED",
    "SENTENCE_REORDERED", "CLAUSE_MOVED", "CLAUSE_REORDERED",
    "SPLIT_ACROSS_VERSES", "MERGED_ACROSS_VERSES",
    "REORDERED_WITHIN_VERSE", "PRONOMINALIZED", "GRAMMATICALLY_ENCODED",
    "IMPLICIT", "VERSIFICATION_DIFFERENCE", "POSSIBLE_OMISSION_CANDIDATE",
    "UNCERTAIN_COMPETING_MAPPING",
)

_RELATIONSHIP_VALUE = {
    "VERSIFICATION_DIFFERENCE": 100,
    "MERGED_ACROSS_VERSES": 98,
    "SPLIT_ACROSS_VERSES": 96,
    "CROSS_VERSE_REORDERED": 94,
    "SENTENCE_REORDERED": 92,
    "SENTENCE_MOVED": 90,
    "CLAUSE_REORDERED": 88,
    "CLAUSE_MOVED": 86,
    "CROSS_VERSE_MOVED": 84,
    "CROSS_VERSE": 82,
    "PRONOMINALIZED": 80,
    "GRAMMATICALLY_ENCODED": 78,
    "IMPLICIT": 76,
    "REORDERED_WITHIN_VERSE": 70,
    "PARAPHRASED": 64,
    "UNCERTAIN": 60,
    "SAME_VERSE": 20,
}


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _reference_parts(reference: str) -> tuple[str, str, str]:
    book, cv = str(reference).split(" ", 1)
    chapter, verse = cv.split(":", 1)
    return book, chapter, verse


def _anchors_for_references(
    repository: SemanticSourceRepository, references: Sequence[str], *, limit: int,
) -> list[SourceSemanticUnit]:
    if not references:
        return []
    placeholders = ",".join("?" for _ in references)
    with repository._connect() as connection:
        rows = connection.execute(
            f"SELECT * FROM help_anchors WHERE reference IN ({placeholders}) "
            "ORDER BY reference, CASE tool WHEN 'translationNotes' THEN 0 ELSE 1 END, group_id, id",
            tuple(references),
        ).fetchall()
    # Prefer diversity over repeated anchors for the same help group.
    selected: list[SourceSemanticUnit] = []
    seen_groups: set[tuple[str, str, str]] = set()
    for row in rows:
        key = (str(row["reference"]), str(row["tool"]), str(row["group_id"] or row["id"]))
        if key in seen_groups:
            continue
        book, chapter, verse = _reference_parts(str(row["reference"]))
        try:
            unit = repository.unit_for_check(
                book=book, chapter=chapter, verse=verse, tool=str(row["tool"]),
                check_id=str(row["id"]), group_id=str(row["group_id"] or ""),
                source_quote=str(row["quote"] or ""), occurrence=int(row["occurrence"] or 1),
            )
        except Exception:
            continue
        selected.append(unit)
        seen_groups.add(key)
        if len(selected) >= max(1, int(limit)):
            break
    return selected


def propose_corpus_batches(
    repository: SemanticSourceRepository,
    corpora: Sequence[tuple[str | Path, str]],
    *, max_batches: int = 10, units_per_batch: int = 10,
) -> list[tuple[Path, UsfmPassageIndex, PassageWindow, list[SourceSemanticUnit]]]:
    """Choose structurally diverse, deterministic corpus batches.

    Selection uses paragraph/sentence windows, chapter coverage, verse bridges,
    and help-anchor diversity.  It does not encode any target-language grammar.
    """
    available: list[tuple[float, Path, UsfmPassageIndex, PassageWindow, list[SourceSemanticUnit]]] = []
    for raw_path, book in corpora:
        path = Path(raw_path)
        index = UsfmPassageIndex.from_path(path, book_hint=book)
        for window in index.windows:
            units = _anchors_for_references(repository, window.references, limit=units_per_batch)
            if not units:
                continue
            chapters = {segment.chapter for segment in window.segments}
            has_range = any("-" in segment.verse or "–" in segment.verse for segment in window.segments)
            score = (
                min(8, len(window.segments)) * 4
                + min(units_per_batch, len(units)) * 2
                + (12 if has_range else 0)
                + (5 if len(chapters) > 1 else 0)
            )
            # Stable tie spreading prevents all samples coming from one chapter.
            score += int(hashlib.sha256(window.id.encode()).hexdigest()[:4], 16) / 65535
            available.append((score, path, index, window, units))

    selected: list[tuple[Path, UsfmPassageIndex, PassageWindow, list[SourceSemanticUnit]]] = []
    used_chapters: set[tuple[str, str]] = set()

    # The known regression is a required sentinel, not a learned Tamil rule.
    regression = next((row for row in available if row[2].book == "PHP" and "PHP 1:3" in row[3].references), None)
    if regression:
        units = regression[4]
        if not any(unit.check_id == "gjyv" for unit in units):
            try:
                sentinel = repository.unit_for_check(
                    book="PHP", chapter="1", verse="3", tool="translationNotes", check_id="gjyv",
                )
                units = [sentinel] + units[: max(0, units_per_batch - 1)]
            except Exception:
                pass
        selected.append((regression[1], regression[2], regression[3], units))
        used_chapters.add(("PHP", "1"))

    # First pass maximizes book/chapter coverage, second pass fills by diagnostic score.
    ranked = sorted(available, key=lambda row: (-row[0], row[2].book, row[3].ordinal))
    for require_new_chapter in (True, False):
        for _, path, index, window, units in ranked:
            if len(selected) >= max_batches:
                break
            if any(existing[1].book == index.book and existing[2].id == window.id for existing in selected):
                continue
            chapter = window.segments[0].chapter if window.segments else ""
            if require_new_chapter and (index.book, chapter) in used_chapters:
                continue
            selected.append((path, index, window, units))
            used_chapters.add((index.book, chapter))
        if len(selected) >= max_batches:
            break
    return selected


def structural_screen_candidates(
    repository: SemanticSourceRepository,
    corpora: Sequence[tuple[str | Path, str]],
    *, limit: int = 40,
) -> list[dict[str, Any]]:
    """Create local-only candidates from deterministic structural evidence.

    These are screening hypotheses, not semantic conclusions.  They are useful
    for choosing passages for later model/human validation when corpus text may
    not be transmitted externally.  Only the supplied PHP sentinel receives a
    meaning-preserved conclusion because its exact mapping is a stated regression
    requirement and its quote is verified byte-for-byte against the corpus.
    """
    index_by_book = {
        book.upper(): UsfmPassageIndex.from_path(path, book_hint=book)
        for path, book in corpora
    }
    screens: list[dict[str, Any]] = []

    # Required exact regression sentinel.
    php = index_by_book.get("PHP")
    if php is not None:
        unit = repository.unit_for_check(
            book="PHP", chapter="1", verse="3", tool="translationNotes", check_id="gjyv",
        )
        segment = php.segment_for_source_reference("1", "6")
        quote = "என் தேவனை"
        if segment and segment.text.count(quote) == 1:
            start = segment.text.index(quote)
            screens.append({
                "candidateId": "php-1-3-gjyv-cross-verse-regression",
                "proposalProvenance": "MACHINE_PROPOSED", "validationStatus": "UNCONFIRMED",
                "proposalScope": "EXACT_REGRESSION_SENTINEL", "diagnosticScore": 110,
                "sourceUnit": asdict(unit),
                "targetSpans": [{"reference": "PHP 1:6", "quote": quote, "start": start, "end": start + len(quote)}],
                "relationships": ["CROSS_VERSE", "CROSS_VERSE_REORDERED"],
                "meaningStatus": "PRESERVED", "confidence": 0.99,
                "evidence": {"source": unit.source_quote, "target": quote, "explanation": "Required PHP 1:3→1:6 regression; exact target quote verified in imported IRVTam USFM."},
                "searchedWindows": [php.window_for_source_reference("1", "3").id] if php.window_for_source_reference("1", "3") else [],
                "mappingFingerprint": hashlib.sha256((unit.id + segment.text).encode()).hexdigest(),
            })

    classifier = (
        ("PRONOMINALIZED", lambda group, note: "pronoun" in group or "pronoun" in note),
        ("GRAMMATICALLY_ENCODED", lambda group, note: group.startswith("grammar-") or any(key in group for key in ("activepassive", "abstractnouns", "nominaladj", "gendernotations", "possession"))),
        ("IMPLICIT", lambda group, note: "ellipsis" in group or "implicit" in note or "understood" in note),
        ("REORDERED_WITHIN_VERSE", lambda group, note: "reverse the order" in note or "put this clause first" in note),
        ("SENTENCE_REORDERED", lambda group, note: "begin a new sentence" in note or "make this a separate sentence" in note),
    )
    with repository._connect() as connection:
        rows = connection.execute(
            "SELECT * FROM help_anchors WHERE book IN ('LUK','PHP') ORDER BY book, reference, tool, id"
        ).fetchall()
    per_relationship: dict[str, int] = {}
    per_relationship_book: dict[tuple[str, str], int] = {}
    for row in rows:
        book = str(row["book"])
        index = index_by_book.get(book)
        if index is None:
            continue
        reference = str(row["reference"])
        _, chapter, verse = _reference_parts(reference)
        segment = index.segment_for_source_reference(chapter, verse)
        window = index.window_for_source_reference(chapter, verse)
        if segment is None or window is None:
            continue
        group = str(row["group_id"] or "").lower()
        note = str(row["note"] or "").lower()
        hypotheses = [name for name, predicate in classifier if predicate(group, note)]
        lo_hi = segment.verse.replace("–", "-").split("-", 1)
        if len(lo_hi) == 2 and all(part.isdigit() for part in lo_hi):
            hypotheses.extend(["VERSIFICATION_DIFFERENCE", "MERGED_ACROSS_VERSES"])
        if not hypotheses:
            continue
        primary = hypotheses[0]
        if per_relationship.get(primary, 0) >= 8 or per_relationship_book.get((primary, book), 0) >= 4:
            continue
        try:
            unit = repository.unit_for_check(
                book=book, chapter=chapter, verse=verse, tool=str(row["tool"]),
                check_id=str(row["id"]), group_id=str(row["group_id"] or ""),
                source_quote=str(row["quote"] or ""), occurrence=int(row["occurrence"] or 1),
            )
        except Exception:
            continue
        screens.append({
            "candidateId": hashlib.sha256(f"structural|{unit.id}|{segment.reference}".encode()).hexdigest()[:20],
            "proposalProvenance": "MACHINE_PROPOSED", "validationStatus": "UNCONFIRMED",
            "proposalScope": "STRUCTURAL_SCREEN", "diagnosticScore": _RELATIONSHIP_VALUE.get(primary, 60),
            "sourceUnit": asdict(unit), "targetSpans": [], "targetPassageReferences": window.references,
            "relationships": list(dict.fromkeys(hypotheses)), "meaningStatus": "UNCERTAIN", "confidence": 0.0,
            "evidence": {
                "source": unit.source_quote, "target": "",
                "explanation": "Deterministic Stage 3 help/USFM structure identified this passage for semantic validation; no cross-language meaning conclusion or target span has been accepted.",
            },
            "searchedWindows": [window.id], "mappingFingerprint": "",
        })
        per_relationship[primary] = per_relationship.get(primary, 0) + 1
        per_relationship_book[(primary, book)] = per_relationship_book.get((primary, book), 0) + 1
    return rank_representative_candidates(screens, limit=limit)


def _candidate_from_mapping(mapping: dict[str, Any], unit: SourceSemanticUnit, run: MappingRun) -> dict[str, Any]:
    relationships = list(dict.fromkeys(str(value) for value in mapping.get("relationships") or []))
    confidence = float(mapping.get("confidence") or 0.0)
    diagnostic = max((_RELATIONSHIP_VALUE.get(value, 40) for value in relationships), default=40)
    diagnostic += round(confidence * 10, 2)
    if mapping.get("meaning_status") != "PRESERVED":
        diagnostic += 6
    return {
        "candidateId": hashlib.sha256(f"{unit.id}|{run.fingerprint}".encode()).hexdigest()[:20],
        "proposalProvenance": "MACHINE_PROPOSED",
        "validationStatus": "UNCONFIRMED",
        "diagnosticScore": diagnostic,
        "sourceUnit": asdict(unit),
        "targetSpans": list(mapping.get("target_spans") or []),
        "relationships": relationships,
        "meaningStatus": str(mapping.get("meaning_status") or "UNCERTAIN"),
        "confidence": confidence,
        "evidence": dict(mapping.get("evidence") or {}),
        "searchedWindows": list(run.searched_windows),
        "mappingFingerprint": run.fingerprint,
    }


def _candidate_from_unresolved(row: dict[str, Any], unit: SourceSemanticUnit, run: MappingRun) -> dict[str, Any]:
    exhausted = row.get("reason") == "SEARCH_BUDGET_EXHAUSTED"
    relationship = "NEEDS_EXTENDED_PASSAGE_REVIEW" if exhausted else "UNCERTAIN_COMPETING_MAPPING"
    return {
        "candidateId": hashlib.sha256(f"{unit.id}|{run.fingerprint}|unresolved".encode()).hexdigest()[:20],
        "proposalProvenance": "MACHINE_PROPOSED",
        "validationStatus": "UNCONFIRMED",
        "diagnosticScore": 72 if exhausted else 75,
        "sourceUnit": asdict(unit),
        "targetSpans": [],
        "relationships": [relationship],
        "meaningStatus": "UNCERTAIN",
        "confidence": 0.0,
        "evidence": {"source": unit.source_quote, "target": "", "explanation": str(row.get("detail") or "")},
        "searchedWindows": list(run.searched_windows),
        "mappingFingerprint": run.fingerprint,
    }


def candidates_from_run(run: MappingRun) -> list[dict[str, Any]]:
    units = {unit.id: unit for unit in run.source_units}
    candidates = [
        _candidate_from_mapping(mapping, units[str(mapping["source_unit_id"])], run)
        for mapping in run.result.get("mappings", [])
        if str(mapping.get("source_unit_id") or "") in units
    ]
    candidates.extend(
        _candidate_from_unresolved(row, units[str(row["source_unit_id"])], run)
        for row in run.result.get("unresolved_source_units", [])
        if str(row.get("source_unit_id") or "") in units
    )
    return candidates


def rank_representative_candidates(candidates: Iterable[dict[str, Any]], *, limit: int = 40) -> list[dict[str, Any]]:
    """Rank while retaining relationship and book diversity."""
    unique: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        unique[str(candidate.get("candidateId"))] = candidate
    ranked = sorted(unique.values(), key=lambda row: (-float(row.get("diagnosticScore") or 0), str(row.get("candidateId"))))
    output: list[dict[str, Any]] = []
    relationship_counts: dict[str, int] = {}
    book_counts: dict[str, int] = {}
    for candidate in ranked:
        relationships = candidate.get("relationships") or ["UNCERTAIN"]
        primary = str(relationships[0])
        book = str((candidate.get("sourceUnit") or {}).get("source_reference") or "").split(" ", 1)[0]
        if relationship_counts.get(primary, 0) >= 8 or book_counts.get(book, 0) >= max(12, limit - 8):
            continue
        output.append(candidate)
        relationship_counts[primary] = relationship_counts.get(primary, 0) + 1
        book_counts[book] = book_counts.get(book, 0) + 1
        if len(output) >= limit:
            break
    for rank, candidate in enumerate(output, 1):
        candidate["rank"] = rank
    return output


def validation_payload(
    *, candidates: Sequence[dict[str, Any]], corpora: Sequence[tuple[str | Path, str]],
    source_db: str | Path, model: str, budget: PassageSearchBudget,
) -> dict[str, Any]:
    relationship_counts: dict[str, int] = {}
    for candidate in candidates:
        for relationship in candidate.get("relationships") or []:
            relationship_counts[str(relationship)] = relationship_counts.get(str(relationship), 0) + 1
    return {
        "schema": VALIDATION_SCHEMA,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "proposalProvenance": "MACHINE_PROPOSED",
        "validationStatus": "UNCONFIRMED",
        "languageSpecificRulesUsed": False,
        "model": model,
        "searchBudget": asdict(budget.normalized()),
        "sourceDatabase": {"file": Path(source_db).name, "sha256": file_sha256(source_db)},
        "corpora": [
            {"book": book, "file": Path(path).name, "sha256": file_sha256(path)} for path, book in corpora
        ],
        "summary": {
            "candidateCount": len(candidates), "relationshipCounts": relationship_counts,
            "requestedCoverage": {
                relationship: relationship_counts.get(relationship, 0)
                for relationship in REQUESTED_VALIDATION_RELATIONSHIPS
            },
        },
        "candidates": list(candidates),
    }


def write_validation_payload(path: str | Path, payload: dict[str, Any]) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.with_suffix(destination.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    json.loads(temp.read_text(encoding="utf-8"))
    temp.replace(destination)
    return destination
