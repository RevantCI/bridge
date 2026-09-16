// Verse-range arithmetic for the Cross-verse alignment page (#116).
//
// Verse "numbers" are the opaque strings the engine hands back in
// `verseNums` -- "3-4" (a bridge) and "3a" (a lettered segment) are real
// input (CLAUDE.md gotcha 12). Every neighbour/ordering question here is
// answered by *index into the chapter's verse list*, never by parsing the
// string as a number.

const NON_VERSE = new Set(["front"]);

function usable(verseNums: readonly string[]): string[] {
  return verseNums.filter((v) => !NON_VERSE.has(v));
}

/** The selected verse plus one on each side, clamped to the chapter. */
export function defaultRange(verseNums: readonly string[], selected: string): string[] {
  const verses = usable(verseNums);
  const index = verses.indexOf(selected);
  if (index < 0) return selected ? [selected] : [];
  return verses.slice(Math.max(0, index - 1), Math.min(verses.length, index + 2));
}

/** Every verse from `from` to `to` inclusive, in chapter order; the two
 *  endpoints may be given in either order. Unknown endpoints yield []. */
export function rangeBetween(verseNums: readonly string[], from: string, to: string): string[] {
  const verses = usable(verseNums);
  const a = verses.indexOf(from);
  const b = verses.indexOf(to);
  if (a < 0 || b < 0) return [];
  return verses.slice(Math.min(a, b), Math.max(a, b) + 1);
}

/** Toggle one verse in a selection, keeping chapter order. A selection never
 *  drops to empty: toggling the last remaining verse is a no-op. */
export function toggleVerse(verseNums: readonly string[], selection: readonly string[], verse: string): string[] {
  const verses = usable(verseNums);
  if (!verses.includes(verse)) return [...selection];
  const set = new Set(selection);
  if (set.has(verse)) {
    if (set.size === 1) return [...selection];
    set.delete(verse);
  } else {
    set.add(verse);
  }
  return verses.filter((v) => set.has(v));
}

/** The chapter-order span that covers a selection: [first, last]. */
export function spanOf(verseNums: readonly string[], selection: readonly string[]): [string, string] | null {
  const ordered = usable(verseNums).filter((v) => selection.includes(v));
  if (ordered.length === 0) return null;
  return [ordered[0], ordered[ordered.length - 1]];
}

/** Split the composite ids the page puts in the DOM ("verse|tokenId"). The
 *  verse itself may contain "-" or letters but never "|". */
export function splitVerseId(composite: string): { verse: string; id: string } {
  const at = composite.indexOf("|");
  if (at < 0) return { verse: "", id: composite };
  return { verse: composite.slice(0, at), id: composite.slice(at + 1) };
}

export function joinVerseId(verse: string, id: string): string {
  return `${verse}|${id}`;
}
