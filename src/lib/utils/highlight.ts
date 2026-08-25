import type { AiCheckReview, QaFinding, FindingCategory, NativeCheckReview } from "../types/finding";

// Category -> CSS class matching the approved wireframe's four-color legend
// (tN purple, tW blue, Alignment amber, everything else = Greek Room teal).
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
  const spans: ReviewSpan[] = findings
    .filter((f) => f.start_offset !== null && f.end_offset !== null && f.end_offset! <= text.length)
    .map((finding) => ({
      start: finding.start_offset!, end: finding.end_offset!, id: finding.id,
      className: categoryClass(finding.category), title: finding.explanation,
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

  // AI proposal text has no occurrence metadata yet. Highlight only an exact,
  // unique match; repeated text remains in the card instead of guessing a span.
  for (const review of aiReviews) {
    const className = review.tool === "translationNotes" ? "m-tn" : "m-tw";
    for (const proposedText of review.proposed_selection_text) {
      const ranges = exactTextRanges(text, proposedText);
      if (ranges.length === 1) {
        const evidence = review.evidence_used
          .map((item) => String(item.title ?? item.identifier ?? item.kind ?? ""))
          .filter(Boolean)
          .join(", ");
        spans.push({
          ...ranges[0], id: review.check_id, className,
          title: [`AI proposal: ${review.rationale}`, evidence ? `Evidence: ${evidence}` : ""].filter(Boolean).join("\n"),
        });
      }
    }
  }

  if (spans.length === 0) {
    return [{ text, findingIds: [], className: null, title: "" }];
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
    });
  }
  return segments;
}
