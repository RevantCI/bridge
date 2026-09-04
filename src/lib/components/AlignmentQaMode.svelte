<script lang="ts">
  import QaFindingDetail from "./QaFindingDetail.svelte";
  import QaFindingList from "./QaFindingList.svelte";
  import AnalysisControls from "./AnalysisControls.svelte";
  import type {
    AnalysisJobSnapshot, AnalysisScopeState, AnalysisScopeStatus,
  } from "../types/analysisJob";
  import type { QaDisposition, ReviewQueueOrder, ReviewerDecision } from "../types/qaReview";
  import {
    addReviewerNote,
    decideFinding,
    detailError,
    detailLoading,
    goToNextUnresolved,
    hasMoreFindings,
    loadMoreFindings,
    loadQueue,
    reviewError,
    reviewFilters,
    reviewLoading,
    reviewQueue,
    reviewTotal,
    setReviewCanonicalScope,
    selectFinding,
    selectedDetail,
    selectedFindingId,
    stepSelection,
  } from "../reviewStores";

  /**
   * QA mode: the primary Stage 9A work surface.
   *
   * Queue on the left, evidence and decision on the right. Filters restart
   * the queue rather than filtering the loaded page, so what the reviewer
   * sees always matches what the engine ordered.
   */

  export let chapter: string;
  export let verse: string | null = null;

  const KIND_FILTERS: Array<{ value: string; label: string }> = [
    { value: "POSSIBLE_OMISSION", label: "Possible omissions" },
    { value: "POSSIBLE_ADDITION", label: "Possible additions" },
    { value: "POSSIBLE_UNDERTRANSLATION", label: "Undertranslation" },
    { value: "POSSIBLE_OVERTRANSLATION", label: "Overtranslation" },
    { value: "MEANING_SHIFT", label: "Meaning shifts" },
    { value: "CONTRADICTION", label: "Contradictions" },
    { value: "NEGATION_PROBLEM", label: "Negation" },
    { value: "QUANTITY_PROBLEM", label: "Quantity" },
    { value: "TEMPORAL_PROBLEM", label: "Temporal" },
    { value: "PARTICIPANT_PROBLEM", label: "Participant" },
    { value: "REFERENT_PROBLEM", label: "Referent" },
    { value: "RESOURCE_CONFLICT", label: "Resource conflict" },
    { value: "SOURCE_VARIANT_REVIEW", label: "Source variant" },
  ];

  const STATE_FILTERS: Array<{ value: QaDisposition; label: string }> = [
    { value: "UNRESOLVED", label: "Unreviewed" },
    { value: "CONFIRMED_TRANSLATION_ERROR", label: "Confirmed" },
    { value: "ACCEPTABLE_TRANSLATION", label: "Accepted" },
    { value: "FALSE_POSITIVE", label: "False positives" },
    { value: "NEEDS_DISCUSSION", label: "Needs discussion" },
  ];

  let busy = false;
  let flash = "";
  let flashTone: "ok" | "warn" = "ok";
  let analysisState: AnalysisScopeState = "NOT_ANALYZED";
  let scopeReady = false;

  async function applyFilters(): Promise<void> {
    if (!scopeReady) return;
    await loadQueue();
    await selectFinding(null);
  }

  function toggle<T>(list: T[], value: T): T[] {
    return list.includes(value) ? list.filter((item) => item !== value) : [...list, value];
  }

  async function toggleKind(value: string): Promise<void> {
    reviewFilters.update((f) => ({ ...f, kinds: toggle(f.kinds, value) }));
    await applyFilters();
  }

  async function toggleDisposition(value: QaDisposition): Promise<void> {
    reviewFilters.update((f) => ({ ...f, dispositions: toggle(f.dispositions, value) }));
    await applyFilters();
  }

  async function toggleStale(): Promise<void> {
    reviewFilters.update((f) => ({
      ...f,
      lifecycleStatuses: f.lifecycleStatuses.includes("STALE") ? [] : ["STALE"],
    }));
    await applyFilters();
  }

  async function setOrder(order: ReviewQueueOrder): Promise<void> {
    reviewFilters.update((f) => ({ ...f, order }));
    await applyFilters();
  }

  function announce(message: string, tone: "ok" | "warn" = "ok"): void {
    flash = message;
    flashTone = tone;
  }

  async function onDecide(
    event: CustomEvent<{ disposition: ReviewerDecision; note: string; promote: boolean }>,
  ): Promise<void> {
    const id = $selectedFindingId;
    if (!id) return;
    busy = true;
    const result = await decideFinding(id, event.detail.disposition, {
      note: event.detail.note,
      promote: event.detail.promote,
    });
    busy = false;
    if (result.ok) {
      const promoted = result.promoted.length
        ? ` Promoted ${result.promoted.length} coverage account${result.promoted.length === 1 ? "" : "s"}.`
        : "";
      announce(`Decision recorded.${promoted}`);
      await goToNextUnresolved();
    } else {
      announce(result.message, "warn");
    }
  }

  async function onNote(event: CustomEvent<{ note: string }>): Promise<void> {
    const id = $selectedFindingId;
    if (!id) return;
    busy = true;
    const result = await addReviewerNote(id, event.detail.note);
    busy = false;
    announce(result.ok ? "Note saved." : result.message, result.ok ? "ok" : "warn");
  }

  async function onScopeStatus(event: CustomEvent<AnalysisScopeStatus>): Promise<void> {
    analysisState = event.detail.state;
    scopeReady = true;
    setReviewCanonicalScope(event.detail.canonicalReferences);
    await loadQueue();
    await selectFinding(null);
  }

  function onScopeInvalidated(): void {
    scopeReady = false;
    setReviewCanonicalScope([]);
  }

  async function analysisCompleted(
    event: CustomEvent<{ job: AnalysisJobSnapshot }>,
  ): Promise<void> {
    // The completed persisted job is authoritative, especially for an
    // AFFECTED run whose canonical references can be narrower than the base
    // scope status refreshed after completion.
    setReviewCanonicalScope(event.detail.job.canonicalReferences);
    await loadQueue();
    await selectFinding(null);
    announce("Analysis complete. The QA review queue has been refreshed.");
  }

  function scopeLabel(references: string[]): string {
    if (!references.length) return "resolving...";
    if (references.length === 1) return references[0];
    return `${references[0]} - ${references[references.length - 1]}`;
  }
</script>

<div class="qa-mode">
  <AnalysisControls
    {chapter}
    {verse}
    on:scopeStatus={onScopeStatus}
    on:scopeInvalidated={onScopeInvalidated}
    on:completed={analysisCompleted}
  />
  <p class="review-scope" aria-live="polite">
    Review scope: Current analysis range - {scopeLabel($reviewFilters.canonicalReferences)}
  </p>
  <div class="filters" role="group" aria-label="Filter the review queue">
    <div class="filter-row">
      <span class="filter-label" id="filter-order">Order</span>
      <div class="chips" role="group" aria-labelledby="filter-order">
        <button
          type="button"
          class="chip"
          aria-pressed={$reviewFilters.order === "CANONICAL"}
          on:click={() => setOrder("CANONICAL")}
        >Book order</button>
        <button
          type="button"
          class="chip"
          aria-pressed={$reviewFilters.order === "SEVERITY"}
          on:click={() => setOrder("SEVERITY")}
        >Highest priority first</button>
      </div>
    </div>

    <div class="filter-row">
      <span class="filter-label" id="filter-state">Review state</span>
      <div class="chips" role="group" aria-labelledby="filter-state">
        {#each STATE_FILTERS as option}
          <button
            type="button"
            class="chip"
            aria-pressed={$reviewFilters.dispositions.includes(option.value)}
            on:click={() => toggleDisposition(option.value)}
          >{option.label}</button>
        {/each}
        <button
          type="button"
          class="chip"
          aria-pressed={$reviewFilters.lifecycleStatuses.includes("STALE")}
          on:click={toggleStale}
        >Stale only</button>
      </div>
    </div>

    <div class="filter-row">
      <span class="filter-label" id="filter-kind">Issue type</span>
      <div class="chips" role="group" aria-labelledby="filter-kind">
        {#each KIND_FILTERS as option}
          <button
            type="button"
            class="chip"
            aria-pressed={$reviewFilters.kinds.includes(option.value)}
            on:click={() => toggleKind(option.value)}
          >{option.label}</button>
        {/each}
      </div>
    </div>
  </div>

  {#if flash}
    <p class="flash" class:warn={flashTone === "warn"} role="status">{flash}</p>
  {/if}
  {#if $reviewError}
    <p class="flash warn" role="alert">{$reviewError}</p>
  {/if}
  {#if scopeReady && !$reviewLoading && $reviewTotal === 0}
    <p class="empty-state" role="status">
      {#if analysisState === "NOT_ANALYZED"}
        This range has not been analyzed yet. Choose a scope and run analysis.
      {:else if analysisState === "PARTIALLY_ANALYZED"}
        Part of this range has analysis results. Run analysis for complete coverage.
      {:else if analysisState === "STALE"}
        Previous results are out of date because the target text or source resources changed.
      {:else if analysisState === "SEARCH_INCOMPLETE"}
        Analysis completed with incomplete semantic search. No omission was inferred from unresolved searches.
      {:else if analysisState === "FAILED"}
        The latest analysis failed. Retry it from the analysis controls above.
      {:else if analysisState === "CURRENT"}
        Analysis complete. No possible QA issues were found in this range.
      {:else if analysisState === "RUNNING"}
        Analysis is running. Findings will appear here when the QA stage completes.
      {/if}
    </p>
  {/if}

  <div class="panes">
    <div class="pane list-pane">
      <QaFindingList
        findings={$reviewQueue}
        selectedId={$selectedFindingId}
        loading={$reviewLoading}
        hasMore={$hasMoreFindings}
        total={$reviewTotal}
        on:select={(event) => selectFinding(event.detail.id)}
        on:loadMore={() => loadMoreFindings()}
      />
    </div>

    <div class="pane detail-pane">
      <QaFindingDetail
        detail={$selectedDetail}
        loading={$detailLoading}
        error={$detailError}
        {busy}
        on:decide={onDecide}
        on:note={onNote}
        on:next={() => stepSelection(1)}
        on:previous={() => stepSelection(-1)}
      />
    </div>
  </div>
</div>

<style>
  .qa-mode { display: flex; flex-direction: column; min-height: 0; height: 100%; }

  .review-scope {
    margin: 0;
    padding: 0.35rem 0.6rem;
    border-bottom: 1px solid #e5e7eb;
    color: #4b5563;
    font-size: 0.75rem;
    flex: none;
  }

  .filters {
    padding: 0.45rem 0.6rem;
    border-bottom: 1px solid #e5e7eb;
    display: flex;
    flex-direction: column;
    gap: 0.3rem;
    flex: none;
    /* Many filters on a 1366x768 screen: cap the block and let it scroll
       rather than pushing the queue itself off the viewport. */
    max-height: 8.5rem;
    overflow-y: auto;
  }

  .filter-row { display: flex; align-items: baseline; gap: 0.5rem; flex-wrap: wrap; }
  .filter-label { font-size: 0.7rem; color: #6b7280; min-width: 5.5rem; }
  .chips { display: flex; flex-wrap: wrap; gap: 0.25rem; }

  .chip {
    font: inherit;
    font-size: 0.72rem;
    padding: 0.15rem 0.5rem;
    border: 1px solid #d1d5db;
    border-radius: 999px;
    background: #fff;
    color: #374151;
    cursor: pointer;
  }

  /* Pressed state carries a border weight and a check glyph position, not
     colour alone. */
  .chip[aria-pressed="true"] {
    border-color: #1d4ed8;
    border-width: 2px;
    padding: 0.1rem 0.45rem;
    background: #eff6ff;
    color: #1d4ed8;
    font-weight: 600;
  }

  .chip:focus-visible { outline: 2px solid #2563eb; outline-offset: 1px; }

  .flash {
    margin: 0;
    padding: 0.3rem 0.6rem;
    font-size: 0.78rem;
    background: #ecfdf5;
    color: #065f46;
    border-bottom: 1px solid #d1fae5;
    flex: none;
  }

  .flash.warn { background: #fef2f2; color: #991b1b; border-bottom-color: #fecaca; }
  .empty-state { margin: 0; padding: 0.4rem 0.6rem; font-size: 0.76rem; background: #f9fafb; color: #4b5563; border-bottom: 1px solid #e5e7eb; }

  .panes {
    display: grid;
    grid-template-columns: minmax(16rem, 22rem) minmax(0, 1fr);
    min-height: 0;
    flex: 1 1 auto;
  }

  .pane { min-height: 0; min-width: 0; }
  .list-pane { border-right: 1px solid #e5e7eb; }

  /* Below roughly a narrow laptop the two panes stack instead of shrinking
     the evidence column into unreadability. */
  @media (max-width: 900px) {
    .panes { grid-template-columns: minmax(0, 1fr); grid-template-rows: 14rem minmax(0, 1fr); }
    .list-pane { border-right: none; border-bottom: 1px solid #e5e7eb; }
  }
</style>
