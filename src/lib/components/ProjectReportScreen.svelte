<script lang="ts">
  import { tick } from "svelte";
  import { bridge } from "../api/bridgeClient";
  import ReportBars from "./ReportBars.svelte";
  import ReportDonut from "./ReportDonut.svelte";
  import type {
    QaReport, ReportBookSummary, ReportCategory, ReportJobSnapshot, ReportRow, ReportSeverity,
    TriageJobSnapshot, TriageRecord,
  } from "../types/report";
  import type { TriageOverrideVerdict } from "../types/finding";
  import {
    CATEGORY_LABELS, CATEGORY_LONG_LABELS, CATEGORY_ORDER, EMPTY_FILTERS, EXPORT_COLUMNS, SEVERITY_ORDER,
    TRIAGE_VERDICT_LABELS, applyTriage, bookDisplayName, categoryBreakdown, chaptersForBook, checkOutcomes,
    effectiveVerdict, exportFileName, exportRows, familyProgress, filterRows, fixedByBreakdown, fixedByLabel,
    hiddenByTriage, isFiltered, resultBreakdown, statusLabel, triageFor, triagedCount,
    type ReportFilters,
  } from "../utils/reportStats";

  /**
   * The project QA report: every check Bridge has run across the
   * collection and every issue it found, as an Allure-style page — book
   * list with per-check progress on the left; filters, stat tiles, charts
   * and the issue table on the right. All of it is derived on the client
   * from one report.get payload (see engine/tc_ai_bridge/qa_report.py), so
   * filtering never round-trips to the sidecar.
   *
   * Export: CSV/TSV go through the engine (a save dialog, then
   * report.export writes the filtered rows); PDF prints the right panel
   * through the webview's own print dialog, because that is the one
   * renderer in the app that shapes Tamil/Odia/Hebrew correctly.
   */
  export let projectName: string;
  export let report: QaReport | null = null;
  export let job: ReportJobSnapshot | null = null;
  export let error = "";
  export let onGenerate: () => void;
  export let onCancel: () => void = () => {};
  export let onNavigate: (book: string, chapter: string, verse: string) => void = () => {};

  /**
   * AI triage overlay. Optional and online-only: with no verdicts and no API
   * key this component renders exactly as it did before triage existed, which
   * is the local-first requirement — nothing offline may depend on it.
   */
  export let triage: Record<string, TriageRecord> = {};
  export let triageJob: TriageJobSnapshot | null = null;
  export let triageAvailable = false;
  export let triageUnavailableReason = "";
  export let triageError = "";
  /** 0 (or null) = off; otherwise hide false positives at or above this confidence. */
  export let triageThreshold: number | null = 90;
  export let onRunTriage: () => void = () => {};
  export let onCancelTriage: () => void = () => {};
  export let onTriageThreshold: (value: number | null) => void = () => {};
  export let onTriageOverride: (
    book: string, hash: string, verdict: TriageOverrideVerdict | "",
  ) => void = () => {};

  // Same finding-source legend as the rest of the app (index.css): tN red,
  // tW blue, Greek Room green, alignment amber; AI review takes violet.
  // Validated in this order for colour-vision separation with the legend
  // and direct labels as the mandatory secondary encoding.
  const CATEGORY_COLORS: Record<ReportCategory, string> = {
    translationNotes: "var(--tn)",
    translationWords: "var(--tw)",
    greekRoom: "var(--gr)",
    alignment: "var(--align)",
    aiReview: "var(--ai)",
  };
  const RESOLVED_COLOR = "var(--success)";
  const UNRESOLVED_COLOR = "var(--danger)";
  const NOT_RUN_COLOR = "var(--border-strong)";
  // Human vs machine vs unresolved share one ring, so all three pairs must
  // separate: cyan / violet / red validates all-pairs (the accent blue did
  // not against violet).
  const HUMAN_COLOR = "#0891B2";
  const MACHINE_COLOR = "var(--ai)";
  const TERMINAL = new Set(["succeeded", "failed", "cancelled"]);
  const PAGE = 100;

  let filters: ReportFilters = { ...EMPTY_FILTERS };
  let visibleCount = PAGE;
  let printing = false;
  let exporting = false;
  let exportMessage = "";
  let exportError = "";
  let exportMenu: HTMLDetailsElement | null = null;
  /** Click-to-reveal: shows the rows the slider is hiding, without moving it. */
  let revealTriaged = false;

  $: generating = job !== null && !TERMINAL.has(job.state);
  $: triaging = triageJob !== null && !TERMINAL.has(triageJob.state);
  $: rows = report?.rows ?? [];
  $: books = report?.books ?? [];
  // Filters first, then the triage overlay, so "N hidden by AI triage"
  // always counts within what the reviewer's filters already selected.
  $: matched = filterRows(rows, filters);
  // Computed whether or not they are currently revealed, so the count in the
  // disclosure stays truthful while the rows themselves are on screen.
  $: hiddenRows = hiddenByTriage(matched, triage, triageThreshold);
  $: hiddenRowIds = new Set(hiddenRows.map((row) => row.id));
  $: filtered = revealTriaged ? matched : applyTriage(matched, triage, triageThreshold);
  $: triagedRows = triagedCount(matched, triage);
  $: shown = printing ? filtered : filtered.slice(0, visibleCount);
  $: scopedBooks = filters.book ? books.filter((book) => book.bookId === filters.book) : books;
  $: categories = categoryBreakdown(filtered);
  $: fixedBy = fixedByBreakdown(filtered);
  $: results = resultBreakdown(filtered);
  $: outcomes = checkOutcomes(scopedBooks);
  $: checkTotals = outcomes.reduce(
    (sum, o) => ({ run: sum.run + o.passed + o.failed, passed: sum.passed + o.passed, failed: sum.failed + o.failed }),
    { run: 0, passed: 0, failed: 0 },
  );
  $: chapters = filters.book ? chaptersForBook(rows, filters.book) : [];
  $: unresolvedByBook = rows.reduce<Record<string, number>>((acc, row) => {
    if (row.resolution === "unresolved") acc[row.book] = (acc[row.book] ?? 0) + 1;
    return acc;
  }, {});
  $: collectionUnresolved = Object.values(unresolvedByBook).reduce((a, b) => a + b, 0);
  // A new filter always starts the table from the top.
  $: filters, (visibleCount = PAGE);
  $: countLabel = `Showing ${shown.length} of ${filtered.length} ${filtered.length === 1 ? "issue" : "issues"}`
    + (isFiltered(filters) ? ` (filtered from ${rows.length})` : "");
  // A new threshold, like a new filter, starts the table from the top.
  $: triageThreshold, (visibleCount = PAGE);

  function selectBook(bookId: string): void {
    filters = { ...filters, book: filters.book === bookId ? "" : bookId, chapter: "" };
  }

  function toggleCategory(category: ReportCategory): void {
    const next = filters.categories.includes(category)
      ? filters.categories.filter((c) => c !== category)
      : [...filters.categories, category];
    filters = { ...filters, categories: next };
  }

  function clearFilters(): void {
    filters = { ...EMPTY_FILTERS };
  }

  function setChapter(event: Event): void {
    filters = { ...filters, chapter: (event.target as HTMLSelectElement).value };
  }

  function setBook(event: Event): void {
    filters = { ...filters, book: (event.target as HTMLSelectElement).value, chapter: "" };
  }

  async function exportAs(format: "csv" | "tsv"): Promise<void> {
    exportMenu?.removeAttribute("open");
    exportMessage = "";
    exportError = "";
    try {
      const path = await bridge.pickSavePath(exportFileName(projectName, format));
      if (!path) return;
      exporting = true;
      const result = await bridge.reportExport(path, format, exportRows(filtered, triage), EXPORT_COLUMNS);
      exportMessage = `Wrote ${result.rows} row${result.rows === 1 ? "" : "s"} to ${result.path}`;
    } catch (e) {
      exportError = e instanceof Error ? e.message : String(e);
    } finally {
      exporting = false;
    }
  }

  async function printReport(): Promise<void> {
    exportMenu?.removeAttribute("open");
    printing = true;
    await tick();
    try {
      window.print();
    } finally {
      printing = false;
    }
  }

  function bookUnresolved(book: ReportBookSummary): number {
    return unresolvedByBook[book.bookId] ?? 0;
  }

  function formatDate(value: string): string {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
  }

  function severityChip(severity: ReportSeverity): string {
    return severity;
  }

  // --- AI triage -------------------------------------------------------

  const TRIAGE_OFF = 49; // the slider position below its 50 floor

  function setThreshold(event: Event): void {
    const raw = Number((event.target as HTMLInputElement).value);
    onTriageThreshold(raw <= TRIAGE_OFF ? null : raw);
    revealTriaged = false;
  }

  /** Thumbs toggle: clicking the verdict a row already has clears it. */
  function override(row: ReportRow, verdict: TriageOverrideVerdict): void {
    const record = triageFor(row, triage);
    if (!record) return;
    const next = record.userOverride?.verdict === verdict ? "" : verdict;
    onTriageOverride(row.book, row.triageHash, next);
  }

  function triageLabel(record: TriageRecord): string {
    const verdict = effectiveVerdict(record);
    if (record.userOverride) {
      return `${TRIAGE_VERDICT_LABELS[verdict]} · your call`;
    }
    return `${TRIAGE_VERDICT_LABELS[verdict]} · ${record.confidence}%`;
  }

  $: triageProgressLabel = triageJob
    ? `Triaging… ${triageJob.completedBooks}/${triageJob.totalBooks} books`
      + (triageJob.currentBook ? ` · ${triageJob.currentBook.toUpperCase()}` : "")
      + (triageJob.currentBookTriaged ? ` · ${triageJob.currentBookTriaged} findings` : "")
    : "";
  $: triageButtonTitle = triageAvailable
    ? "Ask the configured AI model how likely each Greek Room finding is to be a false positive"
    : (triageUnavailableReason || "AI triage needs an API key. Add one in Settings.");
</script>

<svelte:window on:beforeprint={() => (printing = true)} on:afterprint={() => (printing = false)} />

<div class="screen print-expand">
  <div class="header no-print">
    <div class="header-left">
      <span class="eyebrow">QA REPORT</span>
      <h1>{projectName}</h1>
      {#if report}
        <span class="intro">· {report.bookCount} {report.bookCount === 1 ? "book" : "books"} · generated {formatDate(report.generatedAt)}</span>
      {/if}
    </div>
    <div class="header-right">
      {#if generating && job}
        <div class="generating" role="status">
          <div class="spin" />
          <span class="gen-label">
            Generating report… {job.completedBooks}/{job.totalBooks} books{#if job.currentBook}&nbsp;· {job.currentBook.toUpperCase()}{/if}
          </span>
          <div class="track"><div class="fill" style="width:{job.percent}%" /></div>
          <button class="small-button" on:click={onCancel} disabled={job.state === "cancelling"}>
            {job.state === "cancelling" ? "Cancelling…" : "Cancel"}
          </button>
        </div>
      {:else if report}
        <button class="small-button" on:click={onGenerate}>Regenerate</button>
      {/if}
      {#if report && triaging && triageJob}
        <div class="generating" role="status">
          <div class="spin" />
          <span class="gen-label">{triageProgressLabel}</span>
          <div class="track"><div class="fill" style="width:{triageJob.percent}%" /></div>
          <button
            class="small-button"
            on:click={onCancelTriage}
            disabled={triageJob.state === "cancelling"}
          >{triageJob.state === "cancelling" ? "Cancelling…" : "Cancel"}</button>
        </div>
      {:else if report}
        <button
          class="small-button"
          on:click={onRunTriage}
          disabled={!triageAvailable}
          title={triageButtonTitle}
        >Run AI triage</button>
      {/if}
      {#if report}
        <details class="export" bind:this={exportMenu}>
          <summary class="small-button primary">Export ▾</summary>
          <div class="menu">
            <button on:click={() => exportAs("csv")} disabled={exporting}>CSV</button>
            <button on:click={() => exportAs("tsv")} disabled={exporting}>TSV</button>
            <button on:click={printReport}>PDF (print)</button>
            <small>Exports the {filtered.length} filtered row{filtered.length === 1 ? "" : "s"}. For PDF, choose “Save as PDF” in the print dialog.</small>
          </div>
        </details>
      {/if}
    </div>
  </div>

  {#if exportMessage || exportError || exporting}
    <div class="export-status no-print" class:error={Boolean(exportError)} role="status">
      {#if exporting}Writing…{:else}{exportError || exportMessage}{/if}
    </div>
  {/if}

  <div class="panels print-expand">
    <aside class="left-panel no-print" aria-label="Books in this report">
      {#if report}
        <div class="list-area">
          <button class="book-row all" class:selected={!filters.book} on:click={() => selectBook("")}>
            <div class="book-badge">ALL</div>
            <div class="book-copy">
              <strong>All books</strong>
              <span class="note">{report.bookCount} {report.bookCount === 1 ? "book" : "books"} · {collectionUnresolved} unresolved issue{collectionUnresolved === 1 ? "" : "s"}</span>
            </div>
          </button>
          <section class="books">
            {#each books as book (book.bookId)}
              {@const open = bookUnresolved(book)}
              {@const bars = familyProgress(book)}
              <button
                class="book-row"
                class:selected={filters.book === book.bookId}
                class:missing={book.missing}
                on:click={() => selectBook(book.bookId)}
                aria-pressed={filters.book === book.bookId}
              >
                <div class="book-badge">{book.bookId.toUpperCase() || "?"}</div>
                <div class="book-copy">
                  <div class="book-title">
                    <strong>{bookDisplayName(book)}</strong>
                    {#if open > 0}<span class="pill open">{open} open</span>{/if}
                  </div>
                  {#if book.missing}
                    <span class="note">Project folder is missing</span>
                  {:else if book.lazy}
                    <span class="note">Not yet opened — no checks run</span>
                  {:else if book.error}
                    <span class="note error">Could not read: {book.error}</span>
                  {:else}
                    <div class="bars">
                      {#each bars as bar (bar.family)}
                        <div class="bar-row" class:muted={bar.state === "not_run" || bar.state === "unavailable"}>
                          <span class="bar-label">{bar.label}</span>
                          <div class="track"><div class="fill {bar.family}" style="width:{bar.percent}%" /></div>
                          <span class="bar-detail">{bar.detail}</span>
                        </div>
                      {/each}
                    </div>
                  {/if}
                </div>
              </button>
            {/each}
          </section>
        </div>
      {:else}
        <div class="list-area"><p class="empty">Books appear here once the report is generated.</p></div>
      {/if}
    </aside>

    <main class="right-panel print-expand">
      {#if !report && generating && job}
        <div class="report-area"><p class="empty">Generating the report… {job.completedBooks}/{job.totalBooks} books.</p></div>
      {:else if !report && error}
        <div class="report-area">
          <p class="empty error">Could not generate the report: {error}</p>
          <button class="small-button" on:click={onGenerate}>Try again</button>
        </div>
      {:else if !report}
        <div class="report-area">
          <p class="empty">No report yet. Generate one to list every check Bridge has run and every issue it found across the project.</p>
          <button class="small-button primary" on:click={onGenerate}>Generate report</button>
        </div>
      {:else}
        <div class="report-area print-root" class:stale={generating}>
          {#if error}
            <p class="banner error">{error}</p>
          {/if}
          <div class="print-only">
            <h2>{projectName} — QA report</h2>
            <p>Generated {formatDate(report.generatedAt)} · {report.bookCount} books{#if isFiltered(filters)} · filtered to {filtered.length} of {rows.length} rows{/if}</p>
          </div>

          <section class="filters no-print" aria-label="Filters">
            <div class="chips" role="group" aria-label="Error category">
              {#each CATEGORY_ORDER as category (category)}
                <button
                  class="chip"
                  class:active={filters.categories.includes(category)}
                  style="--chip:{CATEGORY_COLORS[category]}"
                  aria-pressed={filters.categories.includes(category)}
                  title={CATEGORY_LONG_LABELS[category]}
                  on:click={() => toggleCategory(category)}
                ><i />{CATEGORY_LABELS[category]}</button>
              {/each}
            </div>
            <label>Book
              <select value={filters.book} on:change={setBook}>
                <option value="">All books</option>
                {#each books as book (book.bookId)}
                  <option value={book.bookId}>{bookDisplayName(book)}</option>
                {/each}
              </select>
            </label>
            <label>Chapter
              <select value={filters.chapter} on:change={setChapter} disabled={!filters.book}>
                <option value="">All</option>
                {#each chapters as chapter (chapter)}
                  <option value={chapter}>{chapter}</option>
                {/each}
              </select>
            </label>
            <label>Fixed by
              <select bind:value={filters.fixedBy}>
                <option value="">Any</option>
                <option value="human">Human</option>
                <option value="machine">Machine</option>
                <option value="unresolved">Unresolved</option>
              </select>
            </label>
            <label>Result
              <select bind:value={filters.result}>
                <option value="">Pass and fail</option>
                <option value="fail">Fail</option>
                <option value="pass">Pass</option>
              </select>
            </label>
            <label>Severity
              <select bind:value={filters.severity}>
                <option value="">Any</option>
                {#each SEVERITY_ORDER as severity (severity)}
                  <option value={severity}>{severity}</option>
                {/each}
              </select>
            </label>
            <input type="search" placeholder="Search issues, references, proposals" bind:value={filters.search} aria-label="Search" />
            {#if isFiltered(filters)}
              <button class="small-button" on:click={clearFilters}>Clear filters</button>
            {/if}
          </section>

          {#if triageError}
            <p class="banner error no-print">AI triage: {triageError}</p>
          {/if}

          {#if triagedRows > 0}
            <section class="triage-bar no-print" aria-label="AI triage">
              <label class="triage-slider">
                <span class="triage-label">
                  Hide findings rated
                  <strong>{triageThreshold === null ? "—" : `≥ ${triageThreshold}%`}</strong>
                  likely false positive
                </span>
                <input
                  type="range"
                  min={TRIAGE_OFF}
                  max="100"
                  step="1"
                  value={triageThreshold ?? TRIAGE_OFF}
                  on:input={setThreshold}
                  aria-label="Hide findings rated at least this likely to be a false positive"
                  aria-valuetext={triageThreshold === null ? "Off — showing everything" : `${triageThreshold} percent`}
                />
                <span class="triage-ends"><span>Off</span><span>100%</span></span>
              </label>
              <p class="triage-note">
                {#if triageThreshold === null}
                  Showing every finding. {triagedRows} of {matched.length} have an AI triage score.
                {:else if hiddenRows.length > 0}
                  <strong>{hiddenRows.length}</strong>
                  {hiddenRows.length === 1 ? "finding" : "findings"}
                  {revealTriaged ? "shown despite AI triage." : "hidden by AI triage."}
                  <button class="link-button" on:click={() => (revealTriaged = !revealTriaged)}>
                    {revealTriaged ? "Hide them again" : "Show them"}
                  </button>
                {:else}
                  Nothing is hidden at this level. {triagedRows} of {matched.length} findings have an AI triage score.
                {/if}
              </p>
              <p class="triage-caveat">
                Scores rank findings by how suspicious the model found them. They are
                not calibrated probabilities — only <em>uncertain</em> and
                <em>likely real</em> findings are ever kept visible.
              </p>
            </section>
          {/if}

          <section class="tiles" aria-label="Summary">
            <div class="tile"><span class="tile-label">Checks run</span><span class="tile-value">{checkTotals.run}</span><small>verses and checks</small></div>
            <div class="tile good"><span class="tile-label">Passed</span><span class="tile-value">{checkTotals.passed}</span></div>
            <div class="tile bad"><span class="tile-label">Failed</span><span class="tile-value">{checkTotals.failed}</span></div>
            <div class="tile"><span class="tile-label">Issues</span><span class="tile-value">{filtered.length}</span><small>{isFiltered(filters) ? `of ${rows.length}` : "in the table"}</small></div>
            <div class="tile good"><span class="tile-label">Resolved</span><span class="tile-value">{results.pass}</span><small>{fixedBy.human} human · {fixedBy.machine} machine</small></div>
            <div class="tile bad"><span class="tile-label">Unresolved</span><span class="tile-value">{results.fail}</span></div>
          </section>

          <section class="charts" aria-label="Charts">
            <ReportDonut
              title="Issues by category"
              centerLabel="issues"
              slices={categories.map((c) => ({ key: c.category, label: CATEGORY_LABELS[c.category], value: c.total, color: CATEGORY_COLORS[c.category] }))}
            />
            <ReportBars
              title="Fixed vs unresolved, by category"
              rows={categories.map((c) => ({
                key: c.category, label: CATEGORY_LABELS[c.category],
                segments: [
                  { key: "resolved", label: "Fixed", value: c.resolved, color: RESOLVED_COLOR },
                  { key: "unresolved", label: "Unresolved", value: c.unresolved, color: UNRESOLVED_COLOR },
                ],
              }))}
              legend={[{ key: "resolved", label: "Fixed", color: RESOLVED_COLOR }, { key: "unresolved", label: "Unresolved", color: UNRESOLVED_COLOR }]}
            />
            <ReportBars
              title="Checks passed vs failed"
              rows={outcomes.map((o) => ({
                key: o.family, label: o.label, sublabel: o.unit,
                segments: [
                  { key: "passed", label: "Passed", value: o.passed, color: RESOLVED_COLOR },
                  { key: "failed", label: "Failed", value: o.failed, color: UNRESOLVED_COLOR },
                  { key: "notRun", label: "Not run", value: o.notRun, color: NOT_RUN_COLOR },
                ],
              }))}
              legend={[
                { key: "passed", label: "Passed", color: RESOLVED_COLOR },
                { key: "failed", label: "Failed", color: UNRESOLVED_COLOR },
                { key: "notRun", label: "Not run", color: NOT_RUN_COLOR },
              ]}
            />
            <ReportDonut
              title="Fixed by"
              centerLabel="issues"
              slices={[
                { key: "human", label: "Human", value: fixedBy.human, color: HUMAN_COLOR },
                { key: "machine", label: "Machine", value: fixedBy.machine, color: MACHINE_COLOR },
                { key: "unresolved", label: "Unresolved", value: fixedBy.unresolved, color: UNRESOLVED_COLOR },
              ]}
            />
          </section>

          <section class="table-section" aria-label="Issues">
            <div class="table-head">
              <span class="count">{countLabel}</span>
            </div>
            {#if filtered.length === 0}
              <p class="empty">{rows.length === 0 ? "No issues were found in the checks run so far." : "No issues match these filters."}</p>
            {:else}
              <div class="table-wrap">
                <table class="issues" aria-label="Issue table">
                  <thead>
                    <tr>
                      <th>Error category</th>
                      <th>Book</th>
                      <th class="num">Chapter</th>
                      <th class="num">Verse</th>
                      <th>Issue and explanation</th>
                      <th>AI proposal</th>
                      <th>Fixed by</th>
                      <th>Pass / fail</th>
                    </tr>
                  </thead>
                  <tbody>
                    {#each shown as row (row.id)}
                      {@const record = triageFor(row, triage)}
                      <tr
                        class:unresolved={row.resolution === "unresolved"}
                        class:triage-hidden={revealTriaged && hiddenRowIds.has(row.id)}
                      >
                        <td>
                          <span class="cat" style="--chip:{CATEGORY_COLORS[row.category]}"><i />{CATEGORY_LABELS[row.category]}</span>
                          <small class="engine">{row.engine}</small>
                        </td>
                        <td class="book">{row.bookName || row.book.toUpperCase()}</td>
                        <td class="num">{row.chapter}</td>
                        <td class="num">
                          <button class="verse-link" title="Open {row.reference}" on:click={() => onNavigate(row.book, row.chapter, row.verse)}>{row.verse}</button>
                        </td>
                        <td class="issue">
                          <strong>{row.issue}</strong>
                          {#if row.explanation && row.explanation !== row.issue}<span class="explain">{row.explanation}</span>{/if}
                          <span class="meta">
                            <i class="sev sev-{severityChip(row.severity)}">{row.severity}</i>
                            <span>{statusLabel(row.status)}</span>
                            {#if row.selection}<span>selected: {row.selection}</span>{/if}
                            {#if row.note}<span>note: {row.note}</span>{/if}
                          </span>
                          {#if record}
                            <span
                              class="triage-tag verdict-{effectiveVerdict(record)}"
                              class:overridden={Boolean(record.userOverride)}
                              title={record.reason}
                            >
                              <span class="triage-verdict">{triageLabel(record)}</span>
                              {#if record.reason}<span class="triage-reason">{record.reason}</span>{/if}
                              <span class="thumbs no-print">
                                <button
                                  class="thumb"
                                  class:on={record.userOverride?.verdict === "true_positive"}
                                  title="Mark as a real problem — always shown, never re-sent to the model"
                                  aria-label="Mark {row.reference} as a real problem"
                                  aria-pressed={record.userOverride?.verdict === "true_positive"}
                                  on:click={() => override(row, "true_positive")}
                                >&#128077;</button>
                                <button
                                  class="thumb"
                                  class:on={record.userOverride?.verdict === "false_positive"}
                                  title="Mark as a false positive — hidden by the slider, never re-sent to the model"
                                  aria-label="Mark {row.reference} as a false positive"
                                  aria-pressed={record.userOverride?.verdict === "false_positive"}
                                  on:click={() => override(row, "false_positive")}
                                >&#128078;</button>
                              </span>
                            </span>
                          {/if}
                        </td>
                        <td class="proposal">
                          {#if row.aiProposal}
                            {row.aiProposal}
                            {#if row.aiVerdict}<small>AI verdict: {row.aiVerdict}</small>{/if}
                          {:else if row.aiVerdict}
                            <small>AI verdict: {row.aiVerdict}</small>
                          {:else}
                            <span class="muted">—</span>
                          {/if}
                        </td>
                        <td class="fixed">
                          {fixedByLabel(row)}
                          {#if row.decidedAt}<small>{formatDate(row.decidedAt)}</small>{/if}
                        </td>
                        <td><span class="result {row.result}">{row.result === "pass" ? "✓ Pass" : "✗ Fail"}</span></td>
                      </tr>
                    {/each}
                  </tbody>
                </table>
              </div>
              {#if !printing && filtered.length > shown.length}
                <div class="paging no-print">
                  <button class="small-button" on:click={() => (visibleCount += PAGE)}>Show {Math.min(PAGE, filtered.length - shown.length)} more</button>
                  <button class="small-button" on:click={() => (visibleCount = filtered.length)}>Show all {filtered.length}</button>
                </div>
              {/if}
            {/if}
          </section>
          <p class="footnote">{report.note}</p>
        </div>
      {/if}
    </main>
  </div>
</div>

<style>
  .screen { flex: 1; min-height: 0; display: flex; flex-direction: column; overflow: hidden; background: var(--surface); }
  .header { flex-shrink: 0; padding: 12px 32px; border-bottom: 1px solid var(--border); display: flex; align-items: center; gap: 18px; box-sizing: border-box; }
  .header-left { flex: 1; min-width: 0; display: flex; align-items: baseline; gap: 8px; overflow: hidden; }
  .header-right { display: flex; align-items: center; gap: 10px; flex-shrink: 0; }
  .eyebrow { color: var(--accent); font-size: var(--fs-2xs); letter-spacing: .12em; font-weight: 800; flex-shrink: 0; }
  h1 { font-size: var(--fs-xl); line-height: 1.2; margin: 0; color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .intro { color: var(--text-2); font-size: var(--fs-sm); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .generating { display: flex; align-items: center; gap: 8px; font-size: var(--fs-xs); color: var(--text-2); }
  .gen-label { white-space: nowrap; }
  .spin { width: 12px; height: 12px; border-radius: 50%; border: 2px solid var(--accent-bg); border-top-color: var(--accent); animation: spin 0.8s linear infinite; flex-shrink: 0; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .generating .track { width: 120px; }
  .track { height: 6px; background: #EEF0F3; border-radius: 4px; overflow: hidden; }
  .fill { height: 100%; background: var(--accent); transition: width 0.3s; }
  .export { position: relative; }
  .export summary { list-style: none; display: inline-block; }
  .export summary::-webkit-details-marker { display: none; }
  .export .menu { position: absolute; right: 0; top: calc(100% + 6px); z-index: 20; width: 240px; background: var(--surface); border: 1px solid var(--border); border-radius: 10px; box-shadow: 0 8px 24px rgba(0,0,0,.12); padding: 6px; display: flex; flex-direction: column; gap: 2px; }
  .export .menu button { text-align: left; border: 0; background: transparent; padding: 8px 10px; border-radius: 6px; font-size: var(--fs-sm); color: var(--text); cursor: pointer; }
  .export .menu button:hover:not(:disabled) { background: var(--surface-2); }
  .export .menu button:disabled { opacity: .55; cursor: not-allowed; }
  .export .menu small { color: var(--text-3); font-size: var(--fs-2xs); padding: 6px 10px 4px; line-height: 1.4; }
  .export-status { flex-shrink: 0; padding: 6px 32px; font-size: var(--fs-xs); color: var(--success); background: var(--success-bg); border-bottom: 1px solid var(--border); }
  .export-status.error { color: var(--danger); background: var(--danger-bg); }
  .panels { flex: 1; min-height: 0; display: flex; overflow: hidden; }
  .left-panel { width: 400px; flex-shrink: 0; overflow-y: auto; border-right: 1px solid var(--border); box-sizing: border-box; }
  .list-area { padding: 16px 18px; box-sizing: border-box; display: flex; flex-direction: column; gap: 10px; }
  .right-panel { flex: 1; min-width: 0; overflow-y: auto; box-sizing: border-box; }
  .report-area { box-sizing: border-box; padding: 18px 28px 28px; max-width: 1180px; transition: opacity .2s; }
  .report-area.stale { opacity: .55; }
  .empty { background: var(--surface-2); color: var(--text-2); border-radius: 8px; padding: 14px; font-size: var(--fs-xs); margin: 0 0 10px; }
  .empty.error { color: var(--danger); background: var(--danger-bg); }
  .banner { border-radius: 8px; padding: 9px 12px; font-size: var(--fs-xs); margin: 0 0 12px; }
  .banner.error { color: var(--danger); background: var(--danger-bg); }
  .print-only { display: none; }

  /* Book list */
  .books { border: 1px solid var(--border); border-radius: 10px; overflow: hidden; }
  .book-row { width: 100%; text-align: left; font: inherit; display: flex; align-items: flex-start; gap: 10px; padding: 10px 11px; border: 0; border-bottom: 1px solid var(--border); background: var(--surface); cursor: pointer; }
  .book-row:last-child { border-bottom: 0; }
  .book-row:hover { background: var(--surface-2); }
  .book-row:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }
  .book-row.selected { background: var(--accent-bg); }
  .book-row.all { border: 1px solid var(--border); border-radius: 10px; align-items: center; }
  .book-row.missing { background: #fff9ed; }
  .book-badge { width: 36px; height: 36px; display: grid; place-items: center; border-radius: 8px; background: var(--accent-bg); color: var(--accent); font-size: var(--fs-2xs); font-weight: 800; flex-shrink: 0; }
  .book-copy { display: flex; flex-direction: column; min-width: 0; flex: 1; gap: 4px; }
  .book-title { display: flex; align-items: center; gap: 8px; }
  .book-copy strong { font-size: var(--fs-sm); color: var(--text); }
  .book-copy .note { color: var(--text-2); font-size: var(--fs-2xs); }
  .book-copy .note.error { color: var(--danger); }
  .bars { display: flex; flex-direction: column; gap: 3px; margin-top: 2px; }
  .bar-row { display: grid; grid-template-columns: 62px 1fr 108px; align-items: center; gap: 7px; }
  .bar-row.muted { opacity: .6; }
  .bar-label { color: var(--text-2); font-size: var(--fs-3xs); font-weight: 600; }
  .bar-detail { color: var(--text-3); font-size: var(--fs-3xs); text-align: right; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .bar-row .track { width: 100%; }
  .fill.greekRoom { background: var(--gr); }
  .fill.translationNotes { background: var(--tn); }
  .fill.translationWords { background: var(--tw); }
  .fill.alignment { background: var(--align); }
  .fill.aiReview { background: var(--ai); }
  .pill { font-size: var(--fs-3xs); font-weight: 700; padding: 2px 7px; border-radius: 999px; flex-shrink: 0; }
  .pill.open { background: var(--danger-bg); color: var(--danger); }

  /* Filters */
  .filters { display: flex; flex-wrap: wrap; align-items: end; gap: 10px 12px; padding: 10px 12px; border: 1px solid var(--border); border-radius: 10px; background: var(--surface-2); margin-bottom: 14px; }
  .chips { display: flex; flex-wrap: wrap; gap: 6px; align-self: center; }
  .chip { display: inline-flex; align-items: center; gap: 6px; font-size: var(--fs-2xs); font-weight: 700; padding: 5px 9px; border-radius: 999px; border: 1px solid var(--border-strong); background: var(--surface); color: var(--text-2); cursor: pointer; }
  .chip i, .cat i { width: 8px; height: 8px; border-radius: 50%; background: var(--chip); display: inline-block; }
  .chip.active { border-color: var(--chip); color: var(--text); box-shadow: inset 0 0 0 1px var(--chip); }
  .filters label { display: flex; flex-direction: column; gap: 3px; font-size: var(--fs-3xs); font-weight: 700; color: var(--text-2); }
  .filters select { height: 28px; border: 1px solid var(--border-strong); border-radius: 6px; font-size: var(--fs-xs); padding: 0 6px; background: var(--surface); color: var(--text); min-width: 96px; }
  .filters input { height: 28px; border: 1px solid var(--border-strong); border-radius: 6px; font-size: var(--fs-xs); padding: 0 10px; background: var(--surface); color: var(--text); flex: 1; min-width: 160px; align-self: end; }

  /* AI triage overlay. Violet throughout, matching the AI-review category
     colour used by the charts and chips, so "this came from a model" reads
     the same everywhere on the page. */
  .triage-bar { display: flex; flex-direction: column; gap: 6px; padding: 10px 12px; border: 1px solid var(--border); border-left: 3px solid var(--ai); border-radius: 10px; background: var(--surface-2); margin-bottom: 14px; }
  .triage-slider { display: grid; grid-template-columns: auto minmax(140px, 260px); grid-template-areas: "label slider" "label ends"; align-items: center; gap: 2px 12px; }
  .triage-label { grid-area: label; font-size: var(--fs-xs); color: var(--text-2); }
  .triage-label strong { color: var(--text); }
  .triage-slider input { grid-area: slider; width: 100%; accent-color: var(--ai); }
  .triage-ends { grid-area: ends; display: flex; justify-content: space-between; font-size: var(--fs-3xs); color: var(--text-2); }
  .triage-note { margin: 0; font-size: var(--fs-xs); color: var(--text-2); }
  .triage-note strong { color: var(--text); }
  .triage-caveat { margin: 0; font-size: var(--fs-2xs); color: var(--text-2); opacity: 0.85; }
  .link-button { background: none; border: 0; padding: 0; font: inherit; color: var(--accent); text-decoration: underline; cursor: pointer; }

  /* Per-row verdict. The label carries the verdict in words as well as the
     colour, so it survives both printing and colour-vision differences. */
  .triage-tag { display: flex; flex-wrap: wrap; align-items: center; gap: 4px 8px; margin-top: 4px; font-size: var(--fs-2xs); color: var(--text-2); }
  .triage-verdict { font-weight: 700; padding: 1px 7px; border-radius: 999px; border: 1px solid var(--border-strong); }
  .verdict-false_positive .triage-verdict { color: var(--ai); border-color: var(--ai); }
  .verdict-true_positive .triage-verdict { color: var(--danger); border-color: var(--danger); }
  .verdict-uncertain .triage-verdict { color: var(--text-2); }
  .triage-tag.overridden .triage-verdict { box-shadow: inset 0 0 0 1px currentColor; }
  .triage-reason { font-style: italic; flex: 1; min-width: 0; }
  .thumbs { display: inline-flex; gap: 2px; }
  .thumb { border: 1px solid transparent; background: none; border-radius: 6px; cursor: pointer; font-size: var(--fs-xs); line-height: 1; padding: 2px 4px; opacity: 0.45; }
  .thumb:hover { opacity: 1; background: var(--surface-2); }
  .thumb.on { opacity: 1; border-color: var(--ai); background: var(--surface-2); }
  /* A row shown only because the reviewer asked to see what was hidden. */
  tr.triage-hidden { opacity: 0.6; background: repeating-linear-gradient(135deg, transparent, transparent 6px, var(--surface-2) 6px, var(--surface-2) 12px); }

  /* Tiles */
  .tiles { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 10px; margin-bottom: 16px; }
  .tile { border: 1px solid var(--border); border-radius: 10px; padding: 10px 12px; display: flex; flex-direction: column; gap: 2px; min-width: 0; background: var(--surface); }
  .tile-label { font-size: var(--fs-2xs); color: var(--text-2); font-weight: 600; }
  .tile-value { font-size: var(--fs-4xl); font-weight: 650; color: var(--text); line-height: 1.1; }
  .tile small { font-size: var(--fs-3xs); color: var(--text-3); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .tile.good .tile-value { color: var(--success); }
  .tile.bad .tile-value { color: var(--danger); }

  /* Charts */
  .charts { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px 24px; padding: 14px 16px; border: 1px solid var(--border); border-radius: 10px; margin-bottom: 16px; }

  /* Table */
  .table-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px; }
  .count { font-size: var(--fs-2xs); color: var(--text-2); font-weight: 600; }
  .table-wrap { overflow-x: auto; border: 1px solid var(--border); border-radius: 10px; }
  table.issues { width: 100%; border-collapse: collapse; font-size: var(--fs-xs); }
  .issues th { text-align: left; font-size: var(--fs-3xs); letter-spacing: .06em; text-transform: uppercase; color: var(--text-2); background: var(--surface-2); padding: 8px 10px; border-bottom: 1px solid var(--border); white-space: nowrap; }
  .issues td { padding: 8px 10px; border-bottom: 1px solid var(--border); vertical-align: top; color: var(--text); }
  .issues tr:last-child td { border-bottom: 0; }
  .issues tr.unresolved td:first-child { box-shadow: inset 3px 0 0 var(--danger); }
  .issues .num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
  .issues .book { white-space: nowrap; }
  .cat { display: inline-flex; align-items: center; gap: 6px; font-weight: 700; font-size: var(--fs-2xs); white-space: nowrap; }
  .engine { display: block; color: var(--text-3); font-size: var(--fs-3xs); margin-top: 2px; }
  .verse-link { border: 0; background: transparent; color: var(--accent); font: inherit; font-weight: 700; cursor: pointer; padding: 0; text-decoration: underline; text-underline-offset: 2px; }
  .issue { min-width: 260px; }
  .issue strong { display: block; font-weight: 650; }
  .explain { display: block; color: var(--text-2); margin-top: 2px; line-height: 1.4; }
  .meta { display: flex; flex-wrap: wrap; gap: 4px 8px; margin-top: 4px; font-size: var(--fs-3xs); color: var(--text-3); align-items: center; }
  .sev { font-style: normal; font-weight: 700; padding: 1px 6px; border-radius: 999px; background: var(--surface-2); color: var(--text-2); }
  .sev-critical, .sev-high { background: var(--danger-bg); color: var(--danger); }
  .sev-medium { background: var(--warning-bg); color: var(--warning); }
  .proposal { min-width: 160px; max-width: 280px; color: var(--text); }
  .proposal small, .fixed small { display: block; color: var(--text-3); font-size: var(--fs-3xs); margin-top: 2px; }
  .fixed { white-space: nowrap; }
  .muted { color: var(--text-3); }
  .result { font-size: var(--fs-2xs); font-weight: 700; padding: 2px 8px; border-radius: 999px; white-space: nowrap; }
  .result.pass { background: var(--success-bg); color: var(--success); }
  .result.fail { background: var(--danger-bg); color: var(--danger); }
  .paging { display: flex; gap: 8px; margin-top: 10px; }
  .footnote { color: var(--text-3); font-size: var(--fs-2xs); margin: 14px 0 0; }
  .small-button { border: 1px solid var(--border-strong); border-radius: 6px; background: var(--surface); color: var(--text); padding: 6px 10px; cursor: pointer; font-size: var(--fs-2xs); font-weight: 600; flex-shrink: 0; }
  .small-button:hover:not(:disabled) { background: var(--surface-2); }
  .small-button:disabled { opacity: .55; cursor: not-allowed; }
  .small-button.primary { border-color: var(--accent); background: var(--accent); color: #fff; }
  .small-button.primary:hover:not(:disabled) { background: var(--accent); filter: brightness(1.05); }

  @media (max-width: 1100px) {
    .tiles { grid-template-columns: repeat(3, minmax(0, 1fr)); }
    .charts { grid-template-columns: 1fr; }
  }
  @media (max-width: 900px) {
    .panels { flex-direction: column; overflow-y: auto; }
    .left-panel { width: 100%; max-height: 40vh; border-right: 0; border-bottom: 1px solid var(--border); }
    .right-panel { overflow-y: visible; }
  }
  @media print {
    .print-only { display: block; margin-bottom: 12px; }
    .print-only h2 { font-size: var(--fs-xl); margin: 0 0 4px; }
    .print-only p { font-size: var(--fs-xs); color: var(--text-2); margin: 0; }
    .report-area { max-width: none; padding: 0; opacity: 1 !important; }
    .charts { break-inside: avoid; }
    .table-wrap { overflow: visible; border: 0; }
    .issues tr { break-inside: avoid; }
    .verse-link { text-decoration: none; color: var(--text); }
  }
</style>
