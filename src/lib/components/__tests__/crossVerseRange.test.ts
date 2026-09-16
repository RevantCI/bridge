import { describe, expect, it } from "vitest";
import {
  defaultRange, joinVerseId, rangeBetween, spanOf, splitVerseId, toggleVerse,
} from "../../crossVerseRange";

// Bridges and lettered segments are real verse "numbers" (CLAUDE.md gotcha 12);
// every helper must treat them as opaque strings ordered by the chapter list.
const VERSES = ["front", "1", "2", "3-4", "5a", "5b", "6"];

describe("defaultRange", () => {
  it("is the selected verse plus one on each side, in chapter order", () => {
    expect(defaultRange(VERSES, "2")).toEqual(["1", "2", "3-4"]);
    expect(defaultRange(VERSES, "5a")).toEqual(["3-4", "5a", "5b"]);
  });

  it("clamps at the chapter edges and never includes 'front'", () => {
    expect(defaultRange(VERSES, "1")).toEqual(["1", "2"]);
    expect(defaultRange(VERSES, "6")).toEqual(["5b", "6"]);
  });

  it("falls back to the verse alone when it is not in the list", () => {
    expect(defaultRange(VERSES, "99")).toEqual(["99"]);
    expect(defaultRange(VERSES, "")).toEqual([]);
  });
});

describe("rangeBetween / spanOf", () => {
  it("is inclusive and accepts the endpoints in either order", () => {
    expect(rangeBetween(VERSES, "2", "5a")).toEqual(["2", "3-4", "5a"]);
    expect(rangeBetween(VERSES, "5a", "2")).toEqual(["2", "3-4", "5a"]);
    expect(rangeBetween(VERSES, "3-4", "3-4")).toEqual(["3-4"]);
    expect(rangeBetween(VERSES, "2", "nope")).toEqual([]);
  });

  it("spanOf reports the first and last selected verse in chapter order", () => {
    expect(spanOf(VERSES, ["5a", "2"])).toEqual(["2", "5a"]);
    expect(spanOf(VERSES, [])).toBeNull();
  });
});

describe("toggleVerse", () => {
  it("adds and removes while keeping chapter order", () => {
    expect(toggleVerse(VERSES, ["1", "3-4"], "2")).toEqual(["1", "2", "3-4"]);
    expect(toggleVerse(VERSES, ["1", "2", "3-4"], "1")).toEqual(["2", "3-4"]);
  });

  it("never empties the selection and ignores unknown verses", () => {
    expect(toggleVerse(VERSES, ["2"], "2")).toEqual(["2"]);
    expect(toggleVerse(VERSES, ["2"], "front")).toEqual(["2"]);
  });
});

describe("composite ids", () => {
  it("round-trips verses that contain '-' and letters", () => {
    expect(splitVerseId(joinVerseId("3-4", "T002"))).toEqual({ verse: "3-4", id: "T002" });
    expect(splitVerseId(joinVerseId("5a", "H001"))).toEqual({ verse: "5a", id: "H001" });
    expect(splitVerseId("T001")).toEqual({ verse: "", id: "T001" });
  });
});
