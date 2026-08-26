<script lang="ts">
  import type { BookProgressEntry } from "../types/finding";

  export let books: BookProgressEntry[];
  export let loading: boolean;
  export let error: string;
  export let onSelectBook: (path: string) => void;
  export let onRetry: () => void;

  function percent(part: number, total: number): number {
    if (total <= 0) return 0;
    return Math.round((part / total) * 100);
  }
</script>

<div class="dashboard">
  <main class="card">
    <div class="eyebrow">PROJECT DASHBOARD</div>
    <h1>Books in this project</h1>
    <p class="intro">Pick a book to open it, or check review and AI-check progress at a glance.</p>

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
  </main>
</div>

<style>
  .dashboard { flex: 1; background: var(--bg); display: flex; align-items: flex-start; justify-content: center; overflow: auto; padding: 28px; }
  .card { width: min(760px, 100%); border: 1px solid var(--border); border-radius: 16px; background: var(--surface); padding: 34px; box-shadow: 0 18px 55px rgba(25, 35, 55, .10); margin: auto; }
  .eyebrow { color: var(--accent); font-size: 10px; letter-spacing: .12em; font-weight: 800; margin-bottom: 8px; }
  h1 { font-size: 22px; line-height: 1.2; margin: 0; color: var(--text); }
  .intro { color: var(--text-2); font-size: 13px; line-height: 1.55; margin: 10px 0 20px; }
  .empty { background: var(--surface-2); color: var(--text-2); border-radius: 8px; padding: 14px; font-size: 11px; margin: 0; }
  .error-row { display: flex; align-items: center; justify-content: space-between; gap: 10px; background: var(--surface-2); color: var(--danger); border-radius: 8px; padding: 14px; font-size: 11px; }
  .books { border: 1px solid var(--border); border-radius: 10px; max-height: 480px; overflow: auto; }
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
</style>
