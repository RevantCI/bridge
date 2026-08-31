<script lang="ts">
  import { onMount } from "svelte";
  import { bridge } from "../api/bridgeClient";
  import {
    alignmentStatusByVerse, checkStatusByVerse, currentChapter, findingsByVerse,
    verseKey,
  } from "../stores";
  import type { AlignmentContext, AlignmentGroupView, AlignmentToken } from "../types/finding";
  import LexiconPopup from "./LexiconPopup.svelte";

  export let chapter: string;
  export let verse: string;
  export let onClose: () => void;

  let context: AlignmentContext | null = null;
  let lexiconToken: AlignmentToken | null = null;
  let loading = true;
  let busy = false;
  let error = "";
  let notice = "";
  let restoreId = "";

  // Interlinear drag/click-to-align state. `pickedUpId` is the click-based
  // accessible alternative to dragging: click a target word to pick it up,
  // click a column (or the word bank) to drop it there — same one-step
  // "drop" semantics as dragging, just keyboard/click operable.
  let pickedUpId: string | null = null;
  let dragOverColumn: string | null = null;
  let dragOverBank = false;

  // Pointer-based (not native HTML5) drag-and-drop. Tauri's window-level
  // dragDropEnabled — real, load-bearing for the "drop a file to import"
  // feature in ImportScreen.svelte/App.svelte — intercepts the browser's
  // native drag events before the page ever sees them, so draggable/
  // dragstart/dragover/drop are silently inert inside this webview.
  // Pointer events aren't part of that native drag protocol, so a
  // from-scratch pointer-tracked drag with a floating ghost works instead.
  let dragTokenId: string | null = null;
  let dragStart: { x: number; y: number } | null = null;
  let dragMoved = false;
  let ghostPos = { x: 0, y: 0 };
  let suppressClickId: string | null = null;
  const DRAG_THRESHOLD = 6;

  $: ghostLabel = dragTokenId ? (context?.bottomTokens.find((t) => t.id === dragTokenId)?.word ?? "") : "";

  // Resolved lexicon gloss per source token id, for the hover tooltip (item b).
  // Fetched once on load — source tokens don't change across alignment edits.
  let meaningByToken: Record<string, string> = {};

  onMount(load);

  onMount(() => {
    window.addEventListener("pointermove", handlePointerMove);
    window.addEventListener("pointerup", handlePointerUp);
    return () => {
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointerup", handlePointerUp);
    };
  });

  async function load() {
    loading = true;
    error = "";
    try {
      context = await bridge.getAlignment(chapter, verse);
      restoreId = context.history[0]?.id ?? "";
      void loadMeanings(context.topTokens);
    } catch (value) {
      error = value instanceof Error ? value.message : String(value);
    } finally {
      loading = false;
    }
  }

  async function loadMeanings(tokens: AlignmentToken[]) {
    const cache = new Map<string, string>();
    await Promise.all(
      tokens
        .filter((t) => t.strong || t.morph)
        .map(async (t) => {
          const key = `${t.strong ?? ""}|${t.morph ?? ""}`;
          if (!cache.has(key)) {
            try {
              const entry = await bridge.getLexiconEntry(t.strong ?? "", t.morph ?? "");
              cache.set(key, entry.segments.map((s) => s.meaning || s.lemma).filter(Boolean).join("; "));
            } catch {
              cache.set(key, "");
            }
          }
          meaningByToken[t.id] = cache.get(key) ?? "";
        }),
    );
    meaningByToken = { ...meaningByToken };
  }

  function label(token: AlignmentToken): string {
    return token.occurrences > 1 ? `${token.word} ${token.occurrence}/${token.occurrences}` : token.word;
  }

  function sourceTitle(token: AlignmentToken): string {
    return meaningByToken[token.id] || [token.lemma, token.strong, token.morph].filter(Boolean).join(" · ");
  }

  function targetGroup(id: string): string {
    if (!context) return "";
    return context.groups.find((group) => group.bottomIds.includes(id))?.id ?? "";
  }

  function groupForSource(sourceId: string): AlignmentGroupView | undefined {
    return context?.groups.find((group) => group.topIds.includes(sourceId));
  }

  function alignedTargetsFor(sourceId: string): AlignmentToken[] {
    if (!context) return [];
    const group = groupForSource(sourceId);
    if (!group) return [];
    return group.bottomIds
      .map((id) => context!.bottomTokens.find((b) => b.id === id))
      .filter((item): item is AlignmentToken => Boolean(item));
  }

  $: unalignedTokens = context ? context.bottomTokens.filter((item) => !targetGroup(item.id)) : [];
  $: unalignedCount = unalignedTokens.length;

  async function refreshChecks(updated: AlignmentContext, message: string) {
    context = updated;
    restoreId = updated.history[0]?.id ?? "";
    const key = verseKey(chapter, verse);
    alignmentStatusByVerse.update((values) => ({ ...values, [key]: updated.status }));
    checkStatusByVerse.update((values) => ({ ...values, [key]: "pending" }));
    try {
      // `alignment` runs the verse-local QA set without starting the much
      // slower whole-book USFM preflight. The background job remains the
      // source of book-structural findings.
      const findings = await bridge.runVerseChecks(chapter, verse, ["alignment", "greekroom"]);
      findingsByVerse.update((values) => ({ ...values, [key]: findings }));
      checkStatusByVerse.update((values) => ({ ...values, [key]: "succeeded" }));
      notice = `${message} Local and Greek Room checks are current.`;
    } catch (value) {
      checkStatusByVerse.update((values) => ({ ...values, [key]: "failed" }));
      error = `${message} The save succeeded, but rechecking failed: ${value instanceof Error ? value.message : String(value)}`;
    }
  }

  async function mutate(action: () => Promise<AlignmentContext>, message: string) {
    if (busy) return;
    busy = true;
    error = "";
    notice = "";
    try {
      await refreshChecks(await action(), message);
    } catch (value) {
      error = value instanceof Error ? value.message : String(value);
    } finally {
      busy = false;
    }
  }

  // Every drop/click-drop realigns the source column's FULL target set
  // (existing members + the newly placed word) — realign() replaces
  // whatever group the given top id belongs to, so this must include the
  // words already there or they'd be bumped back to the word bank.
  function dropOntoColumn(targetId: string, sourceId: string) {
    if (!context) return;
    const destGroup = groupForSource(sourceId);
    if (destGroup?.bottomIds.includes(targetId)) return; // already in this column
    const existingBottomIds = (destGroup?.bottomIds ?? []).filter((id) => id !== targetId);
    void mutate(
      () => bridge.realignWords(chapter, verse, [sourceId], [...existingBottomIds, targetId], context!.alignment),
      "Alignment saved.",
    );
  }

  function returnToBank(targetId: string) {
    if (!context || !targetGroup(targetId)) return;
    void mutate(
      () => bridge.unalignWords(chapter, verse, [targetId], context!.alignment),
      "Returned to word bank.",
    );
  }

  function handleWordClick(id: string) {
    if (busy) return;
    if (suppressClickId === id) { suppressClickId = null; return; }
    pickedUpId = pickedUpId === id ? null : id;
  }

  function handleColumnClick(sourceId: string) {
    if (!pickedUpId || busy) return;
    const id = pickedUpId;
    pickedUpId = null;
    dropOntoColumn(id, sourceId);
  }

  function handleBankAreaClick() {
    if (!pickedUpId || busy) return;
    const id = pickedUpId;
    pickedUpId = null;
    returnToBank(id);
  }

  function startPointerTrack(event: PointerEvent, id: string) {
    if (busy || event.button !== 0) return;
    dragTokenId = id;
    dragStart = { x: event.clientX, y: event.clientY };
    dragMoved = false;
  }

  function updateHoverTargetFromPoint(x: number, y: number) {
    const el = document.elementFromPoint(x, y);
    const columnEl = el?.closest<HTMLElement>("[data-drop-column]");
    const bankEl = el?.closest<HTMLElement>("[data-drop-bank]");
    dragOverColumn = columnEl?.dataset.dropColumn ?? null;
    dragOverBank = Boolean(bankEl);
  }

  function handlePointerMove(event: PointerEvent) {
    if (!dragTokenId || !dragStart) return;
    const dx = event.clientX - dragStart.x;
    const dy = event.clientY - dragStart.y;
    if (!dragMoved && Math.hypot(dx, dy) > DRAG_THRESHOLD) {
      dragMoved = true;
      pickedUpId = null; // a real drag supersedes click-to-pick-up mode
    }
    if (dragMoved) {
      ghostPos = { x: event.clientX, y: event.clientY };
      updateHoverTargetFromPoint(event.clientX, event.clientY);
    }
  }

  function handlePointerUp(): void {
    if (!dragTokenId) return;
    const id = dragTokenId;
    const moved = dragMoved;
    const dropColumn = dragOverColumn;
    const dropBank = dragOverBank;
    dragTokenId = null;
    dragStart = null;
    dragMoved = false;
    dragOverColumn = null;
    dragOverBank = false;
    if (!moved) return; // the browser's own click event will fire next and handle pick-up
    suppressClickId = id;
    if (dropColumn) dropOntoColumn(id, dropColumn);
    else if (dropBank) returnToBank(id);
  }

  function undo() {
    if (!context) return;
    void mutate(
      () => bridge.undoAlignment(chapter, verse, context!.alignment),
      "Last alignment change undone.",
    );
  }

  function restore() {
    if (!context || !restoreId) return;
    void mutate(
      () => bridge.restoreAlignment(chapter, verse, restoreId, context!.alignment),
      "Selected alignment backup restored.",
    );
  }
</script>

<svelte:window on:keydown={(event) => event.key === "Escape" && !busy && !lexiconToken && onClose()} />

<div class="overlay" role="presentation">
  <section class="modal" role="dialog" aria-modal="true" aria-label={`Word alignment ${chapter}:${verse}`}>
    <header>
      <div>
        <div class="eyebrow">WORD ALIGNMENT</div>
        <h2>{chapter}:{verse} — align source and target words</h2>
      </div>
      <button class="close" on:click={onClose} disabled={busy} aria-label="Close alignment editor">×</button>
    </header>

    {#if loading}
      <div class="loading"><span class="spin" /> Loading alignment…</div>
    {:else if context}
      <div class="summary">
        <span class="status {context.status}">Verse: {context.status}</span>
        <span>Chapter:</span>
        <span>{context.chapterStatus.complete} complete</span>
        <span>{context.chapterStatus.partial} partial</span>
        <span>{context.chapterStatus.untouched} untouched</span>
        {#if context.chapterStatus.invalid}<span class="danger">{context.chapterStatus.invalid} invalid</span>{/if}
      </div>

      {#if !context.sourceAvailable}
        <div class="source-warning">
          <strong>Original-language source unavailable</strong>
          <span>{context.sourceMessage}</span>
        </div>
      {:else if unalignedCount > 0}
        <div class="alignment-flag">
          ⚑ Not fully aligned — {unalignedCount} target word{unalignedCount === 1 ? "" : "s"} still
          {unalignedCount === 1 ? "needs" : "need"} a source word. Drag or click a word bank item below, then a
          column, to align it.
        </div>
      {:else if context.status === "invalid"}
        <div class="alignment-flag">⚑ Alignment has structural issues — see below.</div>
      {/if}

      {#if context.issues.length > 0}
        <div class="issues">
          {#each context.issues as issue}<div>⚠ {issue}</div>{/each}
        </div>
      {/if}

      {#if notice}<div class="notice">✓ {notice}</div>{/if}
      {#if error}<div class="error">{error}</div>{/if}

      <div class="workspace">
        <div class="interlinear" dir={context.sourceDirection}>
          {#each context.topTokens as src (src.id)}
            <div class="column">
              <button
                class="token source"
                on:click={() => (lexiconToken = src)}
                disabled={busy}
                title={sourceTitle(src)}
              >
                <span>{label(src)}</span>
                {#if src.lemma}<small>{src.lemma}</small>{/if}
              </button>
              <div
                class="target-cell"
                class:drop-hover={dragOverColumn === src.id}
                data-drop-column={src.id}
                dir={context.targetDirection}
                role="button"
                tabindex="0"
                aria-label={pickedUpId ? `Align picked-up word to ${src.word}` : `Target words aligned to ${src.word}`}
                on:click={() => handleColumnClick(src.id)}
                on:keydown={(event) => (event.key === "Enter" || event.key === " ") && (event.preventDefault(), handleColumnClick(src.id))}
              >
                {#each alignedTargetsFor(src.id) as item (item.id)}
                  <div class="token target aligned-card" title={`Aligned to ${src.word}`}>
                    <span class="word">{label(item)}</span>
                    <button
                      type="button"
                      class="unalign-x"
                      on:click|stopPropagation={() => returnToBank(item.id)}
                      disabled={busy}
                      aria-label={`Unalign ${item.word} from ${src.word}`}
                      title="Remove from this column"
                    >×</button>
                  </div>
                {:else}
                  <span class="placeholder" aria-hidden="true">·</span>
                {/each}
              </div>
            </div>
          {:else}
            <p class="empty">No source tokens are present in this verse.</p>
          {/each}
        </div>

        <section class="word-bank">
          <div class="panel-title">
            <span>Target words</span>
            <small>In verse order — drag an unaligned (blue) word into a column above, or click it then click a column</small>
          </div>
          <div
            class="tokens bank-tokens"
            class:drop-hover={dragOverBank}
            data-drop-bank="true"
            dir={context.targetDirection}
            role="button"
            tabindex="0"
            aria-label={pickedUpId ? "Return picked-up word to the word bank" : "Word bank"}
            on:click={handleBankAreaClick}
            on:keydown={(event) => (event.key === "Enter" || event.key === " ") && (event.preventDefault(), handleBankAreaClick())}
          >
            {#each context.bottomTokens as item (item.id)}
              {#if targetGroup(item.id)}
                <span class="token target already-aligned" title={`Already aligned`}>{label(item)}</span>
              {:else}
                <button
                  type="button"
                  class="token target unaligned"
                  class:picked={pickedUpId === item.id}
                  on:pointerdown={(event) => startPointerTrack(event, item.id)}
                  on:click|stopPropagation={() => handleWordClick(item.id)}
                  disabled={busy}
                >{label(item)}</button>
              {/if}
            {:else}
              <p class="empty">This verse has no target words.</p>
            {/each}
          </div>
        </section>
      </div>

      <footer>
        <div class="history-controls">
          <button on:click={undo} disabled={busy || context.history.length === 0}>Undo last change</button>
          <select bind:value={restoreId} disabled={busy || context.history.length === 0} aria-label="Alignment backup">
            {#each context.history as item}
              <option value={item.id}>{item.timestamp} · {item.operation}</option>
            {/each}
          </select>
          <button on:click={restore} disabled={busy || !restoreId}>Restore selected</button>
        </div>
        <div class="completion">
          {#if context.completionState === "completed"}<span class="completed">✓ Human-completed</span>{/if}
        </div>
      </footer>
    {:else if error}
      <div class="error">{error}</div>
    {/if}
  </section>
</div>

{#if lexiconToken}
  <LexiconPopup
    token={lexiconToken}
    direction={context?.sourceDirection ?? "rtl"}
    onClose={() => (lexiconToken = null)}
  />
{/if}

{#if dragTokenId && dragMoved}
  <div class="drag-ghost" style="left:{ghostPos.x}px; top:{ghostPos.y}px;">{ghostLabel}</div>
{/if}

<style>
  .overlay { position: fixed; inset: 0; z-index: 50; background: rgba(15, 20, 26, .58); display: grid; place-items: center; padding: 24px; }
  .modal { width: min(1040px, 100%); max-height: calc(100vh - 48px); overflow: auto; background: var(--surface); border-radius: 16px; box-shadow: 0 24px 80px rgba(0,0,0,.24); padding: 20px; color: var(--text); }
  header { display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; border-bottom: 1px solid var(--border); padding-bottom: 14px; }
  .eyebrow { color: var(--accent); font-size: 10px; letter-spacing: .12em; font-weight: 800; }
  h2 { margin: 4px 0 0; font-size: 18px; }
  button, select { font: inherit; }
  button { border: 1px solid var(--border-strong); background: var(--surface); color: var(--text); border-radius: 7px; padding: 7px 10px; cursor: pointer; }
  button:hover:not(:disabled) { border-color: var(--accent); }
  button:disabled { opacity: .5; cursor: not-allowed; }
  .close { border: 0; font-size: 24px; padding: 0 5px; color: var(--text-2); }
  .loading { padding: 36px; display: flex; gap: 10px; justify-content: center; color: var(--text-2); }
  .spin { width: 12px; height: 12px; border: 2px solid var(--accent-bg); border-top-color: var(--accent); border-radius: 50%; animation: spin .8s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .summary { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; font-size: 11px; color: var(--text-2); padding: 12px 0; }
  .status { border-radius: 999px; padding: 3px 8px; background: var(--surface-2); font-weight: 700; }
  .status.complete, .completed { color: var(--success); background: #EAF7EF; }
  .status.partial { color: var(--warning); background: var(--warning-bg); }
  .status.invalid, .danger { color: var(--danger); }
  .source-warning, .issues, .notice, .error, .alignment-flag { border-radius: 9px; padding: 10px 12px; margin-bottom: 12px; font-size: 12px; line-height: 1.45; }
  .source-warning { display: flex; flex-direction: column; gap: 3px; background: var(--warning-bg); color: var(--warning); }
  .alignment-flag { background: var(--warning-bg); color: var(--warning); font-weight: 600; }
  .issues { background: #FFF5F5; color: var(--danger); }
  .notice { background: #EAF7EF; color: var(--success); }
  .error { background: #FFF0F0; color: var(--danger); }
  .workspace { display: flex; flex-direction: column; gap: 14px; }
  .interlinear { display: flex; gap: 10px; overflow-x: auto; padding: 12px 6px; border: 1px solid var(--border); border-radius: 10px; min-height: 128px; }
  .column { display: flex; flex-direction: column; align-items: center; gap: 6px; min-width: 76px; flex-shrink: 0; }
  .target-cell {
    display: flex; flex-direction: column; align-items: center; gap: 4px; width: 100%; box-sizing: border-box;
    min-height: 36px; justify-content: flex-end; padding: 4px; border-radius: 8px;
  }
  .target-cell.drop-hover { background: var(--accent-bg); outline: 2px dashed var(--accent); }
  .target-cell .placeholder { color: var(--text-3); font-size: 16px; line-height: 1; padding-bottom: 6px; }
  .panel-title { display: flex; justify-content: space-between; gap: 10px; font-size: 12px; font-weight: 700; margin-bottom: 10px; }
  .panel-title small { color: var(--text-3); font-weight: 400; }
  .token { display: inline-flex; flex-direction: column; align-items: center; gap: 2px; min-width: 62px; }
  .token small { font-size: 9px; color: var(--text-3); max-width: 130px; overflow: hidden; text-overflow: ellipsis; }
  .column .token.source { width: 100%; background: #F6F1FF; cursor: pointer; }
  .token.target { touch-action: none; user-select: none; }
  .token.target.unaligned { background: #EFF7FF; border-color: var(--border-strong); color: var(--text); }
  .token.picked { outline: 2px solid var(--accent); outline-offset: 1px; }
  .already-aligned {
    background: var(--surface-2); border: 1px solid var(--border); color: var(--text-3);
    padding: 7px 10px; border-radius: 7px; cursor: default;
  }
  .aligned-card {
    flex-direction: row; align-items: center; gap: 4px; min-width: 0;
    border: 1px solid var(--border-strong); border-radius: 7px; padding: 5px 6px 5px 10px;
    background: #EFF7FF; color: var(--text); cursor: default; font: inherit;
  }
  .aligned-card .word { font-size: 12px; }
  .unalign-x {
    border: 0; background: none; padding: 0; width: 16px; height: 16px; line-height: 1;
    display: inline-flex; align-items: center; justify-content: center; border-radius: 50%;
    color: var(--text-2); font-size: 13px; cursor: pointer; flex-shrink: 0;
  }
  .unalign-x:hover:not(:disabled) { color: var(--danger); background: var(--danger-bg); }
  .word-bank { border: 1px solid var(--border); border-radius: 10px; padding: 12px; }
  .bank-tokens { display: flex; flex-wrap: wrap; gap: 7px; min-height: 46px; align-content: flex-start; border-radius: 8px; padding: 4px; }
  .bank-tokens.drop-hover { background: var(--accent-bg); outline: 2px dashed var(--accent); }
  .drag-ghost {
    position: fixed; z-index: 999; transform: translate(-50%, -130%); pointer-events: none;
    background: var(--accent); color: white; font-size: 12px; font-weight: 700;
    border-radius: 7px; padding: 6px 10px; box-shadow: 0 8px 20px rgba(0,0,0,.28);
  }
  .empty { color: var(--text-3); font-size: 11px; margin: 6px; }
  footer { display: flex; justify-content: space-between; gap: 12px; align-items: center; flex-wrap: wrap; }
  .history-controls, .completion { display: flex; align-items: center; gap: 7px; }
  select { border: 1px solid var(--border-strong); border-radius: 7px; padding: 7px; max-width: 235px; color: var(--text); background: var(--surface); }
  .completed { font-size: 11px; font-weight: 700; padding: 5px 8px; border-radius: 999px; }
  @media (max-width: 780px) {
    .modal { padding: 14px; }
    footer { align-items: stretch; }
    .history-controls, .completion { flex-wrap: wrap; }
  }
</style>
