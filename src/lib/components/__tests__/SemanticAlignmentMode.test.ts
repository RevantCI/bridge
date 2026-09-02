import { describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/svelte";

import SemanticAlignmentMode from "../SemanticAlignmentMode.svelte";
import { detail, quantityContradiction, staleConfirmed } from "./fixtures";

function realized(realization: string, properties: string[] = []) {
  return detail({
    location: [{
      location: {
        id: "loc-1",
        locationOutcome: "LOCATED",
        reviewStatus: "AI_PROPOSED",
        revision: 1,
        realization,
        properties,
        targetQuote: "ஸ்தோத்திரிக்கிறேன்",
        targetDisplayedReferences: ["PHP 1:6"],
        locationConfidence: { calibratedValue: 0.82 },
      },
      alternatives: [],
    }],
    meaning: [{
      assessment: {
        id: "a-1", meaningStatus: "PRESERVED", reviewStatus: "AI_PROPOSED", revision: 1,
        meaningConfidence: { calibratedValue: 0.9 },
      },
      components: [],
    }],
  });
}

describe("SemanticAlignmentMode", () => {
  it("asks for a selection rather than rendering an empty frame", () => {
    render(SemanticAlignmentMode, { props: { detail: null } });
    expect(screen.getByText(/Select a possible issue/i)).toBeInTheDocument();
  });

  it("shows the source meaning with its reference and obligation", () => {
    render(SemanticAlignmentMode, { props: { detail: detail() } });
    expect(screen.getByText("εὐχαριστέω")).toBeInTheDocument();
    expect(screen.getByText("PHP 1:3")).toBeInTheDocument();
    expect(screen.getByText("REQUIRED")).toBeInTheDocument();
  });

  it("reports location and meaning as separate cells, each with its confidence", () => {
    render(SemanticAlignmentMode, { props: { detail: realized("LEXICALLY_REALIZED") } });
    expect(screen.getByText("Located")).toBeInTheDocument();
    expect(screen.getByText("Preserved")).toBeInTheDocument();
    expect(screen.getByText(/Confidence 82%/)).toBeInTheDocument();
    expect(screen.getByText(/Confidence 90%/)).toBeInTheDocument();
    expect(screen.getByText(/judged independently/i)).toBeInTheDocument();
  });

  it.each([
    ["LEXICALLY_REALIZED", "Translated as a word", /carries this meaning directly/i],
    ["GRAMMATICALLY_REALIZED", "Carried by grammar", /target grammar carries this meaning/i],
    ["PRONOMINALIZED", "Rendered as a pronoun", /uses a pronoun/i],
    ["IMPLICIT", "Left implicit", /recoverable from context/i],
  ])("distinguishes %s visibly and explains it", (realization, label, help) => {
    render(SemanticAlignmentMode, { props: { detail: realized(realization) } });
    expect(screen.getByText(label)).toBeInTheDocument();
    expect(screen.getByText(help)).toBeInTheDocument();
  });

  it.each([
    ["SPLIT", "Split across expressions"],
    ["MERGED", "Merged with another"],
    ["CROSS_VERSE", "Realized in another verse"],
  ])("names the %s property without implying a defect", (property, label) => {
    render(SemanticAlignmentMode, {
      props: { detail: realized("LEXICALLY_REALIZED", [property]) },
    });
    expect(screen.getByText(label)).toBeInTheDocument();
    // Described neutrally, never as an error or a warning.
    expect(screen.queryByText(/error|wrong|incorrect/i)).toBeNull();
  });

  it("says why meaning was not assessed rather than leaving it blank", () => {
    render(SemanticAlignmentMode, { props: { detail: detail() } });
    expect(
      screen.getByText(/assesses meaning only where it located a realization/i),
    ).toBeInTheDocument();
  });

  it("shows coverage and support alongside, not merged into meaning", () => {
    render(SemanticAlignmentMode, { props: { detail: detail() } });
    const cell = screen.getByText(/Coverage & support/i).closest("div");
    expect(within(cell as HTMLElement).getByText("Possibly missing")).toBeInTheDocument();
  });

  it("surfaces the review and lifecycle state of the relationship", () => {
    render(SemanticAlignmentMode, { props: { detail: staleConfirmed() } });
    expect(screen.getByText("Stale")).toBeInTheDocument();
    expect(screen.getByText("Reviewed")).toBeInTheDocument();
  });

  it("keeps a failed meaning assessment visible next to a strong location", () => {
    render(SemanticAlignmentMode, { props: { detail: quantityContradiction() } });
    expect(screen.getByText("Located")).toBeInTheDocument();
    expect(screen.getByText("Contradicted")).toBeInTheDocument();
  });
});
