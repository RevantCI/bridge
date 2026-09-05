<script lang="ts">
  import { bridge } from "../api/bridgeClient";
  import type {
    AffectedTargetSpan,
    CorrectionEligibility,
    CorrectionIntent,
    CorrectionProposal,
    CorrectionProposalEvent,
    CorrectionReviewContext,
  } from "../types/correctionReview";
  import type { SettingsData } from "../types/finding";
  import type { CoverageDimension } from "../types/passageSemanticV1";
  import {
    codePointLength,
    graphemeBoundariesInCodePoints,
    graphemeDiff,
    visualContextSegments,
  } from "../utils/unicodeDiff";

  export let findingId: string;
  /** Re-evaluate backend eligibility after the Stage 9A review changes. */
  export let findingRevision = 0;

  let eligibility: CorrectionEligibility | null = null;
  let context: CorrectionReviewContext | null = null;
  let settings: SettingsData | null = null;
  let proposals: CorrectionProposal[] = [];
  let selectedProposalId = "";
  let history: CorrectionProposalEvent[] = [];
  let loading = true;
  let busy = false;
  let error = "";
  let notice = "";
  let loadedReviewKey = "";
  let creationOpen = false;
  let creationMode: "" | "manual" | "suggestion" = "";
  let selectedSpanIndex = 0;
  let selectedReference = "";
  let insertionBoundaryIndex = 0;
  let proposedText = "";
  let explanation = "";
  let observedMeaning = "";
  let requiredMeaning = "";
  let failedDimension: CoverageDimension = "OTHER";
  let editing = false;
  let editText = "";
  let editExplanation = "";
  let reviewNote = "";

  $: reviewKey = `${findingId}:${findingRevision}`;
  $: if (findingId && reviewKey !== loadedReviewKey) {
    loadedReviewKey = reviewKey;
    void loadAll(reviewKey);
  }
  $: selectedProposal = proposals.find((item) => item.id === selectedProposalId) ?? null;
  $: selectedTarget = selectedProposal && context
    ? context.currentTargets.find((item) =>
        item.displayedReference === selectedProposal?.intent.affectedTargetSpan.displayedReference)
      ?? null
    : null;
  $: selectedSpan = selectedProposal?.intent.affectedTargetSpan ?? null;
  $: contextParts = selectedTarget && selectedSpan
    ? visualContextSegments(selectedTarget.text, selectedSpan.startCodePoint, selectedSpan.endCodePoint)
    : null;
  $: diff = selectedProposal ? graphemeDiff(selectedProposal.currentText, selectedProposal.proposedText) : [];
  $: proposalBlockingReasons = (eligibility?.reasons ?? []).filter((reason) =>
    reason.code !== "ELIGIBLE"
    && !(reason.code === "CONFLICTING_CORRECTION"
      && proposals.some((item) => item.id === reason.entityId)),
  );
  $: proposalCurrent = Boolean(
    selectedProposal?.lifecycleStatus === "ACTIVE" && proposalBlockingReasons.length === 0,
  );
  $: providerAvailable = Boolean(settings?.hasApiKey);
  $: insertionTarget = context?.currentTargets.find((item) => item.displayedReference === selectedReference)
    ?? context?.currentTargets[0] ?? null;
  $: insertionBoundaries = insertionTarget ? graphemeBoundariesInCodePoints(insertionTarget.text) : [0];

  function message(exc: unknown): string {
    return exc instanceof Error ? exc.message : String(exc);
  }

  function chooseLatest(items: CorrectionProposal[]): string {
    const active = [...items].reverse().find((item) => item.lifecycleStatus === "ACTIVE");
    return active?.id ?? items.at(-1)?.id ?? "";
  }

  function initializeDraft(): void {
    const suggested = context?.suggestedIntent;
    observedMeaning = suggested?.observedMeaning ?? "";
    requiredMeaning = suggested?.requiredMeaning ?? "";
    failedDimension = suggested?.failedDimension ?? "OTHER";
    selectedSpanIndex = 0;
    selectedReference = context?.candidateSpans[0]?.displayedReference
      ?? context?.currentTargets[0]?.displayedReference ?? "";
    insertionBoundaryIndex = 0;
    proposedText = "";
    explanation = "";
  }

  async function loadHistory(proposalId: string): Promise<void> {
    if (!proposalId) {
      history = [];
      return;
    }
    history = (await bridge.correctionGetProposalHistory(proposalId)).events;
  }

  async function loadAll(requestKey: string): Promise<void> {
    loading = true;
    error = "";
    notice = "";
    creationOpen = false;
    creationMode = "";
    try {
      const [nextEligibility, nextContext, listed, nextSettings] = await Promise.all([
        bridge.correctionGetEligibility(findingId),
        bridge.correctionGetReviewContext(findingId),
        bridge.correctionListForFinding(findingId),
        bridge.getSettings(),
      ]);
      if (requestKey !== loadedReviewKey) return;
      eligibility = nextEligibility;
      context = nextContext;
      settings = nextSettings;
      proposals = listed.proposals;
      selectedProposalId = chooseLatest(proposals);
      initializeDraft();
      await loadHistory(selectedProposalId);
    } catch (exc) {
      error = message(exc);
    } finally {
      loading = false;
    }
  }

  async function reloadProposals(preferredId = ""): Promise<void> {
    const listed = await bridge.correctionListForFinding(findingId);
    proposals = listed.proposals;
    selectedProposalId = proposals.some((item) => item.id === preferredId)
      ? preferredId : chooseLatest(proposals);
    await loadHistory(selectedProposalId);
  }

  function draftSpan(): AffectedTargetSpan | null {
    if (!context) return null;
    if (context.candidateSpans.length) return context.candidateSpans[selectedSpanIndex] ?? null;
    if (!insertionTarget) return null;
    const point = insertionBoundaries[insertionBoundaryIndex] ?? 0;
    return {
      displayedReference: insertionTarget.displayedReference,
      canonicalReferences: insertionTarget.canonicalReferences,
      startCodePoint: point,
      endCodePoint: point,
      originalText: "",
      targetTextRevision: insertionTarget.targetTextRevision,
      targetContentHash: insertionTarget.targetContentHash,
    };
  }

  function draftIntent(): CorrectionIntent | null {
    const affectedTargetSpan = draftSpan();
    if (!affectedTargetSpan || !context) return null;
    return {
      failedDimension,
      observedMeaning: observedMeaning.trim(),
      requiredMeaning: requiredMeaning.trim(),
      affectedSourceSemanticUnitIds: context.suggestedIntent.affectedSourceSemanticUnitIds,
      affectedTargetSpan,
    };
  }

  async function create(requestSuggestion: boolean): Promise<void> {
    const intent = draftIntent();
    if (!intent) {
      error = "Choose an exact target span or insertion point first.";
      return;
    }
    busy = true;
    error = "";
    try {
      const created = await bridge.correctionCreateProposal({
        findingId,
        intent,
        humanProposedText: requestSuggestion ? "" : proposedText.trim(),
        explanation: explanation.trim(),
        requestSuggestion,
        actorId: settings?.reviewerName || undefined,
      });
      proposals = [...proposals, created];
      selectedProposalId = created.id;
      await loadHistory(created.id);
      creationOpen = false;
      creationMode = "";
      notice = requestSuggestion ? "Suggestion created for human review." : "Proposal saved for human review.";
    } catch (exc) {
      error = message(exc);
    } finally {
      busy = false;
    }
  }

  function startEdit(): void {
    if (!selectedProposal) return;
    editing = true;
    editText = selectedProposal.proposedText;
    editExplanation = selectedProposal.explanation;
  }

  async function editProposal(text: string, why: string): Promise<void> {
    if (!selectedProposal) return;
    const proposalId = selectedProposal.id;
    busy = true;
    error = "";
    try {
      const updated = await bridge.correctionEditProposal(proposalId, {
        proposedText: text.trim(),
        explanation: why.trim(),
        expectedProposalRevision: selectedProposal.revision,
        actorId: settings?.reviewerName || undefined,
      });
      proposals = proposals.map((item) => item.id === updated.id ? updated : item);
      await loadHistory(updated.id);
      editing = false;
      notice = "Proposal wording updated. Scripture has not changed.";
    } catch (exc) {
      if (/revision[_ ]conflict/i.test(message(exc))) {
        await reloadProposals(proposalId);
        editing = false;
        error = "This proposal changed elsewhere. The current proposal has been reloaded; your edit was not overwritten.";
      } else {
        error = message(exc);
      }
    } finally {
      busy = false;
    }
  }

  async function rejectProposal(): Promise<void> {
    if (!selectedProposal) return;
    busy = true;
    error = "";
    try {
      const updated = await bridge.correctionRejectProposal(selectedProposal.id, {
        expectedProposalRevision: selectedProposal.revision,
        actorId: settings?.reviewerName || undefined,
        note: reviewNote.trim(),
      });
      proposals = proposals.map((item) => item.id === updated.id ? updated : item);
      await loadHistory(updated.id);
      notice = "Proposal rejected and retained in history.";
      reviewNote = "";
    } catch (exc) {
      error = message(exc);
    } finally {
      busy = false;
    }
  }

  async function regenerate(): Promise<void> {
    if (!selectedProposal) return;
    const oldId = selectedProposal.id;
    busy = true;
    error = "";
    try {
      const replacement = await bridge.correctionRegenerateProposal(oldId, {
        expectedProposalRevision: selectedProposal.revision,
        actorId: settings?.reviewerName || undefined,
      });
      await reloadProposals(replacement.id);
      notice = "A new suggestion was created. The previous proposal remains in history.";
    } catch (exc) {
      error = message(exc);
    } finally {
      busy = false;
    }
  }

  function provenanceLabel(item: CorrectionProposal): string {
    if (item.creationMode === "MACHINE_SUGGESTED_HUMAN_EDITED" || item.creationMode === "HUMAN_MODIFIED_AI") {
      return "Machine-suggested · Human-edited";
    }
    if (item.creationMode === "HUMAN_AUTHORED") return "Human-authored";
    if (item.creationMode === "MACHINE_SUGGESTED") return "Machine-suggested";
    if (item.creationMode === "AI_GENERATED") return "AI provider-suggested";
    return "Migrated proposal";
  }

  function value(item: Record<string, unknown>, ...keys: string[]): string {
    for (const key of keys) if (item[key] !== undefined && item[key] !== null) return String(item[key]);
    return "—";
  }
</script>

<section class="correction" data-correction-panel aria-labelledby="correction-title">
  <header class="title-row">
    <div>
      <h4 id="correction-title">Correction</h4>
      <p>Proposal review only. Scripture is unchanged.</p>
    </div>
    {#if selectedProposal}
      <span class="status" class:stale={selectedProposal.lifecycleStatus === "STALE"}>
        {selectedProposal.reviewStatus === "HUMAN_REJECTED" ? "Rejected" : selectedProposal.lifecycleStatus}
      </span>
    {/if}
  </header>

  {#if loading}
    <p class="state" role="status">Checking correction eligibility…</p>
  {:else if error && !context}
    <p class="message error" role="alert">{error}</p>
  {:else}
    {#if error}<p class="message error" role="alert">{error}</p>{/if}
    {#if notice}<p class="message ok" role="status">{notice}</p>{/if}

    {#if selectedProposal}
      {#if selectedProposal.lifecycleStatus === "STALE"}
        <p class="stale-notice" role="status" aria-label="Stale correction proposal">
          <strong>Stale proposal.</strong> Its text or evidence changed. It remains historical and
          cannot be edited or regenerated from these assumptions.
        </p>
      {/if}
      {#if proposalBlockingReasons.length}
        <div class="unavailable current-blockers">
          <h5>Correction unavailable</h5>
          <ul>{#each proposalBlockingReasons as reason}<li>{reason.detail}</li>{/each}</ul>
        </div>
      {/if}

      {#if proposals.length > 1}
        <div class="proposal-picker">
          <span>{proposals.length} proposals retained</span>
          {#each proposals as item, index}
            <button
              type="button"
              aria-pressed={selectedProposalId === item.id}
              on:click={async () => { selectedProposalId = item.id; await loadHistory(item.id); }}
            >Proposal {index + 1} · {item.lifecycleStatus}</button>
          {/each}
        </div>
      {/if}

      <div class="review-scroll" data-correction-scroll>
        <section class="block" aria-labelledby="correction-current">
          <h5 id="correction-current">Current text</h5>
          <p class="reference">{selectedSpan?.displayedReference}</p>
          <p class="coordinates">
            {selectedSpan?.startCodePoint === selectedSpan?.endCodePoint ? "Insertion point" : "Affected span"}
            [{selectedSpan?.startCodePoint}, {selectedSpan?.endCodePoint})
          </p>
          {#if contextParts}
            <p class="scripture context-text">
              <span>{contextParts.before}</span>{#if contextParts.insertion}<span class="caret" aria-label="Insertion point"></span>{:else}<mark>{contextParts.affected}</mark>{/if}<span>{contextParts.after}</span>
            </p>
          {:else}
            <p class="scripture">{selectedProposal.currentText || "Insertion into empty span"}</p>
          {/if}
        </section>

        <section class="block" aria-labelledby="correction-proposed">
          <h5 id="correction-proposed">Proposed text</h5>
          <p class="scripture proposed">{selectedProposal.proposedText}</p>
          <div class="diff" aria-label={selectedProposal.currentText ? "Replacement diff" : "Insertion diff"}>
            {#each diff as part}
              {#if part.kind === "removed"}<del>{part.text}</del>{:else if part.kind === "inserted"}<ins>{part.text}</ins>{:else}<span>{part.text}</span>{/if}
            {/each}
          </div>
          {#if selectedProposal.originalSuggestedText && selectedProposal.originalSuggestedText !== selectedProposal.proposedText}
            <p class="original">Original machine suggestion: {selectedProposal.originalSuggestedText}</p>
          {/if}
          {#if selectedProposal.alternatives.length}
            <h6>Alternatives</h6>
            <ul class="alternatives">
              {#each selectedProposal.alternatives as alternative}
                <li>
                  <button
                    type="button"
                    disabled={busy || !proposalCurrent}
                    aria-label="Use alternative: {alternative.proposedText}"
                    on:click={() => editProposal(alternative.proposedText, alternative.explanation)}
                  >{alternative.proposedText}</button>
                  {#if alternative.explanation}<p>{alternative.explanation}</p>{/if}
                </li>
              {/each}
            </ul>
          {/if}
        </section>

        <section class="block" aria-labelledby="correction-why">
          <h5 id="correction-why">Why this change</h5>
          <p>{selectedProposal.explanation || "No additional explanation was recorded."}</p>
        </section>

        <section class="block" aria-labelledby="correction-meaning">
          <h5 id="correction-meaning">Affected meaning</h5>
          <dl>
            <dt>Failed dimension</dt><dd>{selectedProposal.intent.failedDimension}</dd>
            <dt>Currently expressed</dt><dd>{selectedProposal.intent.observedMeaning}</dd>
            <dt>Required meaning</dt><dd>{selectedProposal.intent.requiredMeaning}</dd>
          </dl>
        </section>

        <section class="block" aria-labelledby="correction-source">
          <h5 id="correction-source">Source evidence</h5>
          {#if context?.sourceEvidence.length}
            {#each context.sourceEvidence as item}<p class="scripture">{value(item, "rawSurface", "normalizedSurface")}</p>{/each}
          {:else}<p class="muted">No source surface is attached.</p>{/if}
        </section>

        <section class="block" aria-labelledby="correction-location">
          <h5 id="correction-location">Target location</h5>
          <p>{selectedSpan?.displayedReference} · [{selectedSpan?.startCodePoint}, {selectedSpan?.endCodePoint})</p>
          <p class="muted">Exact Unicode code-point coordinates; no fuzzy relocation.</p>
        </section>

        <section class="block" aria-labelledby="correction-resources">
          <h5 id="correction-resources">Resources</h5>
          {#if context?.resources.length}
            {#each context.resources as item}<p>{value(item, "content", "explanation", "kind")}</p>{/each}
          {:else}<p class="muted">No tN, tW or TWL evidence applies.</p>{/if}
        </section>

        <section class="block" aria-labelledby="correction-provenance">
          <h5 id="correction-provenance">Provenance</h5>
          <p>{provenanceLabel(selectedProposal)}</p>
          {#if selectedProposal.providerMetadata}
            <p class="muted">{selectedProposal.providerMetadata.providerName} · {selectedProposal.providerMetadata.model}</p>
          {/if}
          {#if selectedProposal.supersedesProposalId}<p class="muted">This proposal supersedes an earlier retained proposal.</p>{/if}
        </section>

        <section class="block" aria-labelledby="correction-history">
          <h5 id="correction-history">History</h5>
          {#if history.length}
            <ol class="history">
              {#each history as item}
                <li><strong>{item.eventType}</strong> · {item.actorId || item.actorType}
                  <time datetime={item.createdAt}>{item.createdAt}</time>
                  {#if item.providerMetadata}
                    <span class="history-provenance">
                      {item.providerMetadata.providerName} · {item.providerMetadata.model}
                    </span>
                  {/if}
                  {#if item.note || item.reason}<p>{item.note || item.reason}</p>{/if}
                </li>
              {/each}
            </ol>
          {:else}<p class="muted">No proposal events recorded.</p>{/if}
        </section>
      </div>

      <div class="review-actions" data-correction-actions>
        {#if editing}
          <label for="correction-edit-text">Edit proposed wording</label>
          <textarea id="correction-edit-text" bind:value={editText} rows="3"></textarea>
          <label for="correction-edit-why">Why this wording</label>
          <textarea id="correction-edit-why" bind:value={editExplanation} rows="2"></textarea>
          <div class="buttons">
            <button type="button" disabled={busy || !editText.trim()} on:click={() => editProposal(editText, editExplanation)}>Save proposal edit</button>
            <button type="button" class="secondary" on:click={() => (editing = false)}>Cancel edit</button>
          </div>
        {:else}
          <label for="proposal-review-note">Proposal review note <span class="muted">(optional)</span></label>
          <textarea id="proposal-review-note" bind:value={reviewNote} rows="2"></textarea>
          <div class="buttons">
            <button type="button" disabled={busy || !proposalCurrent} on:click={startEdit}>Edit proposal</button>
            <button type="button" class="danger" disabled={busy || !proposalCurrent} on:click={rejectProposal}>Reject proposal</button>
            {#if providerAvailable}
              <button type="button" class="secondary" disabled={busy || !proposalCurrent} on:click={regenerate}>Generate another suggestion</button>
            {/if}
          </div>
        {/if}
        <p class="boundary">Proposal actions update companion review data only.</p>
      </div>
    {:else if eligibility && !eligibility.eligible}
      <div class="unavailable">
        <h5>Correction proposal unavailable</h5>
        <ul>{#each eligibility.reasons.filter((item) => item.code !== "ELIGIBLE") as reason}<li>{reason.detail}</li>{/each}</ul>
      </div>
    {:else if eligibility?.eligible}
      {#if !creationOpen}
        <button type="button" class="create" on:click={() => { creationOpen = true; initializeDraft(); }}>Create correction proposal</button>
      {:else}
        <div class="create-workflow">
          <h5>Choose how to begin</h5>
          <div class="buttons">
            <button type="button" on:click={() => (creationMode = "manual")}>Write correction manually</button>
            {#if providerAvailable}<button type="button" class="secondary" disabled={busy} on:click={() => (creationMode = "suggestion")}>Suggest wording</button>{/if}
          </div>
          {#if creationMode}
            <div class="draft-form">
              {#if context?.candidateSpans.length}
                <fieldset>
                  <legend>Exact affected span</legend>
                  {#each context.candidateSpans as span, index}
                    <label><input type="radio" name="correction-span" value={index} bind:group={selectedSpanIndex} /> {span.displayedReference} [{span.startCodePoint}, {span.endCodePoint}) · <span class="scripture">{span.originalText}</span></label>
                  {/each}
                </fieldset>
              {:else if insertionTarget}
                <label for="insertion-reference">Insertion reference</label>
                <select id="insertion-reference" bind:value={selectedReference}>
                  {#each context?.currentTargets ?? [] as target}<option value={target.displayedReference}>{target.displayedReference}</option>{/each}
                </select>
                <label for="insertion-point">Insertion point after {insertionBoundaryIndex} text elements</label>
                <input id="insertion-point" type="range" min="0" max={Math.max(0, insertionBoundaries.length - 1)} bind:value={insertionBoundaryIndex} />
                {@const point = insertionBoundaries[insertionBoundaryIndex] ?? 0}
                {@const preview = visualContextSegments(insertionTarget.text, point, point)}
                <p class="scripture context-text"><span>{preview.before}</span><span class="caret" aria-label="Insertion point"></span><span>{preview.after}</span></p>
              {/if}
              <label for="intent-dimension">Affected meaning</label>
              <select id="intent-dimension" bind:value={failedDimension}>
                {#each ["LEXICAL_CONTENT", "POLARITY", "QUANTITY", "PARTICIPANT", "REFERENT", "PREDICATION", "TEMPORAL_ASPECTUAL", "SPATIAL_RELATION", "CLAUSE_RELATION", "DISCOURSE_RELATION", "OTHER"] as dimension}<option value={dimension}>{dimension}</option>{/each}
              </select>
              <label for="observed-meaning">Meaning currently expressed</label>
              <textarea id="observed-meaning" bind:value={observedMeaning} rows="2"></textarea>
              <label for="required-meaning">Meaning required</label>
              <textarea id="required-meaning" bind:value={requiredMeaning} rows="2"></textarea>
              {#if creationMode === "manual"}
                <label for="proposed-wording">Proposed wording</label>
                <textarea id="proposed-wording" bind:value={proposedText} rows="3"></textarea>
                <label for="proposal-explanation">Why this wording</label>
                <textarea id="proposal-explanation" bind:value={explanation} rows="2"></textarea>
                <button type="button" disabled={busy || !proposedText.trim() || !observedMeaning.trim() || !requiredMeaning.trim()} on:click={() => create(false)}>Save proposal</button>
              {:else}
                <p class="muted">Bridge will send only this correction intent and its relevant evidence to the configured provider. You will review the result before any later application stage.</p>
                <button type="button" disabled={busy || !observedMeaning.trim() || !requiredMeaning.trim()} on:click={() => create(true)}>Generate suggestion</button>
              {/if}
            </div>
          {/if}
        </div>
      {/if}
    {/if}
  {/if}
</section>

<style>
  .correction { border: 1px solid #c7d2fe; border-radius: 7px; background: #f8faff; min-height: 0; display: flex; flex-direction: column; }
  .title-row { display: flex; justify-content: space-between; align-items: flex-start; gap: .75rem; padding: .65rem .75rem; border-bottom: 1px solid #dbeafe; }
  h4, h5, h6, p { margin-top: 0; }
  h4 { margin-bottom: .15rem; font-size: .8rem; letter-spacing: .04em; text-transform: uppercase; }
  h5 { margin-bottom: .4rem; font-size: .78rem; text-transform: uppercase; color: #374151; }
  h6 { margin: .65rem 0 .3rem; font-size: .76rem; }
  .title-row p, .boundary { margin-bottom: 0; color: #6b7280; font-size: .73rem; }
  .status { border: 1px solid #cbd5e1; border-radius: 999px; padding: .12rem .45rem; font-size: .7rem; white-space: nowrap; }
  .status.stale { border-color: #b45309; color: #92400e; }
  .state, .unavailable, .create-workflow { padding: .75rem; font-size: .82rem; }
  .message { margin: .5rem .75rem 0; padding: .45rem .6rem; border-radius: 4px; font-size: .78rem; }
  .message.error { background: #fff1f2; color: #9f1239; }
  .message.ok { background: #ecfdf5; color: #166534; }
  .stale-notice { margin: .6rem .75rem 0; padding: .5rem; border-left: 4px solid #b45309; background: #fffbeb; font-size: .8rem; }
  .proposal-picker { display: flex; align-items: center; flex-wrap: wrap; gap: .3rem; padding: .5rem .75rem; border-bottom: 1px solid #e5e7eb; font-size: .72rem; }
  .proposal-picker button { font: inherit; border: 1px solid #cbd5e1; background: #fff; border-radius: 999px; padding: .15rem .45rem; }
  .proposal-picker button[aria-pressed="true"] { border-width: 2px; border-color: #2563eb; }
  .review-scroll { padding: .65rem .75rem; display: flex; flex-direction: column; gap: .6rem; overflow-y: auto; max-height: 24rem; min-height: 7rem; }
  .block { border: 1px solid #e5e7eb; border-radius: 5px; padding: .55rem .65rem; background: #fff; }
  .block p:last-child { margin-bottom: 0; }
  .reference { color: #4b5563; font-weight: 600; font-size: .78rem; margin-bottom: .2rem; }
  .coordinates { color: #6b7280; font-size: .72rem; margin-bottom: .35rem; }
  .scripture { overflow-wrap: anywhere; line-height: 1.7; }
  .context-text { border: 1px solid #e5e7eb; padding: .45rem; border-radius: 4px; }
  mark { background: #fef08a; padding: .05rem; }
  .caret { display: inline-block; height: 1.35em; border-left: 3px solid #dc2626; vertical-align: text-bottom; margin: 0 1px; }
  .proposed { font-size: 1rem; }
  .diff { padding: .4rem; background: #f8fafc; border-radius: 4px; line-height: 1.7; overflow-wrap: anywhere; }
  del { background: #fee2e2; color: #991b1b; text-decoration-thickness: 2px; }
  ins { background: #dcfce7; color: #166534; text-decoration: none; border-bottom: 2px solid #16a34a; }
  .original { color: #4b5563; font-size: .75rem; margin-top: .4rem; }
  .alternatives { list-style: none; margin: 0; padding: 0; display: grid; gap: .35rem; }
  .alternatives li { border-left: 3px solid #bfdbfe; padding-left: .45rem; }
  .alternatives p { margin: .15rem 0 0; color: #6b7280; font-size: .75rem; }
  dl { display: grid; grid-template-columns: minmax(7rem, max-content) 1fr; gap: .25rem .6rem; font-size: .8rem; }
  dt { color: #6b7280; } dd { margin: 0; overflow-wrap: anywhere; }
  .history { margin: 0; padding-left: 1.1rem; font-size: .76rem; }
  .history time { display: block; color: #6b7280; font-size: .69rem; }
  .history-provenance { display: block; color: #4b5563; font-size: .69rem; }
  .history p { margin: .15rem 0 .4rem; }
  .muted { color: #6b7280; }
  .review-actions { position: sticky; bottom: 0; padding: .65rem .75rem; border-top: 1px solid #dbeafe; background: #f8faff; }
  label, legend { font-size: .76rem; color: #374151; }
  textarea, select, input[type="range"] { width: 100%; box-sizing: border-box; font: inherit; margin: .18rem 0 .45rem; }
  textarea, select { border: 1px solid #cbd5e1; border-radius: 4px; padding: .35rem .45rem; resize: vertical; }
  fieldset { border: 1px solid #dbeafe; margin: .4rem 0; display: grid; gap: .3rem; }
  .buttons { display: flex; flex-wrap: wrap; gap: .4rem; margin: .4rem 0; }
  button { font: inherit; font-size: .77rem; border: 1px solid #2563eb; color: #1d4ed8; background: #fff; border-radius: 4px; padding: .35rem .6rem; cursor: pointer; }
  button.secondary { border-color: #94a3b8; color: #334155; }
  button.danger { border-color: #dc2626; color: #b91c1c; }
  button:disabled { opacity: .5; cursor: not-allowed; }
  button:focus-visible, textarea:focus-visible, select:focus-visible, input:focus-visible { outline: 2px solid #2563eb; outline-offset: 2px; }
  .create { margin: .75rem; align-self: flex-start; }
  .draft-form { margin-top: .6rem; max-height: 22rem; overflow-y: auto; padding-right: .25rem; }
  .unavailable ul { margin-bottom: 0; padding-left: 1.2rem; }
  .boundary { margin-top: .35rem; }
  @media (max-width: 900px) {
    .review-scroll { max-height: 19rem; }
    dl { grid-template-columns: 1fr; gap: .1rem; }
    dd { margin-bottom: .35rem; }
  }
</style>
