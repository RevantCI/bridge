<script lang="ts">
  // Cross-verse alignment page, slice 1 (#116): several verses of one
  // chapter side by side -- source tokens down the left, each verse's word
  // bank down the right, a gap overview across the top. In this slice a
  // drop is accepted only within the same verse and goes through the
  // existing alignment.realign / alignment.unalign; a drop across verses
  // does nothing yet (#117 adds the Bridge-private link store). The tC
  // alignment data stays strictly verse-local throughout.
  import { onMount } from "svelte";
  import { bridge } from "../api/bridgeClient";
  import {
    alignmentStatusByVerse, checkStatusByVerse, currentChapter, findingsByVerse, verseKey, verseNums,
  } from "../stores";
  import type { AlignmentContext, AlignmentCounts, AlignmentToken } from "../types/finding";
  import { createPointerDrag } from "../alignmentDrag";
  import {
    alignedTargetsFor, bottomIdsAfterDrop, groupForTarget, occurrenceLabel as occurrence, unalignedTargets,
    unmatchedSources,
  } from "../alignmentGroups";
  import { defaultRange, joinVerseId, rangeBetween, spanOf, splitVerseId, toggleVerse } from "../crossVerseRange";
  import LexiconPopup from "./LexiconPopup.svelte";

  export let chapter: string;
  /** The verse the page was opened on; the default range is this ±1. */
  export let verse: string;
  export let onClose: () => void;

  const CROSS_VERSE_NOTICE =
    "Cross-verse links are saved in the next slice (#117). Nothing changed: translationCore alignment stays verse-local.";

  let selection: string[] = defaultRange($verseNums, verse);
  let contexts: Record<string, AlignmentContext> = {};
  let chapterStatus: AlignmentCounts | null = null;
  let loading = true;
  let busy = false;
  let error = "";
  let notice = "";
  /** When set, both columns show only that verse's gaps. */
  let gapFilterVerse: string | null = null;
  let lexiconToken: AlignmentToken | null = null;
  let lexiconDirection: "ltr" | "rtl" = "rtl";
  let pickedUpKey: string | null = null;
  let meaningByToken: Record<string, string> = {};
  const meaningCache = new Map<string, string>();
  let loadSequence = 0;

  $: span = spanOf($verseNums, selection);
  $: spanVerses = span ? rangeBetween($verseNums, span[0], span[1]) : [];
  $: ordered = selection.filter((v) => contexts[v]);
  $: totalGaps = ordered.reduce(
    (acc, v) => ({
      sourceUnmatched: acc.sourceUnmatched + contexts[v].gaps.sourceUnmatched,
      targetUnmatched: acc.targetUnmatched + contexts[v].gaps.targetUnmatched,
    }),
    { sourceUnmatched: 0, targetUnmatched: 0 },
  );
  $: visibleVerses = gapFilterVerse ? ordered.filter((v) => v === gapFilterVerse) : ordered;

  // The page is chapter-scoped: navigating to another chapter underneath it
  // would leave the range pointing at verses of the old one.
  $: if ($currentChapter !== chapter) onClose();

  // Composite ids in the DOM: a draggable token is "verse|T001", a drop
  // column is "verse|H001", a word bank is the verse. The drop handler
  // compares the two verses to route same-verse vs cross-verse.
  const drag = createPointerDrag({
    onDragStart: () => { pickedUpKey = null; },
    onDrop: ({ tokenId, column, bank }) => {
      if (column) dropOnColumn(tokenId, column);
      else if (bank) dropOnBank(tokenId, bank);
    },
  });
  const dragState = drag.state;
  $: ghostLabel = $dragState.tokenId ? tokenWord($dragState.tokenId) : "";

  onMount(() => drag.attach(window));
  onMount(() => { void load(); });

  function tokenWord(compositeId: string): string {
    const { verse: v, id } = splitVerseId(compositeId);
    return contexts[v]?.bottomTokens.find((t) => t.id === id)?.word ?? "";
  }

  async function load() {
    const sequence = ++loadSequence;
    loading = true;
    error = "";
    try {
      const range = await bridge.getAlignmentRange(chapter, selection);
      if (sequence !== loadSequence) return; // a newer selection superseded this load
      const next: Record<string, AlignmentContext> = {};
      for (const context of range.verses) next[context.verse] = context;
      contexts = next;
      chapterStatus = range.chapterStatus;
      void loadMeanings(range.verses.flatMap((c) => c.topTokens));
    } catch (value) {
      if (sequence !== loadSequence) return;
      error = value instanceof Error ? value.message : String(value);
    } finally {
      if (sequence === loadSequence) loading = false;
    }
  }

  async function loadMeanings(tokens: AlignmentToken[]) {
    await Promise.all(
      tokens
        .filter((t) => t.strong || t.morph)
        .map(async (t) => {
          const key = `${t.strong ?? ""}|${t.morph ?? ""}`;
          if (!meaningCache.has(key)) {
            try {
              const entry = await bridge.getLexiconEntry(t.strong ?? "", t.morph ?? "");
              meaningCache.set(key, entry.segments.map((s) => s.meaning || s.lemma).filter(Boolean).join("; "));
            } catch {
              meaningCache.set(key, "");
            }
          }
          meaningByToken[key] = meaningCache.get(key) ?? "";
        }),
    );
    meaningByToken = { ...meaningByToken };
  }

  function sourceTitle(token: AlignmentToken): string {
    const key = `${token.strong ?? ""}|${token.morph ?? ""}`;
    return meaningByToken[key] || [token.lemma, token.strong, token.morph].filter(Boolean).join(" · ");
  }

  // ---- range picker -------------------------------------------------------

  function setSpan(from: string, to: string) {
    const next = rangeBetween($verseNums, from, to);
    if (next.length === 0) return;
    selection = next;
    gapFilterVerse = null;
    void load();
  }

  function onFromChange(event: Event) {
    const from = (event.currentTarget as HTMLSelectElement).value;
    setSpan(from, span?.[1] ?? from);
  }

  function onToChange(event: Event) {
    const to = (event.currentTarget as HTMLSelectElement).value;
    setSpan(span?.[0] ?? to, to);
  }

  function toggleChip(v: string) {
    const next = toggleVerse($verseNums, selection, v);
    if (next.length === selection.length) return;
    selection = next;
    if (gapFilterVerse && !next.includes(gapFilterVerse)) gapFilterVerse = null;
    void load();
  }

  function toggleGapFilter(v: string) {
    gapFilterVerse = gapFilterVerse === v ? null : v;
  }

  // ---- mutations (same-verse only in this slice) --------------------------

  async function refreshChecks(v: string, updated: AlignmentContext, message: string) {
    contexts = { ...contexts, [v]: updated };
    chapterStatus = updated.chapterStatus;
    const key = verseKey(chapter, v);
    alignmentStatusByVerse.update((values) => ({ ...values, [key]: updated.status }));
    checkStatusByVerse.update((values) => ({ ...values, [key]: "pending" }));
    try {
      // `alignment` runs the verse-local QA set without the slow whole-book
      // USFM preflight -- exactly what AlignmentModal does after a save.
      const findings = await bridge.runVerseChecks(chapter, v, ["alignment", "greekroom"]);
      findingsByVerse.update((values) => ({ ...values, [key]: findings }));
      checkStatusByVerse.update((values) => ({ ...values, [key]: "succeeded" }));
      notice = `${message} Local and Greek Room checks for ${chapter}:${v} are current.`;
    } catch (value) {
      checkStatusByVerse.update((values) => ({ ...values, [key]: "failed" }));
      error = `${message} The save succeeded, but rechecking failed: ${value instanceof Error ? value.message : String(value)}`;
    }
  }

  async function mutate(v: string, action: () => Promise<AlignmentContext>, message: string) {
    if (busy) return;
    busy = true;
    error = "";
    notice = "";
    try {
      await refreshChecks(v, await action(), message);
    } catch (value) {
      error = value instanceof Error ? value.message : String(value);
    } finally {
      busy = false;
    }
  }

  function alignWithin(v: string, topId: string, bottomId: string) {
    const context = contexts[v];
    if (!context) return;
    const bottomIds = bottomIdsAfterDrop(context, topId, bottomId);
    if (!bottomIds) return; // already in this column
    void mutate(v, () => bridge.realignWords(chapter, v, [topId], bottomIds, context.alignment), "Alignment saved.");
  }

  function returnToBank(v: string, bottomId: string) {
    const context = contexts[v];
    if (!context || !groupForTarget(context, bottomId)) return;
    void mutate(v, () => bridge.unalignWords(chapter, v, [bottomId], context.alignment), "Returned to word bank.");
  }

  /** Routes a token ("verse|T001") dropped on a column ("verse|H001"). */
  function dropOnColumn(tokenKey: string, columnKey: string) {
    const token = splitVerseId(tokenKey);
    const column = splitVerseId(columnKey);
    if (token.verse !== column.verse) {
      error = "";
      notice = CROSS_VERSE_NOTICE;
      return;
    }
    alignWithin(token.verse, column.id, token.id);
  }

  function dropOnBank(tokenKey: string, bankVerse: string) {
    const token = splitVerseId(tokenKey);
    if (token.verse !== bankVerse) {
      error = "";
      notice = CROSS_VERSE_NOTICE;
      return;
    }
    returnToBank(token.verse, token.id);
  }

  // Click-to-pick-up: the keyboard/click-operable alternative to dragging.
  function handleWordClick(tokenKey: string) {
    if (busy) return;
    if (drag.consumeSuppressedClick(tokenKey)) return;
    pickedUpKey = pickedUpKey === tokenKey ? null : tokenKey;
  }

  function handleColumnClick(columnKey: string) {
    if (!pickedUpKey || busy) return;
    const key = pickedUpKey;
    pickedUpKey = null;
    dropOnColumn(key, columnKey);
  }

  function handleBankClick(bankVerse: string) {
    if (!pickedUpKey || busy) return;
    const key = pickedUpKey;
    pickedUpKey = null;
    dropOnBank(key, bankVerse);
  }

  function startPointerTrack(event: PointerEvent, tokenKey: string) {
    if (busy) return;
    drag.start(event, tokenKey);
  }

  function openLexicon(token: AlignmentToken, direction: "ltr" | "rtl") {
    lexiconToken = token;
    lexiconDirection = direction;
  }

  function sourceRows(context: AlignmentContext): AlignmentToken[] {
    return gapFilterVerse ? unmatchedSources(context) : context.topTokens;
  }

  function bankTokens(context: AlignmentContext): AlignmentToken[] {
    return gapFilterVerse ? unalignedTargets(context) : context.bottomTokens;
  }

  function activate(event: KeyboardEvent, action: () => void) {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      action();
    }
  }
</script>

<svelte:window on:keydown={(event) => event.key === "Escape" && !busy && !lexiconToken && onClose()} />

<div class="overlay" role="presentation">
  <section class="page" role="dialog" aria-modal="true" aria-label={`Cross-verse alignment, chapter ${chapter}`}>
    <header>
      <div class="title">
        <div class="eyebrow">CROSS-VERSE ALIGNMENT</div>
        <h2>Chapter {chapter} · verses {span ? (span[0] === span[1] ? span[0] : `${span[0]}–${span[1]}`) : verse}</h2>
      </div>
      <div class="picker" aria-label="Verse range">
        <label>From
          <select value={span?.[0] ?? verse} on:change={onFromChange} disabled={busy}>
            {#each $verseNums.filter((v) => v !== "front") as v}<option value={v}>{v}</option>{/each}
          </select>
        </label>
        <label>To
          <select value={span?.[1] ?? verse} on:change={onToChange} disabled={busy}>
            {#each $verseNums.filter((v) => v !== "front") as v}<option value={v}>{v}</option>{/each}
          </select>
        </label>
        <div class="chips" role="group" aria-label="Verses in range">
          {#each spanVerses as v (v)}
            <button
              type="button"
              class="chip"
              class:on={selection.includes(v)}
              aria-pressed={selection.includes(v)}
              on:click={() => toggleChip(v)}
              disabled={busy}
              title={selection.includes(v) ? `Hide verse ${v}` : `Show verse ${v}`}
            >{v}</button>
          {/each}
        </div>
      </div>
      <button class="close" on:click={onClose} disabled={busy} aria-label="Close cross-verse alignment">×</button>
    </header>

    {#if loading && ordered.length === 0}
      <div class="loading"><span class="spin" /> Loading {selection.length} verse{selection.length === 1 ? "" : "s"}…</div>
    {:else}
      <div class="gap-strip" aria-label="Gap overview">
        {#each ordered as v (v)}
          {@const gaps = contexts[v].gaps}
          <button
            type="button"
            class="gap"
            class:active={gapFilterVerse === v}
            class:clean={gaps.sourceUnmatched === 0 && gaps.targetUnmatched === 0}
            aria-pressed={gapFilterVerse === v}
            on:click={() => toggleGapFilter(v)}
            title={gapFilterVerse === v ? "Show all words again" : `Show only the gaps in verse ${v}`}
          >
            <span class="gap-verse">v.{v}</span>
            <span class="status {contexts[v].status}">{contexts[v].status}</span>
            <span>{gaps.sourceUnmatched} source word{gaps.sourceUnmatched === 1 ? "" : "s"} with no counterpart</span>
            <span>{gaps.targetUnmatched} target word{gaps.targetUnmatched === 1 ? "" : "s"} with no counterpart</span>
          </button>
        {/each}
        <div class="gap-total">
          <span>Range: {totalGaps.sourceUnmatched} source · {totalGaps.targetUnmatched} target unmatched</span>
          {#if chapterStatus}
            <span>Chapter: {chapterStatus.complete} complete · {chapterStatus.partial} partial · {chapterStatus.untouched} untouched{#if chapterStatus.invalid} · {chapterStatus.invalid} invalid{/if}</span>
          {/if}
          {#if gapFilterVerse}<button type="button" class="link" on:click={() => (gapFilterVerse = null)}>Show all</button>{/if}
        </div>
      </div>

      {#if notice}<div class="notice">{notice}</div>{/if}
      {#if error}<div class="error">{error}</div>{/if}
      {#if loading}<div class="reloading"><span class="spin" /> Updating range…</div>{/if}

      <div class="columns">
        <section class="col sources" aria-label="Source words">
          <div class="col-title">Source words <small>click a word for its lexicon entry · drop target words into the cell beside it</small></div>
          <div class="scroll">
            {#each visibleVerses as v (v)}
              {@const context = contexts[v]}
              <div class="verse-block">
                <div class="verse-head">
                  <span class="vnum">{chapter}:{v}</span>
                  {#if !context.sourceAvailable}<span class="warn">no original-language source</span>{/if}
                  {#if context.issues.length}<span class="warn" title={context.issues.join("\n")}>⚠ {context.issues.length} issue{context.issues.length === 1 ? "" : "s"}</span>{/if}
                </div>
                {#each sourceRows(context) as src (src.id)}
                  {@const columnKey = joinVerseId(v, src.id)}
                  <div class="row">
                    <button
                      type="button"
                      class="token source"
                      dir={context.sourceDirection}
                      class:hebrew={context.sourceDirection === "rtl"}
                      on:click={() => openLexicon(src, context.sourceDirection)}
                      disabled={busy}
                      title={sourceTitle(src)}
                    >
                      <span class="word">{src.word}{#if src.occurrences > 1}<span class="occ">{occurrence(src)}</span>{/if}</span>
                      {#if src.lemma}<small>{src.lemma}</small>{/if}
                    </button>
                    <div
                      class="drop-cell"
                      class:drop-hover={$dragState.overColumn === columnKey}
                      data-drop-column={columnKey}
                      dir={context.targetDirection}
                      role="button"
                      tabindex="0"
                      aria-label={pickedUpKey ? `Align picked-up word to ${src.word} in verse ${v}` : `Target words aligned to ${src.word} in verse ${v}`}
                      on:click={() => handleColumnClick(columnKey)}
                      on:keydown={(event) => activate(event, () => handleColumnClick(columnKey))}
                    >
                      {#each alignedTargetsFor(context, src.id) as item (item.id)}
                        <span class="token target aligned-card">
                          <span class="word">{item.word}{#if item.occurrences > 1}<span class="occ">{occurrence(item)}</span>{/if}</span>
                          <button
                            type="button"
                            class="unalign-x"
                            on:click|stopPropagation={() => returnToBank(v, item.id)}
                            disabled={busy}
                            aria-label={`Unalign ${item.word} from ${src.word}`}
                            title="Return to the word bank"
                          >×</button>
                        </span>
                      {:else}
                        <span class="placeholder" aria-hidden="true">·</span>
                      {/each}
                    </div>
                  </div>
                {:else}
                  <p class="empty">{gapFilterVerse ? "Every source word has a counterpart." : "No source tokens in this verse."}</p>
                {/each}
              </div>
            {/each}
          </div>
        </section>

        <section class="col targets" aria-label="Target words">
          <div class="col-title">Target words <small>in verse order · drag a blue word into a source cell, or click it then click a cell</small></div>
          <div class="scroll">
            {#each visibleVerses as v (v)}
              {@const context = contexts[v]}
              <div class="verse-block">
                <div class="verse-head">
                  <span class="vnum">{chapter}:{v}</span>
                  <span class="status {context.status}">{context.status}</span>
                </div>
                <div
                  class="bank"
                  class:drop-hover={$dragState.overBank === v}
                  data-drop-bank={v}
                  dir={context.targetDirection}
                  role="button"
                  tabindex="0"
                  aria-label={pickedUpKey ? `Return picked-up word to the word bank of verse ${v}` : `Word bank of verse ${v}`}
                  on:click={() => handleBankClick(v)}
                  on:keydown={(event) => activate(event, () => handleBankClick(v))}
                >
                  {#each bankTokens(context) as item (item.id)}
                    {@const tokenKey = joinVerseId(v, item.id)}
                    {#if groupForTarget(context, item.id)}
                      <span class="token target already-aligned" title="Already aligned in this verse">
                        <span class="word">{item.word}{#if item.occurrences > 1}<span class="occ">{occurrence(item)}</span>{/if}</span>
                      </span>
                    {:else}
                      <button
                        type="button"
                        class="token target unaligned"
                        class:picked={pickedUpKey === tokenKey}
                        on:pointerdown={(event) => startPointerTrack(event, tokenKey)}
                        on:click|stopPropagation={() => handleWordClick(tokenKey)}
                        disabled={busy}
                      ><span class="word">{item.word}{#if item.occurrences > 1}<span class="occ">{occurrence(item)}</span>{/if}</span></button>
                    {/if}
                  {:else}
                    <p class="empty">{gapFilterVerse ? "Every target word is aligned." : "This verse has no target words."}</p>
                  {/each}
                </div>
              </div>
            {/each}
          </div>
        </section>
      </div>
    {/if}
  </section>
</div>

{#if lexiconToken}
  <LexiconPopup token={lexiconToken} direction={lexiconDirection} onClose={() => (lexiconToken = null)} />
{/if}

{#if $dragState.tokenId && $dragState.moved}
  <div class="drag-ghost" style="left:{$dragState.ghost.x}px; top:{$dragState.ghost.y}px;">{ghostLabel}</div>
{/if}

<style>
  .overlay { position: fixed; inset: 0; z-index: 50; background: rgba(15, 20, 26, .58); display: grid; place-items: center; padding: 16px; }
  .page {
    width: min(1340px, 100%); height: calc(100vh - 32px); display: flex; flex-direction: column; min-height: 0;
    background: var(--surface); border-radius: 14px; box-shadow: 0 24px 80px rgba(0,0,0,.24); padding: 14px 18px; color: var(--text);
  }
  header { display: flex; gap: 16px; align-items: flex-start; border-bottom: 1px solid var(--border); padding-bottom: 10px; flex-shrink: 0; }
  .title { min-width: 220px; }
  .eyebrow { color: var(--accent); font-size: var(--fs-2xs); letter-spacing: .12em; font-weight: 800; }
  h2 { margin: 3px 0 0; font-size: var(--fs-xl); }
  .picker { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; flex: 1; font-size: var(--fs-xs); color: var(--text-2); }
  .picker label { display: inline-flex; align-items: center; gap: 5px; }
  button, select { font: inherit; }
  button { border: 1px solid var(--border-strong); background: var(--surface); color: var(--text); border-radius: 7px; padding: 6px 9px; cursor: pointer; }
  button:hover:not(:disabled) { border-color: var(--accent); }
  button:disabled { opacity: .5; cursor: not-allowed; }
  select { border: 1px solid var(--border-strong); border-radius: 7px; padding: 5px 7px; color: var(--text); background: var(--surface); }
  .chips { display: flex; flex-wrap: wrap; gap: 4px; }
  .chip { padding: 3px 8px; border-radius: 999px; font-size: var(--fs-xs); color: var(--text-3); background: var(--surface-2); border-color: transparent; }
  .chip.on { color: var(--accent); background: var(--accent-bg); border-color: var(--accent); font-weight: 700; }
  .close { border: 0; font-size: var(--fs-5xl); padding: 0 5px; color: var(--text-2); line-height: 1; }
  .link { border: 0; background: none; color: var(--accent); padding: 0; text-decoration: underline; }
  .loading, .reloading { padding: 12px; display: flex; gap: 10px; align-items: center; justify-content: center; color: var(--text-2); font-size: var(--fs-sm); }
  .loading { padding: 36px; }
  .spin { width: 12px; height: 12px; border: 2px solid var(--accent-bg); border-top-color: var(--accent); border-radius: 50%; animation: spin .8s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }

  .gap-strip { display: flex; gap: 8px; flex-wrap: wrap; align-items: stretch; padding: 10px 0 8px; flex-shrink: 0; font-size: var(--fs-xs); }
  .gap { display: flex; flex-direction: column; align-items: flex-start; gap: 2px; text-align: left; padding: 6px 10px; border-radius: 9px; background: var(--warning-bg); color: var(--warning); border-color: transparent; min-width: 190px; }
  .gap.clean { background: #EAF7EF; color: var(--success); }
  .gap.active { outline: 2px solid var(--accent); outline-offset: 1px; }
  .gap-verse { font-weight: 800; color: var(--text); }
  .gap-total { display: flex; flex-direction: column; justify-content: center; gap: 3px; color: var(--text-2); padding: 0 6px; margin-left: auto; text-align: right; }
  .status { border-radius: 999px; padding: 1px 7px; background: var(--surface-2); font-weight: 700; font-size: var(--fs-2xs); color: var(--text-2); }
  .status.complete { color: var(--success); background: #EAF7EF; }
  .status.partial { color: var(--warning); background: var(--warning-bg); }
  .status.invalid { color: var(--danger); background: var(--danger-bg); }
  .notice, .error { border-radius: 9px; padding: 8px 12px; margin-bottom: 8px; font-size: var(--fs-sm); line-height: 1.45; flex-shrink: 0; }
  .notice { background: #EAF7EF; color: var(--success); }
  .error { background: #FFF0F0; color: var(--danger); }

  /* Two vertically scrolling columns: the range view never scrolls sideways (#72). */
  .columns { display: grid; grid-template-columns: minmax(0, 1.25fr) minmax(0, 1fr); gap: 12px; flex: 1; min-height: 0; }
  .col { display: flex; flex-direction: column; min-height: 0; border: 1px solid var(--border); border-radius: 10px; }
  .col-title { display: flex; flex-wrap: wrap; gap: 6px 10px; align-items: baseline; padding: 8px 12px; font-size: var(--fs-sm); font-weight: 700; border-bottom: 1px solid var(--border); flex-shrink: 0; }
  .col-title small { color: var(--text-3); font-weight: 400; }
  .scroll { overflow-y: auto; overflow-x: hidden; padding: 6px 10px 10px; min-height: 0; flex: 1; }
  .verse-block { padding: 6px 0 10px; border-bottom: 1px dashed var(--border); }
  .verse-block:last-child { border-bottom: 0; }
  .verse-head { display: flex; align-items: center; gap: 8px; padding: 6px 0; position: sticky; top: 0; background: var(--surface); z-index: 1; font-size: var(--fs-xs); }
  .vnum { font-weight: 800; color: var(--text); }
  .warn { color: var(--warning); }
  .row { display: grid; grid-template-columns: minmax(150px, 2fr) minmax(0, 3fr); gap: 8px; align-items: stretch; padding: 3px 0; }
  .token { display: inline-flex; flex-direction: column; align-items: center; gap: 2px; min-width: 62px; }
  .token small { font-size: var(--fs-3xs); color: var(--text-3); max-width: 160px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .occ { margin-left: 3px; font-size: 0.8em; font-weight: 400; color: var(--text-3); }
  .token.source { width: 100%; background: #F6F1FF; cursor: pointer; align-items: flex-start; font-family: var(--font-greek); }
  .token.source.hebrew { font-family: var(--font-hebrew); align-items: flex-end; }
  .token.source .word { font-size: var(--fs-lg); }
  .drop-cell { display: flex; flex-wrap: wrap; align-items: center; gap: 4px; min-height: 38px; padding: 4px 6px; border-radius: 8px; border: 1px dashed var(--border); }
  .drop-cell.drop-hover, .bank.drop-hover { background: var(--accent-bg); outline: 2px dashed var(--accent); }
  .drop-cell .placeholder { color: var(--text-3); font-size: var(--fs-xl); line-height: 1; padding: 0 6px; }
  .token.target { font-family: var(--font-target); touch-action: none; user-select: none; }
  .token.target.unaligned { background: #EFF7FF; border-color: var(--border-strong); color: var(--text); }
  .token.picked { outline: 2px solid var(--accent); outline-offset: 1px; }
  .already-aligned { background: var(--surface-2); border: 1px solid var(--border); color: var(--text-3); padding: 6px 9px; border-radius: 7px; cursor: default; }
  .aligned-card { flex-direction: row; align-items: center; gap: 4px; min-width: 0; border: 1px solid var(--border-strong); border-radius: 7px; padding: 4px 6px 4px 9px; background: #EFF7FF; color: var(--text); }
  .aligned-card .word { font-size: var(--fs-sm); }
  .unalign-x { border: 0; background: none; padding: 0; width: 16px; height: 16px; line-height: 1; display: inline-flex; align-items: center; justify-content: center; border-radius: 50%; color: var(--text-2); font-size: var(--fs-md); flex-shrink: 0; }
  .unalign-x:hover:not(:disabled) { color: var(--danger); background: var(--danger-bg); }
  .bank { display: flex; flex-wrap: wrap; gap: 6px; min-height: 44px; align-content: flex-start; border-radius: 8px; padding: 4px; }
  .drag-ghost { position: fixed; z-index: 999; transform: translate(-50%, -130%); pointer-events: none; background: var(--accent); color: white; font-family: var(--font-target); font-size: var(--fs-sm); font-weight: 700; border-radius: 7px; padding: 6px 10px; box-shadow: 0 8px 20px rgba(0,0,0,.28); }
  .empty { color: var(--text-3); font-size: var(--fs-xs); margin: 6px; }
  @media (max-width: 900px) {
    .columns { grid-template-columns: 1fr; }
    .page { padding: 10px; }
  }
</style>
