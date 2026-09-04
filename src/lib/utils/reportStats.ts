/**
 * Pure helpers behind the project QA report screen: filtering the rows the
 * engine sends (engine/tc_ai_bridge/qa_report.py), and the small aggregates
 * the charts, stat tiles and book list draw. Kept out of the component so
 * they can be unit-tested against plain data.
 */
import type {
  ReportBookSummary,
  ReportCategory,
  ReportExportColumn,
  ReportFixedBy,
  ReportResult,
  ReportRow,
  ReportSeverity,
} from "../types/report";

export const CATEGORY_ORDER: ReportCategory[] = [
  "translationNotes", "translationWords", "alignment", "greekRoom", "aiReview",
];

export const CATEGORY_LABELS: Record<ReportCategory, string> = {
  translationNotes: "tN",
  translationWords: "tW",
  alignment: "Alignment",
  greekRoom: "Greek Room",
  aiReview: "AI review",
};

export const CATEGORY_LONG_LABELS: Record<ReportCategory, string> = {
  translationNotes: "translationNotes",
  translationWords: "translationWords",
  alignment: "Word alignment",
  greekRoom: "Greek Room (Wildebeest, USFM, Names, local)",
  aiReview: "AI review observations",
};

export const SEVERITY_ORDER: ReportSeverity[] = ["critical", "high", "medium", "low", "info"];

export type FixedByFilter = "" | "human" | "machine" | "unresolved";

export interface ReportFilters {
  /** Empty = every category. */
  categories: ReportCategory[];
  /** Book id, or "" for every book. */
  book: string;
  /** Chapter number, or "" for every chapter (only meaningful with a book). */
  chapter: string;
  fixedBy: FixedByFilter;
  result: "" | ReportResult;
  severity: "" | ReportSeverity;
  /** Case-insensitive substring over reference, issue, explanation, proposal, note. */
  search: string;
}

export const EMPTY_FILTERS: ReportFilters = {
  categories: [], book: "", chapter: "", fixedBy: "", result: "", severity: "", search: "",
};

export function isFiltered(filters: ReportFilters): boolean {
  return filters.categories.length > 0 || filters.book !== "" || filters.chapter !== ""
    || filters.fixedBy !== "" || filters.result !== "" || filters.severity !== ""
    || filters.search.trim() !== "";
}

function matchesFixedBy(row: ReportRow, value: FixedByFilter): boolean {
  if (!value) return true;
  if (value === "unresolved") return row.resolution === "unresolved";
  return row.resolution === "resolved" && row.fixedBy === value;
}

export function filterRows(rows: ReportRow[], filters: ReportFilters): ReportRow[] {
  const needle = filters.search.trim().toLocaleLowerCase();
  return rows.filter((row) => {
    if (filters.categories.length > 0 && !filters.categories.includes(row.category)) return false;
    if (filters.book && row.book !== filters.book) return false;
    if (filters.book && filters.chapter && row.chapter !== filters.chapter) return false;
    if (!matchesFixedBy(row, filters.fixedBy)) return false;
    if (filters.result && row.result !== filters.result) return false;
    if (filters.severity && row.severity !== filters.severity) return false;
    if (needle) {
      const haystack = [row.reference, row.issue, row.explanation, row.aiProposal, row.note, row.checkType]
        .join("\n").toLocaleLowerCase();
      if (!haystack.includes(needle)) return false;
    }
    return true;
  });
}

/** Chapters that have at least one row for the book, in canonical order. */
export function chaptersForBook(rows: ReportRow[], book: string): string[] {
  const seen = new Set<string>();
  for (const row of rows) if (row.book === book) seen.add(row.chapter);
  return [...seen].sort((a, b) => {
    const na = Number(a), nb = Number(b);
    if (Number.isFinite(na) && Number.isFinite(nb)) return na - nb;
    return a.localeCompare(b);
  });
}

export interface CategoryCount {
  category: ReportCategory;
  total: number;
  resolved: number;
  unresolved: number;
}

export function categoryBreakdown(rows: ReportRow[]): CategoryCount[] {
  const counts = new Map<ReportCategory, CategoryCount>();
  for (const category of CATEGORY_ORDER) counts.set(category, { category, total: 0, resolved: 0, unresolved: 0 });
  for (const row of rows) {
    const bucket = counts.get(row.category);
    if (!bucket) continue;
    bucket.total += 1;
    if (row.resolution === "resolved") bucket.resolved += 1;
    else bucket.unresolved += 1;
  }
  return [...counts.values()];
}

export interface FixedByCount {
  human: number;
  machine: number;
  unresolved: number;
}

export function fixedByBreakdown(rows: ReportRow[]): FixedByCount {
  const out: FixedByCount = { human: 0, machine: 0, unresolved: 0 };
  for (const row of rows) {
    if (row.resolution !== "resolved") out.unresolved += 1;
    else if (row.fixedBy === "machine") out.machine += 1;
    else out.human += 1;
  }
  return out;
}

export function resultBreakdown(rows: ReportRow[]): { pass: number; fail: number } {
  let pass = 0;
  for (const row of rows) if (row.result === "pass") pass += 1;
  return { pass, fail: rows.length - pass };
}

export function severityBreakdown(rows: ReportRow[]): Array<{ severity: ReportSeverity; open: number }> {
  const counts = new Map<ReportSeverity, number>(SEVERITY_ORDER.map((s) => [s, 0]));
  for (const row of rows) {
    if (row.resolution !== "unresolved") continue;
    counts.set(row.severity, (counts.get(row.severity) ?? 0) + 1);
  }
  return SEVERITY_ORDER.map((severity) => ({ severity, open: counts.get(severity) ?? 0 }));
}

export type CheckFamily = "greekRoom" | "translationNotes" | "translationWords" | "alignment";

export const CHECK_FAMILY_ORDER: CheckFamily[] = ["greekRoom", "translationNotes", "translationWords", "alignment"];

export const CHECK_FAMILY_LABELS: Record<CheckFamily, string> = {
  greekRoom: "Greek Room",
  translationNotes: "tN checks",
  translationWords: "tW checks",
  alignment: "Alignment",
};

export interface CheckOutcome {
  family: CheckFamily;
  label: string;
  passed: number;
  failed: number;
  notRun: number;
  /** What one unit is: a verse or a check. */
  unit: "verses" | "checks";
}

/**
 * Check-level pass/fail per family, summed over the given books. A verse
 * or check that was never run is "not run", never a failure — the point
 * of this chart is to show what has and hasn't been checked.
 */
export function checkOutcomes(books: ReportBookSummary[]): CheckOutcome[] {
  const out: CheckOutcome[] = CHECK_FAMILY_ORDER.map((family) => ({
    family, label: CHECK_FAMILY_LABELS[family], passed: 0, failed: 0, notRun: 0,
    unit: family === "greekRoom" || family === "alignment" ? "verses" : "checks",
  }));
  for (const book of books) {
    const gr = book.checks.greekRoom;
    out[0].passed += gr.passed;
    out[0].failed += gr.failed;
    out[0].notRun += Math.max(0, gr.total - gr.run);
    const tn = book.checks.translationNotes;
    out[1].passed += tn.passed;
    out[1].failed += tn.failed;
    const tw = book.checks.translationWords;
    out[2].passed += tw.passed;
    out[2].failed += tw.failed;
    const al = book.checks.alignment;
    out[3].passed += al.passed;
    out[3].failed += al.failed;
    out[3].notRun += al.untouched;
  }
  return out;
}

export interface FamilyProgress {
  family: CheckFamily | "aiReview";
  label: string;
  percent: number;
  state: "not_run" | "partial" | "complete" | "unavailable";
  /** Short, e.g. "12/40 chapters", "83/120 checks", "not materialized". */
  detail: string;
}

/** The four (plus AI review) progress bars on a book row. */
export function familyProgress(book: ReportBookSummary): FamilyProgress[] {
  if (book.lazy || book.missing || book.error) {
    return [];
  }
  const { greekRoom, translationNotes, translationWords, alignment, aiReview } = book.checks;
  const helps = (label: string, summary: typeof translationNotes): FamilyProgress => ({
    family: label === "tN" ? "translationNotes" : "translationWords",
    label,
    percent: summary.percent,
    state: summary.state,
    detail: !summary.available
      ? "no resource index"
      : summary.total === 0
        ? "no checks"
        : `${summary.passed}/${summary.total} checks`,
  });
  return [
    {
      family: "greekRoom", label: "Greek Room", percent: greekRoom.percent, state: greekRoom.state,
      detail: greekRoom.checked === 0
        ? "not run"
        : `${greekRoom.checkedChapters}/${greekRoom.chapterCount} chapters`,
    },
    helps("tN", translationNotes),
    helps("tW", translationWords),
    {
      family: "alignment", label: "Alignment", percent: alignment.percent, state: alignment.state,
      detail: alignment.total === 0
        ? "no verses"
        : `${alignment.complete}/${alignment.total} verses${alignment.invalid ? ` · ${alignment.invalid} invalid` : ""}`,
    },
    {
      family: "aiReview", label: "AI review", percent: aiReview.percent, state: aiReview.state,
      detail: aiReview.current === 0 && aiReview.stale === 0
        ? "not run"
        : `${aiReview.current}/${aiReview.total} verses${aiReview.stale ? ` · ${aiReview.stale} stale` : ""}`,
    },
  ];
}

export function bookDisplayName(book: Pick<ReportBookSummary, "bookId" | "bookName">): string {
  return book.bookName || book.bookId.toUpperCase();
}

export const FIXED_BY_LABELS: Record<ReportFixedBy | "unresolved", string> = {
  human: "Human",
  machine: "Machine",
  "": "—",
  unresolved: "Unresolved",
};

export function fixedByLabel(row: Pick<ReportRow, "resolution" | "fixedBy" | "fixedByDetail">): string {
  if (row.resolution !== "resolved") return "—";
  const base = row.fixedBy === "machine" ? "Machine" : "Human";
  return row.fixedByDetail && row.fixedByDetail !== "reviewer" ? `${base} (${row.fixedByDetail})` : base;
}

const STATUS_LABELS: Record<string, string> = {
  open: "open",
  needs_discussion: "needs discussion",
  accepted: "accepted",
  rejected: "rejected",
  ignored: "ignored",
  fixed: "fixed",
  pending: "pending",
  selected: "selected",
  nothing_to_select: "nothing to select",
  invalidated: "invalidated",
  stale: "stale after edit",
};

export function statusLabel(status: string): string {
  return STATUS_LABELS[status] ?? status.replace(/_/g, " ");
}

/** Columns the CSV/TSV export writes — the table's columns plus the fields behind them. */
export const EXPORT_COLUMNS: ReportExportColumn[] = [
  { key: "category", label: "Error category" },
  { key: "book", label: "Book" },
  { key: "chapter", label: "Chapter" },
  { key: "verse", label: "Verse" },
  { key: "reference", label: "Reference" },
  { key: "issue", label: "Issue" },
  { key: "explanation", label: "Explanation" },
  { key: "aiProposal", label: "AI proposal" },
  { key: "fixedBy", label: "Fixed by" },
  { key: "fixedByDetail", label: "Fixed by (detail)" },
  { key: "result", label: "Pass or fail" },
  { key: "status", label: "Status" },
  { key: "severity", label: "Severity" },
  { key: "engine", label: "Engine" },
  { key: "checkType", label: "Check" },
  { key: "selection", label: "Selection" },
  { key: "note", label: "Reviewer note" },
  { key: "decidedAt", label: "Decided at" },
];

export function exportFileName(projectName: string, format: "csv" | "tsv"): string {
  const stem = (projectName || "bridge").replace(/[^\p{L}\p{N}]+/gu, "-").replace(/^-+|-+$/g, "").toLowerCase() || "bridge";
  const stamp = new Date().toISOString().slice(0, 10);
  return `${stem}-qa-report-${stamp}.${format}`;
}

/** Category rows the export/table label with the same short names the charts use. */
export function exportRows(rows: ReportRow[]): ReportRow[] {
  return rows.map((row) => ({ ...row, category: CATEGORY_LABELS[row.category] as ReportCategory }));
}
