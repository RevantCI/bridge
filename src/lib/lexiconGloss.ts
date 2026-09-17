/**
 * Source-word glosses for the two alignment surfaces (single verse and
 * cross-verse range).
 *
 * Both modals used to print the token's `lemma` under the source word. A lemma
 * is another Greek or Hebrew string, so for a reviewer who does not read either
 * script it carried no information at all -- the label was decoration. What is
 * actually useful there is the English gloss, with the lemma demoted to the
 * hover title where a reader who *does* want it can still find it alongside
 * Strong's number and the morphology.
 *
 * Both modals resolve the same lexicon entries, keyed on the same
 * `strong|morph` pair, so the cache and the two label builders live here rather
 * than being copy-pasted into each component.
 */
import { bridge } from "./api/bridgeClient";
import type { LexiconSegment, TokenRef } from "./types/finding";

/** How much of a Strong's definition fits under a word before it reads as a paragraph. */
const SHORT_GLOSS_LIMIT = 42;

/**
 * Compress one Strong's definition into something that fits under a word.
 *
 * The bundled Open Scriptures entries are full dictionary definitions, not
 * glosses -- G746 is "(properly abstract) a commencement, or (concretely) chief
 * (in various applications of order, time, place, or rank)". Rendering that
 * verbatim in a narrow cell is worse than the lemma was. The sense a reader
 * needs is always at the front, before the first `i.e.`, the first `;`, and
 * outside the parenthetical hedges, so this keeps that head and leaves the
 * unabridged text to the tooltip and the lexicon popup.
 */
export function shortGloss(meaning: string | null | undefined): string {
  let text = String(meaning ?? "");
  if (!text.trim()) return "";
  // Parenthetical asides qualify the definition rather than carrying it, and
  // they are what make these strings long. Dropped before the length cap so
  // the cap spends its budget on the sense itself.
  text = text.replace(/\([^()]*\)/g, " ");
  const cut = text.search(/;|,?\s+i\.e\.\s+|\s+--\s+/);
  if (cut > 0) text = text.slice(0, cut);
  text = text.replace(/\s+/g, " ").replace(/^[\s,;:.-]+/, "").replace(/[\s,;:.-]+$/, "");
  if (text.length <= SHORT_GLOSS_LIMIT) return text;
  // Prefer breaking where the definition itself breaks, so the label never
  // ends mid-word; fall back to a hard cut when there is no comma to use.
  const head = text.slice(0, SHORT_GLOSS_LIMIT);
  const lastComma = head.lastIndexOf(",");
  const kept = lastComma > SHORT_GLOSS_LIMIT / 2 ? head.slice(0, lastComma) : head;
  return `${kept.replace(/\s+$/, "")}…`;
}

/** The cache key: two tokens with the same Strong's number and morphology resolve identically. */
export function lexiconKey(token: Pick<TokenRef, "strong" | "morph">): string {
  return `${token.strong ?? ""}|${token.morph ?? ""}`;
}

/**
 * One token's resolved labels. `short` goes under the word, `title` into the
 * hover tooltip; both are plain strings so a component can drop them straight
 * into markup.
 */
export interface SourceGloss {
  short: string;
  title: string;
}

/** The lexicon-backed half of a token's labels, before the token's own lemma is folded in. */
interface ResolvedEntry {
  short: string;
  /** The unabridged meaning, one line per morpheme segment, for the tooltip. */
  detail: string;
}

const EMPTY: ResolvedEntry = { short: "", detail: "" };

function resolve(segments: readonly LexiconSegment[]): ResolvedEntry {
  const shorts: string[] = [];
  const details: string[] = [];
  for (const segment of segments) {
    const gloss = shortGloss(segment.meaning);
    if (gloss) shorts.push(gloss);
    const full = (segment.meaning ?? "").replace(/\s+/g, " ").trim();
    const lemma = (segment.lemma ?? "").trim();
    // With one segment the tooltip's first line already names the lemma, so
    // repeating it here would just be noise; with several (a Hebrew proclitic
    // plus its lexeme) the reader needs to know which meaning is whose.
    if (full && lemma && segments.length > 1) details.push(`${lemma} — ${full}`);
    else if (full) details.push(full);
  }
  // A Hebrew proclitic is its own segment ("b:H7225" is a preposition plus a
  // lexeme), so the word's gloss is the segments joined in order -- not the
  // lexeme's gloss alone.
  return { short: shorts.join(" + "), detail: details.join("\n") };
}

/**
 * Resolves and caches source-token glosses for one modal instance.
 *
 * `load` is fire-and-forget from `onMount`; `glossFor` returns the best labels
 * available right now, so a component renders the fallback immediately and
 * re-renders with the gloss once the lookups land.
 */
export class SourceGlossCache {
  private readonly entries = new Map<string, ResolvedEntry>();
  /** Bumped after every batch so a Svelte `$:` can depend on it and re-render. */
  version = 0;

  /** Resolve every distinct `strong|morph` in `tokens`, skipping ones already cached. */
  async load(tokens: readonly TokenRef[]): Promise<void> {
    const wanted = new Set<string>();
    for (const token of tokens) {
      if (!token.strong && !token.morph) continue;
      const key = lexiconKey(token);
      if (!this.entries.has(key)) wanted.add(key);
    }
    if (!wanted.size) return;
    // Claimed up front: two overlapping `load` calls (the cross-verse modal
    // reloads on every range change) must not each fire the same lookup.
    for (const key of wanted) this.entries.set(key, EMPTY);
    await Promise.all(
      [...wanted].map(async (key) => {
        const [strong, morph] = key.split("|");
        try {
          const entry = await bridge.getLexiconEntry(strong, morph);
          this.entries.set(key, resolve(entry?.segments ?? []));
        } catch {
          this.entries.set(key, EMPTY);
        }
      }),
    );
    this.version += 1;
  }

  /**
   * The label pair for one source token.
   *
   * `short` falls back to the lemma when the lexicon has nothing -- an
   * unresolved Strong's number should not leave the cell blank, and the lemma
   * is still what the old UI showed there.
   */
  glossFor(token: TokenRef): SourceGloss {
    const entry = this.entries.get(lexiconKey(token)) ?? EMPTY;
    const lemma = (token.lemma ?? "").trim();
    const identity = [lemma, token.strong, token.morph].filter(Boolean).join(" · ");
    const title = [identity, entry.detail].filter(Boolean).join("\n");
    return { short: entry.short || lemma, title };
  }
}
