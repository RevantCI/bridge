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
import type { CoverageDimension } from "./types/passageSemanticV1";

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
  canonicalReferences: string[];
  kinds: string[];
  coverageDimensions: CoverageDimension[];
  severities: string[];
  dispositions: QaDisposition[];
  lifecycleStatuses: string[];
  order: ReviewQueueOrder;
}

export const EMPTY_FILTERS: ReviewFilters = {
  book: "",
  chapter: null,
  canonicalReferences: [],
  kinds: [],
  coverageDimensions: [],
  severities: [],
  dispositions: [],
  lifecycleStatuses: [],
  order: "CANONICAL",
};

const PAGE_SIZE = 50;
let queueGeneration = 0;

/**
 * Filter state splits in two, and only one half survives a project reload.
 *
 * `order`, `dispositions`, `kinds`, `coverageDimensions` and
 * `lifecycleStatuses` are *preferences* --
 * a reviewer's working style, which they reasonably expect to still be set the
 * next time they open the app (#61: losing them mid-session was misread as a
 * finding-count bug). `book`, `chapter` and `canonicalReferences` are *scope*:
 * they come from the project being opened, and restoring a previous project's
 * book would silently point the queue at text the reviewer is not looking at.
 *
 * So scope always resets and preferences always rehydrate.
 */
const FILTER_STORAGE_KEY = "bridge.reviewFilters.v1";

type PersistedFilters = Pick<
  ReviewFilters,
  "order" | "dispositions" | "kinds" | "coverageDimensions" | "lifecycleStatuses"
>;

const REVIEW_QUEUE_ORDERS: readonly ReviewQueueOrder[] = ["CANONICAL", "SEVERITY"];
const QA_DISPOSITIONS: readonly QaDisposition[] = [
  "UNRESOLVED",
  "CONFIRMED_TRANSLATION_ERROR",
  "ACCEPTABLE_TRANSLATION",
  "FALSE_POSITIVE",
  "NEEDS_DISCUSSION",
  "CORRECTED",
];

const COVERAGE_DIMENSIONS: readonly CoverageDimension[] = [
  "LEXICAL_CONTENT", "POLARITY", "QUANTITY", "PARTICIPANT", "REFERENT",
  "PREDICATION", "TEMPORAL_ASPECTUAL", "SPATIAL_RELATION", "CLAUSE_RELATION",
  "DISCOURSE_RELATION", "OTHER",
];

function stringArray(value: unknown): string[] | null {
  if (!Array.isArray(value)) return null;
  return value.every((item) => typeof item === "string") ? (value as string[]) : null;
}

/**
 * Read back what a previous session stored.
 *
 * Every field is validated rather than trusted: this value outlives the app
 * version that wrote it, so a renamed disposition or a hand-edited entry has to
 * degrade to the default instead of being forwarded to the engine as a filter
 * nothing will ever match. One bad field discards only that field.
 */
function readPersistedFilters(): Partial<PersistedFilters> {
  let raw: string | null = null;
  try {
    raw = localStorage.getItem(FILTER_STORAGE_KEY);
  } catch {
    return {}; // storage unavailable (disabled, or a webview without it)
  }
  if (!raw) return {};

  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return {};
  }
  if (!parsed || typeof parsed !== "object") return {};

  const source = parsed as Record<string, unknown>;
  const restored: Partial<PersistedFilters> = {};

  if (REVIEW_QUEUE_ORDERS.includes(source.order as ReviewQueueOrder)) {
    restored.order = source.order as ReviewQueueOrder;
  }
  const kinds = stringArray(source.kinds);
  if (kinds) restored.kinds = kinds;
  const lifecycleStatuses = stringArray(source.lifecycleStatuses);
  if (lifecycleStatuses) restored.lifecycleStatuses = lifecycleStatuses;

  const dimensions = stringArray(source.coverageDimensions);
  if (dimensions) {
    const known = dimensions.filter(
      (value): value is CoverageDimension =>
        COVERAGE_DIMENSIONS.includes(value as CoverageDimension),
    );
    if (known.length === dimensions.length) restored.coverageDimensions = known;
  }

  const dispositions = stringArray(source.dispositions);
  if (dispositions) {
    const known = dispositions.filter(
      (value): value is QaDisposition => QA_DISPOSITIONS.includes(value as QaDisposition),
    );
    if (known.length === dispositions.length) restored.dispositions = known;
  }
  return restored;
}

function writePersistedFilters(filters: ReviewFilters): void {
  try {
    localStorage.setItem(FILTER_STORAGE_KEY, JSON.stringify({
      order: filters.order,
      dispositions: filters.dispositions,
      kinds: filters.kinds,
      coverageDimensions: filters.coverageDimensions,
      lifecycleStatuses: filters.lifecycleStatuses,
    } satisfies PersistedFilters));
  } catch {
    // Best-effort: failing to remember a filter must never break review itself.
  }
}

/** A fresh queue's filters: scope cleared, preferences as the reviewer left them. */
export function initialReviewFilters(): ReviewFilters {
  return { ...EMPTY_FILTERS, ...readPersistedFilters() };
}

export const reviewFilters = writable<ReviewFilters>(initialReviewFilters());

// Singleton store for the app's lifetime, so this subscription is never torn down.
reviewFilters.subscribe(writePersistedFilters);
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
    canonicalReferences: filters.canonicalReferences.length
      ? filters.canonicalReferences
      : undefined,
    kinds: filters.kinds.length ? filters.kinds : undefined,
    coverageDimensions: filters.coverageDimensions.length
      ? filters.coverageDimensions
      : undefined,
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
  const generation = ++queueGeneration;
  reviewLoading.set(true);
  reviewError.set("");
  try {
    const page = await bridge.qaReviewGetQueue(toQueryFilters(get(reviewFilters), ""));
    if (generation !== queueGeneration) return;
    reviewQueue.set(page.findings);
    reviewTotal.set(page.totalCount);
    reviewCursor.set(page.nextCursor);
  } catch (error) {
    if (generation !== queueGeneration) return;
    reviewError.set(String(error));
    reviewQueue.set([]);
    reviewTotal.set(0);
    reviewCursor.set("");
  } finally {
    if (generation === queueGeneration) reviewLoading.set(false);
  }
}

/** Append the next page. Safe to call repeatedly; no-ops when exhausted. */
export async function loadMoreFindings(): Promise<void> {
  const cursor = get(reviewCursor);
  if (!cursor || get(reviewLoading)) return;
  const generation = queueGeneration;
  reviewLoading.set(true);
  try {
    const page = await bridge.qaReviewGetQueue(toQueryFilters(get(reviewFilters), cursor));
    if (generation !== queueGeneration) return;
    // Guard against a page arriving after the filters changed underneath it.
    reviewQueue.update((existing) => {
      const seen = new Set(existing.map((item) => item.id));
      return [...existing, ...page.findings.filter((item) => !seen.has(item.id))];
    });
    reviewTotal.set(page.totalCount);
    reviewCursor.set(page.nextCursor);
  } catch (error) {
    if (generation === queueGeneration) reviewError.set(String(error));
  } finally {
    if (generation === queueGeneration) reviewLoading.set(false);
  }
}

/**
 * Replace the canonical scope used by every queue page and clear rows from
 * the previous scope immediately. Historical rows remain in SQLite and will
 * reappear when their canonical scope is selected again.
 */
export function setReviewCanonicalScope(references: string[]): void {
  const normalized = [...new Set(references.map((reference) => reference.trim()).filter(Boolean))];
  const current = get(reviewFilters).canonicalReferences;
  if (current.length === normalized.length
      && current.every((reference, index) => reference === normalized[index])) return;
  queueGeneration += 1;
  reviewFilters.update((filters) => ({ ...filters, canonicalReferences: normalized }));
  reviewQueue.set([]);
  reviewTotal.set(0);
  reviewCursor.set("");
  reviewLoading.set(false);
  reviewError.set("");
  selectedFindingId.set(null);
  selectedDetail.set(null);
  detailError.set("");
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
  const loadedDetail = get(selectedDetail);
  const detail = loadedDetail?.finding.id === findingId ? loadedDetail : null;
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
  queueGeneration += 1;
  reviewFilters.set(initialReviewFilters());
  reviewQueue.set([]);
  reviewTotal.set(0);
  reviewCursor.set("");
  reviewError.set("");
  selectedFindingId.set(null);
  selectedDetail.set(null);
  detailError.set("");
}
