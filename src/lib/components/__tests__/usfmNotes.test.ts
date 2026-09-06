import { describe, it, expect } from "vitest";
import { parseVerseNotes, withNoteMarkers } from "../../utils/usfmNotes";
import type { TextSegment } from "../../utils/highlight";

// The verse that surfaced this: IRV Hindi Philippians 1:6, which rendered its
// footnote markup inline in the editor panel.
const PHP_1_6 =
  "\\it मुझे इस बात का भरोसा है\\it*\\f + \\fr 1.6 \\fq मुझे इस बात का भरोसा है: " +
  "\\ft इसका मतलब यह है पौलुस ने जो कुछ कहा उसका सच पूरी तरह से आश्वस्त था।\\f* " +
  "कि जिसने तुम में अच्छा काम आरम्भ किया है।";

const seg = (text: string): TextSegment => ({
  text,
  findingIds: [],
  className: null,
  title: "",
  numbers: [],
});

describe("parseVerseNotes", () => {
  it("lifts the footnote out of the verse", () => {
    const parsed = parseVerseNotes(PHP_1_6);
    expect(parsed.clean).not.toContain("\\f");
    expect(parsed.clean).not.toContain("इसका मतलब यह है");
    expect(parsed.clean).toContain("कि जिसने तुम में अच्छा काम आरम्भ किया है।");
  });

  it("leaves styling markers untouched", () => {
    const parsed = parseVerseNotes(PHP_1_6);
    expect(parsed.clean).toContain("\\it");
    expect(parsed.clean).toContain("\\it*");
  });

  it("does not touch a verse whose only markup is styling", () => {
    const raw = "\\it emphasised\\it* plain \\nd LORD\\nd*";
    expect(parseVerseNotes(raw).clean).toBe(raw);
  });

  it("captures the footnote reference and body separately", () => {
    const parsed = parseVerseNotes(PHP_1_6);
    expect(parsed.footnotes).toHaveLength(1);
    const note = parsed.footnotes[0];
    expect(note.caller).toBe("+");
    expect(note.reference).toBe("1.6");
    expect(note.parts.map((p) => p.marker)).toEqual(["fr", "fq", "ft"]);
    expect(note.text).toContain("इसका मतलब यह है");
    expect(note.text).not.toContain("1.6");
  });

  it("parses cross references with their origin and target", () => {
    const parsed = parseVerseNotes("पवित्र लोगों\\x + \\xo 1.1 \\xt रोम. 1:7; 2 कुरि. 1:1\\x* के नाम");
    expect(parsed.xrefs).toHaveLength(1);
    expect(parsed.xrefs[0].reference).toBe("1.1");
    expect(parsed.xrefs[0].text).toBe("रोम. 1:7; 2 कुरि. 1:1");
    expect(parsed.clean).toBe("पवित्र लोगों के नाम");
  });

  it("keeps both kinds in document order with their positions", () => {
    const parsed = parseVerseNotes("a\\f + \\ft one\\f* b\\x + \\xt Gen 1:1\\x* c\\f + \\ft two\\f*");
    expect(parsed.notes.map((n) => n.kind)).toEqual(["footnote", "xref", "footnote"]);
    expect(parsed.clean).toBe("a b c");
    expect(parsed.notes.map((n) => n.position)).toEqual([1, 3, 5]);
  });

  it("records the position each note was lifted from", () => {
    const parsed = parseVerseNotes("alpha\\f + \\ft note\\f* bravo");
    expect(parsed.clean).toBe("alpha bravo");
    expect(parsed.footnotes[0].position).toBe(5);
  });

  it("leaves a verse with no notes byte-identical", () => {
    const plain = "मसीह यीशु के दास पौलुस और तीमुथियुस की ओर से";
    const parsed = parseVerseNotes(plain);
    expect(parsed.clean).toBe(plain);
    expect(parsed.notes).toHaveLength(0);
  });

  it("does not leave a double space where a note was removed", () => {
    expect(parseVerseNotes("alpha \\f + \\ft n\\f* bravo").clean).toBe("alpha bravo");
  });

  it("maps offsets so a span after a removed note still covers the same word", () => {
    const raw = "alpha\\f + \\ft note\\f* bravo charlie";
    const parsed = parseVerseNotes(raw);
    const rawStart = raw.indexOf("bravo");
    expect(
      parsed.clean.slice(parsed.mapOffset(rawStart), parsed.mapOffset(rawStart + 5)),
    ).toBe("bravo");
  });

  it("maps the real Philippians 1:6 span across its footnote", () => {
    const parsed = parseVerseNotes(PHP_1_6);
    const word = "आरम्भ";
    const rawStart = PHP_1_6.indexOf(word);
    expect(
      parsed.clean.slice(parsed.mapOffset(rawStart), parsed.mapOffset(rawStart + word.length)),
    ).toBe(word);
  });

  it("collapses a span that lived entirely inside a note to zero length", () => {
    const raw = "alpha\\f + \\ft hidden\\f* bravo";
    const parsed = parseVerseNotes(raw);
    const rawStart = raw.indexOf("hidden");
    expect(parsed.mapOffset(rawStart)).toBe(parsed.mapOffset(rawStart + 6));
  });

  it("tolerates an unterminated footnote without swallowing the verse", () => {
    const parsed = parseVerseNotes("alpha\\f + \\ft dangling bravo");
    expect(parsed.clean).toContain("alpha");
    expect(parsed.notes).toHaveLength(0);
  });
});

describe("withNoteMarkers", () => {
  it("splits a segment so the marker lands where the note was", () => {
    const parsed = parseVerseNotes("alpha\\f + \\ft n\\f* bravo");
    const pieces = withNoteMarkers([seg(parsed.clean)], parsed.notes);
    expect(pieces.map((p) => (p.kind === "note" ? "[f]" : p.seg.text))).toEqual([
      "alpha",
      "[f]",
      " bravo",
    ]);
  });

  it("puts a leading note before all the text", () => {
    const parsed = parseVerseNotes("\\f + \\ft n\\f*alpha");
    const pieces = withNoteMarkers([seg(parsed.clean)], parsed.notes);
    expect(pieces[0].kind).toBe("note");
  });

  it("puts a trailing note after all the text", () => {
    const parsed = parseVerseNotes("alpha\\f + \\ft n\\f*");
    const pieces = withNoteMarkers([seg(parsed.clean)], parsed.notes);
    expect(pieces[pieces.length - 1].kind).toBe("note");
  });

  it("keeps highlight segments intact when a note sits on their boundary", () => {
    const parsed = parseVerseNotes("alpha\\f + \\ft n\\f* bravo");
    const marked: TextSegment[] = [
      { ...seg("alpha"), className: "m-gr" },
      seg(" bravo"),
    ];
    const pieces = withNoteMarkers(marked, parsed.notes);
    const texts = pieces.filter((p) => p.kind === "text");
    expect(texts.map((p) => (p as { seg: TextSegment }).seg.text)).toEqual(["alpha", " bravo"]);
    expect((texts[0] as { seg: TextSegment }).seg.className).toBe("m-gr");
  });

  it("returns segments unchanged when there are no notes", () => {
    const pieces = withNoteMarkers([seg("alpha bravo")], []);
    expect(pieces).toHaveLength(1);
    expect(pieces[0].kind).toBe("text");
  });

  it("orders several markers by position", () => {
    const parsed = parseVerseNotes("a\\f + \\ft one\\f*b\\x + \\xt G 1:1\\x*c");
    const pieces = withNoteMarkers([seg(parsed.clean)], parsed.notes);
    expect(pieces.map((p) => (p.kind === "note" ? p.note.kind : p.seg.text))).toEqual([
      "a",
      "footnote",
      "b",
      "xref",
      "c",
    ]);
  });
});
