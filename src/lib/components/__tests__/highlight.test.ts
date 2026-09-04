import { describe, expect, it } from "vitest";

import { buildSegments, categoryClass } from "../../utils/highlight";
import type { AiCheckReview } from "../../types/finding";

function aiReview(overrides: Partial<AiCheckReview> = {}): AiCheckReview {
  return {
    tool: "translationNotes",
    group_id: "figs-metaphor",
    check_id: "tn-1",
    source_quote: "λόγος",
    proposed_selection_ids: [],
    proposed_selection_text: [],
    proposed_selections: [{ text: "beta", occurrence: 1, occurrences: 1 }],
    nothing_to_select: false,
    verdict: "problem",
    severity: "high",
    rationale: "The metaphor is not carried over.",
    suggested_correction: "",
    confidence: 0.9,
    evidence_used: [],
    selection_state: "proposed" as never,
    semantic_mapping: null,
    ...overrides,
  };
}

const TEXT = "alpha beta gamma";

function marked(segments: ReturnType<typeof buildSegments>): Array<[string, string | null]> {
  return segments.filter((s) => s.className).map((s) => [s.text, s.className]);
}

describe("verse-text underlines", () => {
  it("maps each finding source to its own colour class", () => {
    expect(categoryClass("translation_note")).toBe("m-tn");
    expect(categoryClass("translation_word")).toBe("m-tw");
    expect(categoryClass("alignment")).toBe("m-align");
    // Everything Greek Room produces shares one class.
    expect(categoryClass("unicode")).toBe("m-gr");
    expect(categoryClass("structure")).toBe("m-gr");
  });

  it("underlines a tN issue the AI flagged", () => {
    const segments = buildSegments(TEXT, [], [], [aiReview()]);
    expect(marked(segments)).toEqual([["beta", "m-tn"]]);
  });

  it("underlines a tW issue with the tW colour", () => {
    const segments = buildSegments(TEXT, [], [], [aiReview({ tool: "translationWords" })]);
    expect(marked(segments)).toEqual([["beta", "m-tw"]]);
  });

  it("underlines a review verdict, which still needs a human look", () => {
    const segments = buildSegments(TEXT, [], [], [aiReview({ verdict: "review" })]);
    expect(marked(segments)).toEqual([["beta", "m-tn"]]);
  });

  it("underlines a proposal the AI passed, whatever the verdict", () => {
    // The mark says "this is where the check landed", not "this is wrong".
    // In Manual reviewer mode nothing is auto-applied, so a passing proposal
    // is the only thing marking the words until a human applies it --
    // filtering these out blanked the verse until you selected text by hand.
    for (const verdict of ["pass", "problem", "review", "not_applicable"] as const) {
      const segments = buildSegments(TEXT, [], [], [aiReview({ verdict })]);
      expect(marked(segments), `verdict ${verdict}`).toEqual([["beta", "m-tn"]]);
    }
  });

  it("marks nothing when the AI proposed no span", () => {
    const segments = buildSegments(TEXT, [], [], [aiReview({
      verdict: "problem", nothing_to_select: true,
      proposed_selections: [], proposed_selection_text: [],
    })]);
    expect(marked(segments)).toEqual([]);
  });
});
