<script lang="ts">
  import type { BookProgressEntry, ProjectReport, CoverageState } from "../types/finding";

  export let projectName: string;
  export let subtitle = "";
  export let books: BookProgressEntry[];
  export let loading: boolean;
  export let error: string;
  export let onSelectBook: (path: string) => void;
  export let onRetry: () => void;

  // Project-level QA report for whichever book is currently open — see
  // BridgeEngine.build_project_report(). null while loading/unavailable
  // (e.g. no book open yet), in which case the report section just
  // doesn't render rather than showing an empty shell.
  export let report: ProjectReport | null = null;
  export let reportLoading = false;
  export let reportError = "";
  export let onNavigateToFinding: (chapter: string, verse: string) => void = () => {};

  function percent(part: number, total: number): number {
    if (total <= 0) return 0;
    return Math.round((part / total) * 100);
  }

  const COVERAGE_ORDER: CoverageState[] = ["ISSUE", "REVIEW_REQUIRED", "NOT_CHECKED", "PASS"];
  const COVERAGE_LABEL: Record<CoverageState, string> = {
    PASS: "Pass", ISSUE: "Issue", REVIEW_REQUIRED: "Review required", NOT_CHECKED: "Not checked",
  };
  const COVERAGE_CLASS: Record<CoverageState, string> = {
    PASS: "pass", ISSUE: "issue", REVIEW_REQUIRED: "review", NOT_CHECKED: "not-checked",
  };
</script>

<div class="screen">
  <div class="header">
    <div class="eyebrow">PROJECT</div>
    <h1>{projectName}</h1>
    {#if subtitle}<p class="intro">{subtitle}</p>{/if}
  </div>

  {#if reportLoading}
    <div class="report-area"><p class="empty">Loading report…</p></div>
  {:else if reportError}
    <div class="report-area"><p class="empty">Could not load report: {reportError}</p></div>
  {:else if report}
    <div class="report-area" aria-label="Current book QA report">
      <div class="gate" class:ready={report.publicationGate.readyForHumanPublicationSignoff}>
        {#if report.publicationGate.readyForHumanPublicationSignoff}
          ✓ No blocking issues detected in {report.bookId?.toUpperCase()} — advisory only, not a translation-quality signoff.
        {:else}
          {report.publicationGate.criticalFindings} critical · {report.publicationGate.highFindings} high ·
          {report.publicationGate.staleAIReviews} stale · {report.publicationGate.openDiscussions} discussion(s) open in {report.bookId?.toUpperCase()}
        {/if}
      </div>

      <div class="coverage-bar" role="img" aria-label="Verse checking coverage">
        {#each COVERAGE_ORDER as state (state)}
          {#if report.coverage.verses.counts[state] > 0}
            <div
              class="coverage-seg {COVERAGE_CLASS[state]}"
              style="width:{percent(report.coverage.verses.counts[state], report.coverage.verses.totalVerses)}%"
              title="{COVERAGE_LABEL[state]}: {report.coverage.verses.counts[state]}"
            />
          {/if}
        {/each}
      </div>
      <div class="coverage-legend">
        {#each COVERAGE_ORDER as state (state)}
          <span class="legend-item"><i class={COVERAGE_CLASS[state]} />{COVERAGE_LABEL[state]} {report.coverage.verses.counts[state]}</span>
        {/each}
        <span class="legend-percent">{report.coverage.verses.checkedPercent}% checked</span>
      </div>

      {#if report.exceptionQueue.length > 0}
        <div class="exceptions" aria-label="Verses needing attention">
          {#each report.exceptionQueue.slice(0, 25) as row (row.chapter + ':' + row.verse)}
            <button class="exception-row" on:click={() => onNavigateToFinding(row.chapter, row.verse)}>
              <span class="ref">{report.bookId?.toUpperCase()} {row.chapter}:{row.verse}</span>
              {#if row.critical}<span class="pill critical">{row.critical} critical</span>{/if}
              {#if row.high}<span class="pill high">{row.high} high</span>{/if}
              {#if row.discussions}<span class="pill discussion">{row.discussions} discussion</span>{/if}
              {#if row.wordAlignment === "invalid"}<span class="pill invalid">alignment invalid</span>{/if}
              {#if row.summary}<span class="summary">{row.summary}</span>{/if}
            </button>
          {/each}
          {#if report.exceptionQueue.length > 25}
            <p class="more">+ {report.exceptionQueue.length - 25} more</p>
          {/if}
        </div>
      {:else}
        <p class="empty">No verses currently need attention in this book.</p>
      {/if}
    </div>
  {/if}

  <div class="list-area">
    {#if loading}
      <p class="empty">Loading book progress…</p>
    {:else if error}
      <div class="error-row">
        <span>Could not load book progress: {error}</span>
        <button class="small-button" on:click={onRetry}>Retry</button>
      </div>
    {:else if books.length === 0}
      <p class="empty">No books found in this project.</p>
    {:else}
      <section class="books" aria-label="Books in this project">
        {#each books as book (book.path)}
          <article class:missing={book.missing} class="book-row">
            <div class="book-badge">{book.bookId?.toUpperCase() || "?"}</div>
            <div class="book-copy">
              <strong>{book.bookName || book.bookId || "Unnamed book"}</strong>
              {#if book.missing}
                <span class="note">Project folder is missing</span>
              {:else if book.lazy || book.progress === null}
                <span class="note">Not yet opened</span>
              {:else if book.progress.checkedChapterCount === 0}
                <span class="note">Not yet checked</span>
              {:else}
                <div class="bars">
                  <div class="bar-row">
                    <span class="bar-label">Reviewed {book.progress.reviewedVerseCount}/{book.progress.verseCount}</span>
                    <div class="track"><div class="fill" style="width:{percent(book.progress.reviewedVerseCount, book.progress.verseCount)}%" /></div>
                  </div>
                  <div class="bar-row">
                    <span class="bar-label">AI-checked {book.progress.checkedChapterCount}/{book.progress.chapterCount} chapters</span>
                    <div class="track"><div class="fill checked" style="width:{percent(book.progress.checkedChapterCount, book.progress.chapterCount)}%" /></div>
                  </div>
                </div>
                {#if book.progress.updatedAt}
                  <small>Updated {new Date(book.progress.updatedAt).toLocaleString()}</small>
                {/if}
              {/if}
            </div>
            <button class="small-button primary" on:click={() => onSelectBook(book.path)} disabled={book.missing}>Open</button>
          </article>
        {/each}
      </section>
    {/if}
  </div>
</div>

<style>
  .screen { flex: 1; display: flex; flex-direction: column; overflow: hidden; background: var(--surface); }
  .header { flex-shrink: 0; padding: 28px 40px 18px; border-bottom: 1px solid var(--border); }
  .list-area { flex: 1; overflow: auto; padding: 20px 40px; }
  .header, .list-area { max-width: 900px; width: 100%; margin: 0 auto; box-sizing: border-box; }
  .eyebrow { color: var(--accent); font-size: 10px; letter-spacing: .12em; font-weight: 800; margin-bottom: 8px; }
  h1 { font-size: 22px; line-height: 1.2; margin: 0; color: var(--text); }
  .intro { color: var(--text-2); font-size: 13px; line-height: 1.55; margin: 10px 0 0; }
  .empty { background: var(--surface-2); color: var(--text-2); border-radius: 8px; padding: 14px; font-size: 11px; margin: 0; }
  .error-row { display: flex; align-items: center; justify-content: space-between; gap: 10px; background: var(--surface-2); color: var(--danger); border-radius: 8px; padding: 14px; font-size: 11px; }
  .report-area { max-width: 900px; width: 100%; margin: 0 auto; box-sizing: border-box; padding: 16px 40px 0; }
  .gate { border-radius: 8px; padding: 10px 14px; font-size: 11px; font-weight: 600; background: var(--danger-bg); color: var(--danger); margin-bottom: 12px; }
  .gate.ready { background: var(--gr-bg); color: var(--gr); }
  .coverage-bar { display: flex; width: 100%; height: 10px; border-radius: 5px; overflow: hidden; background: var(--surface-2); }
  .coverage-seg { height: 100%; }
  .coverage-seg.pass { background: var(--gr); }
  .coverage-seg.issue { background: var(--danger); }
  .coverage-seg.review { background: var(--warning); }
  .coverage-seg.not-checked { background: var(--border-strong); }
  .coverage-legend { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; margin: 8px 0 14px; font-size: 10px; color: var(--text-2); }
  .legend-item { display: inline-flex; align-items: center; gap: 5px; }
  .legend-item i { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
  .legend-item i.pass { background: var(--gr); }
  .legend-item i.issue { background: var(--danger); }
  .legend-item i.review { background: var(--warning); }
  .legend-item i.not-checked { background: var(--border-strong); }
  .legend-percent { margin-left: auto; font-weight: 700; color: var(--text); }
  .exceptions { border: 1px solid var(--border); border-radius: 10px; overflow: hidden; }
  .exception-row { width: 100%; text-align: left; display: flex; align-items: center; gap: 8px; padding: 9px 12px; border: 0; border-bottom: 1px solid var(--border); background: var(--surface); cursor: pointer; font: inherit; }
  .exception-row:last-child { border-bottom: 0; }
  .exception-row:hover { background: var(--surface-2); }
  .exception-row .ref { font-weight: 700; font-size: 11px; color: var(--text); flex-shrink: 0; }
  .exception-row .summary { color: var(--text-2); font-size: 10px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .pill { font-size: 9px; font-weight: 700; padding: 2px 7px; border-radius: 999px; flex-shrink: 0; }
  .pill.critical { background: var(--danger-bg); color: var(--danger); }
  .pill.high { background: var(--warning-bg); color: var(--warning); }
  .pill.discussion { background: var(--accent-bg); color: var(--accent); }
  .pill.invalid { background: var(--surface-2); color: var(--text-2); }
  .more { color: var(--text-2); font-size: 10px; margin: 8px 2px 0; }
  .books { border: 1px solid var(--border); border-radius: 10px; }
  .book-row { min-height: 66px; display: flex; align-items: center; gap: 11px; padding: 9px 11px; border-bottom: 1px solid var(--border); }
  .book-row:last-child { border-bottom: 0; }
  .book-row.missing { background: #fff9ed; }
  .book-badge { width: 38px; height: 38px; display: grid; place-items: center; border-radius: 8px; background: var(--accent-bg); color: var(--accent); font-size: 10px; font-weight: 800; flex-shrink: 0; }
  .book-copy { display: flex; flex-direction: column; min-width: 0; flex: 1; gap: 3px; }
  .book-copy strong { font-size: 12px; color: var(--text); }
  .book-copy .note { color: var(--text-2); font-size: 10px; }
  .book-copy small { color: var(--text-2); font-size: 9px; }
  .bars { display: flex; flex-direction: column; gap: 4px; margin: 2px 0; }
  .bar-row { display: flex; align-items: center; gap: 8px; }
  .bar-label { color: var(--text-2); font-size: 9px; width: 175px; flex-shrink: 0; }
  .track { width: 100%; height: 6px; background: #EEF0F3; border-radius: 4px; overflow: hidden; }
  .fill { height: 100%; background: var(--accent); }
  .fill.checked { background: var(--gr); }
  .small-button { border: 1px solid var(--border-strong); border-radius: 6px; background: var(--surface); color: var(--text); padding: 6px 10px; cursor: pointer; font-size: 10px; flex-shrink: 0; }
  .small-button.primary { border-color: var(--accent); color: var(--accent); }
  .small-button:disabled { opacity: .55; cursor: not-allowed; }
  @media (max-width: 760px) {
    .header, .list-area { padding-left: 20px; padding-right: 20px; }
    .bar-row { flex-direction: column; align-items: stretch; gap: 2px; }
    .bar-label { width: auto; }
  }
</style>
