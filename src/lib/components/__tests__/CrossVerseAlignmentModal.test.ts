import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/svelte";
import { get } from "svelte/store";
import CrossVerseAlignmentModal from "../CrossVerseAlignmentModal.svelte";
import {
  alignmentStatusByVerse, chapterVerseNums, checkStatusByVerse, currentChapter, findingsByVerse,
} from "../../stores";
import type { AlignmentContext, AlignmentRange, AlignmentToken } from "../../types/finding";

const { getAlignmentRange, realignWords, unalignWords, runVerseChecks, getLexiconEntry } = vi.hoisted(() => ({
  getAlignmentRange: vi.fn(),
  realignWords: vi.fn(),
  unalignWords: vi.fn(),
  runVerseChecks: vi.fn(),
  getLexiconEntry: vi.fn(),
}));

vi.mock("../../api/bridgeClient", () => ({
  bridge: { getAlignmentRange, realignWords, unalignWords, runVerseChecks, getLexiconEntry },
}));

function token(id: string, word: string, extra: Partial<AlignmentToken> = {}): AlignmentToken {
  return { id, word, occurrence: 1, occurrences: 1, ...extra };
}

/** A verse with source tokens H001.. and target words T001.., where the
 *  first `aligned` pairs are grouped 1:1 and the rest sit in the word bank. */
function context(verse: string, sources: string[], targets: string[], aligned: number): AlignmentContext {
  const topTokens = sources.map((w, i) => token(`H${String(i + 1).padStart(3, "0")}`, w, { strong: "G2316", lemma: `${w}·lemma` }));
  const bottomTokens = targets.map((w, i) => token(`T${String(i + 1).padStart(3, "0")}`, w));
  const groups = topTokens.map((top, i) => ({
    id: `G${String(i + 1).padStart(3, "0")}`,
    topIds: [top.id],
    bottomIds: i < aligned && bottomTokens[i] ? [bottomTokens[i].id] : [],
  }));
  return {
    chapter: "1", verse,
    alignment: {
      alignments: groups.map((g) => ({
        topWords: g.topIds.map((id) => topTokens.find((t) => t.id === id)!),
        bottomWords: g.bottomIds.map((id) => bottomTokens.find((t) => t.id === id)!),
      })),
      wordBank: bottomTokens.slice(aligned),
    },
    topTokens, bottomTokens, groups,
    status: aligned === sources.length && aligned === targets.length ? "complete" : aligned ? "partial" : "untouched",
    completionState: "pending",
    sourceAvailable: true, sourceMessage: "",
    sourceDirection: "ltr", targetDirection: "ltr",
    issues: [], canComplete: false, history: [],
    chapterStatus: { complete: 1, partial: 1, untouched: 2, invalid: 0 },
    gaps: {
      sourceUnmatched: groups.filter((g) => g.bottomIds.length === 0).length,
      targetUnmatched: targets.length - aligned,
    },
  };
}

const V1 = context("1", ["θεός"], ["God"], 1);
const V2 = context("2", ["λόγος", "ἦν"], ["word", "was"], 1);
const V34 = context("3-4", ["φῶς"], ["light", "shone"], 0);

function rangeFor(verses: string[]): AlignmentRange {
  const all: Record<string, AlignmentContext> = { "1": V1, "2": V2, "3-4": V34 };
  return { chapter: "1", verses: verses.map((v) => all[v]), chapterStatus: V1.chapterStatus };
}

function seed() {
  chapterVerseNums.set({ "1": ["1", "2", "3-4", "5"] });
  currentChapter.set("1");
  alignmentStatusByVerse.set({});
  checkStatusByVerse.set({});
  findingsByVerse.set({});
}

beforeEach(() => {
  seed();
  getAlignmentRange.mockImplementation(async (_chapter: string, verses: string[]) => rangeFor(verses));
  getLexiconEntry.mockResolvedValue({ languageId: "el-x-koine", segments: [{ meaning: "God", lemma: "θεός" }] });
  runVerseChecks.mockResolvedValue([{ id: "f1" }]);
});

async function renderPage(verse = "2") {
  const onClose = vi.fn();
  const utils = render(CrossVerseAlignmentModal, { props: { chapter: "1", verse, onClose } });
  await waitFor(() => expect(getAlignmentRange).toHaveBeenCalled());
  await waitFor(() => expect(screen.getAllByText("1:2").length).toBeGreaterThan(0));
  return { ...utils, onClose };
}

describe("CrossVerseAlignmentModal", () => {
  it("opens on the selected verse ±1 and shows every verse in both columns plus the gap overview", async () => {
    await renderPage("2");
    expect(getAlignmentRange).toHaveBeenCalledWith("1", ["1", "2", "3-4"]);
    // Two columns, so each verse header appears twice; the bridge verse keeps its string.
    expect(screen.getAllByText("1:1")).toHaveLength(2);
    expect(screen.getAllByText("1:3-4")).toHaveLength(2);
    const strip = screen.getByLabelText("Gap overview");
    // v.2 and v.3-4 each have one unmatched source word; only v.3-4 has two unaligned targets.
    expect(within(strip).getAllByText("1 source word with no counterpart")).toHaveLength(2);
    expect(within(strip).getByText("2 target words with no counterpart")).toBeInTheDocument();
    expect(within(strip).getByText("0 source words with no counterpart")).toBeInTheDocument();
    expect(within(strip).getByText(/Range: 2 source · 3 target unmatched/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /verses 1–3-4/ })).toBeInTheDocument();
  });

  it("a same-verse drop realigns through alignment.realign, resending the column's existing words, then reruns local checks", async () => {
    realignWords.mockResolvedValue({ ...V2, status: "complete", gaps: { sourceUnmatched: 0, targetUnmatched: 0 } });
    await renderPage("2");
    // Click-to-pick-up is the same one-step drop the pointer drag delivers.
    const bank2 = screen.getByLabelText("Word bank of verse 2");
    await fireEvent.click(within(bank2).getByRole("button", { name: "was" }));
    await fireEvent.click(screen.getByLabelText(/Align picked-up word to λόγος in verse 2/));
    await waitFor(() => expect(realignWords).toHaveBeenCalledTimes(1));
    expect(realignWords).toHaveBeenCalledWith("1", "2", ["H001"], ["T001", "T002"], V2.alignment);
    await waitFor(() => expect(runVerseChecks).toHaveBeenCalledWith("1", "2", ["alignment", "greekroom"]));
    expect(get(alignmentStatusByVerse)["1:2"]).toBe("complete");
    expect(get(checkStatusByVerse)["1:2"]).toBe("succeeded");
    expect(get(findingsByVerse)["1:2"]).toEqual([{ id: "f1" }]);
    expect(unalignWords).not.toHaveBeenCalled();
  });

  it("a cross-verse drop calls nothing and says the link is saved in the next slice", async () => {
    await renderPage("2");
    const bank2 = screen.getByLabelText("Word bank of verse 2");
    await fireEvent.click(within(bank2).getByRole("button", { name: "was" }));
    await fireEvent.click(screen.getByLabelText(/Align picked-up word to φῶς in verse 3-4/));
    expect(await screen.findByText(/saved in the next slice/)).toBeInTheDocument();
    expect(realignWords).not.toHaveBeenCalled();
    expect(unalignWords).not.toHaveBeenCalled();
    expect(runVerseChecks).not.toHaveBeenCalled();
  });

  it("dropping a word on another verse's word bank is also refused", async () => {
    await renderPage("2");
    const bank2 = screen.getByLabelText("Word bank of verse 2");
    await fireEvent.click(within(bank2).getByRole("button", { name: "was" }));
    await fireEvent.click(screen.getByLabelText(/word bank of verse 1$/i));
    expect(await screen.findByText(/saved in the next slice/)).toBeInTheDocument();
    expect(unalignWords).not.toHaveBeenCalled();
  });

  it("the × on an aligned card unaligns within its own verse", async () => {
    unalignWords.mockResolvedValue(V1);
    await renderPage("2");
    await fireEvent.click(screen.getByRole("button", { name: "Unalign God from θεός" }));
    await waitFor(() => expect(unalignWords).toHaveBeenCalledWith("1", "1", ["T001"], V1.alignment));
    await waitFor(() => expect(runVerseChecks).toHaveBeenCalledWith("1", "1", ["alignment", "greekroom"]));
  });

  it("clicking a verse in the gap overview filters both columns to that verse's gaps", async () => {
    await renderPage("2");
    const strip = screen.getByLabelText("Gap overview");
    await fireEvent.click(within(strip).getByRole("button", { name: /v\.2/ }));
    // Only verse 2 remains, only its unmatched source (ἦν) and unaligned target (was).
    expect(screen.queryAllByText("1:1")).toHaveLength(0);
    expect(screen.queryByText("λόγος")).not.toBeInTheDocument();
    expect(screen.getByText("ἦν")).toBeInTheDocument();
    expect(screen.queryByText("word")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "was" })).toBeInTheDocument();
    await fireEvent.click(screen.getByRole("button", { name: "Show all" }));
    expect(screen.getAllByText("1:1")).toHaveLength(2);
  });

  it("changing the range refetches with the new verse strings and toggling a chip drops a verse", async () => {
    await renderPage("2");
    const [fromSelect] = screen.getAllByRole("combobox");
    await fireEvent.change(fromSelect, { target: { value: "2" } });
    await waitFor(() => expect(getAlignmentRange).toHaveBeenLastCalledWith("1", ["2", "3-4"]));
    const chips = screen.getByRole("group", { name: "Verses in range" });
    await fireEvent.click(within(chips).getByRole("button", { name: "3-4" }));
    await waitFor(() => expect(getAlignmentRange).toHaveBeenLastCalledWith("1", ["2"]));
  });

  it("closes itself when the chapter changes underneath it", async () => {
    const { onClose } = await renderPage("2");
    currentChapter.set("2");
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });
});
