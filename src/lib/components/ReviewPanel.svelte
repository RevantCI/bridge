<script lang="ts">
  import { onDestroy, onMount } from "svelte";
  import { bridge } from "../api/bridgeClient";
  import AlignmentModal from "./AlignmentModal.svelte";
  import TranslationHelpsReview from "./TranslationHelpsReview.svelte";
  import { aiJobAppliesToReference, isAIReviewJobActive } from "../utils/aiJobScope";
  import { findingNumbers } from "../utils/highlight";
  import {
    selectedVerse, selectedFindings, findingsByVerse, currentChapter,
    checkStatusByVerse, checkingProgress, verseKey,
    aiCheckReviewsByVerse, nativeChecksByVerse, project, reviewerMode, reviewerModeLabel,
  } from "../stores";
  import {
    editingChapter, editingVerse, editText, editSaving, editError, editErrorKey,
    recheckingKey, recheckedKey, startVerseEdit, cancelVerseEdit, setVerseEditSavedHook,
    setPendingAcceptFinding,
  } from "../verseEditor";
  import type { AiExplainResult, AIReviewJobSnapshot, FindingStatus } from "../types/finding";

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

  let alignmentOpen = false;
  let alignmentKey = "";
  let aiExplainError = "";
  let aiExplainErrorJobId = "";
  let aiExplainErrorReference = "";
  let aiExplainResult: AiExplainResult | null = null;
  let aiExplainKey = "";
  let aiJob: AIReviewJobSnapshot | null = null;
  let visibleAIJob: AIReviewJobSnapshot | null = null;
  let aiJobBusy = false;
  let currentReviewReference = "";
  let visibleAIExplainError = "";
  let aiPollTimer: ReturnType<typeof setTimeout> | undefined;
  let aiPollSequence = 0;
  let processedAIResults = new Set<string>();
  let observedProjectPath = "";
  let aiFailedResults: Array<{ chapter: string; verse: string; error: string | null }> = [];
  let translationHelpsReview: TranslationHelpsReview;

  $: currentReviewReference = `${$project?.path ?? ""}::${$selectedVerse ? verseKey($currentChapter, $selectedVerse) : ""}`;
  $: aiJobBusy = isAIReviewJobActive(aiJob);
  $: visibleAIJob = aiJob && $selectedVerse && aiJobAppliesToReference(
    aiJob, $project?.path ?? "", $currentChapter, $selectedVerse,
  ) ? aiJob : null;
  $: visibleAIExplainError = aiExplainError && (
    aiExplainErrorJobId
      ? visibleAIJob?.jobId === aiExplainErrorJobId
      : aiExplainErrorReference === currentReviewReference
  ) ? aiExplainError : "";
  $: aiFailedResults = visibleAIJob
    ? Object.values(visibleAIJob.results)
        .filter((result) => result.status === "failed")
        .map((result) => ({ chapter: result.chapter, verse: result.verse, error: result.error }))
    : [];

  function nativeCheckStateChanged(): void {
    aiExplainResult = null;
    aiExplainError = "";
    aiExplainErrorJobId = "";
    aiExplainErrorReference = "";
    aiExplainKey = "";
  }

  $: if (
    $editingChapter && !$editSaving && $selectedVerse &&
    verseKey($currentChapter, $selectedVerse) !== verseKey($editingChapter, $editingVerse)
  ) {
    cancelVerseEdit();
    editError.set("");
  }

  $: if (
    aiExplainResult && $selectedVerse &&
    verseKey($currentChapter, $selectedVerse) !== aiExplainKey
  ) {
    aiExplainResult = null;
    aiExplainError = "";
  }

  async function hydrateCompletedAIReview(
    chapter: string, verse: string, expectedProjectPath: string,
  ): Promise<void> {
    try {
      const result = await bridge.listChecksForVerse(chapter, verse);
      if (result.state !== "ready" || ($project?.path ?? "") !== expectedProjectPath) return;
      const key = verseKey(chapter, verse);
      aiCheckReviewsByVerse.update((values) => ({ ...values, [key]: result.aiReviews ?? [] }));
      nativeChecksByVerse.update((values) => ({ ...values, [key]: result.checks ?? [] }));
    } catch (error) {
      console.error(`Could not hydrate completed AI review ${chapter}:${verse}`, error);
    }
  }

  function syncAIJobResult(snapshot: AIReviewJobSnapshot): void {
    for (const [key, resultStatus] of Object.entries(snapshot.results)) {
      if (resultStatus.status !== "succeeded") continue;
      const resultIdentity = `${snapshot.jobId}:${key}`;
      if (!processedAIResults.has(resultIdentity)) {
        processedAIResults = new Set([...processedAIResults, resultIdentity]);
        void hydrateCompletedAIReview(
          resultStatus.chapter, resultStatus.verse, snapshot.projectPath,
        );
        if ($selectedVerse && key === verseKey($currentChapter, $selectedVerse)) {
          void translationHelpsReview?.refresh();
        }
      }
    }
    const latest = snapshot.latestResult;
    if (latest?.result.status === "succeeded") {
      const { key, result } = latest;
      aiCheckReviewsByVerse.update((values) => ({ ...values, [key]: result.checkReviews ?? [] }));
      if ($selectedVerse && key === verseKey($currentChapter, $selectedVerse)) {
        aiExplainKey = key;
        aiExplainError = "";
        aiExplainErrorJobId = "";
        aiExplainErrorReference = "";
        aiExplainResult = {
          summary: result.summary,
          checkReviews: result.checkReviews,
          qaIssues: result.qaIssues,
          alignmentProposal: result.alignmentProposal,
          alignmentWasAIProposed: result.alignmentWasAIProposed,
          usage: result.usage,
        };
      }
    }
  }

  async function pollAIJob(jobId: string, sequence: number): Promise<void> {
    try {
      const snapshot = await bridge.aiReviewStatus(jobId);
      if (sequence !== aiPollSequence) return;
      aiJob = snapshot;
      syncAIJobResult(snapshot);
      if (["queued", "running", "cancelling"].includes(snapshot.state)) {
        aiPollTimer = setTimeout(() => void pollAIJob(jobId, sequence), 650);
      } else {
        if ($selectedVerse && aiJobAppliesToReference(
          snapshot, $project?.path ?? "", $currentChapter, $selectedVerse,
        )) {
          void translationHelpsReview?.refresh();
        }
        if (snapshot.state === "failed") {
          aiExplainError = snapshot.error || "AI review failed.";
          aiExplainErrorJobId = snapshot.jobId;
          aiExplainErrorReference = "";
        }
      }
    } catch (error) {
      if (sequence === aiPollSequence) {
        aiExplainError = error instanceof Error ? error.message : String(error);
        aiExplainErrorJobId = jobId;
        aiExplainErrorReference = "";
      }
    }
  }

  async function startAIReview(
    scope: "verse" | "chapter" | "book",
    chapter: string = $currentChapter,
    verse: string = $selectedVerse ?? "",
  ) {
    if (!verse || aiJobBusy) return;
    const requestedReference = `${$project?.path ?? ""}::${verseKey(chapter, verse)}`;
    if (scope !== "verse" && !window.confirm(
      `Run AI review for this ${scope}? Each verse may use one or two model requests and incur API charges.`,
    )) return;
    aiExplainError = "";
    aiExplainErrorJobId = "";
    aiExplainErrorReference = "";
    aiExplainResult = null;
    try {
      const snapshot = await bridge.startAIReview(scope, chapter, verse, $reviewerMode);
      aiJob = snapshot;
      processedAIResults = new Set();
      const sequence = ++aiPollSequence;
      void pollAIJob(snapshot.jobId, sequence);
    } catch (e) {
      aiExplainError = e instanceof Error ? e.message : String(e);
      aiExplainErrorJobId = "";
      aiExplainErrorReference = requestedReference;
    }
  }

  async function cancelAIReview(): Promise<void> {
    if (!aiJob || !["queued", "running", "cancelling"].includes(aiJob.state)) return;
    try {
      aiJob = await bridge.cancelAIReview(aiJob.jobId);
    } catch (error) {
      aiExplainError = error instanceof Error ? error.message : String(error);
      aiExplainErrorJobId = aiJob?.jobId ?? "";
      aiExplainErrorReference = "";
    }
  }

  async function retryAIReview(): Promise<void> {
    if (!aiJob || !["failed", "cancelled"].includes(aiJob.state)) return;
    aiExplainError = "";
    aiExplainErrorJobId = "";
    aiExplainErrorReference = "";
    try {
      const snapshot = await bridge.retryAIReview(aiJob.jobId);
      aiJob = snapshot;
      processedAIResults = new Set();
      const sequence = ++aiPollSequence;
      void pollAIJob(snapshot.jobId, sequence);
    } catch (error) {
      aiExplainError = error instanceof Error ? error.message : String(error);
      aiExplainErrorJobId = aiJob?.jobId ?? "";
      aiExplainErrorReference = "";
    }
  }

  $: if (($project?.path ?? "") !== observedProjectPath) {
    if (observedProjectPath && aiJob && ["queued", "running", "cancelling"].includes(aiJob.state)) {
      void cancelAIReview();
    }
    observedProjectPath = $project?.path ?? "";
    aiJob = null;
    aiExplainResult = null;
    aiExplainError = "";
    aiExplainErrorJobId = "";
    aiExplainErrorReference = "";
    aiPollSequence += 1;
    if (aiPollTimer) clearTimeout(aiPollTimer);
  }

  onDestroy(() => {
    aiPollSequence += 1;
    if (aiPollTimer) clearTimeout(aiPollTimer);
  });

  $: if (
    alignmentOpen && $selectedVerse &&
    verseKey($currentChapter, $selectedVerse) !== alignmentKey
  ) {
    alignmentOpen = false;
  }

  function openAlignment() {
    if (!$selectedVerse || $checkingProgress.running || $editSaving || $recheckingKey) return;
    alignmentKey = verseKey($currentChapter, $selectedVerse);
    alignmentOpen = true;
  }

  function startEdit() {
    startVerseEdit($currentChapter, $selectedVerse ?? "");
  }

  // "Accept and edit" on a specific Greek Room finding: same edit session
  // as startEdit, but remembers which finding this was so a successful
  // save can record it as "accepted" (see setVerseEditSavedHook below)
  // rather than leaving it open for the next recheck to silently re-decide.
  function acceptAndEdit(findingId: string) {
    if (startVerseEdit($currentChapter, $selectedVerse ?? "")) {
      setPendingAcceptFinding(findingId);
    }
  }

  onMount(() => {
    setVerseEditSavedHook(({ chapter, verse, issueResolutionsNeedingRecheck, acceptFindingId }) => {
      const key = verseKey(chapter, verse);
      // Invalidate any live Greek-Room-only check still in flight from when
      // this verse was first selected, so it can't resolve after this point
      // and overwrite saveVerseEdit's own fresh (post-edit) findings with a
      // stale pre-edit wildebeest result.
      latestLiveCheckByVerse.set(key, ++liveCheckSequence);
      if ($selectedVerse && verseKey($currentChapter, $selectedVerse) === key) {
        void translationHelpsReview?.refresh();
        // Record the human decision unconditionally — the same "a decision
        // persists even if the finding somehow still recurs" behavior
        // Ignore already relies on. Usually the edit actually fixed the
        // underlying text, so this specific finding id won't even reappear
        // in the fresh recheck results at all; this just makes sure it's
        // filed as accepted for the case where it does.
        if (acceptFindingId) void decide(acceptFindingId, "accepted");
      }
      if (issueResolutionsNeedingRecheck > 0) {
        // A saved issue can only close against the edited text. Start the
        // evidence-grounded verse review automatically; failures remain visibly
        // stale/retryable and never restore the previous resolved state.
        void startAIReview("verse", chapter, verse);
      }
    });
  });

  const severityBadge: Record<string, string> = {
    high: "badge-wrong", medium: "badge-review", low: "badge-review", info: "badge-review",
  };

  type ReviewTab = "greekroom" | "tntw" | "ai";
  let activeTab: ReviewTab = "greekroom";
  // The three real Greek Room engines (see each adapter's own engine_name:
  // wildebeest_adapter.py, usfm_adapter.py, names_adapter.py) — everything
  // else on a finding's `engine` field (tN/tW/alignment's own QAIssue.source,
  // or "local" as its fallback) is native tC/Bridge QA, not Greek Room.
  const GREEK_ROOM_ENGINES = new Set(["wildebeest", "usfm", "names"]);
  function isGreekRoom(engine: string): boolean {
    return GREEK_ROOM_ENGINES.has(engine);
  }
  $: greekRoomOpenCount = $selectedFindings.filter((f) => isGreekRoom(f.engine) && f.status === "open").length;
  $: tntwOpenCount = $selectedFindings.filter((f) => !isGreekRoom(f.engine) && f.status === "open").length;
  // Same cross-reference-style numbering shown inline in the verse text
  // (VerseList.svelte) — both read $selectedFindings for the same verse
  // and both exclude ignored/accepted findings before numbering (VerseList
  // excludes them from buildSegments' highlighting too), so the numbers
  // line up without any shared state beyond that.
  $: findingNumberMap = findingNumbers(
    $selectedFindings.filter((f) => f.status !== "ignored" && f.status !== "accepted"),
  );
  function byFindingNumber(a: { id: string }, b: { id: string }): number {
    const na = findingNumberMap.get(a.id) ?? Infinity;
    const nb = findingNumberMap.get(b.id) ?? Infinity;
    return na - nb;
  }
</script>

<div class="panel">
  {#if $selectedVerse}
    <div class="panel-header">
      <div class="ref">{$currentChapter}:{$selectedVerse} — verse review</div>
      <div class="sub">
        {$selectedFindings.filter((f) => f.status === "open").length} open finding(s)
      </div>
    </div>

    <div class="panel-pinned">
      {#if $recheckingKey === verseKey($currentChapter, $selectedVerse)}
        <div class="operation-status checking"><span class="spin" /> Verse saved. Re-checking local and Greek Room QA…</div>
      {:else if $recheckedKey === verseKey($currentChapter, $selectedVerse)}
        <div class="operation-status saved">✓ Verse saved and re-check completed.</div>
      {:else if $editError && $editErrorKey === verseKey($currentChapter, $selectedVerse) && !$editingChapter}
        <div class="operation-status failed">The verse was not fully rechecked: {$editError}</div>
      {/if}

      {#if $editingChapter === $currentChapter && $editingVerse === $selectedVerse}
        <div class="operation-status checking">✎ Editing this verse in the left panel — save or cancel there.</div>
      {/if}

      <div class="section ai-review-controls">
        <div class="section-title">
          Automatic AI review
          <span class="mode-pill">{reviewerModeLabel($reviewerMode)}</span>
        </div>
        <p class="ai-review-help">
          {$reviewerMode === "basic"
            ? "Safe, evidence-grounded selections are applied automatically; uncertain checks remain for review."
            : "AI prepares evidence and exact-word proposals; you decide what to apply or edit."}
        </p>
        <div class="ai-scope-actions">
          <button on:click={() => startAIReview("verse")} disabled={$checkingProgress.running || aiJobBusy}>This verse</button>
          <button on:click={() => startAIReview("chapter")} disabled={$checkingProgress.running || aiJobBusy}>Chapter</button>
          <button on:click={() => startAIReview("book")} disabled={$checkingProgress.running || aiJobBusy}>Whole book</button>
        </div>
        {#if visibleAIJob}
          <div class="ai-job-status" class:failed={visibleAIJob.state === "failed"}>
            <div><b>{visibleAIJob.state === "succeeded" ? "Complete" : visibleAIJob.currentStage}</b><span>{visibleAIJob.percent}%</span></div>
            <progress max="100" value={visibleAIJob.percent} />
            <small>{visibleAIJob.completedVerses}/{visibleAIJob.totalVerses} verses · {visibleAIJob.mode} mode{visibleAIJob.failedVerses ? ` · ${visibleAIJob.failedVerses} failed` : ""}</small>
            {#if visibleAIJob.skippedCurrentVerses > 0}
              <small>{visibleAIJob.skippedCurrentVerses} already-current verse(s) preserved and skipped.</small>
            {/if}
            {#if visibleAIJob.resumeOf}<small>Resumed from the previous unfinished job.</small>{/if}
            {#if aiFailedResults.length > 0}
              <div class="ai-failure-list">
                {#each aiFailedResults.slice(0, 3) as failure}
                  <div><b>{failure.chapter}:{failure.verse}</b> — {failure.error || "Unknown AI review error"}</div>
                {/each}
                {#if aiFailedResults.length > 3}<div>+ {aiFailedResults.length - 3} more failed verse(s)</div>{/if}
              </div>
            {/if}
            <div class="ai-job-actions">
              {#if ["queued", "running", "cancelling"].includes(visibleAIJob.state)}
                <button on:click={cancelAIReview} disabled={visibleAIJob.state === "cancelling"}>{visibleAIJob.state === "cancelling" ? "Cancelling…" : "Cancel"}</button>
              {:else if ["failed", "cancelled"].includes(visibleAIJob.state)}
                <button on:click={retryAIReview}>Retry</button>
              {/if}
            </div>
          </div>
        {:else if aiJobBusy}
          <div class="ai-job-background" role="status">
            An AI review is continuing in the background for another reference. Return to its starting reference to view progress or cancel it.
          </div>
        {/if}
        {#if visibleAIExplainError}<p class="ai-control-error">{visibleAIExplainError}</p>{/if}
      </div>
    </div>

    <div class="panel-scroll">
      <div class="tabs" role="tablist" aria-label="Verse report">
        <button
          type="button" role="tab" aria-selected={activeTab === "greekroom"}
          class:active={activeTab === "greekroom"} on:click={() => (activeTab = "greekroom")}
        >
          Greek Room QA
          {#if greekRoomChecking}<span class="tab-live" />{/if}
          {#if greekRoomOpenCount > 0}<span class="tab-count">{greekRoomOpenCount}</span>{/if}
        </button>
        <button
          type="button" role="tab" aria-selected={activeTab === "tntw"}
          class:active={activeTab === "tntw"} on:click={() => (activeTab = "tntw")}
        >
          tN/tW/Alignment
          {#if tntwOpenCount > 0}<span class="tab-count">{tntwOpenCount}</span>{/if}
        </button>
        <button
          type="button" role="tab" aria-selected={activeTab === "ai"}
          class:active={activeTab === "ai"} on:click={() => (activeTab = "ai")}
        >AI explanation</button>
      </div>

      <div class="tab-content">
      <div class="tab-panel" role="tabpanel" hidden={activeTab !== "tntw"}>
        <TranslationHelpsReview
          bind:this={translationHelpsReview}
          chapter={$currentChapter}
          verse={$selectedVerse}
          onStateChanged={nativeCheckStateChanged}
          onRerunAIReview={() => void startAIReview("verse")}
          aiReviewBusy={$checkingProgress.running || aiJobBusy}
        />

        <div class="section">
          <div class="section-title">Already computed in background pass</div>
          {#each $selectedFindings.filter((f) => !isGreekRoom(f.engine)) as f}
            <div class="finding">
              <div class="verdict">
                {#if findingNumberMap.has(f.id)}<span class="finding-num-badge" title="Marked in the verse text">{findingNumberMap.get(f.id)}</span>{/if}
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
            </div>
          {:else}
            <p class="none">No local QA findings.</p>
          {/each}
        </div>
      </div>

      {#if activeTab === "greekroom"}
        {@const grFindings = $selectedFindings.filter((f) => isGreekRoom(f.engine))}
        {@const grOpenFindings = grFindings.filter((f) => f.status !== "ignored" && f.status !== "accepted").sort(byFindingNumber)}
        {@const grIgnoredFindings = grFindings.filter((f) => f.status === "ignored")}
        {@const grAcceptedFindings = grFindings.filter((f) => f.status === "accepted")}
        <div class="tab-panel" role="tabpanel">
          <div class="section">
            <div class="section-title">
              Greek Room QA
              {#if greekRoomChecking}
                <span class="live"><span class="spin" /> live check</span>
              {/if}
            </div>
            {#each grOpenFindings as f}
              <div class="finding">
                <div class="verdict">
                  {#if findingNumberMap.has(f.id)}<span class="finding-num-badge" title="Marked in the verse text">{findingNumberMap.get(f.id)}</span>{/if}
                  <span class="badge {severityBadge[f.severity]}">{f.severity}</span>
                  <span class="engine-badge">{f.engine}</span>
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
                <div class="decision-row two-up">
                  <button
                    class="edit-inline"
                    on:click={() => acceptAndEdit(f.id)}
                    disabled={$checkingProgress.running || Boolean($editingChapter) || $editSaving || Boolean($recheckingKey)}
                    title={$checkingProgress.running ? "Wait for background checking to finish before editing" : "Edit this verse and mark this finding accepted"}
                  >✎ Accept and edit</button>
                  <button class="ignore" disabled={decisionSaveState[f.id] === "saving"} on:click={() => decide(f.id, "ignored")}>⊘ Ignore</button>
                </div>
              </div>
            {/each}
            {#if grFindings.length === 0 && !greekRoomChecking}<p class="none">No Greek Room findings.</p>{/if}
          </div>

          {#if grAcceptedFindings.length > 0}
            <details class="section accepted-section">
              <summary class="section-title ignored-summary">Accepted ({grAcceptedFindings.length})</summary>
              {#each grAcceptedFindings as f}
                <div class="finding">
                  <div class="verdict">
                    <span class="badge {severityBadge[f.severity]}">{f.severity}</span>
                    <span class="engine-badge">{f.engine}</span>
                    <span class="check-id">{f.check_type}</span>
                    <span class="badge badge-decided">{f.status}</span>
                    {#if decisionSaveState[f.id] === "saving"}
                      <span class="save-state">Saving…</span>
                    {:else if decisionSaveState[f.id] === "saved"}
                      <span class="save-state saved">✓ Saved</span>
                    {:else if decisionSaveState[f.id] === "error"}
                      <span class="save-state failed" title={decisionSaveError[f.id]}>Save failed</span>
                    {/if}
                  </div>
                  <p class="explain">{f.explanation}</p>
                  <div class="decision-row one-up">
                    <button class="undo-accept" disabled={decisionSaveState[f.id] === "saving"} on:click={() => decide(f.id, "open")}>↺ Undo accept</button>
                  </div>
                </div>
              {/each}
            </details>
          {/if}

          {#if grIgnoredFindings.length > 0}
            <details class="section ignored-section">
              <summary class="section-title ignored-summary">Ignored ({grIgnoredFindings.length})</summary>
              {#each grIgnoredFindings as f}
                <div class="finding">
                  <div class="verdict">
                    {#if findingNumberMap.has(f.id)}<span class="finding-num-badge" title="Marked in the verse text">{findingNumberMap.get(f.id)}</span>{/if}
                    <span class="badge {severityBadge[f.severity]}">{f.severity}</span>
                    <span class="engine-badge">{f.engine}</span>
                    <span class="check-id">{f.check_type}</span>
                    <span class="badge badge-decided">{f.status}</span>
                    {#if decisionSaveState[f.id] === "saving"}
                      <span class="save-state">Saving…</span>
                    {:else if decisionSaveState[f.id] === "saved"}
                      <span class="save-state saved">✓ Saved</span>
                    {:else if decisionSaveState[f.id] === "error"}
                      <span class="save-state failed" title={decisionSaveError[f.id]}>Save failed</span>
                    {/if}
                  </div>
                  <p class="explain">{f.explanation}</p>
                  <div class="decision-row two-up">
                    <button
                      class="edit-inline"
                      on:click={startEdit}
                      disabled={$checkingProgress.running || Boolean($editingChapter) || $editSaving || Boolean($recheckingKey)}
                      title={$checkingProgress.running ? "Wait for background checking to finish before editing" : "Edit this verse"}
                    >✎ Edit verse</button>
                    <button class="undo-ignore" disabled={decisionSaveState[f.id] === "saving"} on:click={() => decide(f.id, "open")}>↺ Undo ignore</button>
                  </div>
                </div>
              {/each}
            </details>
          {/if}
        </div>
      {:else if activeTab === "ai"}
        <div class="tab-panel" role="tabpanel">
          {#if visibleAIExplainError}
            <div class="section ai-explain-section">
              <div class="section-title">AI explanation</div>
              <p class="ai-error">{visibleAIExplainError}</p>
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
          {:else}
            <p class="none">No AI explanation yet for this verse — run "AI review" below.</p>
          {/if}
        </div>
      {/if}
      </div>

    </div>

    <div class="footer-actions">
      <button
        class="align-btn"
        on:click={openAlignment}
        disabled={$checkingProgress.running || Boolean($editingChapter) || $editSaving || Boolean($recheckingKey)}
        title={$checkingProgress.running ? "Wait for background checking to finish before aligning" : "Review word alignment"}
      >⇄ Align words</button>
      <button
        class="edit-btn"
        on:click={startEdit}
        disabled={$checkingProgress.running || Boolean($editingChapter) || $editSaving || Boolean($recheckingKey)}
        title={$checkingProgress.running ? "Wait for background checking to finish before editing" : "Edit this verse"}
      >✎ Edit verse</button>
      <button
        class="ai-explain-btn"
        on:click={() => startAIReview("verse")}
        disabled={$checkingProgress.running || Boolean($editingChapter) || $editSaving || Boolean($recheckingKey) || aiJobBusy}
        title="Run an evidence-grounded AI review for this verse in the background"
      >🤖 AI review</button>
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
  .panel-pinned { flex-shrink: 0; padding: 14px 16px; border-bottom: 1px solid var(--border); overflow-y: auto; max-height: 60vh; }
  .ref { font-size: 13px; font-weight: 700; color: var(--text); }
  .sub { font-size: 11px; color: var(--text-2); margin-top: 2px; }
  .panel-scroll { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
  .operation-status { display: flex; align-items: center; gap: 7px; border-radius: 8px; padding: 8px 10px; margin-bottom: 12px; font-size: 11px; line-height: 1.4; }
  .operation-status.checking { color: var(--accent); background: var(--accent-bg); }
  .operation-status.saved { color: var(--success); background: var(--success-bg); }
  .operation-status.failed { color: var(--danger); background: var(--danger-bg); }
  .tabs { display: flex; gap: 4px; border-bottom: 1px solid var(--border); flex-shrink: 0; padding: 14px 16px 0; background: var(--surface); }
  .tab-content { flex: 1; overflow-y: auto; padding: 14px 16px; }
  .tabs button {
    flex: 1; display: flex; align-items: center; justify-content: center; gap: 5px;
    padding: 8px 6px; font-size: 10.5px; font-weight: 700; color: var(--text-2);
    background: none; border: none; border-bottom: 2px solid transparent; border-radius: 0;
    cursor: pointer;
  }
  .tabs button:hover:not(.active) { color: var(--text); }
  .tabs button.active { color: var(--accent); border-bottom-color: var(--accent); }
  .tab-count {
    font-size: 9px; font-weight: 700; padding: 1px 6px; border-radius: 999px;
    background: var(--accent-bg); color: var(--accent);
  }
  .tabs button.active .tab-count { background: var(--accent); color: white; }
  .tab-live { width: 6px; height: 6px; border-radius: 50%; background: var(--gr); flex-shrink: 0; }
  .tab-panel:empty { display: none; }
  .section { border: 1px solid var(--border); border-radius: 12px; padding: 12px 14px; margin-bottom: 12px; }
  .section-title { font-size: 11px; font-weight: 700; color: var(--text); display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
  .ignored-summary { cursor: pointer; user-select: none; margin-bottom: 0; list-style: none; }
  .ignored-summary::-webkit-details-marker { display: none; }
  .ignored-summary::before { content: "▸"; font-size: 9px; color: var(--text-3); transition: transform 0.15s ease; }
  .ignored-section[open] .ignored-summary, .accepted-section[open] .ignored-summary { margin-bottom: 8px; }
  .ignored-section[open] .ignored-summary::before, .accepted-section[open] .ignored-summary::before { transform: rotate(90deg); }
  .live { display: flex; align-items: center; gap: 5px; font-size: 10px; font-weight: 700; color: var(--gr); }
  .spin { width: 10px; height: 10px; border-radius: 50%; border: 2px solid var(--gr-bg); border-top-color: var(--gr); animation: spin 0.8s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .finding { border-top: 1px dashed var(--border); padding-top: 10px; margin-top: 10px; }
  .finding:first-child { border-top: none; padding-top: 0; margin-top: 0; }
  .verdict { display: flex; align-items: center; flex-wrap: wrap; gap: 6px 8px; margin-bottom: 6px; }
  .badge { font-size: 10px; font-weight: 700; padding: 3px 8px; border-radius: 5px; flex-shrink: 0; }
  .badge-wrong { background: var(--danger-bg); color: var(--danger); }
  .badge-review { background: var(--warning-bg); color: var(--warning); }
  .badge-decided { background: var(--success-bg); color: var(--success); text-transform: capitalize; }
  .check-id { font-size: 11px; color: var(--text-3); min-width: 0; overflow-wrap: anywhere; }
  .engine-badge { font-size: 9px; font-weight: 700; text-transform: capitalize; color: var(--accent); background: var(--accent-bg); padding: 2px 7px; border-radius: 999px; flex-shrink: 0; }
  .finding-num-badge {
    display: inline-flex; align-items: center; justify-content: center; width: 16px; height: 16px;
    font-size: 9px; font-weight: 800; color: white; background: var(--accent); border-radius: 50%;
    flex-shrink: 0;
  }
  .save-state { margin-left: auto; font-size: 10px; color: var(--text-3); white-space: nowrap; }
  .save-state.saved { color: var(--success); }
  .save-state.failed { color: var(--danger); }
  .explain { font-size: 12px; color: var(--text-2); line-height: 1.6; margin: 0 0 8px; }
  .evidence { font-size: 11px; color: var(--text-2); padding-left: 16px; margin: 0 0 8px; }
  .decision-row { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 6px; }
  .decision-row.two-up { grid-template-columns: 1fr 1fr; }
  .decision-row.one-up { grid-template-columns: 1fr; }
  .decision-row button { padding: 7px; font-size: 11px; font-weight: 700; border-radius: 6px; border: none; cursor: pointer; }
  .accept { background: var(--success); color: #fff; }
  .ignore { background: #F5EBFC; color: #9333EA; }
  .undo-ignore, .undo-accept { background: var(--surface-2); color: var(--text-2); border: 1px solid var(--border-strong); }
  .edit-inline { background: var(--accent-bg); color: var(--accent); }
  .none { font-size: 11px; color: var(--text-3); }
  .decision-row button:disabled { opacity: .55; cursor: not-allowed; }
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
  .ai-review-controls { border-color: var(--accent); }
  .mode-pill { margin-left: auto; text-transform: capitalize; font-size: 9px; padding: 2px 7px; border-radius: 999px; color: var(--accent); background: var(--accent-bg); }
  .ai-review-help { font-size: 10px; line-height: 1.45; color: var(--text-2); margin: 0 0 8px; }
  .ai-scope-actions { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 5px; }
  .ai-scope-actions button, .ai-job-actions button { padding: 6px; font-size: 10px; font-weight: 700; border-radius: 6px; border: 1px solid var(--border-strong); color: var(--accent); background: var(--surface); cursor: pointer; }
  .ai-scope-actions button:disabled, .ai-job-actions button:disabled { opacity: .55; cursor: not-allowed; }
  .ai-job-status { margin-top: 9px; padding: 8px; border-radius: 7px; color: var(--accent); background: var(--accent-bg); }
  .ai-job-status.failed { color: var(--danger); background: var(--danger-bg); }
  .ai-job-status > div:first-child { display: flex; justify-content: space-between; gap: 8px; font-size: 10px; }
  .ai-job-status progress { width: 100%; height: 6px; margin: 5px 0; accent-color: var(--accent); }
  .ai-job-status small { display: block; font-size: 9px; color: var(--text-3); }
  .ai-failure-list { margin-top: 7px; padding-top: 6px; border-top: 1px solid color-mix(in srgb, var(--danger) 25%, transparent); font-size: 9px; line-height: 1.4; overflow-wrap: anywhere; }
  .ai-job-actions { margin-top: 6px; }
  .ai-job-background { margin-top: 9px; padding: 8px; border-radius: 7px; font-size: 9px; line-height: 1.4; color: var(--text-2); background: var(--surface-2); }
  .ai-control-error { margin: 8px 0 0; font-size: 10px; line-height: 1.4; color: var(--danger); overflow-wrap: anywhere; }
</style>
