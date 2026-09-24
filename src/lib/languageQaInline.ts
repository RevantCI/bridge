// Keeps languageQaFindingsByVerse -- the store VerseList draws Language QA
// marks from -- in step with the engine, for the chapter on screen.
//
// This used to be a side effect of LanguageQaPanel's own status poll, which
// fetches ONE PAGE of findings (50 or 100) for the panel's list. The marks
// therefore covered only whatever that page held: a book with more than a
// page of findings lost its later chapters' marks, and paging the panel moved
// the marks around. The marks now come from languageQa.inline, which returns
// every inline-rule finding for a chapter, unpaged, and the panel no longer
// writes this store at all.
import { get } from "svelte/store";
import { bridge } from "./api/bridgeClient";
import { currentChapter, languageQaFindingsByVerse, verseKey } from "./stores";
import type { LanguageQaFinding } from "./types/languageQa";

/** Same cadence LanguageQaPanel polled at while collapsed, its default state. */
export const INLINE_POLL_MS = 5000;

/** Group one inline response by verse key. The engine has already filtered
 * to the inline rules, so nothing is dropped here. */
export function groupInlineFindings(findings: LanguageQaFinding[]): Record<string, LanguageQaFinding[]> {
  const byVerse: Record<string, LanguageQaFinding[]> = {};
  for (const finding of findings) {
    (byVerse[verseKey(finding.chapter, finding.verse)] ??= []).push(finding);
  }
  return byVerse;
}

function sameFindings(a: LanguageQaFinding[] | undefined, b: LanguageQaFinding[]): boolean {
  return a !== undefined && a.length === b.length && a.every((finding, i) => {
    const other = b[i];
    return finding.id === other.id && finding.start === other.start && finding.end === other.end
      && finding.textHash === other.textHash && finding.previouslyIgnored === other.previouslyIgnored
      && finding.packVersion === other.packVersion;
  });
}

/**
 * The next map, reusing the current entry of every verse whose findings did
 * not change. When nothing changed at all the SAME map comes back, so a poll
 * that finds nothing new never notifies the store's subscribers, and a verse
 * whose marks did not change keeps its array. Exported for its test.
 */
export function patchInlineFindings(
  current: Record<string, LanguageQaFinding[]>,
  incoming: Record<string, LanguageQaFinding[]>,
): Record<string, LanguageQaFinding[]> {
  let changed = Object.keys(current).length !== Object.keys(incoming).length;
  const next: Record<string, LanguageQaFinding[]> = {};
  for (const [key, findings] of Object.entries(incoming)) {
    if (sameFindings(current[key], findings)) {
      next[key] = current[key];
    } else {
      next[key] = findings;
      changed = true;
    }
  }
  return changed ? next : current;
}

/**
 * Poll languageQa.inline for $currentChapter until the returned stop
 * function is called. Only the newest request may write the store or
 * schedule the next poll: a chapter change starts a fresh request at once and
 * the one still in flight, answering for the old chapter, is discarded. A
 * response naming a different project is ignored the same way LanguageQaPanel
 * ignores one. A failed request keeps the marks already shown and retries on
 * the next tick -- the panel is where errors are reported.
 */
export function startLanguageQaInline(
  projectPath: string,
  { intervalMs = INLINE_POLL_MS }: { intervalMs?: number } = {},
): () => void {
  let disposed = false;
  let sequence = 0;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let chapter = get(currentChapter);

  async function refresh(): Promise<void> {
    if (disposed) return;
    if (timer) clearTimeout(timer);
    const ticket = ++sequence;
    const requested = chapter;
    try {
      const next = await bridge.languageQaInline(projectPath, requested);
      if (disposed || ticket !== sequence || requested !== chapter || next.projectPath !== projectPath) return;
      // A Svelte store notifies on every object write, same reference or not,
      // so an unchanged poll must not write at all.
      const current = get(languageQaFindingsByVerse);
      const patched = patchInlineFindings(current, groupInlineFindings(next.findings));
      if (patched !== current) languageQaFindingsByVerse.set(patched);
    } catch {
      // Keep the last marks; the next tick retries.
    } finally {
      if (!disposed && ticket === sequence) timer = setTimeout(() => void refresh(), intervalMs);
    }
  }

  const unsubscribe = currentChapter.subscribe((next) => {
    if (next === chapter) return;
    chapter = next;
    void refresh();
  });
  void refresh();

  return () => {
    disposed = true;
    ++sequence;
    if (timer) clearTimeout(timer);
    unsubscribe();
    languageQaFindingsByVerse.set({});
  };
}
