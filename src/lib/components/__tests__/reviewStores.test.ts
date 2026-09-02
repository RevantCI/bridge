import { beforeEach, describe, expect, it, vi } from "vitest";
import { get } from "svelte/store";

// vi.mock is hoisted above the imports, so the spies it returns have to be
// created inside vi.hoisted rather than as ordinary top-level consts.
const {
  qaReviewGetQueue, qaReviewGetFinding, qaReviewDecideFinding, qaReviewAddNote,
} = vi.hoisted(() => ({
  qaReviewGetQueue: vi.fn(),
  qaReviewGetFinding: vi.fn(),
  qaReviewDecideFinding: vi.fn(),
  qaReviewAddNote: vi.fn(),
}));

vi.mock("../../api/bridgeClient", () => ({
  bridge: { qaReviewGetQueue, qaReviewGetFinding, qaReviewDecideFinding, qaReviewAddNote },
}));

import {
  decideFinding,
  goToNextUnresolved,
  hasMoreFindings,
  loadMoreFindings,
  loadQueue,
  resetReviewState,
  reviewError,
  reviewFilters,
  reviewQueue,
  reviewTotal,
  selectFinding,
  selectedDetail,
  selectedFindingId,
  stepSelection,
} from "../../reviewStores";
import { detail, summary } from "./fixtures";

function page(ids: string[], nextCursor = "", total = ids.length) {
  return {
    findings: ids.map((id) => summary({ id })),
    nextCursor,
    totalCount: total,
    order: "CANONICAL" as const,
  };
}

describe("review queue store", () => {
  beforeEach(() => {
    resetReviewState();
    vi.clearAllMocks();
  });

  it("loads the first page and reports how many remain", async () => {
    qaReviewGetQueue.mockResolvedValue(page(["a", "b"], "cursor-1", 40));
    await loadQueue();
    expect(get(reviewQueue).map((f) => f.id)).toEqual(["a", "b"]);
    expect(get(reviewTotal)).toBe(40);
    expect(get(hasMoreFindings)).toBe(true);
  });

  it("appends later pages without duplicating a finding", async () => {
    qaReviewGetQueue.mockResolvedValueOnce(page(["a", "b"], "cursor-1", 4));
    await loadQueue();
    // A page that re-sends "b" must not produce it twice.
    qaReviewGetQueue.mockResolvedValueOnce(page(["b", "c"], "", 4));
    await loadMoreFindings();
    expect(get(reviewQueue).map((f) => f.id)).toEqual(["a", "b", "c"]);
    expect(get(hasMoreFindings)).toBe(false);
  });

  it("does not ask for more once the cursor is exhausted", async () => {
    qaReviewGetQueue.mockResolvedValue(page(["a"], ""));
    await loadQueue();
    qaReviewGetQueue.mockClear();
    await loadMoreFindings();
    expect(qaReviewGetQueue).not.toHaveBeenCalled();
  });

  it("passes the active filters through to the engine", async () => {
    qaReviewGetQueue.mockResolvedValue(page([]));
    reviewFilters.update((f) => ({
      ...f, kinds: ["POSSIBLE_OMISSION"], dispositions: ["UNRESOLVED"], order: "SEVERITY",
    }));
    await loadQueue();
    expect(qaReviewGetQueue).toHaveBeenCalledWith(expect.objectContaining({
      kinds: ["POSSIBLE_OMISSION"],
      dispositions: ["UNRESOLVED"],
      order: "SEVERITY",
    }));
  });

  it("surfaces a queue failure instead of showing a silently empty list", async () => {
    qaReviewGetQueue.mockRejectedValue(new Error("engine unavailable"));
    await loadQueue();
    expect(get(reviewError)).toContain("engine unavailable");
    expect(get(reviewQueue)).toEqual([]);
  });

  it("loads evidence when a finding is selected", async () => {
    qaReviewGetFinding.mockResolvedValue(detail());
    await selectFinding("qa-finding-0001");
    expect(get(selectedFindingId)).toBe("qa-finding-0001");
    expect(get(selectedDetail)?.finding.id).toBe("qa-finding-0001");
  });

  it("steps forward and back through the queue", async () => {
    qaReviewGetQueue.mockResolvedValue(page(["a", "b", "c"], ""));
    qaReviewGetFinding.mockImplementation(async (id: string) =>
      detail({ finding: { ...detail().finding, id } }));
    await loadQueue();
    await selectFinding("a");
    await stepSelection(1);
    expect(get(selectedFindingId)).toBe("b");
    await stepSelection(-1);
    expect(get(selectedFindingId)).toBe("a");
  });

  it("pulls another page when stepping past the loaded end", async () => {
    qaReviewGetQueue.mockResolvedValueOnce(page(["a"], "cursor-1", 2));
    qaReviewGetFinding.mockImplementation(async (id: string) =>
      detail({ finding: { ...detail().finding, id } }));
    await loadQueue();
    await selectFinding("a");
    qaReviewGetQueue.mockResolvedValueOnce(page(["b"], "", 2));
    await stepSelection(1);
    expect(get(selectedFindingId)).toBe("b");
  });

  it("skips already-decided findings when advancing to the next unresolved", async () => {
    qaReviewGetQueue.mockResolvedValue({
      findings: [
        summary({ id: "a" }),
        summary({ id: "b", qaDisposition: "ACCEPTABLE_TRANSLATION" }),
        summary({ id: "c" }),
      ],
      nextCursor: "", totalCount: 3, order: "CANONICAL" as const,
    });
    qaReviewGetFinding.mockImplementation(async (id: string) =>
      detail({ finding: { ...detail().finding, id } }));
    await loadQueue();
    await selectFinding("a");
    await goToNextUnresolved();
    expect(get(selectedFindingId)).toBe("c");
  });

  it("sends the revision and target hashes the reviewer actually saw", async () => {
    qaReviewGetQueue.mockResolvedValue(page(["a"], ""));
    qaReviewGetFinding.mockResolvedValue(detail({
      finding: { ...detail().finding, id: "a", revision: 4, targetContentHashes: ["hash-x"] },
    }));
    qaReviewDecideFinding.mockResolvedValue({
      finding: { ...detail().finding, id: "a", revision: 5, qaDisposition: "FALSE_POSITIVE", reviewStatus: "HUMAN_REJECTED" },
      promotedCoverageAccountIds: [],
      history: [],
    });
    await loadQueue();
    await selectFinding("a");

    const result = await decideFinding("a", "FALSE_POSITIVE", { note: "not a real issue" });
    expect(result.ok).toBe(true);
    expect(qaReviewDecideFinding).toHaveBeenCalledWith("a", "FALSE_POSITIVE", 4, {
      note: "not a real issue",
      promote: undefined,
      expectedTargetContentHashes: ["hash-x"],
    });
  });

  it("folds the decision back into the queue row", async () => {
    qaReviewGetQueue.mockResolvedValue(page(["a"], ""));
    qaReviewGetFinding.mockResolvedValue(detail({ finding: { ...detail().finding, id: "a" } }));
    qaReviewDecideFinding.mockResolvedValue({
      finding: {
        ...detail().finding, id: "a", revision: 2,
        qaDisposition: "ACCEPTABLE_TRANSLATION", reviewStatus: "HUMAN_APPROVED",
      },
      promotedCoverageAccountIds: [],
      history: [],
    });
    await loadQueue();
    await selectFinding("a");
    await decideFinding("a", "ACCEPTABLE_TRANSLATION");
    const row = get(reviewQueue).find((item) => item.id === "a");
    expect(row?.qaDisposition).toBe("ACCEPTABLE_TRANSLATION");
    expect(row?.revision).toBe(2);
  });

  it("reports a revision conflict plainly and reloads rather than retrying", async () => {
    qaReviewGetQueue.mockResolvedValue(page(["a"], ""));
    qaReviewGetFinding.mockResolvedValue(detail({ finding: { ...detail().finding, id: "a" } }));
    qaReviewDecideFinding.mockRejectedValue(new Error("revision_conflict: QA finding revision conflict"));
    await loadQueue();
    await selectFinding("a");
    qaReviewGetFinding.mockClear();

    const result = await decideFinding("a", "CONFIRMED_TRANSLATION_ERROR");
    expect(result.ok).toBe(false);
    expect(result.conflict).toBe(true);
    expect(result.message).toMatch(/changed since you opened it/i);
    // Reloaded so the reviewer decides against what it says now.
    expect(qaReviewGetFinding).toHaveBeenCalledWith("a");
    // And never silently retried.
    expect(qaReviewDecideFinding).toHaveBeenCalledTimes(1);
  });

  it("treats changed target text as a conflict too", async () => {
    qaReviewGetQueue.mockResolvedValue(page(["a"], ""));
    qaReviewGetFinding.mockResolvedValue(detail({ finding: { ...detail().finding, id: "a" } }));
    qaReviewDecideFinding.mockRejectedValue(
      new Error("Target content changed since this finding was displayed"));
    await loadQueue();
    await selectFinding("a");
    const result = await decideFinding("a", "CONFIRMED_TRANSLATION_ERROR");
    expect(result.conflict).toBe(true);
  });

  it("reports promotion back to the caller", async () => {
    qaReviewGetQueue.mockResolvedValue(page(["a"], ""));
    qaReviewGetFinding.mockResolvedValue(detail({ finding: { ...detail().finding, id: "a" } }));
    qaReviewDecideFinding.mockResolvedValue({
      finding: { ...detail().finding, id: "a", revision: 2, qaDisposition: "CONFIRMED_TRANSLATION_ERROR" },
      promotedCoverageAccountIds: ["source-coverage-1"],
      history: [],
    });
    await loadQueue();
    await selectFinding("a");
    const result = await decideFinding("a", "CONFIRMED_TRANSLATION_ERROR", { promote: true });
    expect(result.promoted).toEqual(["source-coverage-1"]);
  });

  it("clears every book-scoped value on reset", async () => {
    qaReviewGetQueue.mockResolvedValue(page(["a"], "cursor-1", 9));
    qaReviewGetFinding.mockResolvedValue(detail({ finding: { ...detail().finding, id: "a" } }));
    await loadQueue();
    await selectFinding("a");

    resetReviewState();
    expect(get(reviewQueue)).toEqual([]);
    expect(get(reviewTotal)).toBe(0);
    expect(get(selectedFindingId)).toBeNull();
    expect(get(selectedDetail)).toBeNull();
    expect(get(hasMoreFindings)).toBe(false);
  });
});
