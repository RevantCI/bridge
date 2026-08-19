<script lang="ts">
  import { bridge } from "../api/bridgeClient";
  import { project } from "../stores";

  export let onClose: () => void;

  let exporting = false;
  let resultMessage = "";
  let errorMessage = "";

  async function doExport(kind: "aligned" | "nonAligned") {
    exporting = true;
    resultMessage = "";
    errorMessage = "";
    try {
      const bookId = $project?.bookId ?? "export";
      const defaultName = kind === "aligned" ? `${bookId}-aligned.json` : `${bookId}.usfm`;
      const path = await bridge.pickSavePath(defaultName);
      if (!path) {
        exporting = false;
        return;
      }
      const result =
        kind === "aligned" ? await bridge.exportAligned(path) : await bridge.exportNonAligned(path);
      resultMessage = `Wrote ${result.chapters} chapter(s) to ${result.path}`;
    } catch (e) {
      errorMessage = e instanceof Error ? e.message : String(e);
    } finally {
      exporting = false;
    }
  }
</script>

<div class="modal-overlay">
  <div class="modal">
    <h2>Export project</h2>
    <p class="sub">Choose what to export. You'll be asked where to save it.</p>

    <button class="export-opt" on:click={() => doExport("aligned")} disabled={exporting}>
      <div class="t">Aligned data</div>
      <div class="d">Full JSON export: verse text, word-alignment groups, and recorded QA decisions for every chapter. Nothing simplified — this is the project's native alignment data.</div>
    </button>

    <button class="export-opt" on:click={() => doExport("nonAligned")} disabled={exporting}>
      <div class="t">Non-aligned data (simplified USFM)</div>
      <div class="d">Verse text only, with basic \id / \c / \v markers. Note: this is a simplified reconstruction — footnotes, section headers, and poetry markup from the original file are not preserved.</div>
    </button>

    {#if exporting}<p class="status">Writing…</p>{/if}
    {#if resultMessage}<p class="status success">{resultMessage}</p>{/if}
    {#if errorMessage}<p class="status error">{errorMessage}</p>{/if}

    <div class="modal-actions">
      <button class="btn ghost" on:click={onClose}>Close</button>
    </div>
  </div>
</div>

<style>
  .modal-overlay { position: absolute; inset: 0; background: rgba(15, 20, 26, 0.45); display: flex; align-items: center; justify-content: center; z-index: 30; }
  .modal { width: 460px; background: var(--surface); border-radius: 14px; padding: 22px; }
  h2 { font-size: 15px; margin: 0 0 6px; color: var(--text); }
  .sub { font-size: 12px; color: var(--text-2); margin: 0 0 18px; }
  .export-opt { width: 100%; text-align: left; border: 1px solid var(--border); border-radius: 10px; padding: 12px 14px; margin-bottom: 10px; background: var(--surface); cursor: pointer; display: block; }
  .export-opt:hover { border-color: var(--accent); }
  .export-opt:disabled { opacity: 0.6; cursor: not-allowed; }
  .t { font-size: 13px; font-weight: 700; color: var(--text); }
  .d { font-size: 11px; color: var(--text-2); margin-top: 2px; line-height: 1.5; }
  .status { font-size: 11px; margin: 8px 0 0; }
  .status.success { color: var(--success); }
  .status.error { color: var(--danger); }
  .modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 14px; }
  .btn { font-size: 12px; font-weight: 600; padding: 7px 14px; border-radius: 6px; border: 1px solid var(--border-strong); background: var(--surface); color: var(--text); cursor: pointer; }
  .btn.ghost { background: transparent; }
</style>
