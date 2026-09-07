/**
 * Whole-collection QA report wire types.
 *
 * Mirrors engine/tc_ai_bridge/qa_report.py (rows, per-book summaries, the
 * collection payload) and engine/report_jobs.py (the job snapshot). Keep in
 * sync manually, like types/finding.ts.
 */
import type { TriageRecord } from "./finding";

export type { TriageRecord };

export type ReportCategory =
  | "greekRoom" | "translationNotes" | "translationWords" | "alignment" | "aiReview";

export type ReportSeverity = "critical" | "high" | "medium" | "low" | "info";
export type ReportResolution = "resolved" | "unresolved";
export type ReportResult = "pass" | "fail";
export type ReportFixedBy = "human" | "machine" | "";

/** One issue (or one tN/tW check) in the report table. */
export interface ReportRow {
  /** `<bookId>:<finding or check id>` — unique across the collection. */
  id: string;
  category: ReportCategory;
  /** wildebeest | usfm | names | local | translationNotes | translationWords | translationCore | ai */
  engine: string;
  checkType: string;
  severity: ReportSeverity;
  book: string;
  bookName: string;
  chapter: string;
  verse: string;
  /** "RUT 1:1" */
  reference: string;
  issue: string;
  explanation: string;
  aiProposal: string;
  /** pass | review | problem | not_applicable | "" — the AI review's verdict on a tN/tW check. */
  aiVerdict: string;
  /**
   * Raw state. Greek Room/alignment: open | accepted | rejected | ignored |
   * fixed | needs_discussion. tN/tW: pending | selected | nothing_to_select |
   * invalidated | stale (or a verse.decide status once ignored).
   */
  status: string;
  resolution: ReportResolution;
  result: ReportResult;
  fixedBy: ReportFixedBy;
  /** Reviewer name, "Bridge AI", "translationCore", or "reviewer". */
  fixedByDetail: string;
  decidedAt: string;
  note: string;
  /** The tN/tW selection text, or "nothing to select". */
  selection: string;
  /**
   * Key into the book's AI-triage store, for rows backed by a persisted
   * QaFinding. Empty for tN/tW/alignment/AI-review rows, which are workflow
   * state rather than checker output and are never triaged. The report
   * itself never reads a verdict — the screen merges triage.results by this
   * key — so an untriaged project renders exactly as it always did.
   */
  triageHash: string;
}

export type CheckState = "not_run" | "partial" | "complete" | "unavailable";

export interface GreekRoomCheckSummary {
  state: CheckState;
  checked: number;
  total: number;
  percent: number;
  checkedChapters: number;
  chapterCount: number;
  engines: { wildebeest: boolean; usfm: boolean; names: boolean };
  run: number;
  passed: number;
  failed: number;
}

export interface HelpsCheckSummary {
  state: CheckState;
  available: boolean;
  total: number;
  passed: number;
  failed: number;
  pending: number;
  invalidated: number;
  percent: number;
  run: number;
}

export interface AlignmentCheckSummary {
  state: CheckState;
  complete: number;
  partial: number;
  untouched: number;
  invalid: number;
  total: number;
  percent: number;
  run: number;
  passed: number;
  failed: number;
}

export interface AiReviewCheckSummary {
  state: CheckState;
  current: number;
  stale: number;
  missing: number;
  total: number;
  percent: number;
}

export interface BookChecks {
  greekRoom: GreekRoomCheckSummary;
  translationNotes: HelpsCheckSummary;
  translationWords: HelpsCheckSummary;
  alignment: AlignmentCheckSummary;
  aiReview: AiReviewCheckSummary;
}

export interface CheckResults {
  run: number;
  passed: number;
  failed: number;
}

export interface IssueSummary {
  total: number;
  resolved: number;
  unresolved: number;
  byCategory: Record<string, { total: number; resolved: number; unresolved: number }>;
  openBySeverity: Record<string, number>;
  byFixedBy: { human: number; machine: number; unresolved: number };
}

export interface ReportBookSummary {
  bookId: string;
  bookName: string;
  path: string;
  lazy: boolean;
  missing: boolean;
  error: string | null;
  chapterCount: number;
  verseCount: number;
  checks: BookChecks;
  checkResults: CheckResults;
  issues: IssueSummary;
  /** Wall-clock ms this book's report took to build. 0 for a book that was
   * never opened (saying "not checked" costs no I/O). */
  durationMs: number;
}

export interface QaReport {
  schemaVersion: number;
  generatedAt: string;
  projectName: string;
  bookCount: number;
  books: ReportBookSummary[];
  rows: ReportRow[];
  /** Collection-wide sums per check family (same keys as BookChecks, counts only). */
  checks: Record<string, Record<string, number>>;
  checkResults: CheckResults;
  issues: IssueSummary;
  note: string;
}

export type ReportJobState =
  | "queued" | "running" | "cancelling" | "succeeded" | "failed" | "cancelled";

export interface ReportJobSnapshot {
  jobId: string;
  state: ReportJobState;
  totalBooks: number;
  completedBooks: number;
  percent: number;
  currentBook: string | null;
  failedBooks: Array<{ bookId: string; error: string }>;
  /** Per-book build time, and their sum — the only measurement of report
   * generation cost that exists. Keyed by book id. */
  bookDurationsMs: Record<string, number>;
  totalDurationMs: number;
  error: string | null;
  createdAt: string;
  finishedAt: string | null;
  /** True once report.get will return a payload. */
  ready: boolean;
}

export interface ReportGetResponse extends ReportJobSnapshot {
  report: QaReport;
}

export interface ReportExportColumn {
  key: keyof ReportRow | string;
  label: string;
}

export interface ReportExportResult {
  written: boolean;
  path: string;
  rows: number;
  format: "csv" | "tsv";
}

// --- AI triage (engine/tc_ai_bridge/triage.py + engine/triage_jobs.py) ----
// An overlay on the report: verdicts are keyed by ReportRow.triageHash and
// merged client-side, so nothing here is required for the report to render.

/** triage.run when it declined to start — no API key, or nothing to triage. */
export interface TriageUnavailable {
  state: "unavailable";
  message: string;
  jobId: "";
  totalBooks: 0;
}

export interface TriageJobSnapshot {
  jobId: string;
  state: ReportJobState;
  force: boolean;
  totalBooks: number;
  completedBooks: number;
  percent: number;
  currentBook: string | null;
  currentChapter: string | null;
  /** Progress inside the book in flight, so a long single-book run still moves. */
  currentBookTriaged: number;
  currentBookSkipped: number;
  triaged: number;
  /** Findings not re-sent: already cached, or carrying a user override. */
  skipped: number;
  /** Verdicts dropped because the finding's evidence changed. */
  pruned: number;
  /** Model requests attempted, and how many produced nothing usable. When
   * every batch fails the run's state is "failed", not "succeeded". */
  batches: number;
  failedBatches: number;
  failedBooks: Array<{ bookId: string; error: string }>;
  books: Array<{
    bookId: string; bookName: string; findings: number; triaged: number;
    skipped: number; batches: number; failedBatches: number;
  }>;
  error: string | null;
  createdAt: string;
  finishedAt: string | null;
}

export type TriageRunResponse = TriageJobSnapshot | TriageUnavailable;

export function isTriageUnavailable(value: TriageRunResponse): value is TriageUnavailable {
  return (value as TriageUnavailable).state === "unavailable";
}

export interface TriageResultsResponse {
  /** triageHash -> verdict, flat across the collection (hashes embed the book). */
  entries: Record<string, TriageRecord>;
  books: Array<{ bookId: string; bookName: string; count: number }>;
  total: number;
  running: boolean;
  jobId: string;
  /** False when no API key is configured — the same question triage.run asks. */
  available: boolean;
  unavailableReason: string;
}

export interface TriageOverrideResponse {
  bookId: string;
  hash: string;
  record: TriageRecord;
}
