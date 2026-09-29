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

import AlignmentReview from "../AlignmentReview.svelte";

describe("AlignmentReview shell", () => {
  it("is the QA surface alone, with no mode tabs left to choose between", () => {
    render(AlignmentReview, { props: { chapter: "1", verse: "3" } });
    // #129 removed Semantic, Passage and Word. One remaining mode needs no
    // tablist, so there should be no tab or tabpanel roles at all.
    expect(screen.queryAllByRole("tab")).toHaveLength(0);
    expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
  });

  it("does not offer the removed Semantic, Passage or Word modes", () => {
    render(AlignmentReview, { props: { chapter: "1", verse: "3" } });
    for (const label of [/^Semantic$/, /^Passage$/, /^Word$/]) {
      expect(screen.queryByRole("button", { name: label })).not.toBeInTheDocument();
    }
  });

  it("still names itself, so the surface is identifiable", () => {
    render(AlignmentReview, { props: { chapter: "1", verse: "3" } });
    expect(screen.getByRole("heading", { name: /Alignment Review/i })).toBeInTheDocument();
  });

  it("renders without a verse rather than failing", () => {
    // Word mode was the only part that needed one; QA mode takes a null verse.
    render(AlignmentReview, { props: { chapter: "1", verse: null } });
    expect(screen.getByRole("heading", { name: /Alignment Review/i })).toBeInTheDocument();
  });

  it("closes on Escape and via the close button", async () => {
    const onClose = vi.fn();
    render(AlignmentReview, { props: { chapter: "1", verse: "3", onClose } });
    await fireEvent.click(screen.getByRole("button", { name: /Close alignment review/i }));
    expect(onClose).toHaveBeenCalledOnce();

    await fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(2);
  });
});
