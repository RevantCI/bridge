<script lang="ts">
  import { engineLog } from "../stores";
  import type { EngineLogEntry } from "../api/bridgeClient";

  export let onClose: () => void;

  let filter: "all" | "warn" | "error" = "all";

  $: visible = ([...$engineLog] as EngineLogEntry[])
    .reverse()
    .filter((entry) => filter === "all" || entry.level === filter);

  function formatTime(tsMs: number): string {
    return new Date(tsMs).toLocaleTimeString(undefined, { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" });
  }
</script>

<div class="modal-overlay">
  <div class="diagnostics-modal">
    <button class="close-btn" on:click={onClose} aria-label="Close diagnostics">✕</button>
    <div class="header">
      <div class="title">Engine diagnostics</div>
      <p class="desc">
        Sidecar lifecycle events (start, restart, crash), request timeouts, and the Python engine's
        own error output. If the engine ever restarts mid-session, reopen your project — its
        in-memory state does not carry over.
      </p>
      <div class="filters">
        <button class:active={filter === "all"} on:click={() => (filter = "all")}>All ({$engineLog.length})</button>
        <button class:active={filter === "warn"} on:click={() => (filter = "warn")}>Warnings</button>
        <button class:active={filter === "error"} on:click={() => (filter = "error")}>Errors</button>
      </div>
    </div>
    <div class="log-body">
      {#if visible.length === 0}
        <p class="muted">No {filter === "all" ? "" : filter} entries yet.</p>
      {:else}
        {#each visible as entry, index (index)}
          <div class="entry {entry.level}">
            <span class="time">{formatTime(entry.ts_ms)}</span>
            <span class="level-badge {entry.level}">{entry.level}</span>
            <span class="message">{entry.message}</span>
          </div>
        {/each}
      {/if}
    </div>
  </div>
</div>

<style>
  .modal-overlay { position: absolute; inset: 0; background: rgba(15, 20, 26, 0.45); display: flex; align-items: center; justify-content: center; z-index: 30; }
  .diagnostics-modal { width: 720px; height: 520px; background: var(--surface); border-radius: 14px; display: flex; flex-direction: column; overflow: hidden; position: relative; }
  .close-btn { position: absolute; top: 10px; right: 10px; z-index: 2; width: 28px; height: 28px; border-radius: 6px; border: none; background: transparent; color: var(--text-2); font-size: 14px; cursor: pointer; }
  .close-btn:hover { background: var(--surface-2); }
  .header { padding: 20px 24px 12px; border-bottom: 1px solid var(--border); flex-shrink: 0; }
  .title { font-size: 14px; font-weight: 700; color: var(--text); margin-bottom: 4px; }
  .desc { font-size: 11px; line-height: 1.5; color: var(--text-2); margin: 0 0 12px; max-width: 560px; }
  .filters { display: flex; gap: 6px; }
  .filters button { font-size: 10px; font-weight: 650; padding: 5px 10px; border-radius: 999px; border: 1px solid var(--border-strong); background: var(--surface-2); color: var(--text-2); cursor: pointer; }
  .filters button.active { background: var(--accent-bg); color: var(--accent); border-color: var(--accent); }
  .log-body { flex: 1; overflow-y: auto; padding: 8px 24px 20px; font-family: ui-monospace, "SF Mono", Consolas, monospace; }
  .muted { font-size: 12px; color: var(--text-3); padding: 12px 0; }
  .entry { display: flex; align-items: baseline; gap: 8px; padding: 5px 0; border-bottom: 1px solid var(--border); font-size: 11px; }
  .entry:last-child { border-bottom: none; }
  .time { color: var(--text-3); flex-shrink: 0; }
  .level-badge { flex-shrink: 0; text-transform: uppercase; font-size: 9px; font-weight: 700; padding: 2px 6px; border-radius: 4px; background: var(--surface-2); color: var(--text-2); }
  .level-badge.warn { color: var(--warning); background: var(--warning-bg); }
  .level-badge.error { color: var(--danger); background: var(--danger-bg); }
  .message { color: var(--text); overflow-wrap: anywhere; white-space: pre-wrap; }
  .entry.error .message { color: var(--danger); }
</style>
