<script context="module" lang="ts">
  export interface DonutSlice {
    key: string;
    label: string;
    value: number;
    color: string;
  }
</script>

<script lang="ts">
  /**
   * Part-to-whole donut for the QA report: at most a handful of slices, a
   * hero number in the middle, and a legend that carries every identity and
   * value in text — the ring is never the only way to read it. Slices are
   * separated by a 2px surface gap and each carries a native tooltip.
   */
  export let title: string;
  export let slices: DonutSlice[] = [];
  export let centerLabel = "";

  const RADIUS = 44;
  const STROKE = 13;
  const SIZE = (RADIUS + STROKE) * 2;
  const CIRCUMFERENCE = 2 * Math.PI * RADIUS;
  const GAP = 2;

  $: total = slices.reduce((sum, slice) => sum + slice.value, 0);
  $: visible = slices.filter((slice) => slice.value > 0);
  // Each arc is drawn with stroke-dasharray on a full circle, rotated to its
  // start; the gap comes off the arc's own length so slices never touch.
  $: arcs = visible.reduce<Array<DonutSlice & { length: number; offset: number; percent: number }>>((acc, slice) => {
    const previous = acc.length ? acc[acc.length - 1] : null;
    const offset = previous ? previous.offset + previous.length : 0;
    const length = (slice.value / total) * CIRCUMFERENCE;
    acc.push({ ...slice, length, offset, percent: Math.round((slice.value / total) * 100) });
    return acc;
  }, []);

  function dash(length: number): string {
    const drawn = Math.max(0, length - (visible.length > 1 ? GAP : 0));
    return `${drawn} ${CIRCUMFERENCE - drawn}`;
  }
</script>

<figure class="donut" aria-label={title}>
  <figcaption>{title}</figcaption>
  <div class="body">
    <svg viewBox="0 0 {SIZE} {SIZE}" width={SIZE} height={SIZE} role="img" aria-label="{title}: {total}">
      <circle class="track" cx={SIZE / 2} cy={SIZE / 2} r={RADIUS} stroke-width={STROKE} fill="none" />
      {#each arcs as arc (arc.key)}
        <circle
          cx={SIZE / 2} cy={SIZE / 2} r={RADIUS} fill="none"
          stroke={arc.color} stroke-width={STROKE}
          stroke-dasharray={dash(arc.length)}
          stroke-dashoffset={-arc.offset}
          transform="rotate(-90 {SIZE / 2} {SIZE / 2})"
        >
          <title>{arc.label}: {arc.value} ({arc.percent}%)</title>
        </circle>
      {/each}
      <text class="hero" x="50%" y="50%" text-anchor="middle" dominant-baseline="central">{total}</text>
      {#if centerLabel}
        <text class="hero-label" x="50%" y={SIZE / 2 + 17} text-anchor="middle">{centerLabel}</text>
      {/if}
    </svg>
    <ul class="legend">
      {#each slices as slice (slice.key)}
        <li class:zero={slice.value === 0}>
          <i style="background:{slice.color}" />
          <span class="label">{slice.label}</span>
          <span class="value">{slice.value}</span>
          <span class="pct">{total ? Math.round((slice.value / total) * 100) : 0}%</span>
        </li>
      {/each}
    </ul>
  </div>
</figure>

<style>
  .donut { margin: 0; min-width: 0; }
  figcaption { font-size: 11px; font-weight: 700; color: var(--text); margin-bottom: 8px; }
  .body { display: flex; align-items: center; gap: 14px; }
  svg { flex-shrink: 0; }
  .track { stroke: var(--surface-2); }
  .hero { font-size: 22px; font-weight: 650; fill: var(--text); }
  .hero-label { font-size: 8px; fill: var(--text-3); font-weight: 600; letter-spacing: .04em; text-transform: uppercase; }
  .legend { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 4px; min-width: 0; flex: 1; }
  .legend li { display: grid; grid-template-columns: 8px 1fr auto auto; align-items: center; gap: 7px; font-size: 10px; color: var(--text-2); }
  .legend li.zero { opacity: .55; }
  .legend i { width: 8px; height: 8px; border-radius: 2px; display: inline-block; }
  .legend .label { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .legend .value { font-weight: 700; color: var(--text); font-variant-numeric: tabular-nums; }
  .legend .pct { color: var(--text-3); font-variant-numeric: tabular-nums; width: 30px; text-align: right; }
</style>
