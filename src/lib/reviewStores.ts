import { derived, get, writable } from "svelte/store";

import { bridge } from "./api/bridgeClient";
import type {
  QaDisposition,
  QaFindingDetail,
  QaFindingSummary,
  ReviewQueueFilters,
  ReviewQueueOrder,
  ReviewerDecision,
} from "./types/qaReview";

/**
 * State for the Stage 9A review queue.
 *
 * The queue is paged by cursor rather than loaded whole: a book's findings
 * can run to thousands, and the review UI must never hold the entire
 * semantic graph in memory. Pages accumulate as the reviewer scrolls, and
 * any filter change starts a fresh queue rather than filtering in place.
 */

export interface ReviewFilters {
  book: string;
  chapter: number | null;
  kinds: string[];
  severities: string[];
  dispositions: QaDisposition[];
  lifecycleStatuses: string[];
  order: ReviewQueueOrder;
}

export const EMPTY_FILTERS: ReviewFilters = {
  book: "",
  chapter: null,
  kinds: [],
  severities: [],
  dispositions: [],
  lifecycleStatuses: [],
  order: "CANONICAL",
};

const PAGE_SIZE = 50;

export const reviewFilters = writable<ReviewFilters>({ ...EMPTY_FILTERS });
export const reviewQueue = writable<QaFindingSummary[]>([]);
export const reviewTotal = writable(0);
export const reviewCursor = writable("");
export const reviewLoading = writable(false);
export const reviewError = writable("");

export const selectedFindingId = writable<string | null>(null);
export const selectedDetail = writable<QaFindingDetail | null>(null);
export const detailLoading = writable(false);
export const detailError = writable("");

/** True while more pages remain behind the current cursor. */
export const hasMoreFindings = derived(reviewCursor, ($cursor) => $cursor !== "");

export const selectedIndex = derived(
  [reviewQueue, selectedFindingId],
  ([$queue, $id]) => ($id ? $queue.findIndex((item) => item.id === $id) : -1),
);

function toQueryFilters(filters: ReviewFilters, cursor: string): ReviewQueueFilters {
  return {
    book: filters.book || undefined,
    chapter: filters.chapter ?? undefined,
    kinds: filters.kinds.length ? filters.kinds : undefined,
    severities: filters.severities.length ? (filters.severities as never) : undefined,
    dispositions: filters.dispositions.length ? filters.dispositions : undefined,
    lifecycleStatuses: filters.lifecycleStatuses.length
      ? (filters.lifecycleStatuses as never)
      : undefined,
    order: filters.order,
    limit: PAGE_SIZE,
    cursor: cursor || undefined,
  };
}

/** Load the first page for the current filters, discarding anything held. */
export async function loadQueue(): Promise<void> {
  reviewLoading.set(true);
  reviewError.set("");
  try {
    const page = await bridge.qaReviewGetQueue(toQueryFilters(get(reviewFilters), ""));
    reviewQueue.set(page.findings);
    reviewTotal.set(page.totalCount);
    reviewCursor.set(page.nextCursor);
  } catch (error) {
    reviewError.set(String(error));
    reviewQueue.set([]);
    reviewTotal.set(0);
    reviewCursor.set("");
  } finally {
    reviewLoading.set(false);
  }
}

/** Append the next page. Safe to call repeatedly; no-ops when exhausted. */
export async function loadMoreFindings(): Promise<void> {
  const cursor = get(reviewCursor);
  if (!cursor || get(reviewLoading)) return;
  reviewLoading.set(true);
  try {
    const page = await bridge.qaReviewGetQueue(toQueryFilters(get(reviewFilters), cursor));
    // Guard against a page arriving after the filters changed underneath it.
    reviewQueue.update((existing) => {
      const seen = new Set(existing.map((item) => item.id));
      return [...existing, ...page.findings.filter((item) => !seen.has(item.id))];
    });
    reviewTotal.set(page.totalCount);
    reviewCursor.set(page.nextCursor);
  } catch (error) {
    reviewError.set(String(error));
  } finally {
    reviewLoading.set(false);
  }
}

export async function selectFinding(findingId: string | null): Promise<void> {
  selectedFindingId.set(findingId);
  selectedDetail.set(null);
  detailError.set("");
  if (!findingId) return;
  detailLoading.set(true);
  try {
    selectedDetail.set(await bridge.qaReviewGetFinding(findingId));
  } catch (error) {
    detailError.set(String(error));
  } finally {
    detailLoading.set(false);
  }
}

/** Move by one position in the queue; loads the next page when it runs out. */
export async function stepSelection(delta: number): Promise<void> {
  const queue = get(reviewQueue);
  const index = get(selectedIndex);
  const next = index < 0 ? 0 : index + delta;
  if (next < 0) return;
  if (next >= queue.length) {
    if (!get(reviewCursor)) return;
    await loadMoreFindings();
    const grown = get(reviewQueue);
    if (next >= grown.length) return;
    await selectFinding(grown[next].id);
    return;
  }
  await selectFinding(queue[next].id);
}

/** Jump to the next finding still awaiting a decision, wrapping forward only. */
export async function goToNextUnresolved(): Promise<void> {
  const queue = get(reviewQueue);
  const from = get(selectedIndex) + 1;
  const next = queue.findIndex(
    (item, index) => index >= from && item.qaDisposition === "UNRESOLVED",
  );
  if (next >= 0) {
    await selectFinding(queue[next].id);
    return;
  }
  if (get(reviewCursor)) {
    await loadMoreFindings();
    if (get(reviewQueue).length > queue.length) await goToNextUnresolved();
  }
}

export interface DecisionOutcome {
  ok: boolean;
  conflict: boolean;
  message: string;
  promoted: string[];
}

/**
 * Record a decision and fold the result back into the queue in place.
 *
 * A `revision_conflict` is surfaced rather than retried: the finding moved
 * under the reviewer, so the honest response is to reload it and let them
 * decide again against what it says now.
 */
export async function decideFinding(
  findingId: string,
  disposition: ReviewerDecision,
  options: { note?: string; promote?: boolean } = {},
): Promise<DecisionOutcome> {
  const detail = get(selectedDetail);
  const summary = get(reviewQueue).find((item) => item.id === findingId);
  const revision = detail?.finding?.revision ?? summary?.revision;
  if (revision === undefined) {
    return { ok: false, conflict: false, message: "This finding is no longer loaded.", promoted: [] };
  }
  try {
    const result = await bridge.qaReviewDecideFinding(findingId, disposition, revision, {
      note: options.note,
      promote: options.promote,
      expectedTargetContentHashes: detail?.finding?.targetContentHashes,
    });
    reviewQueue.update((items) =>
      items.map((item) =>
        item.id === findingId
          ? {
              ...item,
              qaDisposition: result.finding.qaDisposition,
              reviewStatus: result.finding.reviewStatus,
              revision: result.finding.revision,
            }
          : item,
      ),
    );
    selectedDetail.update((current) =>
      current && current.finding.id === findingId
        ? { ...current, finding: result.finding, history: result.history }
        : current,
    );
    return {
      ok: true,
      conflict: false,
      message: "",
      promoted: result.promotedCoverageAccountIds ?? [],
    };
  } catch (error) {
    const message = String(error);
    const conflict = message.includes("revision_conflict")
      || message.toLowerCase().includes("revision conflict")
      || message.toLowerCase().includes("target content changed");
    if (conflict) await selectFinding(findingId);
    return {
      ok: false,
      conflict,
      message: conflict
        ? "This finding changed since you opened it. It has been reloaded — please decide again."
        : message,
      promoted: [],
    };
  }
}

export async function addReviewerNote(findingId: string, note: string): Promise<DecisionOutcome> {
  try {
    const result = await bridge.qaReviewAddNote("QA_FINDING", findingId, note);
    selectedDetail.update((current) =>
      current && current.finding.id === findingId
        ? { ...current, history: result.history }
        : current,
    );
    return { ok: true, conflict: false, message: "", promoted: [] };
  } catch (error) {
    return { ok: false, conflict: false, message: String(error), promoted: [] };
  }
}

export function resetReviewState(): void {
  reviewFilters.set({ ...EMPTY_FILTERS });
  reviewQueue.set([]);
  reviewTotal.set(0);
  reviewCursor.set("");
  reviewError.set("");
  selectedFindingId.set(null);
  selectedDetail.set(null);
  detailError.set("");
}
