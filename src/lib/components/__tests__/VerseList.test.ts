import { describe, expect, it, beforeEach, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/svelte";
import { get } from "svelte/store";

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
  chapterVerseNums,
  currentChapter,
  verseTexts,
  findingsByVerse,
  checkStatusByVerse,
  checkingProgress,
  alignmentStatusByVerse,
  nativeChecksByVerse,
  aiCheckReviewsByVerse,
  selectedVerse,
  verseKey,
} from "../../stores";
import { alignmentOpen, alignmentKey } from "../../alignmentUi";
import { editingChapter, editingVerse, editSaving, recheckingKey } from "../../verseEditor";
import { aiReviewRequest, aiJobActive } from "../../aiReviewUi";
import type { QaFinding } from "../../types/finding";

/** The store holds full QaFindings; fixtures.ts only builds summaries/details. */
function finding(overrides: Partial<QaFinding> = {}): QaFinding {
  return {
    id: "f1",
    project_id: "p1",
    book: "php",
    chapter: 1,
    verse: 6,
    start_offset: null,
    end_offset: null,
    original_text: "",
    engine: "greek_room",
    check_type: "spelling",
    category: "spelling",
    severity: "low",
    confidence: 0.5,
    suggested_replacement: null,
    explanation: "Possible spelling issue",
    evidence: [],
    engine_version: "1",
    resource_versions: {},
    status: "open",
    human_comment: null,
    created_at: "2026-09-06T00:00:00Z",
    resolved_at: null,
    ...overrides,
  };
}

const PHP_1_6 =
  "\\it मुझे इस बात का भरोसा है\\it*\\f + \\fr 1.6 \\fq मुझे इस बात का भरोसा है: " +
  "\\ft इसका मतलब यह है पौलुस ने जो कुछ कहा उसका सच पूरी तरह से आश्वस्त था।\\f* " +
  "कि जिसने तुम में अच्छा काम आरम्भ किया है।";

function seed(text: string, findings: QaFinding[] = []): void {
  currentChapter.set("1");
  chapterVerseNums.set({ "1": ["6"] });
  verseTexts.set({ [verseKey("1", "6")]: text });
  findingsByVerse.set({ [verseKey("1", "6")]: findings });
  checkStatusByVerse.set({});
  alignmentStatusByVerse.set({});
  nativeChecksByVerse.set({});
  aiCheckReviewsByVerse.set({});
  selectedVerse.set(null);
  checkingProgress.set({
    running: false, percent: 0, label: "", jobId: "", state: "idle", error: "", scope: "chapter",
  });
  alignmentOpen.set(false);
  alignmentKey.set("");
  editingChapter.set("");
  editingVerse.set("");
  editSaving.set(false);
  recheckingKey.set("");
  aiReviewRequest.set(null);
  aiJobActive.set(false);
  vi.clearAllMocks();
  decideVerse.mockResolvedValue(undefined);
  editVerse.mockResolvedValue({ issueResolutionsNeedingRecheck: 0 });
  runVerseChecks.mockResolvedValue([]);
}

/** The one verse row seed() renders, addressed the way the component keys it. */
function verseRow(): HTMLElement {
  return document.querySelector('[data-verse-key="1:6"]') as HTMLElement;
}

const FOOTNOTE_MARKER = /Show footnote at this point in verse 1:6/;
const XREF_MARKER = /Show cross reference at this point in verse 1:6/;

describe("VerseList footnote handling", () => {
  beforeEach(() => seed(PHP_1_6));

  it("keeps footnote markup out of the verse area", () => {
    render(VerseList, { props: { onSelect: vi.fn() } });
    expect(document.body.textContent).not.toContain("\\f");
    expect(document.body.textContent).not.toContain("\\fr");
  });

  it("leaves styling markers in the text", () => {
    render(VerseList, { props: { onSelect: vi.fn() } });
    expect(document.body.textContent).toContain("\\it");
  });

  it("does not show the footnote text inline with the verse", () => {
    render(VerseList, { props: { onSelect: vi.fn() } });
    expect(screen.queryByText(/इसका मतलब यह है/)).toBeNull();
  });

  it("still shows the Scripture itself", () => {
    render(VerseList, { props: { onSelect: vi.fn() } });
    expect(document.body.textContent).toContain("कि जिसने तुम में अच्छा काम आरम्भ किया है।");
  });

  it("offers an f marker for a verse that has a footnote", () => {
    render(VerseList, { props: { onSelect: vi.fn() } });
    expect(screen.getByLabelText(FOOTNOTE_MARKER)).toHaveTextContent("f");
  });

  it("places the marker where the footnote was, not at the end of the verse", () => {
    render(VerseList, { props: { onSelect: vi.fn() } });
    const vtext = document.querySelector(".vtext") as HTMLElement;
    const nodes = Array.from(vtext.childNodes);
    const markerIndex = nodes.findIndex(
      (node) => node instanceof HTMLElement && node.classList.contains("note-btn"),
    );
    expect(markerIndex).toBeGreaterThan(-1);
    // Scripture still follows the marker, so it is not trailing the verse.
    const after = nodes.slice(markerIndex + 1).map((n) => n.textContent ?? "").join("");
    expect(after).toContain("कि जिसने");
  });

  it("shows no marker for a verse with no notes", () => {
    seed("मसीह यीशु के दास पौलुस");
    render(VerseList, { props: { onSelect: vi.fn() } });
    expect(screen.queryByLabelText(/Show footnote/)).toBeNull();
    expect(screen.queryByLabelText(/Show cross reference/)).toBeNull();
  });

  it("opens a titled popup carrying the footnote text", async () => {
    render(VerseList, { props: { onSelect: vi.fn() } });
    await fireEvent.click(screen.getByLabelText(FOOTNOTE_MARKER));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("Footnotes")).toBeInTheDocument();
    expect(screen.getByText(/इसका मतलब यह है/)).toBeInTheDocument();
  });

  it("closes the popup again", async () => {
    render(VerseList, { props: { onSelect: vi.fn() } });
    await fireEvent.click(screen.getByLabelText(FOOTNOTE_MARKER));
    await fireEvent.click(screen.getByLabelText("Close footnotes"));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("does not select the verse when the marker is clicked", async () => {
    const onSelect = vi.fn();
    render(VerseList, { props: { onSelect } });
    await fireEvent.click(screen.getByLabelText(FOOTNOTE_MARKER));
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("uses the cross reference title for an x marker", async () => {
    seed("पवित्र लोगों\\x + \\xo 1.1 \\xt रोम. 1:7\\x* के नाम");
    render(VerseList, { props: { onSelect: vi.fn() } });
    await fireEvent.click(screen.getByLabelText(XREF_MARKER));
    expect(screen.getByText("Cross reference")).toBeInTheDocument();
    expect(screen.getByText("रोम. 1:7")).toBeInTheDocument();
  });

  it("renders one marker per note on a verse with several", () => {
    seed("a\\f + \\ft one\\f* b\\f + \\ft two\\f*");
    render(VerseList, { props: { onSelect: vi.fn() } });
    expect(screen.getAllByLabelText(/Show footnote at this point/)).toHaveLength(2);
  });

  it("opens only the note whose marker was clicked", async () => {
    seed("a\\f + \\ft first note\\f* b\\f + \\ft second note\\f*");
    render(VerseList, { props: { onSelect: vi.fn() } });
    await fireEvent.click(screen.getAllByLabelText(/Show footnote at this point/)[1]);
    expect(screen.getByText("second note")).toBeInTheDocument();
    expect(screen.queryByText("first note")).toBeNull();
  });

  it("keeps a finding underline on its word after the note is lifted out", () => {
    // "आरम्भ" sits after the footnote, so its raw offset is far beyond where
    // the word lands once the note is removed. Without offset remapping the
    // mark would be dropped entirely.
    const word = "आरम्भ";
    const start = PHP_1_6.indexOf(word);
    seed(PHP_1_6, [finding({ start_offset: start, end_offset: start + word.length })]);
    render(VerseList, { props: { onSelect: vi.fn() } });
    const marks = Array.from(document.querySelectorAll("mark")).map((m) => m.textContent);
    expect(marks).toContain(word);
  });

  it("offers exactly the two actions the review panel offers", async () => {
    seed("alpha beta", [finding({
      start_offset: 0, end_offset: 5, original_text: "alpha", suggested_replacement: null,
    })]);
    render(VerseList, { props: { onSelect: vi.fn() } });
    await fireEvent.contextMenu(document.querySelector("mark") as HTMLElement, {
      clientX: 25, clientY: 35,
    });
    expect(screen.getByRole("menu", { name: /Actions for Possible spelling issue/i }))
      .toBeInTheDocument();
    expect(screen.getAllByRole("menuitem").map((item) => item.textContent))
      .toEqual(["Accept finding", "Ignore"]);
    // Both stay usable whether or not the check proposed a correction — the
    // menu never changes height between findings.
    for (const item of screen.getAllByRole("menuitem")) expect(item).toBeEnabled();
  });

  it("accepts without touching the verse when the check proposed no correction", async () => {
    seed("alpha beta", [finding({
      start_offset: 0, end_offset: 5, original_text: "alpha", suggested_replacement: null,
    })]);
    render(VerseList, { props: { onSelect: vi.fn() } });
    await fireEvent.contextMenu(document.querySelector("mark") as HTMLElement);
    expect(screen.getByRole("menuitem", { name: "Accept finding" }))
      .toHaveAttribute("title", expect.stringContaining("left alone"));
    await fireEvent.click(screen.getByRole("menuitem", { name: "Accept finding" }));
    expect(decideVerse).toHaveBeenCalledWith("1", "6", "f1", "accepted");
    expect(editVerse).not.toHaveBeenCalled();
  });

  it("applies the proposed correction as part of accepting", async () => {
    seed("alpha beta", [finding({
      start_offset: 0, end_offset: 5, original_text: "alpha", suggested_replacement: "omega",
    })]);
    render(VerseList, { props: { onSelect: vi.fn() } });
    await fireEvent.contextMenu(document.querySelector("mark") as HTMLElement);
    expect(screen.getByRole("menuitem", { name: "Accept finding" }))
      .toHaveAttribute("title", expect.stringContaining("proposed correction"));
    await fireEvent.click(screen.getByRole("menuitem", { name: "Accept finding" }));
    expect(editVerse).toHaveBeenCalledWith("1", "6", "omega beta");
    expect(runVerseChecks).toHaveBeenCalledWith("1", "6", ["local", "greekroom"]);
  });

  it("does not accept a correction that could not be applied", async () => {
    // original_text no longer matches the verse, so the fix is stale.
    seed("alpha beta", [finding({
      start_offset: 0, end_offset: 5, original_text: "moved", suggested_replacement: "omega",
    })]);
    render(VerseList, { props: { onSelect: vi.fn() } });
    await fireEvent.contextMenu(document.querySelector("mark") as HTMLElement);
    await fireEvent.click(screen.getByRole("menuitem", { name: "Accept finding" }));
    expect(editVerse).not.toHaveBeenCalled();
    expect(decideVerse).not.toHaveBeenCalled();
    // Menu stays open with the reason, rather than silently filing a decision.
    expect(screen.getByRole("menu")).toBeInTheDocument();
    expect(screen.getByRole("status").textContent).toMatch(/stale/i);
  });

  it("ignores a finding and drops its underline", async () => {
    seed("alpha beta", [finding({ start_offset: 0, end_offset: 5, original_text: "alpha" })]);
    render(VerseList, { props: { onSelect: vi.fn() } });
    await fireEvent.contextMenu(document.querySelector("mark") as HTMLElement);
    await fireEvent.click(screen.getByRole("menuitem", { name: "Ignore" }));
    expect(decideVerse).toHaveBeenCalledWith("1", "6", "f1", "ignored");
    expect(editVerse).not.toHaveBeenCalled();
    expect(document.querySelector("mark")).toBeNull();
  });

  it("opens the same finding menu from the keyboard, with no pointer involved", async () => {
    seed("alpha beta", [finding({
      start_offset: 0, end_offset: 5, original_text: "alpha", suggested_replacement: "omega",
    })]);
    render(VerseList, { props: { onSelect: vi.fn() } });
    const row = verseRow();
    expect(row).toHaveAttribute("aria-keyshortcuts", "Shift+F10");
    await fireEvent.keyDown(row, { key: "F10", shiftKey: true });
    expect(screen.getByRole("menu")).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "Accept finding" })).toBeEnabled();
  });

  it("also opens it with the dedicated Menu key", async () => {
    seed("alpha beta", [finding({ start_offset: 0, end_offset: 5, original_text: "alpha" })]);
    render(VerseList, { props: { onSelect: vi.fn() } });
    await fireEvent.keyDown(verseRow(), { key: "ContextMenu" });
    expect(screen.getByRole("menu")).toBeInTheDocument();
  });

  it("walks between a verse's findings with the arrow keys before opening the menu", async () => {
    seed("alpha beta", [
      finding({ id: "f1", start_offset: 0, end_offset: 5, original_text: "alpha",
        explanation: "First finding" }),
      finding({ id: "f2", start_offset: 6, end_offset: 10, original_text: "beta",
        explanation: "Second finding" }),
    ]);
    selectedVerse.set("6");
    render(VerseList, { props: { onSelect: vi.fn() } });
    const row = verseRow();

    // Starts on the first underline in reading order.
    expect(document.querySelector("mark.active-finding")?.textContent).toBe("alpha");
    await fireEvent.keyDown(row, { key: "ArrowRight" });
    expect(document.querySelector("mark.active-finding")?.textContent).toBe("beta");

    await fireEvent.keyDown(row, { key: "F10", shiftKey: true });
    expect(screen.getByRole("menu", { name: /Actions for Second finding/i })).toBeInTheDocument();
  });

  it("opens the general verse menu, not the finding menu, when the shortcut fires with no underlined finding", async () => {
    seed("alpha beta", [finding({ start_offset: null, end_offset: null })]);
    render(VerseList, { props: { onSelect: vi.fn() } });
    const row = verseRow();
    await fireEvent.keyDown(row, { key: "F10", shiftKey: true });
    expect(screen.getByRole("menu", { name: /Actions for verse 6/i })).toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: "Accept finding" })).toBeNull();
  });

  it("advertises the popup on the focusable row rather than the plain mark", () => {
    seed("alpha beta", [finding({ start_offset: 0, end_offset: 5, original_text: "alpha" })]);
    render(VerseList, { props: { onSelect: vi.fn() } });
    expect(verseRow()).toHaveAttribute("aria-haspopup", "menu");
    expect(document.querySelector("mark")).not.toHaveAttribute("aria-haspopup");
  });
});

describe("VerseList alignment glyph (issue #70)", () => {
  beforeEach(() => seed(PHP_1_6));

  function glyph(): HTMLElement {
    return screen.getByLabelText(/Open Align Words/) as HTMLElement;
  }

  it("always renders the ⇄ arrow, colored by completion status", () => {
    alignmentStatusByVerse.set({ [verseKey("1", "6")]: "complete" });
    render(VerseList, { props: { onSelect: vi.fn() } });
    expect(glyph()).toHaveTextContent("⇄");
    expect(glyph()).toHaveClass("complete");
  });

  it("colors the arrow for partial, invalid and untouched alignment too", () => {
    alignmentStatusByVerse.set({ [verseKey("1", "6")]: "partial" });
    const { unmount } = render(VerseList, { props: { onSelect: vi.fn() } });
    expect(glyph()).toHaveTextContent("⇄");
    expect(glyph()).toHaveClass("partial");
    unmount();

    alignmentStatusByVerse.set({ [verseKey("1", "6")]: "invalid" });
    const rendered2 = render(VerseList, { props: { onSelect: vi.fn() } });
    expect(glyph()).toHaveTextContent("⇄");
    expect(glyph()).toHaveClass("invalid");
    rendered2.unmount();

    alignmentStatusByVerse.set({});
    render(VerseList, { props: { onSelect: vi.fn() } });
    expect(glyph()).toHaveTextContent("⇄");
    expect(glyph()).toHaveClass("untouched");
  });

  it("selects the verse and opens the Align Words modal when clicked", async () => {
    const onSelect = vi.fn();
    render(VerseList, { props: { onSelect } });
    await fireEvent.click(glyph());
    expect(onSelect).toHaveBeenCalledWith("6");
    expect(get(alignmentOpen)).toBe(true);
    expect(get(alignmentKey)).toBe(verseKey("1", "6"));
  });

  it("does not also trigger the row's own select/edit handlers", async () => {
    const onSelect = vi.fn();
    render(VerseList, { props: { onSelect } });
    await fireEvent.click(glyph());
    // selectFromList runs exactly once (from the glyph handler itself, not
    // once more via the row's on:click) -- stopPropagation is load-bearing.
    expect(onSelect).toHaveBeenCalledTimes(1);
  });

  it("disables the glyph and refuses to open while background checking runs", async () => {
    checkingProgress.set({
      running: true, percent: 40, label: "Checking…", jobId: "j1", state: "running", error: "", scope: "chapter",
    });
    const onSelect = vi.fn();
    render(VerseList, { props: { onSelect } });
    expect(glyph()).toBeDisabled();
    await fireEvent.click(glyph());
    expect(onSelect).not.toHaveBeenCalled();
    expect(get(alignmentOpen)).toBe(false);
  });
});

describe("VerseList verse context menu (issue #69)", () => {
  beforeEach(() => seed("alpha beta"));

  it("opens on a plain right-click with AI review and Edit verse", async () => {
    const onSelect = vi.fn();
    render(VerseList, { props: { onSelect } });
    await fireEvent.contextMenu(verseRow());
    expect(screen.getByRole("menu", { name: /Actions for verse 6/i })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "AI review" })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "Edit verse" })).toBeInTheDocument();
    expect(onSelect).toHaveBeenCalledWith("6");
  });

  it("does not also open the finding menu when a finding mark is right-clicked", async () => {
    seed("alpha beta", [finding({
      start_offset: 0, end_offset: 5, original_text: "alpha", suggested_replacement: null,
    })]);
    render(VerseList, { props: { onSelect: vi.fn() } });
    await fireEvent.contextMenu(document.querySelector("mark") as HTMLElement);
    expect(screen.getAllByRole("menu")).toHaveLength(1);
    expect(screen.getByRole("menuitem", { name: "Accept finding" })).toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: "AI review" })).toBeNull();
  });

  it("opens the AI review submenu and requests a scope, then closes", async () => {
    render(VerseList, { props: { onSelect: vi.fn() } });
    await fireEvent.contextMenu(verseRow());
    await fireEvent.click(screen.getByRole("menuitem", { name: "AI review" }));
    await fireEvent.click(screen.getByRole("menuitem", { name: "Chapter" }));
    expect(get(aiReviewRequest)).toEqual({ chapter: "1", verse: "6", scope: "chapter" });
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("starts editing the verse from the menu's Edit verse item", async () => {
    render(VerseList, { props: { onSelect: vi.fn() } });
    await fireEvent.contextMenu(verseRow());
    await fireEvent.click(screen.getByRole("menuitem", { name: "Edit verse" }));
    expect(get(editingChapter)).toBe("1");
    expect(get(editingVerse)).toBe("6");
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("disables every action while background checking runs", async () => {
    checkingProgress.set({
      running: true, percent: 40, label: "Checking…", jobId: "j1", state: "running", error: "", scope: "chapter",
    });
    render(VerseList, { props: { onSelect: vi.fn() } });
    await fireEvent.contextMenu(verseRow());
    expect(screen.getByRole("menuitem", { name: "Edit verse" })).toBeDisabled();
    await fireEvent.click(screen.getByRole("menuitem", { name: "AI review" }));
    expect(screen.getByRole("menuitem", { name: "Verse" })).toBeDisabled();
    expect(screen.getByRole("menuitem", { name: "Chapter" })).toBeDisabled();
    expect(screen.getByRole("menuitem", { name: "Book" })).toBeDisabled();
  });

  it("disables only the verse scope while an AI review job is already active", async () => {
    aiJobActive.set(true);
    render(VerseList, { props: { onSelect: vi.fn() } });
    await fireEvent.contextMenu(verseRow());
    await fireEvent.click(screen.getByRole("menuitem", { name: "AI review" }));
    expect(screen.getByRole("menuitem", { name: "Verse" })).toBeDisabled();
    expect(screen.getByRole("menuitem", { name: "Chapter" })).toBeDisabled();
    expect(screen.getByRole("menuitem", { name: "Book" })).toBeDisabled();
  });

  it("opens the same verse menu via Shift+F10 and closes it on Escape", async () => {
    render(VerseList, { props: { onSelect: vi.fn() } });
    const row = verseRow();
    await fireEvent.keyDown(row, { key: "F10", shiftKey: true });
    const menu = screen.getByRole("menu", { name: /Actions for verse 6/i });
    await fireEvent.keyDown(menu, { key: "Escape" });
    expect(screen.queryByRole("menu")).toBeNull();
  });
});
