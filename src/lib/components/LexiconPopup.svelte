<script lang="ts">
  import { onMount } from "svelte";
  import { bridge } from "../api/bridgeClient";
  import type { AlignmentToken, LexiconEntryResponse } from "../types/finding";

  export let token: AlignmentToken;
  export let direction: "ltr" | "rtl" = "rtl";
  export let onClose: () => void;

  let loading = true;
  let error = "";
  let response: LexiconEntryResponse | null = null;

  onMount(async () => {
    loading = true;
    error = "";
    try {
      response = await bridge.getLexiconEntry(token.strong ?? "", token.morph ?? "");
    } catch (value) {
      error = value instanceof Error ? value.message : String(value);
    } finally {
      loading = false;
    }
  });
</script>

<svelte:window on:keydown={(event) => event.key === "Escape" && onClose()} />

<div class="overlay" role="presentation">
  <section
    class="popup"
    role="dialog"
    aria-modal="true"
    aria-label={`Word details for ${token.word}`}
  >
    <header>
      <div class="eyebrow">WORD DETAILS</div>
      <span class="headword" dir={direction}>{token.word}</span>
      <button class="close" on:click={onClose} aria-label="Close word details">×</button>
    </header>

    {#if loading}
      <div class="loading"><span class="spin" /> Looking up lexicon entry…</div>
    {:else if error}
      <div class="error">{error}</div>
    {:else if response}
      <div class="segments">
        {#each response.segments as segment, index (index)}
          <div class="segment">
            {#if segment.lemma}<div class="lemma" dir={direction}>{segment.lemma}</div>{/if}
            <dl>
              {#if segment.translit}
                <dt>Transliteration</dt><dd>{segment.translit}{#if segment.pron}&nbsp;({segment.pron}){/if}</dd>
              {/if}
              {#if segment.morphLabel}<dt>Morphology</dt><dd>{segment.morphLabel}</dd>{/if}
              {#if segment.strong}<dt>Strong's</dt><dd>{segment.strong}</dd>{/if}
              {#if segment.meaning}<dt>Meaning</dt><dd>{segment.meaning}</dd>{/if}
              {#if segment.usage}<dt>Usage</dt><dd>{segment.usage}</dd>{/if}
              {#if segment.source}<dt>Source</dt><dd>{segment.source}</dd>{/if}
            </dl>
            {#if !segment.lemma && !segment.meaning}
              <p class="unresolved">No lexicon entry found for this segment.</p>
            {/if}
          </div>
        {:else}
          <p class="unresolved">No morphology or lexicon data is available for this word.</p>
        {/each}
      </div>
    {/if}
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
    padding: 18px; color: var(--text);
  }
  header {
    display: flex; flex-wrap: wrap; align-items: flex-start; gap: 10px;
    border-bottom: 1px solid var(--border); padding-bottom: 12px; margin-bottom: 12px;
  }
  .eyebrow { color: var(--accent); font-size: 10px; letter-spacing: .12em; font-weight: 800; flex: 0 0 100%; }
  .headword { font-size: 20px; font-weight: 700; flex: 1; min-width: 0; overflow-wrap: anywhere; }
  button { font: inherit; }
  .close { border: 0; background: none; font-size: 22px; padding: 0 4px; color: var(--text-2); cursor: pointer; }
  .close:hover { color: var(--text); }
  .loading { display: flex; gap: 10px; align-items: center; color: var(--text-2); padding: 16px 0; }
  .spin { width: 12px; height: 12px; border: 2px solid var(--accent-bg); border-top-color: var(--accent); border-radius: 50%; animation: spin .8s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .error { background: #FFF0F0; color: var(--danger); border-radius: 9px; padding: 10px 12px; font-size: 12px; }
  .segments { display: flex; flex-direction: column; gap: 12px; }
  .segment { border: 1px solid var(--border); border-radius: 10px; padding: 12px; }
  .segment + .segment { background: var(--surface-2); }
  .lemma { font-size: 18px; font-weight: 700; margin-bottom: 8px; overflow-wrap: anywhere; }
  dl { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 4px 10px; margin: 0; font-size: 12px; }
  dt { color: var(--text-3); font-weight: 700; white-space: nowrap; }
  dd { margin: 0; color: var(--text); line-height: 1.5; min-width: 0; overflow-wrap: anywhere; }
  .unresolved { color: var(--text-3); font-size: 12px; margin: 4px 0 0; }
</style>
