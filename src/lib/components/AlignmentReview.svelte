<script lang="ts">
  import AlignmentModal from "./AlignmentModal.svelte";
  import AlignmentQaMode from "./AlignmentQaMode.svelte";
  import PassageAlignmentMode from "./PassageAlignmentMode.svelte";
  import SemanticAlignmentMode from "./SemanticAlignmentMode.svelte";
  import { detailLoading, selectedDetail } from "../reviewStores";

  /**
   * The Alignment Review shell.
   *
   * A container around the four review modes, not a rewrite of any of them:
   * Word mode is the existing translationCore-compatible alignment editor,
   * mounted unchanged. Bridge's semantic relationships are never converted
   * into native translationCore alignment groups here.
   *
   * Semantic and Passage modes present the same focused relationship that QA
   * mode selected, from the relationship's and the passage's point of view
   * respectively. Selecting a finding in QA mode is what gives the other two
   * something to show.
   */
  export let chapter: string;
  export let verse: string | null = null;
  export let onClose: () => void = () => {};

  type Mode = "word" | "semantic" | "passage" | "qa";

  const MODES: Array<{ id: Mode; label: string }> = [
    { id: "word", label: "Word" },
    { id: "semantic", label: "Semantic" },
    { id: "passage", label: "Passage" },
    { id: "qa", label: "QA" },
  ];

  /** QA mode is the Stage 9A work surface, so it opens there. */
  export let mode: Mode = "qa";

  let tabRefs: Record<string, HTMLButtonElement | null> = {};

  function select(next: Mode): void {
    mode = next;
  }

  /**
   * Arrow-key tab navigation, per the WAI-ARIA tabs pattern: the tablist is
   * one tab stop and arrows move between tabs.
   */
  function onTabKeydown(event: KeyboardEvent, index: number): void {
    const keys: Record<string, number> = {
      ArrowRight: 1, ArrowLeft: -1, Home: -index, End: MODES.length - 1 - index,
    };
    const delta = keys[event.key];
    if (delta === undefined) return;
    event.preventDefault();
    const next = MODES[(index + delta + MODES.length) % MODES.length];
    select(next.id);
    tabRefs[next.id]?.focus();
  }

  function onKeydown(event: KeyboardEvent): void {
    if (event.key === "Escape") {
      event.preventDefault();
      onClose();
    }
  }
</script>

<svelte:window on:keydown={onKeydown} />

<section class="review" aria-label="Alignment review">
  <header class="bar">
    <h2>Alignment Review</h2>
    <div class="tablist" role="tablist" aria-label="Review modes">
      {#each MODES as item, index}
        <button
          bind:this={tabRefs[item.id]}
          type="button"
          role="tab"
          id="review-tab-{item.id}"
          aria-selected={mode === item.id}
          aria-controls="review-panel-{item.id}"
          tabindex={mode === item.id ? 0 : -1}
          class="tab"
          class:active={mode === item.id}
          on:click={() => select(item.id)}
          on:keydown={(event) => onTabKeydown(event, index)}
        >
          {item.label}
        </button>
      {/each}
    </div>
    <button type="button" class="close" on:click={onClose} aria-label="Close alignment review">
      Close
    </button>
  </header>

  <div class="body">
    {#if mode === "word"}
      <div id="review-panel-word" role="tabpanel" aria-labelledby="review-tab-word" class="panel">
        {#if verse}
          <!-- The existing translationCore-compatible editor, unmodified. -->
          <AlignmentModal {chapter} {verse} onClose={() => select("qa")} />
        {:else}
          <p class="placeholder">Select a verse to align its words.</p>
        {/if}
      </div>
    {:else if mode === "semantic"}
      <div id="review-panel-semantic" role="tabpanel" aria-labelledby="review-tab-semantic" class="panel">
        <SemanticAlignmentMode detail={$selectedDetail} loading={$detailLoading} />
      </div>
    {:else if mode === "passage"}
      <div id="review-panel-passage" role="tabpanel" aria-labelledby="review-tab-passage" class="panel">
        <PassageAlignmentMode detail={$selectedDetail} />
      </div>
    {:else}
      <div id="review-panel-qa" role="tabpanel" aria-labelledby="review-tab-qa" class="panel">
        <AlignmentQaMode {chapter} {verse} />
      </div>
    {/if}
  </div>
</section>

<style>
  .review {
    display: flex;
    flex-direction: column;
    height: 100%;
    min-height: 0;
    background: #fff;
  }

  .bar {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    padding: 0.4rem 0.7rem;
    border-bottom: 1px solid #e5e7eb;
    background: #f9fafb;
    flex: none;
    flex-wrap: wrap;
  }

  h2 { margin: 0; font-size: 0.9rem; }

  .tablist { display: flex; gap: 0.2rem; flex: 1 1 auto; }

  .tab {
    font: inherit;
    font-size: 0.8rem;
    padding: 0.25rem 0.7rem;
    border: 1px solid transparent;
    border-radius: 4px 4px 0 0;
    background: none;
    color: #4b5563;
    cursor: pointer;
  }

  /* The selected tab is marked by an underline and weight as well as fill,
     so it stays distinguishable without colour. */
  .tab.active {
    background: #fff;
    color: #111827;
    font-weight: 600;
    border-color: #e5e7eb;
    border-bottom: 2px solid #2563eb;
  }

  .tab:focus-visible { outline: 2px solid #2563eb; outline-offset: 1px; }

  .close {
    font: inherit;
    font-size: 0.78rem;
    padding: 0.25rem 0.6rem;
    border: 1px solid #d1d5db;
    border-radius: 4px;
    background: #fff;
    cursor: pointer;
  }

  .close:focus-visible { outline: 2px solid #2563eb; outline-offset: 1px; }

  .body { flex: 1 1 auto; min-height: 0; display: flex; }
  .panel { flex: 1 1 auto; min-height: 0; min-width: 0; display: flex; flex-direction: column; }
  .placeholder { padding: 1.25rem; color: #6b7280; font-size: 0.85rem; max-width: 44rem; }
</style>
