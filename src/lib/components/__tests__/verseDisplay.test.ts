import { describe, it, expect } from "vitest";
import { identityDisplay, plainOffset, plainToUtf16, utf16Offset } from "../../utils/verseDisplay";
import { DISPLAY_FIXTURES, displayFor } from "./verseDisplayFixtures";

// The verse that surfaced the note lifting: IRV Hindi Philippians 1:6.
const PHP_1_6 =
  "\\it मुझे इस बात का भरोसा है\\it*\\f + \\fr 1.6 \\fq मुझे इस बात का भरोसा है: " +
  "\\ft इसका मतलब यह है पौलुस ने जो कुछ कहा उसका सच पूरी तरह से आश्वस्त था।\\f* " +
  "कि जिसने तुम में अच्छा काम आरम्भ किया है।";

describe("the engine's display payload", () => {
  it("lifts the footnote and the style markers out of Philippians 1:6", () => {
    const display = displayFor(PHP_1_6);
    expect(display.plain).toBe("मुझे इस बात का भरोसा है कि जिसने तुम में अच्छा काम आरम्भ किया है।");
    expect(display.notes).toHaveLength(1);
    expect(display.notes[0].reference).toBe("1.6");
    expect(display.styles.map((s) => s.marker)).toEqual(["it"]);
  });

  it("maps the real Philippians 1:6 span across its footnote", () => {
    const display = displayFor(PHP_1_6);
    const word = "आरम्भ";
    const rawStart = PHP_1_6.indexOf(word);
    expect(
      display.plain.slice(utf16Offset(display, rawStart), utf16Offset(display, rawStart + word.length)),
    ).toBe(word);
  });

  it("maps offsets so a span after a removed note still covers the same word", () => {
    const raw = "இந்த \\f + \\ft குறிப்பு\\f* நற்கிரியையை";
    const display = displayFor(raw);
    const rawStart = Array.from(raw.slice(0, raw.indexOf("நற்கிரியையை"))).length;
    const rawEnd = rawStart + Array.from("நற்கிரியையை").length;
    expect(display.plain.slice(utf16Offset(display, rawStart), utf16Offset(display, rawEnd))).toBe("நற்கிரியையை");
  });

  it("collapses a span that lived entirely inside a note to zero length", () => {
    const raw = "a \\f + \\ft inside\\f* b";
    const display = displayFor(raw);
    const rawStart = raw.indexOf("inside");
    expect(plainOffset(display, rawStart)).toBe(plainOffset(display, rawStart + 6));
    expect(plainOffset(display, rawStart)).toBe(2);
  });

  it("clamps offsets outside the raw string", () => {
    const display = displayFor("a \\f + \\ft n\\f* b");
    expect(plainOffset(display, -5)).toBe(0);
    expect(plainOffset(display, 999)).toBe(Array.from(display.plain).length);
  });

  it("converts a note position to a UTF-16 index for layout", () => {
    const display = displayFor(PHP_1_6);
    const [note] = display.notes;
    expect(plainToUtf16(display, note.position)).toBe("मुझे इस बात का भरोसा है".length);
  });

  it("is the identity for a verse without markup", () => {
    const display = identityDisplay("alpha beta");
    expect(display.plain).toBe("alpha beta");
    expect(plainOffset(display, 6)).toBe(6);
    expect(utf16Offset(display, 6)).toBe(6);
  });

  it("every fixture is deletion-only: plain is raw minus the removed ranges", () => {
    for (const [raw, display] of Object.entries(DISPLAY_FIXTURES)) {
      const points = Array.from(raw);
      const kept = points.filter((_, i) => !display.removed.some(([a, b]) => a <= i && i < b)).join("");
      expect(kept, raw).toBe(display.plain);
    }
  });
});
