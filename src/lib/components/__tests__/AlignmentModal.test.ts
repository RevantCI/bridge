import { describe, expect, it } from "vitest";

// @ts-expect-error Vite's test-only raw loader is not part of the app tsconfig.
import alignmentModalSource from "../AlignmentModal.svelte?raw";

/** The text of one CSS rule block, by selector, from a component's source. */
function rule(source: string, selector: string): string {
  const match = source.match(new RegExp(`\\${selector}\\s*{([^}]*)}`));
  return match?.[1] ?? "";
}

describe("AlignmentModal layout", () => {
  // jsdom neither lays out nor paints, so this asserts on the rules themselves
  // (the pattern QaFindingDetail.test.ts uses). It guards #72: the interlinear
  // wraps instead of scrolling sideways, and that was not bought by letting the
  // columns squash.
  it("wraps the interlinear instead of scrolling it sideways", () => {
    const interlinear = rule(alignmentModalSource, ".interlinear");
    expect(interlinear).toMatch(/flex-wrap:\s*wrap/);
    expect(interlinear).toMatch(/overflow-x:\s*hidden/);
    expect(interlinear).not.toMatch(/overflow-x:\s*(auto|scroll)/);
  });

  it("caps the wrapped block so the word bank stays on screen", () => {
    const interlinear = rule(alignmentModalSource, ".interlinear");
    expect(interlinear).toMatch(/max-height:/);
    expect(interlinear).toMatch(/overflow-y:\s*auto/);
  });

  it("keeps the columns unsqueezable", () => {
    expect(rule(alignmentModalSource, ".column")).toMatch(/flex-shrink:\s*0/);
  });
});
