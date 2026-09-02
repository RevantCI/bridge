import type {
  BadgeTone,
  LifecycleStatus,
  LocationOutcome,
  MeaningStatus,
  QaDisposition,
  QaFindingSeverity,
  ReviewStatus,
} from "../types/qaReview";

/**
 * Reviewer-facing wording for machine analysis.
 *
 * Everything Stage 8 produces is a possibility until a human says otherwise,
 * so these labels say "Possible omission", never "Error" or "Wrong
 * translation". The confirmed forms exist because a reviewer can promote a
 * finding explicitly, and only then.
 */
const FINDING_KIND_LABELS: Record<string, string> = {
  POSSIBLY_MISSING: "Possibly missing",
  MISSING: "Missing (confirmed)",
  POSSIBLY_UNSUPPORTED: "Possibly unsupported",
  UNSUPPORTED: "Unsupported (confirmed)",
  RESOURCE_CONFLICT: "Resource conflict",
  NEEDS_PASSAGE_REVIEW: "Needs passage review",
  NEEDS_EXTENDED_PASSAGE_REVIEW: "Needs extended passage review",
  POSSIBLE_OMISSION: "Possible omission",
  POSSIBLE_ADDITION: "Possible unsupported addition",
  POSSIBLE_UNDERTRANSLATION: "Possible undertranslation",
  POSSIBLE_OVERTRANSLATION: "Possible overtranslation",
  MEANING_SHIFT: "Possible meaning shift",
  CONTRADICTION: "Possible contradiction",
  NEGATION_PROBLEM: "Possible negation problem",
  QUANTITY_PROBLEM: "Possible quantity problem",
  TEMPORAL_PROBLEM: "Possible temporal problem",
  PARTICIPANT_PROBLEM: "Possible participant problem",
  REFERENT_PROBLEM: "Possible referent problem",
  SOURCE_VARIANT_REVIEW: "Source variant review",
};

const DISPOSITION_LABELS: Record<QaDisposition, string> = {
  UNRESOLVED: "Not yet reviewed",
  CONFIRMED_TRANSLATION_ERROR: "Confirmed translation issue",
  ACCEPTABLE_TRANSLATION: "Accepted as correct",
  FALSE_POSITIVE: "False positive",
  NEEDS_DISCUSSION: "Needs discussion",
  CORRECTED: "Corrected",
};

const DISPOSITION_TONES: Record<QaDisposition, BadgeTone> = {
  UNRESOLVED: "possible",
  CONFIRMED_TRANSLATION_ERROR: "confirmed",
  ACCEPTABLE_TRANSLATION: "acceptable",
  FALSE_POSITIVE: "rejected",
  NEEDS_DISCUSSION: "discussion",
  CORRECTED: "acceptable",
};

const REVIEW_STATUS_LABELS: Record<ReviewStatus, string> = {
  UNREVIEWED: "Unreviewed",
  // Deliberately not "AI proposed": Stages 6B-8 are deterministic and no
  // language model is involved. This marks machine-proposed, not AI-written.
  AI_PROPOSED: "Machine-proposed",
  HUMAN_APPROVED: "Reviewed",
  HUMAN_REJECTED: "Rejected by reviewer",
  HUMAN_MODIFIED: "Modified by reviewer",
  NEEDS_DISCUSSION: "Needs discussion",
};

const LIFECYCLE_LABELS: Record<LifecycleStatus, string> = {
  ACTIVE: "Active",
  INACTIVE: "Inactive",
  STALE: "Stale",
  SUPERSEDED: "Superseded",
  QUARANTINED: "Quarantined",
};

const LOCATION_OUTCOME_LABELS: Record<LocationOutcome, string> = {
  LOCATED: "Located",
  AMBIGUOUS: "Ambiguous",
  NOT_LOCATED: "Not located",
  SEARCH_INCOMPLETE: "Search incomplete",
  UNSUPPORTED_ANALYSIS: "Analysis unsupported",
};

/**
 * What each location outcome means for the reviewer's next move. NOT_LOCATED
 * and SEARCH_INCOMPLETE look similar but are not: one is a finding about the
 * translation, the other is a gap in Bridge's own search.
 */
const LOCATION_OUTCOME_HELP: Record<LocationOutcome, string> = {
  LOCATED: "Bridge believes this is where the source meaning was translated.",
  AMBIGUOUS: "Several target expressions competed and none won clearly. Check the alternatives.",
  NOT_LOCATED: "Bridge found no target expression carrying this source meaning.",
  SEARCH_INCOMPLETE: "Bridge did not finish searching this passage, so absence here proves nothing.",
  UNSUPPORTED_ANALYSIS: "Bridge cannot analyse this construction, so it reached no conclusion.",
};

const MEANING_STATUS_LABELS: Record<MeaningStatus, string> = {
  PRESERVED: "Preserved",
  PRESERVED_WITH_RESTRUCTURING: "Preserved, restructured",
  PARTIAL: "Partially preserved",
  OVERTRANSLATED: "Overtranslated",
  UNDERTRANSLATED: "Undertranslated",
  MEANING_SHIFT: "Meaning shift",
  CONTRADICTED: "Contradicted",
  UNVERIFIABLE: "Unverifiable",
};

const COVERAGE_LABELS: Record<string, string> = {
  NOT_CHECKED: "Not checked",
  COVERED: "Covered",
  COVERED_BY_RESTRUCTURING: "Covered by restructuring",
  POSSIBLY_MISSING: "Possibly missing",
  MISSING: "Missing (confirmed by a reviewer)",
  UNCERTAIN: "Uncertain",
  SOURCE_SUPPORTED: "Supported by the source",
  CONTEXT_SUPPORTED: "Supported by context",
  GRAMMATICALLY_REQUIRED: "Required by target grammar",
  EXPLICITATION_SUPPORTED: "Defensible explicitation",
  POSSIBLY_UNSUPPORTED: "Possibly unsupported",
  UNSUPPORTED: "Unsupported (confirmed by a reviewer)",
};

/**
 * Why an apparent extra word may be perfectly correct. Shown alongside the
 * status so a reviewer is not nudged toward treating every addition as a
 * fault.
 */
const COVERAGE_HELP: Record<string, string> = {
  COVERED_BY_RESTRUCTURING:
    "The meaning is present, carried by a different construction than the source uses.",
  GRAMMATICALLY_REQUIRED:
    "The target language requires this word; it has no separate source counterpart and needs none.",
  EXPLICITATION_SUPPORTED:
    "This makes something explicit that the source left implicit — normal, defensible translation.",
  CONTEXT_SUPPORTED: "The surrounding passage supports this, even without a direct source word.",
  POSSIBLY_MISSING: "Bridge found no counterpart, but has not confirmed anything is wrong.",
  POSSIBLY_UNSUPPORTED: "Bridge found no source basis, but has not confirmed anything is wrong.",
};

const SEVERITY_LABELS: Record<QaFindingSeverity, string> = {
  CRITICAL: "Critical",
  HIGH: "High",
  MEDIUM: "Medium",
  LOW: "Low",
  INFO: "Info",
};

const REALIZATION_LABELS: Record<string, string> = {
  LEXICALLY_REALIZED: "Translated as a word",
  GRAMMATICALLY_REALIZED: "Carried by grammar",
  PRONOMINALIZED: "Rendered as a pronoun",
  IMPLICIT: "Left implicit",
  NOT_LOCATED: "Not located",
  UNCERTAIN: "Uncertain",
};

const PROPERTY_LABELS: Record<string, string> = {
  SPLIT: "Split across expressions",
  MERGED: "Merged with another",
  CROSS_VERSE: "Realized in another verse",
  REORDERED: "Reordered",
  DISCONTIGUOUS: "Discontiguous",
  EXPLICITATED: "Made explicit",
  CLAUSE_RESTRUCTURED: "Clause restructured",
  IDIOMATIC_REALIZATION: "Idiomatic rendering",
  VERSIFICATION_DIFFERENCE: "Versification difference",
};

function humanize(value: string): string {
  if (!value) return "";
  const spaced = value.replace(/_/g, " ").toLowerCase();
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

export function findingKindLabel(kind: string): string {
  return FINDING_KIND_LABELS[kind] ?? humanize(kind);
}

export function dispositionLabel(value: QaDisposition): string {
  return DISPOSITION_LABELS[value] ?? humanize(value);
}

export function dispositionTone(value: QaDisposition): BadgeTone {
  return DISPOSITION_TONES[value] ?? "neutral";
}

export function reviewStatusLabel(value: ReviewStatus): string {
  return REVIEW_STATUS_LABELS[value] ?? humanize(value);
}

export function lifecycleLabel(value: LifecycleStatus): string {
  return LIFECYCLE_LABELS[value] ?? humanize(value);
}

export function locationOutcomeLabel(value: LocationOutcome | string): string {
  return LOCATION_OUTCOME_LABELS[value as LocationOutcome] ?? humanize(String(value));
}

export function locationOutcomeHelp(value: LocationOutcome | string): string {
  return LOCATION_OUTCOME_HELP[value as LocationOutcome] ?? "";
}

export function meaningStatusLabel(value: MeaningStatus | string): string {
  return MEANING_STATUS_LABELS[value as MeaningStatus] ?? humanize(String(value));
}

export function coverageLabel(value: string): string {
  return COVERAGE_LABELS[value] ?? humanize(value);
}

export function coverageHelp(value: string): string {
  return COVERAGE_HELP[value] ?? "";
}

export function severityLabel(value: QaFindingSeverity | string): string {
  return SEVERITY_LABELS[value as QaFindingSeverity] ?? humanize(String(value));
}

export function realizationLabel(value: string): string {
  return REALIZATION_LABELS[value] ?? humanize(value);
}

export function propertyLabel(value: string): string {
  return PROPERTY_LABELS[value] ?? humanize(value);
}

export function componentStatusLabel(value: string): string {
  return humanize(value);
}

/**
 * Severity orders the queue; it never means the issue is real.
 * Callers use this for the tooltip so styling cannot imply otherwise.
 */
export const SEVERITY_IS_PRIORITY_ONLY =
  "Severity sets review order only. It does not mean the issue is confirmed.";

/** The four conclusions a reviewer may reach, in the order they are offered. */
export const REVIEWER_ACTIONS = [
  {
    disposition: "CONFIRMED_TRANSLATION_ERROR" as const,
    label: "Confirm translation issue",
    hint: "The translation has a real problem here.",
  },
  {
    disposition: "ACCEPTABLE_TRANSLATION" as const,
    label: "Accept translation as correct",
    hint: "The difference is legitimate — idiom, grammar, restructuring or explicitation.",
  },
  {
    disposition: "FALSE_POSITIVE" as const,
    label: "False positive",
    hint: "Bridge should not have raised this at all.",
  },
  {
    disposition: "NEEDS_DISCUSSION" as const,
    label: "Needs discussion",
    hint: "Defer this for the team to decide.",
  },
];
