"""LLM-backed cross-verse link proposals, gated against the offline scorer (#146).

`cross_verse_proposals.py` learns from this project's own completed alignments, so
on a book nobody has finished it has nothing to say -- `no-completed-alignments`,
and the reviewer gets no help precisely where the work is hardest. This module is
the other half: an optional, human-invoked model call that can propose a
realization with no corpus behind it at all.

**Three rules hold this together, and none of them is decoration.**

*The model picks from a closed menu.* It never sees the verse's whole token
inventory, and it never sees Bridge's own ids. It is handed opaque `S1`/`T1`
handles for the gap tokens only, and every id it returns is resolved back through
that table -- an unknown handle is an `AIError`, not a dropped row. So the model
cannot invent a word; the worst it can do is mis-pick from a list Bridge wrote.
This is the same discipline `ai_client.run_full_review` applies to evidence ids.

*A link is written only where two independent signals agree.* `autoLinkable` needs
the model's pick and the offline statistical scorer's top candidate to be the same
pair, and the pair to be uncontested. One uncalibrated number gating an automatic
write would be a guess with a decimal point on it; two methods that disagree are
telling you something, and that case stays a suggestion. On a cold-start book the
offline scorer proposes nothing, so nothing is auto-linkable there -- the model
adds suggestions, not writes, exactly where it has no corroboration.

*Nothing here writes.* This module returns proposals. A link is still written only
by `alignment.crossVerse.link` (#117), the one writer, whether a human clicked
Accept or the caller is applying an agreed proposal.

The confidences below are as uncalibrated as the offline ones
(`cross_verse_proposals.py:35-40`). The model's self-reported number is recorded
because it is evidence about the model, not because it is known to mean anything;
it is deliberately NOT what gates the automatic link.
"""
from __future__ import annotations

import json
from typing import Any, Callable

AI_PROPOSAL_CALIBRATION_VERSION = "cross-verse-ai-uncalibrated-v1"

#: Cap on the menu handed to the model. A range's gaps are normally single
#: digits on each side; a pathological range (a whole unaligned chapter pulled
#: into one view) would otherwise build a prompt with no upper bound. Truncating
#: is reported, never silent -- see `truncated` on the result.
MAX_MENU_SOURCES = 40
MAX_MENU_TARGETS = 60

INSTRUCTIONS = (
    "You are helping a Bible translation reviewer find CROSS-VERSE realizations in an "
    "existing translation.\n\n"
    "Every source word listed in `sourceGaps` is an original-language word that has no "
    "counterpart in its own verse's translation. Every word in `targetGaps` is a word in "
    "the translation that no source word accounts for. Because translators redistribute "
    "meaning across verse boundaries, a source word from one verse is often realized by a "
    "target word in a neighbouring verse.\n\n"
    "For each source word you are confident about, return one link to the target word "
    "that realizes it. Rules:\n"
    "- Use ONLY the `id` values given. Never invent an id, a word or a verse.\n"
    "- The source and target of a link must be in DIFFERENT verses. A same-verse pair is "
    "handled elsewhere and will be discarded.\n"
    "- Each source id at most once, and each target id at most once: one target word "
    "realizes one source word.\n"
    "- Omit a source word entirely rather than guessing. A short, correct list is worth "
    "far more than a complete one. Returning no links at all is a valid answer.\n"
    "- `confidence` is 0-100 for how sure you are that this target word carries this "
    "source word's meaning.\n"
    "- `reason` is one short sentence a reviewer who reads neither original language can "
    "check, naming what in the target verse carries the meaning."
)

LINK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["links"],
    "properties": {
        "links": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["source_id", "target_id", "confidence", "reason"],
                "properties": {
                    "source_id": {"type": "string"},
                    "target_id": {"type": "string"},
                    "confidence": {"type": "integer", "minimum": 0, "maximum": 100},
                    "reason": {"type": "string"},
                },
            },
        },
    },
}


class MenuEntry:
    """One gap token, its opaque handle, and the verse it sits in."""

    __slots__ = ("handle", "verse", "token")

    def __init__(self, handle: str, verse: str, token: dict[str, Any]) -> None:
        self.handle, self.verse, self.token = handle, verse, token


def build_menu(
    gaps_by_verse: dict[str, dict[str, Any]],
    *,
    verse_order: list[str],
    verse_texts: dict[str, str] | None = None,
    glosses: dict[str, str] | None = None,
) -> tuple[dict[str, Any], dict[str, MenuEntry], dict[str, MenuEntry], bool]:
    """Build the model's payload plus the two handle tables that decode its reply.

    Verses are emitted in `verse_order`, not dict order, so the model sees the
    range in reading order -- which is the whole basis on which it can reason
    about a word moving to the next verse. Verse strings stay opaque throughout
    (bridges "3-4", segments "3a" -- CLAUDE.md gotcha 12).
    """
    verse_texts = verse_texts or {}
    glosses = glosses or {}
    ordered = [v for v in verse_order if v in gaps_by_verse]
    # A verse in the range that `verse_order` does not know about would otherwise
    # vanish from the prompt while still being scored offline.
    ordered += [v for v in gaps_by_verse if v not in set(ordered)]

    sources: dict[str, MenuEntry] = {}
    targets: dict[str, MenuEntry] = {}
    source_rows: list[dict[str, Any]] = []
    target_rows: list[dict[str, Any]] = []
    truncated = False

    for verse in ordered:
        entry = gaps_by_verse.get(verse) or {}
        for token in entry.get("sourceGaps", ()):
            if len(sources) >= MAX_MENU_SOURCES:
                truncated = True
                break
            handle = f"S{len(sources) + 1}"
            sources[handle] = MenuEntry(handle, verse, token)
            row = {
                "id": handle,
                "verse": verse,
                "word": token.get("word", ""),
                "lemma": token.get("lemma", "") or "",
                "strong": token.get("strong", "") or "",
            }
            gloss = glosses.get(str(token.get("strong") or ""), "")
            if gloss:
                # The one piece of context a reviewer-facing model most needs and
                # cannot derive: what the original-language word actually means.
                row["meaning"] = gloss
            source_rows.append(row)
        for token in entry.get("targetGaps", ()):
            if len(targets) >= MAX_MENU_TARGETS:
                truncated = True
                break
            handle = f"T{len(targets) + 1}"
            targets[handle] = MenuEntry(handle, verse, token)
            target_rows.append({"id": handle, "verse": verse, "word": token.get("word", "")})

    payload = {
        "verses": [
            {"verse": verse, "translation": verse_texts.get(verse, "")}
            for verse in ordered
        ],
        "sourceGaps": source_rows,
        "targetGaps": target_rows,
    }
    return payload, sources, targets, truncated


def _offline_best(offline_result: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    """The offline scorer's top proposal per source token, keyed (verse, topId)."""
    best: dict[tuple[str, str], dict[str, Any]] = {}
    for proposal in offline_result.get("proposals", ()) or ():
        source = proposal.get("source") or {}
        best[(str(source.get("verse", "")), str(source.get("topId", "")))] = proposal
    return best


def _decode_links(
    raw: dict[str, Any],
    sources: dict[str, MenuEntry],
    targets: dict[str, MenuEntry],
    *,
    error: Callable[[str], Exception],
) -> list[dict[str, Any]]:
    """Resolve the model's handles back to real tokens, refusing anything invented.

    An unknown handle raises rather than being skipped: a model returning ids
    Bridge never sent is not a row to drop quietly, it is a sign the prompt or the
    provider is wrong, and silently ignoring it would hide that for good.
    """
    links = raw.get("links")
    if links is None:
        return []
    if not isinstance(links, list):
        raise error("The model's cross-verse reply had a 'links' field that was not a list.")
    decoded: list[dict[str, Any]] = []
    seen_sources: set[str] = set()
    seen_targets: set[str] = set()
    for item in links:
        if not isinstance(item, dict):
            raise error("The model returned a cross-verse link that was not an object.")
        source_handle = str(item.get("source_id") or "")
        target_handle = str(item.get("target_id") or "")
        if source_handle not in sources:
            raise error(
                f"The model returned source id {source_handle!r}, which was not in the "
                "list it was given."
            )
        if target_handle not in targets:
            raise error(
                f"The model returned target id {target_handle!r}, which was not in the "
                "list it was given."
            )
        source, target = sources[source_handle], targets[target_handle]
        # Same-verse is `alignment.realign`, and the link store refuses both ends
        # in one verse anyway (#117) -- drop it here rather than propose something
        # that can only fail on accept.
        if source.verse == target.verse:
            continue
        # One target word realizes one source word. A model that reuses either
        # side has contradicted itself; keep the first and drop the rest rather
        # than surfacing two proposals that cannot both be accepted.
        if source_handle in seen_sources or target_handle in seen_targets:
            continue
        seen_sources.add(source_handle)
        seen_targets.add(target_handle)
        confidence = item.get("confidence", 0)
        try:
            confidence = max(0, min(100, int(confidence)))
        except (TypeError, ValueError):
            confidence = 0
        decoded.append({
            "source": source,
            "target": target,
            "confidence": confidence,
            "reason": str(item.get("reason") or "").strip(),
        })
    return decoded


def compose(
    decoded: list[dict[str, Any]],
    offline_result: dict[str, Any],
    *,
    chapter: str,
) -> list[dict[str, Any]]:
    """Turn decoded model links into proposals, setting `autoLinkable` on agreement.

    The output shape matches `cross_verse_proposals.propose`'s proposals so the UI
    renders both through one path; `MODEL_PICK` is an additional evidence kind, not
    a replacement, and an agreed proposal carries the offline evidence too so the
    reviewer can see *both* reasons rather than being asked to trust the model.
    """
    offline_best = _offline_best(offline_result)
    proposals: list[dict[str, Any]] = []
    for link in decoded:
        source, target = link["source"], link["target"]
        source_id = str(source.token.get("id", ""))
        target_id = str(target.token.get("id", ""))
        counterpart = offline_best.get((source.verse, source_id))
        agrees = bool(
            counterpart
            and str((counterpart.get("target") or {}).get("verse", "")) == target.verse
            and str((counterpart.get("target") or {}).get("bottomId", "")) == target_id
        )
        # Only the offline pass can report a contest here: `_decode_links` has
        # already dropped any second model link onto the same target, so two of
        # the model's own picks can never both reach this point. What this
        # carries through is the case that matters -- another source token's
        # best *offline* candidate is this same word, which means accepting
        # would settle a competition nobody has adjudicated.
        contested = bool(counterpart and counterpart.get("contested"))
        evidence: list[dict[str, Any]] = [{
            "kind": "MODEL_PICK",
            "rawScore": round(link["confidence"] / 100.0, 4),
            "weight": 1.0,
            "weightedScore": round(link["confidence"] / 100.0, 4),
            "modelConfidence": link["confidence"],
            "reason": link["reason"],
        }]
        if agrees and counterpart:
            evidence.extend(counterpart.get("evidence", ()) or ())
        proposals.append({
            "status": "PROPOSED" if agrees and not contested else "AMBIGUOUS",
            "confidence": round(link["confidence"] / 100.0, 4),
            "margin": 0.0,
            "contested": contested,
            "agreesWithCorpus": agrees,
            # The gate. Never the model's confidence on its own: see the module
            # docstring. An agreed, uncontested pair is two methods reaching the
            # same answer by different evidence.
            "autoLinkable": bool(agrees and not contested),
            "source": {
                "chapter": chapter, "verse": source.verse, "topId": source_id,
                "word": source.token.get("word", ""),
                "signature": source.token.get("signature", ""),
                "strong": source.token.get("strong", "") or "",
                "lemma": source.token.get("lemma", "") or "",
            },
            "target": {
                "chapter": chapter, "verse": target.verse, "bottomId": target_id,
                "word": target.token.get("word", ""),
                "signature": target.token.get("signature", ""),
            },
            "evidence": evidence,
            "alternatives": [],
        })
    proposals.sort(key=lambda p: (not p["autoLinkable"], p["source"]["verse"], p["source"]["topId"]))
    return proposals


def propose_with_model(
    gaps_by_verse: dict[str, dict[str, Any]],
    offline_result: dict[str, Any],
    call_model: Callable[[str, str], dict[str, Any]],
    *,
    chapter: str,
    verse_order: list[str],
    verse_texts: dict[str, str] | None = None,
    glosses: dict[str, str] | None = None,
    error: Callable[[str], Exception] = RuntimeError,
) -> dict[str, Any]:
    """Ask the model for cross-verse links and compose them into gated proposals.

    `call_model(instructions, input_json)` is injected rather than an
    `OpenAIResponsesClient` so this stays testable without a client, a key or a
    transport -- the same reason `cross_verse_proposals.propose` takes a table
    rather than a project.
    """
    payload, sources, targets, truncated = build_menu(
        gaps_by_verse, verse_order=verse_order, verse_texts=verse_texts, glosses=glosses,
    )
    if not sources or not targets:
        # Nothing to ask about. Spending a request to be told so would be a
        # billed round trip for an answer Bridge already has.
        return {
            "proposals": [], "calibrationVersion": AI_PROPOSAL_CALIBRATION_VERSION,
            "modelConsulted": False, "truncated": truncated,
        }
    raw = call_model(INSTRUCTIONS, json.dumps(payload, ensure_ascii=False))
    if not isinstance(raw, dict):
        raise error("The model's cross-verse reply was not a JSON object.")
    decoded = _decode_links(raw, sources, targets, error=error)
    return {
        "proposals": compose(decoded, offline_result, chapter=chapter),
        "calibrationVersion": AI_PROPOSAL_CALIBRATION_VERSION,
        "modelConsulted": True,
        "truncated": truncated,
    }
