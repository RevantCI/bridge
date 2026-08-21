import type {
  AlignmentContext, AlignmentStatusResponse, CheckJobSnapshot, ImportMetadata,
  ImportPreview, ProjectInfo, VerseAlignment, VerseData, QaFinding, SettingsData,
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

  engineInfo(): Promise<Record<string, unknown>> {
    return call("engine_info");
  },

  async pickProjectFolder(): Promise<string | null> {
    return invoke<string | null>("pick_project_folder");
  },

  async pickImportFile(): Promise<string | null> {
    return invoke<string | null>("pick_import_file");
  },

  openProject(path: string): Promise<ProjectInfo> {
    return call("project_open", { path });
  },

  scanProject(): Promise<{ chapters: string[]; checkTypes: Record<string, number>; indexTools: Record<string, number> }> {
    return call("project_scan");
  },

  inspectImport(path: string): Promise<ImportPreview> {
    return call("project_inspect_import", { path });
  },

  importProject(path: string, metadata: ImportMetadata): Promise<ProjectInfo> {
    return call("project_import", { path, metadata });
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
