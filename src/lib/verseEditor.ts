// Verse-edit lifecycle, shared between VerseList.svelte (renders the inline
// textarea in the left editor panel) and ReviewPanel.svelte (the "Edit
// verse" triggers, plus the recheck/AI-review follow-up once a save
// completes). Moved out of ReviewPanel.svelte so the edit textbox could
// move into the left panel — there's much more width there than the
// 400px-wide review panel — without either component needing to reach
// into the other's internals.
import { get, writable } from "svelte/store";
import { bridge } from "./api/bridgeClient";
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
  | ((info: { chapter: string; verse: string; issueResolutionsNeedingRecheck: number }) => void)
  | null = null;

/** ReviewPanel registers its own follow-up (refresh translation helps,
 * maybe restart AI review) here rather than saveVerseEdit calling back
 * into a specific component instance. */
export function setVerseEditSavedHook(hook: typeof onSaved): void {
  onSaved = hook;
}

export function startVerseEdit(chapter: string, verse: string): boolean {
  if (!verse || get(checkingProgress).running || get(editSaving) || get(recheckingKey)) return false;
  editingChapter.set(chapter);
  editingVerse.set(verse);
  editText.set(get(verseTexts)[verseKey(chapter, verse)] ?? "");
  editError.set("");
  editErrorKey.set("");
  return true;
}

export function cancelVerseEdit(): void {
  editingChapter.set("");
  editingVerse.set("");
}

export async function saveVerseEdit(): Promise<void> {
  const chapter = get(editingChapter);
  const verse = get(editingVerse);
  if (!chapter || !verse) return;
  const key = verseKey(chapter, verse);
  const text = get(editText);
  if (text.trim() === (get(verseTexts)[key] ?? "").trim()) {
    // No real change — apply_scripture_edit rejects this as a no-op
    // rather than journaling a spurious edit, so don't call it.
    cancelVerseEdit();
    return;
  }
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
    onSaved?.({ chapter, verse, issueResolutionsNeedingRecheck: editResult.issueResolutionsNeedingRecheck });
    window.setTimeout(() => {
      if (get(recheckedKey) === key) recheckedKey.set("");
    }, 3500);
  } catch (e) {
    recheckingKey.set("");
    checkStatusByVerse.update((map) => ({ ...map, [key]: "failed" }));
    editError.set(e instanceof Error ? e.message : String(e));
    editErrorKey.set(key);
  } finally {
    editSaving.set(false);
  }
}
