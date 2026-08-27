<script lang="ts">
  import { onDestroy } from "svelte";
  import { bridge } from "../api/bridgeClient";
  import {
    aiCheckReviewsByVerse, checkStatusByVerse, findingsByVerse, nativeChecksByVerse,
    reviewerMode, verseKey, verseTexts,
  } from "../stores";
  import type {
    AiCheckReview, CheckTargetSelection, DesktopConnectorState, IssueResolutionRecord,
    NativeCheckListResponse, NativeCheckReview,
  } from "../types/finding";
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
  let resolutions: IssueResolutionRecord[] = [];
  let resolutionLoadSequence = 0;
  let resolutionKey = "";
  let resolutionSelectedText = "";
  let resolutionIssueSummary = "";
  let resolutionReviewerNote = "";
  let resolutionCorrection = "";
  let resolutionBusy = false;
  let resolutionError = "";
  let connectorState: DesktopConnectorState | null = null;
  let connectorMessage = "";

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
    resolutionKey = "";
    resolutionError = "";
    connectorState = null;
    void refreshResolutions();
    void refresh();
  }

  onDestroy(() => {
    loadSequence += 1;
    resolutionLoadSequence += 1;
    if (retryTimer) clearTimeout(retryTimer);
  });

  function identity(check: NativeCheckReview): string {
    return `${check.tool}:${check.groupId}:${check.checkId}`;
  }

  function aiReviewFor(check: NativeCheckReview): AiCheckReview | undefined {
    return aiReviews.find((item) => item.tool === check.tool && item.check_id === check.checkId);
  }

  function resolutionFor(check: NativeCheckReview): IssueResolutionRecord | undefined {
    return resolutions.find((item) => (
      item.check.tool === check.tool
      && item.check.groupId === check.groupId
      && item.check.checkId === check.checkId
    ));
  }

  async function refreshResolutions(): Promise<void> {
    const operationKey = verseKey(chapter, verse);
    const sequence = ++resolutionLoadSequence;
    try {
      const result = await bridge.listIssueResolutions(chapter, verse);
      if (sequence === resolutionLoadSequence && operationKey === key) resolutions = result.items;
    } catch (error) {
      if (sequence === resolutionLoadSequence && operationKey === key) {
        console.error("Could not restore issue resolutions", error);
        resolutions = [];
      }
    }
  }

  function replaceResolution(record: IssueResolutionRecord): void {
    resolutions = [
      ...resolutions.filter((item) => item.resolutionId !== record.resolutionId),
      record,
    ];
  }

  async function startResolution(check: NativeCheckReview, aiReview?: AiCheckReview): Promise<void> {
    const existing = resolutionFor(check);
    resolutionKey = identity(check);
    resolutionSelectedText = existing?.selectedText
      || check.selections[0]?.text
      || aiReview?.proposed_selections?.[0]?.text
      || "";
    resolutionIssueSummary = existing?.issueSummary
      || aiReview?.rationale
      || check.occurrenceNote
      || `${toolLabel(check)} requires review.`;
    resolutionReviewerNote = existing?.reviewerNote || "";
    resolutionCorrection = existing?.proposedCorrection || aiReview?.suggested_correction || "";
    resolutionError = "";
    connectorState = null;
    connectorMessage = "Checking the local Paratext connection…";
    try {
      const state = await bridge.paratextGetState();
      if (resolutionKey !== identity(check)) return;
      connectorState = state;
      const hasProjectIdentity = Boolean(state.connected && state.project_id?.trim());
      connectorMessage = hasProjectIdentity
        ? `Destination: ${state.project_name || "Paratext project"} · ${state.project_id}`
        : state.connected
          ? "Connected to Paratext, but no active Scripture project was detected. Open and focus the destination project in Paratext; this handoff will remain safely queued."
          : "Paratext is not connected; this handoff will remain safely queued.";
    } catch (error) {
      if (resolutionKey !== identity(check)) return;
      connectorMessage = `Paratext is unavailable; this handoff will remain safely queued. ${error instanceof Error ? error.message : String(error)}`;
    }
  }

  function cancelResolution(): void {
    if (resolutionBusy) return;
    resolutionKey = "";
    resolutionError = "";
  }

  async function saveAndQueueResolution(check: NativeCheckReview, aiReview?: AiCheckReview): Promise<void> {
    if (resolutionBusy) return;
    resolutionBusy = true;
    resolutionError = "";
    try {
      const record = await bridge.saveIssueResolution(chapter, verse, {
        tool: check.tool, groupId: check.groupId, checkId: check.checkId,
        expectedFingerprint: check.stateFingerprint,
      }, {
        selectedText: resolutionSelectedText.trim(),
        issueSummary: resolutionIssueSummary.trim(),
        reviewerNote: resolutionReviewerNote.trim(),
        proposedCorrection: resolutionCorrection.trim(),
        evidence: aiReview?.evidence_used ?? [],
      });
      const result = await bridge.queueIssueResolutionForParatext(
        chapter, verse, record.resolutionId, String(connectorState?.project_id ?? ""),
      );
      // The queue call returns the record after the live handoff attempt. Use
      // that authoritative snapshot so a slower list request cannot repaint a
      // successfully sent item as queued.
      replaceResolution(result.record);
      mutationNotice = result.handoff.status === "sent"
        ? "Issue resolution saved and sent to Paratext."
        : `Issue resolution saved in the Paratext outbox. ${result.handoff.lastError || "Retry when Paratext is available."}`;
      resolutionKey = "";
    } catch (error) {
      resolutionError = error instanceof Error ? error.message : String(error);
    } finally {
      resolutionBusy = false;
    }
  }

  async function retryResolution(record: IssueResolutionRecord): Promise<void> {
    if (resolutionBusy) return;
    resolutionBusy = true;
    mutationError = "";
    try {
      const result = await bridge.retryIssueResolutionParatext(chapter, verse, record.resolutionId);
      replaceResolution(result.record);
      mutationNotice = result.handoff.status === "sent"
        ? "Queued issue was sent to Paratext."
        : `Paratext handoff remains queued. ${result.handoff.lastError}`;
    } catch (error) {
      mutationError = error instanceof Error ? error.message : String(error);
    } finally {
      resolutionBusy = false;
    }
  }

  function toolLabel(check: NativeCheckReview): string {
    return check.tool === "translationNotes" ? "Translation Note" : "Translation Word";
  }

  function statusLabel(check: NativeCheckReview): string {
    if (check.selectionStatus === "nothing_to_select") return "Nothing to select";
    if (check.selectionStatus === "invalidated") return "Recheck required";
    return check.selectionStatus.charAt(0).toUpperCase() + check.selectionStatus.slice(1);
  }

  function resolutionLifecycleLabel(record: IssueResolutionRecord): string {
    switch (record.recheck.status) {
      case "stale": return "Correction needs recheck";
      case "running": return "Rechecking correction";
      case "resolved": return "Resolved after recheck";
      case "reflagged": return "Issue remains after recheck";
      case "needs_review": return "Recheck needs human review";
      case "failed": return "Recheck failed";
      case "cancelled": return "Recheck cancelled";
      default: return record.status === "resolved" ? "Resolved" : "Resolution recorded";
    }
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
  {#if mutationError}<div class="load-error">{mutationError}</div>{/if}
  {#if preparationMessage}<div class="preparing-notice"><span class="spin" /> {preparationMessage}</div>{/if}
  {#if loading && !preparationMessage && checks.length === 0}
    <div class="loading-placeholder" role="status" aria-label="Loading translation helps">
      <span /><span /><span />
    </div>
  {/if}
  {#if loadError}
    <div class="load-error">Could not load translation helps: {loadError}</div>
    <button class="small-btn" on:click={refresh}>Retry</button>
  {:else if !loading && !preparationMessage && checks.length === 0}
    <p class="none">No translationNotes or translationWords checks are available for this verse.</p>
  {/if}

  {#each checks as check (identity(check))}
    {@const aiReview = aiReviewFor(check)}
    {@const resolution = resolutionFor(check)}
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

      {#if resolutionKey === identity(check)}
        <div class="resolution-editor">
          <div class="resolution-title">Issue resolution and Paratext handoff</div>
          <label>
            <span>Exact target word or phrase <small>(optional)</small></span>
            <input bind:value={resolutionSelectedText} placeholder="Text from the current verse" />
          </label>
          <label>
            <span>Issue</span>
            <textarea bind:value={resolutionIssueSummary} rows="3" placeholder="Describe the translation issue" />
          </label>
          <label>
            <span>Proposed correction <small>(optional)</small></span>
            <input bind:value={resolutionCorrection} placeholder="Suggested wording or action" />
          </label>
          <label>
            <span>Reviewer note</span>
            <textarea bind:value={resolutionReviewerNote} rows="3" placeholder="Message for the Paratext reviewer" />
          </label>
          <div class="connector-state" class:connected={Boolean(connectorState?.connected && connectorState?.project_id?.trim())}>{connectorMessage}</div>
          <p class="resolution-safety">Nothing is sent silently. This explicit action saves an audit record and a Notes 1.1 copy first; unsupported or offline delivery remains retryable.</p>
          {#if resolutionError}<p class="mutation-error">{resolutionError}</p>{/if}
          <div class="editor-actions">
            <button
              class="save-btn"
              on:click={() => saveAndQueueResolution(check, aiReview)}
              disabled={resolutionBusy || !resolutionIssueSummary.trim() || !resolutionReviewerNote.trim()}
            >{resolutionBusy ? "Saving…" : "Save & hand off"}</button>
            <button class="small-btn" on:click={cancelResolution} disabled={resolutionBusy}>Cancel</button>
          </div>
        </div>
      {:else}
        <div class="resolution-actions">
          <button class="small-btn resolution-btn" on:click={() => startResolution(check, aiReview)}>
            {resolution ? "Update resolution" : "Resolve / Paratext"}
          </button>
          {#if resolution}
            <span class="lifecycle-status {resolution.recheck.status}">
              {resolutionLifecycleLabel(resolution)}
            </span>
            <span class="handoff-status {resolution.paratext.status}">
              {resolution.paratext.status === "sent" ? "Sent to Paratext" : resolution.paratext.status === "queued" ? "Paratext queued" : "Resolution saved"}
            </span>
            {#if resolution.paratext.status === "queued"}
              <button class="small-btn" on:click={() => retryResolution(resolution)} disabled={resolutionBusy}>Retry handoff</button>
            {/if}
            {#if ["stale", "failed", "cancelled", "reflagged", "needs_review"].includes(resolution.recheck.status)}
              <button class="small-btn" on:click={onRerunAIReview} disabled={aiReviewBusy}>Run AI recheck</button>
            {/if}
          {/if}
        </div>
        {#if resolution && resolution.recheck.status !== "not_run"}
          <div class="lifecycle-detail {resolution.recheck.status}" role="status">
            {#if resolution.recheck.rationale}<p>{resolution.recheck.rationale}</p>{/if}
            {#if resolution.recheck.reason && !resolution.recheck.rationale}<p>{resolution.recheck.reason}</p>{/if}
            {#if resolution.recheck.error}<p>{resolution.recheck.error}</p>{/if}
            {#if resolution.recheck.verdict}
              <small>AI verdict: {resolution.recheck.verdict.replaceAll("_", " ")}{resolution.recheck.confidence !== undefined ? ` · ${Math.round(resolution.recheck.confidence * 100)}% confidence` : ""}</small>
            {/if}
          </div>
        {/if}
      {/if}
    </article>
  {/each}
</div>

<style>
  .section { border: 1px solid var(--border); border-radius: 12px; padding: 12px 14px; margin-bottom: 12px; }
  .translation-helps { min-height: 126px; }
  .section-title { font-size: 11px; font-weight: 700; color: var(--text); display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
  .mode-badge { margin-left: auto; text-transform: capitalize; font-size: 9px; padding: 2px 6px; border-radius: 999px; color: var(--accent); background: var(--accent-bg); }
  .loading-label { display: flex; align-items: center; gap: 4px; color: var(--text-3); font-weight: 500; }
  .spin { width: 9px; height: 9px; border-radius: 50%; border: 2px solid var(--accent-bg); border-top-color: var(--accent); animation: spin .8s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .basic-notice, .mutation-notice, .preparing-notice, .load-error, .stale-review-notice { font-size: 10px; line-height: 1.4; border-radius: 6px; padding: 7px 8px; margin-bottom: 8px; }
  .basic-notice { color: var(--warning); background: var(--warning-bg); }
  .mutation-notice { color: var(--success); background: var(--success-bg); overflow-wrap: anywhere; }
  .preparing-notice { display: flex; align-items: center; gap: 6px; color: var(--accent); background: var(--accent-bg); }
  .loading-placeholder { min-height: 66px; display: grid; align-content: center; gap: 7px; }
  .loading-placeholder span { display: block; height: 8px; border-radius: 999px; background: var(--surface-2); animation: loading-pulse 1.2s ease-in-out infinite; }
  .loading-placeholder span:nth-child(1) { width: 72%; }
  .loading-placeholder span:nth-child(2) { width: 94%; animation-delay: .12s; }
  .loading-placeholder span:nth-child(3) { width: 54%; animation-delay: .24s; }
  @keyframes loading-pulse { 0%, 100% { opacity: .45; } 50% { opacity: 1; } }
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
  .resolution-editor { margin-top: 9px; border-top: 1px dashed var(--border); padding-top: 9px; display: grid; gap: 7px; }
  .resolution-title { font-size: 10px; font-weight: 750; color: var(--text); }
  .resolution-editor label { display: grid; gap: 4px; font-size: 10px; font-weight: 650; color: var(--text-2); }
  .resolution-editor label small { color: var(--text-3); font-weight: 400; }
  .resolution-editor input, .resolution-editor textarea { width: 100%; box-sizing: border-box; border: 1px solid var(--border); border-radius: 5px; padding: 6px 7px; font: inherit; font-size: 10px; color: var(--text); background: var(--surface); resize: vertical; }
  .connector-state { font-size: 9px; line-height: 1.4; padding: 6px 7px; border-radius: 5px; color: var(--warning); background: var(--warning-bg); overflow-wrap: anywhere; }
  .connector-state.connected { color: var(--success); background: var(--success-bg); }
  .resolution-safety { margin: 0; font-size: 9px; line-height: 1.4; color: var(--text-3); }
  .resolution-actions { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; margin-top: 8px; padding-top: 8px; border-top: 1px dashed var(--border); }
  .small-btn.resolution-btn { color: var(--accent); border-color: var(--accent); }
  .handoff-status { font-size: 9px; padding: 3px 6px; border-radius: 999px; color: var(--text-2); background: var(--surface-2); }
  .handoff-status.queued { color: var(--warning); background: var(--warning-bg); }
  .handoff-status.sent { color: var(--success); background: var(--success-bg); }
  .lifecycle-status { font-size: 9px; padding: 3px 6px; border-radius: 999px; color: var(--text-2); background: var(--surface-2); }
  .lifecycle-status.resolved { color: var(--success); background: var(--success-bg); }
  .lifecycle-status.stale, .lifecycle-status.running { color: var(--warning); background: var(--warning-bg); }
  .lifecycle-status.reflagged, .lifecycle-status.failed { color: var(--danger); background: var(--danger-bg); }
  .lifecycle-detail { margin-top: 6px; padding: 6px 7px; border-radius: 5px; font-size: 9px; line-height: 1.4; color: var(--text-2); background: var(--surface-2); }
  .lifecycle-detail.resolved { color: var(--success); background: var(--success-bg); }
  .lifecycle-detail.reflagged, .lifecycle-detail.failed { color: var(--danger); background: var(--danger-bg); }
  .lifecycle-detail p { margin: 0 0 3px; }
  .none { font-size: 11px; color: var(--text-3); }
</style>
