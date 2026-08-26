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

export interface LexiconSegment {
  strong: string | null;
  morphLabel: string | null;
  partOfSpeech: string | null;
  lemma: string | null;
  translit: string | null;
  pron: string | null;
  meaning: string | null;
  usage: string | null;
  source: string | null;
}

export interface LexiconEntryResponse {
  languageId: string | null;
  segments: LexiconSegment[];
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

/**
 * Field names deliberately match alignment_reliability.compile_link_proposal's
 * own schema verbatim (snake_case), not this file's usual camelCase convention —
 * this object round-trips unchanged from alignment.aiPropose back into
 * alignment.aiApplyProposal, which expects exactly these keys. See
 * bridge_service.py's propose_ai_alignment for the full rationale.
 */
export interface AlignmentAiProposalGroup {
  top_ids: string[];
  bottom_ids: string[];
  confidence: number;
  reason: string;
  origin: "existing" | "ai_compiled" | "extended_protected" | "implicit" | "unresolved";
  relation?: string;
}

export interface AlignmentAiProposal {
  groups: AlignmentAiProposalGroup[];
  links: Array<{ top_id: string; bottom_id: string; confidence: number; reason: string }>;
  uncertain_links: Array<{ top_id: string; bottom_id: string; confidence: number; reason: string }>;
  implicit_top_ids: string[];
  target_only_ids: string[];
  review_notes: string[];
  diagnostics: Array<Record<string, unknown>>;
  conflicts: Array<Record<string, unknown>>;
  requires_human_review: boolean;
  compiler_version: string;
  mode: string;
  lock_policy: string;
  thresholds: { auto: number; review: number };
}

export interface AlignmentAiProposeResponse {
  proposal: AlignmentAiProposal;
  usage: { totalTokens: number; estimatedCostUSD: number };
}

/** Field names match AICheckReview.to_dict()/QAIssue.to_dict() verbatim (Python's own
 * dict output, snake_case) — this is display-only data, never sent back to the engine,
 * but declaring it with the wire shape it actually has avoids a silently-wrong type. */
export interface AiCheckReview {
  tool: string;
  group_id: string;
  check_id: string;
  source_quote: string;
  proposed_selection_ids: string[];
  proposed_selection_text: string[];
  proposed_selections: CheckTargetSelection[];
  nothing_to_select: boolean;
  verdict: "pass" | "review" | "problem" | "not_applicable";
  severity: "critical" | "high" | "medium" | "editorial" | "info";
  rationale: string;
  suggested_correction: string;
  confidence: number;
  evidence_used: Array<Record<string, unknown>>;
}

export interface AiQaIssue {
  code: string;
  severity: "critical" | "high" | "medium" | "editorial" | "info";
  title: string;
  detail: string;
  source: string;
  check_id?: string;
  group_id?: string;
  confidence?: number;
}

export interface AiExplainResult {
  summary: string;
  checkReviews: AiCheckReview[];
  qaIssues: AiQaIssue[];
  alignmentProposal: AlignmentAiProposal | null;
  alignmentWasAIProposed: boolean;
  usage: { totalTokens: number; estimatedCostUSD: number };
}

export interface DesktopConnectorState {
  connected: boolean;
  detected?: boolean;
  reference?: string;
  [key: string]: unknown;
}

export interface ProjectInfo {
  projectId?: string;
  collectionId?: string;
  managed?: boolean;
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
  originalLanguageResource?: {
    available: boolean;
    languageId?: string;
    resourceId?: string;
    version?: string;
    owner?: string;
    commit?: string;
    release?: string;
    license?: string;
    attribution?: string;
    projectVersion?: string;
    versionMismatch?: boolean;
    message?: string;
  };
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
  duplicates: DuplicateAssessment;
}

export type DuplicateClassification = "new" | "exactDuplicate" | "possibleDuplicate" | "partialOverlap";

export interface DuplicateMatch {
  match: "exact" | "possible";
  reason: "sourceFingerprint" | "bookLanguageBible";
  groupId: string;
  projectId: string;
  collectionId?: string;
  path: string;
  bookId: string;
  bookName: string;
  projectName?: string;
  bibleName?: string;
  lastOpenedAt?: string;
  missing: boolean;
}

export interface DuplicateAssessment {
  classification: DuplicateClassification;
  matches: DuplicateMatch[];
  inputBookCount: number;
  exactBookCount: number;
  missingExactBookCount: number;
  possibleBookCount: number;
  overlapBookCount: number;
  matchingGroupCount: number;
  exactMatchGroupId: string;
  sourceFingerprints: Record<string, string>;
  collectionFingerprint: string;
}

export interface RegisteredProject {
  projectId: string;
  collectionId?: string;
  path: string;
  managed: boolean;
  missing: boolean;
  bookId: string;
  bookName: string;
  targetLanguageId?: string;
  targetLanguage?: string;
  projectName?: string;
  bibleName?: string;
  lastOpenedAt?: string;
  bookCount?: number;
}

export interface ImportedProject {
  projectId?: string;
  collectionId?: string;
  directoryName?: string;
  path: string;
  bookId: string;
  bookName: string;
  chapters?: string[];
  checkIndexStatus?: string;
  lazy?: boolean;
}

/** Flattened `totals` block from a book's .bridge/progress.json rollup. */
export interface BookProgressSummary {
  chapterCount: number;
  checkedChapterCount: number;
  verseCount: number;
  checkedVerseCount: number;
  reviewedVerseCount: number;
  findingCount: number;
  approvedFindingCount: number;
  updatedAt: string | null;
}

export interface BookProgressEntry {
  path: string;
  bookId: string;
  bookName: string;
  lazy: boolean;
  missing: boolean;
  /** null = lazy sibling never opened, or a materialized book never checked yet. */
  progress: BookProgressSummary | null;
}

export interface VerseData {
  chapter: string;
  verse: string;
  text: string;
  alignment: VerseAlignment;
  alignmentStatus: AlignmentWorkStatus;
}

export type NativeCheckTool = "translationNotes" | "translationWords";
export type CheckSelectionStatus = "pending" | "selected" | "nothing_to_select" | "invalidated";
export type CheckEvaluationStatus = "not_run" | "running" | "passed" | "issue_open" | "needs_review" | "failed";
export type CheckSelectionProvenance = "none" | "existing_tc" | "human" | "bridge_ai";

export interface CheckTargetSelection {
  text: string;
  occurrence: number;
  occurrences: number;
}

export interface NativeCheckReview {
  chapter: string;
  verse: string;
  tool: NativeCheckTool;
  groupId: string;
  checkId: string;
  sourceQuote: string;
  sourceOccurrence: number | null;
  occurrenceNote: string;
  selections: CheckTargetSelection[];
  nothingToSelect: boolean;
  invalidated: boolean;
  stale: boolean;
  selectionStatus: CheckSelectionStatus;
  evaluationStatus: CheckEvaluationStatus;
  provenance: CheckSelectionProvenance;
  stateFingerprint: string;
}

export interface NativeCheckListResponse {
  chapter: string;
  verse: string;
  checks: NativeCheckReview[];
  state: "ready" | "preparing";
  retryAfterMs: number;
  message: string;
  aiReviewState: "missing" | "current" | "stale";
  aiReviews: AiCheckReview[];
  aiQaIssues: AiQaIssue[];
  aiSummary: string;
}

export interface CheckSelectionValidation {
  valid: boolean;
  errors: string[];
  selections: CheckTargetSelection[];
  ranges: Array<{ start: number; end: number }>;
  stateFingerprint: string;
}

export interface CheckSelectionMutation {
  committed: true;
  review: NativeCheckReview;
  files: Record<string, string>;
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

export interface AIReviewJobVerseResult {
  chapter: string;
  verse: string;
  status: "succeeded" | "failed";
  summary: string;
  checkReviews: AiCheckReview[];
  qaIssues: AiQaIssue[];
  appliedSelections: Array<Record<string, unknown>>;
  skippedSelections: Array<Record<string, unknown>>;
  alignmentProposal: AlignmentAiProposal | null;
  alignmentWasAIProposed: boolean;
  usage: { totalTokens: number; estimatedCostUSD: number };
  error: string | null;
}

export interface AIReviewJobVerseStatus {
  chapter: string;
  verse: string;
  status: "succeeded" | "failed";
  summary: string;
  appliedCount: number;
  skippedCount: number;
  usage: { totalTokens?: number; estimatedCostUSD?: number };
  error: string | null;
}

export interface AIReviewJobSnapshot {
  jobId: string;
  scope: "verse" | "chapter" | "book";
  mode: "basic" | "advanced";
  projectPath: string;
  state: CheckJobState;
  chapters: string[];
  chapterVerses: Record<string, string[]>;
  skippedCurrentVerses: number;
  resumeOf: string;
  totalVerses: number;
  completedVerses: number;
  failedVerses: number;
  percent: number;
  currentChapter: string | null;
  currentVerse: string | null;
  currentStage: string;
  results: Record<string, AIReviewJobVerseStatus>;
  latestResult: { key: string; result: AIReviewJobVerseResult } | null;
  error: string | null;
  createdAt: string;
  finishedAt: string | null;
}

export interface AIReviewChapterResponse {
  chapter: string;
  reviewsByVerse: Record<string, AiCheckReview[]>;
  states: Record<string, "missing" | "current" | "stale">;
  current: number;
  stale: number;
  missing: number;
}

export interface SettingsData {
  provider: string;
  apiBaseUrl: string;
  model: string;
  reviewerName: string;
  reviewerMode: "basic" | "advanced";
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
