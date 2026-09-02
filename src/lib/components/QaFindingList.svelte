<script lang="ts">
  import { createEventDispatcher } from "svelte";

  import ReviewStatusBadge from "./ReviewStatusBadge.svelte";
  import type { QaFindingSummary } from "../types/qaReview";
  import {
    SEVERITY_IS_PRIORITY_ONLY,
    dispositionLabel,
    dispositionTone,
    findingKindLabel,
    severityLabel,
  } from "../utils/reviewLabels";

  /**
   * The review queue list.
   *
   * Windowed rather than fully rendered: a book can produce thousands of
   * findings and only the visible slice is put in the DOM. Rows are a fixed
   * height so the window can be computed from scrollTop without measuring,
   * which keeps scrolling smooth with a large queue.
   *
   * Keyboard: the list is a single tab stop; arrows move the active row and
   * Enter/Space opens it, so a reviewer never has to tab through a thousand
   * rows to reach the one below.
   */
  export let findings: QaFindingSummary[] = [];
  export let selectedId: string | null = null;
  export let loading = false;
  export let hasMore = false;
  export let total = 0;

  const dispatch = createEventDispatcher<{
    select: { id: string };
    loadMore: void;
  }>();

  const ROW_HEIGHT = 76;
  const OVERSCAN = 6;
  /** Below this many rows, windowing costs more than it saves. */
  const VIRTUALIZE_ABOVE = 60;

  let viewport: HTMLDivElement | null = null;
  let scrollTop = 0;
  let viewportHeight = 480;

  $: virtualized = findings.length > VIRTUALIZE_ABOVE;
  $: firstIndex = virtualized
    ? Math.max(0, Math.floor(scrollTop / ROW_HEIGHT) - OVERSCAN)
    : 0;
  $: lastIndex = virtualized
    ? Math.min(
        findings.length,
        Math.ceil((scrollTop + viewportHeight) / ROW_HEIGHT) + OVERSCAN,
      )
    : findings.length;
  $: visible = findings.slice(firstIndex, lastIndex);
  $: topPad = virtualized ? firstIndex * ROW_HEIGHT : 0;
  $: bottomPad = virtualized ? Math.max(0, (findings.length - lastIndex) * ROW_HEIGHT) : 0;

  function onScroll(event: Event): void {
    const element = event.currentTarget as HTMLDivElement;
    scrollTop = element.scrollTop;
    viewportHeight = element.clientHeight;
    // Ask for the next page before the reviewer reaches the very bottom.
    const remaining = element.scrollHeight - element.scrollTop - element.clientHeight;
    if (hasMore && !loading && remaining < ROW_HEIGHT * 4) dispatch("loadMore");
  }

  function move(delta: number): void {
    if (findings.length === 0) return;
    const current = findings.findIndex((item) => item.id === selectedId);
    const next = Math.min(findings.length - 1, Math.max(0, (current < 0 ? -1 : current) + delta));
    dispatch("select", { id: findings[next].id });
    scrollRowIntoView(next);
  }

  function scrollRowIntoView(index: number): void {
    if (!viewport) return;
    const top = index * ROW_HEIGHT;
    const bottom = top + ROW_HEIGHT;
    if (top < viewport.scrollTop) viewport.scrollTop = top;
    else if (bottom > viewport.scrollTop + viewport.clientHeight) {
      viewport.scrollTop = bottom - viewport.clientHeight;
    }
  }

  function onKeydown(event: KeyboardEvent): void {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      move(1);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      move(-1);
    } else if (event.key === "Home") {
      event.preventDefault();
      if (findings.length) {
        dispatch("select", { id: findings[0].id });
        scrollRowIntoView(0);
      }
    } else if (event.key === "End") {
      event.preventDefault();
      if (findings.length) {
        dispatch("select", { id: findings[findings.length - 1].id });
        scrollRowIntoView(findings.length - 1);
      }
    }
  }

  function referenceOf(finding: QaFindingSummary): string {
    return finding.displayedReferences?.[0] ?? finding.book ?? "";
  }
</script>

<div class="list-shell">
  <div class="list-summary" aria-live="polite">
    {#if loading && findings.length === 0}
      Loading findings…
    {:else}
      Showing {findings.length} of {total} possible {total === 1 ? "issue" : "issues"}
    {/if}
  </div>

  <div
    class="viewport"
    bind:this={viewport}
    on:scroll={onScroll}
    on:keydown={onKeydown}
    role="listbox"
    tabindex="0"
    aria-label="Possible issues awaiting review"
    aria-activedescendant={selectedId ? `finding-${selectedId}` : undefined}
  >
    {#if findings.length === 0 && !loading}
      <p class="empty">No findings match these filters.</p>
    {:else}
      <div style="height: {topPad}px" aria-hidden="true"></div>
      {#each visible as finding (finding.id)}
        <div
          id="finding-{finding.id}"
          class="row"
          class:selected={finding.id === selectedId}
          class:stale={finding.lifecycleStatus === "STALE"}
          role="option"
          aria-selected={finding.id === selectedId}
          tabindex="-1"
          on:click={() => dispatch("select", { id: finding.id })}
          on:keydown={(event) => {
            if (event.key === "Enter" || event.key === " ") {
              event.preventDefault();
              dispatch("select", { id: finding.id });
            }
          }}
        >
          <div class="row-top">
            <span class="reference">{referenceOf(finding)}</span>
            <span class="severity" title={SEVERITY_IS_PRIORITY_ONLY}>
              {severityLabel(finding.severity)} priority
            </span>
          </div>
          <div class="row-kind">{findingKindLabel(finding.kind)}</div>
          <div class="row-badges">
            <ReviewStatusBadge
              label={dispositionLabel(finding.qaDisposition)}
              tone={dispositionTone(finding.qaDisposition)}
            />
            {#if finding.lifecycleStatus === "STALE"}
              <ReviewStatusBadge
                label="Stale"
                tone="stale"
                title="Produced against an earlier revision of the text or resources."
              />
            {/if}
          </div>
        </div>
      {/each}
      <div style="height: {bottomPad}px" aria-hidden="true"></div>
      {#if loading && findings.length > 0}
        <p class="loading-more">Loading more…</p>
      {/if}
    {/if}
  </div>
</div>

<style>
  .list-shell {
    display: flex;
    flex-direction: column;
    min-height: 0;
    height: 100%;
  }

  .list-summary {
    padding: 0.4rem 0.6rem;
    font-size: 0.75rem;
    color: #4b5563;
    border-bottom: 1px solid #e5e7eb;
    flex: none;
  }

  .viewport {
    flex: 1 1 auto;
    min-height: 0;
    overflow-y: auto;
  }

  .viewport:focus-visible {
    outline: 2px solid #2563eb;
    outline-offset: -2px;
  }

  .row {
    box-sizing: border-box;
    height: 76px;
    padding: 0.4rem 0.6rem;
    border-bottom: 1px solid #f1f5f9;
    cursor: pointer;
    display: flex;
    flex-direction: column;
    gap: 0.15rem;
    overflow: hidden;
  }

  .row:hover { background: #f8fafc; }

  .row.selected {
    background: #eff6ff;
    /* A left rule, not just a fill, so selection survives greyscale. */
    box-shadow: inset 3px 0 0 #2563eb;
  }

  .row.stale { border-left: 3px dashed #b59a4d; }

  .row-top {
    display: flex;
    justify-content: space-between;
    gap: 0.5rem;
    font-size: 0.7rem;
    color: #6b7280;
  }

  .reference { font-weight: 600; color: #111827; }

  .row-kind {
    font-size: 0.82rem;
    color: #111827;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .row-badges { display: flex; gap: 0.3rem; overflow: hidden; }

  .empty, .loading-more {
    padding: 1rem 0.6rem;
    font-size: 0.8rem;
    color: #6b7280;
  }
</style>
