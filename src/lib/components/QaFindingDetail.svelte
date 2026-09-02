<script lang="ts">
  import { createEventDispatcher } from "svelte";

  import EvidenceInspector from "./EvidenceInspector.svelte";
  import ReviewStatusBadge from "./ReviewStatusBadge.svelte";
  import type { QaFindingDetail, ReviewerDecision } from "../types/qaReview";
  import {
    REVIEWER_ACTIONS,
    SEVERITY_IS_PRIORITY_ONLY,
    dispositionLabel,
    dispositionTone,
    findingKindLabel,
    lifecycleLabel,
    reviewStatusLabel,
    severityLabel,
  } from "../utils/reviewLabels";

  /**
   * The finding detail pane: what Bridge found, why, and the four
   * conclusions a reviewer may reach.
   *
   * There is deliberately no "Apply correction" here. Stage 9A classifies
   * findings only; generating or applying replacement Scripture is Stage 9B.
   */
  export let detail: QaFindingDetail | null = null;
  export let loading = false;
  export let error = "";
  export let busy = false;

  const dispatch = createEventDispatcher<{
    decide: { disposition: ReviewerDecision; note: string; promote: boolean };
    note: { note: string };
    next: void;
    previous: void;
  }>();

  let note = "";
  let promote = false;

  // Reset the per-finding controls whenever a different finding is opened,
  // so a note typed against one finding cannot be submitted against another.
  let lastId: string | null = null;
  $: if (detail && detail.finding.id !== lastId) {
    lastId = detail.finding.id;
    note = "";
    promote = false;
  }

  $: finding = detail?.finding ?? null;
  $: decided = finding ? finding.qaDisposition !== "UNRESOLVED" : false;
  /** Only a confirmed issue can promote POSSIBLY_MISSING to MISSING. */
  $: promotable = Boolean(
    finding && ["POSSIBLE_OMISSION", "POSSIBLE_ADDITION", "POSSIBLY_MISSING", "POSSIBLY_UNSUPPORTED"]
      .includes(String(finding.kind)),
  );

  function decide(disposition: ReviewerDecision): void {
    dispatch("decide", {
      disposition,
      note: note.trim(),
      promote: promote && disposition === "CONFIRMED_TRANSLATION_ERROR",
    });
  }

  function submitNote(): void {
    if (!note.trim()) return;
    dispatch("note", { note: note.trim() });
    note = "";
  }
</script>

<div class="detail">
  {#if loading}
    <p class="state" role="status">Loading evidence…</p>
  {:else if error}
    <p class="state error" role="alert">{error}</p>
  {:else if !detail || !finding}
    <p class="state">Select a possible issue from the list to inspect its evidence.</p>
  {:else}
    <header class="head">
      <div class="head-line">
        <h3>{findingKindLabel(String(finding.kind))}</h3>
        <div class="nav">
          <button type="button" on:click={() => dispatch("previous")} aria-label="Previous finding">
            ‹ Previous
          </button>
          <button type="button" on:click={() => dispatch("next")} aria-label="Next finding">
            Next ›
          </button>
        </div>
      </div>

      <p class="reference">{(finding.displayedReferences ?? []).join(", ")}</p>

      <div class="badges">
        <ReviewStatusBadge
          label={dispositionLabel(finding.qaDisposition)}
          tone={dispositionTone(finding.qaDisposition)}
        />
        <ReviewStatusBadge label={reviewStatusLabel(finding.reviewStatus)} tone="neutral" />
        <ReviewStatusBadge
          label={lifecycleLabel(finding.lifecycleStatus)}
          tone={finding.lifecycleStatus === "STALE" ? "stale" : "neutral"}
        />
        <ReviewStatusBadge
          label="{severityLabel(finding.severity)} priority"
          tone="neutral"
          title={SEVERITY_IS_PRIORITY_ONLY}
        />
      </div>

      <p class="explanation">{finding.explanation}</p>
      <p class="caveat">
        This is what Bridge noticed, not a confirmed error. It stays a possibility until you
        decide.
      </p>
    </header>

    <div class="evidence">
      <EvidenceInspector {detail} />
    </div>

    <footer class="actions">
      <h4 id="decide-heading">Your decision</h4>

      <label class="note-label" for="reviewer-note">
        Note <span class="muted">(optional; saved with your decision, never into Scripture)</span>
      </label>
      <textarea
        id="reviewer-note"
        bind:value={note}
        rows="2"
        placeholder="Why is this acceptable, wrong, or worth discussing?"
      ></textarea>

      {#if promotable}
        <label class="promote">
          <input type="checkbox" bind:checked={promote} />
          <span>
            Also record this as confirmed missing / unsupported
            <span class="muted">— only applies when you confirm a translation issue</span>
          </span>
        </label>
      {/if}

      <div class="buttons" role="group" aria-labelledby="decide-heading">
        {#each REVIEWER_ACTIONS as action}
          <button
            type="button"
            class="decision"
            disabled={busy}
            title={action.hint}
            on:click={() => decide(action.disposition)}
          >
            {action.label}
          </button>
        {/each}
        <button type="button" class="secondary" disabled={busy || !note.trim()} on:click={submitNote}>
          Add note only
        </button>
      </div>

      {#if decided}
        <!-- Static state, not an announcement: the stale notice above is the
             pane's live region, and a second one would double-announce. -->
        <p class="decided">
          Recorded as “{dispositionLabel(finding.qaDisposition)}”. Deciding again replaces it and
          adds another entry to the history.
        </p>
      {/if}
    </footer>
  {/if}
</div>

<style>
  .detail {
    display: flex;
    flex-direction: column;
    min-height: 0;
    height: 100%;
    overflow-y: auto;
  }

  .state { padding: 1.2rem; color: #6b7280; font-size: 0.85rem; }
  .state.error { color: #9b1c1c; }

  .head { padding: 0.75rem 0.9rem; border-bottom: 1px solid #e5e7eb; flex: none; }

  .head-line {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: 0.75rem;
    flex-wrap: wrap;
  }

  h3 { margin: 0; font-size: 1rem; }
  h4 { margin: 0 0 0.4rem; font-size: 0.78rem; text-transform: uppercase; color: #374151; }

  .nav { display: flex; gap: 0.3rem; }
  .nav button {
    font-size: 0.75rem;
    padding: 0.2rem 0.5rem;
    border: 1px solid #d1d5db;
    border-radius: 4px;
    background: #fff;
    cursor: pointer;
  }

  .reference { margin: 0.2rem 0; font-size: 0.8rem; color: #4b5563; font-weight: 600; }
  .badges { display: flex; flex-wrap: wrap; gap: 0.3rem; margin: 0.4rem 0; }
  .explanation { margin: 0.4rem 0 0.2rem; font-size: 0.86rem; line-height: 1.5; }
  .caveat { margin: 0; font-size: 0.75rem; color: #6b7280; font-style: italic; }

  .evidence { padding: 0.75rem 0.9rem; flex: 1 1 auto; min-height: 0; }

  /* The decision controls must never sit below the fold on a small laptop:
     the pane scrolls, and these stay pinned to its bottom edge. */
  .actions {
    position: sticky;
    bottom: 0;
    padding: 0.7rem 0.9rem;
    border-top: 1px solid #e5e7eb;
    background: #f9fafb;
    flex: none;
  }

  .note-label { display: block; font-size: 0.78rem; margin-bottom: 0.2rem; }
  .muted { color: #6b7280; font-weight: 400; }

  textarea {
    width: 100%;
    box-sizing: border-box;
    font: inherit;
    font-size: 0.82rem;
    padding: 0.35rem 0.5rem;
    border: 1px solid #d1d5db;
    border-radius: 4px;
    resize: vertical;
  }

  .promote {
    display: flex;
    align-items: flex-start;
    gap: 0.4rem;
    margin: 0.4rem 0;
    font-size: 0.78rem;
  }

  .buttons { display: flex; flex-wrap: wrap; gap: 0.4rem; margin-top: 0.5rem; }

  .decision, .secondary {
    font: inherit;
    font-size: 0.8rem;
    padding: 0.35rem 0.7rem;
    border-radius: 4px;
    border: 1px solid #2563eb;
    background: #fff;
    color: #1d4ed8;
    cursor: pointer;
  }

  .secondary { border-color: #d1d5db; color: #374151; }
  .decision:disabled, .secondary:disabled { opacity: 0.5; cursor: not-allowed; }
  .decision:focus-visible, .secondary:focus-visible, .nav button:focus-visible {
    outline: 2px solid #2563eb;
    outline-offset: 1px;
  }

  .decided { margin: 0.5rem 0 0; font-size: 0.76rem; color: #4b5563; }
</style>
