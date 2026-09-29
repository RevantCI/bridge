<script lang="ts">
  import LanguageQaHistoryList from "./LanguageQaHistoryList.svelte";

  export let projectPath: string;
  export let chapter: string;
  export let verse: string;
  export let onClose: () => void;
</script>

<svelte:window on:keydown={(event) => event.key === "Escape" && onClose()} />

<div
  class="overlay"
  role="presentation"
  on:click={(event) => event.target === event.currentTarget && onClose()}
>
  <section class="popup" role="dialog" aria-modal="true" aria-label={`Language QA history for verse ${chapter}:${verse}`}>
    <header>
      <div class="eyebrow">LANGUAGE QA</div>
      <span class="headword">Decision history</span>
      <span class="ref">{chapter}:{verse}</span>
      <button class="close" on:click={onClose} aria-label="Close Language QA history">×</button>
    </header>
    <LanguageQaHistoryList {projectPath} {chapter} {verse} />
  </section>
</div>

<style>
  .overlay {
    position: fixed; inset: 0; z-index: 60; background: rgba(15, 20, 26, .58);
    display: grid; place-items: center; padding: 24px;
  }
  .popup {
    width: min(480px, 100%); max-height: calc(100vh - 48px);
    overflow-y: auto; overflow-x: hidden;
    background: var(--surface); border-radius: 14px; box-shadow: 0 24px 80px rgba(0,0,0,.28);
    padding: 18px; color: var(--text); cursor: default; font-size: var(--fs-sm);
  }
  header {
    display: flex; flex-wrap: wrap; align-items: flex-start; gap: 10px;
    border-bottom: 1px solid var(--border); padding-bottom: 12px; margin-bottom: 12px;
  }
  .eyebrow { color: var(--accent); font-size: var(--fs-2xs); letter-spacing: .12em; font-weight: 800; flex: 0 0 100%; }
  .headword { font-size: var(--fs-2xl); font-weight: 700; flex: 1; min-width: 0; }
  .ref { font-size: var(--fs-sm); color: var(--text-3); font-weight: 700; padding-top: 6px; }
  button { font: inherit; }
  .close { border: 0; background: none; font-size: var(--fs-4xl); padding: 0 4px; color: var(--text-2); cursor: pointer; }
  .close:hover { color: var(--text); }
</style>
