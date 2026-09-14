import { beforeEach, describe, expect, it, vi } from "vitest";
import { get } from "svelte/store";

vi.mock("../../api/bridgeClient", () => ({
  bridge: {
    qaReviewGetQueue: vi.fn().mockResolvedValue({
      findings: [], nextCursor: "", totalCount: 0, order: "CANONICAL",
    }),
    qaReviewGetFinding: vi.fn(),
    qaReviewDecideFinding: vi.fn(),
    qaReviewAddNote: vi.fn(),
  },
}));

const KEY = "bridge.reviewFilters.v1";

/**
 * Rehydration happens when the module is first evaluated, so a test that wants
 * to observe it has to reset the module registry and re-import rather than
 * reuse the instance an earlier test already initialised.
 */
async function freshStores() {
  vi.resetModules();
  return import("../../reviewStores");
}

describe("review filter persistence (#61)", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.clearAllMocks();
  });

  it("writes the preference filters when the reviewer changes them", async () => {
    const { reviewFilters } = await freshStores();
    reviewFilters.update((f) => ({ ...f, order: "SEVERITY", kinds: ["MEANING_SHIFT"] }));

    expect(JSON.parse(localStorage.getItem(KEY)!)).toEqual({
      order: "SEVERITY",
      dispositions: [],
      kinds: ["MEANING_SHIFT"],
      lifecycleStatuses: [],
    });
  });

  it("never persists the navigation scope", async () => {
    const { reviewFilters } = await freshStores();
    reviewFilters.update((f) => ({
      ...f, book: "PHP", chapter: 2, canonicalReferences: ["PHP 2:1"],
    }));

    const stored = JSON.parse(localStorage.getItem(KEY)!);
    expect(stored).not.toHaveProperty("book");
    expect(stored).not.toHaveProperty("chapter");
    expect(stored).not.toHaveProperty("canonicalReferences");
  });

  it("restores the preference filters on the next launch", async () => {
    localStorage.setItem(KEY, JSON.stringify({
      order: "SEVERITY",
      dispositions: ["NEEDS_DISCUSSION"],
      kinds: ["QUANTITY_PROBLEM"],
      lifecycleStatuses: ["STALE"],
    }));

    const { reviewFilters } = await freshStores();
    expect(get(reviewFilters)).toEqual({
      book: "",
      chapter: null,
      canonicalReferences: [],
      kinds: ["QUANTITY_PROBLEM"],
      severities: [],
      dispositions: ["NEEDS_DISCUSSION"],
      lifecycleStatuses: ["STALE"],
      order: "SEVERITY",
    });
  });

  it("keeps preferences but drops scope when a project is reloaded", async () => {
    const { reviewFilters, resetReviewState } = await freshStores();
    reviewFilters.update((f) => ({
      ...f,
      order: "SEVERITY",
      dispositions: ["FALSE_POSITIVE"],
      book: "PHP",
      chapter: 2,
      canonicalReferences: ["PHP 2:1"],
    }));

    resetReviewState();

    const after = get(reviewFilters);
    expect(after.order).toBe("SEVERITY");
    expect(after.dispositions).toEqual(["FALSE_POSITIVE"]);
    expect(after.book).toBe("");
    expect(after.chapter).toBeNull();
    expect(after.canonicalReferences).toEqual([]);
  });

  describe("a stored value that cannot be trusted", () => {
    it("falls back to defaults on unparseable JSON", async () => {
      localStorage.setItem(KEY, "{not json");
      const { reviewFilters, EMPTY_FILTERS } = await freshStores();
      expect(get(reviewFilters)).toEqual(EMPTY_FILTERS);
    });

    it("ignores an order value the queue does not support", async () => {
      localStorage.setItem(KEY, JSON.stringify({ order: "RANDOM", kinds: ["MEANING_SHIFT"] }));
      const { reviewFilters } = await freshStores();
      expect(get(reviewFilters).order).toBe("CANONICAL");
      expect(get(reviewFilters).kinds).toEqual(["MEANING_SHIFT"]);
    });

    it("discards a disposition list carrying a value this build does not know", async () => {
      // A renamed or removed disposition would otherwise be sent to the engine
      // as a filter nothing can ever match, hiding the whole queue.
      localStorage.setItem(KEY, JSON.stringify({
        dispositions: ["NEEDS_DISCUSSION", "RETIRED_IN_A_LATER_BUILD"],
      }));
      const { reviewFilters } = await freshStores();
      expect(get(reviewFilters).dispositions).toEqual([]);
    });

    it("ignores a field of the wrong shape", async () => {
      localStorage.setItem(KEY, JSON.stringify({ kinds: "MEANING_SHIFT", order: "SEVERITY" }));
      const { reviewFilters } = await freshStores();
      expect(get(reviewFilters).kinds).toEqual([]);
      expect(get(reviewFilters).order).toBe("SEVERITY");
    });
  });

  it("still works when storage is unavailable", async () => {
    const getItem = vi.spyOn(Storage.prototype, "getItem")
      .mockImplementation(() => { throw new Error("storage disabled"); });
    const setItem = vi.spyOn(Storage.prototype, "setItem")
      .mockImplementation(() => { throw new Error("storage disabled"); });
    try {
      const { reviewFilters, EMPTY_FILTERS } = await freshStores();
      expect(get(reviewFilters)).toEqual(EMPTY_FILTERS);
      expect(() => reviewFilters.update((f) => ({ ...f, order: "SEVERITY" }))).not.toThrow();
      expect(get(reviewFilters).order).toBe("SEVERITY");
    } finally {
      getItem.mockRestore();
      setItem.mockRestore();
    }
  });
});
