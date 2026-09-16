import { describe, expect, it, vi, beforeEach } from "vitest";
import {
  crossVerseVersesFromRun, parseDisplayedReference, suggestCrossVerseRange, unionInChapterOrder,
  versesForReferences,
} from "../../crossVerseSuggest";

const { analysisJobGetScopeStatus, semanticLocationGetRange, targetSemanticGetRange } = vi.hoisted(() => ({
  analysisJobGetScopeStatus: vi.fn(),
  semanticLocationGetRange: vi.fn(),
  targetSemanticGetRange: vi.fn(),
}));

vi.mock("../../api/bridgeClient", () => ({
  bridge: { analysisJobGetScopeStatus, semanticLocationGetRange, targetSemanticGetRange },
}));

describe("parseDisplayedReference / versesForReferences", () => {
  it("splits 'BOOK c:v' on the last space and the first colon, keeping bridges as strings", () => {
    expect(parseDisplayedReference("PHP 1:3")).toEqual({ chapter: "1", verse: "3" });
    expect(parseDisplayedReference("PHP 1:2-3")).toEqual({ chapter: "1", verse: "2-3" });
    expect(parseDisplayedReference("1 Sam 2:5a")).toEqual({ chapter: "2", verse: "5a" });
    expect(parseDisplayedReference("PHP 1")).toBeNull();
    expect(parseDisplayedReference("")).toBeNull();
  });

  it("keeps only the first chapter's verses, deduplicated, in the order given", () => {
    expect(versesForReferences(["PHP 1:6", "PHP 1:3", "PHP 1:6", "PHP 2:1"])).toEqual({ chapter: "1", verses: ["6", "3"] });
    expect(versesForReferences([])).toBeNull();
    expect(versesForReferences(["nope"])).toBeNull();
  });
});

describe("crossVerseVersesFromRun", () => {
  const inventory = {
    tokens: [
      { id: "t1", displayedReference: "PHP 1:3" },
      { id: "t2", displayedReference: "PHP 1:6" },
      { id: "t3", displayedReference: "PHP 2:1" },
    ],
  } as never;

  it("collects the chapter's verses that CROSS_VERSE relationships land in, through the target tokens", () => {
    const run = {
      relationships: [
        { properties: ["CROSS_VERSE", "REORDERED"], targetTokenInstanceIds: ["t2"] },
        { properties: [], targetTokenInstanceIds: ["t1"] },
        { properties: ["CROSS_VERSE"], targetTokenInstanceIds: ["t3", "t2"] },
      ],
    } as never;
    expect(crossVerseVersesFromRun(run, inventory, "1")).toEqual(["6"]);
    expect(crossVerseVersesFromRun(run, inventory, "2")).toEqual(["1"]);
    expect(crossVerseVersesFromRun(run, null, "1")).toEqual([]);
  });

  it("unions in chapter order", () => {
    expect(unionInChapterOrder(["1", "2", "3-4", "5"], ["5", "2"], ["3-4", "2"])).toEqual(["2", "3-4", "5"]);
  });
});

describe("suggestCrossVerseRange", () => {
  beforeEach(() => {
    analysisJobGetScopeStatus.mockReset();
    semanticLocationGetRange.mockReset();
    targetSemanticGetRange.mockReset();
  });

  it("returns null when the chapter has no completed analysis", async () => {
    analysisJobGetScopeStatus.mockResolvedValue({ state: "NOT_ANALYZED", latestJob: null });
    expect(await suggestCrossVerseRange("1")).toBeNull();
    expect(analysisJobGetScopeStatus).toHaveBeenCalledWith({ kind: "CURRENT_CHAPTER", chapter: "1" });
    expect(semanticLocationGetRange).not.toHaveBeenCalled();
  });

  it("reads the last job's location run and its target inventory", async () => {
    analysisJobGetScopeStatus.mockResolvedValue({
      state: "ANALYZED", latestJob: { stageStatuses: { LOCATION: { runId: "run-9" } } },
    });
    semanticLocationGetRange.mockResolvedValue({
      targetInventoryId: "inv-1",
      relationships: [{ properties: ["CROSS_VERSE"], targetTokenInstanceIds: ["t2"] }],
    });
    targetSemanticGetRange.mockResolvedValue({ tokens: [{ id: "t2", displayedReference: "PHP 1:6" }] });
    expect(await suggestCrossVerseRange("1")).toEqual({ runId: "run-9", verses: ["6"] });
    expect(semanticLocationGetRange).toHaveBeenCalledWith("run-9");
    expect(targetSemanticGetRange).toHaveBeenCalledWith("inv-1");
  });

  it("never throws: a failing read is just no suggestion", async () => {
    analysisJobGetScopeStatus.mockRejectedValue(new Error("No project open"));
    expect(await suggestCrossVerseRange("1")).toBeNull();
  });
});
