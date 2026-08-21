<script lang="ts">
  import { tick } from "svelte";
  import { verseNums, verseTexts, findingsByVerse, checkStatusByVerse, alignmentStatusByVerse, selectedVerse, currentChapter, showSource, verseKey } from "../stores";
  import { buildSegments } from "../utils/highlight";

  export let onSelect: (verse: string) => void;

  let scrollContainer: HTMLDivElement;
  let lastScrolledKey = "";

  async function scrollSelectedToTop(key: string): Promise<void> {
    await tick();
    const target = scrollContainer?.querySelector<HTMLElement>(`[data-verse-key="${key}"]`);
    if (!target) return;
    const containerRect = scrollContainer.getBoundingClientRect();
    const targetRect = target.getBoundingClientRect();
    scrollContainer.scrollTo({
      top: Math.max(0, scrollContainer.scrollTop + targetRect.top - containerRect.top - 8),
      behavior: "smooth",
    });
    lastScrolledKey = key;
  }

  $: {
    const key = $selectedVerse ? verseKey($currentChapter, $selectedVerse) : "";
    if (key && scrollContainer && key !== lastScrolledKey) void scrollSelectedToTop(key);
  }
</script>

<div class="editor-scroll" class:show-source={$showSource} bind:this={scrollContainer}>
  <div class="chapter-label">Chapter {$currentChapter}</div>

  {#each $verseNums as v}
    {@const key = verseKey($currentChapter, v)}
    {@const findings = $findingsByVerse[key] ?? []}
    {@const checkStatus = $checkStatusByVerse[key]}
    {@const alignmentStatus = $alignmentStatusByVerse[key] ?? "untouched"}
    {@const openCount = findings.filter((f) => f.status === "open").length}
    {@const segments = buildSegments($verseTexts[key] ?? "", findings)}
    <div
      class="verse"
      data-verse-key={key}
      class:active={$selectedVerse === v}
      class:approved={checkStatus === "succeeded" && openCount === 0}
      class:check-failed={checkStatus === "failed" || checkStatus === "cancelled"}
      role="button"
      tabindex="0"
      on:click={() => onSelect(v)}
      on:keydown={(e) => (e.key === "Enter" || e.key === " ") && onSelect(v)}
    >
      <div class="vnum">
        {v}{#if checkStatus === "succeeded" && openCount === 0}&nbsp;✓{:else if checkStatus === "failed" || checkStatus === "cancelled"}&nbsp;⚠{/if}
      </div>
      <div class="vtext">
        {#each segments as seg}
          {#if seg.className}
            <mark class={seg.className}>{seg.text}</mark>
          {:else}
            {seg.text}
          {/if}
        {/each}
      </div>
      <span class="alignment-state {alignmentStatus}" title={`Alignment: ${alignmentStatus}`}>
        {alignmentStatus === "complete" ? "●" : alignmentStatus === "partial" ? "◐" : alignmentStatus === "invalid" ? "!" : "○"}
      </span>
    </div>
  {/each}

  {#if $verseNums.length === 0}
    <p class="empty">No verses loaded for this chapter yet.</p>
  {/if}
</div>

<style>
  .editor-scroll { flex: 1; overflow-y: auto; padding: 22px 32px; background: var(--surface); }
  .chapter-label { font-size: 11px; font-weight: 700; color: var(--text-3); text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 14px; }
  .verse { display: flex; gap: 10px; padding: 9px 10px; border-radius: 7px; margin-bottom: 2px; cursor: pointer; border: 1px solid transparent; }
  .verse:hover { background: var(--surface-2); }
  .verse.active { background: var(--accent-bg); border-color: #C7D9FB; }
  .vnum { font-size: 11px; font-weight: 700; color: var(--text-3); width: 26px; flex-shrink: 0; padding-top: 2px; }
  .verse.approved .vnum { color: var(--success); }
  .verse.check-failed .vnum { color: var(--danger, #ef4444); }
  .vtext { font-size: 16px; line-height: 1.85; color: var(--text); }
  .alignment-state { margin-left: auto; flex-shrink: 0; padding-top: 3px; font-size: 11px; color: var(--text-3); }
  .alignment-state.complete { color: var(--success); }
  .alignment-state.partial { color: var(--warning); }
  .alignment-state.invalid { color: var(--danger); font-weight: 800; }
  .empty { color: var(--text-3); font-size: 13px; }
</style>
