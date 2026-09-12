# V11-003 / #57 — decision and implementation prompt

Manually-written correction proposals are not marked reviewed until an
Edit→Save round-trip, so "Review application" never appears.

**Part A** records the decision and the evidence behind it. **Part B** is the
prompt for the code agent.

---

# Part A — decision

## Root cause

`engine/tc_ai_bridge/correction_wording.py:574`, in `_build_proposal`:

```python
review_status=(
    ReviewStatus.AI_PROPOSED if result is not None else ReviewStatus.UNREVIEWED
),
```

`result is None` means no AI wording was produced — i.e. a human wrote it —
and the proposal lands `UNREVIEWED`. The panel gates on
`CorrectionReviewPanel.svelte:107-108`:

```js
$: proposalReviewed = Boolean(
  selectedProposal?.reviewStatus === "HUMAN_MODIFIED"
    || selectedProposal?.reviewStatus === "HUMAN_APPROVED",
);
$: mayApply = Boolean(
  proposalCurrent && proposalReviewed && selectedProposal?.verificationStatus === "NOT_RUN",
);
```

so `mayApply` stays false and "Review application" never renders.

## Decision: default a human-authored proposal to `HUMAN_APPROVED`, and lazily reseed existing ones

The deciding fact: Edit→Save calls
`update_correction_proposal_wording(..., review_status=ReviewStatus.HUMAN_MODIFIED)`
(`correction_wording.py:631`) with **no check on who performs it**. Today's
workaround is therefore already self-review by the proposal's own author,
just with a pointless round-trip. Defaulting to approved removes a ceremony
that is already a no-op; it does not loosen any safety property.

Supporting:

- `creationMode` records authorship independently (`HUMAN_AUTHORED` vs
  `MACHINE_SUGGESTED` / `AI_GENERATED` / `HUMAN_MODIFIED_AI`,
  `passage_semantic_models.py:835-844`), so `reviewStatus` is free to mean
  review rather than provenance. No information is lost.
- Applying is gated independently regardless: `mayApply` also requires
  `proposalCurrent` and `verificationStatus === "NOT_RUN"`, and Stage 9B.3b
  requires an explicit human application step on top.

**Rejected — fixing the frontend gate** (treating `UNREVIEWED` +
`HUMAN_AUTHORED` as reviewed in the panel). That would have the UI derive
meaning not present in persisted state, contradicting the Phase 2 invariant
applied in V11-001: the frontend mirrors persisted backend state, never
computes it locally.

**Deferred, not rejected — the author ≠ reviewer distinction.** Once the team
direction (#74–#81) lands, a second person endorsing a correction is a real
requirement. That should be a dedicated reviewer field plus a policy check,
not an overloaded `reviewStatus`. File it against that milestone; do not
build it now.

## The concurrency hazard in "reseed on read"

`update_correction_proposal_wording` bumps `revision`
(`passage_semantic_repository.py:4082-4090`). The panel caches
`selectedProposal.revision` and sends it as `expectedProposalRevision` on
edit, reject and apply (`CorrectionReviewPanel.svelte:601`, `:627`, `:649`),
and surfaces a revision conflict to the user (`:515`, `:609`).

So a reseed that bumps `revision` would make the user's *next* action fail
with `REVISION_CONFLICT` — converting a silent bug into a confusing error.
**The reseed must write `review_status` in place and leave `revision`
untouched.** This is a deliberate exception to the CAS discipline, justified
because the reseed is a data-repair backfill, not a human edit, and it must
be invisible to optimistic concurrency.

## Note on the issue's labels

#57 is labelled `area:frontend`. The fix is backend (`correction_wording.py`
plus the repository read path); the only frontend change is one TypeScript
union member and a Vitest case. Worth relabelling.

---

# Part B — prompt for the code agent

> Paste from here down. Start from `origin/main` with the V11-000a review fix
> already pushed.

---

You are implementing **V11-003 / #57** in the Bridge repository: a manually
written correction proposal must be usable without an Edit→Save round-trip.

Read `docs/V11-003_ISSUE57_PROMPT.md` Part A first — the product decision is
already made, with the reasoning and the rejected alternatives. Do not
relitigate it. Read `CLAUDE.md` and treat its staleness and schema rules as
binding.

## Scope

**In:** the review-status default for newly created human-authored
proposals; a lazy, idempotent reseed of existing `UNREVIEWED` +
`HUMAN_AUTHORED` proposals; tests for both.

**Out:** any author-≠-reviewer policy or reviewer field (deferred to the
#74–#81 team milestone); any change to the frontend gate at
`CorrectionReviewPanel.svelte:107-108`; any change to how `HUMAN_MODIFIED` is
set on edit; any schema version bump.

## W1. The default for new proposals

`engine/tc_ai_bridge/correction_wording.py`, `_build_proposal` (~line 574).
Change only the `else` branch:

```python
review_status=(
    ReviewStatus.AI_PROPOSED if result is not None
    else ReviewStatus.HUMAN_APPROVED if human_proposed_text.strip()
    else ReviewStatus.UNREVIEWED
),
```

- `result is not None` must keep behaving exactly as it does today. Do not
  touch the AI path.
- A proposal with no human text and no AI result stays `UNREVIEWED`. That is
  correct — nobody has written anything to review.
- **Do not append an extra history event for this.** The `CREATED` event
  (`passage_semantic_repository.py:3959`) already snapshots the whole
  proposal payload, `reviewStatus` included, so the approval is already in
  the audit trail. A second event would be redundant noise.

## W2. Lazy reseed for existing proposals

Precedent: `ad0b3c1` ("reseed reviewer_name for profiles predating V11-005"),
which put the reseed in the store itself. Follow that shape.

Reseed a proposal when, and only when, **all** of:

- `reviewStatus == "UNREVIEWED"`, and
- `creationMode == "HUMAN_AUTHORED"`, and
- `lifecycleStatus == "ACTIVE"`, and
- the proposal has no AI provenance (empty/absent `providerMetadata` and
  `originalSuggestedText`).

Never touch `AI_PROPOSED`, `HUMAN_REJECTED`, `NEEDS_DISCUSSION`,
`HUMAN_MODIFIED`, or any non-`ACTIVE` proposal.

Requirements:

1. **Do not bump `revision`.** Update the `review_status` column and the
   payload's `reviewStatus` key in place. Part A explains why; put a comment
   at the write site saying it, because it looks like a CAS violation to
   anyone reading it later.
2. **One choke point**, covering both `correction_proposal()`
   (`passage_semantic_repository.py:4204`) and
   `correction_proposals_for_finding()` (`:4218`). A proposal must not be
   reachable in one read path unreseeded and the other reseeded.
3. **Idempotent.** A second read performs no write and appends no event.
   Assert this, don't assume it.
4. **Attribution: `ActorType.MIGRATION`** (`passage_semantic_models.py:310`).
   Not `HUMAN` — the V1.1 acceptance pass explicitly verified that automatic
   events never attribute to the named reviewer. Append one event via
   `_append_correction_event` with a new event type, e.g.
   `"REVIEW_STATUS_BACKFILLED"`, and `base_revision` equal to the unchanged
   current revision.
5. The new event type needs `CorrectionEventType` in
   `src/lib/types/correctionReview.ts:198` extended by one member. Confirm by
   grep that it is **not** present in
   `schemas/bridge-passage-semantic-v1.schema.json` or
   `src-tauri/src/passage_semantic_wire.rs` — my read says it is not, so this
   is a one-line TS change and not a three-surface update, but verify rather
   than trust that.
6. **Never write on a read when the database is in read-only or recovery
   mode.** Find how the repository already guards that (`recovery_check` and
   the read-only path referenced around
   `passage_semantic_repository.py:55-63`) and honour it — a reseed that
   throws inside a read would break project open.

## Verify before you build

Confirm that `correction_proposals.review_status` feeds **no** engine
fingerprint or policy identity. My read: the Stage 6B precedent query reads
`lexical_groups.review_status` (`passage_semantic_repository.py:3248-3257`),
a different table, and the Stage 9B.4 verifier fingerprint carries only
engine/policy versions. If you find otherwise, **stop and report** — it would
mean this change needs a version bump, which would change its whole shape.

## Tests

Backend (`engine/tests/correction/`):

1. New proposal with human text → `reviewStatus == "HUMAN_APPROVED"`; one
   `CREATED` event, no extra event.
2. New proposal with `request_suggestion=True` and a provider result → still
   `AI_PROPOSED`. Unchanged.
3. New proposal with neither → still `UNREVIEWED`.
4. Reseed: seed a proposal at `UNREVIEWED` + `HUMAN_AUTHORED`, read it →
   `HUMAN_APPROVED`, **`revision` unchanged**, exactly one
   `REVIEW_STATUS_BACKFILLED` event with `actorType == "MIGRATION"`.
5. Reseed idempotence: read twice → still one event, revision still
   unchanged.
6. Reseed leaves alone: `AI_PROPOSED`, `HUMAN_REJECTED`, a non-`ACTIVE`
   proposal, and an `UNREVIEWED` one carrying `providerMetadata`.
7. Both read paths: a proposal fetched via `correction_proposals_for_finding`
   is reseeded identically to one fetched via `correction_proposal`.
8. **Concurrency regression — the one that proves the `revision` rule.** Read
   a stale proposal (triggering the reseed), then call
   `correction_edit_proposal` with the revision the panel would have cached
   from that same read. It must succeed. Write this test so it fails if
   someone later "fixes" the reseed to bump revision.

Frontend (`src/lib/components/__tests__/CorrectionReviewPanel.test.ts`):

9. A proposal with `reviewStatus: "HUMAN_APPROVED"` and
   `creationMode: "HUMAN_AUTHORED"` renders "Review application" as reachable
   with no edit round-trip. Assert against the same `mayApply` conditions the
   panel uses, not a snapshot.

## Definition of done

- A manual correction is applicable straight after writing it; no Edit→Save.
- Existing stuck proposals become usable on next read, with `revision`
  preserved and the next edit/reject/apply succeeding.
- Reseed is idempotent and narrowly scoped; nothing with AI provenance is
  touched.
- Full gate clean: engine + Greek Room `pytest`, `svelte-check` 0/0, Vitest,
  `cargo test` 12/12, production build.
- Schema still v14; no engine or policy version changed.
- `docs/BUILD_LOG.md` entry; `docs/QA_TEST_MATRIX.md` row if the manual-write
  path has one.

## Stop and report if

- `correction_proposals.review_status` turns out to feed any fingerprint or
  policy identity.
- The reseed cannot be made to skip `revision` without fighting the
  repository's write helpers — say so rather than bumping it.
- The new event type turns out to be pinned in the JSON schema or the Rust
  wire enum after all.

## Do not

Change the frontend `proposalReviewed` gate; add a reviewer field or any
author-≠-reviewer check; bump any version; push. Commit locally and leave it
for review.
