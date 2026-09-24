"""Small offline target-text checks. No dictionaries, source judgments or writes.

Raw code-point spans always refer to the input, never its normalized copy.
Unicode Tamil §12.6 permits decomposed two-part vowels and Grantha conjuncts.
"""
from __future__ import annotations

import hashlib
import unicodedata
from collections import Counter
from dataclasses import dataclass
from typing import Any

import regex

from .usfm import marker_balance_issues

RULE_VERSION = "language-qa-6"
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
# Part B1/B2/B3/B4: closed-class வல்லினம் மிகுதல் environments only -- a
# demonstrative (B1: அந்த/இந்த/எந்த), a manner-adverb (B2: அப்படி/இப்படி/
# எப்படி), an explicit fourth-case/dative (B3: நான்காம் வேற்றுமை விரி --
# எனக்கு/உங்களுக்கு/தேவனுக்கு), or an explicit second-case/accusative
# (B4: இரண்டாம் வேற்றுமை விரி -- என்னை/உங்களை/அவனை/அதை/எதை) followed by a
# க/ச/த/ப-initial word. Deliberately not general sandhi -- see
# docs/BUILD_LOG.md's dated entries for each bounded rule statement this
# mirrors. All four trigger sets share this one mechanism on purpose (same
# tokenizer, same exact-match-against-the-bare-trigger-token, same
# whitespace-only-adjacency and initial-consonant-class checks below) -- not
# four parallel rule engines. Exact-match against the bare trigger form is
# also what keeps this from firing on a token that already carries the
# linking consonant (e.g. "அப்படிக்" tokenizes as one word, not equal to
# "அப்படி") or on a longer word that merely contains a trigger as a prefix
# (அப்படித்தான், இப்படியும், எப்படியோ, எனக்குள்ளே, அதைவிட, ...) -- no separate
# exclusion list needed for any case.
#
# B3 is deliberately an allowlist of explicitly verified dative *surface
# forms*, not a suffix rule (`token.endswith("க்கு")`) -- ordinary Tamil
# lexical words can themselves end in க்கு without being a fourth-case form,
# and Bridge has no morphological analyzer to tell the difference reliably.
# Add a new dative form only when its case analysis is independently
# verified, the same discipline that gated B1/B2's own trigger words.
# Explicitly out of scope for B3: -உடைய (genitive; standard modern Tamil
# does *not* geminate after உடைய -- the opposite direction from B1/B2/B3/B4, and
# a candidate future "excess வல்லினம்" rule, never folded into this one),
# எல்லா (not a case marker; ungated, no rule statement exists yet), any other
# case suffix, compounds, inferred/hidden fourth-case தொகை forms, and general
# words that merely end in க்கு or ஐ.
#
# B4: explicit accusative (இரண்டாம் வேற்றுமை விரி, -ஐ) surface forms, same
# allowlist discipline as B3 -- a fixed list of pronoun forms verified as
# genuine accusative case, not a suffix rule (ordinary nouns/participles can
# end in bare ஐ without being this case -- e.g. பரிசை "the prize",
# அனுப்பப்பட்டவைகளை "the things sent" are real, confirmed bare-boundary
# violations in Philippians too, but are excluded from B4 because they need
# a noun/participle recognizer Bridge doesn't have, not just an allowlist
# lookup). Confirmed real violation: php 2:28 அவனை சீக்கிரமாக (bare).
VALLINAM_TRIGGERS = frozenset({
    "அந்த", "இந்த", "எந்த", "அப்படி", "இப்படி", "எப்படி",
    "எனக்கு", "உங்களுக்கு", "தேவனுக்கு",
    "என்னை", "உங்களை", "அவனை", "அதை", "எதை",
})
VALLINAM_INITIALS = frozenset("கசதப")
# The rules whose findings are drawn inline in the verse text, as opposed to
# listed only in the Language QA panel. The one authority for that choice:
# languageQa.inline filters on it server-side and languageQa.status exposes it.
# highlight.ts's INLINE_LANGUAGE_QA_MARKS only maps these names to CSS classes
# and must have exactly these keys (test_inline_rules_match_the_frontend_class_map).
INLINE_RULES = frozenset({"terminology.deprecated-form", "tamil.vallinam-missing"})
# Every Language QA finding carries this, and the frontend sends it back in the
# `issue` of a verse.decide call. decide_verse keys on it to keep Language QA
# decisions out of the review-progress rollup. Origin is never inferred from
# the finding id.
FINDING_SOURCE = "languageQa"
# What decide_verse records as `issue.source` when its caller names none, so a
# new non-Language-QA decision is distinguishable from a legacy row that has no
# source key (language_qa_jobs._may_concern_language_qa).
UNSPECIFIED_DECISION_SOURCE = "unspecified"
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


def stable_finding_id(book: str, chapter: str, verse: str, rule: str,
                       original: str, occurrence: int) -> str:
    """The one id formula every Language QA finding uses -- deterministic
    across re-scans of unchanged text. `occurrence` disambiguates repeats of
    the same (rule, original) pair within whatever the caller's scope is
    (one verse for scan_text's own rules; also one verse for terminology
    matches, counted independently per verse by the caller)."""
    identity = f"{book}:{chapter}:{verse}:{rule}:{original}:{occurrence}"
    return hashlib.sha1(identity.encode("utf-8", errors="surrogatepass")).hexdigest()[:20]


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


# Same note shape as the frontend's parseVerseNotes (src/lib/utils/usfmNotes.ts
# NOTE_RE): \f or \x, whitespace, then everything up to the matching closer.
_NOTE = regex.compile(r"\\([fx])\s.*?\\\1\*", regex.DOTALL)
_NOTE_FAMILY = regex.compile(r"\\(?!fig\b)[fx][A-Za-z]*\b")  # \fig is a figure, not a note
# USFM 3 attributes (`\w word|lemma="..."\w*`, a milestone's `|who="..."\*`):
# the bar up to the closing marker is not visible text.
_ATTRIBUTES = regex.compile(r"\|[^\\]*(?=\\(?:\+?[A-Za-z0-9_-]+)?\*)")
# Any other marker token: character markers (\wj, \add, \nd, \qt, \w, nested
# \+nd ...), their closers, and a milestone's bare `\*`. Group 1 is the
# closer's star; group 2 an opener's one following space, which belongs to the
# marker syntax.
_MARKER = regex.compile(r"\\(?:\+?[A-Za-z0-9_-]+(\*)?|(\*))( )?")
CROSSING_LIMITATION = "candidate(s) spanning inline USFM markup omitted."


@dataclass(frozen=True)
class LiftedVerse:
    """A verse with its inline USFM lifted out, and where every kept code
    point came from. The visible text is built by deletion only, never by
    rewriting or reordering, so a span of it that does not cross lifted
    markup is byte-identical to the raw span it maps to."""
    visible: str
    raw_index: tuple[int, ...]  # raw_index[i] is the raw offset of visible[i]

    def raw_span(self, start: int, end: int) -> tuple[int, int] | None:
        """Raw half-open span for visible[start:end], or None when that span
        crosses lifted markup (it would not be one contiguous piece of raw text)."""
        if not 0 <= start < end <= len(self.visible):
            return None
        raw_start, raw_end = self.raw_index[start], self.raw_index[end - 1] + 1
        return (raw_start, raw_end) if raw_end - raw_start == end - start else None


def lift_inline_usfm(raw: str) -> tuple[LiftedVerse | None, str]:
    """The text a reader sees, for Language QA to scan: footnotes and
    cross-references removed with their contents (the frontend's
    parseVerseNotes, including its swallow-one-space rule), then character
    markers removed but their content kept, and word attributes dropped.

    Returns (None, reason) instead of guessing when the markup cannot be lifted
    safely: unbalanced paired markers (usfm.marker_balance_issues), note markup
    outside a complete note, or a backslash that is not a marker."""
    issues = marker_balance_issues(raw)
    if issues:
        return None, f"{'; '.join(issues)}; verse not checked."
    removed = bytearray(len(raw))

    def remove(start: int, end: int) -> None:
        removed[start:end] = b"\x01" * (end - start)

    for match in _NOTE.finditer(raw):
        start, end = match.span()
        # Removing a note between two spaces would leave a double space behind.
        if start == 0 or raw[start - 1].isspace():
            if end < len(raw) and raw[end].isspace():
                end += 1
        elif end == len(raw) and raw[start - 1].isspace():
            start -= 1
        remove(start, end)
    for match in _NOTE_FAMILY.finditer(raw):
        if not removed[match.start()]:
            return None, ("Footnote or cross-reference markup outside a complete "
                          "\\f … \\f* or \\x … \\x* note; verse not checked.")
    for match in _ATTRIBUTES.finditer(raw):
        if not removed[match.start()]:
            remove(*match.span())
    for match in _MARKER.finditer(raw):
        if removed[match.start()]:
            continue
        end = match.end()
        if match.group(3) and (match.group(1) or match.group(2)):
            end -= 1  # the space after a closer is text, not marker syntax
        remove(match.start(), end)
    index = tuple(i for i in range(len(raw)) if not removed[i])
    visible = "".join(raw[i] for i in index)
    stray = visible.find("\\")
    if stray != -1:
        return None, f"Backslash that is not a USFM marker at code-point {index[stray]}; verse not checked."
    # Attributes whose marker never closes properly (seen for real: a custom
    # `\zsem-s |x-note="..."*` milestone ending in a bare `*`) would otherwise
    # leak glosses, Greek and notes into the "visible" text and be scanned as
    # Scripture.
    bar = visible.find("|")
    if bar != -1:
        return None, (f"Word attributes not closed by a USFM marker at code-point {index[bar]}; "
                      "verse not checked.")
    return LiftedVerse(visible, index), ""


def scan_text(text: str, *, book: str, chapter: str, verse: str,
              tamil: bool) -> dict[str, Any]:
    """Every rule runs on the verse's visible text (lift_inline_usfm); every
    finding's start/end/originalText is exact raw code points, so
    originalText == text[start:end]. A candidate that would cross lifted
    markup is dropped and counted as a limitation. `checked` is False only
    when the verse was not scanned at all."""
    digest = text_hash(text)
    result: dict[str, Any] = {"textHash": digest, "findings": [], "limitations": [], "checked": False}
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
    lifted, reason = lift_inline_usfm(text)
    if lifted is None:
        result["limitations"].append(reason)
        return result
    result["checked"] = True
    raw, text = text, lifted.visible  # every rule below reads the visible text
    findings = result["findings"]
    occurrences: Counter[tuple[str, str]] = Counter()
    crossing = 0

    def add(rule: str, start: int, end: int, message: str, severity: str = "low",
            suggested_replacement: str | None = None) -> None:
        nonlocal crossing
        span = lifted.raw_span(start, end)
        if span is None:
            crossing += 1
            return
        if len(findings) >= MAX_VERSE_FINDINGS:
            if "Finding limit reached; additional candidates omitted." not in result["limitations"]:
                result["limitations"].append("Finding limit reached; additional candidates omitted.")
            return
        raw_start, raw_end = span
        original = raw[raw_start:raw_end]
        occurrences[(rule, original)] += 1
        findings.append({
            "id": stable_finding_id(book, chapter, verse, rule, original, occurrences[(rule, original)]),
            "book": book, "chapter": chapter, "verse": verse, "rule": rule,
            "severity": severity, "start": raw_start, "end": raw_end,
            "originalText": original, "message": message, "textHash": digest,
            "ruleVersion": RULE_VERSION, "status": "review-needed",
            "suggestedReplacement": suggested_replacement, "source": FINDING_SOURCE,
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
            if previous and text[previous.end():word.start()].isspace():
                prev_norm = unicodedata.normalize("NFC", previous.group())
                word_norm = unicodedata.normalize("NFC", word.group())
                if prev_norm == word_norm:
                    add("tamil.repeated-word", *word.span(), "Adjacent repeated word; Tamil reduplication may be intentional.")
                if prev_norm in VALLINAM_TRIGGERS and word_norm[:1] in VALLINAM_INITIALS:
                    initial = word_norm[0]
                    corrected = f"{prev_norm}{initial}்"
                    # The suggested fix is the whole flagged span with only the
                    # linking consonant inserted -- the raw trigger text and
                    # everything after it (original whitespace, the following
                    # word exactly as written) are preserved untouched.
                    replacement = (
                        text[previous.start():previous.end()] + initial + "்"
                        + text[previous.end():word.end()]
                    )
                    add("tamil.vallinam-missing", previous.start(), word.end(),
                        f'Possible missing வல்லினம் at this word boundary: "{prev_norm} {initial}..." '
                        f'normally takes "{corrected} {initial}...". Verify before editing.',
                        "medium", suggested_replacement=replacement)
            previous = word
        for cluster in GRAPHEME.finditer(text):
            normalized = unicodedata.normalize("NFC", cluster.group())
            if any(c in SIGNS and (i == 0 or normalized[i - 1] not in CONSONANTS)
                   for i, c in enumerate(normalized)):
                add("tamil.dependent-sign", *cluster.span(), "Tamil vowel sign or pulli has no valid consonant base, or has conflicting signs.", "high")
        for word in WORD.finditer(text):
            if regex.search(r"\p{Script=Tamil}", word.group()) and regex.search(r"\p{Script=Latin}", word.group()):
                add("tamil.mixed-word", *word.span(), "Tamil and Latin letters occur inside one word; verify intentional mixed text.", "medium")
    if crossing:
        result["limitations"].append(f"{crossing} {CROSSING_LIMITATION}")
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
            "source": FINDING_SOURCE,
        })
        if len(findings) >= MAX_WORDLIST_FINDINGS:
            break
    return findings
