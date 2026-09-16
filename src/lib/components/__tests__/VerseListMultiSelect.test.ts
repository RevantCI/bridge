import { describe, expect, it, beforeEach, vi } from "vitest";
import { fireEvent, render } from "@testing-library/svelte";
import { get } from "svelte/store";
import { tick } from "svelte";

const { decideVerse, editVerse, runVerseChecks } = vi.hoisted(() => ({
  decideVerse: vi.fn(),
  editVerse: vi.fn(),
  runVerseChecks: vi.fn(),
}));

vi.mock("../../api/bridgeClient", () => ({
  bridge: { decideVerse, editVerse, runVerseChecks },
}));

import VerseList from "../VerseList.svelte";
import {
  aiCheckReviewsByVerse, alignmentStatusByVerse, chapterVerseNums, checkStatusByVerse, checkingProgress,
  currentChapter, findingsByVerse, nativeChecksByVerse, selectedVerse, selectedVerseSet, verseKey, verseTexts,
} from "../../stores";

// #118: Ctrl/Shift-click build the multi-selection that feeds the Cross-verse
// alignment range picker. Verse "numbers" are opaque strings ("3-4"), ordered
// by the chapter's verse list, never by number.
const VERSES = ["1", "2", "3-4", "5"];

function seed(): void {
  currentChapter.set("1");
  chapterVerseNums.set({ "1": VERSES });
  verseTexts.set(Object.fromEntries(VERSES.map((v) => [verseKey("1", v), `text ${v}`])));
  findingsByVerse.set({});
  checkStatusByVerse.set({});
  alignmentStatusByVerse.set({});
  nativeChecksByVerse.set({});
  aiCheckReviewsByVerse.set({});
  selectedVerse.set("2");
  selectedVerseSet.set([]);
  checkingProgress.set({ running: false, percent: 0, label: "", jobId: "", state: "idle", error: "", scope: "chapter" });
}

function row(verse: string): HTMLElement {
  return document.querySelector(`[data-verse-key="1:${verse}"]`) as HTMLElement;
}

describe("VerseList multi-select (#118)", () => {
  beforeEach(seed);

  it("a plain click selects one verse and clears the set", async () => {
    const onSelect = vi.fn((v: string) => selectedVerse.set(v));
    render(VerseList, { props: { onSelect } });
    selectedVerseSet.set(["1", "2"]);
    await fireEvent.click(row("3-4"));
    expect(onSelect).toHaveBeenCalledWith("3-4");
    expect(get(selectedVerseSet)).toEqual([]);
  });

  it("Ctrl-click adds to the set starting from the active verse, keeps chapter order, and toggles off", async () => {
    const onSelect = vi.fn((v: string) => selectedVerse.set(v));
    render(VerseList, { props: { onSelect } });
    await fireEvent.click(row("5"), { ctrlKey: true });
    expect(get(selectedVerseSet)).toEqual(["2", "5"]);
    expect(onSelect).toHaveBeenLastCalledWith("5");
    await fireEvent.click(row("1"), { ctrlKey: true });
    expect(get(selectedVerseSet)).toEqual(["1", "2", "5"]);
    expect(row("1").classList.contains("multi")).toBe(true);
    expect(row("3-4").classList.contains("multi")).toBe(false);
    // Toggling a member off does not move the active verse.
    onSelect.mockClear();
    await fireEvent.click(row("2"), { ctrlKey: true });
    expect(get(selectedVerseSet)).toEqual(["1", "5"]);
    expect(onSelect).not.toHaveBeenCalled();
    // Down to one member the set is empty again: one verse is not a range.
    await fireEvent.click(row("1"), { ctrlKey: true });
    expect(get(selectedVerseSet)).toEqual([]);
  });

  it("Shift-click selects the run from the active verse by chapter order, bridges included", async () => {
    const onSelect = vi.fn((v: string) => selectedVerse.set(v));
    render(VerseList, { props: { onSelect } });
    await fireEvent.click(row("5"), { shiftKey: true });
    expect(get(selectedVerseSet)).toEqual(["2", "3-4", "5"]);
    expect(onSelect).toHaveBeenLastCalledWith("5");
    // Backwards works the same way.
    await fireEvent.click(row("1"), { shiftKey: true });
    expect(get(selectedVerseSet)).toEqual(["1", "2", "3-4", "5"]);
  });

  it("a chapter switch starts the set over", async () => {
    render(VerseList, { props: { onSelect: vi.fn() } });
    await fireEvent.click(row("5"), { shiftKey: true });
    expect(get(selectedVerseSet)).toHaveLength(3);
    currentChapter.set("2");
    await tick();
    expect(get(selectedVerseSet)).toEqual([]);
  });
});
