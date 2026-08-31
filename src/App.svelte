<script lang="ts">
  import { onMount } from "svelte";
  import { bridge } from "./lib/api/bridgeClient";
  import ImportScreen from "./lib/components/ImportScreen.svelte";
  import TopBar from "./lib/components/TopBar.svelte";
  import VerseList from "./lib/components/VerseList.svelte";
  import ReviewPanel from "./lib/components/ReviewPanel.svelte";
  import SettingsModal from "./lib/components/SettingsModal.svelte";
  import ExportModal from "./lib/components/ExportModal.svelte";
  import ProjectDashboard from "./lib/components/ProjectDashboard.svelte";
  import DiagnosticsPanel from "./lib/components/DiagnosticsPanel.svelte";
  import SemanticMappingValidation from "./lib/components/SemanticMappingValidation.svelte";
  import type { AiCheckReview, AlignmentWorkStatus, BookProgressEntry, CheckJobSnapshot, ProjectReport, QaFinding } from "./lib/types/finding";
  import {
    project, currentChapter, chapterVerseNums, verseTexts, findingsByVerse,
    checkStatusByVerse, alignmentStatusByVerse, loadedChapters, selectedVerse, checkingProgress, approvedCount, verseNums,
    verseKey, settingsOpen, exportOpen, bookApprovedSummary, resetBookState, reviewerMode,
    aiCheckReviewsByVerse, diagnosticsOpen, engineLog, appendEngineLog,
  } from "./lib/stores";

  let opened = false;
  let engineStatus: "checking" | "ready" | "error" = "checking";
  let activeJobId = "";
  let monitorGeneration = 0;
  let openingBook = "";
  let bookOpenError = "";
  let droppedPath = "";
  let dropSequence = 0;
  let draggingOver = false;
  let dropError = "";
  let chapterLoadSequence = 0;
  let showingDashboard = false;
  let showingSemanticValidation = false;
  let bookProgress: BookProgressEntry[] = [];
  let dashboardLoading = false;
  let dashboardError = "";
  let report: ProjectReport | null = null;
  let reportLoading = false;
  let reportError = "";
  let engineNotice = "";
  let engineNoticeTimer: ReturnType<typeof setTimeout> | undefined;
  let settingsInitialPane: "ai" | "quality" | "resources" | "security" = "ai";

  function openSettings(pane: "ai" | "quality" | "resources" | "security" = "ai"): void {
    settingsInitialPane = pane;
    settingsOpen.set(true);
  }

  // Sidecar respawns are silent by design (see sidecar.rs) — the new
  // process has no project open, so anything project-scoped will fail
  // with "No project open" until this reconnects it. This is the recovery
  // path for that, not just a status update.
  async function handleEngineRespawn(): Promise<void> {
    if (engineNoticeTimer) clearTimeout(engineNoticeTimer);
    engineNotice = "Engine restarted — reconnecting…";
    try {
      await bridge.ping();
      engineStatus = "ready";
    } catch {
      engineStatus = "error";
    }
    const reopenPath = $project?.path;
    if (reopenPath) {
      try {
        const info = await bridge.openProject(reopenPath, $project?.projectId);
        const siblings = $project?.importedProjects;
        if (!info.importedProjects && siblings) info.importedProjects = siblings;
        project.set(info);
        engineNotice = "Engine restarted — project reconnected automatically.";
      } catch (error) {
        engineNotice = `Engine restarted, but the project could not be reopened automatically (${error instanceof Error ? error.message : String(error)}). Reopen it from Projects if things look stale.`;
      }
    } else {
      engineNotice = "Engine restarted.";
    }
    engineNoticeTimer = setTimeout(() => { engineNotice = ""; }, 10000);
  }

  onMount(() => {
    let unlisten: (() => void) | null = null;
    let unlistenLog: (() => void) | null = null;
    let unlistenRespawn: (() => void) | null = null;
    let disposed = false;
    void (async () => {
      try {
        const initialLog = await bridge.engineLogRecent(200);
        if (!disposed) engineLog.set(initialLog);
      } catch (error) {
        console.error("Could not load engine diagnostics", error);
      }
      const stopLog = await bridge.onEngineLog(appendEngineLog);
      if (disposed) stopLog();
      else unlistenLog = stopLog;
      const stopRespawn = await bridge.onEngineRespawned(() => void handleEngineRespawn());
      if (disposed) stopRespawn();
      else unlistenRespawn = stopRespawn;

      try {
        await bridge.ping();
        engineStatus = "ready";
        try {
          const settings = await bridge.getSettings();
          reviewerMode.set(settings.reviewerMode);
        } catch (error) {
          console.error("Could not load reviewer mode", error);
        }
        const stopListening = await bridge.onFileDrop(
          (paths) => void handleDroppedPaths(paths),
          (phase) => { draggingOver = phase === "over"; },
        );
        if (disposed) stopListening();
        else unlisten = stopListening;
      } catch {
        engineStatus = "error";
      }
    })();
    return () => {
      disposed = true;
      unlisten?.();
      unlistenLog?.();
      unlistenRespawn?.();
      if (engineNoticeTimer) clearTimeout(engineNoticeTimer);
    };
  });

  async function handleDroppedPaths(paths: string[]) {
    draggingOver = false;
    dropError = "";
    if (paths.length !== 1) {
      dropError = "Drop exactly one project file or folder at a time.";
      return;
    }
    await showProjectHome();
    droppedPath = paths[0];
    dropSequence += 1;
  }

  async function showProjectHome() {
    await stopActiveJob();
    resetBookState();
    project.set(null);
    opened = false;
    showingSemanticValidation = false;
    openingBook = "";
    bookOpenError = "";
  }

  async function handleOpened() {
    opened = true;
    showingDashboard = true;
    void loadDashboard();
    void loadReport();
  }

  async function loadDashboard(): Promise<void> {
    dashboardLoading = true;
    dashboardError = "";
    try {
      bookProgress = (await bridge.listBookProgress()).books;
    } catch (error) {
      dashboardError = error instanceof Error ? error.message : String(error);
    } finally {
      dashboardLoading = false;
    }
  }

  async function loadReport(): Promise<void> {
    reportLoading = true;
    reportError = "";
    try {
      report = await bridge.projectReport();
    } catch (error) {
      reportError = error instanceof Error ? error.message : String(error);
    } finally {
      reportLoading = false;
    }
  }

  function openDashboard(): void {
    showingSemanticValidation = false;
    showingDashboard = true;
    void loadDashboard();
    void loadReport();
  }

  const VALIDATION_BOOK_IDS = new Set(["LUK", "PHP"]);

  async function openSemanticValidation(): Promise<void> {
    if ($reviewerMode !== "advanced") return;
    const currentBookId = $project?.bookId?.toUpperCase() ?? "";
    if (!VALIDATION_BOOK_IDS.has(currentBookId)) {
      const validationBook = $project?.importedProjects?.find((book) => (
        VALIDATION_BOOK_IDS.has(book.bookId?.toUpperCase())
      ));
      if (validationBook && !(await switchBook(validationBook.path, false))) return;
    }
    showingDashboard = false;
    showingSemanticValidation = true;
  }

  async function switchValidationBook(path: string): Promise<void> {
    if (!$project || path === $project.path) return;
    if (!(await switchBook(path, false))) {
      throw new Error(bookOpenError || "The validation book could not be opened.");
    }
  }

  async function enterBookFromDashboard(path: string): Promise<void> {
    // switchBook() no-ops when path === $project.path, which is exactly the
    // first-open interstitial case (enterCurrentProject was never called
    // yet) — so the already-open primary book's own row needs this instead.
    if ($project && path === $project.path) {
      showingDashboard = false;
      if (!$loadedChapters[$currentChapter]) await enterCurrentProject();
      return;
    }
    await switchBook(path);
    showingDashboard = false;
  }

  // Clicking a book row (not its Open button) previews that book's report in
  // the dashboard's right panel without leaving the dashboard — same
  // switchBook(path, false) seam openSemanticValidation/switchValidationBook
  // already use to activate a sibling book with no editor navigation.
  async function previewBookOnDashboard(path: string): Promise<void> {
    if ($project && path === $project.path) return;
    if (await switchBook(path, false)) void loadReport();
  }

  // Shared by initial open and book switching: land on the first chapter
  // and its first verse once `project` points at the book to display.
  async function enterCurrentProject(): Promise<void> {
    const firstChapter = $project?.chapters[0] ?? "1";
    await activateChapter(firstChapter);
  }

  // Switch to a sibling book from a multi-book import. The sidecar's
  // project.open doesn't echo back importedProjects (only project.import
  // does), so the sibling list is carried forward on the frontend instead
  // of being re-fetched.
  async function switchBook(path: string, enterEditor = true): Promise<boolean> {
    if (!$project || openingBook) return false;
    if (path === $project.path) return true;
    const siblings = $project.importedProjects;
    const destination = siblings?.find((book) => book.path === path);
    openingBook = destination?.bookName ?? "book";
    bookOpenError = "";
    try {
      await stopActiveJob();
      const info = await bridge.openProject(path);
      if (!info.importedProjects && siblings) info.importedProjects = siblings;
      resetBookState();
      project.set(info);
      if (enterEditor) await enterCurrentProject();
      return true;
    } catch (error) {
      bookOpenError = error instanceof Error ? error.message : String(error);
      return false;
    } finally {
      openingBook = "";
    }
  }

  async function ensureChapterData(chapter: string): Promise<void> {
    const knownVerses = $chapterVerseNums[chapter] ?? [];
    if (
      knownVerses.length > 0 &&
      knownVerses.every((verse) => Object.prototype.hasOwnProperty.call($verseTexts, verseKey(chapter, verse)))
    ) return;
    const { verses } = await bridge.chapterVerseData(chapter);
    const verseIds = Object.keys(verses);
    chapterVerseNums.update((m) => ({ ...m, [chapter]: verseIds }));

    const texts: Record<string, string> = {};
    const alignmentStatuses: Record<string, AlignmentWorkStatus> = {};
    for (const [v, data] of Object.entries(verses)) {
      texts[verseKey(chapter, v)] = data.text;
      alignmentStatuses[verseKey(chapter, v)] = data.alignmentStatus;
    }
    verseTexts.update((t) => ({ ...t, ...texts }));
    alignmentStatusByVerse.update((existing) => ({ ...existing, ...alignmentStatuses }));
  }

  async function hydrateChapterAIReviews(
    chapter: string, expectedProjectPath: string, sequence: number,
  ): Promise<void> {
    try {
      const result = await bridge.listAIReviewsForChapter(chapter);
      if (
        sequence !== chapterLoadSequence || chapter !== $currentChapter
        || ($project?.path ?? "") !== expectedProjectPath
      ) return;
      const updates: Record<string, AiCheckReview[]> = {};
      for (const [verse, reviews] of Object.entries(result.reviewsByVerse)) {
        updates[verseKey(chapter, verse)] = reviews;
      }
      aiCheckReviewsByVerse.update((existing) => ({ ...existing, ...updates }));
    } catch (error) {
      console.error("Could not restore chapter AI reviews", error);
    }
  }

  function applyJobSnapshot(snapshot: CheckJobSnapshot): void {
    chapterVerseNums.update((existing) => ({ ...existing, ...snapshot.chapterVerses }));

    const findingUpdates: Record<string, QaFinding[]> = {};
    const statusUpdates: Record<string, "succeeded" | "failed"> = {};
    for (const [key, result] of Object.entries(snapshot.results)) {
      findingUpdates[key] = result.findings;
      statusUpdates[key] = result.status;
    }
    if (Object.keys(findingUpdates).length > 0) {
      findingsByVerse.update((existing) => ({ ...existing, ...findingUpdates }));
      checkStatusByVerse.update((existing) => ({ ...existing, ...statusUpdates }));
    }

    const terminal = ["succeeded", "failed", "cancelled"].includes(snapshot.state);
    if (terminal) {
      checkStatusByVerse.update((existing) => {
        const next = { ...existing };
        for (const [chapter, verses] of Object.entries(snapshot.chapterVerses)) {
          for (const verse of verses) {
            const key = verseKey(chapter, verse);
            if (!snapshot.results[key]) next[key] = snapshot.state === "cancelled" ? "cancelled" : "failed";
          }
        }
        return next;
      });
      loadedChapters.update((existing) => {
        const next = { ...existing };
        for (const [chapter, verses] of Object.entries(snapshot.chapterVerses)) {
          next[chapter] = verses.length > 0 && verses.every(
            (verse) => snapshot.results[verseKey(chapter, verse)]?.status === "succeeded",
          );
        }
        return next;
      });
    }

    const reference = snapshot.currentChapter
      ? ` · ${snapshot.currentChapter}${snapshot.currentVerse ? `:${snapshot.currentVerse}` : ""}`
      : "";
    checkingProgress.set({
      running: !terminal,
      percent: snapshot.percent,
      label: `${snapshot.currentStage}${reference}`,
      jobId: snapshot.jobId,
      state: snapshot.state,
      error: snapshot.error ?? "",
      scope: snapshot.scope,
    });
  }

  async function monitorJob(initial: CheckJobSnapshot, generation: number): Promise<void> {
    let snapshot = initial;
    try {
      while (!["succeeded", "failed", "cancelled"].includes(snapshot.state)) {
        await new Promise((resolve) => setTimeout(resolve, 750));
        if (generation !== monitorGeneration) return;
        snapshot = await bridge.checkStatus(snapshot.jobId);
        if (generation !== monitorGeneration) return;
        applyJobSnapshot(snapshot);
      }
    } catch (error) {
      if (generation !== monitorGeneration) return;
      checkingProgress.set({
        running: false,
        percent: snapshot.percent,
        label: "Checking failed",
        jobId: snapshot.jobId,
        state: "failed",
        error: error instanceof Error ? error.message : String(error),
        scope: snapshot.scope,
      });
    } finally {
      if (generation === monitorGeneration) activeJobId = "";
    }
  }

  function markJobPending(snapshot: CheckJobSnapshot): void {
    checkStatusByVerse.update((existing) => {
      const next = { ...existing };
      for (const [chapter, verses] of Object.entries(snapshot.chapterVerses)) {
        for (const verse of verses) next[verseKey(chapter, verse)] = "pending";
      }
      return next;
    });
  }

  async function beginChecks(scope: "chapter" | "book", chapters: string[]): Promise<void> {
    if (activeJobId) return;
    const snapshot = await bridge.startChecks(scope, chapters, ["local", "greekroom"]);
    activeJobId = snapshot.jobId;
    const generation = ++monitorGeneration;
    markJobPending(snapshot);
    applyJobSnapshot(snapshot);
    void monitorJob(snapshot, generation);
  }

  async function activateChapter(chapter: string, targetVerse?: string): Promise<void> {
    const sequence = ++chapterLoadSequence;
    currentChapter.set(chapter);
    await ensureChapterData(chapter);
    if (sequence !== chapterLoadSequence || chapter !== $currentChapter) return;
    const verses = $chapterVerseNums[chapter] ?? [];
    selectedVerse.set(
      targetVerse && verses.includes(targetVerse) ? targetVerse : (verses.length > 0 ? verses[0] : null),
    );
    void hydrateChapterAIReviews(chapter, $project?.path ?? "", sequence);
    if (!$loadedChapters[chapter] && !activeJobId) {
      await beginChecks("chapter", [chapter]);
    }
  }

  // Report/dashboard click-through (see ProjectDashboard's exceptionQueue
  // rows): project.report is scoped to whichever book is currently open,
  // so this never needs to switch books — just land on the right
  // chapter:verse and close the dashboard so the editor is visible.
  async function navigateToFinding(chapter: string, verse: string): Promise<void> {
    showingDashboard = false;
    showingSemanticValidation = false;
    await activateChapter(chapter, verse);
  }

  async function cancelChecks(): Promise<void> {
    if (!activeJobId) return;
    applyJobSnapshot(await bridge.cancelChecks(activeJobId));
  }

  async function stopActiveJob(): Promise<void> {
    const jobId = activeJobId;
    if (!jobId) return;
    await bridge.cancelChecks(jobId);
    let snapshot = await bridge.checkStatus(jobId);
    while (!["succeeded", "failed", "cancelled"].includes(snapshot.state)) {
      await new Promise((resolve) => setTimeout(resolve, 400));
      snapshot = await bridge.checkStatus(jobId);
    }
    monitorGeneration++;
    activeJobId = "";
    applyJobSnapshot(snapshot);
  }

  async function retryChecks(): Promise<void> {
    const failedJobId = $checkingProgress.jobId;
    if (!failedJobId || activeJobId) return;
    const snapshot = await bridge.retryChecks(failedJobId);
    activeJobId = snapshot.jobId;
    const generation = ++monitorGeneration;
    markJobPending(snapshot);
    applyJobSnapshot(snapshot);
    void monitorJob(snapshot, generation);
  }

  function dismissCheckNotice(): void {
    checkingProgress.set({
      running: false, percent: 0, label: "", jobId: "", state: "idle", error: "", scope: "chapter",
    });
  }

  async function switchChapter(chapter: string) {
    await activateChapter(chapter);
  }

  async function runWholeBook() {
    const chapters = $project?.chapters ?? [];
    await beginChecks("book", chapters);
  }

  function selectVerse(v: string) {
    selectedVerse.set(v);
  }

  function gotoVerse(v: string) {
    if (($chapterVerseNums[$currentChapter] ?? []).includes(v)) selectedVerse.set(v);
  }

  // Export is enabled only once every chapter in the whole book has been
  // loaded AND fully approved — not just the currently visible one.
  $: bookSummary = bookApprovedSummary();
  $: allApproved =
    $project !== null &&
    bookSummary.totalChapters > 0 &&
    bookSummary.approvedChapters === bookSummary.totalChapters;

  // recompute bookSummary reactively when findings/loadedChapters change
  $: void $findingsByVerse, void $checkStatusByVerse, void $loadedChapters, (bookSummary = bookApprovedSummary());

  $: if ($reviewerMode !== "advanced" && showingSemanticValidation) {
    showingSemanticValidation = false;
    showingDashboard = true;
  }
  $: screen = (
    !opened ? "home" : showingSemanticValidation ? "validation" : showingDashboard ? "dashboard" : "editor"
  ) as "home" | "dashboard" | "validation" | "editor";
  $: projectName = $project?.projectName || $project?.bibleName || $project?.bookName || "";
  $: dashboardSubtitle = [
    $project?.targetLanguage,
    bookProgress.length > 0 ? `${bookProgress.length} ${bookProgress.length === 1 ? "book" : "books"}` : "",
  ].filter(Boolean).join(" · ");

  $: alignmentChapterSummary = ($chapterVerseNums[$currentChapter] ?? []).reduce(
    (counts, verse) => {
      const status = $alignmentStatusByVerse[verseKey($currentChapter, verse)] ?? "untouched";
      counts[status] += 1;
      return counts;
    },
    { complete: 0, partial: 0, untouched: 0, invalid: 0 },
  );
</script>

<div class="frame">
  <TopBar
    {screen}
    {projectName}
    onGoHome={showProjectHome}
    onGoToDashboard={openDashboard}
    onOpenSettings={() => openSettings("ai")}
    onOpenExport={() => exportOpen.set(true)}
    onGotoVerse={gotoVerse}
    onChapterChange={switchChapter}
    onBookChange={switchBook}
    exportEnabled={$project !== null}
    bookSwitching={Boolean(openingBook)}
  />

  {#if openingBook}
    <div class="progress-row checking-row">
      <div class="spin" />
      <span class="progress-label">Opening {openingBook}…</span>
      <div class="track"><div class="fill indeterminate" /></div>
      <span />
    </div>
  {:else if bookOpenError}
    <div class="progress-row check-notice">
      <span class="check-message">Could not open book: {bookOpenError}</span>
      <span class="grow" />
      <button class="progress-action" on:click={() => (bookOpenError = "")}>Dismiss</button>
    </div>
  {:else if $checkingProgress.running}
    <div class="progress-row checking-row">
      <div class="spin" />
      <span class="progress-label" title={$checkingProgress.label}>
        {$checkingProgress.label} — {$checkingProgress.percent}%
      </span>
      <div class="track"><div class="fill" style="width:{$checkingProgress.percent}%" /></div>
      <button class="progress-action cancel-action" on:click={cancelChecks} disabled={$checkingProgress.state === "cancelling"}>
        {$checkingProgress.state === "cancelling" ? "Cancelling…" : "Cancel"}
      </button>
    </div>
  {:else if $checkingProgress.state === "failed" || $checkingProgress.state === "cancelled"}
    <div class="progress-row check-notice">
      <span class="check-message" title={$checkingProgress.error}>{$checkingProgress.error || ($checkingProgress.state === "cancelled" ? "Checking was cancelled." : "Checking failed.")}</span>
      <span class="grow" />
      <button class="progress-action" on:click={retryChecks}>Retry</button>
      <button class="progress-action" on:click={dismissCheckNotice}>Dismiss</button>
    </div>
  {/if}

  {#if screen === "home"}
    <ImportScreen onOpened={handleOpened} {droppedPath} {dropSequence} />
  {:else if screen === "dashboard"}
    <ProjectDashboard
      {projectName}
      subtitle={dashboardSubtitle}
      books={bookProgress}
      loading={dashboardLoading}
      error={dashboardError}
      onSelectBook={enterBookFromDashboard}
      onPreviewBook={previewBookOnDashboard}
      onRetry={loadDashboard}
      {report}
      reportLoading={reportLoading}
      reportError={reportError}
      onNavigateToFinding={navigateToFinding}
      advancedMode={$reviewerMode === "advanced"}
      onOpenSemanticValidation={openSemanticValidation}
      onRequestAdvancedMode={() => openSettings("quality")}
    />
  {:else if screen === "validation"}
    {#key $project?.path}
      <SemanticMappingValidation
        onClose={openDashboard}
        onNavigate={navigateToFinding}
        books={$project?.importedProjects ?? []}
        currentBookPath={$project?.path ?? ""}
        onBookChange={switchValidationBook}
      />
    {/key}
  {:else}
    <div class="body">
      <div class="editor-col">
        <div class="editor-toolbar">
          <span>Chapter {$currentChapter} of {$project?.chapters.length ?? "?"}</span>
          <button class="whole-book-btn" on:click={runWholeBook} disabled={Boolean(activeJobId)}>
            {$checkingProgress.scope === "book" && $checkingProgress.running ? "Running…" : "Run whole book"}
          </button>
          <span class="grow" />
          <span title="Word-alignment status for this chapter">
            Alignment: {alignmentChapterSummary.complete} complete · {alignmentChapterSummary.partial} partial
            {#if alignmentChapterSummary.invalid} · {alignmentChapterSummary.invalid} invalid{/if}
          </span>
          <span>{bookSummary.approvedChapters}/{bookSummary.totalChapters} chapters approved</span>
        </div>
        <VerseList onSelect={selectVerse} />
      </div>
      <ReviewPanel />
    </div>

    <div class="statusbar">
      {#if $project}
        <span>Project: <b>{$project.bookName}</b></span>
        <span>Chapter: <b>{$currentChapter}</b></span>
        <span style="color:var(--success);">✓ Approved: {$approvedCount}/{$verseNums.length}</span>
      {/if}
      <span class="grow" />
      {#if engineNotice}<span class="engine-notice">{engineNotice}</span>{/if}
      <span>Engine: {engineStatus}</span>
      <button class="diagnostics-btn" on:click={() => diagnosticsOpen.set(true)}>
        Diagnostics
        {#if $engineLog.some((entry) => entry.level === "error")}<span class="error-dot" />{/if}
      </button>
    </div>
  {/if}

  {#if $settingsOpen}
    <SettingsModal initialPane={settingsInitialPane} onClose={() => settingsOpen.set(false)} />
  {/if}

  {#if $diagnosticsOpen}
    <DiagnosticsPanel onClose={() => diagnosticsOpen.set(false)} />
  {/if}

  {#if $exportOpen}
    <ExportModal reviewComplete={allApproved} onClose={() => exportOpen.set(false)} />
  {/if}

  {#if draggingOver}
    <div class="global-drop" role="presentation">Drop to review this project source</div>
  {/if}
  {#if dropError}
    <div class="drop-error">{dropError}<button on:click={() => (dropError = "")}>Dismiss</button></div>
  {/if}
</div>

<style>
  .frame { width: 100vw; height: 100vh; background: var(--bg); display: flex; flex-direction: column; position: relative; overflow: hidden; }
  .progress-row { height: 32px; background: var(--surface-2); border-bottom: 1px solid var(--border); display: flex; align-items: center; gap: 10px; padding: 0 16px; font-size: 11px; color: var(--text-2); flex-shrink: 0; }
  .checking-row { display: grid; grid-template-columns: 12px minmax(220px, 320px) minmax(120px, 1fr) 84px; }
  .progress-label { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .spin { width: 12px; height: 12px; border-radius: 50%; border: 2px solid var(--accent-bg); border-top-color: var(--accent); animation: spin 0.8s linear infinite; flex-shrink: 0; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .track { width: 100%; height: 6px; background: #EEF0F3; border-radius: 4px; overflow: hidden; }
  .fill { height: 100%; background: var(--accent); transition: width 0.3s; }
  .indeterminate { width: 35%; animation: slide 1.1s ease-in-out infinite; }
  @keyframes slide { from { transform: translateX(-100%); } to { transform: translateX(300%); } }
  .progress-action { border: 1px solid var(--border-strong); background: var(--surface); color: var(--text-2); border-radius: 5px; padding: 2px 8px; font-size: 11px; cursor: pointer; }
  .cancel-action { width: 84px; }
  .progress-action:disabled { opacity: 0.55; cursor: wait; }
  .check-notice { color: var(--danger); height: auto; min-height: 32px; max-height: 96px; align-items: flex-start; padding-top: 7px; padding-bottom: 7px; }
  .check-message { flex: 1; min-width: 0; max-height: 78px; overflow: auto; white-space: normal; overflow-wrap: anywhere; line-height: 1.35; }
  .body { flex: 1; display: flex; overflow: hidden; }
  .editor-col { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
  .editor-toolbar { height: 34px; background: var(--surface-2); border-bottom: 1px solid var(--border); display: flex; align-items: center; gap: 10px; padding: 0 16px; font-size: 11px; color: var(--text-2); flex-shrink: 0; }
  .whole-book-btn { font-size: 11px; font-weight: 600; padding: 4px 10px; border-radius: 6px; border: 1px solid var(--border-strong); background: var(--surface); color: var(--text); cursor: pointer; }
  .whole-book-btn:disabled { opacity: 0.6; cursor: not-allowed; }
  .grow { flex: 1; }
  .statusbar { height: 28px; background: var(--surface); border-top: 1px solid var(--border); display: flex; align-items: center; padding: 0 16px; gap: 16px; font-size: 11px; color: var(--text-2); flex-shrink: 0; }
  .engine-notice { color: var(--warning); font-weight: 600; }
  .diagnostics-btn { position: relative; font-size: 10px; font-weight: 650; padding: 3px 9px; border-radius: 999px; border: 1px solid var(--border-strong); background: var(--surface-2); color: var(--text-2); cursor: pointer; display: flex; align-items: center; gap: 5px; }
  .diagnostics-btn:hover { background: var(--surface); }
  .error-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--danger); }
  .global-drop { position: absolute; inset: 12px; z-index: 100; display: grid; place-items: center; border: 3px dashed var(--accent); border-radius: 14px; background: color-mix(in srgb, var(--accent-bg) 92%, transparent); color: var(--accent); font-size: 17px; font-weight: 750; pointer-events: none; }
  .drop-error { position: absolute; z-index: 101; left: 50%; bottom: 42px; transform: translateX(-50%); display: flex; align-items: center; gap: 14px; border: 1px solid var(--danger); border-radius: 8px; background: var(--surface); color: var(--danger); padding: 9px 12px; font-size: 11px; box-shadow: 0 8px 24px rgba(0,0,0,.14); }
  .drop-error button { border: 0; background: transparent; color: var(--accent); cursor: pointer; font-size: 11px; }
</style>
