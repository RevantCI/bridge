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
# Whole-book wordlist audit (item 49). Rarity/frequency constants below are an
# unvalidated starting point (mirroring bridge_service.py's
# _CONSISTENCY_MIN_OCCURRENCES/_MIN_RENDERINGS/_DOMINANCE_THRESHOLD) -- measure
# false-positive rate against a real, previously-reviewed Tamil book before
# trusting these defaults. Rarity or spelling similarity alone are never
# findings; both must hold together (docs/LANGUAGE_QA_PLAN.md's LQA-2 row).
MAX_WORDLIST_TERMS = 20_000
WORDLIST_MIN_LENGTH = 4
WORDLIST_RARE_MAX = 2
WORDLIST_COMMON_MIN = 6
WORDLIST_RATIO_MIN = 5
MAX_WORDLIST_FINDINGS = 200
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


def word_occurrences(text: str) -> list[tuple[str, int, int]]:
    """NFC-normalized (word, start, end) triples; spans are raw offsets into
    `text`. Same tokenizer as tamil.repeated-word -- do not add a second one."""
    return [(unicodedata.normalize("NFC", m.group()), *m.span()) for m in WORD.finditer(text)]


def _deletion_neighbors(word: str) -> list[str]:
    return [word[:i] + word[i + 1:] for i in range(len(word))]


def wordlist_findings(book: str, counts: dict[str, int],
                       first_seen: dict[str, tuple[str, str, int, int, str, str]],
                       ) -> list[dict[str, Any]]:
    """Pure function, no I/O. `first_seen` maps a normalized word to
    (chapter, verse, start, end, originalText, textHash) for its first
    occurrence in book-walk order. Flags a rare word only when it is also an
    edit-distance-1 near-duplicate (including a single pulli insertion/
    deletion, which is just an ordinary edit-distance-1 case here) of a much
    more common word in the same book -- rarity alone and spelling similarity
    alone are never findings on their own.
    """
    words = [w for w in counts if len(w) >= WORDLIST_MIN_LENGTH]
    word_set = set(words)
    candidates: dict[str, set[str]] = {}

    def link(a: str, b: str) -> None:
        candidates.setdefault(a, set()).add(b)
        candidates.setdefault(b, set()).add(a)

    # Same-length substitutions: two words that reduce to the same string when
    # the same relative letter is deleted from each share a deletion-neighbor
    # bucket. Every entry in one bucket has the same length by construction
    # (a word's deletion-neighbors are always exactly one codepoint shorter).
    buckets: dict[str, list[str]] = {}
    for word in words:
        for neighbor in _deletion_neighbors(word):
            buckets.setdefault(neighbor, []).append(word)
    for group in buckets.values():
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                link(a, b)
    # Insertion/deletion pairs (including a single pulli inserted or dropped):
    # a word's own deletion-neighbor that happens to itself be a real word in
    # this book is a direct edit-distance-1 match, no bucket needed.
    for word in words:
        for neighbor in _deletion_neighbors(word):
            if neighbor in word_set:
                link(word, neighbor)
    findings: list[dict[str, Any]] = []
    for rare in sorted(candidates):
        rare_count = counts[rare]
        if rare_count > WORDLIST_RARE_MAX:
            continue
        common_options = [w for w in candidates[rare]
                          if counts[w] >= WORDLIST_COMMON_MIN
                          and counts[w] >= rare_count * WORDLIST_RATIO_MIN]
        if not common_options:
            continue
        # Deterministic tie-break: most frequent common match, then lexical order.
        common = sorted(common_options, key=lambda w: (-counts[w], w))[0]
        chapter, verse, start, end, original, text_hash = first_seen[rare]
        identity = f"{book}:tamil.wordlist-variant:{rare}:{common}"
        findings.append({
            "id": hashlib.sha1(identity.encode("utf-8", errors="surrogatepass")).hexdigest()[:20],
            "book": book, "chapter": chapter, "verse": verse, "rule": "tamil.wordlist-variant",
            "severity": "low", "start": start, "end": end, "originalText": original,
            "message": (f'"{rare}" occurs {rare_count} time(s) in this book; "{common}" '
                        f'(a similar spelling) occurs {counts[common]} times here -- verify '
                        f'whether this is a spelling variant or a distinct word/name.'),
            "textHash": text_hash, "ruleVersion": RULE_VERSION, "status": "review-needed",
        })
        if len(findings) >= MAX_WORDLIST_FINDINGS:
            break
    return findings
