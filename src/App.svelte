<script lang="ts">
  import { onMount } from "svelte";
  import { bridge } from "./lib/api/bridgeClient";
  import ImportScreen from "./lib/components/ImportScreen.svelte";
  import TopBar from "./lib/components/TopBar.svelte";
  import VerseList from "./lib/components/VerseList.svelte";
  import ReviewPanel from "./lib/components/ReviewPanel.svelte";
  import SettingsModal from "./lib/components/SettingsModal.svelte";
  import ExportModal from "./lib/components/ExportModal.svelte";
  import {
    project, currentChapter, chapterVerseNums, verseTexts, findingsByVerse,
    loadedChapters, selectedVerse, checkingProgress, approvedCount, verseNums,
    verseKey, settingsOpen, exportOpen, bookApprovedSummary,
  } from "./lib/stores";

  let opened = false;
  let engineStatus: "checking" | "ready" | "error" = "checking";
  let bookRunning = false;
  let bookProgressLabel = "";

  onMount(async () => {
    try {
      await bridge.ping();
      engineStatus = "ready";
    } catch {
      engineStatus = "error";
    }
  });

  async function handleOpened() {
    opened = true;
    const firstChapter = $project?.chapters[0] ?? "1";
    currentChapter.set(firstChapter);
    await loadChapter(firstChapter);
    const verses = $chapterVerseNums[firstChapter] ?? [];
    if (verses.length > 0) selectedVerse.set(verses[0]);
  }

  /**
   * The one place chapter data gets loaded: bulk verse-text fetch, then
   * per-verse background checks with visible progress. Used on initial
   * open, on chapter switch, and by "Run whole book" — so there's exactly
   * one code path for "make sure this chapter's data is loaded," not
   * three slightly different ones.
   */
  async function loadChapter(chapter: string): Promise<void> {
    if ($loadedChapters[chapter]) return; // already loaded, skip

    const { verses } = await bridge.chapterVerseData(chapter);
    const verseIds = Object.keys(verses);
    chapterVerseNums.update((m) => ({ ...m, [chapter]: verseIds }));

    const texts: Record<string, string> = {};
    for (const [v, data] of Object.entries(verses)) {
      texts[verseKey(chapter, v)] = data.text;
    }
    verseTexts.update((t) => ({ ...t, ...texts }));

    checkingProgress.set({ running: true, percent: 0, label: `Checking chapter ${chapter}` });
    for (let i = 0; i < verseIds.length; i++) {
      const v = verseIds[i];
      try {
        const findings = await bridge.runVerseChecks(chapter, v, ["local", "greekroom"]);
        findingsByVerse.update((map) => ({ ...map, [verseKey(chapter, v)]: findings }));
      } catch (e) {
        console.error(`check failed for ${chapter}:${v}`, e);
      }
      checkingProgress.set({
        running: i < verseIds.length - 1,
        percent: Math.round(((i + 1) / verseIds.length) * 100),
        label: `Checking chapter ${chapter}`,
      });
    }
    loadedChapters.update((l) => ({ ...l, [chapter]: true }));
  }

  async function switchChapter(chapter: string) {
    currentChapter.set(chapter);
    await loadChapter(chapter);
    const verses = $chapterVerseNums[chapter] ?? [];
    selectedVerse.set(verses.length > 0 ? verses[0] : null);
  }

  async function runWholeBook() {
    const chapters = $project?.chapters ?? [];
    bookRunning = true;
    for (let i = 0; i < chapters.length; i++) {
      const ch = chapters[i];
      bookProgressLabel = `Whole book: chapter ${ch} (${i + 1} of ${chapters.length})`;
      await loadChapter(ch);
    }
    bookRunning = false;
    bookProgressLabel = "";
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
  $: void $findingsByVerse, void $loadedChapters, (bookSummary = bookApprovedSummary());
</script>

<div class="frame">
  {#if !opened}
    <ImportScreen onOpened={handleOpened} />
  {/if}

  <TopBar
    onOpenSettings={() => settingsOpen.set(true)}
    onOpenExport={() => exportOpen.set(true)}
    onGotoVerse={gotoVerse}
    onChapterChange={switchChapter}
    exportEnabled={allApproved}
  />

  {#if $checkingProgress.running || bookRunning}
    <div class="progress-row">
      <div class="spin" />
      <span>{bookRunning ? bookProgressLabel : `${$checkingProgress.label} — ${$checkingProgress.percent}%`}</span>
      {#if !bookRunning}
        <div class="track"><div class="fill" style="width:{$checkingProgress.percent}%" /></div>
      {/if}
    </div>
  {/if}

  <div class="body">
    <div class="editor-col">
      <div class="editor-toolbar">
        <span>Chapter {$currentChapter} of {$project?.chapters.length ?? "?"}</span>
        <button class="whole-book-btn" on:click={runWholeBook} disabled={bookRunning}>
          {bookRunning ? "Running…" : "Run whole book"}
        </button>
        <span class="grow" />
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
    <span>Engine: {engineStatus}</span>
  </div>

  {#if $settingsOpen}
    <SettingsModal onClose={() => settingsOpen.set(false)} />
  {/if}

  {#if $exportOpen}
    <ExportModal onClose={() => exportOpen.set(false)} />
  {/if}
</div>

<style>
  .frame { width: 100vw; height: 100vh; background: var(--bg); display: flex; flex-direction: column; position: relative; overflow: hidden; }
  .progress-row { height: 32px; background: var(--surface-2); border-bottom: 1px solid var(--border); display: flex; align-items: center; gap: 10px; padding: 0 16px; font-size: 11px; color: var(--text-2); flex-shrink: 0; }
  .spin { width: 12px; height: 12px; border-radius: 50%; border: 2px solid var(--accent-bg); border-top-color: var(--accent); animation: spin 0.8s linear infinite; flex-shrink: 0; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .track { width: 160px; height: 6px; background: #EEF0F3; border-radius: 4px; overflow: hidden; }
  .fill { height: 100%; background: var(--accent); transition: width 0.3s; }
  .body { flex: 1; display: flex; overflow: hidden; }
  .editor-col { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
  .editor-toolbar { height: 34px; background: var(--surface-2); border-bottom: 1px solid var(--border); display: flex; align-items: center; gap: 10px; padding: 0 16px; font-size: 11px; color: var(--text-2); flex-shrink: 0; }
  .whole-book-btn { font-size: 11px; font-weight: 600; padding: 4px 10px; border-radius: 6px; border: 1px solid var(--border-strong); background: var(--surface); color: var(--text); cursor: pointer; }
  .whole-book-btn:disabled { opacity: 0.6; cursor: not-allowed; }
  .grow { flex: 1; }
  .statusbar { height: 28px; background: var(--surface); border-top: 1px solid var(--border); display: flex; align-items: center; padding: 0 16px; gap: 16px; font-size: 11px; color: var(--text-2); flex-shrink: 0; }
</style>
