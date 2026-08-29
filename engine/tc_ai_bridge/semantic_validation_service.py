"""Human validation queue and append-only audit for Stage 3 corpus mappings.

The generated validation set is evidence for review, never application data.
Confirming, rejecting, or correcting a row writes only to the Bridge companion
directory.  Target USFM and translationCore check/alignment files are never
modified by this module.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from .semantic_mapping import MEANING_STATUSES, RELATIONSHIPS, SemanticMappingError
from .semantic_mapping_service import _validate_human_mapping


VALIDATION_SET_NAME = "irvtam-semantic-mapping-candidates.json"
AUDIT_SCHEMA = "bridge.semantic_mapping_validation_audit.v0.1"
DECISION_STATUS = {
    "confirmed": "HUMAN_CONFIRMED",
    "rejected": "HUMAN_REJECTED",
    "corrected": "HUMAN_CORRECTED",
    "unsure": "UNCONFIRMED",
}


def semantic_validation_manifest_path() -> Path:
    """Resolve the generated queue in development and installed builds."""
    candidates: list[Path] = []
    explicit = str(os.environ.get("BRIDGE_SEMANTIC_VALIDATION_SET") or "").strip()
    if explicit:
        candidates.append(Path(explicit))
    bundled = str(os.environ.get("BRIDGE_BUNDLED_RESOURCES_DIR") or "").strip()
    if bundled:
        candidates.append(Path(bundled) / "semantic_mapping" / "validation" / VALIDATION_SET_NAME)
    repository_root = Path(__file__).resolve().parents[2]
    candidates.extend([
        repository_root / "docs" / "validation" / VALIDATION_SET_NAME,
        Path.cwd() / "docs" / "validation" / VALIDATION_SET_NAME,
        Path.cwd() / "resources" / "semantic_mapping" / "validation" / VALIDATION_SET_NAME,
    ])
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise SemanticMappingError(
        "The semantic mapping validation set is not installed. Rebuild Bridge resources or set "
        "BRIDGE_SEMANTIC_VALIDATION_SET."
    )


def _load_manifest(path: Path | None = None) -> tuple[dict[str, Any], str]:
    source = path or semantic_validation_manifest_path()
    raw = source.read_bytes()
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise SemanticMappingError(f"Semantic validation set is invalid JSON: {source}") from exc
    if not isinstance(manifest, dict) or not isinstance(manifest.get("candidates"), list):
        raise SemanticMappingError(f"Semantic validation set has an invalid contract: {source}")
    return manifest, hashlib.sha256(raw).hexdigest()


def _audit_path(project: Any) -> Path:
    return project.companion_dir() / "semanticValidation" / "irvtam-v0.1.json"


def _load_audit(project: Any) -> dict[str, Any]:
    path = _audit_path(project)
    if not path.exists():
        return {"schema": AUDIT_SCHEMA, "decisions": {}, "audit": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SemanticMappingError(f"Semantic validation audit cannot be read: {path}") from exc
    if not isinstance(payload, dict):
        raise SemanticMappingError(f"Semantic validation audit has an invalid contract: {path}")
    if not isinstance(payload.get("decisions"), dict):
        payload["decisions"] = {}
    if not isinstance(payload.get("audit"), list):
        payload["audit"] = []
    return payload


def _save_audit(project: Any, payload: dict[str, Any]) -> Path:
    path = _audit_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    json.loads(temporary.read_text(encoding="utf-8"))
    temporary.replace(path)
    return path


def _candidate_book(candidate: dict[str, Any]) -> str:
    unit = candidate.get("sourceUnit") if isinstance(candidate.get("sourceUnit"), dict) else {}
    return str(unit.get("source_reference") or "").split(" ", 1)[0].upper()


def _candidate_for_id(manifest: dict[str, Any], candidate_id: str, book: str) -> dict[str, Any]:
    for candidate in manifest.get("candidates", []):
        if (
            isinstance(candidate, dict)
            and str(candidate.get("candidateId") or "") == candidate_id
            and _candidate_book(candidate) == book
        ):
            return candidate
    raise SemanticMappingError(f"Unknown semantic validation candidate for {book}: {candidate_id}")


def _mapping_from_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_unit_id": str((candidate.get("sourceUnit") or {}).get("id") or ""),
        "source_reference": str((candidate.get("sourceUnit") or {}).get("source_reference") or ""),
        "target_spans": list(candidate.get("targetSpans") or []),
        "relationships": list(candidate.get("relationships") or []),
        "meaning_status": str(candidate.get("meaningStatus") or "UNCERTAIN"),
        "confidence": float(candidate.get("confidence") or 0.0),
    }


def _validate_mapping(project: Any, mapping: dict[str, Any]) -> dict[str, Any]:
    clean = _validate_human_mapping(project, mapping)
    relationships = list(dict.fromkeys(str(item) for item in mapping.get("relationships") or []))
    if not relationships or any(item not in RELATIONSHIPS for item in relationships):
        raise SemanticMappingError("Corrected mapping must contain only supported semantic relationships")
    source_reference = str(mapping.get("source_reference") or "")
    target_references = {str(span.get("reference") or "") for span in clean.get("target_spans", [])}
    cross_verse = bool(target_references and any(reference != source_reference for reference in target_references))
    if cross_verse and not any(
        item in relationships for item in (
            "CROSS_VERSE", "CROSS_VERSE_MOVED", "CROSS_VERSE_REORDERED",
            "SPLIT_ACROSS_VERSES", "MERGED_ACROSS_VERSES", "VERSIFICATION_DIFFERENCE",
        )
    ):
        raise SemanticMappingError("A cross-reference correction must retain an explicit cross-verse relationship")
    meaning_status = str(mapping.get("meaning_status") or "")
    if meaning_status not in MEANING_STATUSES:
        raise SemanticMappingError("Corrected mapping has an unsupported meaning status")
    try:
        confidence = float(mapping.get("confidence"))
    except (TypeError, ValueError) as exc:
        raise SemanticMappingError("Corrected mapping confidence must be a number from 0 to 1") from exc
    if confidence < 0 or confidence > 1:
        raise SemanticMappingError("Corrected mapping confidence must be a number from 0 to 1")
    clean.update({
        "source_unit_id": str(mapping.get("source_unit_id") or ""),
        "source_reference": source_reference,
        "relationships": relationships,
        "meaning_status": meaning_status,
        "confidence": confidence,
        "proposal_provenance": "HUMAN_CORRECTED",
        "validation_status": "HUMAN_CORRECTED",
    })
    return clean


def list_semantic_validation_candidates(project: Any) -> dict[str, Any]:
    manifest, manifest_hash = _load_manifest()
    audit = _load_audit(project)
    book = str(project.book_id).upper()
    decisions = audit.get("decisions", {})
    rows: list[dict[str, Any]] = []
    for source in manifest.get("candidates", []):
        if not isinstance(source, dict) or _candidate_book(source) != book:
            continue
        candidate = dict(source)
        candidate_id = str(candidate.get("candidateId") or "")
        decision = decisions.get(candidate_id) if isinstance(decisions.get(candidate_id), dict) else None
        project_match = True
        match_error = ""
        try:
            _validate_mapping(project, _mapping_from_candidate(candidate))
        except SemanticMappingError as exc:
            project_match = False
            match_error = str(exc)
        candidate["projectMatch"] = project_match
        candidate["projectMatchError"] = match_error
        candidate["reviewDecision"] = decision
        candidate["validationStatus"] = (
            str(decision.get("validationStatus")) if decision else str(candidate.get("validationStatus") or "UNCONFIRMED")
        )
        rows.append(candidate)

    counts = {"UNCONFIRMED": 0, "HUMAN_CONFIRMED": 0, "HUMAN_REJECTED": 0, "HUMAN_CORRECTED": 0}
    for row in rows:
        status = str(row.get("validationStatus") or "UNCONFIRMED")
        counts[status] = counts.get(status, 0) + 1
    relationships = sorted({
        str(item) for row in rows for item in row.get("relationships", []) if str(item)
    })
    calibration = _calibration_summary(rows)
    return {
        "schema": str(manifest.get("schema") or ""),
        "manifestSha256": manifest_hash,
        "model": str(manifest.get("model") or ""),
        "book": book,
        "available": bool(rows),
        "candidates": rows,
        "summary": {"total": len(rows), "counts": counts},
        "calibration": calibration,
        "relationships": relationships,
        "auditPath": str(_audit_path(project)),
    }


def _calibration_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Describe human agreement without treating unconfirmed rows as failures."""
    reviewed = [
        row for row in rows
        if isinstance(row.get("reviewDecision"), dict)
        and str(row["reviewDecision"].get("decision") or "") in {"confirmed", "corrected", "rejected"}
    ]
    confirmed = sum(1 for row in reviewed if row["reviewDecision"]["decision"] == "confirmed")
    corrected = sum(1 for row in reviewed if row["reviewDecision"]["decision"] == "corrected")
    rejected = sum(1 for row in reviewed if row["reviewDecision"]["decision"] == "rejected")

    def bucket_summary(bucket_rows: list[dict[str, Any]]) -> dict[str, int]:
        return {
            "reviewed": len(bucket_rows),
            "confirmed": sum(1 for row in bucket_rows if row["reviewDecision"]["decision"] == "confirmed"),
            "corrected": sum(1 for row in bucket_rows if row["reviewDecision"]["decision"] == "corrected"),
            "rejected": sum(1 for row in bucket_rows if row["reviewDecision"]["decision"] == "rejected"),
        }

    confidence_bands = {
        "90-100%": bucket_summary([row for row in reviewed if float(row.get("confidence") or 0) >= 0.9]),
        "80-89%": bucket_summary([row for row in reviewed if 0.8 <= float(row.get("confidence") or 0) < 0.9]),
        "below 80%": bucket_summary([row for row in reviewed if float(row.get("confidence") or 0) < 0.8]),
    }
    relationship_rows = {
        relationship: bucket_summary([row for row in reviewed if relationship in row.get("relationships", [])])
        for relationship in sorted({str(item) for row in reviewed for item in row.get("relationships", [])})
    }
    return {
        "reviewed": len(reviewed), "confirmed": confirmed, "corrected": corrected, "rejected": rejected,
        "proposalAgreementPercent": round((confirmed / len(reviewed)) * 100) if reviewed else None,
        "byConfidence": confidence_bands, "byRelationship": relationship_rows,
    }


def decide_semantic_validation_candidate(
    project: Any, *, candidate_id: str, decision: str, reviewer: str,
    note: str = "", corrected_mapping: dict[str, Any] | None = None,
) -> dict[str, Any]:
    decision = str(decision or "").strip().lower()
    if decision not in DECISION_STATUS:
        raise SemanticMappingError(f"Invalid semantic validation decision: {decision}")
    reviewer = str(reviewer or "").strip()
    if not reviewer:
        raise SemanticMappingError("Reviewer name is required for a semantic validation decision")
    manifest, manifest_hash = _load_manifest()
    book = str(project.book_id).upper()
    candidate = _candidate_for_id(manifest, str(candidate_id or ""), book)
    original_mapping = _mapping_from_candidate(candidate)
    clean_mapping: dict[str, Any] | None = None
    if decision == "confirmed":
        clean_mapping = _validate_mapping(project, original_mapping)
        clean_mapping["proposal_provenance"] = "HUMAN_CONFIRMED"
        clean_mapping["validation_status"] = "HUMAN_CONFIRMED"
    elif decision == "corrected":
        if not isinstance(corrected_mapping, dict):
            raise SemanticMappingError("A corrected mapping is required for decision='corrected'")
        merged = dict(original_mapping)
        merged.update(corrected_mapping)
        clean_mapping = _validate_mapping(project, merged)
    elif corrected_mapping is not None:
        raise SemanticMappingError("A corrected mapping is only valid for decision='corrected'")

    now = datetime.now(timezone.utc).isoformat()
    event: dict[str, Any] = {
        "candidateId": str(candidate_id),
        "sourceUnitId": str((candidate.get("sourceUnit") or {}).get("id") or ""),
        "decision": decision,
        "validationStatus": DECISION_STATUS[decision],
        "provenance": DECISION_STATUS[decision],
        "reviewer": reviewer,
        "note": str(note or ""),
        "at": now,
        "manifestSha256": manifest_hash,
        "mappingFingerprint": str(candidate.get("mappingFingerprint") or ""),
    }
    if clean_mapping is not None:
        event["mapping"] = clean_mapping

    audit = _load_audit(project)
    audit.update({
        "schema": AUDIT_SCHEMA,
        "book": book,
        "manifestSha256": manifest_hash,
        "updatedAt": now,
    })
    audit.setdefault("audit", []).append(event)
    audit.setdefault("decisions", {})[str(candidate_id)] = event
    path = _save_audit(project, audit)
    return {"saved": True, "event": event, "auditPath": str(path)}
