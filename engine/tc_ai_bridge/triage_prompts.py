"""Prompt templates for AI triage of Greek Room findings.

Kept in its own module so the wording can be tuned without touching the
batching/parsing/persistence logic in triage.py — tuning a triage prompt is
expected to be iterative, and every edit here invalidates nothing on disk
(a cached verdict is keyed by the finding's evidence, not by the prompt, so
re-tuning means re-running with force=True, not a migration).

Four families, because the reasoning a reviewer would apply is genuinely
different per family and a single generic prompt scored everything as
"uncertain" in early manual trials:

  mechanical   punctuation, repeated words, digits, quote pairing, script
               and Unicode anomalies. Decidable from the target text alone.
  lexical      does the target wording plausibly render the aligned source
               lemma. Needs the source tokens; the most false-positive-prone
               family, because legitimate idiomatic renderings look wrong to
               a word-for-word reading.
  consistency  the same name/term rendered differently elsewhere in the book.
               A real difference may be correct (case, sandhi, a genuinely
               different referent), so the model must reason about whether
               the variation is meaningful.
  structure    USFM marker/nesting problems. Almost never a false positive
               when the checker is confident, so the prompt says so — the
               model should not manufacture doubt to look useful.
"""
from __future__ import annotations

# Shared preamble. Deliberately states the asymmetry of the cost: hiding a
# real translation error is far worse than leaving a false positive visible,
# and the UI's default threshold (90) assumes the model was told this.
_SHARED = """\
You are triaging automated quality-assurance findings for a Bible translation \
review tool. Each finding was produced by a deterministic checker, not by a \
model. Your only job is to judge how likely each finding is to be a FALSE \
POSITIVE — something the checker flagged that a human reviewer would dismiss \
without changing the translation.

Verdicts:
  "false_positive" — a reviewer would dismiss this; the translation is fine as it stands.
  "true_positive"  — a reviewer would agree something needs attention.
  "uncertain"      — you cannot tell from the evidence given.

Rules:
- Judge only the finding in front of you. Do not re-check the verse for other problems.
- The target language may be one you know poorly. If the evidence does not let you \
judge, say "uncertain" with low confidence. Guessing is worse than abstaining.
- A translation that is idiomatic rather than word-for-word is NOT an error.
- Confidence is 0-100 and expresses how sure you are OF YOUR VERDICT, not how \
severe the finding is.
- Hiding a real error is far more costly than leaving a false positive visible. \
Only give a "false_positive" verdict confidence above 90 when the finding is \
plainly spurious.
- "reason" must be ONE short sentence, under 25 words, in English.

Return STRICT JSON only — no prose, no explanation, no markdown code fences:
{"results": [{"finding_id": "<id>", "verdict": "...", "confidence": 0-100, "reason": "..."}]}
Return exactly one result object per finding given, using the finding_id verbatim.
"""

_MECHANICAL = """\
These findings are mechanical: punctuation, repeated words, stray digits, \
unmatched quotation marks, mixed scripts or unusual Unicode.

Common reasons such a finding is a FALSE POSITIVE:
- The punctuation or quotation convention is correct for this language and \
differs from English (e.g. Devanagari danda, guillemets, CJK marks, no space \
before a colon).
- A "repeated word" is legitimate reduplication, an intensifier, or a \
grammatical construction in this language.
- A "mixed script" flag covers a proper noun, a numeral, or a loanword that \
is conventionally written in another script.
- The digit is a verse-internal number that belongs in the text.

Common reasons it is a TRUE POSITIVE:
- A genuinely doubled word with no grammatical role.
- An unclosed quotation that leaves the speech run on.
- A stray control or replacement character (U+FFFD and friends).
"""

_LEXICAL = """\
These findings concern whether the target wording plausibly renders the \
aligned original-language source words. The source tokens (Hebrew/Greek) and \
their lemmas are given.

Common reasons such a finding is a FALSE POSITIVE:
- The target uses a normal idiomatic or functional equivalent rather than a \
gloss of the lemma.
- The source sense is carried by a different word in the same verse, or is \
grammatically encoded (case, verb morphology) rather than lexicalised.
- The rendering is a standard, established equivalent in this translation tradition.
- A term is implicit in the target because the language does not require it.

Common reasons it is a TRUE POSITIVE:
- The target word denotes a clearly different referent or semantic domain.
- A negation, quantity, participant, or proper name is contradicted or dropped.

You are judging PLAUSIBILITY, not preferring a specific rendering. If a \
competent translator could defend the target wording, it is a false positive.
"""

_CONSISTENCY = """\
These findings report that a name or term is rendered differently here than \
elsewhere in the book.

Common reasons such a finding is a FALSE POSITIVE:
- The difference is inflectional — case, number, possession, agglutinative \
suffixes, sandhi, or construct state. Many languages inflect proper nouns.
- The two occurrences refer to different people, places, or things that share \
a source spelling.
- One occurrence is inside a quotation, title, or genealogy with its own convention.
- The variation is an accepted orthographic alternate.

Common reasons it is a TRUE POSITIVE:
- The same referent is spelled two genuinely unrelated ways.
- One spelling looks like a typo of the other (transposition, dropped character).
"""

_STRUCTURE = """\
These findings come from the USFM structural checker: marker syntax, nesting, \
required attributes, chapter/verse numbering.

The structural checker is precise and rarely wrong about syntax. Default to \
"true_positive" unless the evidence positively shows otherwise. Do not \
manufacture doubt.

Legitimate reasons such a finding is a FALSE POSITIVE:
- The marker is valid USFM 3.x that the checker's rule set does not know.
- The construct is a documented publisher extension.
- The flag is about optional whitespace or formatting with no effect on the text.
"""

FAMILY_INSTRUCTIONS: dict[str, str] = {
    "mechanical": _MECHANICAL,
    "lexical": _LEXICAL,
    "consistency": _CONSISTENCY,
    "structure": _STRUCTURE,
}

FAMILIES = tuple(FAMILY_INSTRUCTIONS)

DEFAULT_FAMILY = "mechanical"

# check_type prefix -> family, matched longest-prefix-first on the
# lowercased check_type. These are the dotted check_types the Greek Room
# adapters actually emit, verified against the code rather than assumed:
#   usfm.<slug>                       usfm_adapter.py:277
#   wildebeest.notable_token,
#   wildebeest.non_canonical,
#   wildebeest.zero_width,
#   wildebeest.script.mixed           wildebeest_adapter.py:148-224
#   names.spelling_similarity         names_adapter.py:368
#   alignment.inconsistent_rendering  bridge_service.py:2716
_CHECK_TYPE_PREFIXES: tuple[tuple[str, str], ...] = (
    ("usfm.", "structure"),
    ("wildebeest.", "mechanical"),
    ("names.", "consistency"),
    # Corpus-statistics finding: one source word with several target
    # renderings and no dominant one. Judging it means judging whether every
    # rendering is defensible for that lemma, which is the lexical question,
    # and it is the one family that genuinely needs the source tokens.
    ("alignment.", "lexical"),
)

# tc_ai_bridge/local_checks.py builds QAIssue codes rather than dotted
# check_types, and bridge_service uses `issue.check_id or issue.code` as the
# check_type (bridge_service.py:213). The editorial codes carry a *variable*
# language prefix (TA_/LANG_, local_checks.py:45), so these match on a
# substring, not a prefix.
_CHECK_TYPE_CONTAINS: tuple[tuple[str, str], ...] = (
    ("_repeat_word", "mechanical"),
    ("_double_space", "mechanical"),
    ("_hidden_char", "mechanical"),
    ("usfm_balance", "structure"),
    # ALIGN_DUP_TOP / ALIGN_OCCURRENCE / ALIGN_TARGET_MISMATCH and friends are
    # alignment *data integrity*, not lexical judgement — a duplicated token
    # or bad occurrence metadata is decided by inspecting the structure.
    ("align_", "structure"),
)

# QaFinding.category -> family, used when the check_type matched nothing.
_CATEGORY_FAMILIES: dict[str, str] = {
    "structure": "structure",
    "unicode": "mechanical",
    "repetition": "mechanical",
    "spelling": "consistency",
    "names": "consistency",
    "consistency": "consistency",
    "alignment": "lexical",
    "omission_addition": "lexical",
}


def family_for(check_type: str, category: str = "") -> str:
    """Route one finding to a prompt family.

    check_type wins over category: every Wildebeest check carries category
    "unicode" (wildebeest_adapter.py:196) whatever it actually looked at, so
    the category alone would route a mixed-script check and a punctuation
    check identically and would never reach the consistency prompt at all.
    """
    check = str(check_type or "").strip().lower()
    if check:
        best = ""
        family = ""
        for prefix, candidate in _CHECK_TYPE_PREFIXES:
            if check.startswith(prefix) and len(prefix) > len(best):
                best, family = prefix, candidate
        if family:
            return family
        for needle, candidate in _CHECK_TYPE_CONTAINS:
            if needle in check:
                return candidate
    return _CATEGORY_FAMILIES.get(str(category or "").strip().lower(), DEFAULT_FAMILY)


def instructions_for(family: str) -> str:
    """The full system instructions sent for one batch of `family` findings."""
    detail = FAMILY_INSTRUCTIONS.get(family, FAMILY_INSTRUCTIONS[DEFAULT_FAMILY])
    return f"{_SHARED}\n{detail}"
