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

function scope(
  state: AnalysisScopeState,
  latestJob: AnalysisJobSnapshot | null = null,
  references = ["PHP 1:3", "PHP 1:4", "PHP 1:5", "PHP 1:6"],
) {
  return {
    state, rangeKey: `${references[0]}..${references.at(-1)}`,
    displayedReferences: references, canonicalReferences: references, affectedReferences: [],
    analysisFingerprint: "fingerprint-3-6", policyVersions: {},
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
    canonicalReferences: ["PHP 1:3", "PHP 1:6"], targetRevision: "target-revision",
    targetContentHash: "target", analysisFingerprint: "fingerprint-3-6", policyVersions: {},
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
    expect(queue).toHaveBeenLastCalledWith(expect.objectContaining({
      canonicalReferences: job("COMPLETED").canonicalReferences,
    }));
  });

  it("defaults the queue to the current canonical analysis range", async () => {
    scopeStatus.mockResolvedValue(scope("CURRENT"));
    render(AlignmentQaMode, { props: { chapter: "1", verse: "3" } });
    await waitFor(() => expect(queue).toHaveBeenCalledWith(expect.objectContaining({
      canonicalReferences: ["PHP 1:3", "PHP 1:4", "PHP 1:5", "PHP 1:6"],
    })));
    expect(await screen.findByText(/Review scope: Current analysis range/i)).toBeInTheDocument();
  });

  it("refreshes the queue to a newly selected range instead of retaining the previous range", async () => {
    scopeStatus.mockImplementation(async (requested) => {
      if (requested.kind === "SELECTED_RANGE" && requested.startVerse === "1") {
        return scope("CURRENT", null, ["PHP 1:1"]);
      }
      return scope("CURRENT");
    });
    render(AlignmentQaMode, { props: { chapter: "1", verse: "3" } });
    await waitFor(() => expect(queue).toHaveBeenCalledWith(expect.objectContaining({
      canonicalReferences: ["PHP 1:3", "PHP 1:4", "PHP 1:5", "PHP 1:6"],
    })));

    await fireEvent.change(screen.getByLabelText("Scope"), { target: { value: "SELECTED_RANGE" } });
    await fireEvent.input(screen.getByLabelText("From verse"), { target: { value: "1" } });
    await fireEvent.input(screen.getByLabelText("To verse"), { target: { value: "1" } });

    await waitFor(() => expect(queue).toHaveBeenLastCalledWith(expect.objectContaining({
      canonicalReferences: ["PHP 1:1"],
    })));
  });

  it("uses the persisted job references for an affected-only rerun", async () => {
    const affectedQueued = {
      ...job("QUEUED"),
      requestedScope: { kind: "AFFECTED" as const, baseKind: "CURRENT_PASSAGE" as const },
      rangeKey: "PHP 1:5..PHP 1:5",
      displayedReferences: ["PHP 1:5"],
      canonicalReferences: ["PHP 1:5"],
      analysisFingerprint: "fingerprint-affected-5",
    };
    const affectedComplete = {
      ...job("COMPLETED"), ...affectedQueued, overallStatus: "COMPLETED" as const,
      completedAt: "2026-01-01T00:01:00Z",
    };
    scopeStatus.mockImplementation(async (requested) => requested.kind === "AFFECTED"
      ? {
          ...scope("STALE", null, ["PHP 1:5"]),
          rangeKey: "PHP 1:5..PHP 1:5",
          analysisFingerprint: "fingerprint-affected-5",
        }
      : scope("STALE"));
    startJob.mockResolvedValue(affectedQueued);
    jobStatus.mockResolvedValue(affectedComplete);

    render(AlignmentQaMode, { props: { chapter: "1", verse: "3" } });
    await fireEvent.click(await screen.findByRole("button", { name: "Re-run affected analysis" }));
    await screen.findByText(/QA review queue has been refreshed/i);
    expect(queue).toHaveBeenLastCalledWith(expect.objectContaining({
      canonicalReferences: ["PHP 1:5"],
    }));
  });
});
