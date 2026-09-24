// Collection QA (layered-rules Phase 4.4): one run checks every book of the
// open collection in turn (collection.runChecks). This module owns the run's
// status and its poll, so the dashboard panel and the rest of the app (which
// goes read-only while a run is active) read one source.
//
// It polls only while a run is active, every POLL_MS, and not at all
// otherwise: the performance contract's "zero pollers awake when idle".
import { writable } from "svelte/store";
import { bridge } from "./api/bridgeClient";
import type { CollectionQaSnapshot } from "./types/collectionQa";

export const POLL_MS = 1000;
const ACTIVE = new Set(["queued", "running", "cancelling"]);

/** The latest snapshot (idle: each book's last recorded run), or null before the first read. */
export const collectionQa = writable<CollectionQaSnapshot | null>(null);
/** True while a run is active: book switching, editing and checks are held. */
export const collectionQaRunning = writable(false);

let timer: ReturnType<typeof setTimeout> | undefined;
let sequence = 0;

function publish(snapshot: CollectionQaSnapshot): boolean {
  collectionQa.set(snapshot);
  const active = ACTIVE.has(snapshot.state);
  collectionQaRunning.set(active);
  return active;
}

async function poll(jobId: string, ticket: number): Promise<void> {
  try {
    const snapshot = await bridge.collectionQaStatus(jobId);
    if (ticket !== sequence) return;
    if (publish(snapshot)) timer = setTimeout(() => void poll(jobId, ticket), POLL_MS);
  } catch {
    if (ticket === sequence) timer = setTimeout(() => void poll(jobId, ticket), POLL_MS * 5);
  }
}

/** Read the current state once (the last recorded runs when nothing is running),
 * and keep polling if a run is active -- e.g. after the app reopened mid-run. */
export async function refreshCollectionQa(): Promise<void> {
  const ticket = ++sequence;
  if (timer) clearTimeout(timer);
  const snapshot = await bridge.collectionQaStatus("");
  if (ticket !== sequence) return;
  if (publish(snapshot) && snapshot.jobId) timer = setTimeout(() => void poll(snapshot.jobId, ticket), POLL_MS);
}

export async function startCollectionQa(force = false): Promise<void> {
  const ticket = ++sequence;
  if (timer) clearTimeout(timer);
  const snapshot = await bridge.collectionRunChecks(["local", "greekroom", "languageQa"], force);
  if (ticket !== sequence) return;
  if (publish(snapshot)) timer = setTimeout(() => void poll(snapshot.jobId, ticket), POLL_MS);
}

export async function pauseCollectionQa(paused: boolean): Promise<void> {
  publish(await bridge.collectionPauseChecks(paused));
}

export async function cancelCollectionQa(): Promise<void> {
  publish(await bridge.collectionCancelChecks());
}

/** Stop polling (project closed); the next refresh starts afresh. */
export function stopCollectionQa(): void {
  ++sequence;
  if (timer) clearTimeout(timer);
  timer = undefined;
  collectionQa.set(null);
  collectionQaRunning.set(false);
}
