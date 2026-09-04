<script lang="ts">
  import { createEventDispatcher, onDestroy, onMount } from "svelte";

  import { bridge } from "../api/bridgeClient";
  import type {
    AnalysisJobSnapshot,
    AnalysisScope,
    AnalysisScopeKind,
    AnalysisScopeStatus,
    AnalysisStage,
  } from "../types/analysisJob";

  export let chapter: string;
  export let verse: string | null = null;

  const dispatch = createEventDispatcher<{
    completed: { job: AnalysisJobSnapshot; scopeStatus: AnalysisScopeStatus };
    scopeStatus: AnalysisScopeStatus;
    scopeInvalidated: void;
  }>();

  const STAGES: Array<{ id: AnalysisStage; label: string }> = [
    { id: "SOURCE_INVENTORY", label: "Source inventory" },
    { id: "TARGET_INVENTORY", label: "Target inventory" },
    { id: "LOCATION", label: "Passage search" },
    { id: "MEANING", label: "Meaning analysis" },
    { id: "QA", label: "QA audit" },
  ];
  const TERMINAL = new Set(["COMPLETED", "COMPLETED_WITH_WARNINGS", "FAILED", "CANCELLED"]);

  let kind: Exclude<AnalysisScopeKind, "AFFECTED"> = verse ? "CURRENT_PASSAGE" : "CURRENT_CHAPTER";
  let startChapter = chapter;
  let startVerse = verse ?? "1";
  let endChapter = chapter;
  let endVerse = verse ?? "1";
  let scopeStatus: AnalysisScopeStatus | null = null;
  let job: AnalysisJobSnapshot | null = null;
  let loadingState = false;
  let starting = false;
  let error = "";
  let pollTimer: ReturnType<typeof setTimeout> | null = null;
  let refreshTimer: ReturnType<typeof setTimeout> | null = null;
  let destroyed = false;
  let mounted = false;
  let statusGeneration = 0;
  let statusSelectionSignature = "";
  let observedNavigation = `${chapter}\u241f${verse ?? ""}`;

  function requestedScope(selectedKind: Exclude<AnalysisScopeKind, "AFFECTED"> = kind): AnalysisScope {
    if (selectedKind === "CURRENT_PASSAGE") {
      return { kind: selectedKind, chapter, verse: verse ?? "" };
    }
    if (selectedKind === "CURRENT_CHAPTER") return { kind: selectedKind, chapter };
    if (selectedKind === "CURRENT_BOOK") return { kind: selectedKind };
    return { kind: selectedKind, startChapter, startVerse, endChapter, endVerse };
  }

  function scopeSignature(scope: AnalysisScope): string {
    return JSON.stringify({
      kind: scope.kind,
      baseKind: scope.baseKind ?? "",
      chapter: scope.chapter ?? "",
      verse: scope.verse ?? "",
      startChapter: scope.startChapter ?? "",
      startVerse: scope.startVerse ?? "",
      endChapter: scope.endChapter ?? "",
      endVerse: scope.endVerse ?? "",
    });
  }

  // A queued/running job outlives the selection that started it: the reviewer
  // navigates the queue (or a book-scoped run keeps going) while it works. Only
  // a terminal job may be replaced by whatever the newly selected scope reports.
  function isActive(snapshot: AnalysisJobSnapshot | null): boolean {
    return !!snapshot && !TERMINAL.has(snapshot.overallStatus);
  }

  // A half-typed range ("From verse" cleared to retype) is not an error the
  // reviewer should see - the engine rejects it, so never ask.
  function isResolvable(scope: AnalysisScope): boolean {
    if (scope.kind === "CURRENT_PASSAGE") return !!scope.verse;
    if (scope.kind === "SELECTED_RANGE") {
      return [scope.startChapter, scope.startVerse, scope.endChapter, scope.endVerse]
        .every((value) => !!value && value.trim() !== "");
    }
    return true;
  }

  function displayRange(rangeKey: string): string {
    const [start, end] = rangeKey.split("..");
    if (!end || start === end) return start;
    const first = /^(\S+) (\d+):(\S+)$/.exec(start);
    const last = /^(\S+) (\d+):(\S+)$/.exec(end);
    if (first && last && first[1] === last[1] && first[2] === last[2]) {
      return `${first[1]} ${first[2]}:${first[3]}–${last[2]}:${last[3]}`;
    }
    return `${start}–${end}`;
  }

  async function refreshScopeStatus(
    scope: AnalysisScope = requestedScope(),
  ): Promise<AnalysisScopeStatus | null> {
    if (!isResolvable(scope)) return null;
    const generation = ++statusGeneration;
    const signature = scopeSignature(scope);
    loadingState = true;
    error = "";
    try {
      const resolved = await bridge.analysisJobGetScopeStatus(scope);
      if (destroyed || generation !== statusGeneration
          || signature !== scopeSignature(requestedScope())) return null;
      scopeStatus = resolved;
      statusSelectionSignature = signature;
      if (!isActive(job)) {
        job = resolved.latestJob;
        if (isActive(job)) schedulePoll();
      }
      dispatch("scopeStatus", resolved);
      return resolved;
    } catch (cause) {
      if (generation === statusGeneration) error = String(cause);
      return null;
    } finally {
      if (generation === statusGeneration) loadingState = false;
    }
  }

  function schedulePoll(): void {
    if (destroyed || !job || TERMINAL.has(job.overallStatus)) return;
    if (pollTimer) clearTimeout(pollTimer);
    pollTimer = setTimeout(() => void poll(), 500);
  }

  async function poll(): Promise<void> {
    const tracked = job;
    if (!tracked) return;
    try {
      const polled = await bridge.analysisJobStatus(tracked.jobId);
      if (destroyed || job?.jobId !== tracked.jobId) return;
      job = polled;
      if (!TERMINAL.has(polled.overallStatus)) {
        schedulePoll();
        return;
      }
      const updated = await refreshScopeStatus();
      if (updated && (polled.overallStatus === "COMPLETED"
          || polled.overallStatus === "COMPLETED_WITH_WARNINGS")) {
        dispatch("completed", { job: polled, scopeStatus: updated });
      }
    } catch (cause) {
      error = String(cause);
    }
  }

  async function start(): Promise<void> {
    starting = true;
    loadingState = true;
    error = "";
    try {
      const base = requestedScope();
      const selectionSignature = scopeSignature(base);
      const generation = ++statusGeneration;
      const current = await bridge.analysisJobGetScopeStatus(base);
      if (generation !== statusGeneration
          || selectionSignature !== scopeSignature(requestedScope())) {
        error = "The selected analysis scope changed. Review the displayed range and run again.";
        void refreshScopeStatus();
        return;
      }
      scopeStatus = current;
      statusSelectionSignature = selectionSignature;
      dispatch("scopeStatus", current);
      const scope: AnalysisScope = current.state === "STALE"
        ? { ...base, kind: "AFFECTED", baseKind: kind }
        : base;
      const startStatus = scope.kind === "AFFECTED"
        ? await bridge.analysisJobGetScopeStatus(scope)
        : current;
      if (generation !== statusGeneration
          || selectionSignature !== scopeSignature(requestedScope())) {
        error = "The selected analysis scope changed. Review the displayed range and run again.";
        void refreshScopeStatus();
        return;
      }
      if (scope.kind === "AFFECTED") {
        scopeStatus = startStatus;
        dispatch("scopeStatus", startStatus);
      }
      const startedJob = await bridge.analysisJobStart(
        scope, startStatus.analysisFingerprint,
      );
      if (startedJob.analysisFingerprint !== startStatus.analysisFingerprint
          || startedJob.rangeKey !== startStatus.rangeKey) {
        error = "Bridge rejected an inconsistent resolved analysis scope. Refresh and retry.";
        void refreshScopeStatus();
        return;
      }
      job = startedJob;
      schedulePoll();
    } catch (cause) {
      error = String(cause);
    } finally {
      starting = false;
      loadingState = false;
    }
  }

  async function cancel(): Promise<void> {
    if (!job) return;
    try {
      job = await bridge.analysisJobCancel(job.jobId);
    } catch (cause) {
      error = String(cause);
    }
  }

  function changeScope(): void {
    statusGeneration += 1;
    if (!isActive(job)) {
      if (pollTimer) {
        clearTimeout(pollTimer);
        pollTimer = null;
      }
      job = null;
    }
    scopeStatus = null;
    statusSelectionSignature = "";
    error = "";
    dispatch("scopeInvalidated");
    // Typing a range fires per keystroke; resolve the settled value once.
    if (refreshTimer) clearTimeout(refreshTimer);
    refreshTimer = setTimeout(() => {
      refreshTimer = null;
      if (!destroyed) void refreshScopeStatus();
    }, 150);
  }

  function navigationChanged(): void {
    if (kind !== "SELECTED_RANGE") {
      startChapter = chapter;
      startVerse = verse ?? "1";
      endChapter = chapter;
      endVerse = verse ?? "1";
    }
    changeScope();
  }

  const STATE_LABELS: Record<string, string> = {
    NOT_ANALYZED: "Not analyzed",
    PARTIALLY_ANALYZED: "Partially analyzed",
    CURRENT: "Analysis current",
    STALE: "Analysis stale",
    RUNNING: "Analysis running",
    FAILED: "Analysis failed",
    SEARCH_INCOMPLETE: "Search incomplete",
  };
  $: displayedState = scopeStatus ? STATE_LABELS[scopeStatus.state] : "Checking analysis state";
  $: navigationKey = `${chapter}\u241f${verse ?? ""}`;
  $: if (mounted && navigationKey !== observedNavigation) {
    observedNavigation = navigationKey;
    navigationChanged();
  }

  onMount(() => {
    mounted = true;
    observedNavigation = navigationKey;
    void refreshScopeStatus();
  });
  onDestroy(() => {
    destroyed = true;
    if (pollTimer) clearTimeout(pollTimer);
    if (refreshTimer) clearTimeout(refreshTimer);
  });
</script>

<section class="analysis" aria-labelledby="analysis-heading">
  <div class="controls">
    <strong id="analysis-heading">Passage analysis</strong>
    <label>
      Scope
      <select aria-label="Scope" bind:value={kind} on:change={changeScope} disabled={starting || loadingState || job?.overallStatus === "RUNNING"}>
        {#if verse}<option value="CURRENT_PASSAGE">Current passage</option>{/if}
        <option value="CURRENT_CHAPTER">Current chapter</option>
        <option value="CURRENT_BOOK">Current book</option>
        <option value="SELECTED_RANGE">Selected reference range</option>
      </select>
    </label>
    {#if kind === "SELECTED_RANGE"}
      <div class="range" aria-label="Selected reference range">
        <label>From chapter <input aria-label="From chapter" bind:value={startChapter} on:input={changeScope} disabled={starting || job?.overallStatus === "RUNNING"} /></label>
        <label>verse <input aria-label="From verse" bind:value={startVerse} on:input={changeScope} disabled={starting || job?.overallStatus === "RUNNING"} /></label>
        <label>to chapter <input aria-label="To chapter" bind:value={endChapter} on:input={changeScope} disabled={starting || job?.overallStatus === "RUNNING"} /></label>
        <label>verse <input aria-label="To verse" bind:value={endVerse} on:input={changeScope} disabled={starting || job?.overallStatus === "RUNNING"} /></label>
      </div>
    {/if}
    <span class="state" data-state={scopeStatus?.state ?? "LOADING"}>{displayedState}</span>
    {#if job?.overallStatus === "RUNNING" || job?.overallStatus === "QUEUED"}
      <span class="range-label">
        Running: {displayRange(job.rangeKey)}
      </span>
    {:else if scopeStatus?.rangeKey && statusSelectionSignature === scopeSignature(requestedScope())}
      <span class="range-label">Will analyze: {displayRange(scopeStatus.rangeKey)}</span>
    {/if}
    <button type="button" class="run" disabled={starting || loadingState || !scopeStatus || statusSelectionSignature !== scopeSignature(requestedScope()) || job?.overallStatus === "RUNNING"} on:click={start}>
      {scopeStatus?.state === "STALE" ? "Re-run affected analysis" : "Run analysis"}
    </button>
    {#if job?.overallStatus === "RUNNING" || job?.overallStatus === "QUEUED"}
      <button type="button" class="cancel" on:click={cancel} disabled={job.cancellationRequested}>
        {job.cancellationRequested ? "Cancelling…" : "Cancel"}
      </button>
    {/if}
  </div>

  {#if job}
    <div class="progress" role="status" aria-live="polite">
      <span>{job.stageProgress.completedStages} of {job.stageProgress.totalStages} stages complete</span>
      <ol aria-label="Analysis stages">
        {#each STAGES as stage}
          <li data-status={job.stageStatuses[stage.id].status}>
            <span aria-hidden="true">{job.stageStatuses[stage.id].status === "REUSED" ? "↻" : job.stageStatuses[stage.id].status === "COMPLETED" ? "✓" : job.stageStatuses[stage.id].status === "RUNNING" ? "●" : "○"}</span>
            {stage.label}: {job.stageStatuses[stage.id].status.toLowerCase().replace("_", " ")}
          </li>
        {/each}
      </ol>
    </div>
  {/if}

  {#if scopeStatus?.providerCapability.semanticRetrieval === "LIMITED"}
    <p class="warning" role="note">
      Multilingual semantic retrieval is limited: {scopeStatus.providerCapability.multilingualEmbeddingProvider === "FIXTURE_ONLY"
        ? "a fixture provider is available only for fixture validation."
        : "no production multilingual embedding provider is configured."}
    </p>
  {/if}
  {#if job?.searchIncomplete}
    <p class="warning" role="alert">Search was incomplete. Bridge did not infer omissions from unresolved searches.</p>
  {/if}
  {#if job?.failures.length}
    <p class="error" role="alert">{job.failures[0].message}</p>
  {:else if error}
    <p class="error" role="alert">{error}</p>
  {/if}
</section>

<style>
  .analysis { flex: none; border-bottom: 1px solid #dbeafe; background: #f8fbff; }
  .controls { display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap; padding: 0.45rem 0.6rem; }
  strong { font-size: 0.78rem; color: #1e3a8a; }
  label { display: flex; align-items: center; gap: 0.25rem; font-size: 0.7rem; color: #4b5563; }
  select, input, button { font: inherit; }
  select, input { border: 1px solid #cbd5e1; border-radius: 4px; background: #fff; padding: 0.22rem 0.35rem; }
  input { width: 2.4rem; }
  .range { display: flex; align-items: center; gap: 0.3rem; flex-wrap: wrap; }
  .state { font-size: 0.7rem; padding: 0.2rem 0.45rem; border-radius: 999px; background: #e5e7eb; color: #374151; }
  .state[data-state="CURRENT"] { background: #dcfce7; color: #166534; }
  .state[data-state="STALE"], .state[data-state="SEARCH_INCOMPLETE"] { background: #fef3c7; color: #92400e; }
  .state[data-state="FAILED"] { background: #fee2e2; color: #991b1b; }
  .range-label { font-size: 0.7rem; color: #475569; }
  button { padding: 0.25rem 0.55rem; border-radius: 4px; cursor: pointer; }
  button:disabled { cursor: default; opacity: 0.55; }
  .run { border: 1px solid #2563eb; background: #2563eb; color: #fff; }
  .cancel { border: 1px solid #d1d5db; background: #fff; color: #374151; }
  button:focus-visible, select:focus-visible, input:focus-visible { outline: 2px solid #2563eb; outline-offset: 1px; }
  .progress { padding: 0 0.6rem 0.4rem; font-size: 0.7rem; color: #374151; }
  ol { display: flex; flex-wrap: wrap; gap: 0.65rem; list-style: none; padding: 0.3rem 0 0; margin: 0; }
  li[data-status="RUNNING"] { color: #1d4ed8; font-weight: 600; }
  li[data-status="FAILED"] { color: #b91c1c; }
  .warning, .error { margin: 0; padding: 0.3rem 0.6rem; font-size: 0.72rem; }
  .warning { background: #fffbeb; color: #92400e; }
  .error { background: #fef2f2; color: #991b1b; }
</style>
