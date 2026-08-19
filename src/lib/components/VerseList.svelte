<script lang="ts">
  import { verseNums, verseTexts, findingsByVerse, selectedVerse, currentChapter, showSource, verseKey } from "../stores";
  import { buildSegments } from "../utils/highlight";

  export let onSelect: (verse: string) => void;
</script>

<div class="editor-scroll" class:show-source={$showSource}>
  <div class="chapter-label">Chapter {$currentChapter}</div>

  {#each $verseNums as v}
    {@const key = verseKey($currentChapter, v)}
    {@const findings = $findingsByVerse[key] ?? []}
    {@const openCount = findings.filter((f) => f.status === "open").length}
    {@const segments = buildSegments($verseTexts[key] ?? "", findings)}
    <div
      class="verse"
      class:active={$selectedVerse === v}
      class:approved={findings.length > 0 && openCount === 0}
      role="button"
      tabindex="0"
      on:click={() => onSelect(v)}
      on:keydown={(e) => (e.key === "Enter" || e.key === " ") && onSelect(v)}
    >
      <div class="vnum">{v}{#if findings.length > 0 && openCount === 0}&nbsp;✓{/if}</div>
      <div class="vtext">
        {#each segments as seg}
          {#if seg.className}
            <mark class={seg.className}>{seg.text}</mark>
          {:else}
            {seg.text}
          {/if}
        {/each}
      </div>
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
  .vtext { font-size: 16px; line-height: 1.85; color: var(--text); }
  .empty { color: var(--text-3); font-size: 13px; }
</style>
