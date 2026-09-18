<script lang="ts">
  import { onMount } from "svelte";
  import { bridge } from "../api/bridgeClient";
  import {
    alignmentStatusByVerse, checkStatusByVerse, currentChapter, findingsByVerse,
    verseKey,
  } from "../stores";
  import type { AlignmentContext, AlignmentToken } from "../types/finding";
  import { createPointerDrag } from "../alignmentDrag";
  import { openCrossVerse } from "../alignmentUi";
  import {
    alignedTargetsFor, bottomIdsAfterDrop, groupForTarget, occurrenceLabel as occurrence, unaccountedTargets,
  } from "../alignmentGroups";
  import { SourceGlossCache } from "../lexiconGloss";
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

  // Pointer-based drag lives in alignmentDrag.ts (shared with the cross-verse
  // page, #116); see that file for why it is not native HTML5 drag-and-drop.
  // `data-drop-column` carries the source token id, `data-drop-bank` is "true".
  const drag = createPointerDrag({
    onDragStart: () => { pickedUpId = null; }, // a real drag supersedes click-to-pick-up mode
    onDrop: ({ tokenId, column, bank }) => {
      if (column) dropOntoColumn(tokenId, column);
      else if (bank) returnToBank(tokenId);
    },
  });
  const dragState = drag.state;

  $: ghostLabel = $dragState.tokenId ? (context?.bottomTokens.find((t) => t.id === $dragState.tokenId)?.word ?? "") : "";

  // Resolved lexicon glosses for the source tokens: the English sense goes
  // under the word and the lemma moves into the tooltip, because a lemma is
  // one more Greek/Hebrew string and tells a non-reader of those scripts
  // nothing. Fetched once on load — source tokens don't change across
  // alignment edits. `glossVersion` is what makes the labels re-render when
  // the lookups land.
  const glosses = new SourceGlossCache();
  let glossVersion = 0;

  onMount(load);

  onMount(() => drag.attach(window));

  async function load() {
    loading = true;
    error = "";
    try {
      context = await bridge.getAlignment(chapter, verse);
      restoreId = context.history[0]?.id ?? "";
      void glosses.load(context.topTokens).then(() => (glossVersion = glosses.version));
    } catch (value) {
      error = value instanceof Error ? value.message : String(value);
    } finally {
      loading = false;
    }
  }

  // `glossVersion` is read, not used, so Svelte re-invokes these once the
  // lexicon lookups resolve.
  function sourceGloss(token: AlignmentToken, _version: number): string {
    return glosses.glossFor(token).short;
  }

  function sourceTitle(token: AlignmentToken, _version: number): string {
    return glosses.glossFor(token).title;
  }

  // #117: a word that a cross-verse link accounts for is still in the tC word
  // bank (translationCore alignment is verse-local) but is no longer a gap.
  $: unalignedCount = context ? unaccountedTargets(context).length : 0;
  $: accountedIds = new Set(context?.crossVerseAccountedIds ?? []);
  $: accountedNote = context && context.crossVerseAccounted + context.crossVerseRealized > 0
    ? `${context.crossVerseAccounted + context.crossVerseRealized} word${context.crossVerseAccounted + context.crossVerseRealized === 1 ? "" : "s"} linked across verses (Bridge-private; completion stays with translationCore).`
    : "";

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
  // (existing members + the newly placed word); bottomIdsAfterDrop explains why.
  function dropOntoColumn(targetId: string, sourceId: string) {
    if (!context) return;
    const bottomIds = bottomIdsAfterDrop(context, sourceId, targetId);
    if (!bottomIds) return; // already in this column
    void mutate(
      () => bridge.realignWords(chapter, verse, [sourceId], bottomIds, context!.alignment),
      "Alignment saved.",
    );
  }

  function returnToBank(targetId: string) {
    if (!context || !groupForTarget(context, targetId)) return;
    void mutate(
      () => bridge.unalignWords(chapter, verse, [targetId], context!.alignment),
      "Returned to word bank.",
    );
  }

  function handleWordClick(id: string) {
    if (busy) return;
    if (drag.consumeSuppressedClick(id)) return;
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
    if (busy) return;
    drag.start(event, id);
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
        <button
          type="button"
          class="cross-verse-link"
          on:click={() => { onClose(); openCrossVerse(verse); }}
          disabled={busy}
          title="See this verse beside its neighbours"
        >Cross-verse alignment ›</button>
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
          {#if accountedNote}<span class="accounted-note">{accountedNote}</span>{/if}
        </div>
      {:else if context.fullyAccounted}
        <div class="accounted-flag">↔ {accountedNote}</div>
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
                title={sourceTitle(src, glossVersion)}
              >
                <span>{src.word}{#if src.occurrences > 1}<span class="occ">{occurrence(src)}</span>{/if}</span>
                {#if sourceGloss(src, glossVersion)}<small class="gloss">{sourceGloss(src, glossVersion)}</small>{/if}
              </button>
              <div
                class="target-cell"
                class:drop-hover={$dragState.overColumn === src.id}
                data-drop-column={src.id}
                dir={context.targetDirection}
                role="button"
                tabindex="0"
                aria-label={pickedUpId ? `Align picked-up word to ${src.word}` : `Target words aligned to ${src.word}`}
                on:click={() => handleColumnClick(src.id)}
                on:keydown={(event) => (event.key === "Enter" || event.key === " ") && (event.preventDefault(), handleColumnClick(src.id))}
              >
                {#each alignedTargetsFor(context, src.id) as item (item.id)}
                  <div class="token target aligned-card" title={`Aligned to ${src.word}`}>
                    <span class="word">{item.word}{#if item.occurrences > 1}<span class="occ">{occurrence(item)}</span>{/if}</span>
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
            class:drop-hover={$dragState.overBank !== null}
            data-drop-bank="true"
            dir={context.targetDirection}
            role="button"
            tabindex="0"
            aria-label={pickedUpId ? "Return picked-up word to the word bank" : "Word bank"}
            on:click={handleBankAreaClick}
            on:keydown={(event) => (event.key === "Enter" || event.key === " ") && (event.preventDefault(), handleBankAreaClick())}
          >
            {#each context.bottomTokens as item (item.id)}
              {#if accountedIds.has(item.id)}
                <span class="token target already-aligned accounted" title="Accounted for by a cross-verse link (see Cross-verse alignment)"><span class="word">{item.word}{#if item.occurrences > 1}<span class="occ">{occurrence(item)}</span>{/if}</span><small>↔</small></span>
              {:else if groupForTarget(context, item.id)}
                <span class="token target already-aligned" title={`Already aligned`}><span class="word">{item.word}{#if item.occurrences > 1}<span class="occ">{occurrence(item)}</span>{/if}</span></span>
              {:else}
                <button
                  type="button"
                  class="token target unaligned"
                  class:picked={pickedUpId === item.id}
                  on:pointerdown={(event) => startPointerTrack(event, item.id)}
                  on:click|stopPropagation={() => handleWordClick(item.id)}
                  disabled={busy}
                ><span class="word">{item.word}{#if item.occurrences > 1}<span class="occ">{occurrence(item)}</span>{/if}</span></button>
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

{#if $dragState.tokenId && $dragState.moved}
  <div class="drag-ghost" style="left:{$dragState.ghost.x}px; top:{$dragState.ghost.y}px;">{ghostLabel}</div>
{/if}

<style>
  .overlay { position: fixed; inset: 0; z-index: 50; background: rgba(15, 20, 26, .58); display: grid; place-items: center; padding: 24px; }
  .modal { width: min(1040px, 100%); max-height: calc(100vh - 48px); overflow: auto; background: var(--surface); border-radius: 16px; box-shadow: 0 24px 80px rgba(0,0,0,.24); padding: 20px; color: var(--text); }
  header { display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; border-bottom: 1px solid var(--border); padding-bottom: 14px; }
  .eyebrow { color: var(--accent); font-size: var(--fs-2xs); letter-spacing: .12em; font-weight: 800; }
  h2 { margin: 4px 0 0; font-size: var(--fs-2xl); }
  button, select { font: inherit; }
  button { border: 1px solid var(--border-strong); background: var(--surface); color: var(--text); border-radius: 7px; padding: 7px 10px; cursor: pointer; }
  button:hover:not(:disabled) { border-color: var(--accent); }
  button:disabled { opacity: .5; cursor: not-allowed; }
  .close { border: 0; font-size: var(--fs-5xl); padding: 0 5px; color: var(--text-2); }
  .cross-verse-link { border: 0; background: none; padding: 4px 0 0; color: var(--accent); font-size: var(--fs-xs); font-weight: 600; }
  .cross-verse-link:hover:not(:disabled) { text-decoration: underline; }
  .loading { padding: 36px; display: flex; gap: 10px; justify-content: center; color: var(--text-2); }
  .spin { width: 12px; height: 12px; border: 2px solid var(--accent-bg); border-top-color: var(--accent); border-radius: 50%; animation: spin .8s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .summary { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; font-size: var(--fs-xs); color: var(--text-2); padding: 12px 0; }
  .status { border-radius: 999px; padding: 3px 8px; background: var(--surface-2); font-weight: 700; }
  .status.complete, .completed { color: var(--success); background: #EAF7EF; }
  .status.partial { color: var(--warning); background: var(--warning-bg); }
  .status.invalid, .danger { color: var(--danger); }
  .source-warning, .issues, .notice, .error, .alignment-flag { border-radius: 9px; padding: 10px 12px; margin-bottom: 12px; font-size: var(--fs-sm); line-height: 1.45; }
  .source-warning { display: flex; flex-direction: column; gap: 3px; background: var(--warning-bg); color: var(--warning); }
  .alignment-flag { background: var(--warning-bg); color: var(--warning); font-weight: 600; }
  .accounted-note { display: block; margin-top: 4px; font-weight: 400; color: var(--text-2); }
  .accounted-flag { border-radius: 9px; padding: 10px 12px; margin-bottom: 12px; font-size: var(--fs-sm); background: var(--accent-bg); color: var(--accent); font-weight: 600; }
  .already-aligned.accounted { border-style: dashed; border-color: var(--accent); flex-direction: row; gap: 5px; }
  .already-aligned.accounted small { color: var(--accent); font-weight: 700; }
  .issues { background: #FFF5F5; color: var(--danger); }
  .notice { background: #EAF7EF; color: var(--success); }
  .error { background: #FFF0F0; color: var(--danger); }
  .workspace { display: flex; flex-direction: column; gap: 14px; }
  /* #72: the columns flow left-to-right and wrap, the way a printed interlinear
     reads, instead of sitting on one line behind a horizontal scrollbar. Each
     source word still sits directly above its own target chips -- only the
     single continuous reading line is broken, into several. flex-wrap rather
     than the cross-verse page's auto-fill grid (#136): the unit there is a
     side-by-side source+cell pair needing a consistent track, here it is a
     self-sizing stacked column, so natural widths pack a line tighter.
     `flex-shrink: 0` stays on .column -- wrapping is what absorbs the overflow
     now, columns still must not be squeezed. The max-height caps a long verse
     so the word bank and the footer controls stay on screen: the pointer drag
     has no auto-scroll, so a column you cannot see at the same time as the bank
     is unreachable by drag. */
  .interlinear {
    display: flex; flex-wrap: wrap; align-content: flex-start; gap: 16px 10px;
    overflow-x: hidden; overflow-y: auto; max-height: 48vh;
    padding: 12px 6px; border: 1px solid var(--border); border-radius: 10px; min-height: 128px;
  }
  /* The source column is Hebrew for an OT book and Greek for an NT one, so
     the face keys off the `dir` the markup already sets from
     context.sourceDirection rather than being hardcoded to either. */
  .interlinear[dir="rtl"] { font-family: var(--font-hebrew); }
  .interlinear[dir="ltr"] { font-family: var(--font-greek); }
  /* max-width so a column can never be wider than the box and be silently
     clipped by the overflow-x above on a narrow window. */
  .column { display: flex; flex-direction: column; align-items: center; gap: 6px; min-width: 76px; max-width: 100%; flex-shrink: 0; }
  .target-cell {
    display: flex; flex-direction: column; align-items: center; gap: 4px; width: 100%; box-sizing: border-box;
    min-height: 36px; justify-content: flex-end; padding: 4px; border-radius: 8px;
  }
  .target-cell.drop-hover { background: var(--accent-bg); outline: 2px dashed var(--accent); }
  .target-cell .placeholder { color: var(--text-3); font-size: var(--fs-xl); line-height: 1; padding-bottom: 6px; }
  .panel-title { display: flex; justify-content: space-between; gap: 10px; font-size: var(--fs-sm); font-weight: 700; margin-bottom: 10px; }
  .panel-title small { color: var(--text-3); font-weight: 400; }
  .token { display: inline-flex; flex-direction: column; align-items: center; gap: 2px; min-width: 62px; }
  .token small { font-size: var(--fs-3xs); color: var(--text-3); max-width: 130px; overflow: hidden; text-overflow: ellipsis; }
  /* The gloss replaced the lemma here, so it must undo what the lemma needed:
     `.interlinear` sets the Greek/Hebrew face and, for an OT book, dir=rtl --
     both wrong for an English definition. Clamped to two lines so a long
     definition cannot stretch the interlinear row taller than the words in it;
     the unabridged text stays in the tooltip and the lexicon popup. */
  .gloss {
    font-family: var(--font-ui); direction: ltr; text-align: center;
    white-space: normal; line-height: 1.25; max-width: 120px;
    display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 2; line-clamp: 2;
  }
  .occ { margin-left: 3px; font-size: 0.8em; font-weight: 400; color: var(--text-3); }
  .column .token.source { width: 100%; background: #F6F1FF; cursor: pointer; }
  /* On the target token itself, not on .aligned-card .word: this one rule
     covers the aligned cards inside the interlinear -- where it also has to
     undo the source face inherited from .interlinear -- and the word bank
     tokens outside it. */
  .token.target { font-family: var(--font-target); touch-action: none; user-select: none; }
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
  .aligned-card .word { font-size: var(--fs-sm); }
  .unalign-x {
    border: 0; background: none; padding: 0; width: 16px; height: 16px; line-height: 1;
    display: inline-flex; align-items: center; justify-content: center; border-radius: 50%;
    color: var(--text-2); font-size: var(--fs-md); cursor: pointer; flex-shrink: 0;
  }
  .unalign-x:hover:not(:disabled) { color: var(--danger); background: var(--danger-bg); }
  .word-bank { border: 1px solid var(--border); border-radius: 10px; padding: 12px; }
  .bank-tokens { display: flex; flex-wrap: wrap; gap: 7px; min-height: 46px; align-content: flex-start; border-radius: 8px; padding: 4px; }
  .bank-tokens.drop-hover { background: var(--accent-bg); outline: 2px dashed var(--accent); }
  .drag-ghost {
    position: fixed; z-index: 999; transform: translate(-50%, -130%); pointer-events: none;
    background: var(--accent); color: white; font-family: var(--font-target); font-size: var(--fs-sm); font-weight: 700;
    border-radius: 7px; padding: 6px 10px; box-shadow: 0 8px 20px rgba(0,0,0,.28);
  }
  .empty { color: var(--text-3); font-size: var(--fs-xs); margin: 6px; }
  footer { display: flex; justify-content: space-between; gap: 12px; align-items: center; flex-wrap: wrap; }
  .history-controls, .completion { display: flex; align-items: center; gap: 7px; }
  select { border: 1px solid var(--border-strong); border-radius: 7px; padding: 7px; max-width: 235px; color: var(--text); background: var(--surface); }
  .completed { font-size: var(--fs-xs); font-weight: 700; padding: 5px 8px; border-radius: 999px; }
  @media (max-width: 780px) {
    .modal { padding: 14px; }
    footer { align-items: stretch; }
    .history-controls, .completion { flex-wrap: wrap; }
  }
</style>
