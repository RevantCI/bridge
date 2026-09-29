import type { LanguageQaFinding, LanguageQaSuggestion } from "../../types/languageQa";

// Mirrors language_qa.RULES for the rules these tests use.
const RULES: Record<string, Pick<LanguageQaFinding, "layer" | "category" | "confidence"> & { pack: string; inline: boolean }> = {
  "tamil.vallinam-missing": { pack: "ta-irv", layer: "pattern", category: "sandhi", confidence: "medium", inline: true },
  "terminology.deprecated-form": { pack: "project", layer: "housestyle", category: "termbase", confidence: "high", inline: true },
  "tamil.wordlist-variant": { pack: "ta-irv", layer: "lexicon", category: "typo", confidence: "low", inline: false },
  "unicode.corruption": { pack: "common", layer: "integrity", category: "unicode", confidence: "high", inline: false },
  "spacing.extra": { pack: "common", layer: "integrity", category: "spacing", confidence: "medium", inline: false },
};

/**
 * A Language QA finding shaped as the engine sends it. The rule decides
 * layer, category, confidence, ruleId and inline, as language_qa.RULES does;
 * `suggestedReplacement` in the overrides becomes the single ranked
 * suggestion, as the engine's alias is derived.
 */
export function lqaFinding(overrides: Partial<LanguageQaFinding> = {}): LanguageQaFinding {
  const rule = overrides.rule ?? "tamil.vallinam-missing";
  const meta = RULES[rule] ?? RULES["tamil.vallinam-missing"];
  const replacement = "suggestedReplacement" in overrides ? overrides.suggestedReplacement ?? null : "அந்தக் காகம்";
  const suggestions: LanguageQaSuggestion[] = overrides.suggestions
    ?? (replacement ? [{ text: replacement, rank: 1, source: "rule", rationale: "test rationale" }] : []);
  return {
    id: "lqa-1", book: "php", chapter: "1", verse: "6", rule,
    severity: meta.category === "termbase" ? "high" : "medium",
    start: 0, end: Array.from("அந்த காகம்").length, originalText: "அந்த காகம்",
    message: "Possible missing வல்லினம்.", textHash: "h", ruleVersion: "language-qa-7",
    status: "review-needed", source: "languageQa",
    layer: meta.layer, category: meta.category, confidence: meta.confidence,
    ruleId: `${meta.pack}/${rule}`, packVersion: "language-qa-7", ruleRevision: 1, inline: meta.inline,
    ...overrides,
    suggestions,
    suggestedReplacement: suggestions[0]?.text ?? null,
  };
}
