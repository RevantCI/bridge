"""Stage 6B location evidence from completed translationCore Word Alignment.

V11-000a. Projects same-verse tC alignment groups into the same
`{"sourceTokenInstanceIds": [...], "targetTokenInstanceIds": [...]}` shape
`human_approved_lexical_precedents()` already returns, so
`SemanticLocationEngine._score_candidate` can score a WORD_ALIGNMENT
component the same way it scores HUMAN_PRECEDENT -- see
`docs/V11-000_STAGE6B_ALIGNMENT_SPIKE.md` for the full investigation this
implements.

Read-only, in one direction only: nothing here ever writes to
`.apps/translationCore/alignmentData/` or the `tools/wordAlignment/`
completion markers. A token that cannot be matched to a stored Bridge
identity unambiguously drops that one alignment group from the evidence
(costing a NOT_LOCATED, today's status quo without this evidence) rather
than being guessed at -- a wrong group would confidently mislocate a
finding, which is worse than the gap this closes.

Scope: same-verse source->target links only. A tC alignment group stored
under a verse-bridge key ("3-4") is out of scope for this pass -- deciding
which individual verse each of its tokens belongs to is itself an
unresolved-or-guess problem, so those verses simply contribute no alignment
evidence rather than being split heuristically.
"""
from __future__ import annotations

import unicodedata
from typing import Any

from .lexicon_resources import normalize_strong
from .models import TokenRef, VerseAlignment
from .original_language_resources import OriginalLanguageResource, source_tokens_for_verse
from .source_semantic_inventory import source_token_identity

ALIGNMENT_EVIDENCE_VERSION = "tc-word-alignment-v1"


def _norm(value: str) -> str:
    return unicodedata.normalize("NFC", str(value or "")).casefold().strip()


def resolve_source_token_id(
    resource: OriginalLanguageResource, book: str, chapter: str, verse: str, ref: TokenRef,
) -> str | None:
    """Match a tC `topWord` onto the pinned UHB/UGNT pack's own token identity.

    Matching is conservative, following
    `semantic_alignment_guard.alignment_top_ids_for_canonical_tokens`: exact
    NFC word + occurrence is required, lemma/Strong's/morph only reinforce a
    tie among candidates that already satisfy it. `raw` tokens come from the
    pack itself, never from `ref` -- an NFD-normalized tC entry must not be
    fed into the identity hash directly, or it mints a different id than the
    one Stage 5 already stored.
    """
    raw_tokens = source_tokens_for_verse(book, chapter, verse)
    if not raw_tokens:
        return None
    target_word = _norm(ref.word)
    target_occurrence = int(ref.occurrence or 1)
    if not target_word:
        return None
    candidates: list[tuple[int, int]] = []
    for index, raw in enumerate(raw_tokens):
        if _norm(str(raw.get("word") or "")) != target_word:
            continue
        if int(raw.get("occurrence") or 1) != target_occurrence:
            continue
        score = 10
        if ref.lemma and _norm(str(raw.get("lemma") or "")) == _norm(ref.lemma):
            score += 3
        raw_strong = normalize_strong(str(raw.get("strong") or ""), resource.language_id)
        ref_strong = normalize_strong(ref.strong, resource.language_id) if ref.strong else None
        if ref_strong and raw_strong and ref_strong == raw_strong:
            score += 3
        if ref.morph and str(raw.get("morph") or "") == ref.morph:
            score += 1
        candidates.append((score, index))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    best_score = candidates[0][0]
    best = [index for score, index in candidates if score == best_score]
    if len(best) != 1:
        return None
    index = best[0]
    _, instance_id, _ = source_token_identity(resource, book, chapter, verse, index, raw_tokens[index])
    return instance_id


def resolve_target_token_id(
    *, project_id: str, book: str, displayed_reference: str, text_revision: str,
    current_text: str, profile: str, ref: TokenRef,
) -> str | None:
    """Match a tC `bottomWord` onto a fresh retokenization of the current verse.

    tC's own tokenization and Bridge's `bridge-unicode-word-v1` genuinely
    disagree (whitespace + edge-trimmed punctuation vs. Unicode-word regex
    with punctuation as its own token), so a `bottomWord`'s
    (normalizedForm, occurrence) pair is a *candidate* bound to this exact
    `text_revision`, never an identity. Anything but exactly one match --
    including an occurrences-total mismatch, which signals the two
    tokenizations disagree about this verse -- returns unresolved.
    """
    from .passage_semantic_runtime import target_token_identity, tokenize_target_text

    target_word = _norm(ref.word)
    if not target_word:
        return None
    tokens = tokenize_target_text(current_text, profile)
    exact = [
        token for token in tokens
        if _norm(token["normalized"]) == target_word
        and token["occurrence"] == int(ref.occurrence or 1)
        and token["occurrences"] == int(ref.occurrences or 1)
    ]
    if len(exact) != 1:
        return None
    _, instance_id, _ = target_token_identity(
        project_id, book, displayed_reference, text_revision, profile, exact[0],
    )
    return instance_id


def _reference_chapter_verse(displayed_reference: str) -> tuple[str, str] | None:
    _, separator, location = displayed_reference.rpartition(" ")
    if not separator or ":" not in location:
        return None
    chapter, _, verse = location.partition(":")
    return chapter, verse


def _duplicated_signatures(alignment: VerseAlignment) -> tuple[set[str], set[str]]:
    """Signatures appearing in more than one group -- DUPLICATE_ACTIVE_TOKEN_MEMBERSHIP.

    Same check `local_checks.alignment_integrity_checks` already runs (there,
    to raise ALIGN_DUP_TOP/ALIGN_DUP_BOTTOM); reused here rather than
    re-walked, so a verse already flagged as ambiguous by that QA check never
    quietly becomes location evidence.
    """
    from collections import Counter
    top_counts = Counter(t.signature for t in alignment.all_top())
    bottom_counts = Counter(t.signature for t in alignment.aligned_bottom())
    return (
        {sig for sig, n in top_counts.items() if n > 1},
        {sig for sig, n in bottom_counts.items() if n > 1},
    )


def alignment_evidence_digest(runtime: Any) -> str:
    """Everything that can change what alignment_precedents_for_range finds:
    alignment content AND completion/invalid markers (`alignment_state_digest`
    -- not the content-only digest the legacy compatibility scan memoizes
    against, since `complete_alignment()` can flip completion state with no
    content byte changing, and that alone changes this evidence).

    Stage 6B's run fingerprint (semantic_location.py) must be sensitive to
    the exact same thing `PassageSemanticRuntime.synchronize_alignment_state`
    stales on, or a completion-only change would stale an old run while a
    fresh one recomputes an unchanged fingerprint -- the same
    (project, book, range, fingerprint) row colliding on insert.
    Deferred import to avoid a module cycle (passage_semantic_runtime
    already imports semantic_location, which imports this module).
    """
    from .passage_semantic_runtime import alignment_state_digest
    return alignment_state_digest(runtime.project)


def alignment_precedents_for_range(
    runtime: Any, chapter: str, verse: str, end_chapter: str = "", end_verse: str = "",
) -> list[dict[str, Any]]:
    """Completed same-verse tC alignment groups, projected as location precedents.

    One entry per group that resolved cleanly on both sides, in the same
    shape `human_approved_lexical_precedents()` returns. Never raises for
    verse-scoped data problems (a malformed legacy alignment file, a missing
    current-text revision, ...) -- like HUMAN_PRECEDENT, this is optional
    evidence, so a problem with it costs that verse's contribution, not the
    whole search (see the module docstring's SEARCH_INCOMPLETE reasoning in
    the V11-000a spike doc).
    """
    from .original_language_resources import resource_for_book
    from .passage_semantic_runtime import DEFAULT_TOKENIZER

    project = runtime.project
    book = runtime.book
    resource = resource_for_book(book)
    if resource is None:
        return []
    try:
        passage = runtime.rebuild_current_passage(chapter, verse, end_chapter, end_verse)
    except Exception:
        return []
    precedents: list[dict[str, Any]] = []
    for reference, current_text in passage["targetTextByDisplayedReference"].items():
        parsed = _reference_chapter_verse(reference)
        if parsed is None:
            continue
        ref_chapter, ref_verse = parsed
        try:
            if project.word_alignment_state(ref_chapter, ref_verse) != "completed":
                continue
            alignment = project.load_verse_alignment(ref_chapter, ref_verse)
        except Exception:
            continue
        if not alignment.alignments:
            continue
        revision_row = runtime.repository.current_target_revision(runtime.project_id, book, reference)
        if revision_row is None:
            continue
        text_revision = revision_row["textRevision"]
        duplicated_top, duplicated_bottom = _duplicated_signatures(alignment)
        for group in alignment.alignments:
            if not group.top_words or not group.bottom_words:
                continue  # unaligned-top or empty-bottomWords: no target evidence either way
            if any(t.signature in duplicated_top for t in group.top_words):
                continue
            if any(t.signature in duplicated_bottom for t in group.bottom_words):
                continue
            source_ids = [
                resolve_source_token_id(resource, book, ref_chapter, ref_verse, top)
                for top in group.top_words
            ]
            if any(item is None for item in source_ids):
                continue
            target_ids = [
                resolve_target_token_id(
                    project_id=runtime.project_id, book=book, displayed_reference=reference,
                    text_revision=text_revision, current_text=current_text,
                    profile=DEFAULT_TOKENIZER, ref=bottom,
                )
                for bottom in group.bottom_words
            ]
            if any(item is None for item in target_ids):
                continue
            precedents.append({
                "sourceTokenInstanceIds": source_ids, "targetTokenInstanceIds": target_ids,
            })
    return precedents
