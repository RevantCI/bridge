import { describe, expect, it, vi, beforeEach } from "vitest";

const getLexiconEntry = vi.fn();
vi.mock("../../api/bridgeClient", () => ({ bridge: { getLexiconEntry } }));

const { SourceGlossCache, shortGloss } = await import("../../lexiconGloss");

/** Real Open Scriptures definitions, copied verbatim from the bundled lexicon. */
const G746 =
  "(properly abstract) a commencement, or (concretely) chief (in various applications of order, time, place, or rank)";
const G2632 = "to judge against, i.e. sentence";
const G26 = "love, i.e. affection or benevolence; specially (plural) a love-feast";
const H7225 = "the first, in place, time, order or rank (specifically, a firstfruit)";

describe("shortGloss", () => {
  it("drops the parenthetical hedges that make Strong's definitions long", () => {
    expect(shortGloss(G746)).toBe("a commencement, or chief");
  });

  it("cuts at the definition's own break points", () => {
    expect(shortGloss(G2632)).toBe("to judge against");
    expect(shortGloss(G26)).toBe("love");
  });

  it("keeps a definition that is already short enough intact", () => {
    expect(shortGloss("God")).toBe("God");
    expect(shortGloss(H7225)).toBe("the first, in place, time, order or rank");
  });

  it("ellipsizes at a comma rather than mid-word when it must truncate", () => {
    const gloss = shortGloss("a very long first sense indeed, a second sense, a third sense");
    expect(gloss).toBe("a very long first sense indeed…");
  });

  it("is empty for a missing meaning rather than printing null", () => {
    expect(shortGloss(null)).toBe("");
    expect(shortGloss(undefined)).toBe("");
    expect(shortGloss("   ")).toBe("");
  });
});

describe("SourceGlossCache", () => {
  beforeEach(() => {
    getLexiconEntry.mockReset();
  });

  const token = { word: "θεοῦ", occurrence: 1, occurrences: 1, strong: "G23160", morph: "Gr,N", lemma: "θεός" };

  it("shows the word's meaning, not the lemma, and keeps the lemma for the tooltip", async () => {
    getLexiconEntry.mockResolvedValue({
      languageId: "el-x-koine",
      segments: [{ lemma: "θεός", meaning: "a deity, especially the supreme Divinity" }],
    });
    const cache = new SourceGlossCache();
    await cache.load([token]);

    const gloss = cache.glossFor(token);
    expect(gloss.short).toBe("a deity, especially the supreme Divinity");
    expect(gloss.short).not.toContain("θεός");
    expect(gloss.title).toBe("θεός · G23160 · Gr,N\na deity, especially the supreme Divinity");
  });

  it("joins a Hebrew proclitic's gloss with its lexeme's, in order", async () => {
    const compound = { word: "בְּרֵאשִׁית", occurrence: 1, occurrences: 1, strong: "b:H7225", morph: "He,R:Ncfsa" };
    getLexiconEntry.mockResolvedValue({
      languageId: "hbo",
      segments: [
        { lemma: null, meaning: "Preposition (in/on/with)" },
        { lemma: "רֵאשִׁית", meaning: H7225 },
      ],
    });
    const cache = new SourceGlossCache();
    await cache.load([compound]);

    expect(cache.glossFor(compound).short).toBe(
      "Preposition + the first, in place, time, order or rank",
    );
  });

  it("resolves each strong|morph pair once, however many tokens share it", async () => {
    getLexiconEntry.mockResolvedValue({ languageId: "el-x-koine", segments: [{ meaning: "God", lemma: "θεός" }] });
    const cache = new SourceGlossCache();
    await cache.load([token, { ...token, word: "θεός" }, { ...token, strong: "G26" }]);
    expect(getLexiconEntry).toHaveBeenCalledTimes(2);

    // A second load over the same tokens hits the cache and fires nothing.
    await cache.load([token]);
    expect(getLexiconEntry).toHaveBeenCalledTimes(2);
  });

  it("falls back to the lemma when the lexicon has no entry, rather than blanking the label", async () => {
    getLexiconEntry.mockRejectedValue(new Error("no such strong"));
    const cache = new SourceGlossCache();
    await cache.load([token]);

    expect(cache.glossFor(token).short).toBe("θεός");
    expect(cache.glossFor(token).title).toBe("θεός · G23160 · Gr,N");
  });

  it("returns the lemma fallback before the lookups land", () => {
    const cache = new SourceGlossCache();
    expect(cache.glossFor(token).short).toBe("θεός");
  });
});
