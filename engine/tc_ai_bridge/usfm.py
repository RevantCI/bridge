"""Per-verse USFM helpers, kept under their long-standing names.

Since #91 Phase 1b every one of these is a view over the one fragment reader,
`usfm_verse.lift_verse`: the regexes that used to live here were the second of
five definitions of "the verse's text". Callers (checks, alignment, tN/tW
selection counting, import's word bank, AI prompts) import from here as before.
"""
from __future__ import annotations

from .usfm_verse import (  # noqa: F401  (re-exported names)
    PAIRED_MARKERS,
    WHITESPACE_TOKEN_TRIM_CHARS,
    marker_balance_issues,
    plain_text as strip_usfm,
    tokens as whitespace_tokens,
)

__all__ = [
    "PAIRED_MARKERS",
    "WHITESPACE_TOKEN_TRIM_CHARS",
    "marker_balance_issues",
    "strip_usfm",
    "whitespace_tokens",
]
