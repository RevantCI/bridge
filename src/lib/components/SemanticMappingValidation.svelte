<script lang="ts">
  import { onMount } from "svelte";
  import { bridge } from "../api/bridgeClient";
  import type {
    SemanticMapping, SemanticValidationCandidate, SemanticValidationCorrection,
    SemanticValidationQueue, SemanticValidationStatus,
  } from "../types/finding";

  export let onClose: () => void;
  export let onNavigate: (chapter: string, verse: string) => void;

  let queue: SemanticValidationQueue | null = null;
  let loading = true;
  let error = "";
  let reviewer = "";
  let statusFilter: SemanticValidationStatus | "ALL" = "UNCONFIRMED";
  let relationshipFilter = "ALL";
  let search = "";
  let busyId = "";
  let editingId = "";
  let editSpans = "";
  let editRelationships = "";
  let editMeaning: SemanticMapping["meaning_status"] = "PRESERVED";
  let editConfidence = 0.9;
  let notes: Record<string, string> = {};

  const statusLabel: Record<SemanticValidationStatus, string> = {
    UNCONFIRMED: "Unconfirmed",
    HUMAN_CONFIRMED: "Human confirmed",
    HUMAN_REJECTED: "Human rejected",
    HUMAN_CORRECTED: "Human corrected",
  };

  onMount(() => {
    void (async () => {
      try {
        const settings = await bridge.getSettings();
        reviewer = settings.reviewerName || settings.paratextUsername || "";
      } catch {
        // The reviewer can enter a name directly even when settings are unavailable.
      }
      await load();
    })();
  });

  async function load(): Promise<void> {
    loading = true;
    error = "";
    try {
      queue = await bridge.listSemanticValidationCandidates();
    } catch (caught) {
      error = caught instanceof Error ? caught.message : String(caught);
    } finally {
      loading = false;
    }
  }

  $: normalizedSearch = search.trim().toLocaleLowerCase();
  $: filtered = (queue?.candidates ?? []).filter((candidate) => {
    if (statusFilter !== "ALL" && candidate.validationStatus !== statusFilter) return false;
    if (relationshipFilter !== "ALL" && !candidate.relationships.includes(relationshipFilter)) return false;
    if (!normalizedSearch) return true;
    return [
      candidate.sourceUnit.source_reference,
      candidate.sourceUnit.source_quote,
      candidate.sourceUnit.group_id,
      candidate.targetSpans.map((span) => `${span.reference} ${span.quote}`).join(" "),
      candidate.evidence.explanation,
    ].join(" ").toLocaleLowerCase().includes(normalizedSearch);
  });

  function noteFor(candidateId: string): string {
    return notes[candidateId] ?? "";
  }

  function setNote(candidateId: string, value: string): void {
    notes = { ...notes, [candidateId]: value };
  }

  function beginCorrection(candidate: SemanticValidationCandidate): void {
    editingId = candidate.candidateId;
    const mapping = candidate.reviewDecision?.mapping;
    const spans = mapping?.target_spans ?? candidate.targetSpans;
    editSpans = spans.map((span) => (
      `${span.reference} | ${span.quote} | ${span.start ?? ""} | ${span.end ?? ""}`
    )).join("\n");
    editRelationships = (mapping?.relationships ?? candidate.relationships).join(", ");
    editMeaning = mapping?.meaning_status ?? candidate.meaningStatus;
    editConfidence = mapping?.confidence ?? candidate.confidence;
    error = "";
  }

  function parseCorrection(): SemanticValidationCorrection {
    const relationships = editRelationships.split(",").map((item) => item.trim()).filter(Boolean);
    const target_spans = editSpans.split(/\r?\n/).filter((line) => line.trim()).map((line) => {
      const parts = line.split("|").map((item) => item.trim());
      const [reference, quote, rawStart = "", rawEnd = ""] = parts;
      if (!reference || !quote) throw new Error("Every corrected target span needs a reference and exact quote.");
      const start = rawStart === "" ? null : Number(rawStart);
      const end = rawEnd === "" ? null : Number(rawEnd);
      if ((start === null) !== (end === null) || (start !== null && (!Number.isInteger(start) || !Number.isInteger(end)))) {
        throw new Error("Supply both integer offsets or leave both blank.");
      }
      return { reference, quote, start, end };
    });
    if (!relationships.length) throw new Error("At least one semantic relationship is required.");
    if (!target_spans.length && !relationships.some((item) => ["IMPLICIT", "GRAMMATICALLY_ENCODED"].includes(item))) {
      throw new Error("An overt mapping needs at least one exact target span.");
    }
    return { target_spans, relationships, meaning_status: editMeaning, confidence: Number(editConfidence) };
  }

  function displaySpans(candidate: SemanticValidationCandidate) {
    return candidate.reviewDecision?.mapping?.target_spans ?? candidate.targetSpans;
  }

  function displayRelationships(candidate: SemanticValidationCandidate): string[] {
    return candidate.reviewDecision?.mapping?.relationships ?? candidate.relationships;
  }

  async function decide(
    candidate: SemanticValidationCandidate,
    decision: "confirmed" | "rejected" | "corrected" | "unsure",
  ): Promise<void> {
    if (!reviewer.trim()) {
      error = "Enter the reviewer name before recording a validation decision.";
      return;
    }
    let correction: SemanticValidationCorrection | undefined;
    try {
      if (decision === "corrected") correction = parseCorrection();
    } catch (caught) {
      error = caught instanceof Error ? caught.message : String(caught);
      return;
    }
    busyId = candidate.candidateId;
    error = "";
    try {
      await bridge.decideSemanticValidationCandidate(
        candidate.candidateId, decision, reviewer.trim(), noteFor(candidate.candidateId), correction,
      );
      editingId = "";
      await load();
    } catch (caught) {
      error = caught instanceof Error ? caught.message : String(caught);
    } finally {
      busyId = "";
    }
  }

  function navigate(reference: string): void {
    const match = reference.match(/^[A-Z0-9]+\s+([^:]+):([^\s-]+)/i);
    if (match) onNavigate(match[1], match[2]);
  }
</script>

<div class="screen">
  <header>
    <div>
      <div class="eyebrow">ADVANCED · STAGE 3 VALIDATION</div>
      <h1>Semantic mapping validation</h1>
      <p>Confirm, reject, or correct machine-proposed passage mappings. These decisions never rewrite Scripture or translationCore selections.</p>
    </div>
    <button class="close" on:click={onClose}>Back to dashboard</button>
  </header>

  {#if error}<div class="error" role="alert">{error}</div>{/if}

  {#if loading}
    <div class="empty">Loading the validation queue…</div>
  {:else if !queue?.available}
    <div class="empty">No bundled validation candidates apply to the currently open book. Open IRVTam Luke or Philippians from this collection.</div>
  {:else if queue}
    <section class="summary" aria-label="Validation progress">
      <div><strong>{queue.summary.total}</strong><span>{queue.book} candidates</span></div>
      <div><strong>{queue.summary.counts.UNCONFIRMED ?? 0}</strong><span>Unconfirmed</span></div>
      <div><strong>{queue.summary.counts.HUMAN_CONFIRMED ?? 0}</strong><span>Confirmed</span></div>
      <div><strong>{queue.summary.counts.HUMAN_CORRECTED ?? 0}</strong><span>Corrected</span></div>
      <div><strong>{queue.summary.counts.HUMAN_REJECTED ?? 0}</strong><span>Rejected</span></div>
      <div><strong>{queue.calibration.reviewed}/20</strong><span>Initial review target</span></div>
      {#if queue.calibration.proposalAgreementPercent !== null}
        <div><strong>{queue.calibration.proposalAgreementPercent}%</strong><span>Proposal agreement</span></div>
      {/if}
      <small>Model {queue.model} · manifest {queue.manifestSha256.slice(0, 12)}…</small>
    </section>

    <section class="controls" aria-label="Validation filters">
      <label>Reviewer<input bind:value={reviewer} placeholder="Required audit identity" /></label>
      <label>Status<select bind:value={statusFilter}>
        <option value="ALL">All statuses</option>
        <option value="UNCONFIRMED">Unconfirmed</option>
        <option value="HUMAN_CONFIRMED">Human confirmed</option>
        <option value="HUMAN_CORRECTED">Human corrected</option>
        <option value="HUMAN_REJECTED">Human rejected</option>
      </select></label>
      <label>Relationship<select bind:value={relationshipFilter}>
        <option value="ALL">All relationships</option>
        {#each queue.relationships as relationship}<option value={relationship}>{relationship}</option>{/each}
      </select></label>
      <label class="search">Search<input bind:value={search} placeholder="Reference, source, target or explanation" /></label>
    </section>

    <div class="result-count">Showing {filtered.length} of {queue.summary.total}</div>
    <section class="candidate-list" aria-label="Mapping candidates">
      {#each filtered as candidate (candidate.candidateId)}
        <article class="candidate" class:mismatch={!candidate.projectMatch}>
          <div class="candidate-head">
            <span class="rank">#{candidate.rank}</span>
            <strong>{candidate.sourceUnit.source_reference}</strong>
            <span class="tool">{candidate.sourceUnit.tool === "translationWords" ? "tW" : "tN"} · {candidate.sourceUnit.group_id}</span>
            <span class="status" data-status={candidate.validationStatus}>{statusLabel[candidate.validationStatus]}</span>
          </div>

          <div class="mapping-grid">
            <div class="evidence-block">
              <small>Original-language source</small>
              <div class="source" dir="auto">{candidate.sourceUnit.source_quote}</div>
              {#if candidate.sourceUnit.note}<p>{candidate.sourceUnit.note}</p>{/if}
            </div>
            <div class="arrow">→</div>
            <div class="evidence-block">
              <small>Exact imported-USFM target span{candidate.targetSpans.length === 1 ? "" : "s"}</small>
              {#each displaySpans(candidate) as span}
                <button class="span" on:click={() => navigate(span.reference)}>
                  <b>{span.reference}</b><span dir="auto">{span.quote}</span>
                </button>
              {:else}
                <span class="implicit">No overt target span — review the implicit or grammatical realization.</span>
              {/each}
            </div>
          </div>

          <div class="relations">
            {#each displayRelationships(candidate) as relationship}<span>{relationship}</span>{/each}
            <span class="confidence">Model confidence {Math.round(candidate.confidence * 100)}%</span>
          </div>
          <p class="explanation">{candidate.evidence.explanation}</p>

          {#if !candidate.projectMatch}
            <div class="warning">This proposal no longer exactly matches the open project: {candidate.projectMatchError}</div>
          {/if}
          {#if candidate.reviewDecision}
            <div class="audit">
              Latest decision by {candidate.reviewDecision.reviewer} · {new Date(candidate.reviewDecision.at).toLocaleString()}
              {#if candidate.reviewDecision.note}<br />{candidate.reviewDecision.note}{/if}
            </div>
          {/if}

          <label class="note">Reviewer note<textarea value={noteFor(candidate.candidateId)} on:input={(event) => setNote(candidate.candidateId, event.currentTarget.value)} placeholder="Evidence for this decision (recommended)" /></label>

          {#if editingId === candidate.candidateId}
            <div class="correction">
              <label>Target spans: reference | exact quote | start | end (offsets optional)<textarea bind:value={editSpans} /></label>
              <label>Relationships, comma-separated<input bind:value={editRelationships} /></label>
              <div class="correction-row">
                <label>Meaning<select bind:value={editMeaning}>
                  <option value="PRESERVED">Preserved</option>
                  <option value="PARTIALLY_PRESERVED">Partially preserved</option>
                  <option value="POSSIBLE_PROBLEM">Possible problem</option>
                  <option value="NOT_LOCATED">Not located</option>
                  <option value="UNCERTAIN">Uncertain</option>
                </select></label>
                <label>Confidence<input type="number" min="0" max="1" step="0.01" bind:value={editConfidence} /></label>
              </div>
              <div class="actions">
                <button class="primary" on:click={() => decide(candidate, "corrected")} disabled={Boolean(busyId)}>Save corrected mapping</button>
                <button on:click={() => (editingId = "")}>Cancel correction</button>
              </div>
            </div>
          {:else}
            <div class="actions">
              <button class="primary" on:click={() => decide(candidate, "confirmed")} disabled={Boolean(busyId) || !candidate.projectMatch}>Confirm exact mapping</button>
              <button on:click={() => beginCorrection(candidate)} disabled={Boolean(busyId)}>Correct</button>
              <button class="danger" on:click={() => decide(candidate, "rejected")} disabled={Boolean(busyId)}>Reject</button>
              <button on:click={() => decide(candidate, "unsure")} disabled={Boolean(busyId)}>Needs discussion</button>
              {#if busyId === candidate.candidateId}<span class="saving">Saving…</span>{/if}
            </div>
          {/if}
        </article>
      {:else}
        <div class="empty">No candidates match these filters.</div>
      {/each}
    </section>
  {/if}
</div>

<style>
  .screen { flex: 1; overflow: auto; background: var(--surface-2); padding-bottom: 40px; }
  header { display: flex; align-items: flex-start; justify-content: space-between; gap: 24px; padding: 24px 32px 18px; background: var(--surface); border-bottom: 1px solid var(--border); }
  header > div { max-width: 760px; }
  .eyebrow { color: var(--accent); font-size: 9px; letter-spacing: .12em; font-weight: 800; margin-bottom: 6px; }
  h1 { margin: 0; font-size: 21px; color: var(--text); }
  header p { margin: 7px 0 0; font-size: 11px; line-height: 1.5; color: var(--text-2); }
  button { font: inherit; cursor: pointer; }
  .close, .actions button { border: 1px solid var(--border-strong); border-radius: 6px; background: var(--surface); color: var(--text); padding: 7px 11px; font-size: 10px; }
  .error, .empty { max-width: 1050px; margin: 16px auto; box-sizing: border-box; border-radius: 8px; padding: 12px 14px; font-size: 11px; }
  .error { color: var(--danger); background: var(--danger-bg); }
  .empty { color: var(--text-2); background: var(--surface); }
  .summary, .controls, .candidate-list, .result-count { max-width: 1050px; margin-left: auto; margin-right: auto; box-sizing: border-box; }
  .summary { margin-top: 16px; background: var(--surface); border: 1px solid var(--border); border-radius: 9px; padding: 12px 14px; display: flex; align-items: center; gap: 22px; }
  .summary div { display: flex; flex-direction: column; gap: 2px; min-width: 72px; }
  .summary strong { font-size: 17px; color: var(--text); }
  .summary span, .summary small { font-size: 9px; color: var(--text-2); }
  .summary small { margin-left: auto; }
  .controls { margin-top: 10px; padding: 12px 14px; display: grid; grid-template-columns: 1fr 150px 210px 2fr; gap: 10px; background: var(--surface); border: 1px solid var(--border); border-radius: 9px; }
  label { display: flex; flex-direction: column; gap: 4px; color: var(--text-2); font-size: 9px; font-weight: 600; }
  input, select, textarea { box-sizing: border-box; width: 100%; border: 1px solid var(--border); border-radius: 5px; padding: 6px 7px; color: var(--text); background: var(--surface); font: inherit; font-size: 10px; }
  textarea { min-height: 54px; resize: vertical; }
  .result-count { color: var(--text-2); font-size: 9px; padding: 10px 2px 5px; }
  .candidate-list { display: flex; flex-direction: column; gap: 10px; }
  .candidate { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 13px 14px; }
  .candidate.mismatch { border-color: var(--warning); }
  .candidate-head { display: flex; align-items: center; gap: 8px; font-size: 11px; }
  .rank { color: var(--text-3); font-size: 9px; }
  .tool { color: var(--text-2); font-size: 9px; }
  .status { margin-left: auto; border-radius: 999px; padding: 3px 7px; font-size: 8px; font-weight: 700; color: var(--warning); background: var(--warning-bg); }
  .status[data-status="HUMAN_CONFIRMED"], .status[data-status="HUMAN_CORRECTED"] { color: var(--gr); background: var(--gr-bg); }
  .status[data-status="HUMAN_REJECTED"] { color: var(--danger); background: var(--danger-bg); }
  .mapping-grid { display: grid; grid-template-columns: minmax(0, 1fr) 24px minmax(0, 1.4fr); gap: 8px; margin-top: 10px; align-items: center; }
  .evidence-block { border: 1px solid var(--border); border-radius: 7px; padding: 8px; min-height: 50px; }
  .evidence-block small { display: block; color: var(--text-3); font-size: 8px; margin-bottom: 5px; }
  .evidence-block .source { font-size: 13px; font-weight: 600; }
  .evidence-block p, .explanation { font-size: 10px; line-height: 1.45; color: var(--text-2); }
  .arrow { text-align: center; color: var(--accent); }
  .span { display: flex; align-items: baseline; gap: 7px; width: 100%; text-align: left; border: 0; background: transparent; padding: 3px 0; color: var(--text); }
  .span b { color: var(--accent); font-size: 9px; flex-shrink: 0; }
  .span span { font-size: 11px; }
  .implicit { display: block; color: var(--text-2); font-size: 9px; line-height: 1.4; }
  .relations { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 8px; }
  .relations span { font-size: 8px; border-radius: 999px; padding: 3px 6px; background: var(--accent-bg); color: var(--accent); }
  .relations .confidence { margin-left: auto; background: var(--surface-2); color: var(--text-2); }
  .explanation { margin: 8px 0; }
  .warning, .audit { border-radius: 6px; padding: 7px 8px; font-size: 9px; line-height: 1.4; margin: 7px 0; }
  .warning { color: var(--warning); background: var(--warning-bg); }
  .audit { color: var(--gr); background: var(--gr-bg); }
  .note { margin-top: 8px; }
  .actions { display: flex; align-items: center; flex-wrap: wrap; gap: 7px; margin-top: 9px; }
  .actions button.primary { color: #fff; background: var(--accent); border-color: var(--accent); }
  .actions button.danger { color: var(--danger); border-color: var(--danger); }
  .actions button:disabled { opacity: .5; cursor: not-allowed; }
  .saving { color: var(--text-2); font-size: 9px; }
  .correction { margin-top: 9px; padding: 10px; border: 1px solid var(--accent); border-radius: 7px; background: var(--accent-bg); display: flex; flex-direction: column; gap: 8px; }
  .correction-row { display: grid; grid-template-columns: 2fr 1fr; gap: 8px; }
  @media (max-width: 800px) {
    header { padding: 18px; }
    .summary, .controls, .candidate-list, .result-count, .error, .empty { margin-left: 12px; margin-right: 12px; }
    .summary { flex-wrap: wrap; }
    .summary small { width: 100%; margin-left: 0; }
    .controls { grid-template-columns: 1fr 1fr; }
    .search { grid-column: 1 / -1; }
    .mapping-grid { grid-template-columns: 1fr; }
    .arrow { transform: rotate(90deg); }
  }
</style>
