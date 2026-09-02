<script lang="ts">
  import ReviewStatusBadge from "./ReviewStatusBadge.svelte";
  import type { QaFindingDetail } from "../types/qaReview";
  import {
    coverageHelp,
    coverageLabel,
    componentStatusLabel,
    locationOutcomeHelp,
    locationOutcomeLabel,
    meaningStatusLabel,
    propertyLabel,
    realizationLabel,
  } from "../utils/reviewLabels";

  /**
   * Evidence in layers, not one generated explanation.
   *
   * The layering is the point: LOCATION answers "did Bridge look in the right
   * place?" and MEANING answers "given it looked in the right place, does the
   * meaning survive?". Collapsing them into a single verdict would hide the
   * difference between a mapping problem and a translation problem, which
   * need different review actions.
   */
  export let detail: QaFindingDetail;

  /** Advanced source internals stay folded away until asked for. */
  let showSourceInternals = false;

  function text(value: unknown, fallback = "—"): string {
    if (value === null || value === undefined || value === "") return fallback;
    return String(value);
  }

  function list(value: unknown): string[] {
    return Array.isArray(value) ? value.map((item) => String(item)) : [];
  }

  $: locations = detail.location ?? [];
  $: meanings = detail.meaning ?? [];
  $: coverage = detail.coverage ?? [];
  $: resources = [
    ...(detail.resources ?? []),
    ...(detail.supportingEvidence ?? []),
    ...(detail.conflictingEvidence ?? []),
  ];
  $: conflictingIds = new Set((detail.conflictingEvidence ?? []).map((item) => item.id));

  /**
   * Whether the reviewer is looking at a mapping problem or a translation
   * problem. Stated explicitly because the two require different actions.
   */
  $: mappingCertain = locations.length > 0
    && locations.every((entry) => entry.location?.locationOutcome === "LOCATED");
  $: mappingUnclear = locations.some((entry) =>
    ["AMBIGUOUS", "SEARCH_INCOMPLETE", "UNSUPPORTED_ANALYSIS"].includes(
      String(entry.location?.locationOutcome),
    ),
  );
</script>

<div class="inspector">
  {#if detail.isStale}
    <p class="stale-notice" role="status">
      <strong>Stale.</strong> This finding was produced against an earlier revision of the
      Scripture text or resources. Any decision recorded here is kept as history, but the
      finding must be re-evaluated against the current text.
    </p>
  {/if}

  <!-- SOURCE ------------------------------------------------------------- -->
  <section aria-labelledby="evidence-source">
    <h4 id="evidence-source">Source</h4>
    {#if detail.source.length === 0}
      <p class="muted">No source unit is attached to this finding.</p>
    {:else}
      {#each detail.source as unit}
        <dl class="facts">
          <dt>Text</dt>
          <dd class="scripture">{text(unit.rawSurface ?? unit.normalizedSurface)}</dd>
          <dt>Reference</dt>
          <dd>{list(unit.displayedReferences).join(", ") || "—"}</dd>
          <dt>Semantic unit</dt>
          <dd>{text(unit.kind)}</dd>
          <dt>Obligation</dt>
          <dd>{text(unit.semanticObligation ?? unit.obligationStrength)}</dd>
        </dl>
        {#if showSourceInternals}
          <dl class="facts secondary">
            <dt>Coverage dimension</dt>
            <dd>{text(unit.coverageDimension)}</dd>
            <dt>Accounting role</dt>
            <dd>{text(unit.accountingRole)}</dd>
            <dt>Audit eligibility</dt>
            <dd>{text(unit.auditEligibility)}</dd>
            <dt>Provenance</dt>
            <dd>{text(unit.provenance)}</dd>
            <dt>Unit id</dt>
            <dd class="mono">{text(unit.id)}</dd>
          </dl>
        {/if}
      {/each}
      <button class="link" type="button" on:click={() => (showSourceInternals = !showSourceInternals)}>
        {showSourceInternals ? "Hide" : "Show"} advanced source detail
      </button>
    {/if}
  </section>

  <!-- LOCATION ----------------------------------------------------------- -->
  <section aria-labelledby="evidence-location">
    <h4 id="evidence-location">Location <span class="stage">Stage 6B</span></h4>
    {#if locations.length === 0}
      <p class="muted">
        No target location was recorded for this finding. That is not the same as the
        translation omitting anything — see the coverage section below.
      </p>
    {:else}
      {#each locations as entry}
        {@const location = entry.location}
        <p class="outcome">
          <ReviewStatusBadge
            label={locationOutcomeLabel(location.locationOutcome)}
            tone={location.locationOutcome === "LOCATED" ? "acceptable" : "possible"}
          />
          <span class="outcome-help">{locationOutcomeHelp(location.locationOutcome)}</span>
        </p>
        <dl class="facts">
          {#if location.targetDisplayedReferences}
            <dt>Target reference</dt>
            <dd>{list(location.targetDisplayedReferences).join(", ") || "—"}</dd>
          {/if}
          {#if location.targetQuote}
            <dt>Target text</dt>
            <dd class="scripture">{text(location.targetQuote)}</dd>
          {/if}
          {#if location.realization}
            <dt>Realization</dt>
            <dd>{realizationLabel(String(location.realization))}</dd>
          {/if}
        </dl>
        {#if list(location.properties).length}
          <ul class="properties">
            {#each list(location.properties) as property}
              <li>{propertyLabel(property)}</li>
            {/each}
          </ul>
          <p class="muted small">
            Reordering, splitting and cross-verse realization are normal features of
            translation, not problems in themselves.
          </p>
        {/if}

        <h5>Alternatives considered</h5>
        {#if entry.alternatives.length === 0}
          <p class="muted small">Bridge retained no competing candidate for this location.</p>
        {:else}
          <ul class="alternatives">
            {#each entry.alternatives as candidate}
              <li>
                <span class="scripture">{text(candidate.targetQuote ?? candidate.quote)}</span>
                <span class="muted small">
                  {list(candidate.targetDisplayedReferences).join(", ")}
                  {#if candidate.id === location.selectedCandidateId}· selected{/if}
                </span>
              </li>
            {/each}
          </ul>
        {/if}
      {/each}
    {/if}
  </section>

  <!-- MEANING ------------------------------------------------------------ -->
  <section aria-labelledby="evidence-meaning">
    <h4 id="evidence-meaning">Meaning <span class="stage">Stage 7</span></h4>
    {#if meanings.length === 0}
      <p class="muted">
        No meaning assessment was made. Bridge assesses meaning only where it located a
        realization, so this is a gap in the analysis, not a verdict on the translation.
      </p>
    {:else}
      {#each meanings as entry}
        <p class="outcome">
          <ReviewStatusBadge
            label={meaningStatusLabel(entry.assessment.meaningStatus)}
            tone={["PRESERVED", "PRESERVED_WITH_RESTRUCTURING"].includes(
              String(entry.assessment.meaningStatus),
            ) ? "acceptable" : "possible"}
          />
        </p>
        {#if entry.components.length}
          <table class="components">
            <caption class="visually-hidden">Per-dimension meaning assessment</caption>
            <thead>
              <tr><th scope="col">Dimension</th><th scope="col">Assessment</th></tr>
            </thead>
            <tbody>
              {#each entry.components as component}
                <tr>
                  <th scope="row">{text(component.coverageDimension)}</th>
                  <td>{componentStatusLabel(String(component.status ?? ""))}</td>
                </tr>
              {/each}
            </tbody>
          </table>
          <p class="muted small">
            Each dimension is judged separately: a strong location can sit alongside a
            contradicted quantity.
          </p>
        {/if}
      {/each}
    {/if}
  </section>

  <!-- COVERAGE / SUPPORT ------------------------------------------------- -->
  <section aria-labelledby="evidence-coverage">
    <h4 id="evidence-coverage">Coverage and support <span class="stage">Stage 8</span></h4>
    {#if coverage.length === 0}
      <p class="muted">No coverage account is attached to this finding.</p>
    {:else}
      {#each coverage as account}
        {@const status = String(account.coverageStatus ?? "")}
        <div class="coverage-row">
          <ReviewStatusBadge
            label={coverageLabel(status)}
            tone={status.startsWith("POSSIBLY") ? "possible"
              : ["MISSING", "UNSUPPORTED"].includes(status) ? "confirmed" : "acceptable"}
          />
          <span class="muted small">{text(account.direction)} · {text(account.coverageDimension)}</span>
        </div>
        {#if coverageHelp(status)}
          <p class="help">{coverageHelp(status)}</p>
        {/if}
      {/each}
    {/if}
  </section>

  <!-- RESOURCES ---------------------------------------------------------- -->
  <section aria-labelledby="evidence-resources">
    <h4 id="evidence-resources">Resources</h4>
    {#if resources.length === 0}
      <p class="muted">No translation notes, words or word-list entries apply here.</p>
    {:else}
      <ul class="resources">
        {#each resources as item}
          <li class:conflicting={conflictingIds.has(item.id)}>
            <div class="resource-head">
              <span class="resource-kind">{text(item.kind ?? item.evidenceSource)}</span>
              {#if conflictingIds.has(item.id)}
                <ReviewStatusBadge label="Conflicting" tone="confirmed" />
              {:else if item.validationStatus}
                <ReviewStatusBadge
                  label={text(item.validationStatus)}
                  tone={item.validationStatus === "CONFLICTING" ? "confirmed" : "neutral"}
                />
              {/if}
            </div>
            {#if item.content || item.explanation}
              <p class="resource-body">{text(item.content ?? item.explanation)}</p>
            {/if}
            <p class="muted small mono">
              {text(item.resourceId, "")}
              {#if item.resourceVersion}· {item.resourceVersion}{/if}
              {#if item.evidenceSource === "UNRESOLVED"}
                · evidence record not found
              {/if}
            </p>
          </li>
        {/each}
      </ul>
    {/if}
  </section>

  <!-- MAPPING VS TRANSLATION --------------------------------------------- -->
  <section aria-labelledby="evidence-interpretation">
    <h4 id="evidence-interpretation">What this means</h4>
    {#if mappingUnclear}
      <p class="interpretation">
        <strong>Mapping is uncertain.</strong> Bridge is not confident it found the right target
        expression, so nothing here should be read as a translation fault yet. Reviewing the
        mapping first will usually be more useful than judging the translation.
      </p>
    {:else if mappingCertain}
      <p class="interpretation">
        <strong>Bridge believes it found the right place.</strong> If you agree, this is a
        question about the translation itself. If you disagree, reject the mapping instead —
        that is a different problem with a different fix.
      </p>
    {:else}
      <p class="interpretation">
        <strong>No target location was found.</strong> Either the meaning is genuinely absent, or
        Bridge failed to locate it. Check the coverage status above before concluding either way.
      </p>
    {/if}
  </section>

  <!-- HISTORY ------------------------------------------------------------ -->
  <section aria-labelledby="evidence-history">
    <h4 id="evidence-history">History</h4>
    {#if detail.history.length === 0}
      <p class="muted">No review activity yet.</p>
    {:else}
      <ol class="history">
        {#each detail.history as record}
          <li>
            <span class="actor">{record.actorType === "HUMAN" ? record.actorId : record.actorType}</span>
            <span class="transition">
              {text(record.previousQaDisposition, "—")} → {text(record.newQaDisposition, "—")}
            </span>
            <time datetime={record.createdAt}>{record.createdAt}</time>
            {#if record.note}<p class="note">{record.note}</p>{/if}
          </li>
        {/each}
      </ol>
    {/if}
  </section>
</div>

<style>
  .inspector { display: flex; flex-direction: column; gap: 0.9rem; }

  section {
    border: 1px solid #e5e7eb;
    border-radius: 6px;
    padding: 0.6rem 0.75rem;
    background: #fff;
  }

  h4 {
    margin: 0 0 0.5rem;
    font-size: 0.78rem;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: #374151;
    display: flex;
    justify-content: space-between;
    gap: 0.5rem;
  }

  .stage { font-weight: 400; text-transform: none; color: #9ca3af; letter-spacing: 0; }
  h5 { margin: 0.7rem 0 0.3rem; font-size: 0.75rem; color: #4b5563; }

  .facts {
    display: grid;
    grid-template-columns: minmax(6.5rem, max-content) 1fr;
    gap: 0.2rem 0.7rem;
    margin: 0 0 0.4rem;
    font-size: 0.82rem;
  }

  .facts.secondary { border-top: 1px dashed #e5e7eb; padding-top: 0.4rem; }
  dt { color: #6b7280; }
  dd { margin: 0; color: #111827; overflow-wrap: anywhere; }

  /* Scripture may be Tamil, Hebrew or Greek: give it room to wrap and a
     line height that suits tall scripts rather than clipping it. */
  .scripture { font-size: 1rem; line-height: 1.7; overflow-wrap: anywhere; }
  .mono { font-family: ui-monospace, monospace; font-size: 0.72rem; }
  .muted { color: #6b7280; }
  .small { font-size: 0.73rem; }

  .outcome { display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap; margin: 0 0 0.5rem; }
  .outcome-help { font-size: 0.78rem; color: #4b5563; }

  .properties { margin: 0.3rem 0; padding-left: 1.1rem; font-size: 0.78rem; }
  .alternatives { margin: 0; padding-left: 1.1rem; font-size: 0.82rem; }
  .alternatives li { margin-bottom: 0.3rem; }

  .components { width: 100%; border-collapse: collapse; font-size: 0.8rem; }
  .components th, .components td {
    text-align: left;
    padding: 0.2rem 0.4rem;
    border-bottom: 1px solid #f1f5f9;
  }
  .components thead th { color: #6b7280; font-weight: 500; }

  .coverage-row { display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap; }
  .help { margin: 0.25rem 0 0.5rem; font-size: 0.78rem; color: #1a6b3c; }

  .resources { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 0.5rem; }
  .resources li { border-left: 3px solid #e5e7eb; padding-left: 0.5rem; }
  .resources li.conflicting { border-left-color: #9b1c1c; }
  .resource-head { display: flex; align-items: center; gap: 0.4rem; flex-wrap: wrap; }
  .resource-kind { font-size: 0.75rem; color: #4b5563; }
  .resource-body { margin: 0.2rem 0; font-size: 0.82rem; }

  .interpretation { margin: 0; font-size: 0.82rem; line-height: 1.5; }

  .stale-notice {
    margin: 0;
    padding: 0.5rem 0.7rem;
    border: 1px solid #b59a4d;
    border-left-width: 4px;
    border-radius: 4px;
    background: #fdfaf0;
    font-size: 0.82rem;
  }

  .history { margin: 0; padding-left: 1.1rem; font-size: 0.8rem; }
  .history li { margin-bottom: 0.4rem; }
  .actor { font-weight: 600; }
  .transition { color: #4b5563; margin-left: 0.4rem; }
  .history time { display: block; color: #9ca3af; font-size: 0.72rem; }
  .note { margin: 0.2rem 0 0; color: #111827; }

  .link {
    background: none;
    border: none;
    padding: 0;
    color: #2563eb;
    font-size: 0.75rem;
    cursor: pointer;
    text-decoration: underline;
  }

  .visually-hidden {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip: rect(0 0 0 0);
    white-space: nowrap;
  }
</style>
