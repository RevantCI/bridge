import type { AIReviewJobSnapshot } from "../types/finding";

/**
 * Return whether an AI review job belongs in the currently displayed review
 * panel. The worker may keep running while the user navigates elsewhere, but
 * its progress/completion card must never look like the result of an unrelated
 * verse, chapter, or project.
 */
export function aiJobAppliesToReference(
  job: AIReviewJobSnapshot,
  projectPath: string,
  chapter: string,
  verse: string | null,
): boolean {
  if (!projectPath || job.projectPath !== projectPath) return false;
  if (job.scope === "book") return true;
  if (job.scope === "chapter") return job.chapters.includes(chapter);
  return Boolean(
    verse
    && job.chapters.includes(chapter)
    && (job.chapterVerses[chapter] ?? []).includes(verse)
  );
}

export function isAIReviewJobActive(job: AIReviewJobSnapshot | null): boolean {
  return Boolean(job && ["queued", "running", "cancelling"].includes(job.state));
}
