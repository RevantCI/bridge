import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { waitFor } from "@testing-library/svelte";
import { get } from "svelte/store";
import type { LanguageQaFinding, LanguageQaInline, LanguageQaStatus } from "../../types/languageQa";
import { currentChapter, languageQaFindingsByVerse } from "../../stores";

const inlineCall = vi.fn();
const statusCall = vi.fn();
vi.mock("../../api/bridgeClient", () => ({ bridge: {
  languageQaInline: (...args: unknown[]) => inlineCall(...args),
  languageQaStatus: (...args: unknown[]) => statusCall(...args),
} }));
import {
  groupInlineFindings, languageQaChannel, nudgeLanguageQa, patchInlineFindings, startLanguageQaInline,
} from "../../languageQaInline";
import { buildSegments } from "../../utils/highlight";
import { lqaFinding } from "./languageQaFixture";

const TEXT = "அந்த காகம் பறந்தது.";

function vallinam(chapter: string, verse: string, overrides: Partial<LanguageQaFinding> = {}): LanguageQaFinding {
  return lqaFinding({ id: `v-${chapter}-${verse}`, chapter, verse, ...overrides });
}

function inline(findings: LanguageQaFinding[], overrides: Partial<LanguageQaInline> = {}): LanguageQaInline {
  return {
    projectPath: "C:/project", book: "php", generation: 1, state: "completed",
    ruleVersion: "language-qa-7", chapter: "1",
    inlineRules: ["tamil.vallinam-missing", "terminology.deprecated-form"], findings, ...overrides,
  };
}

function status(overrides: Partial<LanguageQaStatus> = {}): LanguageQaStatus {
  return {
    projectPath: "C:/project", book: "php", generation: 1, state: "completed", ruleVersion: "language-qa-7",
    findings: [], totalFindings: 0, offset: 0, limitations: [],
    coverage: { inScope: [], outOfScope: [], handOff: "", summary: "" }, storage: "", ...overrides,
  };
}

let stop: (() => void) | null = null;

beforeEach(() => {
  inlineCall.mockReset();
  statusCall.mockReset().mockResolvedValue(status());
  currentChapter.set("1");
  languageQaFindingsByVerse.set({});
});

afterEach(() => {
  stop?.();
  stop = null;
});

describe("languageQaInline marks", () => {
  it("fills the store with a whole chapter, not a page -- marks reach the 150th verse", async () => {
    const findings = Array.from({ length: 150 }, (_, i) => vallinam("1", String(i + 1)));
    inlineCall.mockResolvedValue(inline(findings));
    stop = startLanguageQaInline("C:/project", { activeMs: 5, idleMs: 60_000 });
    await waitFor(() => expect(get(languageQaFindingsByVerse)["1:150"]).toBeTruthy());
    expect(inlineCall).toHaveBeenCalledWith("C:/project", "1");
    expect(Object.keys(get(languageQaFindingsByVerse))).toHaveLength(150);
    const segments = buildSegments(TEXT, [], [], [], get(languageQaFindingsByVerse)["1:150"]);
    expect(segments.find((segment) => segment.className === "m-lqa-sandhi")?.text).toBe("அந்த காகம்");
  });

  it("groups by chapter:verse, keeping verse bridges exact", () => {
    const grouped = groupInlineFindings([vallinam("2", "3-4"), vallinam("2", "3-4", { id: "x" }), vallinam("2", "5")]);
    expect(Object.keys(grouped).sort()).toEqual(["2:3-4", "2:5"]);
    expect(grouped["2:3-4"].map((f) => f.id)).toEqual(["v-2-3-4", "x"]);
  });

  it("follows the chapter on screen, and a late answer for the old chapter is discarded", async () => {
    let releaseOld: (value: LanguageQaInline) => void = () => {};
    inlineCall.mockImplementation((_path: string, chapter: string) => chapter === "1"
      ? new Promise<LanguageQaInline>((resolve) => { releaseOld = resolve; })
      : Promise.resolve(inline([vallinam("2", "7")], { chapter: "2" })));
    stop = startLanguageQaInline("C:/project", { activeMs: 60_000, idleMs: 60_000 });
    await waitFor(() => expect(inlineCall).toHaveBeenCalledWith("C:/project", "1"));
    currentChapter.set("2");
    await waitFor(() => expect(get(languageQaFindingsByVerse)["2:7"]).toBeTruthy());
    releaseOld(inline([vallinam("1", "9")]));
    await Promise.resolve();
    await Promise.resolve();
    expect(get(languageQaFindingsByVerse)["1:9"]).toBeUndefined();
    expect(get(languageQaFindingsByVerse)["2:7"]).toBeTruthy();
  });

  it("redraws when a new pass completes, and keeps the old marks while it runs", async () => {
    let pass: Partial<LanguageQaStatus> = { generation: 1, state: "completed" };
    statusCall.mockImplementation(async () => status(pass));
    inlineCall.mockImplementation(async () => pass.generation === 1
      ? inline([vallinam("1", "9")], { generation: 1 })
      : inline([vallinam("1", "10")], { generation: 2 }));
    stop = startLanguageQaInline("C:/project", { activeMs: 5, idleMs: 5 });
    await waitFor(() => expect(get(languageQaFindingsByVerse)["1:9"]).toBeTruthy());
    const drawn = inlineCall.mock.calls.length;
    pass = { generation: 2, state: "running" };
    await waitFor(() => expect(statusCall.mock.calls.length).toBeGreaterThan(4));
    // Mid-pass the engine holds no findings: nothing is fetched, the marks stay.
    expect(inlineCall.mock.calls.length).toBe(drawn);
    expect(get(languageQaFindingsByVerse)["1:9"]).toBeTruthy();
    pass = { generation: 2, state: "completed" };
    await waitFor(() => expect(get(languageQaFindingsByVerse)["1:10"]).toBeTruthy());
    expect(get(languageQaFindingsByVerse)["1:9"]).toBeUndefined();
  });

  it("ignores an answer that belongs to a different project", async () => {
    statusCall.mockResolvedValue(status({ projectPath: "C:/other" }));
    inlineCall.mockResolvedValue(inline([vallinam("1", "9")]));
    stop = startLanguageQaInline("C:/project", { activeMs: 60_000, idleMs: 60_000 });
    await waitFor(() => expect(statusCall).toHaveBeenCalled());
    await Promise.resolve();
    expect(inlineCall).not.toHaveBeenCalled();
    expect(get(languageQaFindingsByVerse)).toEqual({});
    expect(get(languageQaChannel).status).toBeNull();
  });

  it("keeps the marks when a poll fails and reports it on the channel; stopping clears both", async () => {
    inlineCall.mockResolvedValue(inline([vallinam("1", "9")]));
    stop = startLanguageQaInline("C:/project", { activeMs: 5, idleMs: 5 });
    await waitFor(() => expect(get(languageQaFindingsByVerse)["1:9"]).toBeTruthy());
    statusCall.mockRejectedValue(new Error("engine busy"));
    await waitFor(() => expect(get(languageQaChannel).error).toBe("engine busy"));
    expect(get(languageQaFindingsByVerse)["1:9"]).toBeTruthy();
    const calls = statusCall.mock.calls.length;
    stop();
    stop = null;
    expect(get(languageQaFindingsByVerse)).toEqual({});
    expect(get(languageQaChannel)).toEqual({ projectPath: "", status: null, error: "" });
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(statusCall.mock.calls.length).toBe(calls);
  });

  it("patches per verse: unchanged verses keep their array, and an unchanged answer writes nothing", async () => {
    const one = { "1:1": [vallinam("1", "1")], "1:2": [vallinam("1", "2")] };
    const again = { "1:1": [vallinam("1", "1")], "1:2": [vallinam("1", "2")] };
    expect(patchInlineFindings(one, again)).toBe(one);
    const moved = { "1:1": [vallinam("1", "1")], "1:2": [vallinam("1", "2", { start: 3, end: 13 })] };
    const patched = patchInlineFindings(one, moved);
    expect(patched).not.toBe(one);
    expect(patched["1:1"]).toBe(one["1:1"]);
    expect(patched["1:2"]).toBe(moved["1:2"]);
    expect(Object.keys(patchInlineFindings(one, { "1:1": [vallinam("1", "1")] }))).toEqual(["1:1"]);
  });
});

describe("the Language QA status channel", () => {
  it("publishes a count-only status, and polls fast only while a pass is active", async () => {
    statusCall.mockResolvedValue(status({ state: "running", totalFindings: 3 }));
    inlineCall.mockResolvedValue(inline([], { state: "running" }));
    stop = startLanguageQaInline("C:/project", { activeMs: 5, idleMs: 60_000 });
    await waitFor(() => expect(statusCall.mock.calls.length).toBeGreaterThanOrEqual(4));
    expect(statusCall).toHaveBeenCalledWith("C:/project", 0, 0);
    expect(get(languageQaChannel).status?.totalFindings).toBe(3);
    // Idle: one poll, then the back-off.
    statusCall.mockResolvedValue(status({ state: "completed" }));
    await waitFor(() => expect(get(languageQaChannel).status?.state).toBe("completed"));
    const idle = statusCall.mock.calls.length;
    await new Promise((resolve) => setTimeout(resolve, 60));
    expect(statusCall.mock.calls.length).toBe(idle);
  });

  it("a nudge polls at once instead of waiting out the back-off", async () => {
    inlineCall.mockResolvedValue(inline([]));
    stop = startLanguageQaInline("C:/project", { activeMs: 60_000, idleMs: 60_000 });
    await waitFor(() => expect(statusCall).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(get(languageQaChannel).status).not.toBeNull());
    nudgeLanguageQa();
    await waitFor(() => expect(statusCall).toHaveBeenCalledTimes(2));
  });

  it("an unchanged completed pass does not refetch the marks", async () => {
    inlineCall.mockResolvedValue(inline([vallinam("1", "9")]));
    const writes: number[] = [];
    const unsubscribe = languageQaFindingsByVerse.subscribe(() => writes.push(1));
    stop = startLanguageQaInline("C:/project", { activeMs: 5, idleMs: 5 });
    await waitFor(() => expect(get(languageQaFindingsByVerse)["1:9"]).toBeTruthy());
    const afterFirst = writes.length;
    await waitFor(() => expect(statusCall.mock.calls.length).toBeGreaterThanOrEqual(5));
    expect(inlineCall).toHaveBeenCalledTimes(1);
    expect(writes.length).toBe(afterFirst);
    unsubscribe();
  });
});
