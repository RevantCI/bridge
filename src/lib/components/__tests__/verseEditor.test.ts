import { beforeEach, describe, expect, it, vi } from "vitest";
import { get } from "svelte/store";

const { editVerse, runVerseChecks } = vi.hoisted(() => ({
  editVerse: vi.fn(),
  runVerseChecks: vi.fn(),
}));

vi.mock("../../api/bridgeClient", () => ({
  bridge: { editVerse, runVerseChecks },
}));

import { applySuggestedFindingFix, cancelVerseEdit } from "../../verseEditor";
import {
  checkingProgress,
  findingsByVerse,
  verseKey,
  verseTexts,
} from "../../stores";
import type { QaFinding } from "../../types/finding";

function finding(overrides: Partial<QaFinding> = {}): QaFinding {
  return {
    id: "finding-1", project_id: "project-1", book: "php", chapter: 1, verse: 6,
    start_offset: 0, end_offset: 5, original_text: "alpha", engine: "wildebeest",
    check_type: "normalization", category: "unicode", severity: "low", confidence: 1,
    suggested_replacement: "omega", explanation: "Normalize text", evidence: [],
    engine_version: "1", resource_versions: {}, status: "open", human_comment: null,
    created_at: "2026-09-07T00:00:00Z", resolved_at: null,
    ...overrides,
  };
}

describe("applySuggestedFindingFix", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    cancelVerseEdit();
    checkingProgress.set({
      running: false, percent: 0, label: "", jobId: "", state: "idle", error: "", scope: "chapter",
    });
    verseTexts.set({ [verseKey("1", "6")]: "alpha beta" });
    findingsByVerse.set({ [verseKey("1", "6")]: [finding()] });
    editVerse.mockResolvedValue({ issueResolutionsNeedingRecheck: 0 });
    runVerseChecks.mockResolvedValue([]);
  });

  it("uses the normal scripture edit and re-check path", async () => {
    const result = await applySuggestedFindingFix(finding());
    expect(result.ok).toBe(true);
    expect(editVerse).toHaveBeenCalledWith("1", "6", "omega beta");
    expect(runVerseChecks).toHaveBeenCalledWith("1", "6", ["local", "greekroom"]);
    expect(get(verseTexts)[verseKey("1", "6")]).toBe("omega beta");
  });

  it("does not write when the finding no longer matches the verse", async () => {
    const result = await applySuggestedFindingFix(finding({ original_text: "moved" }));
    expect(result.ok).toBe(false);
    expect(result.message).toMatch(/stale/i);
    expect(editVerse).not.toHaveBeenCalled();
  });
});
