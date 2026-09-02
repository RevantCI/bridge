<script lang="ts">
  import VirtualPassageStream from "./VirtualPassageStream.svelte";
  import { bridge } from "../api/bridgeClient";
  import type {
    SemanticLocationRun,
    TargetSemanticInventory,
  } from "../types/passageSemanticV1";
  import type { PassageVerse, QaFindingDetail } from "../types/qaReview";

  /**
   * Passage mode: the target passage as a scrollable stream, with the focused
   * relationship highlighted.
   *
   * Loads read-only: the location run and target inventory the focused
   * finding already points at. Nothing here re-runs analysis.
   */
  export let detail: QaFindingDetail | null = null;

  type FilterId =
    | "linked" | "unlinked" | "crossVerse" | "splitMerged"
    | "findings" | "reviewed" | "stale";

  const FILTERS: Array<{ id: FilterId; label: string }> = [
    { id: "linked", label: "Linked only" },
    { id: "unlinked", label: "Unlinked only" },
    { id: "crossVerse", label: "Cross-verse" },
    { id: "splitMerged", label: "Split / merged" },
    { id: "findings", label: "Has a possible issue" },
    { id: "reviewed", label: "Human-reviewed" },
    { id: "stale", label: "Stale" },
  ];

  let active = new Set<FilterId>();
  let verses: PassageVerse[] = [];
  let focusedRelationshipIds: string[] = [];
  let expandedReference = "";
  let loading = false;
  let error = "";
  let loadedRunId = "";
  let relationshipCount = 0;
  let embeddingsAvailable = true;

  // Reload whenever the focused finding points at a different location run.
  $: runId = String(detail?.location?.[0]?.location?.runId ?? "");
  $: if (runId && runId !== loadedRunId) void load(runId);
  $: if (!runId) {
    verses = [];
    loadedRunId = "";
  }
  $: focusedRelationshipIds = (detail?.location ?? [])
    .map((entry) => String(entry.location?.id ?? ""))
    .filter(Boolean);

  async function load(id: string): Promise<void> {
    loading = true;
    error = "";
    try {
      const run = await bridge.semanticLocationGetRange(id);
      const inventory = run.targetInventoryId
        ? await bridge.targetSemanticGetRange(run.targetInventoryId)
        : null;
      verses = buildVerses(run, inventory);
      relationshipCount = run.relationships?.length ?? 0;
      embeddingsAvailable = Boolean(run.embeddingProvider?.available);
      loadedRunId = id;
      expandedReference = "";
    } catch (cause) {
      error = String(cause);
      verses = [];
    } finally {
      loading = false;
    }
  }

  /**
   * Rebuild the passage from the inventory's tokens, in document order.
   *
   * A relationship carries target token ids rather than references, so the
   * link from a relationship to the verse it lands in runs through the
   * tokens. That is also what makes cross-verse realization visible: one
   * relationship's tokens can fall in more than one verse.
   */
  function buildVerses(
    run: SemanticLocationRun, inventory: TargetSemanticInventory | null,
  ): PassageVerse[] {
    const tokens = inventory?.tokens ?? [];
    const order: string[] = [];
    const words = new Map<string, string[]>();
    const referenceByToken = new Map<string, string>();

    for (const token of tokens) {
      const reference = token.displayedReference;
      if (!reference) continue;
      if (!words.has(reference)) {
        words.set(reference, []);
        order.push(reference);
      }
      words.get(reference)!.push(token.rawForm);
      referenceByToken.set(token.id, reference);
    }

    const perVerse = new Map<string, PassageVerse>();
    for (const reference of order) {
      perVerse.set(reference, {
        reference,
        text: (words.get(reference) ?? []).join(" ").replace(/\s+([,.;:!?])/g, "$1"),
        relationshipIds: [],
        linked: false,
        crossVerse: false,
        splitOrMerged: false,
        hasFinding: false,
        reviewed: false,
        stale: false,
      });
    }

    for (const relationship of run.relationships ?? []) {
      const references = new Set(
        (relationship.targetTokenInstanceIds ?? [])
          .map((tokenId) => referenceByToken.get(tokenId))
          .filter((reference): reference is string => Boolean(reference)),
      );
      const properties = relationship.properties ?? [];
      for (const reference of references) {
        const verse = perVerse.get(reference);
        if (!verse) continue;
        verse.relationshipIds.push(relationship.id);
        verse.linked = true;
        if (properties.includes("CROSS_VERSE")) verse.crossVerse = true;
        if (properties.includes("SPLIT") || properties.includes("MERGED")) {
          verse.splitOrMerged = true;
        }
        if (String(relationship.reviewStatus).startsWith("HUMAN")) verse.reviewed = true;
        if (relationship.lifecycleStatus === "STALE") verse.stale = true;
      }
    }

    for (const reference of detail?.finding?.displayedReferences ?? []) {
      const verse = perVerse.get(reference);
      if (verse) verse.hasFinding = true;
    }

    return order.map((reference) => perVerse.get(reference)!);
  }

  function toggleFilter(id: FilterId): void {
    const next = new Set(active);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    active = next;
  }

  $: filtered = verses.filter((verse) => {
    if (active.has("linked") && !verse.linked) return false;
    if (active.has("unlinked") && verse.linked) return false;
    if (active.has("crossVerse") && !verse.crossVerse) return false;
    if (active.has("splitMerged") && !verse.splitOrMerged) return false;
    if (active.has("findings") && !verse.hasFinding) return false;
    if (active.has("reviewed") && !verse.reviewed) return false;
    if (active.has("stale") && !verse.stale) return false;
    return true;
  });
</script>

<div class="passage">
  {#if !detail}
    <p class="state">
      Select a possible issue in <strong>QA</strong> mode to see its passage in context.
    </p>
  {:else if loading}
    <p class="state" role="status">Loading the passage…</p>
  {:else if error}
    <p class="state error" role="alert">{error}</p>
  {:else if verses.length === 0}
    <p class="state">
      This finding has no located passage to display. Findings whose meaning was never
      located carry no target position to show here.
    </p>
  {:else}
    <div class="filters" role="group" aria-label="Filter the passage">
      {#each FILTERS as filter}
        <button
          type="button"
          class="chip"
          aria-pressed={active.has(filter.id)}
          on:click={() => toggleFilter(filter.id)}
        >{filter.label}</button>
      {/each}
    </div>

    {#if !embeddingsAvailable}
      <p class="notice">
        This run had no embedding provider available, so Bridge relied on lexical and
        structural evidence alone. It found {relationshipCount}
        {relationshipCount === 1 ? "relationship" : "relationships"} in this passage —
        sparse linking here reflects that limit, not the translation.
      </p>
    {/if}

    <VirtualPassageStream
      verses={filtered}
      {focusedRelationshipIds}
      bind:expandedReference
      on:expand={(event) => (expandedReference = event.detail.reference)}
    />
  {/if}
</div>

<style>
  .passage { display: flex; flex-direction: column; min-height: 0; height: 100%; }
  .state { padding: 1.2rem; color: #6b7280; font-size: 0.85rem; }
  .state.error { color: #9b1c1c; }

  .filters {
    display: flex;
    flex-wrap: wrap;
    gap: 0.25rem;
    padding: 0.45rem 0.6rem;
    border-bottom: 1px solid #e5e7eb;
    flex: none;
    max-height: 5rem;
    overflow-y: auto;
  }

  .chip {
    font: inherit;
    font-size: 0.72rem;
    padding: 0.15rem 0.5rem;
    border: 1px solid #d1d5db;
    border-radius: 999px;
    background: #fff;
    color: #374151;
    cursor: pointer;
  }

  .chip[aria-pressed="true"] {
    border-color: #1d4ed8;
    border-width: 2px;
    padding: 0.1rem 0.45rem;
    background: #eff6ff;
    color: #1d4ed8;
    font-weight: 600;
  }

  .chip:focus-visible { outline: 2px solid #2563eb; outline-offset: 1px; }

  /* Sparse linking is usually a capability limit, not a translation problem.
     Saying so prevents the stream from reading as an indictment. */
  .notice {
    margin: 0;
    padding: 0.4rem 0.6rem;
    font-size: 0.76rem;
    background: #fffbeb;
    color: #78350f;
    border-bottom: 1px solid #fde68a;
    flex: none;
  }
</style>
