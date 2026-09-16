import { beforeEach, describe, expect, it, vi } from "vitest";

/**
 * The seam #115 introduced: every engine method goes through the one generic
 * `engine_call` Tauri command, and the client owns the method string and the
 * params shape. These tests pin what the client sends, so a wrapper that
 * drifts (wrong method name, params wrapped one level too deep, envelope
 * unwrapped from the wrong field) fails here instead of in the desktop app.
 */
const { tauriInvoke } = vi.hoisted(() => ({ tauriInvoke: vi.fn() }));

vi.mock("@tauri-apps/api/core", () => ({ invoke: tauriInvoke }));

import { bridge } from "../bridgeClient";

beforeEach(() => {
  tauriInvoke.mockReset();
});

describe("bridgeClient over engine_call", () => {
  it("sends the engine method string and the params object unchanged", async () => {
    tauriInvoke.mockResolvedValue({ id: "1", success: true, result: { bookId: "rut" } });

    const info = await bridge.openProject("C:/projects/rut", "project-1");

    expect(tauriInvoke).toHaveBeenCalledTimes(1);
    expect(tauriInvoke).toHaveBeenCalledWith("engine_call", {
      method: "project.open",
      params: { path: "C:/projects/rut", projectId: "project-1" },
    });
    expect(info).toEqual({ bookId: "rut" });
  });

  it("sends an empty params object for methods that take none", async () => {
    tauriInvoke.mockResolvedValue({ id: "1", success: true, result: { pong: true } });

    await expect(bridge.ping()).resolves.toEqual({ pong: true });
    expect(tauriInvoke).toHaveBeenCalledWith("engine_call", { method: "ping", params: {} });
  });

  it("passes the settings object itself as settings.set params (the engine spreads it)", async () => {
    tauriInvoke.mockResolvedValue({ id: "1", success: true, result: { hasApiKey: false } });

    await bridge.setSettings({ provider: "openai", logosNavigation: true });

    expect(tauriInvoke).toHaveBeenCalledWith("engine_call", {
      method: "settings.set",
      params: { provider: "openai", logosNavigation: true },
    });
  });

  it("leaves optional keys undefined so the engine applies its own defaults", async () => {
    tauriInvoke.mockResolvedValue({ id: "1", success: true, result: { state: "queued" } });

    await bridge.decideVerse("1", "2", "finding-1", "accepted");

    const [, args] = tauriInvoke.mock.calls[0];
    expect(args.method).toBe("verse.decide");
    expect(args.params).toEqual({ chapter: "1", verse: "2", findingId: "finding-1", status: "accepted", comment: undefined });
    // What actually crosses the boundary is JSON, where undefined is absent.
    expect(JSON.parse(JSON.stringify(args.params))).not.toHaveProperty("comment");
  });

  it("reads verse.runChecks findings from the envelope, not from result", async () => {
    tauriInvoke.mockResolvedValue({ id: "1", success: true, findings: [{ id: "f1" }] });

    const findings = await bridge.runVerseChecks("1", "1", ["local"]);

    expect(tauriInvoke).toHaveBeenCalledWith("engine_call", {
      method: "verse.runChecks",
      params: { chapter: "1", verse: "1", checks: ["local"] },
    });
    expect(findings).toEqual([{ id: "f1" }]);
  });

  it("turns an engine error envelope into a thrown Error with the engine's message", async () => {
    tauriInvoke.mockResolvedValue({
      id: "1", success: false, error: { code: "project_error", message: "No project open" },
    });

    await expect(bridge.listBookProgress()).rejects.toThrow("No project open");
  });

  it("does not route the native dialog and log commands through engine_call", async () => {
    tauriInvoke.mockResolvedValue(null);

    await bridge.pickProjectFolder();
    await bridge.pickSavePath("export.usfm");
    await bridge.engineLogRecent(50);

    expect(tauriInvoke.mock.calls.map(([cmd]) => cmd)).toEqual([
      "pick_project_folder", "pick_save_path", "engine_log_recent",
    ]);
  });
});
