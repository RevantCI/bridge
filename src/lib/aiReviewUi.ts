// AI review request, shared between ReviewPanel.svelte (which owns the AI
// review job/polling state and progress UI) and VerseList.svelte (the verse
// right-click menu, issue #69), so the menu can trigger a review without
// duplicating ReviewPanel's job-tracking state -- same reasoning as
// alignmentUi.ts and verseEditor.ts.
import { writable } from "svelte/store";

export type AIReviewScope = "verse" | "chapter" | "book";

export interface AIReviewRequest {
  chapter: string;
  verse: string;
  scope: AIReviewScope;
}

export const aiReviewRequest = writable<AIReviewRequest | null>(null);

/** Mirrors ReviewPanel's own `aiJobBusy` so other components can disable
 * their own "run AI review" controls without reaching into its state. */
export const aiJobActive = writable(false);

export function requestAIReview(chapter: string, verse: string, scope: AIReviewScope): void {
  aiReviewRequest.set({ chapter, verse, scope });
}
