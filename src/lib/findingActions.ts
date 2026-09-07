import { bridge } from "./api/bridgeClient";
import { findingsByVerse, verseKey } from "./stores";
import type { FindingStatus } from "./types/finding";

/** Persist a local finding decision and update every visible copy of that finding. */
export async function decideLocalFinding(
  chapter: string,
  verse: string,
  findingId: string,
  status: FindingStatus,
): Promise<void> {
  await bridge.decideVerse(chapter, verse, findingId, status);
  const key = verseKey(chapter, verse);
  findingsByVerse.update((map) => ({
    ...map,
    [key]: (map[key] ?? []).map((finding) =>
      finding.id === findingId ? { ...finding, status } : finding,
    ),
  }));
}
