import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/svelte";

const { listChecksForVerse, listIssueResolutions } = vi.hoisted(() => ({
  listChecksForVerse: vi.fn(),
  listIssueResolutions: vi.fn(),
}));

vi.mock("../../api/bridgeClient", () => ({
  bridge: { listChecksForVerse, listIssueResolutions },
}));

import TranslationHelpsReview from "../TranslationHelpsReview.svelte";
import { nativeChecksByVerse, aiCheckReviewsByVerse } from "../../stores";
import type { CheckAutomationResult, NativeCheckReview } from "../../types/finding";

function check(overrides: Partial<NativeCheckReview> = {}): NativeCheckReview {
  return {
    chapter: "1",
    verse: "19",
    tool: "translationWords",
    groupId: "jesus",
    checkId: "q36v",
    sourceQuote: "Ἰησοῦ Χριστοῦ",
    sourceOccurrence: 1,
    occurrenceNote: "",
    selections: [],
    nothingToSelect: false,
    invalidated: false,
    stale: false,
    selectionStatus: "pending",
    evaluationStatus: "not_run",
    provenance: "none",
    stateFingerprint: "fp",
    automaticSelection: null,
    ...overrides,
  };
}

function applied(): CheckAutomationResult {
  return { outcome: "applied", reason: "" };
}

function skipped(reason: string): CheckAutomationResult {
  return { outcome: "skipped", reason };
}

function mount(checks: NativeCheckReview[]) {
  listChecksForVerse.mockResolvedValue({
    chapter: "1", verse: "19", checks, state: "ready", retryAfterMs: 0, message: "",
    aiReviewState: "current", aiReviews: [], aiQaIssues: [], aiSummary: "",
  });
  return render(TranslationHelpsReview, { props: { chapter: "1", verse: "19" } });
}

/**
 * The engine already decided, per check, whether it could select the words
 * automatically and why not. Until this was rendered, a check the AI declined
 * looked identical to one no AI had ever seen: "Pending", with no explanation.
 */
describe("TranslationHelpsReview automatic-selection outcome", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    nativeChecksByVerse.set({});
    aiCheckReviewsByVerse.set({});
    listIssueResolutions.mockResolvedValue({ items: [] });
  });

  it("says why a check the AI declined is still pending", async () => {
    mount([check({
      automaticSelection: skipped("AI confidence is below the 82% automatic-selection threshold"),
    })]);

    await waitFor(() => {
      expect(screen.getByText(/Left for you/)).toBeInTheDocument();
    });
    expect(
      screen.getByText(/AI confidence is below the 82% automatic-selection threshold/),
    ).toBeInTheDocument();
  });

  it("marks a check the AI selected, and tallies both against the verse", async () => {
    mount([
      check({
        checkId: "q36v",
        selections: [{ text: "यीशु", occurrence: 1, occurrences: 1 }],
        selectionStatus: "selected",
        provenance: "bridge_ai",
        automaticSelection: applied(),
      }),
      check({
        checkId: "zr2k",
        tool: "translationNotes",
        automaticSelection: skipped("Stage 3 mapping is not safe for a verse-local automatic selection"),
      }),
    ]);

    await waitFor(() => {
      expect(screen.getByText(/Selected automatically by the AI review/)).toBeInTheDocument();
    });
    expect(screen.getByText("1 of 2")).toBeInTheDocument();
    expect(screen.getByText(/1 selected by AI review/)).toBeInTheDocument();
    expect(screen.getByText("1 pending")).toBeInTheDocument();
  });

  it("does not credit the AI for a selection a human has since taken over", async () => {
    mount([check({
      selections: [{ text: "यीशु", occurrence: 1, occurrences: 1 }],
      selectionStatus: "selected",
      provenance: "human",
      automaticSelection: applied(),
    })]);

    await waitFor(() => {
      expect(screen.getByText("1 of 1")).toBeInTheDocument();
    });
    expect(screen.queryByText(/Selected automatically by the AI review/)).not.toBeInTheDocument();
    expect(screen.queryByText(/selected by AI review/)).not.toBeInTheDocument();
  });

  it("keeps the run-AI-review prompt when no automatic pass has run", async () => {
    mount([check()]);

    await waitFor(() => {
      expect(screen.getByText(/Run AI review to evaluate these checks/)).toBeInTheDocument();
    });
    expect(screen.queryByText(/Left for you/)).not.toBeInTheDocument();
  });
});
