import { describe, expect, it } from "vitest";

import {
  EMPTY_FILTERS,
  categoryBreakdown,
  chaptersForBook,
  checkOutcomes,
  exportFileName,
  familyProgress,
  filterRows,
  fixedByBreakdown,
  fixedByLabel,
  isFiltered,
  resultBreakdown,
  severityBreakdown,
} from "../../utils/reportStats";
import type { ReportRow } from "../../types/report";
import { reportBook, reportRow } from "./reportFixtures";

const rows: ReportRow[] = [
  reportRow({ id: "rut:a" }),
  reportRow({
    id: "rut:b", category: "translationNotes", engine: "translationNotes", chapter: "2", verse: "3",
    reference: "RUT 2:3", severity: "medium", status: "selected", resolution: "resolved", result: "pass",
    fixedBy: "machine", fixedByDetail: "Bridge AI", issue: "figs-metaphor: θεός", aiProposal: "Select: தேவன்",
  }),
  reportRow({
    id: "gen:c", book: "gen", bookName: "Genesis", category: "alignment", engine: "translationCore",
    checkType: "WA_INVALID", reference: "GEN 1:1", status: "ignored", resolution: "resolved", result: "pass",
    fixedBy: "human", fixedByDetail: "reviewer", note: "Alignment redone later.",
  }),
  reportRow({
    id: "gen:d", book: "gen", bookName: "Genesis", category: "translationWords", engine: "translationWords",
    chapter: "3", reference: "GEN 3:1", severity: "high", status: "pending", issue: "god: θεός",
  }),
];

describe("filterRows", () => {
  it("returns everything with empty filters", () => {
    expect(filterRows(rows, EMPTY_FILTERS)).toHaveLength(4);
    expect(isFiltered(EMPTY_FILTERS)).toBe(false);
  });

  it("filters by category, book, chapter, fixed-by, result, severity and text", () => {
    expect(filterRows(rows, { ...EMPTY_FILTERS, categories: ["translationNotes", "translationWords"] }).map((r) => r.id))
      .toEqual(["rut:b", "gen:d"]);
    expect(filterRows(rows, { ...EMPTY_FILTERS, book: "gen" }).map((r) => r.id)).toEqual(["gen:c", "gen:d"]);
    expect(filterRows(rows, { ...EMPTY_FILTERS, book: "gen", chapter: "3" }).map((r) => r.id)).toEqual(["gen:d"]);
    // A chapter without a book scopes nothing — chapter "3" exists in more than one book.
    expect(filterRows(rows, { ...EMPTY_FILTERS, chapter: "3" })).toHaveLength(4);
    expect(filterRows(rows, { ...EMPTY_FILTERS, fixedBy: "machine" }).map((r) => r.id)).toEqual(["rut:b"]);
    expect(filterRows(rows, { ...EMPTY_FILTERS, fixedBy: "human" }).map((r) => r.id)).toEqual(["gen:c"]);
    expect(filterRows(rows, { ...EMPTY_FILTERS, fixedBy: "unresolved" }).map((r) => r.id)).toEqual(["rut:a", "gen:d"]);
    expect(filterRows(rows, { ...EMPTY_FILTERS, result: "pass" }).map((r) => r.id)).toEqual(["rut:b", "gen:c"]);
    expect(filterRows(rows, { ...EMPTY_FILTERS, severity: "medium" }).map((r) => r.id)).toEqual(["rut:b"]);
    expect(filterRows(rows, { ...EMPTY_FILTERS, search: "redone" }).map((r) => r.id)).toEqual(["gen:c"]);
    expect(filterRows(rows, { ...EMPTY_FILTERS, search: "தேவன்" }).map((r) => r.id)).toEqual(["rut:b"]);
    expect(filterRows(rows, { ...EMPTY_FILTERS, search: "gen 3" }).map((r) => r.id)).toEqual(["gen:d"]);
  });

  it("lists a book's chapters in canonical order", () => {
    expect(chaptersForBook([...rows, reportRow({ book: "gen", chapter: "10" })], "gen")).toEqual(["1", "3", "10"]);
  });
});

describe("aggregates", () => {
  it("breaks issues down by category in the legend order", () => {
    const breakdown = categoryBreakdown(rows);
    expect(breakdown.map((b) => b.category)).toEqual([
      "translationNotes", "translationWords", "alignment", "greekRoom", "aiReview",
    ]);
    expect(breakdown.find((b) => b.category === "translationNotes")).toEqual({
      category: "translationNotes", total: 1, resolved: 1, unresolved: 0,
    });
    expect(breakdown.find((b) => b.category === "aiReview")?.total).toBe(0);
  });

  it("counts who fixed what, and pass versus fail", () => {
    expect(fixedByBreakdown(rows)).toEqual({ human: 1, machine: 1, unresolved: 2 });
    expect(resultBreakdown(rows)).toEqual({ pass: 2, fail: 2 });
    expect(severityBreakdown(rows).filter((s) => s.open > 0)).toEqual([{ severity: "high", open: 2 }]);
  });

  it("derives check-level outcomes from the book summaries, never counting unrun work as failed", () => {
    const outcomes = checkOutcomes([reportBook()]);
    expect(outcomes.map((o) => [o.family, o.passed, o.failed, o.notRun])).toEqual([
      ["greekRoom", 37, 3, 45],
      ["translationNotes", 83, 37, 0],
      ["translationWords", 0, 0, 0],
      ["alignment", 10, 7, 68],
    ]);
  });

  it("describes each book's progress bars", () => {
    const bars = familyProgress(reportBook());
    expect(bars.map((b) => [b.label, b.percent, b.detail])).toEqual([
      ["Greek Room", 47.1, "2/4 chapters"],
      ["tN", 69.2, "83/120 checks"],
      ["tW", 0, "no resource index"],
      ["Alignment", 11.8, "10/85 verses · 2 invalid"],
      ["AI review", 14.1, "12/85 verses · 3 stale"],
    ]);
    expect(familyProgress(reportBook({ lazy: true }))).toEqual([]);
  });

  it("labels fixed-by with the actor behind it", () => {
    expect(fixedByLabel(reportRow())).toBe("—");
    expect(fixedByLabel(reportRow({ resolution: "resolved", fixedBy: "machine", fixedByDetail: "Bridge AI" }))).toBe("Machine (Bridge AI)");
    expect(fixedByLabel(reportRow({ resolution: "resolved", fixedBy: "human", fixedByDetail: "reviewer" }))).toBe("Human");
    expect(fixedByLabel(reportRow({ resolution: "resolved", fixedBy: "human", fixedByDetail: "translationCore" }))).toBe("Human (translationCore)");
  });

  it("names the export file after the project", () => {
    expect(exportFileName("IRV Tamil (2024)", "csv")).toMatch(/^irv-tamil-2024-qa-report-\d{4}-\d{2}-\d{2}\.csv$/);
    expect(exportFileName("", "tsv")).toMatch(/^bridge-qa-report-.*\.tsv$/);
  });
});
