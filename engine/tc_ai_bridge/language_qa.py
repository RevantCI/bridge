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

RULE_VERSION = "language-qa-7"
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
# The வல்லினம் rules (B1–B4 and those added since) are data, not code: the
# bundled `ta-irv` rule pack (language_packs/ta-irv/), whose matchers are
# compiled and whose examples run as tests at load (layered-rules Phase 3).
# The B1–B4 trigger lists this file used to hold, and the scope reasoning
# behind each, are in docs/BUILD_LOG.md's dated entries and in each rule's
# `provenance`.
#
# The non-pack rules drawn inline in the verse text (a pack rule carries its
# own `inline`). The engine alone decides: every finding carries `inline`,
# languageQa.inline filters on it, and languageQa.status lists the drawn rule
# names. The frontend only styles a finding by its category.
INLINE_RULES = frozenset({"terminology.deprecated-form"})
# Every Language QA finding carries this, and the frontend sends it back in the
# `issue` of a verse.decide call. decide_verse keys on it to keep Language QA
# decisions out of the review-progress rollup. Origin is never inferred from
# the finding id.
FINDING_SOURCE = "languageQa"
# What decide_verse records as `issue.source` when its caller names none, so a
# new non-Language-QA decision is distinguishable from a legacy row that has no
# source key (language_qa_jobs._may_concern_language_qa).
UNSPECIFIED_DECISION_SOURCE = "unspecified"


@dataclass(frozen=True)
class RuleMeta:
    """What a finding says about the rule that produced it (layered-rules
    brief, Phase 1.1). `pack` qualifies `ruleId`: "common" for the
    language-independent integrity checks, "ta-irv" for the Tamil rules,
    "project" for the project's own house-style data. `revision` is the
    rule's own version, bumped only when that rule's matching changes;
    together with PACK_VERSION it decides when an old "ignored" decision
    stops applying (Phase 1.5). `confidence` is a categorical label, not a
    calibrated probability, and is provisional until the Phase 2 benchmark
    measures each rule."""
    pack: str
    layer: str       # "pattern" | "lexicon" | "housestyle" | "integrity"
    category: str    # "typo" | "sandhi" | "word-joining" | "punctuation" | "unicode" | "spacing" | "termbase" | "name"
    confidence: str  # "high" | "medium" | "low"
    revision: int = 1


LAYERS = ("pattern", "lexicon", "housestyle", "integrity")
# highlight.ts's LANGUAGE_QA_CATEGORY_MARKS must have exactly these keys
# (test_category_marks_match_the_engine).
CATEGORIES = ("typo", "sandhi", "word-joining", "punctuation", "unicode", "spacing", "termbase", "name")
CONFIDENCES = ("high", "medium", "low")

RULES: dict[str, RuleMeta] = {
    "unicode.nfc": RuleMeta("common", "integrity", "unicode", "low"),
    "unicode.corruption": RuleMeta("common", "integrity", "unicode", "high"),
    "unicode.private-use": RuleMeta("common", "integrity", "unicode", "medium"),
    "unicode.invisible": RuleMeta("common", "integrity", "unicode", "low", revision=2),  # 2: line breaks no longer reported
    "spacing.unusual": RuleMeta("common", "integrity", "spacing", "low", revision=2),    # same change
    "spacing.extra": RuleMeta("common", "integrity", "spacing", "medium"),
    "punctuation.repeated": RuleMeta("common", "integrity", "punctuation", "medium"),
    "punctuation.space-before": RuleMeta("common", "integrity", "punctuation", "medium"),
    "tamil.repeated-word": RuleMeta("ta-irv", "pattern", "typo", "low"),
    "tamil.dependent-sign": RuleMeta("ta-irv", "integrity", "unicode", "high"),
    "tamil.mixed-word": RuleMeta("ta-irv", "integrity", "typo", "medium"),
    "tamil.wordlist-variant": RuleMeta("ta-irv", "lexicon", "typo", "low"),
    "terminology.deprecated-form": RuleMeta("project", "housestyle", "termbase", "high"),
}
# The version of the rules above, which live in code. A pack rule's findings
# carry the pack's own version instead ("ta-irv@1.0.0") and the rule's own
# version as ruleRevision.
PACK_VERSION = RULE_VERSION
MAX_SUGGESTIONS = 5


def suggestion(text: str, source: str, rationale: str, rank: int = 1) -> dict[str, Any]:
    """One ranked fix. `source` is "rule" | "lexicon" | "termbase" |
    "majority-form" | "housestyle"; `rationale` is shown as the menu item's tooltip."""
    return {"text": text, "rank": rank, "source": source, "rationale": rationale}


def rule_fields(rule: str, suggestions: list[dict[str, Any]] | None = None, *,
                pack: Any = None, pack_rule: Any = None) -> dict[str, Any]:
    """The Phase 1.1 finding fields every producer shares (scan_text's
    add(), the terminology pass, the wordlist audit). A pack rule's fields
    come from the pack (`pack`, `pack_rule`); every other rule's from RULES.
    `rule` and `suggestedReplacement` stay as aliases for one release:
    suggestedReplacement is suggestions[0].text, or None."""
    ranked = [dict(s, rank=i) for i, s in enumerate((suggestions or [])[:MAX_SUGGESTIONS], start=1)]
    if pack_rule is not None:
        fields = {
            "layer": pack_rule.layer, "category": pack_rule.category, "confidence": pack_rule.confidence,
            "ruleId": f"{pack.name}/{pack_rule.id}", "packVersion": pack.pack_version,
            "ruleRevision": pack_rule.version, "inline": pack_rule.inline,
        }
    else:
        meta = RULES[rule]
        fields = {
            "layer": meta.layer, "category": meta.category, "confidence": meta.confidence,
            "ruleId": f"{meta.pack}/{rule}", "packVersion": PACK_VERSION,
            "ruleRevision": meta.revision, "inline": rule in INLINE_RULES,
        }
    return {"source": FINDING_SOURCE, **fields, "suggestions": ranked,
            "suggestedReplacement": ranked[0]["text"] if ranked else None}


def inline_rule_names(pack: Any = None) -> list[str]:
    """The `rule` names drawn inline: the non-pack INLINE_RULES plus every
    enabled inline rule of the pack (default: the bundled ta-irv pack)."""
    if pack is None:
        from .language_packs import default_pack
        pack = default_pack()
    return sorted(INLINE_RULES | {r.name for r in pack.rules if r.enabled and r.inline})


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
# Chapter JSON keeps a verse's USFM line structure: poetry is stored as
# "…;\n\q நான் …\n\q". In USFM a line break is whitespace, so it is never
# reported as a control or unusual-space character. It still separates words,
# as any whitespace does. Reporting it flooded IRV Psalms with 2,977 false
# findings that filled the book cap by chapter 87.
USFM_LINE_BREAKS = frozenset("\n\r")


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
              tamil: bool, pack: Any = None, lists: dict[str, frozenset] | None = None) -> dict[str, Any]:
    """Every rule runs on the verse's visible text (lift_inline_usfm); every
    finding's start/end/originalText is exact raw code points, so
    originalText == text[start:end]. A candidate that would cross lifted
    markup is dropped and counted as a limitation. `checked` is False only
    when the verse was not scanned at all.

    For Tamil, the rule pack (`pack`, default: the bundled ta-irv pack,
    loaded on first use) contributes its token-context and regex rules;
    `lists` resolves its `listRef`s (house-style lists, empty until Phase 6)."""
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
            suggestions: list[dict[str, Any]] | None = None, *, pack_rule: Any = None,
            raw_offsets: bool = False) -> None:
        nonlocal crossing
        span = (start, end) if raw_offsets else lifted.raw_span(start, end)
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
            "ruleVersion": f"{pack.pack_version}#{pack_rule.version}" if pack_rule is not None else RULE_VERSION,
            "status": "review-needed",
            **rule_fields(rule, suggestions, pack=pack, pack_rule=pack_rule),
        })

    def add_candidate(candidate: Any) -> None:
        pack_rule = candidate.rule
        add(pack_rule.name, candidate.start, candidate.end, candidate.message, pack_rule.severity,
            [suggestion(candidate.replacement, "rule", candidate.rationale)] if candidate.replacement else [],
            pack_rule=pack_rule, raw_offsets=candidate.raw)

    if tamil and pack is None:
        from .language_packs import default_pack  # loaded once, on first Tamil scan
        pack = default_pack()
    lists = lists or {}

    if not unicodedata.is_normalized("NFC", text):
        # Report a small exact span rather than copying an entire verse into a finding.
        for cluster in GRAPHEME.finditer(text):
            if not unicodedata.is_normalized("NFC", cluster.group()):
                add("unicode.nfc", *cluster.span(), "Canonically equivalent non-NFC text; review project normalization policy.")
    for index, char in enumerate(text):
        if char in USFM_LINE_BREAKS:
            continue  # USFM line structure, i.e. whitespace -- not a control character in the text
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
                # The pack's word-pair rules (வல்லினம் and the rest). A fix is
                # the whole flagged span with only the linking consonant
                # changed; the raw words and whitespace are kept as written.
                for candidate in pack.pair_candidates(text, previous, word, lists):
                    add_candidate(candidate)
            previous = word
        for candidate in pack.regex_candidates(text, raw):
            add_candidate(candidate)
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
            **rule_fields("tamil.wordlist-variant"),
        })
        if len(findings) >= MAX_WORDLIST_FINDINGS:
            break
    return findings
