// Range suggestions and finding hand-off for the Cross-verse alignment page (#118).
//
// Bridge already knows which verses carry cross-verse realization: Stage 6B
// relationships carry a CROSS_VERSE property, and the last analysis job for a
// chapter names its location run. This module turns that into verse strings the
// range picker can pre-select. Verse "numbers" stay the opaque strings the
// engine uses ("3-4", "3a"); nothing here parses them as integers.
import { bridge } from "./api/bridgeClient";
import type { SemanticLocationRun, TargetSemanticInventory } from "./types/passageSemanticV1";

/** "PHP 1:3" → { chapter: "1", verse: "3" }; "PHP 1:2-3" keeps the bridge string. */
export function parseDisplayedReference(reference: string): { chapter: string; verse: string } | null {
  const trimmed = String(reference ?? "").trim();
  const space = trimmed.lastIndexOf(" ");
  const chapterVerse = space >= 0 ? trimmed.slice(space + 1) : trimmed;
  const colon = chapterVerse.indexOf(":");
  if (colon <= 0) return null;
  const chapter = chapterVerse.slice(0, colon);
  const verse = chapterVerse.slice(colon + 1);
  if (!chapter || !verse) return null;
  return { chapter, verse };
}

/** Verses of one chapter named by a finding's references, in the order given
 *  (deduplicated). References in other chapters are dropped: the page is
 *  chapter-scoped, and the first reference's chapter wins. */
export function versesForReferences(references: readonly string[]): { chapter: string; verses: string[] } | null {
  const parsed = references.map(parseDisplayedReference).filter((x): x is { chapter: string; verse: string } => Boolean(x));
  if (parsed.length === 0) return null;
  const chapter = parsed[0].chapter;
  const verses: string[] = [];
  for (const item of parsed) {
    if (item.chapter === chapter && !verses.includes(item.verse)) verses.push(item.verse);
  }
  return { chapter, verses };
}

/** Verses of `chapter` that a location run's CROSS_VERSE relationships land
 *  in, found through the target tokens' displayed references (the same route
 *  PassageAlignmentMode takes: a relationship carries token ids, not verses). */
export function crossVerseVersesFromRun(
  run: Pick<SemanticLocationRun, "relationships">,
  inventory: Pick<TargetSemanticInventory, "tokens"> | null,
  chapter: string,
): string[] {
  const referenceByToken = new Map<string, string>();
  for (const token of inventory?.tokens ?? []) {
    if (token.displayedReference) referenceByToken.set(token.id, token.displayedReference);
  }
  const verses: string[] = [];
  for (const relationship of run.relationships ?? []) {
    if (!(relationship.properties ?? []).includes("CROSS_VERSE")) continue;
    for (const tokenId of relationship.targetTokenInstanceIds ?? []) {
      const parsed = parseDisplayedReference(referenceByToken.get(tokenId) ?? "");
      if (parsed && parsed.chapter === chapter && !verses.includes(parsed.verse)) verses.push(parsed.verse);
    }
  }
  return verses;
}

/** Union of verse lists, in chapter order. */
export function unionInChapterOrder(verseNums: readonly string[], ...lists: readonly string[][]): string[] {
  const wanted = new Set(lists.flat());
  return verseNums.filter((v) => wanted.has(v));
}

export interface CrossVerseSuggestion {
  runId: string;
  verses: string[];
}

/**
 * The verses the last Stage 6B run for `chapter` marked as cross-verse
 * realization, or null when there is no completed run, no location stage, or
 * any of the reads fails. Never throws: a suggestion is a convenience, and the
 * manual picker is always there.
 */
export async function suggestCrossVerseRange(chapter: string): Promise<CrossVerseSuggestion | null> {
  try {
    const status = await bridge.analysisJobGetScopeStatus({ kind: "CURRENT_CHAPTER", chapter });
    const runId = status.latestJob?.stageStatuses?.LOCATION?.runId ?? "";
    if (!runId) return null;
    const run = await bridge.semanticLocationGetRange(runId);
    const inventory = run.targetInventoryId ? await bridge.targetSemanticGetRange(run.targetInventoryId) : null;
    return { runId, verses: crossVerseVersesFromRun(run, inventory, chapter) };
  } catch {
    return null;
  }
}
