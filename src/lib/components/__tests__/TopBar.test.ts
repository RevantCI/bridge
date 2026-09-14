import { describe, expect, it, beforeEach, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/svelte";

const { engineInfo } = vi.hoisted(() => ({ engineInfo: vi.fn() }));

vi.mock("../../api/bridgeClient", () => ({
  bridge: { engineInfo },
}));

import TopBar from "../TopBar.svelte";
import { project, currentChapter } from "../../stores";
import type { ProjectInfo } from "../../types/finding";

function openBook(chapters: string[]): void {
  project.set({
    path: "C:/projects/php",
    bookId: "php",
    bookName: "Philippians",
    targetLanguage: "Tamil",
    tcVersion: "9",
    chapters,
    checkTypes: {},
  } as ProjectInfo);
}

function mount(overrides: Record<string, unknown> = {}) {
  return render(TopBar, {
    props: {
      screen: "editor",
      projectName: "Philippians",
      onGoHome: vi.fn(),
      onGoToDashboard: vi.fn(),
      onOpenSettings: vi.fn(),
      onOpenConnections: vi.fn(),
      onOpenExport: vi.fn(),
      onGotoVerse: vi.fn(),
      onChapterChange: vi.fn(),
      onBookChange: vi.fn(),
      exportEnabled: true,
      ...overrides,
    },
  });
}

const prev = () => screen.getByLabelText("Previous chapter") as HTMLButtonElement;
const next = () => screen.getByLabelText("Next chapter") as HTMLButtonElement;

describe("TopBar chapter navigation (issue #53)", () => {
  beforeEach(() => {
    engineInfo.mockResolvedValue({ bridgeVersion: "0.9.7", companionSchemaVersion: 15 });
    openBook(["1", "2", "3", "4"]);
    currentChapter.set("2");
  });

  it("steps to the previous and next chapter through the same handler as the dropdown", async () => {
    const onChapterChange = vi.fn();
    mount({ onChapterChange });

    await fireEvent.click(next());
    expect(onChapterChange).toHaveBeenCalledWith("3");

    await fireEvent.click(prev());
    expect(onChapterChange).toHaveBeenCalledWith("1");
    expect(onChapterChange).toHaveBeenCalledTimes(2);
  });

  it("disables Previous on the first chapter", async () => {
    currentChapter.set("1");
    const onChapterChange = vi.fn();
    mount({ onChapterChange });

    expect(prev()).toBeDisabled();
    expect(next()).not.toBeDisabled();
    await fireEvent.click(prev());
    expect(onChapterChange).not.toHaveBeenCalled();
  });

  it("disables Next on the last chapter", async () => {
    currentChapter.set("4");
    const onChapterChange = vi.fn();
    mount({ onChapterChange });

    expect(next()).toBeDisabled();
    expect(prev()).not.toBeDisabled();
    await fireEvent.click(next());
    expect(onChapterChange).not.toHaveBeenCalled();
  });

  it("disables both ends for a single-chapter book", () => {
    openBook(["1"]);
    currentChapter.set("1");
    mount();

    expect(prev()).toBeDisabled();
    expect(next()).toBeDisabled();
  });

  it("steps by position in the book's chapter list, not by number", async () => {
    // Chapter ids are strings from the engine and are not guaranteed to be a
    // clean 1..n run; stepping must agree with the dropdown the reader sees.
    openBook(["1", "2", "2b", "3"]);
    currentChapter.set("2");
    const onChapterChange = vi.fn();
    mount({ onChapterChange });

    await fireEvent.click(next());
    expect(onChapterChange).toHaveBeenCalledWith("2b");
  });

  it("disables both controls when the current chapter is not in the book", () => {
    // Mid-book-switch: the chapter list has already changed under a chapter
    // number that no longer exists. Stepping from nowhere would be a guess.
    currentChapter.set("99");
    mount();

    expect(prev()).toBeDisabled();
    expect(next()).toBeDisabled();
  });

  it("is labelled as a group and reachable by keyboard", () => {
    mount();
    expect(screen.getByRole("group", { name: "Chapter navigation" })).toBeTruthy();
    // Real <button>s, so they are tab-stops and Enter/Space activate them.
    expect(prev().tagName).toBe("BUTTON");
    expect(next().tagName).toBe("BUTTON");
    expect(prev()).toHaveAttribute("title");
    expect(next()).toHaveAttribute("title");
  });

  it("is absent outside the editor screen", () => {
    mount({ screen: "dashboard" });
    expect(screen.queryByLabelText("Previous chapter")).toBeNull();
    expect(screen.queryByLabelText("Next chapter")).toBeNull();
  });
});
