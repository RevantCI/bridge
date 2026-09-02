<script lang="ts">
  import { createEventDispatcher } from "svelte";

  import type { PassageVerse } from "../types/qaReview";

  /**
   * A virtualized target passage stream.
   *
   * Deliberately not one column per verse: a passage may be a whole book, and
   * fixed columns stop scaling almost immediately. Verses are rows in a
   * windowed scroller, collapsed by default and expanded on demand, so the
   * DOM holds a screenful rather than a passage.
   *
   * Connector detail is drawn only for the focused relationship. A full
   * passage graph would be unreadable and would imply relationships the
   * reviewer has not asked about.
   */
  export let verses: PassageVerse[] = [];
  export let focusedRelationshipIds: string[] = [];
  export let expandedReference = "";
  export let search = "";

  const dispatch = createEventDispatcher<{ expand: { reference: string } }>();

  const COLLAPSED_HEIGHT = 34;
  const VIRTUALIZE_ABOVE = 40;

  let viewport: HTMLDivElement | null = null;
  let scrollTop = 0;
  let viewportHeight = 420;

  $: focused = new Set(focusedRelationshipIds);

  // Search narrows the stream itself, so the window is computed over what is
  // actually shown rather than over everything loaded.
  $: shown = search.trim()
    ? verses.filter((verse) =>
        verse.text.toLowerCase().includes(search.trim().toLowerCase())
        || verse.reference.toLowerCase().includes(search.trim().toLowerCase()))
    : verses;

  $: virtualized = shown.length > VIRTUALIZE_ABOVE && !expandedReference;
  $: firstIndex = virtualized ? Math.max(0, Math.floor(scrollTop / COLLAPSED_HEIGHT) - 5) : 0;
  $: lastIndex = virtualized
    ? Math.min(shown.length, Math.ceil((scrollTop + viewportHeight) / COLLAPSED_HEIGHT) + 5)
    : shown.length;
  $: visible = shown.slice(firstIndex, lastIndex);
  $: topPad = virtualized ? firstIndex * COLLAPSED_HEIGHT : 0;
  $: bottomPad = virtualized ? Math.max(0, (shown.length - lastIndex) * COLLAPSED_HEIGHT) : 0;

  function onScroll(event: Event): void {
    const element = event.currentTarget as HTMLDivElement;
    scrollTop = element.scrollTop;
    viewportHeight = element.clientHeight;
  }

  function isFocused(verse: PassageVerse): boolean {
    return verse.relationshipIds.some((id) => focused.has(id));
  }

  function toggle(reference: string): void {
    dispatch("expand", { reference: expandedReference === reference ? "" : reference });
  }
</script>

<div class="stream">
  <label class="search">
    <span class="visually-hidden">Search the target passage</span>
    <input type="search" bind:value={search} placeholder="Search the target passage…" />
  </label>

  <p class="count" aria-live="polite">
    {shown.length} of {verses.length} {verses.length === 1 ? "verse" : "verses"}
  </p>

  <div class="viewport" bind:this={viewport} on:scroll={onScroll}>
    {#if shown.length === 0}
      <p class="empty">No verses match that search.</p>
    {:else}
      <div style="height: {topPad}px" aria-hidden="true"></div>
      {#each visible as verse (verse.reference)}
        {@const open = expandedReference === verse.reference}
        <div class="verse" class:focused={isFocused(verse)} class:open>
          <button
            type="button"
            class="verse-head"
            aria-expanded={open}
            on:click={() => toggle(verse.reference)}
          >
            <span class="caret" aria-hidden="true">{open ? "▾" : "▸"}</span>
            <span class="reference">{verse.reference}</span>
            <span class="preview">{verse.text}</span>
            <span class="marks">
              {#if isFocused(verse)}<span class="mark focus" title="Carries the focused relationship">◆</span>{/if}
              {#if verse.crossVerse}<span class="mark" title="Cross-verse realization">↔</span>{/if}
              {#if verse.splitOrMerged}<span class="mark" title="Split or merged realization">⋔</span>{/if}
              {#if verse.hasFinding}<span class="mark" title="Has a possible issue">?</span>{/if}
              {#if verse.reviewed}<span class="mark" title="Reviewed by a human">✓</span>{/if}
              {#if verse.stale}<span class="mark" title="Stale">↻</span>{/if}
            </span>
          </button>

          {#if open}
            <div class="verse-body">
              <p class="scripture">{verse.text}</p>
              {#if isFocused(verse)}
                <p class="connector">
                  <span aria-hidden="true">└─</span>
                  The focused source meaning is realized here.
                </p>
              {:else if verse.relationshipIds.length}
                <p class="muted small">
                  {verse.relationshipIds.length} other
                  {verse.relationshipIds.length === 1 ? "relationship lands" : "relationships land"}
                  in this verse. Focus one in QA or Semantic mode to trace it.
                </p>
              {:else}
                <p class="muted small">No source meaning was located in this verse.</p>
              {/if}
            </div>
          {/if}
        </div>
      {/each}
      <div style="height: {bottomPad}px" aria-hidden="true"></div>
    {/if}
  </div>
</div>

<style>
  .stream { display: flex; flex-direction: column; min-height: 0; height: 100%; }

  .search { padding: 0.4rem 0.6rem 0.2rem; flex: none; }
  .search input {
    width: 100%;
    box-sizing: border-box;
    font: inherit;
    font-size: 0.8rem;
    padding: 0.3rem 0.5rem;
    border: 1px solid #d1d5db;
    border-radius: 4px;
  }

  .count { margin: 0; padding: 0 0.6rem 0.3rem; font-size: 0.72rem; color: #6b7280; flex: none; }

  .viewport { flex: 1 1 auto; min-height: 0; overflow-y: auto; }

  .verse { border-bottom: 1px solid #f1f5f9; }

  /* The focused relationship is marked by a rule and a glyph, not colour
     alone, so it survives greyscale and high-contrast modes. */
  .verse.focused { box-shadow: inset 3px 0 0 #2563eb; background: #f8fbff; }

  .verse-head {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    width: 100%;
    box-sizing: border-box;
    height: 34px;
    padding: 0 0.6rem;
    border: none;
    background: none;
    font: inherit;
    font-size: 0.8rem;
    text-align: left;
    cursor: pointer;
  }

  .verse-head:focus-visible { outline: 2px solid #2563eb; outline-offset: -2px; }
  .verse.open .verse-head { height: auto; padding-top: 0.3rem; padding-bottom: 0.2rem; }

  .caret { color: #9ca3af; flex: none; }
  .reference { font-weight: 600; flex: none; min-width: 4rem; }

  .preview {
    flex: 1 1 auto;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: #4b5563;
  }

  .verse.open .preview { display: none; }

  .marks { flex: none; display: flex; gap: 0.25rem; color: #6b7280; }
  .mark { font-size: 0.75rem; }
  .mark.focus { color: #2563eb; }

  .verse-body { padding: 0 0.6rem 0.6rem 1.6rem; }
  .scripture { margin: 0 0 0.4rem; font-size: 1rem; line-height: 1.8; overflow-wrap: anywhere; }
  .connector { margin: 0; font-size: 0.78rem; color: #1d4ed8; }
  .muted { color: #6b7280; }
  .small { font-size: 0.75rem; }
  .empty { padding: 1rem 0.6rem; font-size: 0.8rem; color: #6b7280; }

  .visually-hidden {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip: rect(0 0 0 0);
    white-space: nowrap;
  }
</style>
