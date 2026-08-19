import type { QaFinding, FindingCategory } from "../types/finding";

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
}

/**
 * Splits verse text into segments based on findings' start/end offsets.
 * Findings without offsets (most tc_ai_bridge QAIssues — they're
 * verse-level, not span-level) don't produce an inline highlight; they
 * still show up in the review panel, just not underlined in the text.
 * Overlapping spans are merged conservatively (first-match-wins per
 * character) rather than attempting nested/stacked highlighting.
 */
export function buildSegments(text: string, findings: QaFinding[]): TextSegment[] {
  const spanned = findings.filter(
    (f) => f.start_offset !== null && f.end_offset !== null && f.end_offset! <= text.length
  );
  if (spanned.length === 0) {
    return [{ text, findingIds: [], className: null }];
  }

  const boundaries = new Set<number>([0, text.length]);
  spanned.forEach((f) => {
    boundaries.add(f.start_offset!);
    boundaries.add(f.end_offset!);
  });
  const points = Array.from(boundaries).sort((a, b) => a - b);

  const segments: TextSegment[] = [];
  for (let i = 0; i < points.length - 1; i++) {
    const start = points[i];
    const end = points[i + 1];
    const covering = spanned.filter((f) => f.start_offset! <= start && f.end_offset! >= end);
    segments.push({
      text: text.slice(start, end),
      findingIds: covering.map((f) => f.id),
      className: covering.length > 0 ? categoryClass(covering[0].category) : null,
    });
  }
  return segments;
}
