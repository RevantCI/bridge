"""The one implementation of the `QaFinding.targetContentHashes` contract.

Stage 8 (`qa_audit`) writes these hashes; Stage 9B correction eligibility
(`correction_eligibility`) reads them and compares them against Scripture as it
stands now.  Both sides import the resolution and the hash from here so the
same target verse string can never hash differently at write and at read.

**These are per-verse hashes, not the Stage 6A range fingerprint.**  The two
are different invariants and are deliberately kept apart:

* `targetInventory["targetContentHash"]` (Stage 6A) is a SHA-256 of the JSON
  object holding *every* verse in the analyzed range.  It answers "is this
  analysis run still current?" and stays where it is, feeding the
  inventory/run fingerprint machinery.
* `qaFinding["targetContentHashes"]` (Stage 8) is an exact content-addressed
  snapshot of the target Scripture a correction would rewrite.  It answers "is
  the wording the reviewer confirmed still the wording on disk?".

Stage 8 originally wrote the Stage 6A range fingerprint into the Stage 8 field.
Because no single verse's text ever hashes to a whole-range JSON fingerprint,
every naturally emitted finding failed Stage 9B eligibility with
TARGET_TEXT_CHANGED even when Scripture had never been touched.  Never write
the range fingerprint into `targetContentHashes` again.
"""
from __future__ import annotations

import hashlib
from typing import Any, Callable, Iterable, Mapping


# Bumped whenever the meaning of `targetContentHashes` changes.  v1 was the
# Stage 6A range fingerprint; v2 is the per-target-reference verse hash.
TARGET_CONTENT_HASH_CONTRACT = "qa-target-content-hash-v2"


def canonical_text_hash(text: str) -> str:
    """SHA-256 of the raw verse text as UTF-8.

    Identical at Stage 8 persistence, Stage 9B eligibility, and correction
    proposal/application validation -- `PassageSemanticRuntime.text_hash`
    is this function.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def finding_target_references(
    target_semantic_unit_ids: Iterable[Any],
    displayed_references: Iterable[Any],
    resolve_unit: Callable[[str], Mapping[str, Any] | None],
) -> tuple[str, ...]:
    """The target Scripture references a finding's hashes are taken over.

    A finding's `displayedReferences` deliberately carries *both* sides: the
    source semantic unit's reference and the target realization's.  For the
    cross-verse case (source PHP 1:3 realized at target PHP 1:6) those differ,
    and only the target one may be content-addressed -- hashing the source
    reference's verse would make an edit to a neighbouring verse look like an
    edit to the correction target.

    A finding with no target semantic units (an omission: nothing was located
    in the target) has no separate target realization, so its displayed
    references *are* its target references and the fallback returns them.
    Resolution is all-or-nothing: if any target unit cannot be resolved, fall
    back rather than emit a list that silently drops a reference and misaligns
    every hash after it.
    """
    unit_ids = [str(item) for item in target_semantic_unit_ids if str(item)]
    displayed = tuple(dict.fromkeys(
        str(item) for item in displayed_references if str(item)
    ))
    if not unit_ids:
        return displayed
    references: list[str] = []
    for unit_id in unit_ids:
        unit = resolve_unit(unit_id)
        if not unit:
            return displayed
        references.extend(str(item) for item in unit.get("displayedReferences") or ())
    resolved = tuple(dict.fromkeys(item for item in references if item))
    return resolved or displayed


def target_content_hashes(
    references: Iterable[str], current_text: Mapping[str, str],
) -> tuple[str, ...]:
    """One per-verse hash per target reference, positionally aligned.

    A reference with no current Scripture yields an empty hash rather than
    being dropped: dropping it would shift every later hash onto the wrong
    reference, and an empty hash can never match, so the failure is closed.
    """
    return tuple(
        canonical_text_hash(current_text[reference]) if reference in current_text else ""
        for reference in references
    )
