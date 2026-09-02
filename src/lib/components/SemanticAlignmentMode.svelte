<script lang="ts">
  import ReviewStatusBadge from "./ReviewStatusBadge.svelte";
  import type { QaFindingDetail } from "../types/qaReview";
  import {
    coverageLabel,
    locationOutcomeHelp,
    locationOutcomeLabel,
    meaningStatusLabel,
    propertyLabel,
    realizationLabel,
    reviewStatusLabel,
  } from "../utils/reviewLabels";

  /**
   * Semantic mode: what source meaning was selected, where Bridge located it,
   * and how its meaning was assessed.
   *
   * Same underlying record as QA mode, presented relationship-first rather
   * than finding-first. How the meaning was realized is shown prominently and
   * neutrally: a cross-verse or grammatically-carried realization is a normal
   * feature of translation, and nothing here styles it as a defect.
   */
  export let detail: QaFindingDetail | null = null;
  export let loading = false;

  /**
   * Realization and relationship properties a reviewer must be able to tell
   * apart at a glance, each with what it actually means for this passage.
   */
  const REALIZATION_HELP: Record<string, string> = {
    LEXICALLY_REALIZED: "A target word or phrase carries this meaning directly.",
    GRAMMATICALLY_REALIZED:
      "No separate word: the target grammar carries this meaning (an inflection, agreement or particle).",
    PRONOMINALIZED: "The target uses a pronoun where the source names the participant.",
    IMPLICIT: "The target leaves this implicit, recoverable from context rather than stated.",
    NOT_LOCATED: "Bridge found no target expression carrying this meaning.",
    UNCERTAIN: "Bridge could not determine how this was realized.",
  };

  const PROPERTY_HELP: Record<string, string> = {
    SPLIT: "One source meaning is carried by several separate target expressions.",
    MERGED: "Several source meanings are carried by one target expression.",
    CROSS_VERSE: "The target realizes this in a different verse than the source states it.",
    REORDERED: "The target places this differently in the passage than the source does.",
    DISCONTIGUOUS: "The target expression is not contiguous.",
    EXPLICITATED: "The target states explicitly what the source left implicit.",
    CLAUSE_RESTRUCTURED: "The clause was rebuilt rather than rendered word for word.",
    IDIOMATIC_REALIZATION: "Rendered as a target idiom rather than literally.",
    VERSIFICATION_DIFFERENCE: "Source and target versification differ here.",
  };

  function text(value: unknown, fallback = "—"): string {
    if (value === null || value === undefined || value === "") return fallback;
    return String(value);
  }

  function list(value: unknown): string[] {
    return Array.isArray(value) ? value.map(String) : [];
  }

  function confidence(value: unknown): string {
    const score = (value as { calibratedValue?: number } | undefined)?.calibratedValue;
    return typeof score === "number" ? `${Math.round(score * 100)}%` : "—";
  }

  $: sourceUnits = detail?.source ?? [];
  $: locations = detail?.location ?? [];
  $: meanings = detail?.meaning ?? [];
  $: coverage = detail?.coverage ?? [];
</script>

<div class="semantic">
  {#if loading}
    <p class="state" role="status">Loading the semantic relationship…</p>
  {:else if !detail}
    <p class="state">
      Select a possible issue in <strong>QA</strong> mode to inspect the semantic
      relationship behind it.
    </p>
  {:else}
    <div class="columns">
      <!-- SOURCE SIDE -->
      <section aria-labelledby="semantic-source">
        <h4 id="semantic-source">Source meaning</h4>
        {#if sourceUnits.length === 0}
          <p class="muted">
            This finding is about a target expression, so it has no source unit — see
            coverage and support below.
          </p>
        {:else}
          {#each sourceUnits as unit}
            <p class="scripture source-text">{text(unit.rawSurface ?? unit.normalizedSurface)}</p>
            <dl class="facts">
              <dt>Reference</dt>
              <dd>{list(unit.displayedReferences).join(", ") || "—"}</dd>
              <dt>Unit type</dt>
              <dd>{text(unit.kind)}</dd>
              {#if unit.lemma}
                <dt>Lemma</dt>
                <dd class="scripture">{text(unit.lemma)}</dd>
              {/if}
              {#if unit.morphology}
                <dt>Morphology</dt>
                <dd class="mono">{text(unit.morphology)}</dd>
              {/if}
              <dt>Obligation</dt>
              <dd>{text(unit.semanticObligation ?? unit.obligationStrength)}</dd>
              <dt>Coverage dimension</dt>
              <dd>{text(unit.coverageDimension)}</dd>
            </dl>
          {/each}
        {/if}
      </section>

      <!-- TARGET SIDE -->
      <section aria-labelledby="semantic-target">
        <h4 id="semantic-target">Target realization</h4>
        {#if locations.length === 0}
          <p class="muted">Bridge recorded no target location for this meaning.</p>
        {:else}
          {#each locations as entry}
            {@const location = entry.location}
            {#if location.targetQuote}
              <p class="scripture target-text">{text(location.targetQuote)}</p>
            {/if}
            <dl class="facts">
              <dt>Reference</dt>
              <dd>{list(location.targetDisplayedReferences).join(", ") || "—"}</dd>
              {#if list(location.targetSpanIds).length}
                <dt>Spans</dt>
                <dd class="mono">{list(location.targetSpanIds).join(", ")}</dd>
              {/if}
            </dl>

            <h5>How it was realized</h5>
            <div class="realization">
              <ReviewStatusBadge
                label={realizationLabel(String(location.realization ?? "UNCERTAIN"))}
                tone={location.realization === "NOT_LOCATED" ? "possible" : "neutral"}
              />
              <p class="help">{REALIZATION_HELP[String(location.realization)] ?? ""}</p>
            </div>

            {#if list(location.properties).length}
              <ul class="properties">
                {#each list(location.properties) as property}
                  <li>
                    <span class="property-name">{propertyLabel(property)}</span>
                    <span class="help">{PROPERTY_HELP[property] ?? ""}</span>
                  </li>
                {/each}
              </ul>
            {/if}
          {/each}
        {/if}
      </section>
    </div>

    <!-- ASSESSMENT STRIP: location and meaning stay side by side but separate -->
    <section class="assessment" aria-labelledby="semantic-assessment">
      <h4 id="semantic-assessment">Assessment</h4>
      <div class="assessment-grid">
        <div class="assessment-cell">
          <span class="cell-label">Location <span class="stage">Stage 6B</span></span>
          {#if locations.length}
            <ReviewStatusBadge
              label={locationOutcomeLabel(locations[0].location.locationOutcome)}
              tone={locations[0].location.locationOutcome === "LOCATED" ? "acceptable" : "possible"}
            />
            <span class="cell-note">
              Confidence {confidence(locations[0].location.locationConfidence)}
            </span>
            <span class="cell-note">{locationOutcomeHelp(locations[0].location.locationOutcome)}</span>
            <span class="cell-note">
              {reviewStatusLabel(locations[0].location.reviewStatus)}
            </span>
          {:else}
            <span class="cell-note">Not recorded.</span>
          {/if}
        </div>

        <div class="assessment-cell">
          <span class="cell-label">Meaning <span class="stage">Stage 7</span></span>
          {#if meanings.length}
            <ReviewStatusBadge
              label={meaningStatusLabel(meanings[0].assessment.meaningStatus)}
              tone={["PRESERVED", "PRESERVED_WITH_RESTRUCTURING"].includes(
                String(meanings[0].assessment.meaningStatus),
              ) ? "acceptable" : "possible"}
            />
            <span class="cell-note">
              Confidence {confidence(meanings[0].assessment.meaningConfidence)}
            </span>
            <span class="cell-note">
              {reviewStatusLabel(meanings[0].assessment.reviewStatus)}
            </span>
          {:else}
            <span class="cell-note">Not assessed — Bridge assesses meaning only where it located a realization.</span>
          {/if}
        </div>

        <div class="assessment-cell">
          <span class="cell-label">Coverage &amp; support <span class="stage">Stage 8</span></span>
          {#if coverage.length}
            {#each coverage as account}
              <ReviewStatusBadge
                label={coverageLabel(String(account.coverageStatus))}
                tone={String(account.coverageStatus).startsWith("POSSIBLY") ? "possible" : "acceptable"}
              />
            {/each}
          {:else}
            <span class="cell-note">No coverage account.</span>
          {/if}
        </div>

        <div class="assessment-cell">
          <span class="cell-label">Review state</span>
          <ReviewStatusBadge
            label={reviewStatusLabel(detail.finding.reviewStatus)}
            tone="neutral"
          />
          {#if detail.isStale}
            <ReviewStatusBadge label="Stale" tone="stale" />
          {/if}
        </div>
      </div>
      <p class="separate-note">
        Location and meaning are judged independently. A confidently located realization can
        still fail a meaning check, and an uncertain location makes any meaning verdict
        provisional.
      </p>
    </section>
  {/if}
</div>

<style>
  .semantic { display: flex; flex-direction: column; gap: 0.75rem; padding: 0.8rem; overflow-y: auto; min-height: 0; }
  .state { padding: 1.2rem; color: #6b7280; font-size: 0.85rem; }

  .columns { display: grid; grid-template-columns: repeat(auto-fit, minmax(18rem, 1fr)); gap: 0.75rem; }

  section { border: 1px solid #e5e7eb; border-radius: 6px; padding: 0.65rem 0.8rem; background: #fff; }

  h4 {
    margin: 0 0 0.5rem;
    font-size: 0.78rem;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: #374151;
  }

  h5 { margin: 0.7rem 0 0.3rem; font-size: 0.75rem; color: #4b5563; }
  .stage { font-weight: 400; text-transform: none; color: #9ca3af; letter-spacing: 0; }

  /* Greek, Hebrew and Tamil all need room to breathe and must wrap rather
     than clip, whatever the pane width. */
  .scripture { font-size: 1.05rem; line-height: 1.8; overflow-wrap: anywhere; margin: 0 0 0.5rem; }
  .source-text { color: #1f2937; }
  .target-text { color: #1f2937; }

  .facts {
    display: grid;
    grid-template-columns: minmax(6rem, max-content) 1fr;
    gap: 0.2rem 0.7rem;
    margin: 0;
    font-size: 0.8rem;
  }

  dt { color: #6b7280; }
  dd { margin: 0; color: #111827; overflow-wrap: anywhere; }
  .mono { font-family: ui-monospace, monospace; font-size: 0.72rem; }
  .muted { color: #6b7280; font-size: 0.82rem; }

  .realization { display: flex; flex-direction: column; gap: 0.25rem; align-items: flex-start; }
  .help { margin: 0; font-size: 0.76rem; color: #4b5563; }

  .properties { list-style: none; margin: 0.5rem 0 0; padding: 0; display: flex; flex-direction: column; gap: 0.35rem; }
  .properties li { border-left: 3px solid #d1d5db; padding-left: 0.5rem; }
  .property-name { display: block; font-size: 0.78rem; font-weight: 600; }

  .assessment-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(12rem, 1fr));
    gap: 0.6rem;
  }

  .assessment-cell { display: flex; flex-direction: column; gap: 0.25rem; align-items: flex-start; }
  .cell-label { font-size: 0.72rem; color: #6b7280; text-transform: uppercase; letter-spacing: 0.03em; }
  .cell-note { font-size: 0.75rem; color: #4b5563; }

  .separate-note {
    margin: 0.6rem 0 0;
    padding-top: 0.5rem;
    border-top: 1px dashed #e5e7eb;
    font-size: 0.76rem;
    color: #4b5563;
  }
</style>
