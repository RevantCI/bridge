<script lang="ts">
  import { tick } from "svelte";
  import { verseNums, verseTexts, findingsByVerse, checkStatusByVerse, alignmentStatusByVerse, selectedVerse, currentChapter, showSource, verseKey, nativeChecksByVerse, aiCheckReviewsByVerse } from "../stores";
  import { buildSegments } from "../utils/highlight";
  import { editingChapter, editingVerse, editText, editSaving, editError, saveVerseEdit, cancelVerseEdit } from "../verseEditor";

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

  // Grows the edit textarea to fit its full content (1, 2, or more lines)
  // with no scrollbar, plus one blank line of buffer at the bottom — rather
  // than a fixed rows="2" that scrolls for longer verses and wastes space
  // for short ones.
  function autosize(node: HTMLTextAreaElement) {
    const resize = () => {
      node.style.height = "auto";
      const lineHeight = parseFloat(getComputedStyle(node).lineHeight) || 20;
      const borderHeight = node.offsetHeight - node.clientHeight;
      node.style.height = `${node.scrollHeight + lineHeight + borderHeight}px`;
    };
    resize();
    node.addEventListener("input", resize);
    return { destroy: () => node.removeEventListener("input", resize) };
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
    {@const highlightFindings = findings.filter((f) => f.status !== "ignored" && f.status !== "accepted")}
    {@const segments = buildSegments($verseTexts[key] ?? "", highlightFindings, $nativeChecksByVerse[key] ?? [], $aiCheckReviewsByVerse[key] ?? [])}
    {@const isEditingThis = $editingChapter === $currentChapter && $editingVerse === v}
    <div
      class="verse"
      class:editing-row={isEditingThis}
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
      {#if isEditingThis}
        <div class="vedit" on:click|stopPropagation on:keydown|stopPropagation role="presentation">
          <div class="vedit-row">
            <textarea use:autosize bind:value={$editText} disabled={$editSaving} />
            <div class="edit-actions">
              <button
                class="icon-btn save" on:click={() => void saveVerseEdit()}
                disabled={$editSaving || $editText.trim() === ""}
                title={$editSaving ? "Saving…" : "Save & re-check"}
              >{#if $editSaving}<span class="spin-sm" />{:else}✓{/if}</button>
              <button class="icon-btn cancel" on:click={cancelVerseEdit} disabled={$editSaving} title="Cancel">✕</button>
            </div>
          </div>
          {#if $editError}<p class="edit-error">{$editError}</p>{/if}
        </div>
      {:else}
        <div class="vtext">
          {#each segments as seg}
            {#if seg.className}
              <mark class={seg.className} title={seg.title}>{seg.text}</mark>{#if seg.numbers.length}<sup class="finding-num">{seg.numbers.join(",")}</sup>{/if}
            {:else}
              {seg.text}
            {/if}
          {/each}
        </div>
        <span class="alignment-state {alignmentStatus}" title={`Alignment: ${alignmentStatus}`}>
          {alignmentStatus === "complete" ? "●" : alignmentStatus === "partial" ? "◐" : alignmentStatus === "invalid" ? "!" : "○"}
        </span>
      {/if}
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
  .finding-num { font-size: 10px; font-weight: 700; color: var(--accent); margin-left: 1px; }
  .alignment-state { margin-left: auto; flex-shrink: 0; padding-top: 3px; font-size: 11px; color: var(--text-3); }
  .alignment-state.complete { color: var(--success); }
  .alignment-state.partial { color: var(--warning); }
  .alignment-state.invalid { color: var(--danger); font-weight: 800; }
  .empty { color: var(--text-3); font-size: 13px; }
  .verse.editing-row { cursor: default; background: var(--surface); border-color: var(--accent); }
  .vedit { flex: 1; min-width: 0; cursor: default; }
  .vedit-row { display: flex; align-items: flex-start; gap: 8px; }
  .vedit textarea {
    flex: 1; min-width: 0; box-sizing: border-box; font-size: 16px; line-height: 1.7; color: var(--text);
    font-family: inherit; padding: 10px 12px; border: 1px solid var(--accent); border-radius: 8px;
    resize: none; overflow-y: hidden;
  }
  .vedit textarea:disabled { opacity: .6; }
  .edit-error { color: var(--danger); font-size: 11px; margin: 6px 0 0; line-height: 1.4; }
  .edit-actions { display: flex; flex-direction: column; gap: 6px; flex-shrink: 0; }
  .icon-btn {
    width: 32px; height: 32px; padding: 0; font-size: 15px; font-weight: 800; border-radius: 7px;
    border: none; cursor: pointer; display: flex; align-items: center; justify-content: center;
  }
  .icon-btn.save { background: var(--accent); color: white; }
  .icon-btn.cancel { background: var(--surface-2); color: var(--text-2); border: 1px solid var(--border-strong); }
  .icon-btn:disabled { opacity: .55; cursor: not-allowed; }
  .spin-sm { width: 12px; height: 12px; border-radius: 50%; border: 2px solid rgba(255,255,255,0.4); border-top-color: #fff; animation: spin-sm 0.8s linear infinite; }
  @keyframes spin-sm { to { transform: rotate(360deg); } }
</style>
