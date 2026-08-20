import type { ImportMetadata, ImportPreview, ProjectInfo, VerseData, QaFinding, SettingsData } from "../types/finding";

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

  chapterVerseData(chapter: string): Promise<{ chapter: string; verses: Record<string, { text: string; alignment: unknown }> }> {
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

  decideVerse(
    chapter: string, verse: string, findingId: string,
    status: string, comment?: string,
  ): Promise<Record<string, unknown>> {
    return call("verse_decide", { chapter, verse, findingId, status, comment });
  },

  editVerse(chapter: string, verse: string, newText: string): Promise<{ committed: boolean }> {
    return call("verse_edit", { chapter, verse, newText });
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
