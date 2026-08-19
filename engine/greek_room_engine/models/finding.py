"""
QaFinding: the universal result type for every QA engine.

Per the architecture doc (§6): the UI should never need to know whether a
problem came from Wildebeest, USFM, OWL, Smart Edit Distance, UAlign, or AI.
Every checker normalizes its output into a QaFinding.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


class FindingStatus(str, Enum):
    OPEN = "open"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    IGNORED = "ignored"
    FIXED = "fixed"
    NEEDS_DISCUSSION = "needs_discussion"


class FindingCategory(str, Enum):
    """Matches the wireframe's badge categories: tN / tW / Alignment / QA / Greek Room."""
    STRUCTURE = "structure"
    UNICODE = "unicode"
    SPELLING = "spelling"
    NAMES = "names"
    REPETITION = "repetition"
    ALIGNMENT = "alignment"
    CONSISTENCY = "consistency"
    OMISSION_ADDITION = "omission_addition"
    TRANSLATION_WORD = "translation_word"  # tW
    TRANSLATION_NOTE = "translation_note"  # tN


class Severity(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


@dataclass
class EvidenceItem:
    """A single piece of supporting evidence shown in the 'Why flagged?' panel."""
    label: str
    value: str


@dataclass
class QaFinding:
    # Identity
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    project_id: str = ""
    run_id: str = ""
    project_hash: str = ""

    # Location
    book: str = ""
    chapter: int = 0
    verse: int = 0
    start_offset: Optional[int] = None
    end_offset: Optional[int] = None
    original_text: str = ""

    # Classification
    engine: str = ""            # e.g. "wildebeest", "owl", "usfm", "alignment", "ai"
    check_type: str = ""        # e.g. "wildebeest.script.mixed"
    category: FindingCategory = FindingCategory.CONSISTENCY
    severity: Severity = Severity.MEDIUM
    confidence: float = 0.0     # 0.0 - 1.0

    # Content
    suggested_replacement: Optional[str] = None
    explanation: str = ""
    evidence: list[EvidenceItem] = field(default_factory=list)

    # Versioning / provenance
    engine_version: str = ""

    # Human review state
    status: FindingStatus = FindingStatus.OPEN
    human_comment: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    resolved_at: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["category"] = self.category.value
        d["severity"] = self.severity.value
        d["status"] = self.status.value
        return d

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "QaFinding":
        d = dict(d)
        if "category" in d and d["category"] is not None:
            d["category"] = FindingCategory(d["category"])
        if "severity" in d and d["severity"] is not None:
            d["severity"] = Severity(d["severity"])
        if "status" in d and d["status"] is not None:
            d["status"] = FindingStatus(d["status"])
        if "evidence" in d and d["evidence"]:
            d["evidence"] = [
                e if isinstance(e, EvidenceItem) else EvidenceItem(**e)
                for e in d["evidence"]
            ]
        return QaFinding(**d)
