import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";

const { queue, scopeStatus, startJob, jobStatus, cancelJob } = vi.hoisted(() => ({
  queue: vi.fn(), scopeStatus: vi.fn(), startJob: vi.fn(), jobStatus: vi.fn(), cancelJob: vi.fn(),
}));

vi.mock("../../api/bridgeClient", () => ({
  bridge: {
    qaReviewGetQueue: queue,
    qaReviewGetFinding: vi.fn(),
    qaReviewDecideFinding: vi.fn(),
    qaReviewAddNote: vi.fn(),
    analysisJobGetScopeStatus: scopeStatus,
    analysisJobStart: startJob,
    analysisJobStatus: jobStatus,
    analysisJobCancel: cancelJob,
  },
}));

import AlignmentQaMode from "../AlignmentQaMode.svelte";
import { resetReviewState } from "../../reviewStores";
import type { AnalysisJobSnapshot, AnalysisScopeState } from "../../types/analysisJob";

const capability = {
  semanticRetrieval: "LIMITED" as const,
  multilingualEmbeddingProvider: "NOT_CONFIGURED" as const,
  providerId: "unavailable", providerVersion: "v1", modelHash: "unavailable", fixtureProvider: false,
};

function scope(state: AnalysisScopeState, latestJob: AnalysisJobSnapshot | null = null) {
  return {
    state, rangeKey: "PHP 1:3..PHP 1:6", displayedReferences: ["PHP 1:3", "PHP 1:6"],
    canonicalReferences: ["PHP 1:3", "PHP 1:6"], affectedReferences: [],
    latestJob, providerCapability: capability,
  };
}

function job(status: "QUEUED" | "COMPLETED"): AnalysisJobSnapshot {
  const done = status === "COMPLETED";
  const stageStatus = done ? "COMPLETED" as const : "NOT_STARTED" as const;
  const stage = { status: stageStatus, runId: "", cacheStatus: "" as const, elapsedSeconds: null };
  return {
    jobId: "job-1", projectId: "project-1", book: "PHP",
    requestedScope: { kind: "CURRENT_PASSAGE", chapter: "1", verse: "3" },
    rangeKey: "PHP 1:3..PHP 1:6", displayedReferences: ["PHP 1:3", "PHP 1:6"],
    canonicalReferences: ["PHP 1:3", "PHP 1:6"], targetContentHash: "target",
    targetHashes: {}, sourceResourceHash: "source", revision: 1,
    createdAt: "2026-01-01T00:00:00Z", startedAt: null, completedAt: done ? "2026-01-01T00:01:00Z" : null,
    currentStage: done ? "" : "SOURCE_INVENTORY", overallStatus: status,
    stageStatuses: {
      SOURCE_INVENTORY: { ...stage }, TARGET_INVENTORY: { ...stage }, LOCATION: { ...stage },
      MEANING: { ...stage }, QA: { ...stage },
    },
    stageProgress: { completedStages: done ? 5 : 0, totalStages: 5 },
    reusedRunIds: [], createdRunIds: [], warnings: [], failures: [], cancellationRequested: false,
    providerCapability: capability, timings: {}, qaFindingCount: done ? 0 : null, searchIncomplete: false,
  };
}

describe("AlignmentQaMode analysis states", () => {
  beforeEach(() => {
    resetReviewState();
    vi.clearAllMocks();
    queue.mockResolvedValue({ findings: [], nextCursor: "", totalCount: 0, order: "CANONICAL" });
  });

  it.each([
    ["NOT_ANALYZED", /has not been analyzed yet/i],
    ["STALE", /results are out of date/i],
    ["CURRENT", /No possible QA issues were found/i],
  ] as const)("distinguishes the %s empty state", async (state, message) => {
    scopeStatus.mockResolvedValue(scope(state));
    render(AlignmentQaMode, { props: { chapter: "1", verse: "3" } });
    expect(await screen.findByText(message)).toBeInTheDocument();
  });

  it("refreshes the indexed QA queue when analysis completes", async () => {
    scopeStatus.mockResolvedValueOnce(scope("NOT_ANALYZED")).mockResolvedValue(scope("CURRENT", job("COMPLETED")));
    startJob.mockResolvedValue(job("QUEUED"));
    jobStatus.mockResolvedValue(job("COMPLETED"));
    render(AlignmentQaMode, { props: { chapter: "1", verse: "3" } });
    await screen.findByText(/has not been analyzed yet/i);
    await fireEvent.click(screen.getByRole("button", { name: "Run analysis" }));
    await waitFor(() => expect(queue.mock.calls.length).toBeGreaterThanOrEqual(2), { timeout: 2000 });
    expect(await screen.findByText(/QA review queue has been refreshed/i)).toBeInTheDocument();
  });
});
