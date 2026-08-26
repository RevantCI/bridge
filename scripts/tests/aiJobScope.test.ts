import assert from "node:assert/strict";
import test from "node:test";
import type { AIReviewJobSnapshot } from "../../src/lib/types/finding.ts";
import { aiJobAppliesToReference, isAIReviewJobActive } from "../../src/lib/utils/aiJobScope.ts";

function job(overrides: Partial<AIReviewJobSnapshot> = {}): AIReviewJobSnapshot {
  return {
    jobId: "job-1",
    projectPath: "C:/projects/gen",
    scope: "verse",
    mode: "advanced",
    state: "succeeded",
    currentStage: "Complete",
    chapters: ["1"],
    chapterVerses: { "1": ["1"] },
    totalVerses: 1,
    completedVerses: 1,
    failedVerses: 0,
    skippedCurrentVerses: 0,
    percent: 100,
    cancelRequested: false,
    resumeOf: null,
    error: null,
    results: {},
    latestResult: null,
    ...overrides,
  };
}

test("a verse job is visible only on its exact project, chapter and verse", () => {
  const snapshot = job();
  assert.equal(aiJobAppliesToReference(snapshot, "C:/projects/gen", "1", "1"), true);
  assert.equal(aiJobAppliesToReference(snapshot, "C:/projects/gen", "1", "2"), false);
  assert.equal(aiJobAppliesToReference(snapshot, "C:/projects/gen", "2", "1"), false);
  assert.equal(aiJobAppliesToReference(snapshot, "C:/projects/exo", "1", "1"), false);
});

test("a chapter job follows verses only within its original chapter", () => {
  const snapshot = job({ scope: "chapter", chapters: ["2"], chapterVerses: { "2": ["1", "2"] } });
  assert.equal(aiJobAppliesToReference(snapshot, "C:/projects/gen", "2", "1"), true);
  assert.equal(aiJobAppliesToReference(snapshot, "C:/projects/gen", "2", "99"), true);
  assert.equal(aiJobAppliesToReference(snapshot, "C:/projects/gen", "1", "1"), false);
});

test("a book job follows references only within its original project", () => {
  const snapshot = job({ scope: "book" });
  assert.equal(aiJobAppliesToReference(snapshot, "C:/projects/gen", "50", "26"), true);
  assert.equal(aiJobAppliesToReference(snapshot, "C:/projects/exo", "1", "1"), false);
});

test("only queued, running and cancelling jobs are active", () => {
  for (const state of ["queued", "running", "cancelling"] as const) {
    assert.equal(isAIReviewJobActive(job({ state })), true);
  }
  for (const state of ["succeeded", "failed", "cancelled"] as const) {
    assert.equal(isAIReviewJobActive(job({ state })), false);
  }
  assert.equal(isAIReviewJobActive(null), false);
});
