import { bridge } from "./api/bridgeClient";
import { nudgeLanguageQa } from "./languageQaInline";
import { findingsByVerse, languageQaFindingsByVerse, verseKey } from "./stores";
import type { FindingStatus } from "./types/finding";
import type { LanguageQaDecisionIssue, LanguageQaFinding, LanguageQaSuggestion } from "./types/languageQa";

/** A Language QA decision: "accepted" (a Use), "ignored", or "rejected"
 * (marked as a false positive). */
export type LanguageQaDecision = "accepted" | "ignored" | "rejected";

/** What the reviewer saw and chose, recorded in the decision payload. `source`
 * is always "languageQa", whatever the finding object carries: decide_verse
 * counts it in the review-progress rollup only once a check job's Language QA
 * stage has reported that finding (layered-rules 4.1). The pack version and
 * rule revision are what let a later rule change expire an "ignored"
 * (language_qa_jobs.decision_effect). */
export function languageQaDecisionIssue(
  finding: LanguageQaFinding,
  chosen: LanguageQaSuggestion | null = null,
): LanguageQaDecisionIssue {
  return {
    source: "languageQa",
    rule: finding.rule,
    ruleId: finding.ruleId,
    ruleVersion: finding.ruleVersion,
    packVersion: finding.packVersion,
    ruleRevision: finding.ruleRevision,
    layer: finding.layer,
    category: finding.category,
    originalText: finding.originalText,
    suggestedReplacement: chosen?.text ?? finding.suggestions?.[0]?.text ?? finding.suggestedReplacement ?? null,
    chosenSuggestion: chosen?.text ?? null,
    chosenRank: chosen?.rank ?? null,
    message: finding.message,
    start: finding.start,
    end: finding.end,
  };
}

/** Record a decision on a Language QA finding. Unlike decideLocalFinding it
 * touches no QaFinding store: these findings live in languageQaFindingsByVerse. */
export function decideLanguageQaFinding(
  finding: LanguageQaFinding,
  status: LanguageQaDecision,
  chosen: LanguageQaSuggestion | null = null,
): Promise<Record<string, unknown>> {
  return bridge.decideVerse(finding.chapter, finding.verse, finding.id, status, undefined,
    languageQaDecisionIssue(finding, chosen)).then((result) => {
    nudgeLanguageQa();  // the decision started a new pass
    return result;
  });
}

/**
 * Ignore or mark as false positive, without the click waiting on the engine:
 * the mark leaves the store at once, the decision is sent afterwards, and the
 * mark is put back only if recording fails. Resolves to an error message, or
 * "" on success. The next scan independently confirms the suppression
 * (language_qa_jobs reads the same decision back).
 */
export function decideLanguageQaFindingOptimistically(
  finding: LanguageQaFinding,
  status: "ignored" | "rejected",
): Promise<string> {
  const key = verseKey(finding.chapter, finding.verse);
  languageQaFindingsByVerse.update((map) =>
    key in map ? { ...map, [key]: map[key].filter((f) => f.id !== finding.id) } : map);
  return decideLanguageQaFinding(finding, status).then(
    () => "",
    (error: unknown) => {
      languageQaFindingsByVerse.update((map) => {
        const current = map[key] ?? [];
        if (current.some((f) => f.id === finding.id)) return map;
        return { ...map, [key]: [...current, finding].sort((a, b) => a.start - b.start) };
      });
      return error instanceof Error ? error.message : String(error);
    },
  );
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
