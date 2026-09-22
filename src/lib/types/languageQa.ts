export interface LanguageQaFinding {
  id: string;
  book: string;
  chapter: string;
  verse: string;
  rule: string;
  severity: string;
  start: number;
  end: number;
  originalText: string;
  message: string;
  textHash: string;
  ruleVersion: string;
  status: "review-needed";
  /** Only present on terminology.deprecated-form findings; null when the
   * termbase entry has no preferred rendering recorded yet. Absent (not
   * just undefined) on every other Language QA rule. */
  suggestedReplacement?: string | null;
}

export interface LanguageQaStatus {
  projectPath: string;
  book: string;
  generation: number;
  state: "idle" | "queued" | "running" | "completed" | "paused" | "failed";
  ruleVersion: string;
  language?: {
    declared: string;
    language: string;
    script: string;
    basis: string;
    pack: string;
    message: string;
  };
  findings: LanguageQaFinding[];
  totalFindings: number;
  offset: number;
  completedChapters?: number;
  totalChapters?: number;
  checkedVerses?: number;
  skippedVerses?: number;
  incomplete?: boolean;
  limitations: string[];
  error?: string;
  coverage: string;
  storage: string;
}
