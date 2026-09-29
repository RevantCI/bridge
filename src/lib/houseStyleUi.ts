// House style in the UI (layered-rules 6.3/6.4): the scoped Ignore choices,
// and the one-line "Learned ... Undo" notice the learner's decision answer
// carries. The notice lives for the session; Undo writes a superseding state
// (never a delete), and the learner does not learn that pair again.
import { writable } from "svelte/store";
import { bridge } from "./api/bridgeClient";
import { nudgeLanguageQa } from "./languageQaInline";
import type { HouseStyleEntry, HouseStyleScope } from "./types/houseStyle";
import type { LanguageQaFinding } from "./types/languageQa";

export const houseStyleNotice = writable<HouseStyleEntry | null>(null);

export const IGNORE_SCOPES: Array<{ scope: HouseStyleScope | "occurrence"; label: string; title: string }> = [
  { scope: "occurrence", label: "This occurrence", title: "Ignore only this occurrence." },
  { scope: "word-in-book", label: "This word in this book", title: "Never flag this text for this rule in this book." },
  { scope: "word-in-project", label: "This word in the project", title: "Never flag this text for this rule in any book of the project." },
  { scope: "rule-in-book", label: "This rule in this book", title: "Stop this rule for this book." },
  { scope: "rule-in-project", label: "This rule in the project", title: "Stop this rule in every book of the project." },
];

/** Record a scoped Ignore as house style (provenance explicit), with the
 * finding as evidence. The occurrence itself is decided separately. */
export async function recordScopedIgnore(finding: LanguageQaFinding, scope: HouseStyleScope): Promise<void> {
  const byWord = scope.startsWith("word");
  await bridge.housestyleRecord({
    scope, ruleId: finding.ruleId, word: byWord ? finding.originalText : "", provenance: "explicit",
    evidence: [{ chapter: finding.chapter, verse: finding.verse, decisionId: finding.id }],
  });
  nudgeLanguageQa();
}

/** A decision's answer may carry what the learner learned from it. */
export function noticeLearned(result: Record<string, unknown> | undefined): void {
  const learned = (result?.houseStyle as { learned?: HouseStyleEntry } | undefined)?.learned;
  if (learned) houseStyleNotice.set(learned);
}

export async function undoLearned(entry: HouseStyleEntry): Promise<void> {
  houseStyleNotice.set(null);
  await bridge.housestyleSetState(entry.key, "undone");
  nudgeLanguageQa();
}
