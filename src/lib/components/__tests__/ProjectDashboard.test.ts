import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/svelte";

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
});
