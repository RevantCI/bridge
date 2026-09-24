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
//
// It is also Language QA's ONE status channel (performance contract of the
// layered-rules brief). The engine cannot push notifications: the sidecar
// reader in src-tauri/src/sidecar.rs routes a stdout line only to the pending
// request with its id. So there is one count-only languageQa.status poll,
// published as `languageQaChannel`. It polls every ACTIVE_POLL_MS while a pass
// is queued or running, backs off to IDLE_POLL_MS when idle, and polls at once
// when nudged after a local edit or decision. LanguageQaPanel reads this
// channel and fetches its own page only on demand. It no longer polls.
import { get, writable } from "svelte/store";
import { bridge } from "./api/bridgeClient";
import { currentChapter, languageQaFindingsByVerse, verseKey } from "./stores";
import type { LanguageQaFinding, LanguageQaStatus } from "./types/languageQa";

export const ACTIVE_POLL_MS = 500;
export const IDLE_POLL_MS = 10_000;

/** The latest count-only status (no findings), or the error of the last poll. */
export interface LanguageQaChannel {
  projectPath: string;
  status: LanguageQaStatus | null;
  error: string;
}

export const languageQaChannel = writable<LanguageQaChannel>({ projectPath: "", status: null, error: "" });

let nudgeActive: (() => void) | null = null;

/** Poll now instead of waiting out the idle back-off: called after a local
 * edit, decision or pause, which each start or change a pass. */
export function nudgeLanguageQa(): void {
  nudgeActive?.();
}

const ACTIVE_STATES = new Set(["queued", "running"]);

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
 * Run the status channel and keep the marks for $currentChapter until the
 * returned stop function is called.
 *
 * Each tick asks for the count-only status and publishes it. The marks are
 * fetched with languageQa.inline only when there is something new to show:
 * - a completed pass under a generation not yet drawn; or
 * - a chapter change. That draws at once, even mid-pass, since the old
 *   chapter's marks are no use.
 * During a pass the engine holds no findings, so marks are not replaced
 * mid-pass: the last pass's marks stay up instead of blinking out on every
 * rescan. The edited verse's own marks are cleared by saveVerseEdit.
 *
 * Only the newest request may write or schedule. A late answer for an old
 * chapter or another project is discarded. A failed poll keeps the marks and
 * reports the error on the channel.
 */
export function startLanguageQaInline(
  projectPath: string,
  { activeMs = ACTIVE_POLL_MS, idleMs = IDLE_POLL_MS }: { activeMs?: number; idleMs?: number } = {},
): () => void {
  let disposed = false;
  let sequence = 0;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let chapter = get(currentChapter);
  let drawnGeneration: number | null = null;
  let drawnChapter: string | null = null;
  let lastActive = true;
  languageQaChannel.set({ projectPath, status: null, error: "" });

  async function refresh(): Promise<void> {
    if (disposed) return;
    if (timer) clearTimeout(timer);
    const ticket = ++sequence;
    const requested = chapter;
    const stale = () => disposed || ticket !== sequence;
    try {
      const status = await bridge.languageQaStatus(projectPath, 0, 0);
      if (stale() || status.projectPath !== projectPath) return;
      lastActive = ACTIVE_STATES.has(status.state);
      languageQaChannel.set({ projectPath, status, error: "" });
      const newPass = status.state === "completed" && status.generation !== drawnGeneration;
      if (newPass || requested !== drawnChapter) {
        const inline = await bridge.languageQaInline(projectPath, requested);
        if (stale() || requested !== chapter || inline.projectPath !== projectPath) return;
        // A Svelte store notifies on every object write, same reference or
        // not, so an unchanged answer must not write at all.
        const current = get(languageQaFindingsByVerse);
        const patched = patchInlineFindings(current, groupInlineFindings(inline.findings));
        if (patched !== current) languageQaFindingsByVerse.set(patched);
        drawnChapter = requested;
        drawnGeneration = inline.state === "completed" ? inline.generation : drawnGeneration;
      }
    } catch (error) {
      if (!stale()) {
        languageQaChannel.update((value) => ({
          ...value, error: error instanceof Error ? error.message : String(error) }));
      }
    } finally {
      if (!disposed && ticket === sequence) {
        timer = setTimeout(() => void refresh(), lastActive ? activeMs : idleMs);
      }
    }
  }

  const unsubscribe = currentChapter.subscribe((next) => {
    if (next === chapter) return;
    chapter = next;
    void refresh();
  });
  nudgeActive = () => {
    lastActive = true;
    void refresh();
  };
  void refresh();

  return () => {
    disposed = true;
    ++sequence;
    if (timer) clearTimeout(timer);
    unsubscribe();
    nudgeActive = null;
    languageQaFindingsByVerse.set({});
    languageQaChannel.set({ projectPath: "", status: null, error: "" });
  };
}
