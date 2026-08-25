<script lang="ts">
  import { bridge } from "../api/bridgeClient";
  import AlignmentModal from "./AlignmentModal.svelte";
  import TranslationHelpsReview from "./TranslationHelpsReview.svelte";
  import {
    selectedVerse, selectedFindings, findingsByVerse, currentChapter,
    verseTexts, checkStatusByVerse, alignmentStatusByVerse, checkingProgress, verseKey,
    aiCheckReviewsByVerse, nativeChecksByVerse,
  } from "../stores";
  import type { AiExplainResult, FindingStatus } from "../types/finding";

  let greekRoomChecking = false;
  let lastCheckedKey = "";
  let liveCheckSequence = 0;
  let displayedLiveCheck = 0;
  const latestLiveCheckByVerse = new Map<string, number>();
  type DecisionSaveState = "saving" | "saved" | "error";
  let decisionSaveState: Record<string, DecisionSaveState> = {};
  let decisionSaveError: Record<string, string> = {};

  // Re-run Greek Room live whenever the selected verse changes — per the
  // approved design, Greek Room is the one engine that re-checks live on
  // focus; tN/tW/Alignment are already-computed background-pass results.
  $: if ($selectedVerse) {
    const key = verseKey($currentChapter, $selectedVerse);
    if (key !== lastCheckedKey) {
      lastCheckedKey = key;
      runLiveGreekRoomCheck($currentChapter, $selectedVerse);
    }
  }

  async function runLiveGreekRoomCheck(chapter: string, verse: string) {
    const key = verseKey(chapter, verse);
    const requestToken = ++liveCheckSequence;
    latestLiveCheckByVerse.set(key, requestToken);
    displayedLiveCheck = requestToken;
    greekRoomChecking = true;
    try {
      const findings = await bridge.runVerseChecks(chapter, verse, ["greekroom"]);
      if (latestLiveCheckByVerse.get(key) !== requestToken) return;
      findingsByVerse.update((map) => {
        const existing = (map[key] ?? []).filter((f) => f.engine !== "wildebeest");
        return { ...map, [key]: [...existing, ...findings] };
      });
    } catch (e) {
      console.error("Greek Room live check failed", e);
    } finally {
      if (displayedLiveCheck === requestToken) greekRoomChecking = false;
    }
  }

  async function decide(findingId: string, status: FindingStatus) {
    if (!$selectedVerse || decisionSaveState[findingId] === "saving") return;
    const chapter = $currentChapter;
    const verse = $selectedVerse;
    const key = verseKey(chapter, verse);
    decisionSaveState = { ...decisionSaveState, [findingId]: "saving" };
    decisionSaveError = { ...decisionSaveError, [findingId]: "" };
    try {
      await bridge.decideVerse(chapter, verse, findingId, status);
      findingsByVerse.update((map) => {
        const list = (map[key] ?? []).map((f) => (f.id === findingId ? { ...f, status } : f));
        return { ...map, [key]: list };
      });
      decisionSaveState = { ...decisionSaveState, [findingId]: "saved" };
      window.setTimeout(() => {
        if (decisionSaveState[findingId] !== "saved") return;
        const next = { ...decisionSaveState };
        delete next[findingId];
        decisionSaveState = next;
      }, 2500);
    } catch (error) {
      decisionSaveState = { ...decisionSaveState, [findingId]: "error" };
      decisionSaveError = {
        ...decisionSaveError,
        [findingId]: error instanceof Error ? error.message : String(error),
      };
    }
  }

  let editing = false;
  let editText = "";
  let editError: string | null = null;
  let editSaving = false;
  let editChapter = "";
  let editVerse = "";
  let recheckingKey = "";
  let recheckedKey = "";
  let editErrorKey = "";
  let alignmentOpen = false;
  let alignmentKey = "";
  let aiExplainBusy = false;
  let aiExplainError = "";
  let aiExplainResult: AiExplainResult | null = null;
  let aiExplainKey = "";
  let translationHelpsReview: TranslationHelpsReview;

  function nativeCheckStateChanged(): void {
    aiExplainResult = null;
    aiExplainError = "";
    aiExplainKey = "";
  }

  $: if (
    editing && !editSaving && $selectedVerse &&
    verseKey($currentChapter, $selectedVerse) !== verseKey(editChapter, editVerse)
  ) {
    editing = false;
    editError = null;
  }

  $: if (
    aiExplainResult && $selectedVerse &&
    verseKey($currentChapter, $selectedVerse) !== aiExplainKey
  ) {
    aiExplainResult = null;
    aiExplainError = "";
  }

  async function askAiExplain() {
    if (!$selectedVerse || aiExplainBusy) return;
    const chapter = $currentChapter;
    const verse = $selectedVerse;
    aiExplainBusy = true;
    aiExplainError = "";
    aiExplainResult = null;
    try {
      aiExplainResult = await bridge.aiExplainVerse(chapter, verse);
      aiExplainKey = verseKey(chapter, verse);
      aiCheckReviewsByVerse.update((values) => ({
        ...values, [aiExplainKey]: aiExplainResult?.checkReviews ?? [],
      }));
    } catch (e) {
      aiExplainError = e instanceof Error ? e.message : String(e);
    } finally {
      aiExplainBusy = false;
    }
  }

  $: if (
    alignmentOpen && $selectedVerse &&
    verseKey($currentChapter, $selectedVerse) !== alignmentKey
  ) {
    alignmentOpen = false;
  }

  function openAlignment() {
    if (!$selectedVerse || $checkingProgress.running || editSaving || recheckingKey) return;
    alignmentKey = verseKey($currentChapter, $selectedVerse);
    alignmentOpen = true;
  }

  function startEdit() {
    if (!$selectedVerse || $checkingProgress.running || editSaving || recheckingKey) return;
    editChapter = $currentChapter;
    editVerse = $selectedVerse;
    editText = $verseTexts[verseKey(editChapter, editVerse)] ?? "";
    editError = null;
    editErrorKey = "";
    editing = true;
  }

  async function saveEdit() {
    if (!editChapter || !editVerse) return;
    const chapter = editChapter;
    const verse = editVerse;
    const key = verseKey(chapter, verse);
    if (editText.trim() === ($verseTexts[key] ?? "").trim()) {
      // No real change — apply_scripture_edit rejects this as a no-op
      // rather than journaling a spurious edit, so don't call it.
      editing = false;
      return;
    }
    editError = null;
    editSaving = true;
    try {
      await bridge.editVerse(chapter, verse, editText);
      verseTexts.update((t) => ({ ...t, [key]: editText }));
      aiCheckReviewsByVerse.update((values) => {
        const next = { ...values };
        delete next[key];
        return next;
      });
      nativeChecksByVerse.update((values) => {
        const next = { ...values };
        delete next[key];
        return next;
      });
      alignmentStatusByVerse.update((values) => ({ ...values, [key]: "invalid" }));
      if ($selectedVerse && verseKey($currentChapter, $selectedVerse) === key) {
        await translationHelpsReview?.refresh();
      }
      editing = false;
      recheckingKey = key;
      recheckedKey = "";
      checkStatusByVerse.update((map) => ({ ...map, [key]: "pending" }));
      latestLiveCheckByVerse.set(key, ++liveCheckSequence);
      const findings = await bridge.runVerseChecks(chapter, verse, ["local", "greekroom"]);
      findingsByVerse.update((map) => ({ ...map, [key]: findings }));
      checkStatusByVerse.update((map) => ({ ...map, [key]: "succeeded" }));
      recheckingKey = "";
      recheckedKey = key;
      window.setTimeout(() => {
        if (recheckedKey === key) recheckedKey = "";
      }, 3500);
    } catch (e) {
      recheckingKey = "";
      checkStatusByVerse.update((map) => ({ ...map, [key]: "failed" }));
      editError = e instanceof Error ? e.message : String(e);
      editErrorKey = key;
    } finally {
      editSaving = false;
    }
  }

  const severityBadge: Record<string, string> = {
    high: "badge-wrong", medium: "badge-review", low: "badge-review", info: "badge-review",
  };
</script>

<div class="panel">
  {#if $selectedVerse}
    <div class="panel-header">
      <div class="ref">{$currentChapter}:{$selectedVerse} — verse review</div>
      <div class="sub">
        {$selectedFindings.filter((f) => f.status === "open").length} open finding(s)
      </div>
    </div>

    <div class="panel-scroll">
      {#if recheckingKey === verseKey($currentChapter, $selectedVerse)}
        <div class="operation-status checking"><span class="spin" /> Verse saved. Re-checking local and Greek Room QA…</div>
      {:else if recheckedKey === verseKey($currentChapter, $selectedVerse)}
        <div class="operation-status saved">✓ Verse saved and re-check completed.</div>
      {:else if editError && editErrorKey === verseKey($currentChapter, $selectedVerse) && !editing}
        <div class="operation-status failed">The verse was not fully rechecked: {editError}</div>
      {/if}

      {#if editing}
        <div class="section">
          <div class="section-title">Edit verse</div>
          <textarea bind:value={editText} rows="3" />
          {#if editError}<p class="edit-error">{editError}</p>{/if}
          <div class="edit-actions">
            <button class="accept" on:click={saveEdit} disabled={editSaving || editText.trim() === ""}>
              {editSaving ? "Saving…" : "Save & re-check"}
            </button>
            <button class="cancel" on:click={() => (editing = false)} disabled={editSaving}>Cancel</button>
          </div>
        </div>
      {/if}

      <TranslationHelpsReview bind:this={translationHelpsReview} chapter={$currentChapter} verse={$selectedVerse} onStateChanged={nativeCheckStateChanged} />

      <div class="section">
        <div class="section-title">
          Greek Room QA
          {#if greekRoomChecking}
            <span class="live"><span class="spin" /> live check</span>
          {/if}
        </div>
        {#each $selectedFindings.filter((f) => f.engine === "wildebeest") as f}
          <div class="finding">
            <div class="verdict">
              <span class="badge {severityBadge[f.severity]}">{f.severity}</span>
              <span class="check-id">{f.check_type}</span>
              {#if f.status !== "open"}<span class="badge badge-decided">{f.status}</span>{/if}
              {#if decisionSaveState[f.id] === "saving"}
                <span class="save-state">Saving…</span>
              {:else if decisionSaveState[f.id] === "saved"}
                <span class="save-state saved">✓ Saved</span>
              {:else if decisionSaveState[f.id] === "error"}
                <span class="save-state failed" title={decisionSaveError[f.id]}>Save failed</span>
              {/if}
            </div>
            <p class="explain">{f.explanation}</p>
            {#if f.evidence.length > 0}
              <ul class="evidence">
                {#each f.evidence as e}<li>{e.label}: {e.value}</li>{/each}
              </ul>
            {/if}
            <div class="decision-row">
              <button class="accept" disabled={decisionSaveState[f.id] === "saving"} on:click={() => decide(f.id, "accepted")}>✓ Accept</button>
              <button class="reject" disabled={decisionSaveState[f.id] === "saving"} on:click={() => decide(f.id, "rejected")}>✗ Reject</button>
              <button class="ignore" disabled={decisionSaveState[f.id] === "saving"} on:click={() => decide(f.id, "ignored")}>⊘ Ignore</button>
            </div>
          </div>
        {:else}
          {#if !greekRoomChecking}<p class="none">No Greek Room findings.</p>{/if}
        {/each}
      </div>

      <div class="section">
        <div class="section-title">Already computed in background pass</div>
        {#each $selectedFindings.filter((f) => f.engine !== "wildebeest") as f}
          <div class="finding">
            <div class="verdict">
              <span class="badge {severityBadge[f.severity]}">{f.severity}</span>
              <span class="check-id">{f.category}</span>
              {#if f.status !== "open"}<span class="badge badge-decided">{f.status}</span>{/if}
              {#if decisionSaveState[f.id] === "saving"}
                <span class="save-state">Saving…</span>
              {:else if decisionSaveState[f.id] === "saved"}
                <span class="save-state saved">✓ Saved</span>
              {:else if decisionSaveState[f.id] === "error"}
                <span class="save-state failed" title={decisionSaveError[f.id]}>Save failed</span>
              {/if}
            </div>
            <p class="explain">{f.explanation}</p>
            <div class="decision-row">
              <button class="accept" disabled={decisionSaveState[f.id] === "saving"} on:click={() => decide(f.id, "accepted")}>✓ Accept</button>
              <button class="reject" disabled={decisionSaveState[f.id] === "saving"} on:click={() => decide(f.id, "rejected")}>✗ Reject</button>
              <button class="ignore" disabled={decisionSaveState[f.id] === "saving"} on:click={() => decide(f.id, "ignored")}>⊘ Ignore</button>
            </div>
          </div>
        {:else}
          <p class="none">No local QA findings.</p>
        {/each}
      </div>

      {#if aiExplainError}
        <div class="section ai-explain-section">
          <div class="section-title">AI explanation</div>
          <p class="ai-error">{aiExplainError}</p>
        </div>
      {:else if aiExplainResult}
        <div class="section ai-explain-section">
          <div class="section-title">
            AI explanation
            <span class="ai-cost">~${aiExplainResult.usage.estimatedCostUSD.toFixed(4)}</span>
          </div>
          <p class="ai-summary">{aiExplainResult.summary}</p>
          {#each aiExplainResult.checkReviews as review}
            <div class="finding ai-check-review">
              <div class="verdict">
                <span class="badge {severityBadge[review.severity] ?? 'badge-review'}">{review.verdict}</span>
                <span class="check-id">{review.tool}{review.group_id ? ` · ${review.group_id}` : ""}</span>
              </div>
              <p class="explain">{review.rationale}</p>
              {#if review.suggested_correction}<p class="ai-suggestion">Suggested: {review.suggested_correction}</p>{/if}
            </div>
          {/each}
          {#each aiExplainResult.qaIssues as issue}
            <div class="finding ai-qa-issue">
              <div class="verdict">
                <span class="badge {severityBadge[issue.severity] ?? 'badge-review'}">{issue.severity}</span>
                <span class="check-id">{issue.title}</span>
              </div>
              <p class="explain">{issue.detail}</p>
            </div>
          {/each}
          {#if aiExplainResult.checkReviews.length === 0 && aiExplainResult.qaIssues.length === 0}
            <p class="none">AI found nothing to flag for this verse.</p>
          {/if}
        </div>
      {/if}

    </div>

    <div class="footer-actions">
      <button
        class="align-btn"
        on:click={openAlignment}
        disabled={$checkingProgress.running || editing || editSaving || Boolean(recheckingKey)}
        title={$checkingProgress.running ? "Wait for background checking to finish before aligning" : "Review word alignment"}
      >⇄ Align words</button>
      <button
        class="edit-btn"
        on:click={startEdit}
        disabled={$checkingProgress.running || editing || editSaving || Boolean(recheckingKey)}
        title={$checkingProgress.running ? "Wait for background checking to finish before editing" : "Edit this verse"}
      >✎ Edit verse</button>
      <button
        class="ai-explain-btn"
        on:click={askAiExplain}
        disabled={$checkingProgress.running || editing || editSaving || Boolean(recheckingKey) || aiExplainBusy}
        title="Ask AI to prepare evidence-backed check reviews for this verse"
      >{aiExplainBusy ? "Asking AI…" : "🤖 Explain with AI"}</button>
    </div>
  {:else}
    <div class="empty-panel">Select a verse to review its findings.</div>
  {/if}
</div>

{#if alignmentOpen && $selectedVerse}
  <AlignmentModal chapter={$currentChapter} verse={$selectedVerse} onClose={() => (alignmentOpen = false)} />
{/if}

<style>
  .panel { width: 400px; flex-shrink: 0; background: var(--surface); display: flex; flex-direction: column; overflow: hidden; border-left: 1px solid var(--border); }
  .panel-header { padding: 14px 16px; border-bottom: 1px solid var(--border); }
  .ref { font-size: 13px; font-weight: 700; color: var(--text); }
  .sub { font-size: 11px; color: var(--text-2); margin-top: 2px; }
  .panel-scroll { flex: 1; overflow-y: auto; padding: 14px 16px; }
  .operation-status { display: flex; align-items: center; gap: 7px; border-radius: 8px; padding: 8px 10px; margin-bottom: 12px; font-size: 11px; line-height: 1.4; }
  .operation-status.checking { color: var(--accent); background: var(--accent-bg); }
  .operation-status.saved { color: var(--success); background: var(--success-bg); }
  .operation-status.failed { color: var(--danger); background: var(--danger-bg); }
  .section { border: 1px solid var(--border); border-radius: 12px; padding: 12px 14px; margin-bottom: 12px; }
  .section-title { font-size: 11px; font-weight: 700; color: var(--text); display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
  .live { display: flex; align-items: center; gap: 5px; font-size: 10px; font-weight: 700; color: var(--gr); }
  .spin { width: 10px; height: 10px; border-radius: 50%; border: 2px solid var(--gr-bg); border-top-color: var(--gr); animation: spin 0.8s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .finding { border-top: 1px dashed var(--border); padding-top: 10px; margin-top: 10px; }
  .finding:first-child { border-top: none; padding-top: 0; margin-top: 0; }
  .verdict { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
  .badge { font-size: 10px; font-weight: 700; padding: 3px 8px; border-radius: 5px; }
  .badge-wrong { background: var(--danger-bg); color: var(--danger); }
  .badge-review { background: var(--warning-bg); color: var(--warning); }
  .badge-decided { background: var(--success-bg); color: var(--success); text-transform: capitalize; }
  .check-id { font-size: 11px; color: var(--text-3); }
  .save-state { margin-left: auto; font-size: 10px; color: var(--text-3); white-space: nowrap; }
  .save-state.saved { color: var(--success); }
  .save-state.failed { color: var(--danger); }
  .explain { font-size: 12px; color: var(--text-2); line-height: 1.6; margin: 0 0 8px; }
  .evidence { font-size: 11px; color: var(--text-2); padding-left: 16px; margin: 0 0 8px; }
  .decision-row { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 6px; }
  .decision-row button { padding: 7px; font-size: 11px; font-weight: 700; border-radius: 6px; border: none; cursor: pointer; }
  .accept { background: var(--success); color: #fff; }
  .reject { background: var(--danger); color: #fff; }
  .ignore { background: #F5EBFC; color: #9333EA; }
  .none { font-size: 11px; color: var(--text-3); }
  textarea { width: 100%; font-size: 14px; padding: 8px; border: 1px solid var(--accent); border-radius: 6px; font-family: inherit; margin-bottom: 8px; }
  .edit-error { color: var(--danger); font-size: 11px; margin: -4px 0 8px; line-height: 1.4; }
  .edit-actions { display: flex; gap: 6px; }
  .edit-actions button { flex: 1; padding: 7px; font-size: 11px; font-weight: 700; border-radius: 6px; cursor: pointer; }
  .edit-actions .accept { border: none; }
  .cancel { background: var(--surface-2); color: var(--text-2); border: 1px solid var(--border-strong); }
  .decision-row button:disabled, .edit-actions button:disabled { opacity: .55; cursor: not-allowed; }
  .footer-actions { padding: 12px 16px; border-top: 1px solid var(--border); display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px; }
  .edit-btn { width: 100%; padding: 8px; font-size: 12px; font-weight: 700; border-radius: 7px; border: none; background: var(--accent-bg); color: var(--accent); cursor: pointer; }
  .align-btn, .ai-explain-btn { width: 100%; padding: 8px; font-size: 12px; font-weight: 700; border-radius: 7px; border: 1px solid var(--border-strong); background: var(--surface); color: var(--text); cursor: pointer; }
  .edit-btn:disabled, .align-btn:disabled, .ai-explain-btn:disabled { opacity: .55; cursor: not-allowed; }
  .empty-panel { padding: 24px 16px; font-size: 12px; color: var(--text-3); }
  .ai-explain-section { border-color: var(--accent); }
  .ai-cost { margin-left: auto; font-size: 10px; font-weight: 400; color: var(--text-3); }
  .ai-summary { font-size: 12px; color: var(--text); line-height: 1.5; margin: 0 0 10px; }
  .ai-error { font-size: 12px; color: var(--danger); line-height: 1.5; margin: 0; }
  .ai-suggestion { font-size: 11px; color: var(--accent); margin: -4px 0 8px; }
</style>
