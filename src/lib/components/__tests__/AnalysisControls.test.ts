import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";

const { getScopeStatus, startJob, jobStatus, cancelJob } = vi.hoisted(() => ({
  getScopeStatus: vi.fn(),
  startJob: vi.fn(),
  jobStatus: vi.fn(),
  cancelJob: vi.fn(),
}));

vi.mock("../../api/bridgeClient", () => ({
  bridge: {
    analysisJobGetScopeStatus: getScopeStatus,
    analysisJobStart: startJob,
    analysisJobStatus: jobStatus,
    analysisJobCancel: cancelJob,
  },
}));

import AnalysisControls from "../AnalysisControls.svelte";
import type { AnalysisJobSnapshot, AnalysisScopeStatus } from "../../types/analysisJob";

const capability = {
  semanticRetrieval: "LIMITED" as const,
  multilingualEmbeddingProvider: "NOT_CONFIGURED" as const,
  providerId: "unavailable",
  providerVersion: "v1",
  modelHash: "unavailable",
  fixtureProvider: false,
};

function stage(status: "NOT_STARTED" | "COMPLETED" = "NOT_STARTED") {
  return { status, runId: "", cacheStatus: "" as const, elapsedSeconds: null };
}

function job(overallStatus: AnalysisJobSnapshot["overallStatus"]): AnalysisJobSnapshot {
  const finished = overallStatus === "COMPLETED";
  return {
    jobId: "job-1", projectId: "project-1", book: "PHP",
    requestedScope: { kind: "CURRENT_PASSAGE", chapter: "1", verse: "3" },
    rangeKey: "PHP 1:3..PHP 1:6", displayedReferences: ["PHP 1:3", "PHP 1:6"],
    canonicalReferences: ["PHP 1:3", "PHP 1:6"], targetContentHash: "target",
    targetHashes: {}, sourceResourceHash: "source", revision: 1,
    createdAt: "2026-01-01T00:00:00Z", startedAt: null, completedAt: finished ? "2026-01-01T00:01:00Z" : null,
    currentStage: finished ? "" : "SOURCE_INVENTORY", overallStatus,
    stageStatuses: {
      SOURCE_INVENTORY: stage(finished ? "COMPLETED" : "NOT_STARTED"),
      TARGET_INVENTORY: stage(finished ? "COMPLETED" : "NOT_STARTED"),
      LOCATION: stage(finished ? "COMPLETED" : "NOT_STARTED"),
      MEANING: stage(finished ? "COMPLETED" : "NOT_STARTED"),
      QA: stage(finished ? "COMPLETED" : "NOT_STARTED"),
    },
    stageProgress: { completedStages: finished ? 5 : 0, totalStages: 5 },
    reusedRunIds: [], createdRunIds: [], warnings: [], failures: [],
    cancellationRequested: false, providerCapability: capability, timings: {},
    qaFindingCount: finished ? 0 : null, searchIncomplete: false,
  };
}

function scope(state: AnalysisScopeStatus["state"], latestJob: AnalysisJobSnapshot | null = null): AnalysisScopeStatus {
  return {
    state, rangeKey: "PHP 1:3..PHP 1:6", displayedReferences: ["PHP 1:3", "PHP 1:6"],
    canonicalReferences: ["PHP 1:3", "PHP 1:6"], affectedReferences: [],
    latestJob, providerCapability: capability,
  };
}

describe("AnalysisControls", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getScopeStatus.mockResolvedValue(scope("NOT_ANALYZED"));
  });

  it("reports persisted state without automatically starting analysis", async () => {
    render(AnalysisControls, { props: { chapter: "1", verse: "3" } });
    expect(await screen.findByText("Not analyzed")).toBeInTheDocument();
    expect(screen.getByText(/no production multilingual embedding provider/i)).toBeInTheDocument();
    expect(startJob).not.toHaveBeenCalled();
  });

  it("runs explicitly, polls stage progress, and emits completion", async () => {
    startJob.mockResolvedValue(job("QUEUED"));
    jobStatus.mockResolvedValue(job("COMPLETED"));
    getScopeStatus.mockResolvedValueOnce(scope("NOT_ANALYZED")).mockResolvedValue(scope("CURRENT", job("COMPLETED")));
    const { component } = render(AnalysisControls, { props: { chapter: "1", verse: "3" } });
    const completed = vi.fn();
    component.$on("completed", completed);

    await screen.findByText("Not analyzed");
    await fireEvent.click(screen.getByRole("button", { name: "Run analysis" }));
    expect(startJob).toHaveBeenCalledWith({ kind: "CURRENT_PASSAGE", chapter: "1", verse: "3" });
    await waitFor(() => expect(completed).toHaveBeenCalledOnce(), { timeout: 2000 });
    expect(screen.getByText("5 of 5 stages complete")).toBeInTheDocument();
  });

  it("reruns only the affected structural scope when results are stale", async () => {
    getScopeStatus.mockResolvedValue(scope("STALE"));
    startJob.mockResolvedValue(job("QUEUED"));
    render(AnalysisControls, { props: { chapter: "1", verse: "3" } });
    const button = await screen.findByRole("button", { name: "Re-run affected analysis" });
    await fireEvent.click(button);
    expect(startJob).toHaveBeenCalledWith({
      kind: "AFFECTED", baseKind: "CURRENT_PASSAGE", chapter: "1", verse: "3",
    });
  });
});
