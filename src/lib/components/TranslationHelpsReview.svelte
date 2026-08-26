<script lang="ts">
  import { onDestroy } from "svelte";
  import { bridge } from "../api/bridgeClient";
  import {
    aiCheckReviewsByVerse, checkStatusByVerse, findingsByVerse, nativeChecksByVerse,
    reviewerMode, verseKey, verseTexts,
  } from "../stores";
  import type { AiCheckReview, CheckTargetSelection, NativeCheckListResponse, NativeCheckReview } from "../types/finding";
  import { exactTextRanges } from "../utils/highlight";

  export let chapter: string;
  export let verse: string;
  export let onStateChanged: () => void = () => {};
  export let onRerunAIReview: () => void = () => {};
  export let aiReviewBusy = false;

  let requestedKey = "";
  let loadSequence = 0;
  let loading = false;
  let loadError = "";
  let preparationMessage = "";
  let retryTimer: ReturnType<typeof setTimeout> | undefined;
  let editingKey = "";
  let rows: CheckTargetSelection[] = [];
  let nothingToSelect = false;
  let mutationBusy = false;
  let mutationError = "";
  let mutationNotice = "";
  let aiReviewState: NativeCheckListResponse["aiReviewState"] = "missing";

  $: key = verseKey(chapter, verse);
  $: checks = $nativeChecksByVerse[key] ?? [];
  $: aiReviews = $aiCheckReviewsByVerse[key] ?? [];
  $: verseText = $verseTexts[key] ?? "";
  $: if (key && key !== requestedKey) {
    if (retryTimer) clearTimeout(retryTimer);
    requestedKey = key;
    editingKey = "";
    mutationError = "";
    mutationNotice = "";
    aiReviewState = "missing";
    void refresh();
  }

  onDestroy(() => {
    loadSequence += 1;
    if (retryTimer) clearTimeout(retryTimer);
  });

  function identity(check: NativeCheckReview): string {
    return `${check.tool}:${check.groupId}:${check.checkId}`;
  }

  function aiReviewFor(check: NativeCheckReview): AiCheckReview | undefined {
    return aiReviews.find((item) => item.tool === check.tool && item.check_id === check.checkId);
  }

  function toolLabel(check: NativeCheckReview): string {
    return check.tool === "translationNotes" ? "Translation Note" : "Translation Word";
  }

  function statusLabel(check: NativeCheckReview): string {
    if (check.selectionStatus === "nothing_to_select") return "Nothing to select";
    if (check.selectionStatus === "invalidated") return "Recheck required";
    return check.selectionStatus.charAt(0).toUpperCase() + check.selectionStatus.slice(1);
  }

  function evidenceLabel(item: Record<string, unknown>): string {
    const title = String(item.title ?? item.identifier ?? item.kind ?? "Evidence");
    const version = String(item.version ?? "");
    return version ? `${title} · ${version}` : title;
  }

  export async function refresh(): Promise<void> {
    const refreshKey = verseKey(chapter, verse);
    const sequence = ++loadSequence;
    if (retryTimer) {
      clearTimeout(retryTimer);
      retryTimer = undefined;
    }
    loading = true;
    loadError = "";
    preparationMessage = "";
    try {
      const result = await bridge.listChecksForVerse(chapter, verse);
      if (sequence !== loadSequence || refreshKey !== key) return;
      if (result.state === "preparing") {
        preparationMessage = result.message || "Preparing translation helps…";
        const delay = Math.max(500, Math.min(result.retryAfterMs || 750, 2000));
        retryTimer = setTimeout(() => {
          retryTimer = undefined;
          if (sequence === loadSequence && refreshKey === key) void refresh();
        }, delay);
        return;
      }
      nativeChecksByVerse.update((values) => ({ ...values, [refreshKey]: result.checks }));
      aiCheckReviewsByVerse.update((values) => ({ ...values, [refreshKey]: result.aiReviews ?? [] }));
      aiReviewState = result.aiReviewState ?? "missing";
    } catch (error) {
      if (sequence !== loadSequence || refreshKey !== key) return;
      loadError = error instanceof Error ? error.message : String(error);
    } finally {
      if (sequence === loadSequence) loading = false;
    }
  }

  function startEditing(check: NativeCheckReview): void {
    editingKey = identity(check);
    rows = check.selections.length > 0
      ? check.selections.map((selection) => ({ ...selection }))
      : [{ text: "", occurrence: 1, occurrences: 0 }];
    nothingToSelect = check.nothingToSelect;
    mutationError = "";
    mutationNotice = "";
  }

  function cancelEditing(): void {
    if (mutationBusy) return;
    editingKey = "";
    mutationError = "";
  }

  function selectionChanged(index: number): void {
    const next = rows.map((row) => ({ ...row }));
    const text = next[index].text.trim();
    const occurrences = exactTextRanges(verseText, text).length;
    next[index].occurrences = occurrences;
    if (occurrences === 0) next[index].occurrence = 1;
    else if (next[index].occurrence > occurrences) next[index].occurrence = occurrences;
    rows = next;
  }

  function removeSelection(index: number): void {
    rows = rows.filter((_, rowIndex) => rowIndex !== index);
    if (rows.length === 0) rows = [{ text: "", occurrence: 1, occurrences: 0 }];
  }

  async function refreshLocalFindings(operationChapter: string, operationVerse: string, operationKey: string): Promise<void> {
    const local = await bridge.runVerseChecks(operationChapter, operationVerse, ["local"]);
    findingsByVerse.update((values) => {
      const live = (values[operationKey] ?? []).filter((finding) => finding.engine === "wildebeest");
      return { ...values, [operationKey]: [...live, ...local] };
    });
    checkStatusByVerse.update((values) => ({ ...values, [operationKey]: "succeeded" }));
  }

  async function saveSelection(check: NativeCheckReview): Promise<void> {
    if (mutationBusy) return;
    mutationBusy = true;
    mutationError = "";
    mutationNotice = "";
    const operationChapter = chapter;
    const operationVerse = verse;
    const operationKey = verseKey(operationChapter, operationVerse);
    const selections = nothingToSelect
      ? []
      : rows.map((row) => ({ ...row, text: row.text.trim() }));
    try {
      const validation = await bridge.validateCheckSelection(
        operationChapter, operationVerse, check.tool, check.groupId, check.checkId, selections, nothingToSelect,
      );
      if (!validation.valid) {
        if (key === operationKey) mutationError = validation.errors.join(" ");
        return;
      }
      const result = await bridge.saveCheckSelection(
        operationChapter, operationVerse, check.tool, check.groupId, check.checkId,
        validation.selections, nothingToSelect, "human", validation.stateFingerprint,
        { interface: "advanced", evidenceDisplayed: Boolean(aiReviewFor(check)) },
      );
      nativeChecksByVerse.update((values) => ({
        ...values,
        [operationKey]: (values[operationKey] ?? []).map((item) => identity(item) === identity(check) ? result.review : item),
      }));
      aiCheckReviewsByVerse.update((values) => {
        const next = { ...values };
        delete next[operationKey];
        return next;
      });
      if (key === operationKey) {
        onStateChanged();
        editingKey = "";
        mutationNotice = `${toolLabel(check)} selection saved.`;
      }
      try {
        await refreshLocalFindings(operationChapter, operationVerse, operationKey);
      } catch (error) {
        if (key === operationKey) mutationNotice = `Selection saved, but local findings could not refresh: ${error instanceof Error ? error.message : String(error)}`;
      }
    } catch (error) {
      if (key === operationKey) mutationError = error instanceof Error ? error.message : String(error);
    } finally {
      mutationBusy = false;
    }
  }

  async function clearSelection(check: NativeCheckReview): Promise<void> {
    if (mutationBusy) return;
    mutationBusy = true;
    mutationError = "";
    mutationNotice = "";
    const operationChapter = chapter;
    const operationVerse = verse;
    const operationKey = verseKey(operationChapter, operationVerse);
    try {
      const result = await bridge.clearCheckSelection(
        operationChapter, operationVerse, check.tool, check.groupId, check.checkId,
        "human", check.stateFingerprint, { interface: "advanced" },
      );
      nativeChecksByVerse.update((values) => ({
        ...values,
        [operationKey]: (values[operationKey] ?? []).map((item) => identity(item) === identity(check) ? result.review : item),
      }));
      aiCheckReviewsByVerse.update((values) => {
        const next = { ...values };
        delete next[operationKey];
        return next;
      });
      if (key === operationKey) {
        onStateChanged();
        editingKey = "";
        mutationNotice = `${toolLabel(check)} selection cleared.`;
      }
      try {
        await refreshLocalFindings(operationChapter, operationVerse, operationKey);
      } catch (error) {
        if (key === operationKey) mutationNotice = `Selection cleared, but local findings could not refresh: ${error instanceof Error ? error.message : String(error)}`;
      }
    } catch (error) {
      if (key === operationKey) mutationError = error instanceof Error ? error.message : String(error);
    } finally {
      mutationBusy = false;
    }
  }

  async function applyAiProposal(check: NativeCheckReview, aiReview: AiCheckReview): Promise<void> {
    if (mutationBusy) return;
    mutationBusy = true;
    mutationError = "";
    mutationNotice = "";
    const operationChapter = chapter;
    const operationVerse = verse;
    const operationKey = verseKey(operationChapter, operationVerse);
    try {
      const validation = await bridge.validateCheckSelection(
        operationChapter, operationVerse, check.tool, check.groupId, check.checkId,
        aiReview.proposed_selections ?? [], aiReview.nothing_to_select,
      );
      if (!validation.valid) {
        mutationError = validation.errors.join(" ");
        return;
      }
      await bridge.saveCheckSelection(
        operationChapter, operationVerse, check.tool, check.groupId, check.checkId,
        validation.selections, aiReview.nothing_to_select, "bridge_ai", validation.stateFingerprint,
        {
          interface: "advanced-ai-proposal", confidence: aiReview.confidence,
          verdict: aiReview.verdict, evidenceGrounded: aiReview.evidence_used.length > 0,
        },
      );
      await refresh();
      if (key === operationKey) {
        mutationNotice = `${toolLabel(check)} AI proposal applied. You can still edit or clear it.`;
        onStateChanged();
      }
      try {
        await refreshLocalFindings(operationChapter, operationVerse, operationKey);
      } catch (error) {
        mutationNotice = `AI proposal applied, but local findings could not refresh: ${error instanceof Error ? error.message : String(error)}`;
      }
    } catch (error) {
      if (key === operationKey) mutationError = error instanceof Error ? error.message : String(error);
    } finally {
      mutationBusy = false;
    }
  }
</script>

<div class="section translation-helps">
  <div class="section-title">
    Translation helps
    <span class="mode-badge">{$reviewerMode}</span>
    {#if loading}<span class="loading-label"><span class="spin" /> loading</span>{/if}
  </div>

  {#if aiReviewState === "stale"}
    <div class="stale-review-notice" role="status">
      <div>
        <b>Verse changed — the previous AI review is stale.</b>
        <span>Run AI review again before treating this verse as reviewed.</span>
      </div>
      <button class="small-btn" on:click={onRerunAIReview} disabled={aiReviewBusy}>Run AI review again</button>
    </div>
  {/if}
  {#if $reviewerMode === "basic" && checks.some((check) => check.selectionStatus === "pending")}
    <div class="basic-notice">Run AI review to evaluate these checks. Only high-confidence, evidence-grounded selections are applied automatically; uncertain checks stay pending.</div>
  {/if}
  {#if mutationNotice}<div class="mutation-notice">{mutationNotice}</div>{/if}
  {#if preparationMessage}<div class="preparing-notice"><span class="spin" /> {preparationMessage}</div>{/if}
  {#if loadError}
    <div class="load-error">Could not load translation helps: {loadError}</div>
    <button class="small-btn" on:click={refresh}>Retry</button>
  {:else if !loading && !preparationMessage && checks.length === 0}
    <p class="none">No translationNotes or translationWords checks are available for this verse.</p>
  {/if}

  {#each checks as check (identity(check))}
    {@const aiReview = aiReviewFor(check)}
    <article class="native-check" class:tn={check.tool === "translationNotes"} class:tw={check.tool === "translationWords"} class:invalid={check.invalidated}>
      <div class="check-heading">
        <span class="tool-dot" />
        <strong>{toolLabel(check)}</strong>
        <span class="check-group">{check.groupId || check.checkId}</span>
        <span class="status {check.selectionStatus}">{statusLabel(check)}</span>
      </div>
      <div class="source-row"><span>Source</span><b>{check.sourceQuote || "No source quote"}</b>{#if check.sourceOccurrence}<small>occurrence {check.sourceOccurrence}</small>{/if}</div>
      {#if check.selections.length > 0}
        <div class="selection-list">
          {#each check.selections as selection}
            <span class="selection-chip">{selection.text}{selection.occurrences > 1 ? ` · ${selection.occurrence}/${selection.occurrences}` : ""}</span>
          {/each}
        </div>
      {:else if check.nothingToSelect}
        <p class="selection-empty">Reviewer marked that no target selection is required.</p>
      {/if}

      <details>
        <summary>Evidence and justification</summary>
        {#if check.occurrenceNote}<p>{check.occurrenceNote}</p>{/if}
        {#if aiReview}
          <div class="ai-evidence">
            <div><b>AI {aiReview.verdict}</b> · {Math.round(aiReview.confidence * 100)}% confidence</div>
            <p>{aiReview.rationale}</p>
            {#if aiReview.suggested_correction}<p><b>Suggested correction:</b> {aiReview.suggested_correction}</p>{/if}
            {#if aiReview.evidence_used.length > 0}
              <ul>{#each aiReview.evidence_used as item}<li>{evidenceLabel(item)}</li>{/each}</ul>
            {/if}
          </div>
        {:else}
          <p class="muted-evidence">No AI evaluation has been run for this check. Native selection state is shown without calling it passed.</p>
        {/if}
        <div class="provenance">Selection provenance: {check.provenance.replaceAll("_", " ")}</div>
      </details>

      {#if $reviewerMode === "advanced"}
        {#if editingKey === identity(check)}
          <div class="selection-editor">
            <label class="nothing-row"><input type="checkbox" bind:checked={nothingToSelect} /> Nothing to select in the target verse</label>
            {#if !nothingToSelect}
              {#each rows as row, index}
                <div class="selection-row">
                  <input aria-label="Exact target text" bind:value={row.text} on:input={() => selectionChanged(index)} placeholder="Exact word or phrase" />
                  {#if row.occurrences > 1}
                    <select aria-label="Occurrence" bind:value={row.occurrence}>
                      {#each Array(row.occurrences) as _, occurrenceIndex}<option value={occurrenceIndex + 1}>{occurrenceIndex + 1} of {row.occurrences}</option>{/each}
                    </select>
                  {:else}
                    <span class:missing={row.text.trim() && row.occurrences === 0} class="match-count">{row.text.trim() ? (row.occurrences === 1 ? "1 match" : "Not found") : "Enter text"}</span>
                  {/if}
                  <button class="icon-btn" on:click={() => removeSelection(index)} aria-label="Remove selection">×</button>
                </div>
              {/each}
              <button class="small-btn" on:click={() => (rows = [...rows, { text: "", occurrence: 1, occurrences: 0 }])}>+ Add another selection</button>
            {/if}
            {#if mutationError}<p class="mutation-error">{mutationError}</p>{/if}
            <div class="editor-actions">
              <button class="save-btn" on:click={() => saveSelection(check)} disabled={mutationBusy}>{mutationBusy ? "Saving…" : "Validate & save"}</button>
              <button class="small-btn" on:click={cancelEditing} disabled={mutationBusy}>Cancel</button>
            </div>
          </div>
        {:else}
          <div class="advanced-actions">
            {#if aiReview && ((aiReview.proposed_selections ?? []).length > 0 || aiReview.nothing_to_select)}
              <button class="small-btn ai-apply" on:click={() => applyAiProposal(check, aiReview)} disabled={mutationBusy}>Apply AI proposal</button>
            {/if}
            <button class="small-btn" on:click={() => startEditing(check)}>Edit selection</button>
            {#if check.selectionStatus !== "pending"}
              <button class="small-btn danger" on:click={() => clearSelection(check)} disabled={mutationBusy}>Clear</button>
            {/if}
          </div>
        {/if}
      {/if}
    </article>
  {/each}
</div>

<style>
  .section { border: 1px solid var(--border); border-radius: 12px; padding: 12px 14px; margin-bottom: 12px; }
  .section-title { font-size: 11px; font-weight: 700; color: var(--text); display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
  .mode-badge { margin-left: auto; text-transform: capitalize; font-size: 9px; padding: 2px 6px; border-radius: 999px; color: var(--accent); background: var(--accent-bg); }
  .loading-label { display: flex; align-items: center; gap: 4px; color: var(--text-3); font-weight: 500; }
  .spin { width: 9px; height: 9px; border-radius: 50%; border: 2px solid var(--accent-bg); border-top-color: var(--accent); animation: spin .8s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .basic-notice, .mutation-notice, .preparing-notice, .load-error, .stale-review-notice { font-size: 10px; line-height: 1.4; border-radius: 6px; padding: 7px 8px; margin-bottom: 8px; }
  .basic-notice { color: var(--warning); background: var(--warning-bg); }
  .mutation-notice { color: var(--success); background: var(--success-bg); overflow-wrap: anywhere; }
  .preparing-notice { display: flex; align-items: center; gap: 6px; color: var(--accent); background: var(--accent-bg); }
  .load-error { color: var(--danger); background: var(--danger-bg); overflow-wrap: anywhere; }
  .stale-review-notice { display: flex; align-items: center; justify-content: space-between; gap: 8px; color: var(--warning); background: var(--warning-bg); border: 1px solid color-mix(in srgb, var(--warning) 28%, transparent); }
  .stale-review-notice div { display: grid; gap: 2px; min-width: 0; }
  .stale-review-notice button { flex-shrink: 0; background: var(--surface); }
  .native-check { border: 1px solid var(--border); border-left-width: 3px; border-radius: 8px; padding: 9px 10px; margin-top: 8px; }
  .native-check.tn { border-left-color: var(--tn); }
  .native-check.tw { border-left-color: var(--tw); }
  .native-check.invalid { background: var(--warning-bg); }
  .check-heading { display: flex; align-items: center; gap: 6px; min-width: 0; }
  .check-heading strong { font-size: 10px; color: var(--text); }
  .tool-dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }
  .tn .tool-dot { background: var(--tn); }
  .tw .tool-dot { background: var(--tw); }
  .check-group { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 10px; color: var(--text-3); }
  .status { margin-left: auto; flex-shrink: 0; font-size: 9px; padding: 2px 6px; border-radius: 999px; text-transform: capitalize; background: var(--surface-2); color: var(--text-2); }
  .status.selected, .status.nothing_to_select { color: var(--success); background: var(--success-bg); }
  .status.invalidated { color: var(--warning); background: var(--warning-bg); }
  .source-row { display: flex; align-items: baseline; gap: 6px; margin-top: 7px; font-size: 10px; }
  .source-row span, .source-row small { color: var(--text-3); }
  .source-row b { color: var(--text); font-size: 12px; overflow-wrap: anywhere; }
  .selection-list { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 7px; }
  .selection-chip { font-size: 10px; padding: 3px 6px; border-radius: 5px; background: var(--accent-bg); color: var(--accent); }
  .selection-empty { font-size: 10px; color: var(--text-2); margin: 7px 0 0; }
  details { margin-top: 7px; font-size: 10px; color: var(--text-2); }
  summary { cursor: pointer; color: var(--accent); font-weight: 650; }
  details p { line-height: 1.45; margin: 6px 0; white-space: pre-wrap; }
  details ul { margin: 5px 0; padding-left: 16px; }
  .ai-evidence { margin-top: 6px; padding: 7px; background: var(--accent-bg); border-radius: 6px; }
  .muted-evidence, .provenance { color: var(--text-3); }
  .provenance { margin-top: 5px; text-transform: capitalize; }
  .advanced-actions, .editor-actions { display: flex; gap: 6px; margin-top: 8px; }
  .small-btn, .save-btn, .icon-btn { border-radius: 5px; cursor: pointer; font-size: 10px; }
  .small-btn { padding: 5px 8px; color: var(--text-2); background: var(--surface); border: 1px solid var(--border-strong); }
  .small-btn.danger { color: var(--danger); }
  .small-btn.ai-apply { color: var(--accent); border-color: var(--accent); }
  .save-btn { padding: 6px 9px; border: 0; color: white; background: var(--accent); font-weight: 700; }
  .small-btn:disabled, .save-btn:disabled { opacity: .55; cursor: not-allowed; }
  .selection-editor { margin-top: 8px; border-top: 1px dashed var(--border); padding-top: 8px; }
  .nothing-row { display: flex; align-items: center; gap: 6px; font-size: 10px; color: var(--text-2); margin-bottom: 7px; }
  .selection-row { display: grid; grid-template-columns: minmax(0, 1fr) 80px 24px; gap: 5px; margin-bottom: 5px; }
  .selection-row input, .selection-row select { min-width: 0; height: 27px; border: 1px solid var(--border); border-radius: 5px; padding: 0 6px; font: inherit; font-size: 10px; background: var(--surface); color: var(--text); }
  .match-count { align-self: center; color: var(--success); font-size: 9px; }
  .match-count.missing { color: var(--danger); }
  .icon-btn { height: 27px; border: 1px solid var(--border); color: var(--text-3); background: var(--surface-2); }
  .mutation-error { color: var(--danger); font-size: 10px; line-height: 1.4; margin: 7px 0 0; }
  .none { font-size: 11px; color: var(--text-3); }
</style>
