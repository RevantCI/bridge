import { beforeEach, describe, expect, it, vi } from "vitest";
import { get } from "svelte/store";

const { editVerse, runVerseChecks, decideVerse } = vi.hoisted(() => ({
  editVerse: vi.fn(),
  runVerseChecks: vi.fn(),
  decideVerse: vi.fn(),
}));

vi.mock("../../api/bridgeClient", () => ({
  bridge: { editVerse, runVerseChecks, decideVerse },
}));

import { applyLanguageQaSuggestedFix, applySuggestedFindingFix, cancelVerseEdit } from "../../verseEditor";
import {
  checkingProgress,
  findingsByVerse,
  verseKey,
  verseTexts,
} from "../../stores";
import type { QaFinding } from "../../types/finding";
import type { LanguageQaFinding } from "../../types/languageQa";

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

function languageQaFinding(overrides: Partial<LanguageQaFinding> = {}): LanguageQaFinding {
  return {
    id: "term-1", book: "php", chapter: "1", verse: "6", rule: "terminology.deprecated-form",
    severity: "high", start: 0, end: 5, originalText: "alpha", message: "Deprecated form.",
    textHash: "hash", ruleVersion: "language-qa-2", status: "review-needed",
    suggestedReplacement: "omega", ...overrides,
  };
}

describe("applyLanguageQaSuggestedFix", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    cancelVerseEdit();
    checkingProgress.set({
      running: false, percent: 0, label: "", jobId: "", state: "idle", error: "", scope: "chapter",
    });
    verseTexts.set({ [verseKey("1", "6")]: "alpha beta" });
    editVerse.mockResolvedValue({ issueResolutionsNeedingRecheck: 0 });
    runVerseChecks.mockResolvedValue([]);
    decideVerse.mockResolvedValue({});
  });

  it("uses the normal scripture edit/re-check path, then records the decision via verse.decide", async () => {
    const result = await applyLanguageQaSuggestedFix(languageQaFinding());
    expect(result.ok).toBe(true);
    expect(editVerse).toHaveBeenCalledWith("1", "6", "omega beta");
    expect(runVerseChecks).toHaveBeenCalledWith("1", "6", ["local", "greekroom"]);
    expect(decideVerse).toHaveBeenCalledWith("1", "6", "term-1", "accepted");
    expect(get(verseTexts)[verseKey("1", "6")]).toBe("omega beta");
  });

  it("does not write when the finding no longer matches the verse", async () => {
    const result = await applyLanguageQaSuggestedFix(languageQaFinding({ originalText: "moved" }));
    expect(result.ok).toBe(false);
    expect(result.message).toMatch(/stale/i);
    expect(editVerse).not.toHaveBeenCalled();
    expect(decideVerse).not.toHaveBeenCalled();
  });

  it("refuses with no suggested form rather than inventing one", async () => {
    const result = await applyLanguageQaSuggestedFix(languageQaFinding({ suggestedReplacement: null }));
    expect(result.ok).toBe(false);
    expect(editVerse).not.toHaveBeenCalled();
  });

  it("still reports success if recording the decision fails -- the text fix already landed", async () => {
    decideVerse.mockRejectedValue(new Error("workbench unavailable"));
    const result = await applyLanguageQaSuggestedFix(languageQaFinding());
    expect(result.ok).toBe(true);
    expect(editVerse).toHaveBeenCalled();
  });
});
