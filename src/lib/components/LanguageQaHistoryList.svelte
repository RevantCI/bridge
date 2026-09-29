<script lang="ts">
  // Read-only decision history for one verse's Language QA findings, or one
  // finding. It loads in the background behind a placeholder, so opening it
  // never waits on the engine.
  import { onMount } from "svelte";
  import { bridge } from "../api/bridgeClient";
  import type { LanguageQaHistoryEntry } from "../types/languageQa";

  export let projectPath: string;
  export let chapter: string;
  export let verse: string;
  export let findingId: string | undefined = undefined;

  let entries: LanguageQaHistoryEntry[] | null = null;
  let error = "";

  const decisionLabels: Record<string, string> = {
    accepted: "Used a suggestion",
    ignored: "Ignored",
    rejected: "Marked as false positive",
  };

  onMount(() => {
    let live = true;
    bridge.languageQaHistory(projectPath, chapter, verse, findingId).then(
      (result) => { if (live) entries = result.entries; },
      (cause: unknown) => { if (live) error = cause instanceof Error ? cause.message : String(cause); },
    );
    return () => { live = false; };
  });
</script>

{#if error}
  <p class="history-error" role="alert">{error}</p>
{:else if entries === null}
  <p class="history-muted">Loading history…</p>
{:else if entries.length === 0}
  <p class="history-muted">No decisions recorded yet.</p>
{:else}
  <ol class="history" aria-label="Language QA decision history">
    {#each entries as entry (entry.seq)}
      <li>
        <span class="decision">{decisionLabels[entry.decision] ?? entry.decision}</span>
        {#if entry.chosenSuggestion}<span class="chosen">→ “{entry.chosenSuggestion}”</span>{/if}
        {#if !findingId && entry.originalText}<span class="flagged">“{entry.originalText}”</span>{/if}
        <span class="meta">
          {new Date(entry.recordedAt).toLocaleString()}
          {#if entry.revision !== null} · revision {entry.revision}{/if}
          {#if entry.ruleId} · {entry.ruleId}{/if}
        </span>
      </li>
    {/each}
  </ol>
{/if}

<style>
  .history { margin: 6px 0; padding-left: 18px; }
  .history li { padding: 4px 0; border-bottom: 0; }
  .decision { font-weight: 600; }
  .chosen, .flagged { margin-left: 6px; overflow-wrap: anywhere; }
  .meta { display: block; color: var(--text-3); font-size: var(--fs-2xs); }
  .history-muted { color: var(--text-3); margin: 6px 0; }
  .history-error { color: var(--danger); margin: 6px 0; }
</style>
