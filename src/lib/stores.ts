import { writable, derived, get } from "svelte/store";
import type { AiCheckReview, AlignmentWorkStatus, NativeCheckReview, NavigationSyncState, ProjectInfo, QaFinding } from "./types/finding";
import type { EngineLogEntry } from "./api/bridgeClient";

export function verseKey(chapter: string, verse: string): string {
  return `${chapter}:${verse}`;
}

export const project = writable<ProjectInfo | null>(null);
export const currentChapter = writable<string>("1");

// Keyed by chapter number -> list of verse numbers in that chapter.
export const chapterVerseNums = writable<Record<string, string[]>>({});

// Keyed by "chapter:verse" (verseKey) so multiple chapters can coexist
// without collisions — needed for chapter switching and "Run whole book"
// (verse "1" in chapter 1 and verse "1" in chapter 2 are different keys).
export const verseTexts = writable<Record<string, string>>({});
export const findingsByVerse = writable<Record<string, QaFinding[]>>({});
export type CheckStatus = "pending" | "succeeded" | "failed" | "cancelled";
export const checkStatusByVerse = writable<Record<string, CheckStatus>>({});
export const alignmentStatusByVerse = writable<Record<string, AlignmentWorkStatus>>({});
export const nativeChecksByVerse = writable<Record<string, NativeCheckReview[]>>({});
export const aiCheckReviewsByVerse = writable<Record<string, AiCheckReview[]>>({});
export const reviewerMode = writable<"basic" | "advanced">("basic");

// Which chapters have had their verse text + checks loaded already, so
// switching back to a chapter you've already visited doesn't re-fetch.
export const loadedChapters = writable<Record<string, boolean>>({});

export const selectedVerse = writable<string | null>(null);

// Clears everything keyed by the previously open book's chapter/verse
// numbers. Chapter "1" in one book is unrelated to chapter "1" in another,
// so switching books must not let stale entries from the old book show
// through under the new book's chapter/verse selectors.
export function resetBookState(): void {
  chapterVerseNums.set({});
  verseTexts.set({});
  findingsByVerse.set({});
  checkStatusByVerse.set({});
  alignmentStatusByVerse.set({});
  nativeChecksByVerse.set({});
  aiCheckReviewsByVerse.set({});
  loadedChapters.set({});
  selectedVerse.set(null);
  checkingProgress.set({ running: false, percent: 0, label: "", jobId: "", state: "idle", error: "", scope: "chapter" });
}

export interface CheckingProgress {
  running: boolean;
  percent: number;
  label: string;
  jobId: string;
  state: "idle" | "queued" | "running" | "cancelling" | "succeeded" | "failed" | "cancelled";
  error: string;
  scope: "chapter" | "book";
}

export const checkingProgress = writable<CheckingProgress>({
  running: false, percent: 0, label: "", jobId: "", state: "idle", error: "", scope: "chapter",
});

export const settingsOpen = writable(false);
export const exportOpen = writable(false);
export const showSource = writable(false);
export const diagnosticsOpen = writable(false);

const disconnectedNavigationTarget = {
  enabled: false, checking: false, connected: false, reference: "", error: "", checkedAt: 0,
};
export const navigationStatus = writable<NavigationSyncState>({
  enabled: false,
  ownsNavigation: false,
  ownerConflict: false,
  currentReference: "",
  currentOrigin: "bridge",
  candidate: null,
  paratext: { ...disconnectedNavigationTarget },
  logos: { ...disconnectedNavigationTarget },
});

const ENGINE_LOG_CAPACITY = 400;
export const engineLog = writable<EngineLogEntry[]>([]);

export function appendEngineLog(entry: EngineLogEntry): void {
  engineLog.update((entries) => {
    const next = [...entries, entry];
    return next.length > ENGINE_LOG_CAPACITY ? next.slice(next.length - ENGINE_LOG_CAPACITY) : next;
  });
}

export const verseNums = derived(
  [chapterVerseNums, currentChapter],
  ([$chapterVerseNums, $currentChapter]) => $chapterVerseNums[$currentChapter] ?? []
);

export const selectedFindings = derived(
  [findingsByVerse, currentChapter, selectedVerse],
  ([$findingsByVerse, $currentChapter, $selectedVerse]) =>
    $selectedVerse ? $findingsByVerse[verseKey($currentChapter, $selectedVerse)] ?? [] : []
);

export const approvedCount = derived(
  [findingsByVerse, checkStatusByVerse, currentChapter, verseNums],
  ([$findingsByVerse, $checkStatusByVerse, $currentChapter, $verseNums]) =>
    $verseNums.filter((v) =>
      $checkStatusByVerse[verseKey($currentChapter, v)] === "succeeded" &&
      ($findingsByVerse[verseKey($currentChapter, v)] ?? []).every((f) => f.status !== "open")
    ).length
);

// Book-wide: how many chapters are fully approved, for "Run whole book"
// progress and the Export-enabled check (all chapters, not just current).
export function bookApprovedSummary(): { approvedChapters: number; totalChapters: number } {
  const proj = get(project);
  const loaded = get(loadedChapters);
  const cvn = get(chapterVerseNums);
  const fbv = get(findingsByVerse);
  const statuses = get(checkStatusByVerse);
  if (!proj) return { approvedChapters: 0, totalChapters: 0 };
  const chapters = proj.chapters;
  let approvedChapters = 0;
  for (const ch of chapters) {
    if (!loaded[ch]) continue;
    const verses = cvn[ch] ?? [];
    if (verses.length === 0) continue;
    const allApproved = verses.every((v) =>
      statuses[verseKey(ch, v)] === "succeeded" &&
      (fbv[verseKey(ch, v)] ?? []).every((f) => f.status !== "open")
    );
    if (allApproved) approvedChapters++;
  }
  return { approvedChapters, totalChapters: chapters.length };
}
