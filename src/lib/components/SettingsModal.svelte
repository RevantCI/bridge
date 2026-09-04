<script lang="ts">
  import { onMount } from "svelte";
  import { bridge } from "../api/bridgeClient";
  import { navigationStatus, project, reviewerMode } from "../stores";
  import type { SettingsData } from "../types/finding";

  export let onClose: () => void;
  export let initialPane: "ai" | "quality" | "connections" | "resources" | "security" = "ai";

  let activePane: "ai" | "quality" | "connections" | "resources" | "security" = initialPane;
  let loading = true;
  let saving = false;
  let saveMessage = "";

  let provider = "openai";
  let apiBaseUrl = "";
  let model = "gpt-5.6";
  let apiKey = "";
  let hasApiKey = false;
  let mode: "basic" | "advanced" = "basic";
  let paratextNavigation = false;
  let logosNavigation = false;

  const providerPresets: Record<string, string> = {
    openai: "",
    azure: "https://YOUR-RESOURCE.openai.azure.com/openai/deployments/YOUR-DEPLOYMENT",
    local: "http://localhost:11434/v1",
    custom: "",
  };

  onMount(load);

  async function load() {
    loading = true;
    try {
      const s: SettingsData = await bridge.getSettings();
      provider = s.provider || "openai";
      apiBaseUrl = s.apiBaseUrl || "";
      model = s.model || "gpt-5.6";
      hasApiKey = s.hasApiKey;
      mode = s.reviewerMode;
      paratextNavigation = s.paratextNavigation;
      logosNavigation = s.logosNavigation;
      reviewerMode.set(s.reviewerMode);
      navigationStatus.set(await bridge.navigationStatus());
    } catch (e) {
      console.error("failed to load settings", e);
    } finally {
      loading = false;
    }
  }

  function applyPreset() {
    if (provider in providerPresets && !apiBaseUrl) {
      apiBaseUrl = providerPresets[provider];
    }
  }

  async function save() {
    saving = true;
    saveMessage = "";
    try {
      const params: Record<string, unknown> = {
        provider, apiBaseUrl, model, reviewerMode: mode, paratextNavigation, logosNavigation,
      };
      if (apiKey.trim()) params.apiKey = apiKey.trim();
      const result = await bridge.setSettings(params);
      hasApiKey = result.hasApiKey;
      reviewerMode.set(result.reviewerMode);
      apiKey = "";
      navigationStatus.set(await bridge.navigationStatus());
      saveMessage = "Saved.";
    } catch (e) {
      saveMessage = e instanceof Error ? e.message : String(e);
    } finally {
      saving = false;
    }
  }

  async function refreshConnections(): Promise<void> {
    saveMessage = "";
    try {
      navigationStatus.set(await bridge.navigationStatus());
    } catch (e) {
      saveMessage = e instanceof Error ? e.message : String(e);
    }
  }
</script>

<div class="modal-overlay">
  <div class="settings-modal">
    <button class="close-btn" on:click={onClose} aria-label="Close settings">✕</button>
    <div class="settings-nav">
      <div class="nav-title">Settings</div>
      <button class="nav-item" class:active={activePane === "ai"} on:click={() => (activePane = "ai")}>AI provider</button>
      <button class="nav-item" class:active={activePane === "quality"} on:click={() => (activePane = "quality")}>Quality engine</button>
      <button class="nav-item" class:active={activePane === "connections"} on:click={() => (activePane = "connections")}>Connections</button>
      <button class="nav-item" class:active={activePane === "resources"} on:click={() => (activePane = "resources")}>Resources & licenses</button>
      <button class="nav-item" class:active={activePane === "security"} on:click={() => (activePane = "security")}>Security</button>
    </div>

    <div class="settings-body">
      {#if loading}
        <p class="muted">Loading…</p>
      {:else if activePane === "ai"}
        <h3>AI provider</h3>
        <p class="desc">Used only for optional "Explain with AI." Core QA (Greek Room, local checks) never requires this and works fully offline.</p>

        <div class="field">
          <label for="provider">Provider</label>
          <select id="provider" bind:value={provider} on:change={applyPreset}>
            <option value="openai">OpenAI</option>
            <option value="azure">Azure OpenAI</option>
            <option value="local">Local / self-hosted (Ollama, LM Studio, vLLM)</option>
            <option value="custom">Custom</option>
          </select>
        </div>

        <div class="field">
          <label for="baseUrl">API base URL</label>
          <input id="baseUrl" type="text" bind:value={apiBaseUrl} placeholder="Leave blank to use OpenAI's default endpoint" />
          <div class="hint">Works with any OpenAI-Responses-API-compatible endpoint — Azure OpenAI, a self-hosted server, OpenRouter, etc. Blank means the standard OpenAI endpoint.</div>
        </div>

        <div class="field">
          <label for="model">Model</label>
          <input id="model" type="text" bind:value={model} placeholder="e.g. gpt-5.6, claude-sonnet-5, llama3" />
          <div class="hint">For tN/tW review, use a model with strong multilingual reasoning and structured-output support. Small/mini models may miss inflected target-language renderings or omit checks; Bridge keeps uncertain results pending for human review.</div>
        </div>

        <div class="field">
          <label for="apiKey">API key</label>
          <input id="apiKey" type="password" bind:value={apiKey} placeholder={hasApiKey ? "•••••••••••••••• (already set — enter to replace)" : "Enter your API key"} />
          <div class="hint">Stored locally via your OS's secure storage — never sent anywhere except the endpoint above.</div>
        </div>

        <div class="save-row">
          <button class="btn primary" on:click={save} disabled={saving}>{saving ? "Saving…" : "Save"}</button>
          {#if saveMessage}<span class="save-msg">{saveMessage}</span>{/if}
        </div>
      {:else if activePane === "quality"}
        <h3>Quality engine</h3>
        <p class="desc">Greek Room checks run fully offline and never leave this machine.</p>
        <div class="field">
          <div class="field-label">Reviewer experience</div>
          <label class="mode-option" class:selected={mode === "basic"}>
            <input type="radio" bind:group={mode} value="basic" />
            <span><b>Auto</b><small>Streamlined tN/tW review with conservative automatic AI selections and explicit issue handoff.</small></span>
          </label>
          <label class="mode-option" class:selected={mode === "advanced"}>
            <input type="radio" bind:group={mode} value="advanced" />
            <span><b>Manual</b><small>Inspect evidence and edit native translationCore target selections yourself.</small></span>
          </label>
        </div>
        <div class="kv"><span>Offline QA engine (Greek Room)</span><span class="on">On</span></div>
        <div class="kv"><span>Local checks (tN / tW / alignment)</span><span class="on">On</span></div>
        <div class="save-row">
          <button class="btn primary" on:click={save} disabled={saving}>{saving ? "Saving…" : "Save"}</button>
          {#if saveMessage}<span class="save-msg">{saveMessage}</span>{/if}
        </div>
      {:else if activePane === "connections"}
        <h3>Verse navigation</h3>
        <p class="desc">Keep Bridge, Paratext, and Logos on the same verse. Navigation stays on this computer and never changes Scripture text.</p>
        {#if $navigationStatus.ownerConflict}
          <div class="connection-warning">Another Bridge window currently owns desktop navigation. Close it or turn sync off there before enabling this window.</div>
        {/if}
        <label class="connection-option" class:selected={paratextNavigation}>
          <input type="checkbox" bind:checked={paratextNavigation} />
          <span>
            <b>Paratext navigation</b>
            <small>Requires the AI Bridge Connector plugin and an active Scripture window in sync group A–E.</small>
          </span>
          <i class:connected={$navigationStatus.paratext.connected} class:error={Boolean($navigationStatus.paratext.error)} />
        </label>
        <div class="connection-detail">
          {#if !paratextNavigation}Off
          {:else if $navigationStatus.paratext.connected}Connected{#if $navigationStatus.paratext.project_name} · {$navigationStatus.paratext.project_name}{/if}{#if $navigationStatus.paratext.reference} · {$navigationStatus.paratext.reference}{/if}
          {:else if $navigationStatus.paratext.error}{$navigationStatus.paratext.error}
          {:else if $navigationStatus.paratext.checking}Checking…
          {:else}Waiting for Paratext{/if}
        </div>
        <label class="connection-option" class:selected={logosNavigation}>
          <input type="checkbox" bind:checked={logosNavigation} />
          <span>
            <b>Logos navigation</b>
            <small>Requires Logos Desktop for Windows and a navigable Bible panel.</small>
          </span>
          <i class:connected={$navigationStatus.logos.connected} class:error={Boolean($navigationStatus.logos.error)} />
        </label>
        <div class="connection-detail">
          {#if !logosNavigation}Off
          {:else if $navigationStatus.logos.connected}Connected{#if $navigationStatus.logos.reference} · {$navigationStatus.logos.reference}{/if}
          {:else if $navigationStatus.logos.error}{$navigationStatus.logos.error}
          {:else if $navigationStatus.logos.checking}Checking…
          {:else}Waiting for Logos{/if}
        </div>
        <div class="save-row">
          <button class="btn primary" on:click={save} disabled={saving}>{saving ? "Saving…" : "Save & connect"}</button>
          <button class="btn" on:click={refreshConnections} disabled={saving}>Refresh</button>
          {#if saveMessage}<span class="save-msg">{saveMessage}</span>{/if}
        </div>
      {:else if activePane === "resources"}
        <h3>Original-language resources</h3>
        <p class="desc">Bridge bundles versioned Hebrew and Greek source-token indexes for offline word alignment.</p>
        {#if $project?.originalLanguageResource?.available}
          {#if $project.originalLanguageResource.versionMismatch}
            <div class="resource-warning">This project was initialized with a different original-language version. Bridge has not replaced its existing source tokens.</div>
          {/if}
          <div class="kv"><span>Current book source</span><span>{$project.originalLanguageResource.resourceId?.toUpperCase()} {$project.originalLanguageResource.version}</span></div>
          <div class="kv"><span>Language</span><span>{$project.originalLanguageResource.languageId}</span></div>
          <div class="kv"><span>Publisher</span><span>{$project.originalLanguageResource.owner}</span></div>
          <div class="kv"><span>License</span><span>{$project.originalLanguageResource.license}</span></div>
          <div class="resource-note">{$project.originalLanguageResource.attribution}</div>
          <div class="resource-note">Source commit: {$project.originalLanguageResource.commit}</div>
          <div class="resource-note">The installer includes the upstream LICENSE.md and manifest.yaml plus Bridge's NOTICE.md and PROVENANCE.json with file hashes and transformation details.</div>
        {:else if $project}
          <p class="muted">{$project.originalLanguageResource?.message ?? "No original-language resource is available for this book."}</p>
        {:else}
          <p class="muted">Open a project to see whether it uses bundled UHB 3.0.0 or UGNT 0.34.</p>
        {/if}
      {:else if activePane === "security"}
        <h3>Security & privacy</h3>
        <p class="desc">Project data and Greek Room findings never leave this machine unless you explicitly use AI explain.</p>
        <div class="kv"><span>API key storage</span><span>OS secure storage (DPAPI on Windows)</span></div>
      {/if}
    </div>
  </div>
</div>

<style>
  .modal-overlay { position: absolute; inset: 0; background: rgba(15, 20, 26, 0.45); display: flex; align-items: center; justify-content: center; z-index: 30; }
  .settings-modal { width: 640px; height: 480px; background: var(--surface); border-radius: 14px; display: flex; overflow: hidden; position: relative; }
  .close-btn { position: absolute; top: 10px; right: 10px; z-index: 2; width: 28px; height: 28px; border-radius: 6px; border: none; background: transparent; color: var(--text-2); font-size: 14px; cursor: pointer; }
  .close-btn:hover { background: var(--surface-2); }
  .settings-nav { width: 170px; background: var(--surface-2); border-right: 1px solid var(--border); padding: 14px 8px; flex-shrink: 0; }
  .nav-title { font-size: 12px; font-weight: 700; color: var(--text); padding: 6px 10px 12px; }
  .nav-item { display: block; width: 100%; text-align: left; padding: 8px 10px; border-radius: 7px; font-size: 12px; font-weight: 600; color: var(--text-2); background: transparent; border: none; cursor: pointer; margin-bottom: 2px; }
  .nav-item:hover { background: var(--surface); }
  .nav-item.active { background: var(--accent-bg); color: var(--accent); }
  .settings-body { flex: 1; padding: 20px 24px; overflow-y: auto; }
  h3 { font-size: 14px; margin: 0 0 4px; color: var(--text); }
  .desc { font-size: 11px; color: var(--text-2); margin: 0 0 16px; }
  .muted { font-size: 12px; color: var(--text-3); }
  .field { margin-bottom: 14px; }
  .field > label, .field-label { display: block; font-size: 11px; font-weight: 700; color: var(--text-2); margin-bottom: 5px; }
  .field input, .field select { width: 100%; height: 34px; border: 1px solid var(--border); border-radius: 6px; padding: 0 10px; font-size: 12px; color: var(--text); background: var(--surface-2); box-sizing: border-box; }
  .hint { font-size: 10px; color: var(--text-3); margin-top: 4px; }
  .mode-option { display: flex; align-items: flex-start; gap: 9px; border: 1px solid var(--border); border-radius: 8px; padding: 9px 10px; margin-bottom: 7px; cursor: pointer; background: var(--surface-2); }
  .mode-option.selected { border-color: var(--accent); background: var(--accent-bg); }
  .mode-option input { width: auto; height: auto; margin: 2px 0 0; }
  .mode-option span { display: flex; flex-direction: column; gap: 2px; font-size: 11px; color: var(--text); }
  .mode-option small { color: var(--text-2); line-height: 1.35; }
  .save-row { display: flex; align-items: center; gap: 10px; margin-top: 6px; }
  .btn { font-size: 12px; font-weight: 600; padding: 8px 14px; border-radius: 6px; border: 1px solid var(--border-strong); background: var(--surface); color: var(--text); cursor: pointer; }
  .btn.primary { background: var(--accent); border-color: var(--accent); color: #fff; }
  .btn:disabled { opacity: 0.6; cursor: not-allowed; }
  .save-msg { font-size: 11px; color: var(--success); }
  .kv { display: flex; justify-content: space-between; font-size: 12px; padding: 6px 0; border-bottom: 1px dashed var(--border); }
  .kv .on { color: var(--success); font-weight: 700; }
  .resource-note { font-size: 10px; line-height: 1.45; color: var(--text-3); margin-top: 10px; overflow-wrap: anywhere; }
  .resource-warning { font-size: 11px; line-height: 1.4; color: var(--danger); background: var(--danger-bg); border: 1px solid var(--danger); border-radius: 6px; padding: 8px; margin-bottom: 10px; }
  .connection-warning { font-size: 11px; line-height: 1.4; color: var(--danger); background: var(--danger-bg); border: 1px solid var(--danger); border-radius: 6px; padding: 8px; margin-bottom: 10px; }
  .connection-option { display: grid; grid-template-columns: auto 1fr auto; align-items: start; gap: 9px; border: 1px solid var(--border); border-radius: 8px; padding: 10px; cursor: pointer; background: var(--surface-2); }
  .connection-option.selected { border-color: var(--accent); background: var(--accent-bg); }
  .connection-option input { width: auto; height: auto; margin: 2px 0 0; }
  .connection-option span { display: flex; flex-direction: column; gap: 2px; font-size: 11px; }
  .connection-option small { color: var(--text-2); line-height: 1.35; }
  .connection-option i { width: 9px; height: 9px; border-radius: 50%; margin-top: 3px; background: var(--border-strong); }
  .connection-option i.connected { background: var(--success); }
  .connection-option i.error { background: var(--danger); }
  .connection-detail { min-height: 26px; padding: 5px 8px 8px 31px; color: var(--text-3); font-size: 10px; line-height: 1.35; overflow-wrap: anywhere; }
</style>
