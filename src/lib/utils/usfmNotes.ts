import type { TextSegment } from "./highlight";

/**
 * Lifts inline USFM footnotes/cross-references out of a verse so the reader
 * sees Scripture, with each note remembering the spot it came from.
 *
 * Scope is deliberately narrow: ONLY \f..\f* and \x..\x* are removed. Every
 * other marker — \it, \nd, \wj and the rest — is a styling tag and is left in
 * the text exactly as it was, to be rendered as styling later rather than
 * silently discarded here. That is narrower than the engine's strip_usfm(),
 * which also drops character markers; the two agree on what counts as a note,
 * which is the part that matters for locating them.
 *
 * The offset map exists because QaFinding.start_offset/end_offset index the
 * RAW verse string. bridge_service._first_token_span is explicit that it
 * computes against the raw text precisely so those offsets line up with what
 * the frontend highlights. Removing notes shortens the string, and
 * buildSegments drops any span whose end exceeds the text length — so without
 * remapping an underline does not shift, it vanishes. The clean string is
 * therefore built by deletion only, never rewriting or reordering, and every
 * raw index records where it landed.
 */

export type VerseNoteKind = "footnote" | "xref";

export interface VerseNotePart {
  /** USFM marker without its backslash, e.g. "fr", "fq", "ft", "xo", "xt". */
  marker: string;
  text: string;
}

export interface VerseNote {
  kind: VerseNoteKind;
  /** The caller glyph USFM puts right after \f / \x — usually "+". */
  caller: string;
  /** Verse reference from \fr (footnote) or \xo (xref), when present. */
  reference: string;
  parts: VerseNotePart[];
  /** Everything the note says, flattened, for a plain one-line rendering. */
  text: string;
  /** Offset into the CLEAN string where this note sat in the verse. */
  position: number;
}

export interface ParsedVerse {
  /** Reader-facing text: notes lifted out, all other markup untouched. */
  clean: string;
  /** Footnotes and cross-references together, in the order they appear. */
  notes: VerseNote[];
  footnotes: VerseNote[];
  xrefs: VerseNote[];
  /**
   * Maps a raw-string index onto the clean string. Indexes inside a removed
   * note collapse to the position the removal left behind, so a span that
   * lived entirely inside a note maps to a zero-length range — which covers
   * no segment rather than drawing an empty highlight.
   */
  mapOffset(rawOffset: number): number;
}

const NOTE_RE = /\\([fx])\s[\s\S]*?\\\1\*/g;

interface Removal {
  start: number;
  end: number;
  kind: VerseNoteKind;
  body: string;
}

/** Pulls `\fr 1.6 \fq quoted \ft body` apart into ordered marker/text pairs. */
function parseNoteBody(body: string, kind: VerseNoteKind, position: number): VerseNote {
  const trimmed = body.trim();
  // The caller is whatever sits before the first inner marker: "+", "-", "a"…
  const firstMarker = trimmed.search(/\\[A-Za-z0-9]/);
  const caller = (firstMarker === -1 ? trimmed : trimmed.slice(0, firstMarker)).trim();
  const rest = firstMarker === -1 ? "" : trimmed.slice(firstMarker);

  const parts: VerseNotePart[] = [];
  const pattern = /\\([A-Za-z0-9+_-]+)\*?\s*([\s\S]*?)(?=\\[A-Za-z0-9+_-]+\*?|$)/g;
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(rest)) !== null) {
    const text = match[2].trim();
    if (text) parts.push({ marker: match[1], text });
  }

  const referenceMarker = kind === "footnote" ? "fr" : "xo";
  const reference = parts.find((part) => part.marker === referenceMarker)?.text ?? "";

  return {
    kind,
    caller: caller || "+",
    reference,
    parts,
    position,
    text: parts
      .filter((part) => part.marker !== referenceMarker)
      .map((part) => part.text)
      .join(" ")
      .trim(),
  };
}

const isSpace = (char: string | undefined): boolean => char !== undefined && /\s/.test(char);

export function parseVerseNotes(raw: string): ParsedVerse {
  const removals: Removal[] = [];
  NOTE_RE.lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = NOTE_RE.exec(raw)) !== null) {
    removals.push({
      start: match.index,
      end: match.index + match[0].length,
      kind: match[1] === "f" ? "footnote" : "xref",
      // Body sits between the opening "\f " / "\x " and the closing "\f*" / "\x*".
      body: match[0].slice(3, -3),
    });
  }

  // Removing a note between two spaces would leave a double space behind.
  // Swallow exactly one, and nothing else — the rest of the verse's spacing
  // is left byte-identical.
  for (const removal of removals) {
    if (removal.start === 0 || isSpace(raw[removal.start - 1])) {
      if (isSpace(raw[removal.end])) removal.end += 1;
    } else if (removal.end === raw.length && isSpace(raw[removal.start - 1])) {
      removal.start -= 1;
    }
  }

  const removed = new Uint8Array(raw.length);
  for (const removal of removals) {
    for (let i = removal.start; i < removal.end; i++) removed[i] = 1;
  }

  let clean = "";
  const map = new Int32Array(raw.length + 1);
  for (let i = 0; i < raw.length; i++) {
    map[i] = clean.length;
    if (!removed[i]) clean += raw[i];
  }
  map[raw.length] = clean.length;

  const notes = removals.map((removal) =>
    parseNoteBody(removal.body, removal.kind, map[removal.start]),
  );

  return {
    clean,
    notes,
    footnotes: notes.filter((note) => note.kind === "footnote"),
    xrefs: notes.filter((note) => note.kind === "xref"),
    mapOffset(rawOffset: number): number {
      if (rawOffset <= 0) return 0;
      if (rawOffset >= raw.length) return clean.length;
      return map[rawOffset];
    },
  };
}

export type VersePiece =
  | { kind: "text"; seg: TextSegment }
  | { kind: "note"; note: VerseNote };

/**
 * Threads note markers back into the highlighted segments at the exact spot
 * each note was lifted from, splitting a segment when a note landed mid-span.
 */
export function withNoteMarkers(segments: TextSegment[], notes: VerseNote[]): VersePiece[] {
  const ordered = [...notes].sort((a, b) => a.position - b.position);
  const pieces: VersePiece[] = [];
  let noteIndex = 0;
  let offset = 0;

  for (const seg of segments) {
    const segStart = offset;
    const segEnd = offset + seg.text.length;
    let cursor = segStart;

    while (noteIndex < ordered.length && ordered[noteIndex].position <= segEnd) {
      const at = Math.max(ordered[noteIndex].position, segStart);
      if (at > cursor) {
        pieces.push({ kind: "text", seg: { ...seg, text: seg.text.slice(cursor - segStart, at - segStart) } });
        cursor = at;
      }
      pieces.push({ kind: "note", note: ordered[noteIndex] });
      noteIndex += 1;
    }

    if (cursor < segEnd) {
      pieces.push({ kind: "text", seg: { ...seg, text: seg.text.slice(cursor - segStart) } });
    }
    offset = segEnd;
  }

  while (noteIndex < ordered.length) {
    pieces.push({ kind: "note", note: ordered[noteIndex] });
    noteIndex += 1;
  }
  return pieces;
}
