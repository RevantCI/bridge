import { describe, expect, it } from "vitest";

import { codePointSlice, graphemeDiff, visualContextSegments } from "../../utils/unicodeDiff";

describe("Unicode correction diff", () => {
  it.each([
    ["தமிழ்", "தமில்"],
    ["בְּרֵאשִׁית", "בָּרָא"],
    ["ἐν ἀρχῇ", "ἐν λόγῳ"],
    ["𐤀𝕭", "𐤀𝕮"],
  ])("never splits grapheme clusters for %s", (before, after) => {
    const diff = graphemeDiff(before, after);
    expect(diff.map((part) => part.text).join("").length).toBeGreaterThan(0);
    for (const part of diff) {
      expect(part.text.startsWith("\u0301")).toBe(false);
      expect(part.text.startsWith("\u05B0")).toBe(false);
    }
  });

  it("converts code-point spans without treating supplementary characters as two", () => {
    expect(codePointSlice("A𐤀B", 1, 2)).toBe("𐤀");
    expect(visualContextSegments("A𐤀B", 1, 2).affected).toBe("𐤀");
  });

  it("represents insertion and replacement explicitly", () => {
    expect(graphemeDiff("", "தேவன்")).toEqual([{ kind: "inserted", text: "தேவன்" }]);
    const replacement = graphemeDiff("மூன்று", "எல்லாரும்");
    expect(replacement.some((part) => part.kind === "removed")).toBe(true);
    expect(replacement.some((part) => part.kind === "inserted")).toBe(true);
  });

  it("represents deletion without a fabricated insertion", () => {
    expect(graphemeDiff("λόγος", "")).toEqual([{ kind: "removed", text: "λόγος" }]);
  });
});
