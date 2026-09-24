import { bridge } from "./api/bridgeClient";
import { findingsByVerse, verseKey } from "./stores";
import type { FindingStatus } from "./types/finding";
import type { LanguageQaDecisionIssue, LanguageQaFinding } from "./types/languageQa";

/** Always marked "languageQa", whatever the finding object carries: this is
 * what keeps the decision out of the review-progress rollup (decide_verse). */
export function languageQaDecisionIssue(finding: LanguageQaFinding): LanguageQaDecisionIssue {
  return {
    source: "languageQa",
    rule: finding.rule,
    ruleVersion: finding.ruleVersion,
    originalText: finding.originalText,
    suggestedReplacement: finding.suggestedReplacement ?? null,
    message: finding.message,
    start: finding.start,
    end: finding.end,
  };
}

/** Record a decision on a Language QA finding. Unlike decideLocalFinding it
 * touches no QaFinding store: these findings live in languageQaFindingsByVerse. */
export function decideLanguageQaFinding(
  finding: LanguageQaFinding,
  status: "accepted" | "ignored",
): Promise<Record<string, unknown>> {
  return bridge.decideVerse(finding.chapter, finding.verse, finding.id, status, undefined,
    languageQaDecisionIssue(finding));
}

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
