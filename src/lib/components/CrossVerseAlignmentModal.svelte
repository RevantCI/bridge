<script lang="ts">
  // Cross-verse alignment page, slice 1 (#116): several verses of one
  // chapter side by side -- source tokens down the left, each verse's word
  // bank down the right, a gap overview across the top. In this slice a
  // drop is accepted only within the same verse and goes through the
  // existing alignment.realign / alignment.unalign; a drop across verses
  // records a Bridge-private cross-verse link (#117) in the workbench
  // database. The tC alignment data stays strictly verse-local throughout:
  // the linked source token's group stays empty and the target word stays
  // in its own verse's word bank; only the annotations change.
  import { onMount } from "svelte";
  import { bridge } from "../api/bridgeClient";
  import {
    alignmentStatusByVerse, checkStatusByVerse, currentChapter, findingsByVerse, verseKey, verseNums,
  } from "../stores";
  import type {
    AlignmentContext, AlignmentCounts, AlignmentToken, CrossVerseLink, CrossVerseLinkResult,
    CrossVerseProposal,
  } from "../types/finding";
  import { createPointerDrag } from "../alignmentDrag";
  import {
    alignedTargetsFor, bottomIdsAfterDrop, groupForTarget, occurrenceLabel as occurrence, unaccountedTargets,
    unrealizedSources,
  } from "../alignmentGroups";
  import { defaultRange, joinVerseId, rangeBetween, spanOf, splitVerseId, toggleVerse } from "../crossVerseRange";
  import { suggestCrossVerseRange, unionInChapterOrder } from "../crossVerseSuggest";
  import { SourceGlossCache } from "../lexiconGloss";
  import LexiconPopup from "./LexiconPopup.svelte";

  export let chapter: string;
  /** The verse the page was opened on; the default range is this ±1. */
  export let verse: string;
  export let onClose: () => void;
  /** Verses to start with instead of anchor ±1 (#118): the editor's
   *  multi-selection or a finding's references. */
  export let initialVerses: string[] = [];

  const BANK_NOTICE =
    "To link across verses, drop the word onto a source word of the other verse, not into its word bank.";

  let selection: string[] = initialVerses.length > 1
    ? unionInChapterOrder($verseNums, initialVerses)
    : defaultRange($verseNums, verse);
  if (selection.length === 0) selection = defaultRange($verseNums, verse);
  /** Verses the last Stage 6B run marked CROSS_VERSE that the picker added (#118). */
  let suggested: string[] = [];
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
  // The English sense goes under the source word and the lemma moves into the
  // tooltip: a lemma is one more Greek/Hebrew string, and tells a reviewer who
  // does not read those scripts nothing. Cached across range changes, since a
  // verse that leaves and re-enters the range resolves the same entries.
  const glosses = new SourceGlossCache();
  let glossVersion = 0;
  let loadSequence = 0;
  /** Cross-verse suggestions (#139), loaded only on an explicit click. */
  let proposals: CrossVerseProposal[] = [];
  let proposalsBusy = false;
  let proposalError = "";
  let proposalsUnavailable = "";
  let suggestionsShown = false;
  /** #146. `aiAvailable` is undefined until settings load, so the button reads
   *  "checking" rather than flickering from disabled to enabled. */
  let aiAvailable: boolean | undefined = undefined;
  let aiUsed = false;
  let aiTruncated = false;
  let autoLinked = 0;
  let dismissed = new Set<string>();
  /** The selection the current proposals were computed for, so a widened range
   *  is reported as stale rather than silently showing yesterday's answer. */
  let proposalsFor: string[] = [];

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
  $: visibleProposals = proposals.filter((p) => !dismissed.has(proposalKey(p)));
  $: proposalsStale = suggestionsShown && proposalsFor.join("␟") !== selection.join("␟");

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
  onMount(() => { void loadThenSuggest(); });
  // Whether an AI proposal is even offered is a settings question, not a project
  // one, and a failure here must leave the offline path untouched -- so it is its
  // own mount, and a throw just means "no AI button".
  onMount(async () => {
    try {
      aiAvailable = Boolean((await bridge.getSettings())?.hasApiKey);
    } catch {
      aiAvailable = false;
    }
  });

  /** Load the range, then widen it with the last analysis's cross-verse
   *  verses if the page was opened on the default range. The suggestion is
   *  advisory: it never narrows the range and the picker stays manual. */
  async function loadThenSuggest() {
    await load();
    if (initialVerses.length > 1) return;
    const suggestion = await suggestCrossVerseRange(chapter);
    if (!suggestion) return;
    const added = suggestion.verses.filter((v) => !selection.includes(v) && $verseNums.includes(v));
    if (added.length === 0) return;
    suggested = added;
    selection = unionInChapterOrder($verseNums, selection, added);
    await load();
  }

  function resetToDefaultRange() {
    suggested = [];
    selection = defaultRange($verseNums, verse);
    gapFilterVerse = null;
    void load();
  }

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

  /** Suggestions are loaded on an explicit click, never with the range (#139).
   *  The first call in a session pays the one-time Uroman/Smart-Edit-Distance
   *  table load (~2 s) plus a scan of every completed verse in the collection;
   *  paying that silently on every range change would make the picker feel
   *  broken. Steady state afterwards is milliseconds. */
  async function loadProposals() {
    if (proposalsBusy) return;
    proposalsBusy = true;
    proposalError = "";
    try {
      const wanted = [...selection];
      const result = await bridge.crossVersePropose(chapter, wanted);
      proposals = result.proposals;
      proposalsFor = wanted;
      proposalsUnavailable = result.unavailable?.message ?? "";
      suggestionsShown = true;
    } catch (value) {
      proposalError = value instanceof Error ? value.message : String(value);
    } finally {
      proposalsBusy = false;
    }
  }

  /** The same question asked of a model as well (#146), and then the agreed
   *  proposals linked without a further click.
   *
   *  Three things this deliberately keeps from the offline path: it is still
   *  click-only (a billed request must never fire because a range changed), it
   *  still writes through the ordinary `crossVerseLink`, and a refused link
   *  still surfaces rather than being swallowed. What it adds is that a proposal
   *  the model and the corpus scorer *both* chose, uncontested, is applied for
   *  you -- two independent methods agreeing, never the model's own confidence.
   */
  async function loadAiProposals() {
    if (proposalsBusy) return;
    proposalsBusy = true;
    proposalError = "";
    autoLinked = 0;
    try {
      const wanted = [...selection];
      const result = await bridge.crossVerseAiPropose(chapter, wanted);
      proposalsFor = wanted;
      suggestionsShown = true;
      aiUsed = true;
      if (result.unavailable) {
        proposalsUnavailable = result.unavailable.message;
        proposals = [];
        return;
      }
      // A model that returned nothing must not wipe out what statistics found.
      const corpusOnly = (result.corpusProposals ?? []).filter(
        (item) => !result.proposals.some(
          (p) => p.source.verse === item.source.verse && p.source.topId === item.source.topId,
        ),
      );
      proposals = [...result.proposals, ...corpusOnly];
      proposalsUnavailable = result.proposals.length ? "" : (result.corpusUnavailable?.message ?? "");
      aiTruncated = Boolean(result.truncated);

      const gated = result.proposals.filter((item) => item.autoLinkable);
      for (const item of gated) {
        await mutateCross(
          () => bridge.crossVerseLink(
            { chapter, verse: item.source.verse, topId: item.source.topId },
            { chapter, verse: item.target.verse, bottomId: item.target.bottomId },
            "ai-auto",
          ),
          "",
        );
        // Stop at the first refusal rather than pressing on: the later links in
        // the batch were computed against the state before it, and a run that
        // half-applied while showing one error is the worst of both.
        if (error) break;
        autoLinked += 1;
        dismissed = new Set([...dismissed, proposalKey(item)]);
      }
      if (autoLinked > 0) {
        notice = `Linked ${autoLinked} ${autoLinked === 1 ? "pair" : "pairs"} the AI and this project's own completed alignments both chose. Undo any with ×.`;
      }
    } catch (value) {
      proposalError = value instanceof Error ? value.message : String(value);
    } finally {
      proposalsBusy = false;
    }
  }

  function proposalKey(proposal: CrossVerseProposal): string {
    const { source, target } = proposal;
    return `${source.verse}|${source.topId}|${target.verse}|${target.bottomId}`;
  }

  function dismissProposal(proposal: CrossVerseProposal) {
    // Session-local only in this slice; persisting it is #140, which needs a
    // workbench schema bump.
    dismissed = new Set([...dismissed, proposalKey(proposal)]);
  }

  /** Accepting is an ordinary cross-verse link with the ids the proposal
   *  carries -- there is no separate apply path, and nothing was written
   *  until this click. */
  async function acceptProposal(proposal: CrossVerseProposal) {
    const { source, target } = proposal;
    await mutateCross(
      () => bridge.crossVerseLink(
        { chapter, verse: source.verse, topId: source.topId },
        { chapter, verse: target.verse, bottomId: target.bottomId },
      ),
      `Linked ${source.word} (${chapter}:${source.verse}) to ${target.word} (${chapter}:${target.verse}).`,
    );
    // Only after the link actually succeeded: a refused link (the word was
    // aligned underneath us, the text changed) must leave the suggestion on
    // screen with the error, not silently swallow it.
    if (error) return;
    dismissProposal(proposal);
    await loadProposals();
  }

  function evidenceSummary(proposal: CrossVerseProposal): string {
    const parts: string[] = [];
    for (const item of proposal.evidence) {
      if (item.rawScore <= 0) continue;
      if (item.kind === "STRONGS_PRECEDENT" && item.jointCount) {
        parts.push(`this lemma rendered "${proposal.target.word}" ${item.jointCount}× in completed verses`);
      } else if (item.kind === "SURFACE_PRECEDENT" && item.jointCount) {
        parts.push(`this exact form paired ${item.jointCount}×`);
      } else if (item.kind === "PHONETIC") {
        parts.push("the two words sound alike when romanized");
      } else if (item.kind === "PROXIMITY") {
        // rawScore is 1/distance, so only 1 means the verse next door.
        parts.push(item.rawScore === 1 ? "the verse next door" : "a nearby verse");
      } else if (item.kind === "MODEL_PICK") {
        // The model's own sentence, verbatim. It is the only evidence line a
        // reviewer who reads neither original language can check for themselves,
        // so it leads -- and it is attributed, never presented as a measurement.
        parts.unshift(item.reason ? `the AI says: ${item.reason}` : "the AI picked this pairing");
      }
    }
    return parts.join(" · ");
  }

  async function loadMeanings(tokens: AlignmentToken[]) {
    await glosses.load(tokens);
    glossVersion = glosses.version;
  }

  // `glossVersion` is read, not used, so Svelte re-invokes these once the
  // lexicon lookups resolve.
  function sourceGloss(token: AlignmentToken, _version: number): string {
    return glosses.glossFor(token).short;
  }

  function sourceTitle(token: AlignmentToken, _version: number): string {
    return glosses.glossFor(token).title;
  }

  // ---- range picker -------------------------------------------------------

  function setSpan(from: string, to: string) {
    const next = rangeBetween($verseNums, from, to);
    if (next.length === 0) return;
    suggested = [];
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
      // `message` is empty when the caller reports its own aggregate result
      // (the AI auto-link batch, #146), so join rather than interpolate --
      // otherwise every notice starts with a stray space.
      notice = [message, `Local and Greek Room checks for ${chapter}:${v} are current.`]
        .filter(Boolean).join(" ");
    } catch (value) {
      checkStatusByVerse.update((values) => ({ ...values, [key]: "failed" }));
      error = [message, `The save succeeded, but rechecking failed: ${value instanceof Error ? value.message : String(value)}`]
        .filter(Boolean).join(" ");
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

  /** A cross-verse link or unlink returns both verses' contexts; each is
   *  patched in and rechecked, exactly like a same-verse save. */
  async function mutateCross(action: () => Promise<CrossVerseLinkResult>, message: string) {
    if (busy) return;
    busy = true;
    error = "";
    notice = "";
    try {
      const result = await action();
      await refreshChecks(result.source.verse, result.source, message);
      await refreshChecks(result.target.verse, result.target, message);
    } catch (value) {
      error = value instanceof Error ? value.message : String(value);
    } finally {
      busy = false;
    }
  }

  function linkAcross(sourceVerse: string, topId: string, targetVerse: string, bottomId: string) {
    void mutateCross(
      () => bridge.crossVerseLink(
        { chapter, verse: sourceVerse, topId },
        { chapter, verse: targetVerse, bottomId },
      ),
      "Cross-verse link saved.",
    );
  }

  function unlink(link: CrossVerseLink) {
    void mutateCross(() => bridge.crossVerseUnlink(link.id), "Cross-verse link removed.");
  }

  function linksForSource(context: AlignmentContext, topId: string): CrossVerseLink[] {
    return context.crossVerseLinks.filter((link) => link.sourceTopId === topId);
  }

  function linkForBottom(context: AlignmentContext, bottomId: string): CrossVerseLink | undefined {
    return context.crossVerseLinks.find((link) => link.targetBottomId === bottomId && link.state === "active");
  }

  /** Routes a token ("verse|T001") dropped on a column ("verse|H001"): the
   *  same verse realigns through tC, another verse records a Bridge link. */
  function dropOnColumn(tokenKey: string, columnKey: string) {
    const token = splitVerseId(tokenKey);
    const column = splitVerseId(columnKey);
    if (token.verse !== column.verse) {
      linkAcross(column.verse, column.id, token.verse, token.id);
      return;
    }
    alignWithin(token.verse, column.id, token.id);
  }

  function dropOnBank(tokenKey: string, bankVerse: string) {
    const token = splitVerseId(tokenKey);
    if (token.verse !== bankVerse) {
      error = "";
      notice = BANK_NOTICE;
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
    return gapFilterVerse ? unrealizedSources(context) : context.topTokens;
  }

  function bankTokens(context: AlignmentContext): AlignmentToken[] {
    return gapFilterVerse ? unaccountedTargets(context) : context.bottomTokens;
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
            class:accounted={contexts[v].fullyAccounted}
            aria-pressed={gapFilterVerse === v}
            on:click={() => toggleGapFilter(v)}
            title={gapFilterVerse === v ? "Show all words again" : `Show only the gaps in verse ${v}`}
          >
            <span class="gap-verse">v.{v}</span>
            <span class="status {contexts[v].status}">{contexts[v].status}</span>
            <span>{gaps.sourceUnmatched} source word{gaps.sourceUnmatched === 1 ? "" : "s"} with no counterpart</span>
            <span>{gaps.targetUnmatched} target word{gaps.targetUnmatched === 1 ? "" : "s"} with no counterpart</span>
            {#if contexts[v].crossVerseAccounted + contexts[v].crossVerseRealized > 0}
              <span class="linked-note">↔ {contexts[v].crossVerseAccounted + contexts[v].crossVerseRealized} linked across verses{#if contexts[v].fullyAccounted} · nothing left unaccounted{/if}</span>
            {/if}
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

      {#if suggested.length > 0}
        <div class="suggestion">
          ↔ Range widened with verse{suggested.length === 1 ? "" : "s"} {suggested.join(", ")}: the last analysis
          located source material there across verses.
          <button type="button" class="link" on:click={resetToDefaultRange} disabled={busy}>Back to {verse} ±1</button>
        </div>
      {/if}
      <section class="suggest" aria-label="Cross-verse suggestions">
        <div class="suggest-head">
          <button type="button" on:click={loadProposals} disabled={proposalsBusy || busy || loading}>
            {#if proposalsBusy}<span class="spin" />{/if}
            {suggestionsShown ? "Suggest again" : "Suggest links"}
          </button>
          {#if aiAvailable !== false}
            <button
              type="button"
              class="ai"
              on:click={loadAiProposals}
              disabled={proposalsBusy || busy || loading || aiAvailable === undefined}
              title={aiAvailable === undefined
                ? "Checking whether an AI provider is configured…"
                : "Ask the configured AI provider as well, and link the pairs it and this project's own completed alignments both choose. Sends this range's unaligned words to your provider."}
            >
              {#if proposalsBusy && aiUsed}<span class="spin" />{/if}
              Suggest with AI
            </button>
          {/if}
          <small>
            {#if aiAvailable === false}
              learned from this project's own completed alignments · nothing is linked until you accept ·
              <span class="ai-off">add an API key in Settings to also ask an AI</span>
            {:else}
              learned from this project's own completed alignments · nothing is linked until you accept,
              except pairs the AI and the corpus both choose
            {/if}
          </small>
          {#if suggestionsShown && !proposalsBusy}
            <span class="suggest-count">
              {visibleProposals.length} suggestion{visibleProposals.length === 1 ? "" : "s"}
            </span>
          {/if}
        </div>
        {#if proposalError}<div class="error">{proposalError}</div>{/if}
        {#if aiTruncated}
          <p class="empty">
            This range had more gaps than one AI request covers, so only the first of them were
            offered. Narrow the range to reach the rest.
          </p>
        {/if}
        {#if proposalsStale}
          <p class="empty">The range changed since these were worked out — suggest again.</p>
        {/if}
        {#if proposalsUnavailable}
          <p class="empty">{proposalsUnavailable}</p>
        {:else if suggestionsShown && !proposalsBusy && visibleProposals.length === 0}
          <p class="empty">No cross-verse realization found for the gaps in this range.</p>
        {/if}
        {#if visibleProposals.length > 0}
          <ul class="proposals">
            {#each visibleProposals as proposal (proposalKey(proposal))}
              <li class="proposal" class:ambiguous={proposal.status === "AMBIGUOUS"}>
                <div class="proposal-claim">
                  <span class="word source-word">{proposal.source.word}</span>
                  <small>{chapter}:{proposal.source.verse}</small>
                  <span aria-hidden="true">→</span>
                  <span class="word">{proposal.target.word}</span>
                  <small>{chapter}:{proposal.target.verse}</small>
                  {#if proposal.agreesWithCorpus}
                    <span class="status agreed" title="The AI and this project's own completed alignments picked the same pair.">both agree</span>
                  {:else if proposal.evidence.some((item) => item.kind === "MODEL_PICK")}
                    <span class="status ai-only" title="The AI picked this; this project's completed alignments do not corroborate it. Check it before accepting.">AI only</span>
                  {/if}
                  {#if proposal.status === "AMBIGUOUS"}
                    <span class="status partial" title={proposal.contested
                      ? "Another source word's best candidate is this same target word."
                      : "Another candidate scores as well on the evidence; verse distance alone does not settle it."}
                    >ambiguous</span>
                  {/if}
                </div>
                <div class="proposal-why">{evidenceSummary(proposal)}</div>
                <div class="proposal-actions">
                  {#if proposal.status === "PROPOSED"}
                    <button type="button" on:click={() => acceptProposal(proposal)} disabled={busy || proposalsBusy}>
                      Accept
                    </button>
                  {:else}
                    <button type="button" on:click={() => (gapFilterVerse = proposal.source.verse)} disabled={busy}>
                      Show the gap
                    </button>
                  {/if}
                  <button type="button" class="link" on:click={() => dismissProposal(proposal)} disabled={busy}>
                    Dismiss
                  </button>
                </div>
              </li>
            {/each}
          </ul>
        {/if}
      </section>

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
                <div class="rows">
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
                      title={sourceTitle(src, glossVersion)}
                    >
                      <span class="word">{src.word}{#if src.occurrences > 1}<span class="occ">{occurrence(src)}</span>{/if}</span>
                      {#if sourceGloss(src, glossVersion)}<small class="gloss">{sourceGloss(src, glossVersion)}</small>{/if}
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
                      {/each}
                      {#each linksForSource(context, src.id) as link (link.id)}
                        <span
                          class="token target linked-card"
                          class:invalid={link.state === "invalid"}
                          title={link.state === "invalid"
                            ? (link.invalidReason ?? "This link no longer applies.")
                            : `Realized in verse ${link.target.verse} by ${link.target.word}. Bridge-private link; translationCore alignment is unchanged.`}
                        >
                          <span class="word">{link.target.word}</span>
                          <small>{link.state === "invalid" ? "link invalid" : "realized in"} v.{link.target.verse}</small>
                          <button
                            type="button"
                            class="unalign-x"
                            on:click|stopPropagation={() => unlink(link)}
                            disabled={busy}
                            aria-label={`Remove cross-verse link from ${src.word} to ${link.target.word} in verse ${link.target.verse}`}
                            title="Remove this cross-verse link"
                          >×</button>
                        </span>
                      {/each}
                      {#if alignedTargetsFor(context, src.id).length === 0 && linksForSource(context, src.id).length === 0}
                        <span class="placeholder" aria-hidden="true">·</span>
                      {/if}
                    </div>
                  </div>
                {:else}
                  <p class="empty">{gapFilterVerse ? "Every source word has a counterpart." : "No source tokens in this verse."}</p>
                {/each}
                </div>
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
                    {@const accountedBy = linkForBottom(context, item.id)}
                    {#if accountedBy}
                      <span
                        class="token target accounted"
                        title={`Realizes ${accountedBy.source.word} from verse ${accountedBy.source.verse}. Bridge-private link; this word stays in the word bank for translationCore.`}
                      >
                        <span class="word">{item.word}{#if item.occurrences > 1}<span class="occ">{occurrence(item)}</span>{/if}</span>
                        <small>↔ v.{accountedBy.source.verse}</small>
                        <button
                          type="button"
                          class="unalign-x"
                          on:click|stopPropagation={() => unlink(accountedBy)}
                          disabled={busy}
                          aria-label={`Remove cross-verse link from ${accountedBy.source.word} in verse ${accountedBy.source.verse} to ${item.word}`}
                          title="Remove this cross-verse link"
                        >×</button>
                      </span>
                    {:else if groupForTarget(context, item.id)}
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
  .gap.accounted { background: var(--accent-bg); color: var(--accent); }
  .linked-note { font-weight: 700; }
  .gap-verse { font-weight: 800; color: var(--text); }
  .gap-total { display: flex; flex-direction: column; justify-content: center; gap: 3px; color: var(--text-2); padding: 0 6px; margin-left: auto; text-align: right; }
  .status { border-radius: 999px; padding: 1px 7px; background: var(--surface-2); font-weight: 700; font-size: var(--fs-2xs); color: var(--text-2); }
  .status.complete { color: var(--success); background: #EAF7EF; }
  .status.partial { color: var(--warning); background: var(--warning-bg); }
  .status.invalid { color: var(--danger); background: var(--danger-bg); }
  .notice, .error { border-radius: 9px; padding: 8px 12px; margin-bottom: 8px; font-size: var(--fs-sm); line-height: 1.45; flex-shrink: 0; }
  .notice { background: #EAF7EF; color: var(--success); }
  .suggestion { border-radius: 9px; padding: 8px 12px; margin-bottom: 8px; font-size: var(--fs-sm); background: var(--accent-bg); color: var(--accent); flex-shrink: 0; display: flex; gap: 10px; flex-wrap: wrap; align-items: baseline; }
  .error { background: #FFF0F0; color: var(--danger); }

  /* Cross-verse suggestions (#139). Deliberately above the columns and
     collapsed to a single button until asked: a proposal is a claim about the
     text, and it should not appear as if the page had already decided. */
  .suggest { flex-shrink: 0; margin-bottom: 8px; }
  .suggest-head { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; font-size: var(--fs-xs); color: var(--text-3); }
  .suggest-head .spin { margin-right: 4px; }
  .suggest-count { color: var(--accent); font-weight: 700; }
  /* #146. The AI button sits beside the offline one rather than replacing it:
     the corpus pass costs nothing and works with no key, so it stays the
     default action and this is the deliberate, billed second choice. */
  .suggest-head .ai { border-color: var(--accent); color: var(--accent); font-weight: 600; }
  .ai-off { color: var(--text-3); }
  .status.agreed { color: var(--success); background: #EAF7EF; }
  .status.ai-only { color: var(--accent); background: var(--accent-bg); }
  .proposals { list-style: none; margin: 8px 0 0; padding: 0; display: grid; grid-template-columns: repeat(auto-fill, minmax(min(300px, 100%), 1fr)); gap: 6px; }
  .proposal { border: 1px solid var(--border); border-left: 3px solid var(--accent); border-radius: 9px; padding: 6px 10px; background: var(--surface-2); }
  .proposal.ambiguous { border-left-color: var(--warning); }
  .proposal-claim { display: flex; align-items: baseline; gap: 6px; flex-wrap: wrap; }
  .proposal-claim .word { font-family: var(--font-target); font-size: var(--fs-sm); font-weight: 700; }
  .proposal-claim .source-word { font-family: var(--font-greek); }
  .proposal-claim small { color: var(--text-3); font-size: var(--fs-2xs); }
  .proposal-why { color: var(--text-2); font-size: var(--fs-2xs); margin: 3px 0 5px; line-height: 1.4; }
  .proposal-actions { display: flex; gap: 8px; align-items: center; }
  .proposal-actions button { padding: 3px 9px; font-size: var(--fs-xs); }

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
  /* #136: the source cells flow left-to-right and wrap, so one verse occupies
     several short rows instead of one tall column -- on a small window that is
     the difference between one verse on screen and four. auto-fill, not
     auto-fit: with auto-fit a verse holding a single source word stretches that
     one cell across the whole column, which looks like a layout bug; auto-fill
     keeps the empty tracks and the cell its normal width. Still no sideways
     scroll (#72) -- wrapping is what replaces it, and min(150px, 100%) rather
     than a bare 150px because below that width a bare minimum would size the
     track wider than the column and `.scroll`'s overflow-x would clip it. */
  .rows { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(150px, 100%), 1fr)); gap: 4px 10px; align-items: start; }
  .rows .empty { grid-column: 1 / -1; }
  /* Source word above its drop cell rather than beside it, matching the
     single-verse interlinear. A stacked cell needs roughly half the width of a
     side-by-side one, so the auto-fill track above drops from 230px to 150px
     and the same column now holds two cells where it held one -- which is the
     whole point: more of the range on screen at once. */
  .row { display: flex; flex-direction: column; gap: 3px; padding: 3px 0; min-width: 0; }
  .token { display: inline-flex; flex-direction: column; align-items: center; gap: 2px; min-width: 62px; }
  /* max-width: 100% (was a fixed 160px): inside a flowed cell (#136) the label
     must ellipsize within its own track, or a long one widens the source column
     and squeezes the drop cell below it. */
  .token small { font-size: var(--fs-3xs); color: var(--text-3); max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  /* The gloss replaced the lemma here, so it must undo what the lemma needed:
     `.token.source` carries the Greek/Hebrew face and, for an OT book, dir=rtl
     -- both wrong for an English definition. Two lines rather than one
     ellipsized one, because at 150px a single line of definition is mostly the
     ellipsis; the unabridged text stays in the tooltip and the lexicon popup. */
  .gloss {
    font-family: var(--font-ui); direction: ltr; text-align: left;
    white-space: normal; line-height: 1.25;
    display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 2; line-clamp: 2;
  }
  .occ { margin-left: 3px; font-size: 0.8em; font-weight: 400; color: var(--text-3); }
  /* min-width: 0 overrides `.token`'s 62px so the source cell can shrink inside
     a flowed track (#136) and ellipsize, instead of overflowing it. */
  .token.source { width: 100%; min-width: 0; background: #F6F1FF; cursor: pointer; align-items: flex-start; font-family: var(--font-greek); }
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
  .linked-card, .accounted {
    flex-direction: row; align-items: center; gap: 5px; min-width: 0; border: 1px dashed var(--accent);
    border-radius: 7px; padding: 4px 6px 4px 9px; background: var(--accent-bg); color: var(--text);
  }
  .linked-card .word, .accounted .word { font-size: var(--fs-sm); }
  .linked-card small, .accounted small { font-size: var(--fs-3xs); color: var(--accent); font-weight: 700; white-space: nowrap; }
  .linked-card.invalid { border-color: var(--danger); background: var(--danger-bg); }
  .linked-card.invalid small { color: var(--danger); }
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
