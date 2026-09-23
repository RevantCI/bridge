import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { get } from "svelte/store";
import type { LanguageQaStatus } from "../../types/languageQa";
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
  it("stays collapsed automatically, but still fetches real findings for VerseList's inline decoration", async () => {
    // Collapsed used to request limit=0 (count only) since the panel itself
    // only ever showed the total while closed. It now requests a real page
    // even collapsed -- VerseList's double-underline decoration needs
    // finding data regardless of whether this panel is open -- while the
    // panel's own UI still stays visually collapsed either way.
    render(LanguageQaPanel, { projectPath: "C:/project", onNavigate: vi.fn() });
    await waitFor(() => expect(statusCall).toHaveBeenCalledWith("C:/project", 0, 100));
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

  it("populates languageQaFindingsByVerse with only terminology.deprecated-form entries, grouped and keyed", async () => {
    languageQaFindingsByVerse.set({});
    statusCall.mockResolvedValue(snapshot({
      findings: [
        { id: "f1", book: "php", chapter: "2", verse: "3-4", rule: "unicode.corruption",
          severity: "high", start: 0, end: 1, originalText: "\ufffd", message: "Check source encoding.",
          textHash: "hash", ruleVersion: "language-qa-1", status: "review-needed" },
        { id: "f2", book: "php", chapter: "1", verse: "9", rule: "terminology.deprecated-form",
          severity: "high", start: 0, end: 3, originalText: "bad", message: "Deprecated.",
          textHash: "hash2", ruleVersion: "language-qa-2", status: "review-needed",
          suggestedReplacement: "good" },
      ],
    }));
    render(LanguageQaPanel, { projectPath: "C:/project", onNavigate: vi.fn() });
    await waitFor(() => expect(get(languageQaFindingsByVerse)["1:9"]).toBeTruthy());
    const byVerse = get(languageQaFindingsByVerse);
    expect(byVerse["1:9"]).toEqual([expect.objectContaining({ id: "f2", suggestedReplacement: "good" })]);
    expect(byVerse["2:3-4"]).toBeUndefined(); // the unicode.corruption finding never enters this store
  });

  it("picks up a finding that appears at a different verse on a later poll, and drops one that no longer does", async () => {
    // Reproduces the maintainer's reported sequence end to end through the
    // panel's own polling path: ignore verse 9's occurrence (it stops being
    // returned), then edit verse 10 to introduce a fresh occurrence of the
    // same deprecated word (it starts being returned on the next completed
    // pass). languageQaFindingsByVerse must track both changes, not just
    // the first poll's snapshot.
    languageQaFindingsByVerse.set({});
    let call = 0;
    statusCall.mockImplementation(async () => {
      call += 1;
      if (call === 1) {
        return snapshot({
          generation: 1,
          findings: [{ id: "f-9", book: "rut", chapter: "1", verse: "9", rule: "terminology.deprecated-form",
            severity: "high", start: 0, end: 3, originalText: "bad", message: "Deprecated.",
            textHash: "h1", ruleVersion: "language-qa-2", status: "review-needed", suggestedReplacement: "good" }],
        });
      }
      return snapshot({
        generation: 2,
        findings: [{ id: "f-10", book: "rut", chapter: "1", verse: "10", rule: "terminology.deprecated-form",
          severity: "high", start: 0, end: 3, originalText: "bad", message: "Deprecated.",
          textHash: "h2", ruleVersion: "language-qa-2", status: "review-needed", suggestedReplacement: "good" }],
      });
    });
    render(LanguageQaPanel, { projectPath: "C:/project", onNavigate: vi.fn() });
    await waitFor(() => expect(get(languageQaFindingsByVerse)["1:9"]).toBeTruthy());
    await fireEvent.click(await screen.findByRole("button", { name: /Language QA · completed/ }));
    await waitFor(() => expect(get(languageQaFindingsByVerse)["1:10"]).toBeTruthy());
    const byVerse = get(languageQaFindingsByVerse);
    expect(byVerse["1:9"]).toBeUndefined();
    expect(byVerse["1:10"]).toEqual([expect.objectContaining({ id: "f-10" })]);
  });

  it("surfaces failure and leaves automatic retry scheduled", async () => {
    statusCall.mockRejectedValue(new Error("Engine unavailable"));
    render(LanguageQaPanel, { projectPath: "C:/project", onNavigate: vi.fn() });
    await fireEvent.click(await screen.findByRole("button", { name: /Language QA · unavailable/ }));
    expect(screen.getByRole("alert").textContent).toContain("Engine unavailable");
  });
});
