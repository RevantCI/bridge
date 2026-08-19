<script lang="ts">
  import { bridge } from "../api/bridgeClient";
  import { project, currentChapter, verseNums, verseTexts } from "../stores";

  export let onOpened: () => void;

  let dragOver = false;
  let error: string | null = null;
  let loading = false;

  async function openPath(path: string) {
    loading = true;
    error = null;
    try {
      const info = await bridge.openProject(path);
      project.set(info);
      const firstChapter = info.chapters[0] ?? "1";
      currentChapter.set(firstChapter);
      const { verses } = await bridge.chapterVerses(firstChapter);
      verseNums.set(verses);
      const texts: Record<string, string> = {};
      for (const v of verses) {
        const data = await bridge.getVerse(firstChapter, v);
        texts[v] = data.text;
      }
      verseTexts.set(texts);
      onOpened();
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      loading = false;
    }
  }

  async function browseFolder() {
    const path = await bridge.pickProjectFolder();
    if (path) await openPath(path);
  }

  function handleDrop(e: DragEvent) {
    e.preventDefault();
    dragOver = false;
    // Tauri's webview receives OS file drop events separately from the
    // browser DragEvent API on some platforms; wiring the real path from
    // a native drop requires the @tauri-apps/api `onDragDropEvent` listener
    // rather than e.dataTransfer, which Tauri's webview does not populate
    // with real filesystem paths for security reasons. Left as a follow-up
    // — browseFolder() above is the reliable path today.
    error = "Drag-and-drop needs the native Tauri file-drop listener — use Browse for now.";
  }
</script>

<div class="import-overlay">
  <div class="stack">
    <!-- svelte-ignore a11y-no-static-element-interactions -->
    <div
      class="dropzone"
      class:dragover={dragOver}
      role="button"
      tabindex="0"
      on:dragover|preventDefault={() => (dragOver = true)}
      on:dragleave={() => (dragOver = false)}
      on:drop={handleDrop}
    >
      <h2>Open a project</h2>
      <p>Drag a translationCore project folder here, or browse to select one.</p>
      <div class="btn-row">
        <button class="btn primary" on:click={browseFolder} disabled={loading}>
          {loading ? "Opening…" : "Browse for folder…"}
        </button>
      </div>
      {#if error}
        <p class="error">{error}</p>
      {/if}
    </div>
  </div>
</div>

<style>
  .import-overlay { position: absolute; inset: 0; background: var(--bg); display: flex; align-items: center; justify-content: center; z-index: 20; }
  .stack { display: flex; flex-direction: column; align-items: center; }
  .dropzone { width: 460px; border: 2px dashed var(--border-strong); border-radius: 16px; background: var(--surface); padding: 40px; text-align: center; }
  .dropzone.dragover { border-color: var(--accent); background: var(--accent-bg); }
  h2 { font-size: 15px; margin: 0 0 6px; color: var(--text); font-weight: 700; }
  p { font-size: 12px; color: var(--text-2); margin: 0 0 18px; }
  .btn-row { display: flex; gap: 8px; }
  .btn { font-size: 12px; font-weight: 600; padding: 8px 12px; border-radius: 6px; border: 1px solid var(--border-strong); background: var(--surface); color: var(--text); cursor: pointer; flex: 1; }
  .btn.primary { background: var(--accent); border-color: var(--accent); color: #fff; }
  .btn:disabled { opacity: 0.6; cursor: not-allowed; }
  .error { color: var(--danger); font-size: 11px; margin-top: 10px; }
</style>
