// Mirrors engine/greek_room_engine/models/finding.py and the response
// shapes bridge_service.py actually returns. Keep in sync manually.

export type FindingCategory =
  | "structure" | "unicode" | "spelling" | "names" | "repetition"
  | "alignment" | "consistency" | "omission_addition"
  | "translation_word" | "translation_note";

export type Severity = "high" | "medium" | "low" | "info";

export type FindingStatus =
  | "open" | "accepted" | "rejected" | "ignored" | "fixed" | "needs_discussion";

export interface EvidenceItem {
  label: string;
  value: string;
}

export interface QaFinding {
  id: string;
  project_id: string;
  book: string;
  chapter: number;
  verse: number;
  start_offset: number | null;
  end_offset: number | null;
  original_text: string;
  engine: string;
  check_type: string;
  category: FindingCategory;
  severity: Severity;
  confidence: number;
  suggested_replacement: string | null;
  explanation: string;
  evidence: EvidenceItem[];
  engine_version: string;
  status: FindingStatus;
  human_comment: string | null;
  created_at: string;
  resolved_at: string | null;
}

export interface TokenRef {
  word: string;
  occurrence: number;
  occurrences: number;
  strong?: string;
  lemma?: string;
  morph?: string;
  type?: string;
}

export interface AlignmentGroup {
  topWords: TokenRef[];
  bottomWords: TokenRef[];
}

export interface VerseAlignment {
  alignments: AlignmentGroup[];
  wordBank: TokenRef[];
}

export type AlignmentWorkStatus = "complete" | "partial" | "untouched" | "invalid";

export interface AlignmentToken extends TokenRef {
  id: string;
}

export interface AlignmentGroupView {
  id: string;
  topIds: string[];
  bottomIds: string[];
}

export interface AlignmentHistoryEntry {
  id: string;
  operation: string;
  timestamp: string;
}

export interface AlignmentCounts {
  complete: number;
  partial: number;
  untouched: number;
  invalid: number;
}

export interface AlignmentContext {
  chapter: string;
  verse: string;
  alignment: VerseAlignment;
  topTokens: AlignmentToken[];
  bottomTokens: AlignmentToken[];
  groups: AlignmentGroupView[];
  status: AlignmentWorkStatus;
  completionState: "pending" | "completed" | "invalid";
  sourceAvailable: boolean;
  sourceMessage: string;
  sourceDirection: "ltr" | "rtl";
  targetDirection: "ltr" | "rtl";
  issues: string[];
  canComplete: boolean;
  history: AlignmentHistoryEntry[];
  chapterStatus: AlignmentCounts;
}

export interface AlignmentStatusResponse {
  chapter: string;
  counts: AlignmentCounts;
  verses: Record<string, AlignmentWorkStatus>;
}

export interface ProjectInfo {
  path: string;
  bookId: string;
  bookName: string;
  targetLanguage: string;
  targetLanguageId?: string;
  targetLanguageDirection?: string;
  projectName?: string;
  bibleName?: string;
  tcVersion: string;
  chapters: string[];
  checkTypes: Record<string, number>;
  importedProjects?: ImportedProject[];
}

export interface ImportBook {
  bookId: string;
  bookName: string;
  sourceFile: string;
  verseCount: number | null;
  hasAlignments: boolean;
}

export interface ImportMetadata {
  languageId: string;
  languageName: string;
  languageDirection: "ltr" | "rtl" | "";
  projectName: string;
  bibleName: string;
  resourceId?: string;
}

export interface ImportPreview {
  sourcePath: string;
  kind: "usfm" | "usfmCollection" | "paratext" | "translationCore" | "translationCoreArchive";
  metadata: ImportMetadata;
  books: ImportBook[];
  missingFields: string[];
  warnings: string[];
}

export interface ImportedProject {
  path: string;
  bookId: string;
  bookName: string;
  chapters?: string[];
  checkIndexStatus?: string;
  lazy?: boolean;
}

export interface VerseData {
  chapter: string;
  verse: string;
  text: string;
  alignment: VerseAlignment;
  alignmentStatus: AlignmentWorkStatus;
}

export type CheckJobState =
  | "queued" | "running" | "cancelling" | "succeeded" | "failed" | "cancelled";

export interface CheckJobVerseResult {
  chapter: string;
  verse: string;
  status: "succeeded" | "failed";
  findings: QaFinding[];
  error: string | null;
}

export interface CheckJobSnapshot {
  jobId: string;
  scope: "chapter" | "book";
  projectPath: string;
  state: CheckJobState;
  checks: string[];
  chapters: string[];
  chapterVerses: Record<string, string[]>;
  totalVerses: number;
  completedVerses: number;
  failedVerses: number;
  percent: number;
  currentChapter: string | null;
  currentVerse: string | null;
  currentStage: string;
  results: Record<string, CheckJobVerseResult>;
  error: string | null;
  createdAt: string;
  finishedAt: string | null;
}

export interface SettingsData {
  provider: string;
  apiBaseUrl: string;
  model: string;
  reviewerName: string;
  paratextUsername: string;
  hasApiKey: boolean;
  aiUsage: { tokens: number; estimatedCostUSD: number };
}

export const STATUS_COLOR: Record<string, string> = {
  passed: "#22c55e",
  needs_review: "#f59e0b",
  problem: "#ef4444",
  checking: "#3b82f6",
  not_checked: "#9ca3af",
  ignored: "#a855f7",
};
