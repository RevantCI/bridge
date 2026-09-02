import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/svelte";

import EvidenceInspector from "../EvidenceInspector.svelte";
import QaFindingDetail from "../QaFindingDetail.svelte";
import QaFindingList from "../QaFindingList.svelte";
import ReviewStatusBadge from "../ReviewStatusBadge.svelte";
import { LONG_TAMIL, detail, manyFindings, staleConfirmed, summary } from "./fixtures";

/**
 * Accessibility and small-viewport guarantees.
 *
 * jsdom does not lay out or paint, so these assert the *structure* that makes
 * the layout work — scroll containers, a sticky action bar, wrapping text,
 * text labels alongside every colour — rather than measured pixels. Real
 * pixel behaviour at 1366x768 still needs a look in the running desktop app;
 * these tests stop the structure from regressing between those passes.
 */
describe("accessibility", () => {
  it("never encodes status with colour alone", () => {
    const tones = ["possible", "confirmed", "acceptable", "rejected", "discussion", "stale"] as const;
    for (const tone of tones) {
      const { unmount } = render(ReviewStatusBadge, {
        props: { label: `Status ${tone}`, tone },
      });
      // Text carries the meaning; the glyph is decorative reinforcement.
      const badge = screen.getByText(`Status ${tone}`);
      expect(badge).toBeInTheDocument();
      expect(badge.parentElement?.querySelector("[aria-hidden='true']")).not.toBeNull();
      unmount();
    }
  });

  it("gives every interactive control an accessible name", () => {
    render(QaFindingDetail, { props: { detail: detail() } });
    for (const button of screen.getAllByRole("button")) {
      expect(button.textContent?.trim() || button.getAttribute("aria-label")).toBeTruthy();
    }
    expect(screen.getByLabelText(/Note/i)).toBeInTheDocument();
  });

  it("labels the queue and its rows for screen readers", () => {
    render(QaFindingList, { props: { findings: manyFindings(3), total: 3 } });
    expect(screen.getByRole("listbox", { name: /Possible issues awaiting review/i })).toBeInTheDocument();
    expect(screen.getAllByRole("option")).toHaveLength(3);
  });

  it("announces queue size changes politely rather than interrupting", () => {
    const { container } = render(QaFindingList, { props: { findings: manyFindings(3), total: 3 } });
    expect(container.querySelector("[aria-live='polite']")).not.toBeNull();
  });

  it("groups the decision buttons under a named heading", () => {
    render(QaFindingDetail, { props: { detail: detail() } });
    const group = screen.getByRole("group", { name: /Your decision/i });
    expect(group).toBeInTheDocument();
  });

  it("marks up the meaning components as a real table, not a visual grid", () => {
    render(EvidenceInspector, {
      props: {
        detail: detail({
          meaning: [{
            assessment: { id: "a1", meaningStatus: "PARTIAL", reviewStatus: "AI_PROPOSED", revision: 1 },
            components: [{ id: "c1", coverageDimension: "QUANTITY", status: "CONTRADICTED" }],
          }],
        }),
      },
    });
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Dimension" })).toBeInTheDocument();
    expect(screen.getByRole("rowheader", { name: "QUANTITY" })).toBeInTheDocument();
  });

  it("uses a heading hierarchy the reviewer can navigate by", () => {
    render(QaFindingDetail, { props: { detail: detail() } });
    expect(screen.getByRole("heading", { level: 3 })).toBeInTheDocument();
    expect(screen.getAllByRole("heading", { level: 4 }).length).toBeGreaterThan(1);
  });
});

describe("small viewport", () => {
  it("keeps the decision controls out of the scrolling region", () => {
    const { container } = render(QaFindingDetail, { props: { detail: staleConfirmed() } });
    // The actions live in a footer that is a sibling of the scrolling evidence
    // area, not inside it, so they cannot be pushed below the fold by long
    // evidence.
    const actions = container.querySelector("footer.actions");
    const evidence = container.querySelector(".evidence");
    expect(actions).not.toBeNull();
    expect(evidence?.contains(actions as Node)).toBe(false);
    expect(screen.getByRole("button", { name: "Confirm translation issue" })).toBeInTheDocument();
  });

  it("puts long target text in a wrapping container rather than truncating", () => {
    render(EvidenceInspector, {
      props: {
        detail: detail({
          source: [{
            id: "u", rawSurface: LONG_TAMIL, displayedReferences: ["PHP 1:3"],
            kind: "CLAUSE", semanticObligation: "REQUIRED",
          }],
        }),
      },
    });
    const element = screen.getByText(LONG_TAMIL);
    expect(element.className).toContain("scripture");
    expect(element.textContent).toHaveLength(LONG_TAMIL.length);
  });

  it("keeps a long queue inside its own scroll container", () => {
    const { container } = render(QaFindingList, {
      props: { findings: manyFindings(400), total: 400 },
    });
    const viewport = container.querySelector(".viewport");
    expect(viewport).not.toBeNull();
    // Windowed, so a 400-row queue does not put 400 rows on the page.
    expect(screen.getAllByRole("option").length).toBeLessThan(100);
  });

  it("does not hide review controls when many alternatives are present", () => {
    const many = Array.from({ length: 25 }, (_unused, index) => ({
      id: `candidate-${index}`,
      targetQuote: `候補 ${index}`,
      targetDisplayedReferences: ["PHP 1:4"],
    }));
    render(QaFindingDetail, {
      props: {
        detail: detail({
          location: [{
            location: {
              id: "loc", locationOutcome: "AMBIGUOUS", reviewStatus: "AI_PROPOSED",
              revision: 1, properties: [],
            },
            alternatives: many,
          }],
        }),
      },
    });
    expect(screen.getByRole("button", { name: "Confirm translation issue" })).toBeInTheDocument();
    expect(screen.getByText("候補 24")).toBeInTheDocument();
  });

  it("keeps long reviewer notes readable in history", () => {
    const long = "This needs discussion with the team. ".repeat(20);
    render(EvidenceInspector, {
      props: {
        detail: detail({
          history: [{
            ...staleConfirmed().history[0],
            note: long,
          }],
        }),
      },
    });
    expect(screen.getByText(long.trim())).toBeInTheDocument();
  });
});
