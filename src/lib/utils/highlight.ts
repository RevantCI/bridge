import type { AiCheckReview, QaFinding, FindingCategory, NativeCheckReview } from "../types/finding";

// Category -> CSS class matching the four-colour finding-source legend in
// index.css (tN red, tW blue, Alignment amber, everything else = Greek Room
// green). The same classes/tokens colour the review panel, so an underline in
// the verse and its entry in the panel always agree on what found it.
export function categoryClass(category: FindingCategory): string {
  switch (category) {
    case "translation_note": return "m-tn";
    case "translation_word": return "m-tw";
    case "alignment": return "m-align";
    default: return "m-gr"; // unicode, spelling, names, repetition, consistency, structure, omission_addition
  }
}

export interface TextSegment {
  text: string;
  findingIds: string[];
  className: string | null;
  title: string;
  numbers: number[];
}

/**
 * Deterministic 1-based numbering, in verse reading order, for findings
 * anchored to an exact word/phrase span — the same cross-reference-style
 * marker shown both inline in the verse (buildSegments) and next to each
 * finding in ReviewPanel, so a reader can spot which highlighted word a
 * list entry refers to without hunting for it. Findings with no span
 * (most tN/tW/alignment QAIssues — verse-level, not word-level) aren't
 * numbered, matching buildSegments' own existing offset filter. Callers
 * must pass the same verse's finding list to both sides for the numbers
 * to line up — true today since ReviewPanel's $selectedFindings and
 * VerseList's findingsByVerse[key] both read the exact same store entry.
 */
export function findingNumbers(findings: QaFinding[]): Map<string, number> {
  const spanned = findings
    .filter((f) => f.start_offset !== null && f.end_offset !== null)
    .sort((a, b) => (a.start_offset! - b.start_offset!) || a.id.localeCompare(b.id));
  const numbers = new Map<string, number>();
  spanned.forEach((f, index) => numbers.set(f.id, index + 1));
  return numbers;
}

export interface ExactTextRange {
  start: number;
  end: number;
}

/** Exact, non-overlapping occurrences matching the native tC occurrence model. */
export function exactTextRanges(text: string, selectedText: string): ExactTextRange[] {
  if (!selectedText) return [];
  const ranges: ExactTextRange[] = [];
  let from = 0;
  while (from <= text.length - selectedText.length) {
    const start = text.indexOf(selectedText, from);
    if (start < 0) break;
    const end = start + selectedText.length;
    ranges.push({ start, end });
    from = end;
  }
  return ranges;
}

interface ReviewSpan extends ExactTextRange {
  id: string;
  className: string;
  title: string;
  number?: number;
}

/**
 * Splits verse text into segments based on findings' start/end offsets.
 * Findings without offsets (most tc_ai_bridge QAIssues — they're
 * verse-level, not span-level) don't produce an inline highlight; they
 * still show up in the review panel, just not underlined in the text.
 * Overlapping spans are merged conservatively (first-match-wins per
 * character) rather than attempting nested/stacked highlighting.
 */
export function buildSegments(
  text: string,
  findings: QaFinding[],
  nativeChecks: NativeCheckReview[] = [],
  aiReviews: AiCheckReview[] = [],
): TextSegment[] {
  const numbers = findingNumbers(findings);
  const spans: ReviewSpan[] = findings
    .filter((f) => f.start_offset !== null && f.end_offset !== null && f.end_offset! <= text.length)
    .map((finding) => ({
      start: finding.start_offset!, end: finding.end_offset!, id: finding.id,
      className: categoryClass(finding.category), title: finding.explanation,
      number: numbers.get(finding.id),
    }));

  for (const check of nativeChecks) {
    const className = check.tool === "translationNotes" ? "m-tn" : "m-tw";
    const label = check.tool === "translationNotes" ? "Translation Note" : "Translation Word";
    const detail = [
      `${label}: ${check.groupId || check.checkId}`,
      check.sourceQuote ? `Source: ${check.sourceQuote}` : "",
      check.occurrenceNote,
      `Selection: ${check.selectionStatus.replaceAll("_", " ")}`,
    ].filter(Boolean).join("\n");
    for (const selection of check.selections) {
      const ranges = exactTextRanges(text, selection.text);
      const range = ranges[selection.occurrence - 1];
      if (range && ranges.length === selection.occurrences) {
        spans.push({ ...range, id: check.checkId, className, title: detail });
      }
    }
  }

  // Only AI reviews that actually flag something get underlined. A tN/tW check
  // the AI passed is not an issue, and underlining every check it looked at
  // would light up most of the verse and make the marks meaningless as a
  // problem signal. "not_applicable" is likewise not a finding.
  //
  // New AI reviews carry exact translationCore occurrence metadata. Older cached
  // reviews fall back to unique-text matching rather than guessing a repeated span.
  for (const review of aiReviews) {
    if (review.verdict !== "problem" && review.verdict !== "review") continue;
    const className = review.tool === "translationNotes" ? "m-tn" : "m-tw";
    const evidence = review.evidence_used
      .map((item) => String(item.title ?? item.identifier ?? item.kind ?? ""))
      .filter(Boolean)
      .join(", ");
    const title = [`AI proposal: ${review.rationale}`, evidence ? `Evidence: ${evidence}` : ""]
      .filter(Boolean).join("\n");
    if ((review.proposed_selections ?? []).length > 0) {
      for (const selection of review.proposed_selections) {
        const ranges = exactTextRanges(text, selection.text);
        const range = ranges[selection.occurrence - 1];
        if (range && ranges.length === selection.occurrences) {
          spans.push({ ...range, id: review.check_id, className, title });
        }
      }
    } else {
      for (const proposedText of review.proposed_selection_text) {
        const ranges = exactTextRanges(text, proposedText);
        if (ranges.length === 1) {
          spans.push({ ...ranges[0], id: review.check_id, className, title });
        }
      }
    }
  }

  if (spans.length === 0) {
    return [{ text, findingIds: [], className: null, title: "", numbers: [] }];
  }

  const boundaries = new Set<number>([0, text.length]);
  spans.forEach((span) => {
    boundaries.add(span.start);
    boundaries.add(span.end);
  });
  const points = Array.from(boundaries).sort((a, b) => a - b);

  const segments: TextSegment[] = [];
  for (let i = 0; i < points.length - 1; i++) {
    const start = points[i];
    const end = points[i + 1];
    const covering = spans.filter((span) => span.start <= start && span.end >= end);
    const classes = Array.from(new Set(covering.map((span) => span.className)));
    segments.push({
      text: text.slice(start, end),
      findingIds: Array.from(new Set(covering.map((span) => span.id))),
      className: classes.length > 0 ? classes.join(" ") : null,
      title: Array.from(new Set(covering.map((span) => span.title).filter(Boolean))).join("\n\n"),
      numbers: Array.from(new Set(
        covering.map((span) => span.number).filter((n): n is number => n !== undefined),
      )).sort((a, b) => a - b),
    });
  }
  return segments;
}
