/** Wire types for engine/collection_jobs.py (collection.runChecks / qaStatus). */

export type CollectionBookState = "pending" | "running" | "done" | "skipped" | "failed";

export interface CollectionQaBook {
  bookId: string;
  bookName: string;
  path: string;
  state: CollectionBookState;
  elapsedSeconds: number | null;
  jobId: string | null;
  /** Open findings by source category (QaFinding category, or "languageQa"). */
  findingsByCategory: Record<string, number>;
  checkedVerses: number;
  error: string | null;
  completedAt: string | null;
}

export interface CollectionQaSnapshot {
  jobId: string;
  /** "idle" when no run exists in this session: `books` then holds each book's last recorded run. */
  state: "idle" | "queued" | "running" | "cancelling" | "succeeded" | "failed" | "cancelled";
  paused: boolean;
  collectionPath: string;
  checks: string[];
  totalBooks: number;
  completedBooks: number;
  percent: number;
  currentBook: string | null;
  books: CollectionQaBook[];
  /** The whole-collection stage, once every book is done. */
  finalStage: {
    completedAt?: string | null;
    termbaseCoverage?: Array<{ bookId: string; concepts: number; issues: unknown[] }>;
    crossBookNames?: { available: boolean; findings?: unknown[]; error?: string } | null;
    houseStylePropagation?: { available: boolean; reason?: string };
    error?: string;
  } | null;
  elapsedSeconds: number;
  estimatedRemainingSeconds: number | null;
  error: string | null;
  createdAt: string | null;
  finishedAt: string | null;
}
