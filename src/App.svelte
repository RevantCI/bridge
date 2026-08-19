<script lang="ts">
  import { onMount } from "svelte";
  import { bridge } from "./lib/api/bridgeClient";
  import ImportScreen from "./lib/components/ImportScreen.svelte";
  import TopBar from "./lib/components/TopBar.svelte";
  import VerseList from "./lib/components/VerseList.svelte";
  import ReviewPanel from "./lib/components/ReviewPanel.svelte";
  import {
    project, currentChapter, verseNums, findingsByVerse,
    selectedVerse, checkingProgress, approvedCount,
  } from "./lib/stores";

  let opened = false;
  let engineStatus: "checking" | "ready" | "error" = "checking";

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
    await runChapterChecks();
  }

  // Background chapter-wise check orchestration: runs local QA + Greek
  // Room across every verse in the chapter, one at a time, updating the
  // status bar as it goes. This is the "automate the whole checks"
  // requirement — Greek Room is re-run live again on verse focus in
  // ReviewPanel per the approved design; this pass seeds the initial state.
  async function runChapterChecks() {
    const verses = [...$verseNums];
    checkingProgress.set({ running: true, percent: 0, label: `Checking chapter ${$currentChapter}` });
    for (let i = 0; i < verses.length; i++) {
      const v = verses[i];
      try {
        const findings = await bridge.runVerseChecks($currentChapter, v, ["local", "greekroom"]);
        findingsByVerse.update((map) => ({ ...map, [v]: findings }));
      } catch (e) {
        console.error(`check failed for verse ${v}`, e);
      }
      checkingProgress.set({
        running: i < verses.length - 1,
        percent: Math.round(((i + 1) / verses.length) * 100),
        label: `Checking chapter ${$currentChapter}`,
      });
    }
    if (!$selectedVerse && verses.length > 0) selectedVerse.set(verses[0]);
  }

  function selectVerse(v: string) {
    selectedVerse.set(v);
  }

  function gotoVerse(v: string) {
    if ($verseNums.includes(v)) selectedVerse.set(v);
  }

  let settingsOpen = false;
  let exportOpen = false;

  $: allApproved = $verseNums.length > 0 && $approvedCount === $verseNums.length;
</script>

<div class="frame">
  {#if !opened}
    <ImportScreen onOpened={handleOpened} />
  {/if}

  <TopBar
    onOpenSettings={() => (settingsOpen = true)}
    onOpenExport={() => (exportOpen = true)}
    onGotoVerse={gotoVerse}
    exportEnabled={allApproved}
  />

  {#if $checkingProgress.running}
    <div class="progress-row">
      <div class="spin" />
      <span>{$checkingProgress.label} — {$checkingProgress.percent}%</span>
      <div class="track"><div class="fill" style="width:{$checkingProgress.percent}%" /></div>
    </div>
  {/if}

  <div class="body">
    <div class="editor-col">
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

  {#if settingsOpen}
    <div class="modal-overlay">
      <div class="modal">
        <p>Settings modal — wire SettingsModal.svelte here (AI provider pane already calls bridge.getSettings/setSettings).</p>
        <button on:click={() => (settingsOpen = false)}>Close</button>
      </div>
    </div>
  {/if}

  {#if exportOpen}
    <div class="modal-overlay">
      <div class="modal">
        <p>Export modal — aligned / non-aligned USFM export goes here once a real exporter exists in BridgeEngine.</p>
        <button on:click={() => (exportOpen = false)}>Close</button>
      </div>
    </div>
  {/if}
</div>

<style>
  .frame { width: 100vw; height: 100vh; background: var(--bg); display: flex; flex-direction: column; position: relative; overflow: hidden; }
  .progress-row { height: 32px; background: var(--surface-2); border-bottom: 1px solid var(--border); display: flex; align-items: center; gap: 10px; padding: 0 16px; font-size: 11px; color: var(--text-2); flex-shrink: 0; }
  .spin { width: 12px; height: 12px; border-radius: 50%; border: 2px solid var(--accent-bg); border-top-color: var(--accent); animation: spin 0.8s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .track { width: 160px; height: 6px; background: #EEF0F3; border-radius: 4px; overflow: hidden; }
  .fill { height: 100%; background: var(--accent); transition: width 0.3s; }
  .body { flex: 1; display: flex; overflow: hidden; }
  .editor-col { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
  .statusbar { height: 28px; background: var(--surface); border-top: 1px solid var(--border); display: flex; align-items: center; padding: 0 16px; gap: 16px; font-size: 11px; color: var(--text-2); flex-shrink: 0; }
  .grow { flex: 1; }
  .modal-overlay { position: absolute; inset: 0; background: rgba(15, 20, 26, 0.45); display: flex; align-items: center; justify-content: center; z-index: 30; }
  .modal { width: 420px; background: var(--surface); border-radius: 14px; padding: 22px; font-size: 13px; }
</style>
