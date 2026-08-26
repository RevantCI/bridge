import type {
  AiExplainResult, AIReviewChapterResponse, AIReviewJobSnapshot, AlignmentAiProposal, AlignmentAiProposeResponse, AlignmentContext,
  AlignmentStatusResponse, CheckJobSnapshot, DesktopConnectorState, ImportMetadata, ImportPreview,
  CheckSelectionMutation, CheckSelectionValidation, CheckTargetSelection, NativeCheckListResponse,
  NativeCheckTool, ProjectInfo, RegisteredProject, VerseAlignment, VerseData, QaFinding, SettingsData,
} from "../types/finding";

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

  engineInfo(): Promise<Record<string, unknown>> {
    return call("engine_info");
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

  forgetProject(projectId: string): Promise<{ forgotten: boolean }> {
    return call("project_forget", { projectId });
  },

  scanProject(): Promise<{ chapters: string[]; checkTypes: Record<string, number>; indexTools: Record<string, number> }> {
    return call("project_scan");
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

  editVerse(chapter: string, verse: string, newText: string): Promise<{ committed: boolean }> {
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

  getAlignment(chapter: string, verse: string): Promise<AlignmentContext> {
    return call("alignment_get", { chapter, verse });
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
};
