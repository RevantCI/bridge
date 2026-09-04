import type {
  AiExplainResult, AIReviewChapterResponse, AIReviewJobSnapshot, AlignmentAiProposal, AlignmentAiProposeResponse, AlignmentContext,
  AlignmentStatusResponse, BookProgressEntry, CheckJobSnapshot, DesktopConnectorState, ImportMetadata, ImportPreview,
  CheckSelectionMutation, CheckSelectionValidation, CheckTargetSelection, LexiconEntryResponse, NativeCheckListResponse,
  NativeCheckTool, NavigationSyncState, ProjectInfo, RegisteredProject, VerseAlignment, VerseData, QaFinding, SettingsData,
  IssueResolutionHandoffResult, IssueResolutionListResponse, IssueResolutionRecord,
  ProjectReport, CollectionReport, SemanticValidationCorrection, SemanticValidationQueue,
} from "../types/finding";
import type {
  DecideFindingResult,
  DecideLocationResult,
  DecideMeaningResult,
  EntityHistory,
  MeaningStatus,
  QaFindingDetail,
  ReviewEntityType,
  ReviewQueueFilters,
  ReviewQueuePage,
  ReviewRecord,
  ReviewerDecision,
} from "../types/qaReview";
import type {
  CurrentPassageSnapshot,
  PassageSemanticMigrationReport,
  PassageSemanticProjectMetadata,
  PassageSemanticRuntimeStatus,
  PassageSemanticStaleSummary,
  SemanticUnit,
  SourceInventoryCoverageAccount,
  SourceInventoryDiagnostics,
  SourceSemanticInventory,
  TargetInventoryDiagnostics,
  TargetLanguageCapabilities,
  TargetSearchSpan,
  TargetSemanticInventory,
  SemanticLocationCandidate,
  SemanticLocationDiagnostics,
  SemanticLocationRelationship,
  SemanticLocationRun,
  MeaningAnalysisRun,
  MeaningAssessment,
  MeaningComponentAssessment,
  MeaningAnalysisDiagnostics,
} from "../types/passageSemanticV1";
import type {
  AnalysisJobSnapshot,
  AnalysisScope,
  AnalysisScopeStatus,
} from "../types/analysisJob";
import type {
  ReportExportColumn,
  ReportExportResult,
  ReportGetResponse,
  ReportJobSnapshot,
  ReportRow,
} from "../types/report";

/**
 * Thin wrapper around Tauri's invoke() calling the real commands defined
 * in src-tauri/src/commands.rs, which forward to BridgeEngine over the
 * sidecar (engine/bridge_service.py). This file is the ONLY place that
 * imports @tauri-apps/api — swapping to an HTTP transport for a future
 * web build means rewriting this file only, not any component.
 */

async function invoke<T>(cmd: string, args?: Record<string, unknown>): Promise<T> {
  const { invoke: tauriInvoke } = await import("@tauri-apps/api/core");
  return tauriInvoke<T>(cmd, args);
}

export type FileDropPhase = "over" | "drop" | "leave";

/**
 * Native OS drag-and-drop (dropping a file/folder from Explorer onto the window),
 * not the HTML5 drag/drop DOM API — Tauri's webview intercepts that itself. `onDrop`
 * fires with the dropped path(s) once the drop completes; `onPhaseChange` is optional
 * and only useful for "is something being dragged over the window right now" styling.
 * Returns an unlisten function the caller must invoke on unmount.
 */
async function onFileDrop(
  onDrop: (paths: string[]) => void,
  onPhaseChange?: (phase: FileDropPhase) => void,
): Promise<() => void> {
  const { getCurrentWebview } = await import("@tauri-apps/api/webview");
  return getCurrentWebview().onDragDropEvent((event) => {
    const payload = event.payload;
    if (payload.type === "drop") {
      onPhaseChange?.("drop");
      onDrop(payload.paths);
    } else if (payload.type === "over") {
      onPhaseChange?.("over");
    } else if (payload.type === "leave") {
      onPhaseChange?.("leave");
    }
  });
}

export interface EngineLogEntry {
  ts_ms: number;
  level: "info" | "warn" | "error";
  message: string;
}

/** Live diagnostics entries as sidecar.rs records them (spawn/restart/
 * terminate, request timeouts, relayed stderr). Fires after the initial
 * `engineLogRecent()` fetch, so the panel never needs to poll. */
async function onEngineLog(onEntry: (entry: EngineLogEntry) => void): Promise<() => void> {
  const { listen } = await import("@tauri-apps/api/event");
  return listen<EngineLogEntry>("engine-log", (event) => onEntry(event.payload));
}

/** Fires when sidecar.rs silently respawns bridge-engine.exe mid-session
 * (it crashed, or something else killed it) — the new process has no
 * project open, so anything project-scoped will fail until it's reopened. */
async function onEngineRespawned(onRespawn: () => void): Promise<() => void> {
  const { listen } = await import("@tauri-apps/api/event");
  return listen("engine-respawned", () => onRespawn());
}

interface EngineEnvelope<T> {
  id: string;
  success: boolean;
  result?: T;
  findings?: QaFinding[];
  error?: { code: string; message: string };
}

async function call<T>(cmd: string, args?: Record<string, unknown>): Promise<T> {
  const envelope = await invoke<EngineEnvelope<T>>(cmd, args);
  if (!envelope.success) {
    throw new Error(envelope.error?.message ?? `${cmd} failed`);
  }
  return (envelope.result ?? (envelope as unknown)) as T;
}

export const bridge = {
  ping(): Promise<{ pong: boolean }> {
    return call("engine_ping");
  },

  onFileDrop,
  onEngineLog,
  onEngineRespawned,

  engineInfo(): Promise<Record<string, unknown>> {
    return call("engine_info");
  },

  engineLogRecent(limit?: number): Promise<EngineLogEntry[]> {
    return invoke<EngineLogEntry[]>("engine_log_recent", { limit });
  },

  async pickProjectFolder(): Promise<string | null> {
    return invoke<string | null>("pick_project_folder");
  },

  async pickImportFile(): Promise<string | null> {
    return invoke<string | null>("pick_import_file");
  },

  openProject(path: string, projectId?: string): Promise<ProjectInfo> {
    return call("project_open", { path, projectId });
  },

  listProjects(): Promise<{ projects: RegisteredProject[] }> {
    return call("project_list");
  },

  listBookProgress(): Promise<{ books: BookProgressEntry[] }> {
    return call("project_list_book_progress");
  },

  forgetProject(projectId: string): Promise<{ forgotten: boolean }> {
    return call("project_forget", { projectId });
  },

  deleteProject(projectId: string): Promise<{ deleted: boolean; managed: boolean }> {
    return call("project_delete", { projectId });
  },

  scanProject(): Promise<{ chapters: string[]; checkTypes: Record<string, number>; indexTools: Record<string, number> }> {
    return call("project_scan");
  },

  projectReport(): Promise<ProjectReport> {
    return call("project_report");
  },

  projectCollectionReport(): Promise<CollectionReport> {
    return call("project_collection_report");
  },

  // --- Whole-collection QA report (engine/tc_ai_bridge/qa_report.py) -------
  // A background build: generate, poll status, fetch once with get. Export
  // writes the rows the report screen has filtered down to.

  reportGenerate(): Promise<ReportJobSnapshot> {
    return call("report_generate");
  },

  reportStatus(jobId: string): Promise<ReportJobSnapshot> {
    return call("report_status", { jobId });
  },

  reportGet(jobId: string): Promise<ReportGetResponse> {
    return call("report_get", { jobId });
  },

  reportCancel(jobId: string): Promise<ReportJobSnapshot> {
    return call("report_cancel", { jobId });
  },

  reportExport(
    outputPath: string, format: "csv" | "tsv", rows: ReportRow[], columns: ReportExportColumn[],
  ): Promise<ReportExportResult> {
    return call("report_export", { outputPath, format, rows, columns });
  },

  inspectImport(path: string, metadata?: ImportMetadata): Promise<ImportPreview> {
    return call("project_inspect_import", { path, metadata });
  },

  importProject(path: string, metadata: ImportMetadata, allowDuplicate = false): Promise<ProjectInfo> {
    return call("project_import", { path, metadata, allowDuplicate });
  },

  chapterVerses(chapter: string): Promise<{ verses: string[] }> {
    return call("chapter_verses", { chapter });
  },

  chapterVerseData(chapter: string): Promise<{ chapter: string; verses: Record<string, VerseData> }> {
    return call("chapter_verse_data", { chapter });
  },

  getVerse(chapter: string, verse: string): Promise<VerseData> {
    return call("verse_get", { chapter, verse });
  },

  async runVerseChecks(chapter: string, verse: string, checks: string[]): Promise<QaFinding[]> {
    const envelope = await invoke<EngineEnvelope<unknown>>("verse_run_checks", { chapter, verse, checks });
    if (!envelope.success) throw new Error(envelope.error?.message ?? "verse_run_checks failed");
    return envelope.findings ?? [];
  },

  startChecks(scope: "chapter" | "book", chapters: string[], checks: string[]): Promise<CheckJobSnapshot> {
    return call("checks_start", { scope, chapters, checks });
  },

  checkStatus(jobId: string): Promise<CheckJobSnapshot> {
    return call("checks_status", { jobId });
  },

  cancelChecks(jobId: string): Promise<CheckJobSnapshot> {
    return call("checks_cancel", { jobId });
  },

  retryChecks(jobId: string): Promise<CheckJobSnapshot> {
    return call("checks_retry", { jobId });
  },

  decideVerse(
    chapter: string, verse: string, findingId: string,
    status: string, comment?: string,
  ): Promise<Record<string, unknown>> {
    return call("verse_decide", { chapter, verse, findingId, status, comment });
  },

  editVerse(chapter: string, verse: string, newText: string): Promise<{
    committed: boolean;
    issueResolutionsNeedingRecheck: number;
  }> {
    return call("verse_edit", { chapter, verse, newText });
  },

  listChecksForVerse(chapter: string, verse: string): Promise<NativeCheckListResponse> {
    return call("check_list_for_verse", { chapter, verse });
  },

  validateCheckSelection(
    chapter: string, verse: string, tool: NativeCheckTool, groupId: string, checkId: string,
    selections: CheckTargetSelection[], nothingToSelect: boolean,
  ): Promise<CheckSelectionValidation> {
    return call("check_validate_selection", {
      chapter, verse, tool, groupId, checkId, selections, nothingToSelect,
    });
  },

  saveCheckSelection(
    chapter: string, verse: string, tool: NativeCheckTool, groupId: string, checkId: string,
    selections: CheckTargetSelection[], nothingToSelect: boolean,
    provenance: "human" | "bridge_ai", expectedFingerprint: string,
    metadata: Record<string, unknown> = {},
  ): Promise<CheckSelectionMutation> {
    return call("check_save_selection", {
      chapter, verse, tool, groupId, checkId, selections, nothingToSelect,
      provenance, expectedFingerprint, metadata,
    });
  },

  clearCheckSelection(
    chapter: string, verse: string, tool: NativeCheckTool, groupId: string, checkId: string,
    provenance: "human" | "bridge_ai", expectedFingerprint: string,
    metadata: Record<string, unknown> = {},
  ): Promise<CheckSelectionMutation> {
    return call("check_clear_selection", {
      chapter, verse, tool, groupId, checkId, provenance, expectedFingerprint, metadata,
    });
  },

  listIssueResolutions(chapter: string, verse: string): Promise<IssueResolutionListResponse> {
    return call("issue_resolution_list", { chapter, verse });
  },

  saveIssueResolution(
    chapter: string, verse: string,
    check: { tool: NativeCheckTool; groupId: string; checkId: string; expectedFingerprint: string },
    values: {
      selectedText: string;
      issueSummary: string;
      reviewerNote: string;
      proposedCorrection: string;
      evidence: Array<Record<string, unknown> | string>;
    },
  ): Promise<IssueResolutionRecord> {
    return call("issue_resolution_save", {
      chapter, verse, tool: check.tool, groupId: check.groupId, checkId: check.checkId,
      expectedFingerprint: check.expectedFingerprint, ...values,
    });
  },

  queueIssueResolutionForParatext(
    chapter: string, verse: string, resolutionId: string, expectedProjectId = "",
  ): Promise<IssueResolutionHandoffResult> {
    return call("issue_resolution_queue_paratext", {
      chapter, verse, resolutionId, expectedProjectId,
    });
  },

  retryIssueResolutionParatext(
    chapter: string, verse: string, resolutionId: string,
  ): Promise<IssueResolutionHandoffResult> {
    return call("issue_resolution_retry_paratext", { chapter, verse, resolutionId });
  },

  getAlignment(chapter: string, verse: string): Promise<AlignmentContext> {
    return call("alignment_get", { chapter, verse });
  },

  getLexiconEntry(strong: string, morph: string): Promise<LexiconEntryResponse> {
    return call("lexicon_get_entry", { strong, morph });
  },

  alignmentStatus(chapter?: string): Promise<AlignmentStatusResponse> {
    return call("alignment_status", chapter ? { chapter } : {});
  },

  realignWords(
    chapter: string, verse: string, topIds: string[], bottomIds: string[],
    expectedOriginal: VerseAlignment,
  ): Promise<AlignmentContext> {
    return call("alignment_realign", { chapter, verse, topIds, bottomIds, expectedOriginal });
  },

  unalignWords(
    chapter: string, verse: string, bottomIds: string[], expectedOriginal: VerseAlignment,
  ): Promise<AlignmentContext> {
    return call("alignment_unalign", { chapter, verse, bottomIds, expectedOriginal });
  },

  saveAlignment(
    chapter: string, verse: string, alignment: VerseAlignment, expectedOriginal: VerseAlignment,
  ): Promise<AlignmentContext> {
    return call("alignment_save", { chapter, verse, alignment, expectedOriginal });
  },

  completeAlignment(chapter: string, verse: string): Promise<AlignmentContext> {
    return call("alignment_complete", { chapter, verse });
  },

  undoAlignment(
    chapter: string, verse: string, expectedOriginal: VerseAlignment,
  ): Promise<AlignmentContext> {
    return call("alignment_undo", { chapter, verse, expectedOriginal });
  },

  alignmentBackups(chapter: string, verse: string): Promise<{ history: AlignmentContext["history"] }> {
    return call("alignment_backups", { chapter, verse });
  },

  restoreAlignment(
    chapter: string, verse: string, historyId: string, expectedOriginal: VerseAlignment,
  ): Promise<AlignmentContext> {
    return call("alignment_restore", { chapter, verse, historyId, expectedOriginal });
  },

  /** Read-only: nothing is written to project files. See aiApplyAlignmentProposal. */
  aiProposeAlignment(chapter: string, verse: string, mode: "gap_fill" | "audit" = "gap_fill"): Promise<AlignmentAiProposeResponse> {
    return call("alignment_ai_propose", { chapter, verse, mode });
  },

  aiApplyAlignmentProposal(
    chapter: string, verse: string, proposal: AlignmentAiProposal, expectedOriginal: VerseAlignment,
  ): Promise<AlignmentContext> {
    return call("alignment_ai_apply_proposal", { chapter, verse, proposal, expectedOriginal });
  },

  /** Read-only AI preparation of a verse's checks — nothing is written to project files. */
  aiExplainVerse(chapter: string, verse: string): Promise<AiExplainResult> {
    return call("ai_explain", { chapter, verse });
  },

  startAIReview(
    scope: "verse" | "chapter" | "book", chapter: string, verse: string,
    mode: "basic" | "advanced",
  ): Promise<AIReviewJobSnapshot> {
    return call("ai_review_start", { scope, chapter, verse, mode });
  },

  aiReviewStatus(jobId: string): Promise<AIReviewJobSnapshot> {
    return call("ai_review_status", { jobId });
  },

  cancelAIReview(jobId: string): Promise<AIReviewJobSnapshot> {
    return call("ai_review_cancel", { jobId });
  },

  retryAIReview(jobId: string): Promise<AIReviewJobSnapshot> {
    return call("ai_review_retry", { jobId });
  },

  listAIReviewsForChapter(chapter: string): Promise<AIReviewChapterResponse> {
    return call("ai_review_list_chapter", { chapter });
  },

  listSemanticValidationCandidates(): Promise<SemanticValidationQueue> {
    return call("semantic_validation_list");
  },

  decideSemanticValidationCandidate(
    candidateId: string,
    decision: "confirmed" | "rejected" | "corrected" | "unsure",
    reviewer: string,
    note = "",
    correctedMapping?: SemanticValidationCorrection,
  ): Promise<{ saved: boolean; event: Record<string, unknown>; auditPath: string }> {
    return call("semantic_validation_decide", {
      candidateId, decision, reviewer, note, correctedMapping,
    });
  },

  passageSemanticStatus(): Promise<PassageSemanticRuntimeStatus> {
    return call("passage_semantic_status");
  },

  passageSemanticProjectMetadata(): Promise<PassageSemanticProjectMetadata> {
    return call("passage_semantic_project_metadata");
  },

  passageSemanticCurrentPassage(
    chapter: string, verse: string, endChapter?: string, endVerse?: string,
  ): Promise<CurrentPassageSnapshot> {
    return call("passage_semantic_current_passage", {
      chapter, verse, endChapter, endVerse,
    });
  },

  passageSemanticStaleSummary(): Promise<PassageSemanticStaleSummary> {
    return call("passage_semantic_stale_summary");
  },

  passageSemanticMigrationReport(): Promise<PassageSemanticMigrationReport> {
    return call("passage_semantic_migration_report");
  },

  passageSemanticRebuildPassage(
    chapter: string,
    verse: string,
    options: {
      endChapter?: string;
      endVerse?: string;
      tokenizerProfile?: "bridge-unicode-word-v1" | "tc-whitespace-v1";
    } = {},
  ): Promise<CurrentPassageSnapshot> {
    return call("passage_semantic_rebuild_passage", {
      chapter, verse, ...options,
    });
  },

  sourceSemanticBuildRange(
    chapter: string, verse: string, endChapter?: string, endVerse?: string,
  ): Promise<SourceSemanticInventory> {
    return call("source_semantic_build_range", { chapter, verse, endChapter, endVerse });
  },

  sourceSemanticGetRange(inventoryId: string): Promise<SourceSemanticInventory> {
    return call("source_semantic_get_range", { inventoryId });
  },

  sourceSemanticGetUnit(unitId: string): Promise<SemanticUnit> {
    return call("source_semantic_get_unit", { unitId });
  },

  sourceSemanticGetCoverageAccounts(inventoryId: string): Promise<SourceInventoryCoverageAccount[]> {
    return call("source_semantic_get_coverage_accounts", { inventoryId });
  },

  sourceSemanticGetDiagnostics(inventoryId: string): Promise<SourceInventoryDiagnostics> {
    return call("source_semantic_get_diagnostics", { inventoryId });
  },

  targetSemanticBuildRange(
    chapter: string, verse: string, endChapter?: string, endVerse?: string,
  ): Promise<TargetSemanticInventory> {
    return call("target_semantic_build_range", { chapter, verse, endChapter, endVerse });
  },

  targetSemanticGetRange(inventoryId: string): Promise<TargetSemanticInventory> {
    return call("target_semantic_get_range", { inventoryId });
  },

  targetSemanticGetUnit(unitId: string): Promise<SemanticUnit> {
    return call("target_semantic_get_unit", { unitId });
  },

  targetSemanticGetDiagnostics(inventoryId: string): Promise<TargetInventoryDiagnostics> {
    return call("target_semantic_get_diagnostics", { inventoryId });
  },

  targetSemanticGetSearchSpans(inventoryId: string): Promise<TargetSearchSpan[]> {
    return call("target_semantic_get_search_spans", { inventoryId });
  },

  targetSemanticGetCapabilities(inventoryId?: string): Promise<TargetLanguageCapabilities> {
    return call("target_semantic_get_capabilities", { inventoryId });
  },

  semanticLocationRunRange(
    chapter: string, verse: string, endChapter?: string, endVerse?: string,
    maxCandidateEvaluations?: number,
  ): Promise<SemanticLocationRun> {
    return call("semantic_location_run_range", {
      chapter, verse, endChapter, endVerse, maxCandidateEvaluations,
    });
  },

  semanticLocationStatus(runId: string): Promise<Pick<SemanticLocationRun, "id" | "runStatus" | "diagnostics" | "cacheStatus">> {
    return call("semantic_location_status", { runId });
  },

  semanticLocationGetRange(runId: string): Promise<SemanticLocationRun> {
    return call("semantic_location_get_range", { runId });
  },

  semanticLocationGetRelationship(relationshipId: string): Promise<SemanticLocationRelationship> {
    return call("semantic_location_get_relationship", { relationshipId });
  },

  semanticLocationGetCandidates(runId: string, sourceOwnerUnitId?: string): Promise<SemanticLocationCandidate[]> {
    return call("semantic_location_get_candidates", { runId, sourceOwnerUnitId });
  },

  semanticLocationGetDiagnostics(runId: string): Promise<SemanticLocationDiagnostics> {
    return call("semantic_location_get_diagnostics", { runId });
  },

  meaningAnalysisRunRange(
    chapter: string, verse: string, endChapter?: string, endVerse?: string,
    locationRunId?: string,
  ): Promise<MeaningAnalysisRun> {
    return call("meaning_analysis_run_range", {
      chapter, verse, endChapter, endVerse, locationRunId,
    });
  },

  meaningAnalysisStatus(runId: string): Promise<Pick<MeaningAnalysisRun, "id" | "runStatus" | "diagnostics" | "cacheStatus">> {
    return call("meaning_analysis_status", { runId });
  },

  meaningAnalysisGetRange(runId: string): Promise<MeaningAnalysisRun> {
    return call("meaning_analysis_get_range", { runId });
  },

  meaningAnalysisGetAssessment(assessmentId: string): Promise<MeaningAssessment> {
    return call("meaning_analysis_get_assessment", { assessmentId });
  },

  meaningAnalysisGetComponents(assessmentId: string): Promise<MeaningComponentAssessment[]> {
    return call("meaning_analysis_get_components", { assessmentId });
  },

  meaningAnalysisGetDiagnostics(runId: string): Promise<MeaningAnalysisDiagnostics> {
    return call("meaning_analysis_get_diagnostics", { runId });
  },

  paratextGetState(): Promise<DesktopConnectorState> {
    return call("paratext_get_state");
  },

  paratextSetReference(reference: string, originId?: string): Promise<Record<string, unknown>> {
    return call("paratext_set_reference", { reference, originId });
  },

  logosGetState(): Promise<DesktopConnectorState> {
    return call("logos_get_state");
  },

  logosSetReference(reference: string, originId?: string): Promise<DesktopConnectorState> {
    return call("logos_set_reference", { reference, originId });
  },

  navigationStatus(context?: string): Promise<NavigationSyncState> {
    return call("navigation_status", { context });
  },

  navigationPoll(context?: string): Promise<NavigationSyncState> {
    return call("navigation_poll", { context });
  },

  navigationBridgeChanged(reference: string): Promise<NavigationSyncState> {
    return call("navigation_bridge_changed", { reference });
  },

  navigationResolve(
    requestId: string, accepted: boolean, bridgeReference?: string, context?: string,
  ): Promise<NavigationSyncState> {
    return call("navigation_resolve", { requestId, accepted, bridgeReference, context });
  },

  getSettings(): Promise<SettingsData> {
    return call("settings_get");
  },

  setSettings(params: Record<string, unknown>): Promise<SettingsData> {
    return call("settings_set", { params });
  },

  pickSavePath(defaultName: string): Promise<string | null> {
    return invoke<string | null>("pick_save_path", { defaultName });
  },

  exportAligned(outputPath: string): Promise<{ written: boolean; path: string; chapters: number }> {
    return call("export_aligned", { outputPath });
  },

  exportNonAligned(outputPath: string): Promise<{ written: boolean; path: string; chapters: number }> {
    return call("export_non_aligned", { outputPath });
  },

  // --- Stage 8 QA audit (analysis; read-only) -------------------------------

  qaAuditRunRange(
    chapter: string, verse: string, endChapter?: string, endVerse?: string,
    meaningRunId?: string,
  ): Promise<Record<string, unknown>> {
    return call("qa_audit_run_range", { chapter, verse, endChapter, endVerse, meaningRunId });
  },

  qaAuditStatus(runId: string): Promise<Record<string, unknown>> {
    return call("qa_audit_status", { runId });
  },

  qaAuditGetRange(runId: string): Promise<Record<string, unknown>> {
    return call("qa_audit_get_range", { runId });
  },

  qaAuditGetSourceCoverage(runId: string): Promise<Array<Record<string, unknown>>> {
    return call("qa_audit_get_source_coverage", { runId });
  },

  qaAuditGetTargetSupport(runId: string): Promise<Array<Record<string, unknown>>> {
    return call("qa_audit_get_target_support", { runId });
  },

  qaAuditGetFinding(findingId: string): Promise<Record<string, unknown>> {
    return call("qa_audit_get_finding", { findingId });
  },

  qaAuditGetDiagnostics(runId: string): Promise<Record<string, unknown>> {
    return call("qa_audit_get_diagnostics", { runId });
  },

  // --- Stage 9A human review (decisions only; never edits Scripture) --------

  qaReviewGetQueue(filters: ReviewQueueFilters = {}): Promise<ReviewQueuePage> {
    return call("qa_review_get_queue", {
      book: filters.book,
      chapter: filters.chapter,
      canonicalReferences: filters.canonicalReferences,
      kinds: filters.kinds,
      severities: filters.severities,
      dispositions: filters.dispositions,
      reviewStatuses: filters.reviewStatuses,
      lifecycleStatuses: filters.lifecycleStatuses,
      order: filters.order,
      limit: filters.limit,
      cursor: filters.cursor,
    });
  },

  qaReviewGetFinding(findingId: string): Promise<QaFindingDetail> {
    return call("qa_review_get_finding", { findingId });
  },

  /**
   * Record a reviewer's conclusion. `expectedEntityRevision` and
   * `expectedTargetContentHashes` are what make this safe: the engine rejects
   * the write with a `revision_conflict` error rather than clobbering a
   * decision made elsewhere, or accepting one made against text that has since
   * changed. `promote` is the only route from POSSIBLY_MISSING to MISSING.
   */
  qaReviewDecideFinding(
    findingId: string,
    disposition: ReviewerDecision,
    expectedEntityRevision: number,
    options: {
      note?: string;
      promote?: boolean;
      expectedTargetContentHashes?: string[];
    } = {},
  ): Promise<DecideFindingResult> {
    return call("qa_review_decide_finding", {
      findingId,
      disposition,
      expectedEntityRevision,
      expectedTargetContentHashes: options.expectedTargetContentHashes,
      note: options.note,
      promote: options.promote,
    });
  },

  qaReviewAddNote(
    entityType: ReviewEntityType, entityId: string, note: string,
  ): Promise<{ history: ReviewRecord[] }> {
    return call("qa_review_add_note", { entityType, entityId, note });
  },

  /**
   * Approve or reject a Stage 6B location. This is a mapping verdict, not a
   * translation verdict: rejecting says Bridge looked in the wrong place, and
   * leaves the QA disposition untouched.
   */
  semanticReviewDecideLocation(
    relationshipId: string,
    decision: "APPROVE" | "REJECT",
    expectedEntityRevision: number,
    options: { note?: string; selectedCandidateId?: string } = {},
  ): Promise<DecideLocationResult> {
    return call("semantic_review_decide_location", {
      relationshipId,
      decision,
      expectedEntityRevision,
      note: options.note,
      selectedCandidateId: options.selectedCandidateId,
    });
  },

  semanticReviewDecideMeaning(
    assessmentId: string,
    meaningStatus: MeaningStatus,
    expectedEntityRevision: number,
    note?: string,
  ): Promise<DecideMeaningResult> {
    return call("semantic_review_decide_meaning", {
      assessmentId, meaningStatus, expectedEntityRevision, note,
    });
  },

  reviewHistoryGetEntityHistory(
    entityType: ReviewEntityType, entityId: string,
  ): Promise<EntityHistory> {
    return call("review_history_get_entity_history", { entityType, entityId });
  },

  // Stage 9A.4 orchestrates the frozen Stage 5--8 engines. Starting a job is
  // explicit; project open only reports persisted state and never starts one.
  analysisJobStart(
    requestedScope: AnalysisScope,
    expectedAnalysisFingerprint: string,
  ): Promise<AnalysisJobSnapshot> {
    return call("analysis_job_start", { requestedScope, expectedAnalysisFingerprint });
  },

  analysisJobStatus(jobId: string): Promise<AnalysisJobSnapshot> {
    return call("analysis_job_status", { jobId });
  },

  analysisJobCancel(jobId: string): Promise<AnalysisJobSnapshot> {
    return call("analysis_job_cancel", { jobId });
  },

  analysisJobGetRecent(limit = 20): Promise<AnalysisJobSnapshot[]> {
    return call("analysis_job_get_recent", { limit });
  },

  analysisJobGetScopeStatus(requestedScope: AnalysisScope): Promise<AnalysisScopeStatus> {
    return call("analysis_job_get_scope_status", { requestedScope });
  },
};
