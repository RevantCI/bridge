<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import { bridge } from "../api/bridgeClient";
  import type { LanguageQaFinding, LanguageQaStatus } from "../types/languageQa";
  import { languageQaFindingsByVerse, verseKey } from "../stores";

  export let projectPath: string;
  export let onNavigate: (book: string, chapter: string, verse: string) => void;

  let expanded = false;
  let status: LanguageQaStatus | null = null;
  let error = "";
  let offset = 0;
  let sequence = 0;
  let disposed = false;
  let busy = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const detectionLabels: Record<string, string> = {
    metadata: "Language supplied by the project.",
    "script-suggestion": "Tamil suggested from the script; the project has no declared language.",
    "metadata-conflict": "The project language and detected script disagree. Only common checks are enabled.",
    "mixed-script": "The sample contains mixed scripts. Only common checks are enabled.",
    undetermined: "The language could not be determined. Only common checks are enabled.",
  };

  // Collapsed used to fetch limit=0 (count only, no finding objects) since
  // the panel itself only ever displayed the total. Now VerseList's inline
  // double-underline needs real finding data regardless of whether the
  // panel is open, so collapsed still fetches a real page -- just not the
  // 50-per-page the panel's own Previous/Next pagination text assumes when
  // expanded, which must stay exactly as before or that text goes wrong.
  function updateInlineStore(next: LanguageQaStatus): void {
    const byVerse: Record<string, LanguageQaFinding[]> = {};
    for (const finding of next.findings) {
      if (finding.rule !== "terminology.deprecated-form") continue;
      const key = verseKey(finding.chapter, finding.verse);
      (byVerse[key] ??= []).push(finding);
    }
    languageQaFindingsByVerse.set(byVerse);
  }

  async function refresh(): Promise<void> {
    if (disposed || busy) return;
    if (timer) clearTimeout(timer);
    const ticket = ++sequence;
    const path = projectPath;
    busy = true;
    try {
      const next = await bridge.languageQaStatus(path, offset, expanded ? 50 : 100);
      if (disposed || ticket !== sequence || path !== projectPath || next.projectPath !== path) return;
      if (status && next.generation !== status.generation && offset !== 0) {
        offset = 0;
        // Fetch page one before presenting a different generation's rows.
        status = { ...next, findings: [], offset: 0 };
        return;
      }
      status = next;
      updateInlineStore(next);
      error = "";
    } catch (cause) {
      if (!disposed && ticket === sequence) {
        error = cause instanceof Error ? cause.message : String(cause);
        status = null;
      }
    } finally {
      busy = false;
      if (!disposed) timer = setTimeout(() => void refresh(), expanded ? 2000 : 5000);
    }
  }

  async function togglePause(): Promise<void> {
    if (busy) return;
    busy = true;
    ++sequence;
    if (timer) clearTimeout(timer);
    const ticket = sequence;
    const path = projectPath;
    try {
      const next = await bridge.languageQaPause(path, status?.state !== "paused");
      if (disposed || sequence !== ticket || projectPath !== path || next.projectPath !== path) return;
      status = next;
      offset = 0;
      error = "";
    } catch (cause) {
      error = cause instanceof Error ? cause.message : String(cause);
    } finally {
      busy = false;
      if (!disposed) void refresh();
    }
  }

  function toggle(): void {
    expanded = !expanded;
    offset = 0;
    void refresh();
  }

  function page(delta: number): void {
    offset = Math.max(0, offset + delta);
    void refresh();
  }

  onMount(() => { void refresh(); });
  onDestroy(() => {
    disposed = true;
    ++sequence;
    if (timer) clearTimeout(timer);
  });
</script>

<aside class="language-qa" aria-label="Language QA">
  {#if expanded}
    <section id="language-qa-results" aria-label="Language QA results">
      <div class="heading">
        <h2>Language QA · Offline</h2>
        <button on:click={toggle} aria-label="Close Language QA">Close</button>
      </div>
      <p>Checks run automatically for the open book and after edits.</p>
      {#if error}<p role="alert">{error}</p>{/if}
      {#if status}
        <p>
          {status.language?.language === "tam" ? "Tamil" : status.language?.language ?? "Detecting language"}
          {#if status.language} · {status.language.script.toLowerCase()} script{/if}
        </p>
        {#if status.language}<p>{detectionLabels[status.language.basis] ?? ""}</p>{/if}
        <p>{status.language?.message ?? (status.state === "paused" ? "Checks paused. Resume when ready." : "Preparing language checks…")}</p>
        <p>
          {status.state} · {status.completedChapters ?? 0}/{status.totalChapters ?? 0} chapters
          · {status.totalFindings} review candidates
        </p>
        {#if status.error}<p role="alert">{status.error}</p>{/if}
        <button on:click={togglePause} disabled={busy || status.state === "failed"}>
          {status.state === "paused" ? "Resume checks" : "Pause checks"}
        </button>
        {#if status.incomplete}
          <p class="notice">Coverage incomplete. Omitted text has not passed QA.</p>
        {/if}
        {#if status.limitations.length}
          <details>
            <summary>Coverage details ({status.limitations.length})</summary>
            <ul>{#each status.limitations as limitation}<li>{limitation}</li>{/each}</ul>
          </details>
        {/if}
        {#if status.state === "completed" && !status.totalFindings}
          <p>No candidates found by the enabled checks. This is not publication approval.</p>
        {/if}
        <ol aria-label="Language QA findings" start={status.offset + 1}>
          {#each status.findings as finding (finding.id)}
            <li>
              <button on:click={() => onNavigate(finding.book, finding.chapter, finding.verse)}>
                {finding.book.toUpperCase()} {finding.chapter}:{finding.verse}
              </button>
              <span class="severity">{finding.severity}</span>
              <p class="evidence">{finding.originalText}</p>
              <p>{finding.message}</p>
            </li>
          {/each}
        </ol>
        {#if status.totalFindings > 50}
          <div class="paging">
            <button on:click={() => page(-50)} disabled={busy || offset === 0}>Previous</button>
            <span>{status.offset + 1}–{Math.min(status.offset + 50, status.totalFindings)} of {status.totalFindings}</span>
            <button on:click={() => page(50)} disabled={busy || offset + 50 >= status.totalFindings}>Next</button>
          </div>
        {/if}
        <p class="muted">{status.coverage} {status.storage}</p>
      {/if}
    </section>
  {/if}
  <button class="launcher" on:click={toggle} aria-expanded={expanded} aria-controls="language-qa-results">
    Language QA · {error ? "unavailable" : status?.state ?? "starting"}
    {#if status?.totalFindings} · {status.totalFindings}{/if}
  </button>
</aside>

<style>
  .language-qa { position: fixed; bottom: 40px; right: 16px; z-index: 45; font-size: 12px; }
  section { width: min(560px, calc(100vw - 32px)); max-height: min(580px, calc(100vh - 150px)); overflow: auto; padding: 16px; background: var(--surface); color: var(--text); border: 1px solid var(--border); border-radius: 8px; box-shadow: 0 4px 24px #0003; margin-bottom: 8px; }
  .heading, .paging { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
  h2 { font-size: 15px; margin: 0; }
  button { cursor: pointer; border: 1px solid var(--border); border-radius: 4px; padding: 4px 8px; background: var(--surface); color: inherit; }
  button:disabled { opacity: .5; cursor: default; }
  .launcher { display: block; margin-left: auto; }
  p { margin: 8px 0; overflow-wrap: anywhere; }
  ol { padding-left: 22px; }
  li { padding: 8px 0; border-bottom: 1px solid var(--border, #ddd); }
  .evidence { font-size: 16px; white-space: pre-wrap; }
  .severity { margin-left: 8px; }
  .notice { font-weight: 600; }
  .muted { opacity: .75; }
</style>
