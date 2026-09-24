import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { get } from "svelte/store";
import type { LanguageQaFinding, LanguageQaStatus } from "../../types/languageQa";
import { languageQaFindingsByVerse } from "../../stores";
import { lqaFinding } from "./languageQaFixture";

const statusCall = vi.fn();
const pauseCall = vi.fn();
const historyCall = vi.fn();
vi.mock("../../api/bridgeClient", () => ({ bridge: {
  languageQaStatus: (...args: unknown[]) => statusCall(...args),
  languageQaPause: (...args: unknown[]) => pauseCall(...args),
  languageQaHistory: (...args: unknown[]) => historyCall(...args),
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
    findings: [lqaFinding({ id: "f1", chapter: "2", verse: "3-4", rule: "unicode.corruption",
      severity: "high", start: 0, end: 1, originalText: "�", message: "Check source encoding.",
      suggestedReplacement: null })],
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
    await waitFor(() => expect(statusCall).toHaveBeenCalledWith("C:/project", 0, 0, "findings"));
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
    expect(statusCall).toHaveBeenLastCalledWith("C:/project", 0, 50, "findings");
  });

  it("shows incomplete coverage instead of claiming a clean publication", async () => {
    statusCall.mockResolvedValue(snapshot({ totalFindings: 0, findings: [], incomplete: true,
      limitations: ["Chapter 1: 4: Unbalanced \\f: 1 open, 0 close; verse not checked."] }));
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
    const seeded: Record<string, LanguageQaFinding[]> = { "1:1": [lqaFinding({ id: "keep", chapter: "1",
      verse: "1", rule: "terminology.deprecated-form", start: 0, end: 3,
      originalText: "bad", message: "Deprecated.", suggestedReplacement: "good" })] };
    languageQaFindingsByVerse.set(seeded);
    statusCall.mockImplementation(async (_path, _offset, limit) => snapshot({
      totalFindings: 120,
      findings: limit ? [lqaFinding({ id: "f2", chapter: "3", verse: "9", rule: "terminology.deprecated-form",
        start: 0, end: 3, originalText: "bad", message: "Deprecated.", suggestedReplacement: "good" })] : [],
    }));
    render(LanguageQaPanel, { projectPath: "C:/project", onNavigate: vi.fn() });
    await fireEvent.click(await screen.findByRole("button", { name: /Language QA · completed/ }));
    await screen.findByText("Deprecated.");
    expect(get(languageQaFindingsByVerse)).toEqual(seeded);
  });

  it("lists re-check and false-positive findings separately, each paged by the engine", async () => {
    statusCall.mockImplementation(async (_path, _offset, limit, view) => snapshot({
      view, recheckCount: 1, falsePositiveCount: 2, totalFindings: view === "findings" ? 1 : view === "recheck" ? 1 : 2,
      findings: !limit ? [] : view === "recheck"
        ? [lqaFinding({ id: "r1", message: "Ignored before.", previouslyIgnored: true })]
        : view === "falsePositives"
          ? [lqaFinding({ id: "fp1", message: "Not a problem." }), lqaFinding({ id: "fp2", message: "Also fine." })]
          : snapshot().findings,
    }));
    render(LanguageQaPanel, { projectPath: "C:/project", onNavigate: vi.fn() });
    await fireEvent.click(await screen.findByRole("button", { name: /Language QA · completed/ }));
    await fireEvent.click(await screen.findByRole("tab", { name: "Re-check (1)" }));
    await screen.findByText("Ignored before.");
    expect(statusCall).toHaveBeenLastCalledWith("C:/project", 0, 50, "recheck");
    expect(screen.getByText("Re-check", { selector: ".recheck" })).toBeTruthy();
    await fireEvent.click(screen.getByRole("tab", { name: "False positives (2)" }));
    await screen.findByText("Also fine.");
    expect(statusCall).toHaveBeenLastCalledWith("C:/project", 0, 50, "falsePositives");
    expect(screen.queryByText("Ignored before.")).toBeNull();
  });

  it("loads a finding's decision history only when asked, behind a placeholder", async () => {
    let answer: (value: unknown) => void = () => {};
    historyCall.mockReset().mockReturnValue(new Promise((resolve) => { answer = resolve; }));
    render(LanguageQaPanel, { projectPath: "C:/project", onNavigate: vi.fn() });
    await fireEvent.click(await screen.findByRole("button", { name: /Language QA · completed/ }));
    await screen.findByText("Check source encoding.");
    expect(historyCall).not.toHaveBeenCalled();
    await fireEvent.click(screen.getByRole("button", { name: "History" }));
    expect(screen.getByText("Loading history…")).toBeTruthy();
    expect(historyCall).toHaveBeenCalledWith("C:/project", "2", "3-4", "f1");
    answer({ chapter: "2", verse: "3-4", findingId: "f1", entries: [
      { seq: 4, findingId: "f1", decision: "ignored", note: "", rule: "unicode.corruption", ruleId: "common/unicode.corruption",
        originalText: "�", chosenSuggestion: null, chosenRank: null, packVersion: "language-qa-7",
        recordedAt: "2026-09-24T10:00:00Z", revision: 1, actorId: "a" },
      { seq: 9, findingId: "f1", decision: "rejected", note: "", rule: "unicode.corruption", ruleId: "common/unicode.corruption",
        originalText: "�", chosenSuggestion: null, chosenRank: null, packVersion: "language-qa-7",
        recordedAt: "2026-09-24T11:00:00Z", revision: 2, actorId: "a" },
    ] });
    await screen.findByText("Marked as false positive");
    const items = screen.getByRole("list", { name: "Language QA decision history" }).querySelectorAll("li");
    expect(Array.from(items).map((li) => li.querySelector(".decision")?.textContent))
      .toEqual(["Ignored", "Marked as false positive"]);
  });

  it("surfaces failure and leaves automatic retry scheduled", async () => {
    statusCall.mockRejectedValue(new Error("Engine unavailable"));
    render(LanguageQaPanel, { projectPath: "C:/project", onNavigate: vi.fn() });
    await fireEvent.click(await screen.findByRole("button", { name: /Language QA · unavailable/ }));
    expect(screen.getByRole("alert").textContent).toContain("Engine unavailable");
  });
});
