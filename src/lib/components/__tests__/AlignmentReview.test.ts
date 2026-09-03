import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/svelte";

// The shell mounts QA mode, which loads the queue on mount; stub the
// transport so these tests exercise the shell rather than the sidecar.
vi.mock("../../api/bridgeClient", () => ({
  bridge: {
    qaReviewGetQueue: vi.fn().mockResolvedValue({
      findings: [], nextCursor: "", totalCount: 0, order: "CANONICAL",
    }),
    qaReviewGetFinding: vi.fn(),
    qaReviewDecideFinding: vi.fn(),
    qaReviewAddNote: vi.fn(),
    analysisJobGetScopeStatus: vi.fn().mockResolvedValue({
      state: "NOT_ANALYZED", rangeKey: "PHP 1:3..PHP 1:3",
      displayedReferences: ["PHP 1:3"], canonicalReferences: ["PHP 1:3"],
      affectedReferences: [], latestJob: null,
      providerCapability: {
        semanticRetrieval: "LIMITED", multilingualEmbeddingProvider: "NOT_CONFIGURED",
        providerId: "unavailable", providerVersion: "", modelHash: "none", fixtureProvider: false,
      },
    }),
    analysisJobStart: vi.fn(),
    analysisJobStatus: vi.fn(),
    analysisJobCancel: vi.fn(),
  },
}));

// AlignmentModal reaches for Tauri and the project stores; Word mode is
// covered by its own existing behaviour, and the shell only needs to prove
// it mounts the real editor rather than a reimplementation.
vi.mock("../AlignmentModal.svelte", async () => ({
  default: (await import("./WordModeStub.svelte")).default,
}));

import AlignmentReview from "../AlignmentReview.svelte";

describe("AlignmentReview shell", () => {
  it("offers the four review modes as tabs", () => {
    render(AlignmentReview, { props: { chapter: "1", verse: "3" } });
    const tabs = screen.getAllByRole("tab");
    expect(tabs.map((tab) => tab.textContent?.trim().replace(/\s+.*/, ""))).toEqual([
      "Word", "Semantic", "Passage", "QA",
    ]);
  });

  it("opens in QA mode, the Stage 9A work surface", () => {
    render(AlignmentReview, { props: { chapter: "1", verse: "3" } });
    expect(screen.getByRole("tab", { name: /QA/ })).toHaveAttribute("aria-selected", "true");
  });

  it("mounts the existing word aligner rather than a replacement", async () => {
    render(AlignmentReview, { props: { chapter: "1", verse: "3", mode: "word" } });
    expect(screen.getByTestId("word-alignment-editor")).toBeInTheDocument();
  });

  it("keeps the tablist a single tab stop and moves with arrow keys", async () => {
    render(AlignmentReview, { props: { chapter: "1", verse: "3" } });
    const qa = screen.getByRole("tab", { name: /QA/ });
    expect(qa).toHaveAttribute("tabindex", "0");
    expect(screen.getByRole("tab", { name: /Word/ })).toHaveAttribute("tabindex", "-1");

    // Right from the last tab wraps to the first.
    await fireEvent.keyDown(qa, { key: "ArrowRight" });
    expect(screen.getByRole("tab", { name: /Word/ })).toHaveAttribute("aria-selected", "true");

    await fireEvent.keyDown(screen.getByRole("tab", { name: /Word/ }), { key: "End" });
    expect(screen.getByRole("tab", { name: /QA/ })).toHaveAttribute("aria-selected", "true");
  });

  it("associates each panel with the tab that controls it", async () => {
    render(AlignmentReview, { props: { chapter: "1", verse: "3" } });
    const panel = screen.getByRole("tabpanel");
    expect(panel).toHaveAttribute("aria-labelledby", "review-tab-qa");
    expect(screen.getByRole("tab", { name: /QA/ })).toHaveAttribute(
      "aria-controls", "review-panel-qa",
    );
  });

  it("mounts Semantic and Passage modes, which follow the QA selection", async () => {
    render(AlignmentReview, { props: { chapter: "1", verse: "3" } });

    await fireEvent.click(screen.getByRole("tab", { name: /Semantic/ }));
    // Nothing is selected in this test, so each mode says what it needs
    // rather than rendering an empty frame.
    expect(screen.getByText(/Select a possible issue/i)).toBeInTheDocument();
    expect(screen.getByRole("tabpanel")).toHaveAttribute("aria-labelledby", "review-tab-semantic");

    await fireEvent.click(screen.getByRole("tab", { name: /Passage/ }));
    expect(screen.getByText(/to see its passage in context/i)).toBeInTheDocument();
    expect(screen.getByRole("tabpanel")).toHaveAttribute("aria-labelledby", "review-tab-passage");
  });

  it("closes on Escape and via the close button", async () => {
    const onClose = vi.fn();
    render(AlignmentReview, { props: { chapter: "1", verse: "3", onClose } });
    await fireEvent.click(screen.getByRole("button", { name: /Close alignment review/i }));
    expect(onClose).toHaveBeenCalledOnce();

    await fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it("asks for a verse rather than failing when Word mode has none", () => {
    render(AlignmentReview, { props: { chapter: "1", verse: null, mode: "word" } });
    expect(screen.getByText(/Select a verse to align its words/i)).toBeInTheDocument();
  });
});
