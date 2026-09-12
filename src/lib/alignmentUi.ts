// Alignment-modal open state, shared between ReviewPanel.svelte (the
// "⇄ Align words" button and the modal itself) and VerseList.svelte (the
// per-row alignment glyph, issue #70) so either entry point can drive the
// same modal without reaching into the other component's internals --
// same reasoning as verseEditor.ts's edit-session state.
import { writable, get } from "svelte/store";
import { checkingProgress, verseKey } from "./stores";
import { editSaving, recheckingKey } from "./verseEditor";

export const alignmentOpen = writable(false);
export const alignmentKey = writable("");

/** Guards match ReviewPanel's original "Align words" button: no verse, a
 * background check run, an in-flight edit save, or a post-edit recheck all
 * mean the alignment data underneath the modal isn't stable yet. */
export function openAlignment(chapter: string, verse: string): boolean {
  if (!verse || get(checkingProgress).running || get(editSaving) || get(recheckingKey)) return false;
  alignmentKey.set(verseKey(chapter, verse));
  alignmentOpen.set(true);
  return true;
}
