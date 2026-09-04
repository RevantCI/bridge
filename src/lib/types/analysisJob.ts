export type AnalysisScopeKind =
  | "CURRENT_PASSAGE"
  | "CURRENT_CHAPTER"
  | "CURRENT_BOOK"
  | "SELECTED_RANGE"
  | "AFFECTED";

export interface AnalysisScope {
  kind: AnalysisScopeKind;
  chapter?: string;
  verse?: string;
  startChapter?: string;
  startVerse?: string;
  endChapter?: string;
  endVerse?: string;
  baseKind?: Exclude<AnalysisScopeKind, "AFFECTED">;
  resolvedStartChapter?: string;
  resolvedStartVerse?: string;
  resolvedEndChapter?: string;
  resolvedEndVerse?: string;
}

export type AnalysisStage =
  | "SOURCE_INVENTORY"
  | "TARGET_INVENTORY"
  | "LOCATION"
  | "MEANING"
  | "QA";

export type AnalysisStageStatus =
  | "NOT_STARTED"
  | "RUNNING"
  | "COMPLETED"
  | "REUSED"
  | "FAILED"
  | "CANCELLED";

export type AnalysisJobStatus =
  | "QUEUED"
  | "RUNNING"
  | "COMPLETED"
  | "COMPLETED_WITH_WARNINGS"
  | "FAILED"
  | "CANCELLED";

export type AnalysisScopeState =
  | "NOT_ANALYZED"
  | "CURRENT"
  | "PARTIALLY_ANALYZED"
  | "STALE"
  | "RUNNING"
  | "FAILED"
  | "SEARCH_INCOMPLETE";

export interface AnalysisStageSnapshot {
  status: AnalysisStageStatus;
  runId: string;
  cacheStatus: "" | "HIT" | "MISS";
  elapsedSeconds: number | null;
}

export interface AnalysisMessage {
  code: string;
  message: string;
  stage?: AnalysisStage | "ORCHESTRATION";
}

export interface AnalysisProviderCapability {
  semanticRetrieval: "FULL" | "LIMITED";
  multilingualEmbeddingProvider: "AVAILABLE" | "NOT_CONFIGURED" | "FIXTURE_ONLY";
  providerId: string;
  providerVersion: string;
  modelHash: string;
  fixtureProvider: boolean;
}

export interface AnalysisJobSnapshot {
  jobId: string;
  projectId: string;
  book: string;
  requestedScope: AnalysisScope;
  rangeKey: string;
  displayedReferences: string[];
  canonicalReferences: string[];
  targetRevision: string;
  targetContentHash: string;
  targetHashes: Record<string, string>;
  sourceResourceHash: string;
  analysisFingerprint: string;
  policyVersions: Record<string, string>;
  revision: number;
  createdAt: string;
  startedAt: string | null;
  completedAt: string | null;
  currentStage: "" | AnalysisStage;
  overallStatus: AnalysisJobStatus;
  stageStatuses: Record<AnalysisStage, AnalysisStageSnapshot>;
  stageProgress: { completedStages: number; totalStages: number };
  reusedRunIds: string[];
  createdRunIds: string[];
  warnings: AnalysisMessage[];
  failures: AnalysisMessage[];
  cancellationRequested: boolean;
  providerCapability: AnalysisProviderCapability;
  timings: Partial<Record<AnalysisStage, number>>;
  stage8PhaseTimings?: Record<string, number>;
  qaFindingCount: number | null;
  searchIncomplete: boolean;
}

export interface AnalysisScopeStatus {
  state: AnalysisScopeState;
  rangeKey: string;
  displayedReferences: string[];
  canonicalReferences: string[];
  affectedReferences: string[];
  analysisFingerprint: string;
  policyVersions: Record<string, string>;
  latestJob: AnalysisJobSnapshot | null;
  providerCapability: AnalysisProviderCapability;
}
