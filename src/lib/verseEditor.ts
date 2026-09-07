// Verse-edit lifecycle, shared between VerseList.svelte (renders the inline
// textarea in the left editor panel) and ReviewPanel.svelte (the "Edit
// verse" triggers, plus the recheck/AI-review follow-up once a save
// completes). Moved out of ReviewPanel.svelte so the edit textbox could
// move into the left panel — there's much more width there than the
// 400px-wide review panel — without either component needing to reach
// into the other's internals.
import { get, writable } from "svelte/store";
import { bridge } from "./api/bridgeClient";
import type { QaFinding } from "./types/finding";
import {
  alignmentStatusByVerse, checkStatusByVerse, checkingProgress, findingsByVerse,
  nativeChecksByVerse, aiCheckReviewsByVerse, verseKey, verseTexts,
} from "./stores";

export const editingChapter = writable("");
export const editingVerse = writable("");
export const editText = writable("");
export const editSaving = writable(false);
export const editError = writable("");
export const editErrorKey = writable("");
export const recheckingKey = writable("");
export const recheckedKey = writable("");

let onSaved:
  | ((info: {
      chapter: string; verse: string; issueResolutionsNeedingRecheck: number; acceptFindingId: string;
    }) => void)
  | null = null;

/** ReviewPanel registers its own follow-up (refresh translation helps,
 * maybe restart AI review) here rather than saveVerseEdit calling back
 * into a specific component instance. */
export function setVerseEditSavedHook(hook: typeof onSaved): void {
  onSaved = hook;
}

// Set by ReviewPanel's "Accept and edit" (as opposed to a plain "Edit
// verse") right after starting an edit session, so a successful save can
// report which specific finding to mark "accepted" — cleared by
// startVerseEdit (a fresh edit session starts clean) and by cancelVerseEdit
// (a true cancel drops the accept intent too), but saveVerseEdit captures
// its value into a local const before its own internal cancelVerseEdit()
// call clears it, so a successful save still has it for the onSaved payload.
let pendingAcceptFindingId = "";

export function setPendingAcceptFinding(findingId: string): void {
  pendingAcceptFindingId = findingId;
}

export function startVerseEdit(chapter: string, verse: string): boolean {
  if (!verse || get(checkingProgress).running || get(editSaving) || get(recheckingKey)) return false;
  editingChapter.set(chapter);
  editingVerse.set(verse);
  editText.set(get(verseTexts)[verseKey(chapter, verse)] ?? "");
  editError.set("");
  editErrorKey.set("");
  pendingAcceptFindingId = "";
  return true;
}

export function cancelVerseEdit(): void {
  editingChapter.set("");
  editingVerse.set("");
  pendingAcceptFindingId = "";
}

export async function saveVerseEdit(): Promise<boolean> {
  const chapter = get(editingChapter);
  const verse = get(editingVerse);
  if (!chapter || !verse) return false;
  const key = verseKey(chapter, verse);
  const text = get(editText);
  if (text.trim() === (get(verseTexts)[key] ?? "").trim()) {
    // No real change — apply_scripture_edit rejects this as a no-op
    // rather than journaling a spurious edit, so don't call it.
    cancelVerseEdit();
    return false;
  }
  const acceptFindingId = pendingAcceptFindingId;
  editError.set("");
  editSaving.set(true);
  try {
    const editResult = await bridge.editVerse(chapter, verse, text);
    verseTexts.update((t) => ({ ...t, [key]: text }));
    aiCheckReviewsByVerse.update((values) => {
      const next = { ...values };
      delete next[key];
      return next;
    });
    nativeChecksByVerse.update((values) => {
      const next = { ...values };
      delete next[key];
      return next;
    });
    alignmentStatusByVerse.update((values) => ({ ...values, [key]: "invalid" }));
    cancelVerseEdit();
    recheckingKey.set(key);
    recheckedKey.set("");
    checkStatusByVerse.update((map) => ({ ...map, [key]: "pending" }));
    const findings = await bridge.runVerseChecks(chapter, verse, ["local", "greekroom"]);
    findingsByVerse.update((map) => ({ ...map, [key]: findings }));
    checkStatusByVerse.update((map) => ({ ...map, [key]: "succeeded" }));
    recheckingKey.set("");
    recheckedKey.set(key);
    onSaved?.({
      chapter, verse, issueResolutionsNeedingRecheck: editResult.issueResolutionsNeedingRecheck,
      acceptFindingId,
    });
    window.setTimeout(() => {
      if (get(recheckedKey) === key) recheckedKey.set("");
    }, 3500);
    return true;
  } catch (e) {
    recheckingKey.set("");
    checkStatusByVerse.update((map) => ({ ...map, [key]: "failed" }));
    editError.set(e instanceof Error ? e.message : String(e));
    editErrorKey.set(key);
    return false;
  } finally {
    editSaving.set(false);
  }
}

export interface FindingFixOutcome {
  ok: boolean;
  message: string;
}

/** Apply a finding's exact replacement through the normal editor/save/re-check path. */
export async function applySuggestedFindingFix(finding: QaFinding): Promise<FindingFixOutcome> {
  if (finding.suggested_replacement === null
      || finding.start_offset === null
      || finding.end_offset === null) {
    return { ok: false, message: "No proposed fix is available for this finding." };
  }
  const chapter = String(finding.chapter);
  const verse = String(finding.verse);
  const key = verseKey(chapter, verse);
  const current = get(verseTexts)[key];
  if (current === undefined) {
    return { ok: false, message: "The verse text is no longer loaded." };
  }

  // Engine offsets are Unicode code-point offsets. Array.from avoids moving
  // the replacement when the verse contains astral characters.
  const points = Array.from(current);
  const start = finding.start_offset;
  const end = finding.end_offset;
  if (start < 0 || end < start || end > points.length) {
    return { ok: false, message: "The proposed fix no longer matches the current verse." };
  }
  const original = points.slice(start, end).join("");
  if (finding.original_text && original !== finding.original_text) {
    return { ok: false, message: "The proposed fix is stale because the verse text changed." };
  }
  if (!startVerseEdit(chapter, verse)) {
    return { ok: false, message: "Finish the current check or edit before applying this fix." };
  }
  editText.set(
    points.slice(0, start).join("")
      + finding.suggested_replacement
      + points.slice(end).join(""),
  );
  setPendingAcceptFinding(finding.id);
  const saved = await saveVerseEdit();
  return saved
    ? { ok: true, message: "Fix applied and verse re-checked." }
    : { ok: false, message: get(editError) || "The fix could not be applied." };
}
