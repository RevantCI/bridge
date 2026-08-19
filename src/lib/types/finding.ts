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

export interface ProjectInfo {
  path: string;
  bookId: string;
  bookName: string;
  targetLanguage: string;
  tcVersion: string;
  chapters: string[];
  checkTypes: Record<string, number>;
}

export interface VerseData {
  chapter: string;
  verse: string;
  text: string;
  alignment: VerseAlignment;
}

export interface SettingsData {
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
