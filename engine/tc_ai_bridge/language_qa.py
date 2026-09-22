"""Small offline target-text checks. No dictionaries, source judgments or writes.

Raw code-point spans always refer to the input, never its normalized copy.
Unicode Tamil §12.6 permits decomposed two-part vowels and Grantha conjuncts.
"""
from __future__ import annotations

import hashlib
import unicodedata
from collections import Counter
from typing import Any

import regex

RULE_VERSION = "language-qa-1"
MAX_VERSE_CHARS = 20_000
MAX_VERSE_FINDINGS = 100
CONSONANTS = frozenset("கஙசஜஞடணதநனபமயரறலளழவஶஷஸஹ")
SIGNS = frozenset("ாிீுூெேைொோௌ்ௗ")
WORD = regex.compile(r"\p{L}[\p{L}\p{M}]*")
GRAPHEME = regex.compile(r"\X")
SCRIPT_NAMES = ("TAMIL", "DEVANAGARI", "BENGALI", "TELUGU", "KANNADA",
                "MALAYALAM", "GUJARATI", "GURMUKHI", "ORIYA", "SINHALA",
                "ARABIC", "HEBREW", "LATIN", "CYRILLIC", "GREEK")
LANGUAGE_SCRIPTS = {
    "ta": "TAMIL", "tam": "TAMIL", "hi": "DEVANAGARI", "hin": "DEVANAGARI",
    "mr": "DEVANAGARI", "mar": "DEVANAGARI", "ne": "DEVANAGARI", "nep": "DEVANAGARI",
    "sa": "DEVANAGARI", "san": "DEVANAGARI", "bn": "BENGALI", "ben": "BENGALI",
    "as": "BENGALI", "asm": "BENGALI", "te": "TELUGU", "tel": "TELUGU",
    "kn": "KANNADA", "kan": "KANNADA", "ml": "MALAYALAM", "mal": "MALAYALAM",
    "gu": "GUJARATI", "guj": "GUJARATI", "pa": "GURMUKHI", "pan": "GURMUKHI",
    "or": "ORIYA", "ori": "ORIYA", "od": "ORIYA", "ory": "ORIYA",
    "ur": "ARABIC", "urd": "ARABIC", "en": "LATIN", "eng": "LATIN",
}


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="surrogatepass")).hexdigest()


def detect_language(sample: str, declared: str = "") -> dict[str, Any]:
    """Script evidence is not a general language classifier. Never guess Hindi.

    The 80% dominance / 20 letter minimum are routing heuristics, not calibrated
    probabilities; expose the counts and the basis instead of a confidence score.
    """
    declared = declared.strip().lower().replace("_", "-")
    code = declared.split("-")[0]
    counts: Counter[str] = Counter()
    for char in sample[:MAX_VERSE_CHARS]:
        if unicodedata.category(char).startswith("L"):
            name = unicodedata.name(char, "")
            script = next((s for s in SCRIPT_NAMES if name.startswith(s + " ")), "OTHER")
            counts[script] += 1
    total = sum(counts.values())
    script, count = counts.most_common(1)[0] if counts else ("UNKNOWN", 0)
    dominant = total >= 20 and count / total >= .8
    expected = LANGUAGE_SCRIPTS.get(code)
    # BCP-47 explicit scripts take precedence over the usual script for a language.
    explicit = {"taml": "TAMIL", "latn": "LATIN", "deva": "DEVANAGARI",
                "arab": "ARABIC", "beng": "BENGALI", "guru": "GURMUKHI"}
    for part in declared.split("-")[1:]:
        expected = explicit.get(part, expected)
    conflict = bool(expected and dominant and script != expected)
    mixed = total >= 20 and not dominant
    tamil = not conflict and not mixed and (
        (code in {"ta", "tam"} and expected == "TAMIL")
        or (not code and dominant and script == "TAMIL")
    )
    return {
        "declared": declared, "language": "tam" if tamil else code or "und",
        "script": script, "scriptCounts": dict(counts), "sampleLetters": total,
        "basis": "metadata-conflict" if conflict else "mixed-script" if mixed else
                 "metadata" if code else "script-suggestion" if tamil else "undetermined",
        "pack": "tamil" if tamil else "common",
        "message": "Tamil character rules available; grammar and spelling dictionaries are not included."
                   if tamil else "Common technical checks only; language-specific checks unavailable."
    }


def scan_text(text: str, *, book: str, chapter: str, verse: str,
              tamil: bool) -> dict[str, Any]:
    digest = text_hash(text)
    result: dict[str, Any] = {"textHash": digest, "findings": [], "limitations": []}
    if len(text) > MAX_VERSE_CHARS:
        result["limitations"].append("Verse exceeds 20,000 code points; not checked.")
        return result
    for index, char in enumerate(text):
        if unicodedata.category(char) == "Cs":
            # JSON can encode lone surrogates, but the UTF-8 stdio protocol cannot
            # print them. Keep the diagnostic ASCII-safe and never echo bad text.
            result["limitations"].append(
                f"Isolated Unicode surrogate U+{ord(char):04X} at code-point {index}; verse not checked.")
            return result
    if "\\" in text:
        result["limitations"].append("Inline USFM verse omitted from this text-only pass; use USFM checks.")
        return result
    findings = result["findings"]
    occurrences: Counter[tuple[str, str]] = Counter()

    def add(rule: str, start: int, end: int, message: str, severity: str = "low") -> None:
        if len(findings) >= MAX_VERSE_FINDINGS:
            if "Finding limit reached; additional candidates omitted." not in result["limitations"]:
                result["limitations"].append("Finding limit reached; additional candidates omitted.")
            return
        original = text[start:end]
        occurrences[(rule, original)] += 1
        identity = f"{book}:{chapter}:{verse}:{rule}:{original}:{occurrences[(rule, original)]}"
        findings.append({
            "id": hashlib.sha1(identity.encode("utf-8", errors="surrogatepass")).hexdigest()[:20],
            "book": book, "chapter": chapter, "verse": verse, "rule": rule,
            "severity": severity, "start": start, "end": end,
            "originalText": original, "message": message, "textHash": digest,
            "ruleVersion": RULE_VERSION, "status": "review-needed",
        })

    if not unicodedata.is_normalized("NFC", text):
        # Report a small exact span rather than copying an entire verse into a finding.
        for cluster in GRAPHEME.finditer(text):
            if not unicodedata.is_normalized("NFC", cluster.group()):
                add("unicode.nfc", *cluster.span(), "Canonically equivalent non-NFC text; review project normalization policy.")
    for index, char in enumerate(text):
        category = unicodedata.category(char)
        if char == "\ufffd":
            add("unicode.corruption", index, index + 1, "Replacement character or isolated surrogate; inspect the source encoding.", "high")
        elif category == "Co":
            add("unicode.private-use", index, index + 1, "Private-use character; verify the intended Unicode text.", "medium")
        elif category in {"Cf", "Cc", "Zl", "Zp"}:
            add("unicode.invisible", index, index + 1, f"Review {unicodedata.name(char, 'control character')} (U+{ord(char):04X}); it may be intentional.")
        elif char.isspace() and char != " ":
            add("spacing.unusual", index, index + 1, f"Review unusual space U+{ord(char):04X}; it may be intentional.")
    for match in regex.finditer(r" {2,}|^ +| +$", text):
        add("spacing.extra", *match.span(), "Repeated or edge spaces; check the intended spacing.")
    # Ellipsis and ?! are legitimate style choices, so do not flag them here.
    for match in regex.finditer(r"([,;:!?])\1+", text):
        add("punctuation.repeated", *match.span(), "Repeated punctuation; check project style.")
    for match in regex.finditer(r" +(?:[,;:!?]|\.(?!\.))", text):
        add("punctuation.space-before", *match.span(), "Space before punctuation; check project style.")
    if tamil:
        previous = None
        for word in WORD.finditer(text):
            if previous and text[previous.end():word.start()].isspace() and (
                unicodedata.normalize("NFC", previous.group()) == unicodedata.normalize("NFC", word.group())
            ):
                add("tamil.repeated-word", *word.span(), "Adjacent repeated word; Tamil reduplication may be intentional.")
            previous = word
        for cluster in GRAPHEME.finditer(text):
            normalized = unicodedata.normalize("NFC", cluster.group())
            if any(c in SIGNS and (i == 0 or normalized[i - 1] not in CONSONANTS)
                   for i, c in enumerate(normalized)):
                add("tamil.dependent-sign", *cluster.span(), "Tamil vowel sign or pulli has no valid consonant base, or has conflicting signs.", "high")
        for word in WORD.finditer(text):
            if regex.search(r"\p{Script=Tamil}", word.group()) and regex.search(r"\p{Script=Latin}", word.group()):
                add("tamil.mixed-word", *word.span(), "Tamil and Latin letters occur inside one word; verify intentional mixed text.", "medium")
    return result
