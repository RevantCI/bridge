<script lang="ts">
  /**
   * A status pill for review state.
   *
   * Status is never conveyed by colour alone: every tone carries both a
   * Unicode glyph and its own text, so the badge still reads correctly in
   * greyscale, at high contrast, and to a screen reader. Unicode rather than
   * an icon font on purpose - an offline PyInstaller build cannot reach a CDN
   * font and icon-only controls would render as empty boxes.
   */
  import type { BadgeTone } from "../types/qaReview";

  export let label: string;
  export let tone: BadgeTone = "neutral";
  /** Optional longer text for assistive tech, when the label is terse. */
  export let title = "";

  const GLYPH: Record<BadgeTone, string> = {
    possible: "?",
    confirmed: "!",
    acceptable: "✓",
    rejected: "✗",
    discussion: "…",
    stale: "↻",
    neutral: "·",
  };
</script>

<span class="badge tone-{tone}" title={title || label}>
  <span class="glyph" aria-hidden="true">{GLYPH[tone]}</span>
  <span class="label">{label}</span>
</span>

<style>
  .badge {
    display: inline-flex;
    align-items: center;
    gap: 0.3em;
    padding: 0.1em 0.5em;
    border-radius: 999px;
    border: 1px solid currentColor;
    font-size: 0.75rem;
    line-height: 1.5;
    white-space: nowrap;
    max-width: 100%;
  }

  .glyph {
    font-weight: 700;
    /* Keeps the glyph column steady so badges align in a list. */
    min-width: 0.75em;
    text-align: center;
  }

  .label {
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .tone-possible { color: #8a6100; background: #fff8e6; }
  .tone-confirmed { color: #9b1c1c; background: #fdeaea; }
  .tone-acceptable { color: #1a6b3c; background: #eafaf954; }
  .tone-rejected { color: #4b5563; background: #f3f4f6; }
  .tone-discussion { color: #1e40af; background: #eef2ff; }
  .tone-stale { color: #5b4a1f; background: #f5f0e1; }
  .tone-neutral { color: #4b5563; background: #f9fafb; }
</style>
