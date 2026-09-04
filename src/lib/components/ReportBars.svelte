<script context="module" lang="ts">
  export interface BarSegment {
    key: string;
    label: string;
    value: number;
    color: string;
  }

  export interface BarRow {
    key: string;
    label: string;
    /** Secondary text under the label, e.g. "verses" or "checks". */
    sublabel?: string;
    segments: BarSegment[];
  }
</script>

<script lang="ts">
  /**
   * Horizontal stacked bars for the QA report — one row per category or
   * check family, segments separated by a 2px surface gap, the total at the
   * tip of each bar, a legend for the segments, and a native tooltip per
   * segment. Thin (14px) marks on a recessive track; the numbers live in
   * the legend/tooltips/total rather than on every segment.
   */
  export let title: string;
  export let rows: BarRow[] = [];
  export let legend: Array<{ key: string; label: string; color: string }> = [];

  $: max = Math.max(1, ...rows.map((row) => row.segments.reduce((sum, s) => sum + s.value, 0)));

  function total(row: BarRow): number {
    return row.segments.reduce((sum, s) => sum + s.value, 0);
  }
</script>

<figure class="bars" aria-label={title}>
  <figcaption>{title}</figcaption>
  <div class="rows" role="table" aria-label={title}>
    {#each rows as row (row.key)}
      {@const rowTotal = total(row)}
      <div class="row" role="row">
        <div class="label" role="rowheader">
          <span>{row.label}</span>
          {#if row.sublabel}<small>{row.sublabel}</small>{/if}
        </div>
        <div class="track" role="cell" aria-label="{row.label}: {rowTotal}">
          {#each row.segments as segment (segment.key)}
            {#if segment.value > 0}
              <div
                class="segment"
                style="width:{(segment.value / max) * 100}%; background:{segment.color}"
                title="{row.label} — {segment.label}: {segment.value}"
              />
            {/if}
          {/each}
        </div>
        <div class="total" role="cell">{rowTotal}</div>
      </div>
    {/each}
  </div>
  {#if legend.length > 0}
    <ul class="legend">
      {#each legend as entry (entry.key)}
        <li><i style="background:{entry.color}" />{entry.label}</li>
      {/each}
    </ul>
  {/if}
</figure>

<style>
  .bars { margin: 0; min-width: 0; }
  figcaption { font-size: 11px; font-weight: 700; color: var(--text); margin-bottom: 8px; }
  .rows { display: flex; flex-direction: column; gap: 7px; }
  .row { display: grid; grid-template-columns: 92px 1fr 34px; align-items: center; gap: 8px; }
  .label { display: flex; flex-direction: column; min-width: 0; font-size: 10px; color: var(--text-2); font-weight: 600; }
  .label span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .label small { font-size: 9px; font-weight: 500; color: var(--text-3); }
  .track { display: flex; height: 14px; background: var(--surface-2); border-radius: 4px; overflow: hidden; min-width: 0; }
  .segment { height: 100%; flex-shrink: 0; box-sizing: border-box; border-right: 2px solid var(--surface); }
  .segment:last-child { border-right: 0; border-top-right-radius: 4px; border-bottom-right-radius: 4px; }
  .total { font-size: 10px; font-weight: 700; color: var(--text); text-align: right; font-variant-numeric: tabular-nums; }
  .legend { list-style: none; margin: 8px 0 0; padding: 0; display: flex; flex-wrap: wrap; gap: 4px 12px; font-size: 10px; color: var(--text-2); }
  .legend li { display: inline-flex; align-items: center; gap: 5px; }
  .legend i { width: 8px; height: 8px; border-radius: 2px; display: inline-block; }
</style>
