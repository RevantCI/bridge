<script lang="ts">
  import { project, currentChapter } from "../stores";

  export let screen: "home" | "dashboard" | "validation" | "review" | "editor";
  export let projectName = "";
  export let onGoHome: () => void;
  export let onGoToDashboard: () => void;
  export let onOpenSettings: () => void;
  export let onOpenExport: () => void;
  export let onGotoVerse: (verse: string) => void;
  export let onChapterChange: (chapter: string) => void;
  export let onBookChange: (path: string) => void;
  export let exportEnabled: boolean;
  export let bookSwitching = false;

  let gotoValue = "";

  function handleBookSelect(e: Event) {
    const value = (e.target as HTMLSelectElement).value;
    onBookChange(value);
  }

  function jump() {
    const parts = gotoValue.trim().split(":");
    const chapterPart = parts.length > 1 ? parts[0] : null;
    const versePart = parts[parts.length - 1];
    if (chapterPart && chapterPart !== $currentChapter) {
      onChapterChange(chapterPart);
    }
    if (versePart) onGotoVerse(versePart);
  }

  function handleChapterSelect(e: Event) {
    const value = (e.target as HTMLSelectElement).value;
    onChapterChange(value);
  }
</script>

<div class="topbar">
  <div class="brand"><div class="mark" /> Bridge</div>
  <div class="divider" />

  <nav class="breadcrumb" aria-label="Navigation">
    <button class="crumb" class:current={screen === "home"} on:click={onGoHome}>Projects</button>
    {#if screen === "dashboard" || screen === "validation" || screen === "review"}
      <span class="crumb-sep">›</span>
      {#if screen === "validation"}
        <button class="crumb" on:click={onGoToDashboard}>{projectName}</button>
        <span class="crumb-sep">›</span>
        <span class="crumb current">Mapping validation</span>
      {:else if screen === "review"}
        <button class="crumb" on:click={onGoToDashboard}>{projectName}</button>
        <span class="crumb-sep">›</span>
        <span class="crumb current">Alignment Review</span>
      {:else}
        <span class="crumb current">{projectName}</span>
      {/if}
    {:else if screen === "editor"}
      <span class="crumb-sep">›</span>
      <button class="crumb" on:click={onGoToDashboard} disabled={bookSwitching}>{projectName}</button>
      <span class="crumb-sep">›</span>
      {#if $project && $project.importedProjects && $project.importedProjects.length > 1}
        <select class="crumb-select" value={$project.path} on:change={handleBookSelect} disabled={bookSwitching}>
          {#each $project.importedProjects as book}
            <option value={book.path}>{book.bookName}</option>
          {/each}
        </select>
      {:else}
        <span class="crumb current">{$project?.bookName ?? ""}</span>
      {/if}
    {/if}
  </nav>

  {#if screen === "editor"}
    <select class="select" style="width:72px;" value={$currentChapter} on:change={handleChapterSelect}>
      {#each $project?.chapters ?? [] as ch}
        <option value={ch}>Ch {ch}</option>
      {/each}
    </select>
    <div class="goto">
      <input
        bind:value={gotoValue}
        placeholder="Go to 1:4"
        on:keydown={(e) => e.key === "Enter" && jump()}
      />
    </div>
  {/if}

  <div class="grow" />
  {#if screen === "editor"}
    <button class="btn primary" disabled={!exportEnabled} on:click={onOpenExport}>Export</button>
  {/if}
  <button class="btn ghost" on:click={onOpenSettings}>Settings</button>
</div>

<style>
  .topbar { height: 52px; background: var(--surface); border-bottom: 1px solid var(--border); display: flex; align-items: center; padding: 0 16px; gap: 14px; flex-shrink: 0; }
  .brand { display: flex; align-items: center; gap: 8px; font-weight: 600; font-size: 13px; color: var(--text); white-space: nowrap; }
  .mark { width: 22px; height: 22px; border-radius: 6px; background: linear-gradient(135deg, var(--accent), var(--gr)); flex-shrink: 0; }
  .divider { width: 1px; height: 24px; background: var(--border); flex-shrink: 0; }
  .breadcrumb { display: flex; align-items: center; gap: 4px; min-width: 0; flex-shrink: 1; overflow: hidden; }
  .crumb { border: 0; background: transparent; color: var(--text-2); font-size: 12px; font-weight: 600; padding: 4px 6px; border-radius: 6px; cursor: pointer; max-width: 220px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .crumb:hover:not(:disabled) { background: var(--surface-2); color: var(--text); }
  .crumb:disabled { cursor: not-allowed; opacity: 0.6; }
  .crumb.current { color: var(--text); cursor: default; }
  .crumb.current:hover { background: transparent; }
  .crumb-sep { color: var(--text-3); font-size: 12px; flex-shrink: 0; }
  .crumb-select { height: 28px; border: 1px solid transparent; border-radius: 6px; font-size: 12px; font-weight: 600; padding: 0 4px; background: transparent; color: var(--text); max-width: 200px; }
  .crumb-select:hover { background: var(--surface-2); }
  .select { height: 28px; border: 1px solid var(--border); border-radius: 6px; font-size: 12px; padding: 0 6px; background: var(--surface); color: var(--text); flex-shrink: 0; }
  .goto { display: flex; align-items: center; gap: 6px; background: var(--surface-2); border: 1px solid var(--border); border-radius: 6px; padding: 0 8px; height: 28px; width: 150px; flex-shrink: 0; }
  .goto input { border: none; background: transparent; font-size: 12px; color: var(--text); outline: none; width: 100%; }
  .grow { flex: 1; }
  .btn { font-size: 12px; font-weight: 600; padding: 6px 12px; border-radius: 6px; border: 1px solid var(--border-strong); background: var(--surface); color: var(--text); cursor: pointer; flex-shrink: 0; }
  .btn.primary { background: var(--accent); border-color: var(--accent); color: #fff; }
  .btn.primary:disabled { background: #B9C6E0; border-color: #B9C6E0; color: #fff; cursor: not-allowed; }
  .btn.ghost { background: transparent; border-color: var(--border); }
  @media (max-width: 900px) {
    .goto { width: 110px; }
    .crumb { max-width: 130px; }
  }
</style>
