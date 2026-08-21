<script lang="ts">
  import { onMount } from "svelte";
  import { bridge } from "../api/bridgeClient";
  import {
    alignmentStatusByVerse, checkStatusByVerse, currentChapter, findingsByVerse,
    verseKey,
  } from "../stores";
  import type { AlignmentContext, AlignmentToken } from "../types/finding";

  export let chapter: string;
  export let verse: string;
  export let onClose: () => void;

  let context: AlignmentContext | null = null;
  let loading = true;
  let busy = false;
  let error = "";
  let notice = "";
  let selectedTop: string[] = [];
  let selectedBottom: string[] = [];
  let restoreId = "";

  onMount(load);

  async function load() {
    loading = true;
    error = "";
    try {
      context = await bridge.getAlignment(chapter, verse);
      restoreId = context.history[0]?.id ?? "";
    } catch (value) {
      error = value instanceof Error ? value.message : String(value);
    } finally {
      loading = false;
    }
  }

  function toggle(list: string[], id: string): string[] {
    return list.includes(id) ? list.filter((value) => value !== id) : [...list, id];
  }

  function label(token: AlignmentToken): string {
    return token.occurrences > 1 ? `${token.word} ${token.occurrence}/${token.occurrences}` : token.word;
  }

  function token(ids: string[], source: "top" | "bottom"): string {
    if (!context) return "";
    const inventory = source === "top" ? context.topTokens : context.bottomTokens;
    return ids.map((id) => inventory.find((item) => item.id === id)?.word ?? id).join(" ");
  }

  function targetGroup(id: string): string {
    if (!context) return "";
    return context.groups.find((group) => group.bottomIds.includes(id))?.id ?? "";
  }

  async function refreshChecks(updated: AlignmentContext, message: string) {
    context = updated;
    selectedTop = [];
    selectedBottom = [];
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

  function alignSelected() {
    if (!context) return;
    void mutate(
      () => bridge.realignWords(chapter, verse, selectedTop, selectedBottom, context!.alignment),
      "Alignment saved.",
    );
  }

  function unalignSelected() {
    if (!context) return;
    void mutate(
      () => bridge.unalignWords(chapter, verse, selectedBottom, context!.alignment),
      "Selected target words returned to the word bank.",
    );
  }

  function complete() {
    void mutate(() => bridge.completeAlignment(chapter, verse), "Alignment marked complete.");
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

<svelte:window on:keydown={(event) => event.key === "Escape" && !busy && onClose()} />

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
      {/if}

      {#if context.issues.length > 0}
        <div class="issues">
          {#each context.issues as issue}<div>⚠ {issue}</div>{/each}
        </div>
      {/if}

      {#if notice}<div class="notice">✓ {notice}</div>{/if}
      {#if error}<div class="error">{error}</div>{/if}

      <div class="workspace">
        <section class="token-panel">
          <div class="panel-title">
            <span>Source words</span>
            <small>Select one or more</small>
          </div>
          <div class="tokens" dir={context.sourceDirection}>
            {#each context.topTokens as item}
              <button
                class="token source"
                class:selected={selectedTop.includes(item.id)}
                on:click={() => (selectedTop = toggle(selectedTop, item.id))}
                disabled={busy || !context.sourceAvailable}
                title={[item.lemma, item.strong, item.morph].filter(Boolean).join(" · ")}
              >
                <span>{label(item)}</span>
                {#if item.lemma}<small>{item.lemma}</small>{/if}
              </button>
            {:else}
              <p class="empty">No source tokens are present in this verse.</p>
            {/each}
          </div>
        </section>

        <section class="token-panel">
          <div class="panel-title">
            <span>Target words</span>
            <small>Select words to align or unalign</small>
          </div>
          <div class="tokens" dir={context.targetDirection}>
            {#each context.bottomTokens as item}
              {@const group = targetGroup(item.id)}
              <button
                class="token target"
                class:selected={selectedBottom.includes(item.id)}
                class:unaligned={!group}
                on:click={() => (selectedBottom = toggle(selectedBottom, item.id))}
                disabled={busy}
                title={group ? `Currently in ${group}` : "Currently in word bank"}
              >
                <span>{label(item)}</span>
                <small>{group || "word bank"}</small>
              </button>
            {/each}
          </div>
        </section>
      </div>

      <div class="primary-actions">
        <button
          class="primary"
          on:click={alignSelected}
          disabled={busy || !context.sourceAvailable || selectedTop.length === 0 || selectedBottom.length === 0}
        >{busy ? "Saving…" : "Align selected & save"}</button>
        <button
          on:click={unalignSelected}
          disabled={busy || selectedBottom.length === 0 || selectedBottom.every((id) => !targetGroup(id))}
        >Unalign selected & save</button>
        <button on:click={() => { selectedTop = []; selectedBottom = []; }} disabled={busy}>Clear selection</button>
      </div>

      <section class="groups">
        <div class="panel-title"><span>Current alignment groups</span><small>Supports 1:1, 1:many, many:1 and many:many</small></div>
        <div class="group-grid">
          {#each context.groups as group}
            <div class="group-card" class:incomplete={group.bottomIds.length === 0}>
              <span class="group-id">{group.id}</span>
              <span dir={context.sourceDirection}>{token(group.topIds, "top") || "No source"}</span>
              <span class="arrow">↔</span>
              <span dir={context.targetDirection}>{token(group.bottomIds, "bottom") || "Unaligned"}</span>
            </div>
          {:else}<p class="empty">No alignment groups yet.</p>{/each}
        </div>
      </section>

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
          <button class="complete" on:click={complete} disabled={busy || !context.canComplete || context.completionState === "completed"}>
            Mark alignment complete
          </button>
        </div>
      </footer>
    {:else if error}
      <div class="error">{error}</div>
    {/if}
  </section>
</div>

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
  .source-warning, .issues, .notice, .error { border-radius: 9px; padding: 10px 12px; margin-bottom: 12px; font-size: 12px; line-height: 1.45; }
  .source-warning { display: flex; flex-direction: column; gap: 3px; background: var(--warning-bg); color: var(--warning); }
  .issues { background: #FFF5F5; color: var(--danger); }
  .notice { background: #EAF7EF; color: var(--success); }
  .error { background: #FFF0F0; color: var(--danger); }
  .workspace { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
  .token-panel, .groups { border: 1px solid var(--border); border-radius: 10px; padding: 12px; }
  .panel-title { display: flex; justify-content: space-between; gap: 10px; font-size: 12px; font-weight: 700; margin-bottom: 10px; }
  .panel-title small { color: var(--text-3); font-weight: 400; }
  .tokens { display: flex; flex-wrap: wrap; gap: 7px; min-height: 75px; align-content: flex-start; }
  .token { display: inline-flex; flex-direction: column; align-items: flex-start; gap: 2px; min-width: 62px; }
  .token small { font-size: 9px; color: var(--text-3); max-width: 130px; overflow: hidden; text-overflow: ellipsis; }
  .token.source { background: #F6F1FF; }
  .token.target { background: #EFF7FF; }
  .token.unaligned { border-style: dashed; background: var(--warning-bg); }
  .token.selected { color: white; background: var(--accent); border-color: var(--accent); }
  .token.selected small { color: rgba(255,255,255,.8); }
  .primary-actions { display: flex; flex-wrap: wrap; gap: 8px; padding: 12px 0; }
  button.primary, button.complete { background: var(--accent); border-color: var(--accent); color: white; font-weight: 700; }
  .groups { margin-bottom: 12px; }
  .group-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 7px; }
  .group-card { display: grid; grid-template-columns: 42px 1fr 20px 1fr; gap: 7px; align-items: center; border: 1px solid var(--border); border-radius: 7px; padding: 8px; font-size: 11px; }
  .group-card.incomplete { border-color: #E7B25D; background: var(--warning-bg); }
  .group-id { color: var(--text-3); font-size: 9px; font-weight: 700; }
  .arrow { color: var(--accent); text-align: center; }
  .empty { color: var(--text-3); font-size: 11px; margin: 6px; }
  footer { display: flex; justify-content: space-between; gap: 12px; align-items: center; flex-wrap: wrap; }
  .history-controls, .completion { display: flex; align-items: center; gap: 7px; }
  select { border: 1px solid var(--border-strong); border-radius: 7px; padding: 7px; max-width: 235px; color: var(--text); background: var(--surface); }
  .completed { font-size: 11px; font-weight: 700; padding: 5px 8px; border-radius: 999px; }
  @media (max-width: 780px) {
    .workspace, .group-grid { grid-template-columns: 1fr; }
    .modal { padding: 14px; }
    footer { align-items: stretch; }
    .history-controls, .completion { flex-wrap: wrap; }
  }
</style>
