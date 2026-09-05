export type DiffKind = "unchanged" | "removed" | "inserted";

export interface DiffPart {
  kind: DiffKind;
  text: string;
}

function graphemes(text: string): string[] {
  const Segmenter = (Intl as unknown as {
    Segmenter?: new (locale?: string, options?: { granularity: "grapheme" }) => {
      segment(value: string): Iterable<{ segment: string }>;
    };
  }).Segmenter;
  if (Segmenter) {
    return Array.from(new Segmenter(undefined, { granularity: "grapheme" }).segment(text),
      (item) => item.segment);
  }
  // Array.from is code-point safe. The desktop WebView supports Intl.Segmenter;
  // this fallback prevents surrogate splitting on older test/web runtimes.
  return Array.from(text);
}

export function codePointIndexToUtf16(text: string, codePointIndex: number): number {
  if (!Number.isInteger(codePointIndex) || codePointIndex < 0) return 0;
  return Array.from(text).slice(0, codePointIndex).join("").length;
}

export function codePointSlice(text: string, start: number, end: number): string {
  return Array.from(text).slice(start, end).join("");
}

export function codePointLength(text: string): number {
  return Array.from(text).length;
}

export function graphemeBoundariesInCodePoints(text: string): number[] {
  const result = [0];
  let cursor = 0;
  for (const cluster of graphemes(text)) {
    cursor += codePointLength(cluster);
    result.push(cursor);
  }
  return result;
}

export function graphemeDiff(before: string, after: string): DiffPart[] {
  const left = graphemes(before);
  const right = graphemes(after);
  let prefix = 0;
  while (prefix < left.length && prefix < right.length && left[prefix] === right[prefix]) prefix += 1;
  let suffix = 0;
  while (
    suffix < left.length - prefix
    && suffix < right.length - prefix
    && left[left.length - 1 - suffix] === right[right.length - 1 - suffix]
  ) suffix += 1;

  const parts: DiffPart[] = [];
  const commonStart = left.slice(0, prefix).join("");
  const removed = left.slice(prefix, left.length - suffix).join("");
  const inserted = right.slice(prefix, right.length - suffix).join("");
  const commonEnd = suffix ? left.slice(left.length - suffix).join("") : "";
  if (commonStart) parts.push({ kind: "unchanged", text: commonStart });
  if (removed) parts.push({ kind: "removed", text: removed });
  if (inserted) parts.push({ kind: "inserted", text: inserted });
  if (commonEnd) parts.push({ kind: "unchanged", text: commonEnd });
  return parts;
}

export function visualContextSegments(
  text: string, startCodePoint: number, endCodePoint: number,
): { before: string; affected: string; after: string; insertion: boolean } {
  return {
    before: codePointSlice(text, 0, startCodePoint),
    affected: codePointSlice(text, startCodePoint, endCodePoint),
    after: codePointSlice(text, endCodePoint, codePointLength(text)),
    insertion: startCodePoint === endCodePoint,
  };
}
