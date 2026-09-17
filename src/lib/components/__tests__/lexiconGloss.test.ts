import { describe, expect, it, vi, beforeEach } from "vitest";

const getLexiconEntry = vi.fn();
vi.mock("../../api/bridgeClient", () => ({ bridge: { getLexiconEntry } }));

const { SourceGlossCache, shortGloss, shortUsage } = await import("../../lexiconGloss");

/** Real Open Scriptures definitions, copied verbatim from the bundled lexicon. */
const G746 =
  "(properly abstract) a commencement, or (concretely) chief (in various applications of order, time, place, or rank)";
const G2632 = "to judge against, i.e. sentence";
const G26 = "love, i.e. affection or benevolence; specially (plural) a love-feast";
const H7225 = "the first, in place, time, order or rank (specifically, a firstfruit)";

/** The `usage` lists paired with those same entries, also verbatim. */
const G746_USAGE =
  "beginning, corner, (at the, the) first (estate), magistrate, power, principality, principle, rule";
const G2632_USAGE = "condemn, damn";
const G26_USAGE = "(feast of) charity(-ably), dear, love";
const H7225_USAGE = "beginning, chief(-est), first(-fruits, part, time), principal thing.";
const H430_USAGE = "angels, × exceeding, God (gods) (-dess, -ly), × (very) great, judges, × mighty.";
const G2316_USAGE = "X exceeding, God, god(-ly, -ward)";

describe("shortUsage", () => {
  it("keeps the renderings that fit and stops at the character budget", () => {
    expect(shortUsage(G746_USAGE)).toBe("beginning, corner, first, magistrate");
    expect(shortUsage(G2632_USAGE)).toBe("condemn, damn");
  });

  it("unfolds the KJV parenthetical infixes into the bare rendering", () => {
    expect(shortUsage(G26_USAGE)).toBe("charity, dear, love");
    // The infix parenthetical holds commas of its own, so it has to go before the split.
    expect(shortUsage(H7225_USAGE)).toBe("beginning, chief, first, principal thing");
  });

  it("drops the KJV marker in both of the spellings the data uses, and the trailing full stop", () => {
    expect(shortUsage(H430_USAGE)).toBe("angels, exceeding, God, great, judges");
    expect(shortUsage(H430_USAGE)).not.toContain("×");
    // G2316 -- the commonest source token in the NT -- writes the same marker as an ASCII X.
    expect(shortUsage(G2316_USAGE)).toBe("exceeding, God, god");
  });

  it("leaves a rendering that merely starts with an X alone", () => {
    expect(shortUsage("Xerxes, king")).toBe("Xerxes, king");
  });

  it("is empty for a missing usage list rather than printing null", () => {
    expect(shortUsage(null)).toBe("");
    expect(shortUsage(undefined)).toBe("");
    expect(shortUsage("  , ( ) ,  ")).toBe("");
  });

  it("keeps the first rendering even when it alone overruns the budget", () => {
    const only = shortUsage("a single extraordinarily long rendering that overruns the budget");
    expect(only.startsWith("a single extraordinarily long rendering")).toBe(true);
    expect(only.endsWith("…")).toBe(true);
  });
});

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

  it("labels the word with its renderings and keeps the lemma and definition for the tooltip", async () => {
    getLexiconEntry.mockResolvedValue({
      languageId: "el-x-koine",
      segments: [{
        lemma: "θεός",
        meaning: "a deity, especially the supreme Divinity",
        usage: G2316_USAGE,
      }],
    });
    const cache = new SourceGlossCache();
    await cache.load([token]);

    const gloss = cache.glossFor(token);
    expect(gloss.short).toBe("exceeding, God, god");
    expect(gloss.short).not.toContain("θεός");
    // The definition is what moved out of the label, so it has to be in the tooltip.
    expect(gloss.title).toBe("θεός · G23160 · Gr,N\na deity, especially the supreme Divinity");
  });

  it("falls back to the definition when the entry carries no usage list", async () => {
    getLexiconEntry.mockResolvedValue({
      languageId: "el-x-koine",
      segments: [{ lemma: "κατακρίνω", meaning: G2632, usage: null }],
    });
    const cache = new SourceGlossCache();
    await cache.load([token]);
    expect(cache.glossFor(token).short).toBe("to judge against");
  });

  it("joins a Hebrew proclitic's label with its lexeme's renderings, in order", async () => {
    const compound = { word: "בְּרֵאשִׁית", occurrence: 1, occurrences: 1, strong: "b:H7225", morph: "He,R:Ncfsa" };
    getLexiconEntry.mockResolvedValue({
      languageId: "hbo",
      segments: [
        // A proclitic has no Strong's entry: the engine sends the prefix label
        // as `meaning` with no lemma and no usage, and its parenthetical is the
        // part that carries the sense, so it is not compressed away.
        { lemma: null, meaning: "Preposition (in/on/with)", usage: null },
        { lemma: "רֵאשִׁית", meaning: H7225, usage: H7225_USAGE },
      ],
    });
    const cache = new SourceGlossCache();
    await cache.load([compound]);

    expect(cache.glossFor(compound).short).toBe(
      "Preposition (in/on/with) + beginning, chief, first, principal thing",
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
