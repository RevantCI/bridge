// Alignment-modal open state, shared between ReviewPanel.svelte (the
// "⇄ Align words" button and the modal itself) and VerseList.svelte (the
// per-row alignment glyph, issue #70) so either entry point can drive the
// same modal without reaching into the other component's internals --
// same reasoning as verseEditor.ts's edit-session state.
//
// The Cross-verse alignment page (#116) follows the same pattern: the editor
// toolbar button in App.svelte and the link inside AlignmentModal both open
// it through `openCrossVerse`, and App.svelte hosts the one instance.
import { writable, get } from "svelte/store";
import { checkingProgress, verseKey } from "./stores";
import { editSaving, recheckingKey } from "./verseEditor";

export const alignmentOpen = writable(false);
export const alignmentKey = writable("");

export const crossVerseOpen = writable(false);
/** The verse the page was opened on; it centres the default range. */
export const crossVerseAnchor = writable("");
/** Verses the page should start with instead of anchor ±1 (#118): the
 *  editor's multi-selection, or a finding's references. Empty = default. */
export const crossVerseInitialVerses = writable<string[]>([]);
/** A request to open the page on a chapter that may not be the current one.
 *  App.svelte resolves it: switch chapter if needed, then openCrossVerse. */
export const crossVerseRequest = writable<{ chapter: string; verses: string[] } | null>(null);

/** True while alignment data underneath an editor is unstable: a background
 * check run, an in-flight edit save, or a post-edit recheck. */
function alignmentBusy(): boolean {
  return get(checkingProgress).running || Boolean(get(editSaving)) || Boolean(get(recheckingKey));
}

/** Guards match ReviewPanel's original "Align words" button: no verse, a
 * background check run, an in-flight edit save, or a post-edit recheck all
 * mean the alignment data underneath the modal isn't stable yet. */
export function openAlignment(chapter: string, verse: string): boolean {
  if (!verse || alignmentBusy()) return false;
  alignmentKey.set(verseKey(chapter, verse));
  alignmentOpen.set(true);
  return true;
}

/** Same guards as openAlignment. Closes the single-verse modal first: the
 * two editors write the same alignment files and must not be open together. */
export function openCrossVerse(verse: string, verses: readonly string[] = []): boolean {
  if (!verse || alignmentBusy()) return false;
  alignmentOpen.set(false);
  crossVerseInitialVerses.set(verses.length > 1 ? [...verses] : []);
  crossVerseAnchor.set(verse);
  crossVerseOpen.set(true);
  return true;
}

/** From a finding (#118): the references may sit in another chapter, so the
 *  request goes through App.svelte, which owns chapter navigation. */
export function requestCrossVerse(chapter: string, verses: readonly string[]): boolean {
  if (!chapter || verses.length === 0 || alignmentBusy()) return false;
  crossVerseRequest.set({ chapter, verses: [...verses] });
  return true;
}

export function closeCrossVerse(): void {
  crossVerseOpen.set(false);
  crossVerseInitialVerses.set([]);
}
