<script lang="ts">
  import { createEventDispatcher, onDestroy } from "svelte";
  import { bridge } from "../api/bridgeClient";
  import { applyCorrectionProposal, newCorrectionApplicationId } from "../correctionApplication";
  import type {
    AffectedTargetSpan,
    CorrectionEligibility,
    CorrectionApplicationIntent,
    CorrectionIntent,
    CorrectionProposal,
    CorrectionProposalEvent,
    CorrectionReviewContext,
    CorrectionAffectedAnalysisResult,
    AffectedAnalysisState,
  } from "../types/correctionReview";
  import type { AnalysisJobSnapshot } from "../types/analysisJob";
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

  const dispatch = createEventDispatcher<{
    reanalyzed: { result: CorrectionAffectedAnalysisResult };
  }>();

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
  let confirmationOpen = false;
  let application: CorrectionApplicationIntent | null = null;
  let correctionWritesBlocked = false;
  let affectedJob: AnalysisJobSnapshot | null = null;
  let affectedState: AffectedAnalysisState = "NOT_RUN";
  let affectedResult: CorrectionAffectedAnalysisResult | null = null;
  let pollTimer: ReturnType<typeof setTimeout> | null = null;

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
  $: finalVerse = selectedTarget && selectedSpan && selectedProposal
    ? Array.from(selectedTarget.text).slice(0, selectedSpan.startCodePoint).join("")
      + selectedProposal.proposedText
      + Array.from(selectedTarget.text).slice(selectedSpan.endCodePoint).join("")
    : "";
  $: finalDiff = selectedTarget ? graphemeDiff(selectedTarget.text, finalVerse) : [];
  $: proposalBlockingReasons = (eligibility?.reasons ?? []).filter((reason) =>
    reason.code !== "ELIGIBLE"
    && !(reason.code === "CONFLICTING_CORRECTION"
      && proposals.some((item) => item.id === reason.entityId)),
  );
  $: proposalCurrent = Boolean(
    selectedProposal?.lifecycleStatus === "ACTIVE" && proposalBlockingReasons.length === 0,
  );
  $: providerAvailable = Boolean(settings?.hasApiKey);
  $: proposalReviewed = Boolean(
    selectedProposal?.reviewStatus === "HUMAN_MODIFIED"
      || selectedProposal?.reviewStatus === "HUMAN_APPROVED",
  );
  $: mayApply = Boolean(
    proposalCurrent && proposalReviewed && selectedProposal?.verificationStatus === "NOT_RUN",
  );
  $: insertionTarget = context?.currentTargets.find((item) => item.displayedReference === selectedReference)
    ?? context?.currentTargets[0] ?? null;
  $: insertionBoundaries = insertionTarget ? graphemeBoundariesInCodePoints(insertionTarget.text) : [0];
  $: sourceSemanticReferences = correctionSourceReferences(context);
  $: findingDisplayReferences = uniqueReferences(
    context?.findingDisplayedReferences?.length
      ? context.findingDisplayedReferences
      : eligibility?.displayedReferences ?? [],
  );
  $: mayReanalyze = Boolean(
    application?.applicationState === "COMPLETED"
      && selectedProposal?.verificationStatus === "PENDING"
      && !correctionWritesBlocked
      && affectedState !== "RUNNING"
      && affectedState !== "COMPLETED",
  );
  $: relationshipEvidence = correctionRelationshipEvidence(context);

  onDestroy(() => {
    if (pollTimer) clearTimeout(pollTimer);
  });

  function message(exc: unknown): string {
    return exc instanceof Error ? exc.message : String(exc);
  }

  function uniqueReferences(values: unknown): string[] {
    if (!Array.isArray(values)) return [];
    return [...new Set(values.map(String).map((item) => item.trim()).filter(Boolean))];
  }

  function correctionSourceReferences(value: CorrectionReviewContext | null): string[] {
    const explicit = uniqueReferences(value?.sourceSemanticReferences);
    if (explicit.length) return explicit;

    // A rolling/mixed desktop build may briefly pair this frontend with the
    // older 9B.3b sidecar. Source evidence already owns the durable source
    // references; never infer them from the editable target span.
    return uniqueReferences((value?.sourceEvidence ?? []).flatMap((item) => {
      const displayed = uniqueReferences(item.displayedReferences);
      return displayed.length ? displayed : uniqueReferences(item.canonicalReferences);
    }));
  }

  function openApplicationReview(): void {
    if (!selectedProposal || !selectedTarget || !selectedSpan) {
      error = "Correction application context is incomplete. Nothing was applied; reload this finding.";
      return;
    }
    confirmationOpen = true;
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
      application = [...(listed.applications ?? [])].find(
        (item) => item.proposalId === selectedProposalId,
      ) ?? null;
      correctionWritesBlocked = Boolean(listed.correctionWritesBlocked);
      await restoreAffectedJob();
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
    application = [...(listed.applications ?? [])].find(
      (item) => item.proposalId === selectedProposalId,
    ) ?? application;
    correctionWritesBlocked = Boolean(listed.correctionWritesBlocked);
    await restoreAffectedJob();
    await loadHistory(selectedProposalId);
  }

  function correctionRelationshipEvidence(value: CorrectionReviewContext | null): {
    cardinality: string; targetReferences: string[]; realization: string; properties: string[];
  } | null {
    const location = value?.location?.[0];
    if (!location) return null;
    const sourceUnits = uniqueReferences(location.sourceSemanticUnitIds);
    const targetTokens = uniqueReferences(location.targetTokenInstanceIds);
    if (!sourceUnits.length && !targetTokens.length && !location.realization) return null;
    const sourceTokenCount = (value?.sourceEvidence ?? [])
      .filter((item) => sourceUnits.includes(String(item.id ?? "")))
      .reduce((count, item) => count + uniqueReferences(item.tokenInstanceIds).length, 0);
    const sourceCount = sourceTokenCount || sourceUnits.length;
    const targetCount = targetTokens.length;
    const side = (count: number, many: string) => count === 0 ? "null" : count === 1 ? "1" : many;
    return {
      cardinality: `${side(sourceCount, "many")} → ${side(targetCount, "many")}`,
      targetReferences: uniqueReferences(location.displayedReferences),
      realization: String(location.realization ?? "UNCERTAIN"),
      properties: uniqueReferences(location.properties),
    };
  }

  function analysisState(job: AnalysisJobSnapshot | null): AffectedAnalysisState {
    if (!job) return "NOT_RUN";
    if (job.overallStatus === "QUEUED" || job.overallStatus === "RUNNING") return "RUNNING";
    if (job.overallStatus === "COMPLETED_WITH_WARNINGS" && job.searchIncomplete) {
      return "SEARCH_INCOMPLETE";
    }
    if (job.overallStatus === "COMPLETED" || job.overallStatus === "COMPLETED_WITH_WARNINGS") {
      return "COMPLETED";
    }
    return job.overallStatus;
  }

  function latestAffectedJobId(value: CorrectionApplicationIntent | null): string {
    const metadata = value?.resultMetadata as {
      affectedAnalysisJobId?: unknown;
      affectedAnalysisAttempts?: Array<{ analysisJobId?: unknown }>;
    } | undefined;
    const attempts = metadata?.affectedAnalysisAttempts ?? [];
    return String(attempts.at(-1)?.analysisJobId ?? metadata?.affectedAnalysisJobId ?? "");
  }

  async function restoreAffectedJob(): Promise<void> {
    const jobId = latestAffectedJobId(application);
    if (!jobId) {
      affectedJob = null;
      affectedState = "NOT_RUN";
      return;
    }
    try {
      affectedJob = await bridge.analysisJobStatus(jobId);
      affectedState = analysisState(affectedJob);
      const metadata = application?.resultMetadata as {
        affectedAnalysisAttempts?: Array<Record<string, unknown>>;
      } | undefined;
      const attempt = metadata?.affectedAnalysisAttempts?.at(-1) ?? {};
      const requested = affectedJob.requestedScope as unknown as Record<string, unknown>;
      affectedResult = {
        applicationId: application?.applicationId ?? "",
        analysisJobId: affectedJob.jobId,
        resolvedSourceReferences: uniqueReferences(
          attempt.resolvedSourceReferences ?? requested.resolvedSourceReferences,
        ),
        resolvedTargetReferences: uniqueReferences(
          attempt.resolvedTargetReferences ?? requested.resolvedTargetReferences,
        ),
        resolvedStructuralRange: (attempt.resolvedStructuralRange as CorrectionAffectedAnalysisResult["resolvedStructuralRange"] | undefined) ?? {
          startReference: affectedJob.displayedReferences[0] ?? "",
          endReference: affectedJob.displayedReferences.at(-1) ?? "",
          displayedReferences: affectedJob.displayedReferences,
          canonicalReferences: affectedJob.canonicalReferences,
        },
        jobState: affectedState,
        job: affectedJob,
      };
      if (affectedState === "RUNNING") schedulePoll();
    } catch (exc) {
      error = message(exc);
    }
  }

  function schedulePoll(): void {
    if (pollTimer) clearTimeout(pollTimer);
    pollTimer = setTimeout(() => void pollAffected(), 400);
  }

  async function pollAffected(): Promise<void> {
    if (!affectedJob) return;
    try {
      affectedJob = await bridge.analysisJobStatus(affectedJob.jobId);
      affectedState = analysisState(affectedJob);
      if (affectedState === "RUNNING") {
        schedulePoll();
        return;
      }
      if (affectedState === "COMPLETED" || affectedState === "SEARCH_INCOMPLETE") {
        notice = affectedState === "COMPLETED"
          ? "Affected passage re-analysis complete. Current semantic evidence has been refreshed. Correction verification is still pending."
          : "Affected analysis finished with incomplete semantic search. Correction verification is still pending.";
        if (affectedResult) dispatch("reanalyzed", { result: { ...affectedResult, job: affectedJob, jobState: affectedState } });
        const [nextEligibility, nextContext] = await Promise.all([
          bridge.correctionGetEligibility(findingId),
          bridge.correctionGetReviewContext(findingId),
        ]);
        eligibility = nextEligibility;
        context = nextContext;
      } else if (affectedState === "FAILED") {
        error = "Affected passage analysis failed. Scripture remains applied and correction verification remains pending.";
      } else if (affectedState === "CANCELLED") {
        notice = "Affected passage analysis was cancelled. Correction verification remains pending.";
      }
    } catch (exc) {
      error = message(exc);
    }
  }

  async function reanalyzeAffected(retry = false): Promise<void> {
    if (!application || !mayReanalyze) return;
    busy = true;
    error = "";
    try {
      affectedResult = await bridge.correctionReanalyzeAffected({
        applicationId: application.applicationId,
        requestedBy: settings?.reviewerName || "human",
        retry,
      });
      affectedJob = affectedResult.job;
      affectedState = affectedResult.jobState;
      application = await bridge.correctionGetApplicationStatus(application.applicationId);
      notice = affectedState === "RUNNING" ? "Preparing affected analysis…" : notice;
      if (affectedState === "RUNNING") schedulePoll();
    } catch (exc) {
      error = message(exc);
    } finally {
      busy = false;
    }
  }

  async function cancelAffected(): Promise<void> {
    if (!affectedJob || affectedState !== "RUNNING") return;
    busy = true;
    try {
      affectedJob = await bridge.analysisJobCancel(affectedJob.jobId);
      affectedState = analysisState(affectedJob);
      if (affectedState === "RUNNING") schedulePoll();
    } catch (exc) {
      error = message(exc);
    } finally {
      busy = false;
    }
  }

  function stageLabel(job: AnalysisJobSnapshot | null): string {
    if (!job) return "Not run";
    const labels: Record<string, string> = {
      SOURCE_INVENTORY: "Preparing affected analysis…",
      TARGET_INVENTORY: "Building target semantic inventory…",
      LOCATION: "Locating source meaning…",
      MEANING: "Evaluating meaning…",
      QA: "Running QA audit…",
    };
    return affectedState === "RUNNING" ? labels[job.currentStage] ?? "Preparing affected analysis…" : affectedState;
  }

  async function applyCorrection(): Promise<void> {
    if (!selectedProposal || !mayApply) return;
    busy = true;
    error = "";
    const applicationId = application?.applicationId || newCorrectionApplicationId();
    try {
      application = await applyCorrectionProposal({
        findingId,
        findingRevision: eligibility?.findingRevision || findingRevision,
        proposal: selectedProposal,
        actorId: settings?.reviewerName || "human",
        applicationId,
      });
      confirmationOpen = false;
      if (application.applicationState === "COMPLETED") {
        notice = "Scripture updated. Semantic verification is pending.";
        const [nextEligibility, nextContext] = await Promise.all([
          bridge.correctionGetEligibility(findingId),
          bridge.correctionGetReviewContext(findingId),
        ]);
        eligibility = nextEligibility;
        context = nextContext;
        await reloadProposals(selectedProposal.id);
      } else {
        notice = `Correction application: ${application.applicationState}`;
      }
    } catch (exc) {
      if (/revision[_ ]conflict|REVISION_CONFLICT/i.test(message(exc))) {
        confirmationOpen = false;
        await loadAll(loadedReviewKey);
        error = "Scripture changed since this correction was reviewed. Nothing was applied; review the current text and create a new proposal.";
      } else {
        error = message(exc);
      }
    } finally {
      busy = false;
    }
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
      <p>Review wording first; Scripture changes only through explicit Apply confirmation.</p>
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
          {#if relationshipEvidence}
            <dl class="relationship-truth">
              <dt>Source semantic reference</dt><dd>{sourceSemanticReferences.join(", ") || "Unavailable"}</dd>
              <dt>Target realization</dt><dd>{relationshipEvidence.targetReferences.join(", ") || selectedSpan?.displayedReference}</dd>
              <dt>Cardinality</dt><dd>{relationshipEvidence.cardinality}</dd>
              <dt>Realization</dt><dd>{relationshipEvidence.realization === "NOT_LOCATED" ? "No realization located · NOT_LOCATED" : relationshipEvidence.realization}</dd>
              {#if relationshipEvidence.properties.length}
                <dt>Properties</dt><dd>{relationshipEvidence.properties.join(" · ")}</dd>
              {/if}
            </dl>
          {/if}
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
            {#if mayApply}
              <button type="button" class="apply" disabled={busy} on:click={openApplicationReview}>Review application</button>
            {/if}
          </div>
        {/if}
        {#if selectedProposal && !proposalReviewed && proposalCurrent}
          <p class="boundary">Edit or choose this wording to record human review before application.</p>
        {:else if application?.applicationState === "COMPLETED" && affectedState === "NOT_RUN"}
          <p class="boundary">Verification PENDING. No affected analysis was started.</p>
        {:else if application?.applicationState === "COMPLETED"}
          <p class="boundary">Verification PENDING. Affected analysis never marks a correction verified.</p>
        {:else}
          <p class="boundary">Scripture changes only after the separate confirmation below.</p>
        {/if}

        {#if application}
          <div class="affected-analysis" aria-label="Correction follow-up status">
            <dl>
              <dt>Correction application</dt><dd>{application.applicationState}</dd>
              <dt>Semantic verification</dt><dd>{selectedProposal?.verificationStatus ?? "NOT_RUN"}</dd>
              <dt>Affected analysis</dt><dd>{stageLabel(affectedJob)}</dd>
            </dl>
            {#if mayReanalyze}
              <button
                type="button"
                class="apply"
                disabled={busy}
                on:click={() => reanalyzeAffected(affectedState !== "NOT_RUN")}
              >{affectedState === "NOT_RUN" ? "Re-analyze affected passage" : "Retry affected analysis"}</button>
            {/if}
            {#if correctionWritesBlocked}
              <p class="boundary">Affected analysis is unavailable until correction recovery is healthy.</p>
            {/if}
            {#if affectedState === "RUNNING"}
              <button type="button" class="secondary" disabled={busy} on:click={cancelAffected}>Cancel affected analysis</button>
            {/if}
          </div>
        {/if}
      </div>

      {#if confirmationOpen && selectedProposal && selectedTarget && selectedSpan}
        <div class="confirm-backdrop" role="presentation">
          <section class="confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="apply-title">
            <h5 id="apply-title">Confirm correction application</h5>
            <p><strong>Source semantic reference:</strong> {sourceSemanticReferences.join(", ") || "Unavailable"}</p>
            {#if findingDisplayReferences.length
              && findingDisplayReferences.join("|") !== sourceSemanticReferences.join("|")}
              <p><strong>Finding display reference:</strong> {findingDisplayReferences.join(", ")}</p>
            {/if}
            <p><strong>Target verse:</strong> {selectedSpan.displayedReference}</p>
            <p><strong>{selectedSpan.startCodePoint === selectedSpan.endCodePoint ? "Insertion point" : "Affected span"}:</strong> [{selectedSpan.startCodePoint}, {selectedSpan.endCodePoint})</p>
            <h6>CURRENT</h6>
            <p class="scripture confirmation-text">{selectedTarget.text}</p>
            <h6>PROPOSED FINAL</h6>
            <p class="scripture confirmation-text">{finalVerse}</p>
            <div class="diff" aria-label="Final verse diff">
              {#each finalDiff as part}
                {#if part.kind === "removed"}<del>{part.text}</del>{:else if part.kind === "inserted"}<ins>{part.text}</ins>{:else}<span>{part.text}</span>{/if}
              {/each}
            </div>
            <p class="apply-warning">Applying changes this one exact span. Word Alignment becomes invalid/reviewable. Semantic verification is a separate later step and will remain pending.</p>
            <div class="buttons">
              <button type="button" class="apply" disabled={busy} on:click={applyCorrection}>{busy ? "Applying…" : "Apply correction"}</button>
              <button type="button" class="secondary" disabled={busy} on:click={() => (confirmationOpen = false)}>Cancel</button>
            </div>
          </section>
        </div>
      {/if}
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
  .review-actions { position: sticky; z-index: 3; isolation: isolate; bottom: 0; padding: .65rem .75rem; border-top: 1px solid #dbeafe; background: #f8faff; pointer-events: auto; }
  .review-actions textarea, .review-actions button { position: relative; z-index: 1; pointer-events: auto; }
  label, legend { font-size: .76rem; color: #374151; }
  textarea, select, input[type="range"] { width: 100%; box-sizing: border-box; font: inherit; margin: .18rem 0 .45rem; }
  textarea, select { border: 1px solid #cbd5e1; border-radius: 4px; padding: .35rem .45rem; resize: vertical; }
  fieldset { border: 1px solid #dbeafe; margin: .4rem 0; display: grid; gap: .3rem; }
  .buttons { display: flex; flex-wrap: wrap; gap: .4rem; margin: .4rem 0; }
  button { font: inherit; font-size: .77rem; border: 1px solid #2563eb; color: #1d4ed8; background: #fff; border-radius: 4px; padding: .35rem .6rem; cursor: pointer; }
  button.secondary { border-color: #94a3b8; color: #334155; }
  button.danger { border-color: #dc2626; color: #b91c1c; }
  button.apply { background: #1d4ed8; color: #fff; font-weight: 650; }
  button:disabled { opacity: .5; cursor: not-allowed; }
  button:focus-visible, textarea:focus-visible, select:focus-visible, input:focus-visible { outline: 2px solid #2563eb; outline-offset: 2px; }
  .create { margin: .75rem; align-self: flex-start; }
  .draft-form { margin-top: .6rem; max-height: 22rem; overflow-y: auto; padding-right: .25rem; }
  .unavailable ul { margin-bottom: 0; padding-left: 1.2rem; }
  .boundary { margin-top: .35rem; }
  .affected-analysis { margin-top: .55rem; padding-top: .55rem; border-top: 1px solid #dbeafe; }
  .affected-analysis dl, .relationship-truth { margin: 0 0 .45rem; }
  .confirm-backdrop { position: fixed; inset: 0; z-index: 50; background: rgba(15, 23, 42, .55); display: grid; place-items: center; padding: 1rem; pointer-events: auto; }
  .confirm-dialog { width: min(42rem, 100%); max-height: calc(100vh - 2rem); overflow-y: auto; background: #fff; border-radius: 8px; padding: 1rem; box-shadow: 0 20px 50px rgba(15,23,42,.35); }
  .confirmation-text { border: 1px solid #e2e8f0; border-radius: 4px; padding: .5rem; }
  .apply-warning { margin-top: .75rem; padding: .55rem; border-left: 4px solid #d97706; background: #fffbeb; font-size: .78rem; }
  @media (max-width: 900px) {
    .review-scroll { max-height: 19rem; }
    dl { grid-template-columns: 1fr; gap: .1rem; }
    dd { margin-bottom: .35rem; }
  }
</style>
