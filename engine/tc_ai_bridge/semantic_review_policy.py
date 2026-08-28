"""Deterministic Bridge review policy for Stage 3 semantic mappings.

The model proposes linguistic judgments; this module enforces what Bridge is
allowed to represent in verse-local translationCore checkData.  It is target-
language neutral and intentionally conservative.
"""
from __future__ import annotations

from typing import Any

from .semantic_mapping_bridge import mapping_by_source_unit, semantic_state_by_check

_NATIVE_SAFE = {"", "found_this_verse"}
_NONLOCAL = {"found_another_verse", "split_across_verses"}
_NO_LITERAL_LOCAL = {"represented_implicitly"}
_UNRESOLVED = {"target_not_located", "needs_passage_review", "source_anchor_unresolved", "mapping_error"}


def semantic_mapping_for_check(pack: dict[str, Any] | None, check_id: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    states = semantic_state_by_check(pack)
    state = states.get(str(check_id))
    if not state:
        return None, None
    mapping = mapping_by_source_unit(pack).get(str(state.get("sourceUnitId") or ""))
    return state, mapping


def native_tc_apply_allowed(review: Any) -> bool:
    """Whether the AI proposal is safe to write to verse-local tC checkData.

    Human users can still inspect/confirm a rich Bridge mapping.  This function
    only governs the legacy verse-local selection write path.
    """
    state = str(_get(review, "selection_state", "") or "")
    verdict = str(_get(review, "verdict", "review") or "review")
    selections = list(_get(review, "proposed_selections", []) or [])
    nothing = bool(_get(review, "nothing_to_select", False))
    if state not in _NATIVE_SAFE:
        return False
    if verdict == "problem" and nothing:
        return False
    if state == "found_this_verse":
        return bool(selections) and not nothing
    # Legacy no-semantic-state path remains available for not-applicable only;
    # this preserves Beta 13 compatibility without misusing NTS for mapped data.
    return verdict == "not_applicable" and nothing or bool(selections)


def apply_semantic_review_policy(review: Any, pack: dict[str, Any] | None) -> Any:
    """Attach Stage 3 state and enforce non-negotiable review invariants.

    Rules:
    * Cross-verse/split mappings never masquerade as current-verse selections.
    * Implicit/grammatical realizations are explicit semantic states, not NTS.
    * Unresolved semantic search is review, never an automatic omission.
    * ``problem + nothing_to_select`` is impossible.
    * A model cannot invent a local selection when Stage 3 grounded the meaning
      elsewhere in the passage.
    """
    check_id = str(_get(review, "check_id", "") or "")
    state_row, mapping = semantic_mapping_for_check(pack, check_id)
    state = str((state_row or {}).get("state") or "")
    _set(review, "selection_state", state)
    _set(review, "semantic_mapping", mapping)

    if state in _NONLOCAL:
        _clear_local_proposal(review)
        _set(review, "nothing_to_select", False)
        _append_rationale(review, _nonlocal_message(state, state_row or {}, mapping or {}))
    elif state in _NO_LITERAL_LOCAL:
        _clear_local_proposal(review)
        _set(review, "nothing_to_select", False)
        _append_rationale(review, "Stage 3: this source meaning is represented implicitly or grammatically in the target passage. This is an explicit semantic state, not 'Nothing to Select'.")
    elif state in _UNRESOLVED:
        _clear_local_proposal(review)
        _set(review, "nothing_to_select", False)
        _set(review, "verdict", "review")
        _append_rationale(review, "Stage 3: the target realization was not securely grounded within the searched passage. Keep this check pending and extend passage/human review; do not infer an omission from search exhaustion.")
    elif state == "found_this_verse":
        # The current verse is semantically appropriate, but a literal native
        # selection is still required before auto-application.
        if bool(_get(review, "nothing_to_select", False)):
            _set(review, "nothing_to_select", False)
        if not list(_get(review, "proposed_selections", []) or []):
            _set(review, "verdict", "review")
            _append_rationale(review, "Stage 3 located this meaning in the current verse, but no exact translationCore-compatible target selection was resolved. Keep pending until an exact span is selected.")

    # Global backstop independent of semantic-state availability.
    if str(_get(review, "verdict", "review") or "review") == "problem" and bool(_get(review, "nothing_to_select", False)):
        _set(review, "nothing_to_select", False)
        _append_rationale(review, "Bridge consistency gate: a problem verdict cannot be saved as 'Nothing to Select'.")
    return review


def apply_semantic_review_policy_all(reviews: list[Any], pack: dict[str, Any] | None) -> list[Any]:
    return [apply_semantic_review_policy(review, pack) for review in reviews]


def _clear_local_proposal(review: Any) -> None:
    _set(review, "proposed_selection_ids", [])
    _set(review, "proposed_selection_text", [])
    _set(review, "proposed_selections", [])


def _nonlocal_message(state: str, state_row: dict[str, Any], mapping: dict[str, Any]) -> str:
    spans = list(mapping.get("target_spans") or state_row.get("targetSpans") or [])
    rendered = "; ".join(f"{s.get('reference')}: {s.get('quote')}" for s in spans if isinstance(s, dict))
    relation = ", ".join(mapping.get("relationships") or state_row.get("relationships") or [])
    prefix = "Stage 3: meaning is split across target verses" if state == "split_across_verses" else "Stage 3: meaning is realized in another target verse"
    details = f" — {rendered}" if rendered else ""
    rel = f" ({relation})" if relation else ""
    return f"{prefix}{details}{rel}. Do not force this mapping into the current verse's translationCore selection or 'Nothing to Select'."


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _set(obj: Any, key: str, value: Any) -> None:
    if isinstance(obj, dict):
        obj[key] = value
    else:
        setattr(obj, key, value)


def _append_rationale(review: Any, text: str) -> None:
    current = str(_get(review, "rationale", "") or "").strip()
    if text in current:
        return
    _set(review, "rationale", (current + "\n\n" + text).strip())
