<script lang="ts">
  import type { VerseNote, VerseNoteKind } from "../utils/usfmNotes";

  export let kind: VerseNoteKind;
  export let notes: VerseNote[];
  export let reference: string;
  export let onClose: () => void;

  $: title = kind === "footnote" ? "Footnotes" : "Cross reference";

  // \fq quotes the words being annotated, so it reads as the note's lead-in
  // rather than part of the explanation. \xt is the actual target list.
  function leadIn(note: VerseNote): string {
    return note.parts.find((part) => part.marker === (kind === "footnote" ? "fq" : "xt"))?.text ?? "";
  }

  function body(note: VerseNote): string {
    const lead = leadIn(note);
    return note.parts
      .filter((part) => part.marker !== (kind === "footnote" ? "fr" : "xo"))
      .map((part) => part.text)
      .filter((text) => text !== lead)
      .join(" ")
      .trim();
  }
</script>

<svelte:window on:keydown={(event) => event.key === "Escape" && onClose()} />

<div
  class="overlay"
  role="presentation"
  on:click={(event) => event.target === event.currentTarget && onClose()}
>
  <section
    class="popup"
    role="dialog"
    aria-modal="true"
    aria-label={`${title} for verse ${reference}`}
  >
    <header>
      <div class="eyebrow">{kind === "footnote" ? "FOOTNOTE" : "CROSS REFERENCE"}</div>
      <span class="headword">{title}</span>
      <span class="ref">{reference}</span>
      <button class="close" on:click={onClose} aria-label={`Close ${title.toLowerCase()}`}>×</button>
    </header>

    <div class="notes">
      {#each notes as note, index (index)}
        <div class="note">
          {#if notes.length > 1 || note.reference}
            <div class="note-head">
              {#if note.reference}<span class="note-ref">{note.reference}</span>{/if}
              {#if notes.length > 1}<span class="note-index">{index + 1} of {notes.length}</span>{/if}
            </div>
          {/if}
          {#if leadIn(note)}<div class="lead">{leadIn(note)}</div>{/if}
          {#if body(note)}<p class="body">{body(note)}</p>{/if}
          {#if !leadIn(note) && !body(note)}
            <p class="empty">This note carries no text.</p>
          {/if}
        </div>
      {/each}
    </div>
  </section>
</div>

<style>
  .overlay {
    position: fixed; inset: 0; z-index: 60; background: rgba(15, 20, 26, .58);
    display: grid; place-items: center; padding: 24px;
  }
  .popup {
    width: min(440px, 100%); max-height: calc(100vh - 48px);
    overflow-y: auto; overflow-x: hidden;
    background: var(--surface); border-radius: 14px; box-shadow: 0 24px 80px rgba(0,0,0,.28);
    padding: 18px; color: var(--text); cursor: default;
  }
  header {
    display: flex; flex-wrap: wrap; align-items: flex-start; gap: 10px;
    border-bottom: 1px solid var(--border); padding-bottom: 12px; margin-bottom: 12px;
  }
  .eyebrow { color: var(--accent); font-size: 10px; letter-spacing: .12em; font-weight: 800; flex: 0 0 100%; }
  .headword { font-size: 20px; font-weight: 700; flex: 1; min-width: 0; overflow-wrap: anywhere; }
  .ref { font-size: 12px; color: var(--text-3); font-weight: 700; padding-top: 6px; }
  button { font: inherit; }
  .close { border: 0; background: none; font-size: 22px; padding: 0 4px; color: var(--text-2); cursor: pointer; }
  .close:hover { color: var(--text); }
  .notes { display: flex; flex-direction: column; gap: 12px; }
  .note { border: 1px solid var(--border); border-radius: 10px; padding: 12px; }
  .note + .note { background: var(--surface-2); }
  .note-head { display: flex; gap: 8px; align-items: baseline; margin-bottom: 6px; }
  .note-ref { font-size: 11px; font-weight: 800; color: var(--accent); }
  .note-index { font-size: 10px; color: var(--text-3); margin-left: auto; }
  .lead { font-size: 14px; font-weight: 700; line-height: 1.6; margin-bottom: 6px; overflow-wrap: anywhere; }
  .body { font-size: 13px; line-height: 1.7; margin: 0; color: var(--text-2); overflow-wrap: anywhere; }
  .empty { color: var(--text-3); font-size: 12px; margin: 0; }
</style>
