<script lang="ts">
  import { onMount } from "svelte";
  import { iso6393 } from "iso-639-3";
  import { bridge } from "../api/bridgeClient";
  import { project } from "../stores";
  import type { ImportMetadata, ImportPreview, RegisteredProject } from "../types/finding";

  export let onOpened: () => void;
  export let droppedPath = "";
  export let dropSequence = 0;

  let projects: RegisteredProject[] = [];
  let error: string | null = null;
  let loading = false;
  let preview: ImportPreview | null = null;
  let languageQuery = "";
  let showLanguages = false;
  let handledDropSequence = 0;
  let metadata: ImportMetadata = {
    languageId: "", languageName: "", languageDirection: "ltr",
    projectName: "", bibleName: "",
  };

  onMount(() => { void loadProjects(); });

  $: if (dropSequence > handledDropSequence && droppedPath) {
    handledDropSequence = dropSequence;
    void inspect(droppedPath);
  }

  const languages = iso6393
    .filter((language) => language.type !== "special")
    .sort((a, b) => a.name.localeCompare(b.name));

  $: normalizedLanguageQuery = languageQuery.trim().toLocaleLowerCase();
  $: languageMatches = normalizedLanguageQuery
    ? languages.filter((language) =>
        language.name.toLocaleLowerCase().includes(normalizedLanguageQuery) ||
        language.iso6393.toLocaleLowerCase().startsWith(normalizedLanguageQuery) ||
        (language.iso6391 ?? "").toLocaleLowerCase().startsWith(normalizedLanguageQuery),
      ).slice(0, 40)
    : languages.slice(0, 40);
  $: canImport = Boolean(preview && metadata.languageId && metadata.languageName && metadata.projectName && metadata.bibleName);
  $: exactMatch = preview?.duplicates.matches.find((match) => match.match === "exact" && !match.missing);
  $: visibleProjects = projects.filter((item, index) =>
    !item.collectionId || projects.findIndex((candidate) => candidate.collectionId === item.collectionId) === index,
  );

  function message(value: unknown): string {
    return value instanceof Error ? value.message : String(value);
  }

  async function loadProjects() {
    try {
      projects = (await bridge.listProjects()).projects;
    } catch (value) {
      error = message(value);
    }
  }

  async function openPath(path: string, projectId?: string) {
    loading = true;
    error = null;
    try {
      const info = await bridge.openProject(path, projectId);
      project.set(info);
      onOpened();
    } catch (value) {
      error = message(value);
      await loadProjects();
    } finally {
      loading = false;
    }
  }

  async function openExisting() {
    const path = await bridge.pickProjectFolder();
    if (path) await openPath(path);
  }

  async function locate(item: RegisteredProject) {
    const path = await bridge.pickProjectFolder();
    if (path) await openPath(path, item.projectId);
  }

  async function forget(item: RegisteredProject) {
    loading = true;
    error = null;
    try {
      await bridge.forgetProject(item.projectId);
      await loadProjects();
    } catch (value) {
      error = message(value);
    } finally {
      loading = false;
    }
  }

  async function chooseFile() {
    const path = await bridge.pickImportFile();
    if (path) await inspect(path);
  }

  async function chooseFolder() {
    const path = await bridge.pickProjectFolder();
    if (path) await inspect(path);
  }

  async function inspect(path: string) {
    if (loading) {
      error = "Please wait for the current operation to finish, then drop the source again.";
      return;
    }
    loading = true;
    error = null;
    preview = null;
    try {
      preview = await bridge.inspectImport(path);
      metadata = {
        languageId: preview.metadata.languageId ?? "",
        languageName: preview.metadata.languageName ?? "",
        languageDirection: preview.metadata.languageDirection || "ltr",
        projectName: preview.metadata.projectName ?? "",
        bibleName: preview.metadata.bibleName ?? "",
      };
      languageQuery = metadata.languageName || metadata.languageId;
    } catch (value) {
      error = message(value);
    } finally {
      loading = false;
    }
  }

  function selectLanguage(language: (typeof iso6393)[number]) {
    metadata = { ...metadata, languageId: language.iso6393, languageName: language.name };
    languageQuery = `${language.name} (${language.iso6393})`;
    showLanguages = false;
  }

  async function runImport(allowDuplicate = false) {
    if (!preview || !canImport) return;
    loading = true;
    error = null;
    try {
      const previousClassification = preview.duplicates.classification;
      const refreshed = await bridge.inspectImport(preview.sourcePath, metadata);
      preview = refreshed;
      if (previousClassification === "new" && refreshed.duplicates.classification !== "new") {
        return;
      }
      const info = await bridge.importProject(preview.sourcePath, metadata, allowDuplicate);
      project.set(info);
      onOpened();
    } catch (value) {
      error = message(value);
    } finally {
      loading = false;
    }
  }

  function reset() {
    preview = null;
    error = null;
    languageQuery = "";
    void loadProjects();
  }
</script>

<div class="import-overlay">
  <main class="card" class:wide={preview !== null || projects.length > 0}>
    {#if preview === null}
      <div class="eyebrow">PROJECT HOME</div>
      <h1>Your translation projects</h1>
      <p class="intro">Reopen a recent project, import a source, or drop one file or folder anywhere onto this window.</p>

      {#if visibleProjects.length > 0}
        <section class="projects" aria-label="Known projects">
          {#each visibleProjects as item}
            <article class:missing={item.missing} class="project-row">
              <div class="book-badge">{item.bookId?.toUpperCase() || "?"}</div>
              <div class="project-copy">
                <strong>{item.projectName || item.bookName || "Unnamed project"}</strong>
                <span>{item.collectionId ? `${projects.filter((candidate) => candidate.collectionId === item.collectionId).length}-book collection` : item.bookName}{item.bibleName ? ` · ${item.bibleName}` : ""}{item.targetLanguage ? ` · ${item.targetLanguage}` : ""}</span>
                <small title={item.path}>{item.missing ? "Project folder is missing" : item.path}</small>
              </div>
              {#if item.missing}
                <button class="small-button" on:click={() => locate(item)} disabled={loading}>Locate</button>
                <button class="small-button danger" on:click={() => forget(item)} disabled={loading}>Forget</button>
              {:else}
                <button class="small-button primary" on:click={() => openPath(item.path, item.projectId)} disabled={loading}>Open</button>
              {/if}
            </article>
          {/each}
        </section>
      {:else}
        <p class="empty">No projects are registered yet. Existing app-managed projects will appear here automatically.</p>
      {/if}

      <div class="choice-grid">
        <button class="choice primary" on:click={chooseFile} disabled={loading}>
          <span class="choice-title">Import a file</span>
          <span>USFM, SFM, TXT, TCORE, TSTUDIO or ZIP</span>
        </button>
        <button class="choice" on:click={chooseFolder} disabled={loading}>
          <span class="choice-title">Import a folder</span>
          <span>Multi-book USFM, Paratext or translationCore</span>
        </button>
      </div>

      <button class="link-button" on:click={openExisting} disabled={loading}>Open an existing Bridge/translationCore project without copying it</button>
    {:else}
      <div class="header-row">
        <div>
          <div class="eyebrow">IMPORT REVIEW</div>
          <h1>Confirm project details</h1>
          <p class="source" title={preview.sourcePath}>{preview.sourcePath}</p>
        </div>
        <button class="back" on:click={reset} disabled={loading}>Back to projects</button>
      </div>

      {#if preview.duplicates.classification !== "new"}
        <div class:exact={preview.duplicates.classification === "exactDuplicate"} class="duplicate-notice">
          <strong>{preview.duplicates.classification === "exactDuplicate" ? "This source is already imported." : "This source overlaps an existing project."}</strong>
          <span>{preview.duplicates.matches.length} matching {preview.duplicates.matches.length === 1 ? "project" : "projects"} found. Bridge will never overwrite or merge them automatically.</span>
        </div>
      {/if}

      <div class="content-grid">
        <section class="summary">
          <h2>{preview.books.length} {preview.books.length === 1 ? "book" : "books"} found</h2>
          <div class="book-list">
            {#each preview.books as book}
              <div class="book-row">
                <span class="book-id">{book.bookId.toUpperCase()}</span>
                <span class="book-name">{book.bookName}</span>
                <span class="book-meta">{book.verseCount === null ? "existing project" : `${book.verseCount} verses`}{book.hasAlignments ? " · alignments found" : ""}</span>
              </div>
            {/each}
          </div>
          {#each preview.warnings as warning}<p class="warning">{warning}</p>{/each}
          <p class="note">Every source book is copied into Bridge. The first opens immediately; other books are prepared when opened. Existing projects and source files are preserved.</p>
        </section>

        <section class="form">
          <label>
            <span>Language</span>
            <div class="language-field">
              <input value={languageQuery} placeholder="Search every ISO 639-3 language…" autocomplete="off"
                on:input={(event) => { languageQuery = event.currentTarget.value; metadata = { ...metadata, languageId: "", languageName: "" }; showLanguages = true; }}
                on:focus={() => (showLanguages = true)} />
              {#if showLanguages}
                <div class="language-menu">
                  {#each languageMatches as language}
                    <button type="button" on:mousedown|preventDefault={() => selectLanguage(language)}><span>{language.name}</span><code>{language.iso6393}</code></button>
                  {:else}<div class="no-match">No ISO 639-3 language found</div>{/each}
                </div>
              {/if}
            </div>
          </label>

          <div class="two-col">
            <label><span>Language code</span><input value={metadata.languageId} readonly placeholder="ISO 639-3" /></label>
            <label><span>Text direction</span><select bind:value={metadata.languageDirection}><option value="ltr">Left to right</option><option value="rtl">Right to left</option></select></label>
          </div>
          <label><span>Project name</span><input bind:value={metadata.projectName} placeholder="e.g. Community review 2026" /></label>
          <label><span>Bible / translation name</span><input bind:value={metadata.bibleName} placeholder="e.g. Unlocked Literal Text" /></label>

          {#if exactMatch}
            <button class="import-button" on:click={() => openPath(exactMatch.path, exactMatch.projectId)} disabled={loading}>Open existing project</button>
            <button class="separate-button" on:click={() => runImport(true)} disabled={loading || !canImport}>Import as a separate copy</button>
          {:else}
            <button class="import-button" on:click={() => runImport(false)} disabled={loading || !canImport}>
              {loading ? `Importing ${preview.books.length === 1 ? "book" : `${preview.books.length} books`}…` : `Import ${preview.books.length === 1 ? "book" : `${preview.books.length} books`}`}
            </button>
          {/if}
          {#if !canImport}<p class="required">Select a language and complete both project names.</p>{/if}
        </section>
      </div>
    {/if}

    {#if loading && preview === null}<p class="working">Reading, validating, or opening the selected project…</p>{/if}
    {#if error}<p class="error">{error}</p>{/if}
  </main>
</div>

<style>
  .import-overlay { position: absolute; inset: 0; background: var(--bg); display: flex; align-items: flex-start; justify-content: center; z-index: 20; padding: 28px; overflow: auto; }
  .card { position: relative; width: min(570px, 100%); border: 1px solid var(--border); border-radius: 16px; background: var(--surface); padding: 34px; box-shadow: 0 18px 55px rgba(25, 35, 55, .10); margin: auto; }
  .card.wide { width: min(940px, 100%); }
  .eyebrow { color: var(--accent); font-size: 10px; letter-spacing: .12em; font-weight: 800; margin-bottom: 8px; }
  h1 { font-size: 22px; line-height: 1.2; margin: 0; color: var(--text); }
  h2 { font-size: 13px; margin: 0 0 12px; color: var(--text); }
  .intro { color: var(--text-2); font-size: 13px; line-height: 1.55; margin: 10px 0 20px; }
  .projects { border: 1px solid var(--border); border-radius: 10px; max-height: 270px; overflow: auto; margin-bottom: 18px; }
  .project-row { min-height: 66px; display: flex; align-items: center; gap: 11px; padding: 9px 11px; border-bottom: 1px solid var(--border); }
  .project-row:last-child { border-bottom: 0; }
  .project-row.missing { background: #fff9ed; }
  .book-badge { width: 38px; height: 38px; display: grid; place-items: center; border-radius: 8px; background: var(--accent-bg); color: var(--accent); font-size: 10px; font-weight: 800; flex-shrink: 0; }
  .project-copy { display: flex; flex-direction: column; min-width: 0; flex: 1; gap: 2px; }
  .project-copy strong { font-size: 12px; color: var(--text); }
  .project-copy span, .project-copy small { color: var(--text-2); font-size: 10px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .small-button { border: 1px solid var(--border-strong); border-radius: 6px; background: var(--surface); color: var(--text); padding: 6px 10px; cursor: pointer; font-size: 10px; }
  .small-button.primary { border-color: var(--accent); color: var(--accent); }
  .small-button.danger { color: var(--danger); }
  .empty { background: var(--surface-2); color: var(--text-2); border-radius: 8px; padding: 14px; font-size: 11px; margin: 0 0 18px; }
  .choice-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
  button { font: inherit; }
  .choice { min-height: 82px; text-align: left; border: 1px solid var(--border-strong); background: var(--surface); color: var(--text-2); border-radius: 10px; padding: 14px; cursor: pointer; font-size: 11px; line-height: 1.45; }
  .choice:hover { border-color: var(--accent); background: var(--accent-bg); }
  .choice.primary { border-color: var(--accent); }
  .choice-title { display: block; color: var(--text); font-size: 13px; font-weight: 700; margin-bottom: 5px; }
  .link-button, .back { display: block; border: 0; background: none; color: var(--accent); cursor: pointer; font-size: 11px; margin: 15px auto 0; }
  .header-row { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; padding-bottom: 18px; border-bottom: 1px solid var(--border); }
  .source { color: var(--text-2); font-size: 10px; margin: 7px 0 0; max-width: 650px; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
  .back { margin: 4px 0 0; white-space: nowrap; }
  .duplicate-notice { display: flex; flex-direction: column; gap: 3px; margin-top: 16px; border: 1px solid #e8c268; border-radius: 8px; background: #fff9e9; color: #7a5500; padding: 10px 12px; font-size: 10px; }
  .duplicate-notice.exact { border-color: #e6a9a9; background: #fff2f2; color: #8b2d2d; }
  .content-grid { display: grid; grid-template-columns: minmax(0, .9fr) minmax(320px, 1.1fr); gap: 30px; padding-top: 20px; }
  .summary { min-width: 0; }
  .book-list { border: 1px solid var(--border); border-radius: 8px; max-height: 225px; overflow: auto; }
  .book-row { display: grid; grid-template-columns: 42px 1fr auto; align-items: center; gap: 8px; min-height: 38px; padding: 0 10px; border-bottom: 1px solid var(--border); font-size: 11px; }
  .book-row:last-child { border-bottom: 0; }
  .book-id { color: var(--accent); font-weight: 800; }
  .book-name { color: var(--text); font-weight: 600; }
  .book-meta { color: var(--text-2); font-size: 10px; text-align: right; }
  .warning, .note { border-radius: 7px; padding: 9px 10px; font-size: 10px; line-height: 1.45; margin: 10px 0 0; }
  .warning { background: #fff7e6; color: #8a5a00; }
  .note { background: var(--surface-2); color: var(--text-2); }
  .form { display: flex; flex-direction: column; gap: 13px; }
  label { display: flex; flex-direction: column; gap: 5px; color: var(--text); font-size: 11px; font-weight: 650; }
  input, select { width: 100%; box-sizing: border-box; height: 36px; border: 1px solid var(--border-strong); border-radius: 7px; background: var(--surface); color: var(--text); padding: 0 10px; font-size: 12px; outline: none; }
  input:focus, select:focus { border-color: var(--accent); box-shadow: 0 0 0 2px var(--accent-bg); }
  input[readonly] { background: var(--surface-2); color: var(--text-2); }
  .two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
  .language-field { position: relative; }
  .language-menu { position: absolute; z-index: 5; left: 0; right: 0; top: 40px; max-height: 215px; overflow: auto; border: 1px solid var(--border-strong); border-radius: 8px; background: var(--surface); box-shadow: 0 10px 25px rgba(25, 35, 55, .16); }
  .language-menu button { width: 100%; display: flex; justify-content: space-between; align-items: center; border: 0; border-bottom: 1px solid var(--border); background: var(--surface); color: var(--text); padding: 8px 10px; cursor: pointer; font-size: 11px; text-align: left; }
  .language-menu button:hover { background: var(--accent-bg); }
  .language-menu code { color: var(--text-2); font-size: 10px; }
  .no-match { color: var(--text-2); font-size: 11px; padding: 12px; }
  .import-button, .separate-button { height: 38px; border-radius: 7px; font-size: 12px; font-weight: 700; cursor: pointer; }
  .import-button { border: 1px solid var(--accent); background: var(--accent); color: white; }
  .separate-button { border: 1px solid var(--border-strong); background: var(--surface); color: var(--text-2); }
  button:disabled { opacity: .55; cursor: not-allowed; }
  .required, .working, .error { font-size: 10px; margin: 0; text-align: center; }
  .required, .working { color: var(--text-2); }
  .working { margin-top: 15px; }
  .error { color: var(--danger); margin-top: 13px; line-height: 1.45; }
  @media (max-width: 760px) {
    .content-grid { grid-template-columns: 1fr; }
    .choice-grid { grid-template-columns: 1fr; }
    .card { padding: 24px; }
    .book-row { grid-template-columns: 42px 1fr; }
    .book-meta { grid-column: 2; text-align: left; padding-bottom: 8px; }
  }
</style>
