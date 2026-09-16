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
export function openCrossVerse(verse: string): boolean {
  if (!verse || alignmentBusy()) return false;
  alignmentOpen.set(false);
  crossVerseAnchor.set(verse);
  crossVerseOpen.set(true);
  return true;
}

export function closeCrossVerse(): void {
  crossVerseOpen.set(false);
}
