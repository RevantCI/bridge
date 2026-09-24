import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { get } from "svelte/store";
import type { LanguageQaFinding, LanguageQaStatus } from "../../types/languageQa";
import { languageQaFindingsByVerse } from "../../stores";

const statusCall = vi.fn();
const pauseCall = vi.fn();
vi.mock("../../api/bridgeClient", () => ({ bridge: {
  languageQaStatus: (...args: unknown[]) => statusCall(...args),
  languageQaPause: (...args: unknown[]) => pauseCall(...args),
} }));
import LanguageQaPanel from "../LanguageQaPanel.svelte";

function snapshot(overrides: Partial<LanguageQaStatus> = {}): LanguageQaStatus {
  return {
    projectPath: "C:/project", book: "php", generation: 1, state: "completed",
    ruleVersion: "language-qa-1", totalFindings: 1, offset: 0,
    completedChapters: 1, totalChapters: 1, limitations: [],
    coverage: "Technical checks; no grammar certification.", storage: "Session results.",
    language: { declared: "tam", language: "tam", script: "TAMIL", basis: "metadata",
      pack: "tamil", message: "Tamil character rules available." },
    findings: [{ id: "f1", book: "php", chapter: "2", verse: "3-4", rule: "unicode.corruption",
      severity: "high", start: 0, end: 1, originalText: "�", message: "Check source encoding.",
      textHash: "hash", ruleVersion: "language-qa-1", status: "review-needed" }],
    ...overrides,
  };
}

beforeEach(() => {
  statusCall.mockReset().mockImplementation(async (_path, _offset, limit) =>
    snapshot({ findings: limit ? snapshot().findings : [] }));
  pauseCall.mockReset().mockResolvedValue(snapshot({ state: "paused", findings: [] }));
});

describe("Language QA", () => {
  it("stays collapsed automatically and fetches only the count while closed", async () => {
    // Inline marks come from languageQa.inline (languageQaInline.ts), not
    // from this panel's page, so collapsed needs the total only.
    render(LanguageQaPanel, { projectPath: "C:/project", onNavigate: vi.fn() });
    await waitFor(() => expect(statusCall).toHaveBeenCalledWith("C:/project", 0, 0));
    expect(screen.queryByRole("region", { name: "Language QA results" })).toBeNull();
    expect(screen.queryByText("Check source encoding.")).toBeNull();
  });

  it("loads findings on demand and navigates exact verse bridges", async () => {
    const navigate = vi.fn();
    render(LanguageQaPanel, { projectPath: "C:/project", onNavigate: navigate });
    await screen.findByRole("button", { name: /Language QA · completed/ });
    await fireEvent.click(screen.getByRole("button", { name: /Language QA · completed/ }));
    await screen.findByText("Check source encoding.");
    await fireEvent.click(screen.getByRole("button", { name: "PHP 2:3-4" }));
    expect(navigate).toHaveBeenCalledWith("php", "2", "3-4");
    expect(statusCall).toHaveBeenLastCalledWith("C:/project", 0, 50);
  });

  it("shows incomplete coverage instead of claiming a clean publication", async () => {
    statusCall.mockResolvedValue(snapshot({ totalFindings: 0, findings: [], incomplete: true,
      limitations: ["Inline USFM omitted."] }));
    render(LanguageQaPanel, { projectPath: "C:/project", onNavigate: vi.fn() });
    await fireEvent.click(await screen.findByRole("button", { name: /Language QA · completed/ }));
    expect(screen.getByText(/Coverage incomplete/)).toBeTruthy();
    expect(screen.getByText(/not publication approval/)).toBeTruthy();
  });

  it("pauses through the project-guarded endpoint", async () => {
    render(LanguageQaPanel, { projectPath: "C:/project", onNavigate: vi.fn() });
    await fireEvent.click(await screen.findByRole("button", { name: /Language QA · completed/ }));
    await screen.findByText("Check source encoding.");
    statusCall.mockResolvedValue(snapshot({ state: "paused", findings: [] }));
    await fireEvent.click(screen.getByRole("button", { name: "Pause checks" }));
    expect(pauseCall).toHaveBeenCalledWith("C:/project", true);
    await screen.findByRole("button", { name: "Resume checks" });
  });

  it("does not display a response belonging to a different project", async () => {
    statusCall.mockResolvedValue(snapshot({ projectPath: "C:/old-project" }));
    render(LanguageQaPanel, { projectPath: "C:/project", onNavigate: vi.fn() });
    await waitFor(() => expect(statusCall).toHaveBeenCalled());
    await fireEvent.click(screen.getByRole("button", { name: /Language QA/ }));
    expect(screen.queryByText("Check source encoding.")).toBeNull();
  });

  it("never writes the inline-marks store, whatever page it shows", async () => {
    // The panel used to fill languageQaFindingsByVerse from its own page, so
    // any inline finding past the first 100 in the book never got a mark.
    // The store now belongs to languageQaInline.ts; paging here must not touch it.
    const seeded: Record<string, LanguageQaFinding[]> = { "1:1": [{ id: "keep", book: "php", chapter: "1",
      verse: "1", rule: "terminology.deprecated-form", severity: "high", start: 0, end: 3,
      originalText: "bad", message: "Deprecated.", textHash: "h", ruleVersion: "language-qa-6",
      status: "review-needed", suggestedReplacement: "good" }] };
    languageQaFindingsByVerse.set(seeded);
    statusCall.mockImplementation(async (_path, _offset, limit) => snapshot({
      totalFindings: 120,
      findings: limit ? [{ id: "f2", book: "php", chapter: "3", verse: "9", rule: "terminology.deprecated-form",
        severity: "high", start: 0, end: 3, originalText: "bad", message: "Deprecated.",
        textHash: "hash2", ruleVersion: "language-qa-6", status: "review-needed",
        suggestedReplacement: "good" }] : [],
    }));
    render(LanguageQaPanel, { projectPath: "C:/project", onNavigate: vi.fn() });
    await fireEvent.click(await screen.findByRole("button", { name: /Language QA · completed/ }));
    await screen.findByText("Deprecated.");
    expect(get(languageQaFindingsByVerse)).toEqual(seeded);
  });

  it("surfaces failure and leaves automatic retry scheduled", async () => {
    statusCall.mockRejectedValue(new Error("Engine unavailable"));
    render(LanguageQaPanel, { projectPath: "C:/project", onNavigate: vi.fn() });
    await fireEvent.click(await screen.findByRole("button", { name: /Language QA · unavailable/ }));
    expect(screen.getByRole("alert").textContent).toContain("Engine unavailable");
  });
});
