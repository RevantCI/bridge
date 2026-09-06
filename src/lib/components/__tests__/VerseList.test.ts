import { describe, expect, it, beforeEach, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/svelte";

import VerseList from "../VerseList.svelte";
import {
  chapterVerseNums,
  currentChapter,
  verseTexts,
  findingsByVerse,
  checkStatusByVerse,
  alignmentStatusByVerse,
  nativeChecksByVerse,
  aiCheckReviewsByVerse,
  selectedVerse,
  verseKey,
} from "../../stores";
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
});
