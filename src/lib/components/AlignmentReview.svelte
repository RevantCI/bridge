<script lang="ts">
  import AlignmentQaMode from "./AlignmentQaMode.svelte";

  /**
   * The Alignment Review shell.
   *
   * This was a four-tab container (Word, Semantic, Passage, QA). #129 removed
   * three of them, so there is nothing left to tab between and the tablist is
   * gone with them:
   *
   * - Semantic and Passage were read-only re-presentations of the finding QA
   *   mode had already selected, superseded by the cross-verse alignment page
   *   (#116-#119). Audit B7 held them pending exactly that page.
   * - Word was a *second* entry point to `AlignmentModal`. The editor itself is
   *   untouched and still opens as the Align Words popup from the verse view --
   *   it is the only thing that creates completed alignments, which the
   *   cross-verse proposers learn from.
   *
   * What remains is the Stage 9A QA work surface, which this now mounts
   * directly.
   */
  export let chapter: string;
  export let verse: string | null = null;
  export let onClose: () => void = () => {};

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
    <button type="button" class="close" on:click={onClose} aria-label="Close alignment review">
      Close
    </button>
  </header>

  <div class="body">
    <div class="panel">
      <AlignmentQaMode {chapter} {verse} />
    </div>
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

  h2 { margin: 0; font-size: var(--fs-lg); flex: 1 1 auto; }

  .close {
    font: inherit;
    font-size: var(--fs-sm);
    padding: 0.25rem 0.6rem;
    border: 1px solid #d1d5db;
    border-radius: 4px;
    background: #fff;
    cursor: pointer;
  }

  .close:focus-visible { outline: 2px solid #2563eb; outline-offset: 1px; }

  .body { flex: 1 1 auto; min-height: 0; display: flex; }
  .panel { flex: 1 1 auto; min-height: 0; min-width: 0; display: flex; flex-direction: column; }
</style>
