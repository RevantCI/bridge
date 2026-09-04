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
    canonicalReferences: ["PHP 1:3", "PHP 1:6"], targetRevision: "target-revision",
    targetContentHash: "target",
    analysisFingerprint: "fingerprint-3-6", policyVersions: {},
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
    analysisFingerprint: "fingerprint-3-6", policyVersions: {},
    latestJob, providerCapability: capability,
  };
}

function selectedScope(startVerse: string, endVerse: string): AnalysisScopeStatus {
  const references = startVerse === endVerse
    ? [`PHP 1:${startVerse}`]
    : Array.from(
        { length: Number(endVerse) - Number(startVerse) + 1 },
        (_, index) => `PHP 1:${Number(startVerse) + index}`,
      );
  return {
    state: "NOT_ANALYZED",
    rangeKey: `${references[0]}..${references.at(-1)}`,
    displayedReferences: references,
    canonicalReferences: references,
    affectedReferences: [],
    analysisFingerprint: `fingerprint-${startVerse}-${endVerse}`,
    policyVersions: {},
    latestJob: null,
    providerCapability: capability,
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
    expect(startJob).toHaveBeenCalledWith(
      { kind: "CURRENT_PASSAGE", chapter: "1", verse: "3" },
      "fingerprint-3-6",
    );
    expect(await screen.findByText("Running: PHP 1:3–1:6")).toBeInTheDocument();
    await waitFor(() => expect(completed).toHaveBeenCalledOnce(), { timeout: 2000 });
    expect(screen.getByText("5 of 5 stages complete")).toBeInTheDocument();
  });

  it("reruns only the affected structural scope when results are stale", async () => {
    getScopeStatus.mockResolvedValue(scope("STALE"));
    startJob.mockResolvedValue(job("QUEUED"));
    render(AnalysisControls, { props: { chapter: "1", verse: "3" } });
    const button = await screen.findByRole("button", { name: "Re-run affected analysis" });
    await fireEvent.click(button);
    expect(startJob).toHaveBeenCalledWith(
      { kind: "AFFECTED", baseKind: "CURRENT_PASSAGE", chapter: "1", verse: "3" },
      "fingerprint-3-6",
    );
  });

  it("runs the newly selected 1:1 scope after completing 1:3–1:6", async () => {
    getScopeStatus.mockImplementation(async (requested) => {
      if (requested.kind !== "SELECTED_RANGE") return scope("NOT_ANALYZED");
      return selectedScope(requested.startVerse, requested.endVerse);
    });
    startJob.mockImplementation(async (requested) => ({
      ...job("QUEUED"),
      jobId: `job-${requested.startVerse}`,
      requestedScope: requested,
      rangeKey: `PHP 1:${requested.startVerse}..PHP 1:${requested.endVerse}`,
      displayedReferences: [`PHP 1:${requested.startVerse}`],
      canonicalReferences: [`PHP 1:${requested.startVerse}`],
      analysisFingerprint: `fingerprint-${requested.startVerse}-${requested.endVerse}`,
    }));
    jobStatus.mockImplementation(async (jobId) => ({
      ...job("COMPLETED"), jobId,
      rangeKey: jobId === "job-1" ? "PHP 1:1..PHP 1:1" : "PHP 1:3..PHP 1:6",
    }));
    render(AnalysisControls, { props: { chapter: "1", verse: "3" } });
    await screen.findByText("Not analyzed");
    await fireEvent.change(screen.getByLabelText("Scope"), { target: { value: "SELECTED_RANGE" } });
    await fireEvent.input(screen.getByLabelText("To verse"), { target: { value: "6" } });
    expect(await screen.findByText("Will analyze: PHP 1:3–1:6")).toBeInTheDocument();
    await fireEvent.click(screen.getByRole("button", { name: "Run analysis" }));
    await waitFor(() => expect(jobStatus).toHaveBeenCalled());

    await fireEvent.input(screen.getByLabelText("From verse"), { target: { value: "1" } });
    await fireEvent.input(screen.getByLabelText("To verse"), { target: { value: "1" } });
    expect(await screen.findByText("Will analyze: PHP 1:1")).toBeInTheDocument();
    await fireEvent.click(screen.getByRole("button", { name: "Run analysis" }));
    await waitFor(() => expect(startJob).toHaveBeenLastCalledWith(
      { kind: "SELECTED_RANGE", startChapter: "1", startVerse: "1", endChapter: "1", endVerse: "1" },
      "fingerprint-1-1",
    ));
  });

  it("keeps only the newest scope status during rapid out-of-order changes", async () => {
    let resolveOld: ((value: AnalysisScopeStatus) => void) | undefined;
    getScopeStatus.mockImplementation((requested) => {
      if (requested.kind !== "SELECTED_RANGE") return Promise.resolve(scope("NOT_ANALYZED"));
      if (requested.startVerse === "3" && requested.endVerse === "6") {
        return new Promise((resolve) => { resolveOld = resolve; });
      }
      return Promise.resolve(selectedScope(requested.startVerse, requested.endVerse));
    });
    startJob.mockResolvedValue({ ...job("QUEUED"), requestedScope: {
      kind: "SELECTED_RANGE", startChapter: "1", startVerse: "1", endChapter: "1", endVerse: "1",
    }, rangeKey: "PHP 1:1..PHP 1:1", analysisFingerprint: "fingerprint-1-1" });
    render(AnalysisControls, { props: { chapter: "1", verse: "3" } });
    await screen.findByText("Not analyzed");
    await fireEvent.change(screen.getByLabelText("Scope"), { target: { value: "SELECTED_RANGE" } });
    await fireEvent.input(screen.getByLabelText("To verse"), { target: { value: "6" } });
    await fireEvent.input(screen.getByLabelText("From verse"), { target: { value: "1" } });
    await fireEvent.input(screen.getByLabelText("To verse"), { target: { value: "1" } });
    expect(await screen.findByText("Will analyze: PHP 1:1")).toBeInTheDocument();
    resolveOld?.(selectedScope("3", "6"));
    await Promise.resolve();
    expect(screen.queryByText("Will analyze: PHP 1:3–1:6")).not.toBeInTheDocument();
    expect(screen.getByText("Will analyze: PHP 1:1")).toBeInTheDocument();
  });

  it("invalidates and resolves again when current navigation changes", async () => {
    getScopeStatus.mockImplementation(async (requested) => {
      const selectedVerse = requested.verse ?? "1";
      return selectedScope(selectedVerse, selectedVerse);
    });
    const { component } = render(AnalysisControls, { props: { chapter: "1", verse: "3" } });
    expect(await screen.findByText("Will analyze: PHP 1:3")).toBeInTheDocument();
    await component.$set({ chapter: "1", verse: "1" });
    expect(await screen.findByText("Will analyze: PHP 1:1")).toBeInTheDocument();
    expect(getScopeStatus).toHaveBeenLastCalledWith({
      kind: "CURRENT_PASSAGE", chapter: "1", verse: "1",
    });
  });
});
