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
  /** Present (as language-qa-4) on every finding scan_text's shared add()
   * helper produces, and on terminology.deprecated-form's own hand-built
   * dict -- null when no fix applies (e.g. a termbase entry with no
   * preferred rendering recorded yet). Today only terminology.deprecated-form
   * and tamil.vallinam-missing ever carry a real, non-null value. */
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
