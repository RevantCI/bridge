import type { QaReport, ReportBookSummary, ReportRow } from "../../types/report";

export function reportRow(overrides: Partial<ReportRow> = {}): ReportRow {
  return {
    id: "rut:x", category: "greekRoom", engine: "wildebeest", checkType: "wildebeest.script.mixed",
    severity: "high", book: "rut", bookName: "Ruth", chapter: "1", verse: "1", reference: "RUT 1:1",
    issue: "Mixed script", explanation: "Latin character inside Tamil text.", aiProposal: "",
    aiVerdict: "", status: "open", resolution: "unresolved", result: "fail", fixedBy: "",
    fixedByDetail: "", decidedAt: "", note: "", selection: "",
    ...overrides,
  };
}

export function reportBook(overrides: Partial<ReportBookSummary> = {}): ReportBookSummary {
  return {
    bookId: "rut", bookName: "Ruth", path: "/p/rut", lazy: false, missing: false, error: null,
    chapterCount: 4, verseCount: 85,
    checks: {
      greekRoom: {
        state: "partial", checked: 40, total: 85, percent: 47.1, checkedChapters: 2, chapterCount: 4,
        engines: { wildebeest: true, usfm: true, names: false }, run: 40, passed: 37, failed: 3,
      },
      translationNotes: {
        state: "partial", available: true, total: 120, passed: 83, failed: 37, pending: 30,
        invalidated: 7, percent: 69.2, run: 120,
      },
      translationWords: {
        state: "unavailable", available: false, total: 0, passed: 0, failed: 0, pending: 0,
        invalidated: 0, percent: 0, run: 0,
      },
      alignment: {
        state: "partial", complete: 10, partial: 5, untouched: 68, invalid: 2, total: 85,
        percent: 11.8, run: 17, passed: 10, failed: 7,
      },
      aiReview: { state: "partial", current: 12, stale: 3, missing: 70, total: 85, percent: 14.1 },
    },
    checkResults: { run: 177, passed: 130, failed: 47 },
    issues: {
      total: 0, resolved: 0, unresolved: 0, byCategory: {}, openBySeverity: {},
      byFixedBy: { human: 0, machine: 0, unresolved: 0 },
    },
    ...overrides,
  };
}

/** Two books, four rows: two open (rut Greek Room, gen tW pending), two resolved. */
export const sampleRows: ReportRow[] = [
  reportRow({ id: "rut:a" }),
  reportRow({
    id: "rut:b", category: "translationNotes", engine: "translationNotes", chapter: "2", verse: "3",
    reference: "RUT 2:3", severity: "medium", status: "selected", resolution: "resolved", result: "pass",
    fixedBy: "machine", fixedByDetail: "Bridge AI", issue: "figs-metaphor: θεός", aiProposal: "Select: தேவன்",
  }),
  reportRow({
    id: "gen:c", book: "gen", bookName: "Genesis", category: "alignment", engine: "translationCore",
    checkType: "WA_INVALID", reference: "GEN 1:1", issue: "Word Alignment recheck required",
    status: "ignored", resolution: "resolved", result: "pass",
    fixedBy: "human", fixedByDetail: "reviewer", note: "Alignment redone later.",
  }),
  reportRow({
    id: "gen:d", book: "gen", bookName: "Genesis", category: "translationWords", engine: "translationWords",
    chapter: "3", reference: "GEN 3:1", severity: "high", status: "pending", issue: "god: θεός",
    explanation: "Key term 'god' — source 'θεός'.",
  }),
];

export function sampleReport(overrides: Partial<QaReport> = {}): QaReport {
  return {
    schemaVersion: 1,
    generatedAt: "2026-09-04T10:00:00Z",
    projectName: "IRV Tamil",
    bookCount: 2,
    books: [reportBook(), reportBook({ bookId: "gen", bookName: "Genesis", path: "/p/gen" })],
    rows: sampleRows,
    checks: {},
    checkResults: { run: 354, passed: 260, failed: 94 },
    issues: {
      total: 4, resolved: 2, unresolved: 2, byCategory: {}, openBySeverity: { high: 2 },
      byFixedBy: { human: 1, machine: 1, unresolved: 2 },
    },
    note: "Advisory only.",
    ...overrides,
  };
}
