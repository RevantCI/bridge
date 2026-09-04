import { describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/svelte";

import ProjectDashboard from "../ProjectDashboard.svelte";
import type { ExceptionQueueRow, ProjectReport } from "../../types/finding";

const books = [{
  path: "/projects/rut",
  bookId: "rut",
  bookName: "Ruth",
  missing: false,
  lazy: false,
  progress: {
    chapterCount: 4,
    checkedChapterCount: 2,
    verseCount: 85,
    reviewedVerseCount: 10,
    updatedAt: "",
  },
}] as never;

function row(overrides: Partial<ExceptionQueueRow> = {}): ExceptionQueueRow {
  return {
    chapter: "1", verse: "1", critical: 0, high: 0, medium: 0,
    cache: "missing", wordAlignment: "valid", invalidChecks: 0, discussions: 0,
    finalState: "", summary: "",
    localFindings: [], helpsFindings: [],
    ...overrides,
  };
}

function report(rows: ExceptionQueueRow[]): ProjectReport {
  return {
    project: "Ruth", bookId: "rut",
    exceptionQueue: rows,
    qaSeverityCounts: {},
    needsDiscussion: [],
    publicationGate: {
      readyForHumanPublicationSignoff: true, criticalFindings: 0,
      highFindings: 0, staleAIReviews: 0, openDiscussions: 0,
    } as never,
    coverage: {
      verses: {
        counts: { PASS: 1, ISSUE: 0, REVIEW_REQUIRED: 0, NOT_CHECKED: 0 },
        totalVerses: 1, checkedPercent: 100,
      } as never,
      resources: {},
    },
  };
}

function mount(rows: ExceptionQueueRow[] = []) {
  return render(ProjectDashboard, {
    props: {
      projectName: "Ruth", books, loading: false, error: "",
      onSelectBook: () => {}, onPreviewBook: () => {}, onRetry: () => {},
      report: report(rows), reportLoading: false, reportError: "",
    },
  });
}

describe("ProjectDashboard", () => {
  it("labels the checked-chapters bar without the AI prefix", () => {
    mount();
    expect(screen.getByText("Checked 2/4 chapters")).toBeInTheDocument();
    expect(screen.queryByText(/AI-checked/)).not.toBeInTheDocument();
  });

  it("counts tN and tW problems on the verse row", () => {
    mount([row({
      helpsFindings: [
        {
          tool: "translationNotes", category: "translation_note", severity: "medium",
          checkType: "TC_PENDING", groupId: "figs-metaphor",
          explanation: "Review the figure of speech.",
        },
        {
          tool: "translationWords", category: "translation_word", severity: "high",
          checkType: "TC_INVALIDATED", groupId: "faith",
          explanation: "faith / tw-1 is invalidated.",
        },
      ],
    })]);
    expect(screen.getByText("1 tN")).toBeInTheDocument();
    expect(screen.getByText("1 tW")).toBeInTheDocument();
  });

  it("expands Greek Room and tN/tW findings together, colour-keyed by source", async () => {
    mount([row({
      localFindings: [{
        engine: "wildebeest", severity: "high", checkType: "wildebeest.script.mixed",
        explanation: "Mixed script in token.",
      }],
      helpsFindings: [{
        tool: "translationNotes", category: "translation_note", severity: "medium",
        checkType: "TC_PENDING", groupId: "figs-metaphor",
        explanation: "Review the figure of speech.",
      }],
    })]);

    await fireEvent.click(screen.getByRole("button", { name: /2 finding/ }));

    const greekRoom = screen.getByText("Mixed script in token.").closest(".local-finding-row");
    const note = screen.getByText("Review the figure of speech.").closest(".local-finding-row");
    expect(greekRoom?.className).toContain("source-gr");
    expect(note?.className).toContain("source-tn");
  });

  it("offers no expander when a row has nothing to detail", () => {
    mount([row({ high: 1 })]);
    expect(screen.queryByRole("button", { name: /finding/ })).not.toBeInTheDocument();
  });
});
