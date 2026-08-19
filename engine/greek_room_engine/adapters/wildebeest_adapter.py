"""
Wildebeest adapter.

Per doc §7, this is the first and cleanest Greek Room component to
integrate: direct Python API, read-only, no modification of source files.
It catches mixed scripts, bad Unicode, misplaced Indic marks, punctuation
anomalies, etc. — exactly what the "Unicode" badge category needs.

This adapter tries to use the real `wildebeest` package if installed. If
it's not available (e.g. during frontend/protocol development before the
pip dependency is wired up), it falls back to a small set of deterministic
mock checks so the rest of the pipeline (protocol, caching, UI) can be
built and tested independently.
"""
from __future__ import annotations

import re
from typing import Any

from .base import CheckAdapter
from ..models.finding import QaFinding, FindingCategory, Severity, EvidenceItem

try:
    import wildebeest.wb_analysis as wb_ana  # type: ignore
    _WILDEBEEST_AVAILABLE = True
except ImportError:
    wb_ana = None
    _WILDEBEEST_AVAILABLE = False


# Very small illustrative script-mixing check used only when the real
# `wildebeest` package isn't installed. NOT a substitute for the real thing.
_LATIN_RE = re.compile(r"[A-Za-z]")
_TAMIL_RE = re.compile(r"[\u0B80-\u0BFF]")
_DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")


class WildebeestAdapter(CheckAdapter):
    engine_name = "wildebeest"

    def is_available(self) -> bool:
        # Always available: falls back to the mock implementation when the
        # real `wildebeest` package isn't installed, so protocol/UI work
        # isn't blocked on the upstream dependency being wired up yet.
        return True

    def using_real_engine(self) -> bool:
        return _WILDEBEEST_AVAILABLE

    def version(self) -> str:
        if _WILDEBEEST_AVAILABLE:
            try:
                import wildebeest  # type: ignore
                return getattr(wildebeest, "__version__", "unknown")
            except Exception:
                return "unknown"
        return "mock-0.0.0"

    def check_verse(self, *, project_id: str, lang_code: str, ref: str,
                     text: str, params: dict[str, Any]) -> list[QaFinding]:
        if _WILDEBEEST_AVAILABLE:
            return self._check_with_wildebeest(project_id, lang_code, ref, text)
        return self._check_mock(project_id, lang_code, ref, text)

    # -- real integration -------------------------------------------------

    def _check_with_wildebeest(self, project_id: str, lang_code: str,
                                ref: str, text: str) -> list[QaFinding]:
        """
        Adapts wildebeest's BibleTranslationCheck response into QaFindings.

        NOTE: exact call shape depends on the installed wildebeest version;
        adjust field access here if upstream's response schema changes.
        This isolation is the whole point of the adapter boundary (doc §3).
        """
        findings: list[QaFinding] = []
        check_request = {"lang_code": lang_code, "ref": ref, "text": text}
        check_response = wb_ana.check(check_request)  # type: ignore[attr-defined]

        for item in getattr(check_response, "issues", []) or []:
            findings.append(QaFinding(
                project_id=project_id,
                book=ref.split()[0] if " " in ref else "",
                original_text=text[getattr(item, "start", 0):getattr(item, "end", 0)],
                start_offset=getattr(item, "start", None),
                end_offset=getattr(item, "end", None),
                engine=self.engine_name,
                check_type=f"wildebeest.{getattr(item, 'check_id', 'unknown')}",
                category=FindingCategory.UNICODE,
                severity=self._map_severity(getattr(item, "severity", 0.5)),
                confidence=float(getattr(item, "severity", 0.5)),
                suggested_replacement=getattr(item, "suggestion", None),
                explanation=getattr(item, "description", "Wildebeest flagged this span."),
                engine_version=self.version(),
            ))
        return findings

    @staticmethod
    def _map_severity(score: float) -> Severity:
        if score >= 0.8:
            return Severity.HIGH
        if score >= 0.5:
            return Severity.MEDIUM
        return Severity.LOW

    # -- fallback mock ------------------------------------------------------

    def _check_mock(self, project_id: str, lang_code: str, ref: str,
                     text: str) -> list[QaFinding]:
        findings: list[QaFinding] = []

        has_latin = bool(_LATIN_RE.search(text))
        has_tamil = bool(_TAMIL_RE.search(text))
        has_deva = bool(_DEVANAGARI_RE.search(text))

        if has_latin and (has_tamil or has_deva):
            match = _LATIN_RE.search(text)
            start, end = match.start(), match.end()
            findings.append(QaFinding(
                project_id=project_id,
                book=ref.split()[0] if " " in ref else "",
                original_text=text[start:end],
                start_offset=start,
                end_offset=end,
                engine=self.engine_name,
                check_type="wildebeest.script.mixed",
                category=FindingCategory.UNICODE,
                severity=Severity.HIGH,
                confidence=0.9,
                explanation="Token contains a Latin character mixed into non-Latin script text.",
                evidence=[EvidenceItem(label="Mode", value="mock adapter (wildebeest not installed)")],
                engine_version=self.version(),
            ))

        return findings
