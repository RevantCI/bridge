import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { waitFor } from "@testing-library/svelte";
import { get } from "svelte/store";
import type { LanguageQaFinding, LanguageQaInline } from "../../types/languageQa";
import { currentChapter, languageQaFindingsByVerse } from "../../stores";

const inlineCall = vi.fn();
vi.mock("../../api/bridgeClient", () => ({ bridge: {
  languageQaInline: (...args: unknown[]) => inlineCall(...args),
} }));
import { groupInlineFindings, patchInlineFindings, startLanguageQaInline } from "../../languageQaInline";
import { buildSegments } from "../../utils/highlight";
import { lqaFinding } from "./languageQaFixture";

const TEXT = "அந்த காகம் பறந்தது.";

function vallinam(chapter: string, verse: string, overrides: Partial<LanguageQaFinding> = {}): LanguageQaFinding {
  return lqaFinding({ id: `v-${chapter}-${verse}`, chapter, verse, ...overrides });
}

function response(findings: LanguageQaFinding[], overrides: Partial<LanguageQaInline> = {}): LanguageQaInline {
  return {
    projectPath: "C:/project", book: "php", generation: 1, state: "completed",
    ruleVersion: "language-qa-6", chapter: "1",
    inlineRules: ["tamil.vallinam-missing", "terminology.deprecated-form"], findings, ...overrides,
  };
}

let stop: (() => void) | null = null;

beforeEach(() => {
  inlineCall.mockReset();
  currentChapter.set("1");
  languageQaFindingsByVerse.set({});
});

afterEach(() => {
  stop?.();
  stop = null;
});

describe("languageQaInline", () => {
  it("fills the store with a whole chapter, not a page -- marks reach the 150th verse", async () => {
    const findings = Array.from({ length: 150 }, (_, i) => vallinam("1", String(i + 1)));
    inlineCall.mockResolvedValue(response(findings));
    stop = startLanguageQaInline("C:/project", { intervalMs: 60_000 });
    await waitFor(() => expect(get(languageQaFindingsByVerse)["1:150"]).toBeTruthy());
    expect(inlineCall).toHaveBeenCalledWith("C:/project", "1");
    expect(Object.keys(get(languageQaFindingsByVerse))).toHaveLength(150);
    const segments = buildSegments(TEXT, [], [], [], get(languageQaFindingsByVerse)["1:150"]);
    expect(segments.find((segment) => segment.className === "m-lqa-sandhi")?.text).toBe("அந்த காகம்");
  });

  it("patches per verse: unchanged verses keep their array, and an unchanged poll writes nothing", async () => {
    const one = { "1:1": [vallinam("1", "1")], "1:2": [vallinam("1", "2")] };
    const again = { "1:1": [vallinam("1", "1")], "1:2": [vallinam("1", "2")] };
    expect(patchInlineFindings(one, again)).toBe(one);
    const moved = { "1:1": [vallinam("1", "1")], "1:2": [vallinam("1", "2", { start: 3, end: 13 })] };
    const patched = patchInlineFindings(one, moved);
    expect(patched).not.toBe(one);
    expect(patched["1:1"]).toBe(one["1:1"]);
    expect(patched["1:2"]).toBe(moved["1:2"]);
    expect(Object.keys(patchInlineFindings(one, { "1:1": [vallinam("1", "1")] }))).toEqual(["1:1"]);

    // Through the poller: a second identical answer does not notify subscribers.
    inlineCall.mockResolvedValue(response([vallinam("1", "9")]));
    const writes: number[] = [];
    const unsubscribe = languageQaFindingsByVerse.subscribe(() => writes.push(1));
    stop = startLanguageQaInline("C:/project", { intervalMs: 5 });
    await waitFor(() => expect(get(languageQaFindingsByVerse)["1:9"]).toBeTruthy());
    const afterFirst = writes.length;
    await waitFor(() => expect(inlineCall.mock.calls.length).toBeGreaterThanOrEqual(4));
    expect(writes.length).toBe(afterFirst);
    unsubscribe();
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
      : Promise.resolve(response([vallinam("2", "7")], { chapter: "2" })));
    stop = startLanguageQaInline("C:/project", { intervalMs: 60_000 });
    await waitFor(() => expect(inlineCall).toHaveBeenCalledWith("C:/project", "1"));
    currentChapter.set("2");
    await waitFor(() => expect(get(languageQaFindingsByVerse)["2:7"]).toBeTruthy());
    releaseOld(response([vallinam("1", "9")]));
    await Promise.resolve();
    await Promise.resolve();
    expect(get(languageQaFindingsByVerse)["1:9"]).toBeUndefined();
    expect(get(languageQaFindingsByVerse)["2:7"]).toBeTruthy();
  });

  it("tracks later passes: a finding that moves verse is picked up and the old one dropped", async () => {
    let secondPass = false;
    inlineCall.mockImplementation(async () => secondPass
      ? response([vallinam("1", "10")], { generation: 2 })
      : response([vallinam("1", "9")], { generation: 1 }));
    stop = startLanguageQaInline("C:/project", { intervalMs: 5 });
    await waitFor(() => expect(get(languageQaFindingsByVerse)["1:9"]).toBeTruthy());
    secondPass = true;
    await waitFor(() => expect(get(languageQaFindingsByVerse)["1:10"]).toBeTruthy());
    expect(get(languageQaFindingsByVerse)["1:9"]).toBeUndefined();
  });

  it("ignores an answer that belongs to a different project", async () => {
    inlineCall.mockResolvedValue(response([vallinam("1", "9")], { projectPath: "C:/other" }));
    stop = startLanguageQaInline("C:/project", { intervalMs: 60_000 });
    await waitFor(() => expect(inlineCall).toHaveBeenCalled());
    await Promise.resolve();
    expect(get(languageQaFindingsByVerse)).toEqual({});
  });

  it("keeps the marks it has when a poll fails, and stopping clears them", async () => {
    let call = 0;
    let failing = false;
    inlineCall.mockImplementation(async () => {
      call += 1;
      if (!failing) return response([vallinam("1", "9")]);
      throw new Error("engine busy");
    });
    stop = startLanguageQaInline("C:/project", { intervalMs: 5 });
    await waitFor(() => expect(get(languageQaFindingsByVerse)["1:9"]).toBeTruthy());
    failing = true;
    const before = call;
    await waitFor(() => expect(call).toBeGreaterThanOrEqual(before + 2));
    expect(get(languageQaFindingsByVerse)["1:9"]).toBeTruthy();
    stop();
    stop = null;
    expect(get(languageQaFindingsByVerse)).toEqual({});
    const calls = call;
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(call).toBe(calls);
  });
});
