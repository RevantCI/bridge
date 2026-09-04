<script lang="ts">
  import type { BookProgressEntry, ProjectReport, CoverageState } from "../types/finding";

  export let projectName: string;
  export let subtitle = "";
  export let books: BookProgressEntry[];
  export let loading: boolean;
  export let error: string;
  export let onSelectBook: (path: string) => void;
  export let onPreviewBook: (path: string) => void = () => {};
  export let onRetry: () => void;

  // Project-level QA report for whichever book is currently open — see
  // BridgeEngine.build_project_report(). null while loading/unavailable
  // (e.g. no book open yet), in which case the report section just
  // doesn't render rather than showing an empty shell.
  export let report: ProjectReport | null = null;
  export let reportLoading = false;
  export let reportError = "";
  export let onNavigateToFinding: (chapter: string, verse: string) => void = () => {};
  export let advancedMode = false;
  export let onOpenSemanticValidation: () => void = () => {};
  export let onRequestAdvancedMode: () => void = () => {};

  let bookSearch = "";

  $: normalizedBookSearch = bookSearch.trim().toLocaleLowerCase();
  $: filteredBooks = books.filter((book) => {
    if (!normalizedBookSearch) return true;
    return `${book.bookId ?? ""} ${book.bookName ?? ""}`
      .toLocaleLowerCase()
      .includes(normalizedBookSearch);
  });

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

  let expandedRows = new Set<string>();

  function toggleExpanded(key: string): void {
    const next = new Set(expandedRows);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    expandedRows = next;
  }

  // The report only carries the open book's code; its localized name (as
  // parsed from the source USFM's \h/\toc2 line at import — see
  // project_import.py) lives on the matching row in `books`.
  $: openBook = report
    ? books.find((book) => (book.bookId ?? "").toLowerCase() === (report!.bookId ?? "").toLowerCase())
    : undefined;
</script>

<div class="screen">
  <div class="header">
    <div class="header-left">
      <span class="eyebrow">PROJECT</span>
      <h1>{projectName}</h1>
      {#if subtitle}<span class="intro">· {subtitle}</span>{/if}
    </div>
    <div class="header-right">
      {#if report}
        <div class="book-heading" title={openBook?.bookName || report.bookId?.toUpperCase()}>
          <span class="book-native">{openBook?.bookName || report.bookId?.toUpperCase()}</span>
          {#if openBook?.bookName}<span class="book-code">({report.bookId?.toUpperCase()})</span>{/if}
        </div>
      {:else}
        <div class="book-heading" />
      {/if}
      <div class="validation-entry">
        <button
          class="validation-button"
          class:requires-advanced={!advancedMode}
          on:click={advancedMode ? onOpenSemanticValidation : onRequestAdvancedMode}
        >
          {advancedMode ? "Validate semantic mappings" : "Enable semantic validation"}
        </button>
        {#if !advancedMode}<small>Requires Manual reviewer mode</small>{/if}
      </div>
    </div>
  </div>

  <div class="panels">
    <aside class="left-panel" aria-label="Books in this project">
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
          <div class="book-tools">
            <label for="book-search">Find a book</label>
            <input id="book-search" type="search" bind:value={bookSearch} placeholder="Book name or code, for example Luke or LUK" />
            <span>{filteredBooks.length} of {books.length}</span>
          </div>
          <section class="books">
            {#each filteredBooks as book (book.path)}
              {@const previewed = (book.bookId ?? "").toLowerCase() === (report?.bookId ?? "").toLowerCase()}
              <div
                class:missing={book.missing}
                class:previewed
                class="book-row"
                role="button"
                tabindex={book.missing ? -1 : 0}
                aria-disabled={book.missing}
                on:click={() => !book.missing && onPreviewBook(book.path)}
                on:keydown={(e) => !book.missing && (e.key === "Enter" || e.key === " ") && (e.preventDefault(), onPreviewBook(book.path))}
              >
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
                        <span class="bar-label">Checked {book.progress.checkedChapterCount}/{book.progress.chapterCount} chapters</span>
                        <div class="track"><div class="fill checked" style="width:{percent(book.progress.checkedChapterCount, book.progress.chapterCount)}%" /></div>
                      </div>
                    </div>
                    {#if book.progress.updatedAt}
                      <small>Updated {new Date(book.progress.updatedAt).toLocaleString()}</small>
                    {/if}
                  {/if}
                </div>
                <button
                  class="small-button primary"
                  on:click|stopPropagation={() => onSelectBook(book.path)}
                  disabled={book.missing}
                >Open</button>
              </div>
            {:else}
              <p class="empty no-match">No books match “{bookSearch}”.</p>
            {/each}
          </section>
        {/if}
      </div>
    </aside>

    <main class="right-panel">
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
                {@const key = row.chapter + ":" + row.verse}
                {@const helps = row.helpsFindings ?? []}
                {@const tnCount = helps.filter((f) => f.tool === "translationNotes").length}
                {@const twCount = helps.filter((f) => f.tool === "translationWords").length}
                {@const detailCount = row.localFindings.length + helps.length}
                {@const hasDetail = detailCount > 0}
                <div class="exception-item">
                  <div class="exception-row-wrap">
                    <button class="exception-row" on:click={() => onNavigateToFinding(row.chapter, row.verse)}>
                      <span class="ref">{report.bookId?.toUpperCase()} {row.chapter}:{row.verse}</span>
                      {#if row.critical}<span class="pill critical">{row.critical} critical</span>{/if}
                      {#if row.high}<span class="pill high">{row.high} high</span>{/if}
                      {#if tnCount}<span class="pill tn">{tnCount} tN</span>{/if}
                      {#if twCount}<span class="pill tw">{twCount} tW</span>{/if}
                      {#if row.discussions}<span class="pill discussion">{row.discussions} discussion</span>{/if}
                      {#if row.wordAlignment === "invalid"}<span class="pill invalid">alignment invalid</span>{/if}
                      {#if row.summary}<span class="summary">{row.summary}</span>{/if}
                    </button>
                    {#if hasDetail}
                      <button
                        type="button"
                        class="expand-toggle"
                        aria-label={expandedRows.has(key) ? "Collapse findings" : `Show ${detailCount} finding(s)`}
                        aria-expanded={expandedRows.has(key)}
                        on:click={() => toggleExpanded(key)}
                      >{detailCount} finding{detailCount === 1 ? "" : "s"} {expandedRows.has(key) ? "▲" : "▼"}</button>
                    {/if}
                  </div>
                  {#if hasDetail && expandedRows.has(key)}
                    <div class="local-findings">
                      {#each row.localFindings as finding}
                        <div class="local-finding-row source-gr">
                          <span class="pill engine">{finding.engine}</span>
                          <span class="pill {finding.severity}">{finding.severity}</span>
                          <span class="local-explain">{finding.explanation}</span>
                        </div>
                      {/each}
                      {#each helps as finding}
                        <div class="local-finding-row source-{finding.tool === 'translationNotes' ? 'tn' : 'tw'}">
                          <span class="pill engine">{finding.tool === "translationNotes" ? "tN" : "tW"}</span>
                          <span class="pill {finding.severity}">{finding.severity}</span>
                          <span class="local-explain">{finding.explanation}</span>
                        </div>
                      {/each}
                    </div>
                  {/if}
                </div>
              {/each}
              {#if report.exceptionQueue.length > 25}
                <p class="more">+ {report.exceptionQueue.length - 25} more</p>
              {/if}
            </div>
          {:else}
            <p class="empty">No verses currently need attention in this book.</p>
          {/if}
        </div>
      {:else}
        <div class="report-area"><p class="empty">Open a book on the left to see its QA report here.</p></div>
      {/if}
    </main>
  </div>
</div>

<style>
  /* The report and book list form one document. Keeping overflow on only the
     inner book list made a long exception queue extend below the viewport with
     no reachable scrollbar. Now that the book list and the report live in
     their own side-by-side panels, each panel is its own scroll owner
     instead — the outer screen no longer scrolls at all. */
  .screen { flex: 1; min-height: 0; display: flex; flex-direction: column; overflow: hidden; background: var(--surface); }
  .header { flex-shrink: 0; padding: 12px 32px; border-bottom: 1px solid var(--border); display: flex; align-items: center; gap: 18px; box-sizing: border-box; }
  .header-left { flex: 0 0 560px; min-width: 0; display: flex; align-items: baseline; gap: 8px; overflow: hidden; }
  .panels { flex: 1; min-height: 0; display: flex; overflow: hidden; }
  .left-panel { width: 560px; flex-shrink: 0; overflow-y: auto; border-right: 1px solid var(--border); box-sizing: border-box; }
  .list-area { padding: 20px 24px; box-sizing: border-box; }
  .right-panel { flex: 1; min-width: 0; overflow-y: auto; box-sizing: border-box; }
  .header-right { flex: 1; min-width: 0; display: flex; align-items: center; justify-content: space-between; gap: 14px; }
  .book-heading { display: flex; align-items: baseline; gap: 6px; min-width: 0; font-weight: 700; color: var(--text); font-size: 14px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .book-heading .book-code { color: var(--text-2); font-size: 11px; font-weight: 600; flex-shrink: 0; }
  .eyebrow { color: var(--accent); font-size: 10px; letter-spacing: .12em; font-weight: 800; flex-shrink: 0; }
  h1 { font-size: 16px; line-height: 1.2; margin: 0; color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .intro { color: var(--text-2); font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .empty { background: var(--surface-2); color: var(--text-2); border-radius: 8px; padding: 14px; font-size: 11px; margin: 0; }
  .error-row { display: flex; align-items: center; justify-content: space-between; gap: 10px; background: var(--surface-2); color: var(--danger); border-radius: 8px; padding: 14px; font-size: 11px; }
  .report-area { box-sizing: border-box; padding: 20px 32px; max-width: 820px; }
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
  .exception-item { border-bottom: 1px solid var(--border); }
  .exception-item:last-child { border-bottom: 0; }
  .exception-row-wrap { display: flex; align-items: stretch; background: var(--surface); }
  .exception-row { flex: 1; min-width: 0; text-align: left; display: flex; align-items: center; flex-wrap: wrap; gap: 8px; padding: 9px 12px; border: 0; background: none; cursor: pointer; font: inherit; }
  .exception-row:hover { background: var(--surface-2); }
  .exception-row .ref { font-weight: 700; font-size: 11px; color: var(--text); flex-shrink: 0; }
  .exception-row .summary { color: var(--text-2); font-size: 10px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .pill { font-size: 9px; font-weight: 700; padding: 2px 7px; border-radius: 999px; flex-shrink: 0; }
  .pill.critical { background: var(--danger-bg); color: var(--danger); }
  .pill.high { background: var(--warning-bg); color: var(--warning); }
  .pill.medium { background: var(--warning-bg); color: var(--warning); }
  .pill.low { background: var(--surface-2); color: var(--text-2); }
  .pill.discussion { background: var(--accent-bg); color: var(--accent); }
  .pill.invalid { background: var(--surface-2); color: var(--text-2); }
  .pill.engine { background: var(--accent-bg); color: var(--accent); text-transform: capitalize; }
  /* Same finding-source legend as the verse underlines and the review panel
     (index.css mark.m-*): tN red, tW blue, Greek Room green. */
  .pill.tn { background: var(--tn-bg); color: var(--tn); }
  .pill.tw { background: var(--tw-bg); color: var(--tw); }
  .expand-toggle {
    flex-shrink: 0; font-size: 9px; font-weight: 700; color: var(--accent); align-self: center;
    margin-right: 10px; padding: 2px 7px; border-radius: 999px; background: var(--accent-bg);
    border: 0; cursor: pointer;
  }
  .local-findings { background: var(--surface-2); padding: 6px 12px 10px 32px; display: flex; flex-direction: column; gap: 6px; }
  .local-finding-row { display: flex; align-items: center; gap: 7px; font-size: 10px; border-left: 3px solid transparent; padding-left: 6px; }
  .local-finding-row.source-gr { border-left-color: var(--gr); }
  .local-finding-row.source-tn { border-left-color: var(--tn); }
  .local-finding-row.source-tw { border-left-color: var(--tw); }
  .local-explain { color: var(--text-2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .more { color: var(--text-2); font-size: 10px; margin: 8px 2px 0; }
  .books { border: 1px solid var(--border); border-radius: 10px; }
  .book-tools { display: grid; grid-template-columns: auto 1fr auto; align-items: center; gap: 9px; margin-bottom: 10px; }
  .book-tools label { color: var(--text-2); font-size: 10px; font-weight: 700; white-space: nowrap; }
  .book-tools input { min-width: 0; border: 1px solid var(--border-strong); border-radius: 7px; background: var(--surface); color: var(--text); padding: 8px 10px; font: inherit; font-size: 11px; }
  .book-tools span { color: var(--text-3); font-size: 9px; white-space: nowrap; flex-shrink: 0; }
  .no-match { margin: 10px; }
  .book-row { min-height: 66px; display: flex; align-items: center; gap: 11px; padding: 9px 11px; border-bottom: 1px solid var(--border); cursor: pointer; }
  .book-row:last-child { border-bottom: 0; }
  .book-row:hover { background: var(--surface-2); }
  .book-row:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }
  .book-row.previewed { background: var(--accent-bg); }
  .book-row.missing { background: #fff9ed; cursor: default; }
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
  .validation-button { border: 1px solid var(--accent); border-radius: 7px; background: var(--accent-bg); color: var(--accent); padding: 8px 11px; cursor: pointer; font-size: 10px; font-weight: 700; flex-shrink: 0; }
  .validation-entry { display: flex; flex-direction: column; align-items: flex-end; gap: 5px; flex-shrink: 0; }
  .validation-entry small { color: var(--text-3); font-size: 9px; }
  .validation-button.requires-advanced { border-color: var(--border-strong); background: var(--surface); color: var(--text-2); }
  .small-button:disabled { opacity: .55; cursor: not-allowed; }
  @media (max-width: 900px) {
    .panels { flex-direction: column; overflow-y: auto; }
    .left-panel { width: 100%; max-height: 45vh; border-right: 0; border-bottom: 1px solid var(--border); overflow-y: visible; }
    .right-panel { overflow-y: visible; }
    .header { flex-wrap: wrap; row-gap: 6px; }
    .header-left { flex-basis: 100%; }
    .header-right { flex-basis: 100%; }
  }
  @media (max-width: 760px) {
    .header { padding-left: 20px; padding-right: 20px; }
    .list-area, .report-area { padding-left: 20px; padding-right: 20px; }
    .bar-row { flex-direction: column; align-items: stretch; gap: 2px; }
    .bar-label { width: auto; }
    .book-tools { grid-template-columns: 1fr auto; }
    .book-tools label { grid-column: 1 / -1; }
  }
</style>
