<script lang="ts">
  import { bridge } from "../api/bridgeClient";
  import {
    selectedVerse, selectedFindings, findingsByVerse, currentChapter,
    verseTexts, checkStatusByVerse, verseKey,
  } from "../stores";
  import type { FindingStatus } from "../types/finding";

  let greekRoomChecking = false;
  let lastCheckedKey = "";

  // Re-run Greek Room live whenever the selected verse changes — per the
  // approved design, Greek Room is the one engine that re-checks live on
  // focus; tN/tW/Alignment are already-computed background-pass results.
  $: if ($selectedVerse) {
    const key = verseKey($currentChapter, $selectedVerse);
    if (key !== lastCheckedKey) {
      lastCheckedKey = key;
      runLiveGreekRoomCheck($currentChapter, $selectedVerse);
    }
  }

  async function runLiveGreekRoomCheck(chapter: string, verse: string) {
    greekRoomChecking = true;
    try {
      const findings = await bridge.runVerseChecks(chapter, verse, ["greekroom"]);
      const key = verseKey(chapter, verse);
      findingsByVerse.update((map) => {
        const existing = (map[key] ?? []).filter((f) => f.engine !== "wildebeest");
        return { ...map, [key]: [...existing, ...findings] };
      });
    } catch (e) {
      console.error("Greek Room live check failed", e);
    } finally {
      greekRoomChecking = false;
    }
  }

  async function decide(findingId: string, status: FindingStatus) {
    if (!$selectedVerse) return;
    await bridge.decideVerse($currentChapter, $selectedVerse, findingId, status);
    const key = verseKey($currentChapter, $selectedVerse);
    findingsByVerse.update((map) => {
      const list = (map[key] ?? []).map((f) => (f.id === findingId ? { ...f, status } : f));
      return { ...map, [key]: list };
    });
  }

  let editing = false;
  let editText = "";
  let editError: string | null = null;
  let editSaving = false;

  function startEdit() {
    if (!$selectedVerse) return;
    editText = $verseTexts[verseKey($currentChapter, $selectedVerse)] ?? "";
    editError = null;
    editing = true;
  }

  async function saveEdit() {
    if (!$selectedVerse) return;
    const key = verseKey($currentChapter, $selectedVerse);
    if (editText.trim() === ($verseTexts[key] ?? "").trim()) {
      // No real change — apply_scripture_edit rejects this as a no-op
      // rather than journaling a spurious edit, so don't call it.
      editing = false;
      return;
    }
    editError = null;
    editSaving = true;
    try {
      await bridge.editVerse($currentChapter, $selectedVerse, editText);
      verseTexts.update((t) => ({ ...t, [key]: editText }));
      editing = false;
      checkStatusByVerse.update((map) => ({ ...map, [key]: "pending" }));
      const findings = await bridge.runVerseChecks($currentChapter, $selectedVerse, ["local", "greekroom"]);
      findingsByVerse.update((map) => ({ ...map, [key]: findings }));
      checkStatusByVerse.update((map) => ({ ...map, [key]: "succeeded" }));
    } catch (e) {
      checkStatusByVerse.update((map) => ({ ...map, [key]: "failed" }));
      editError = e instanceof Error ? e.message : String(e);
    } finally {
      editSaving = false;
    }
  }

  const severityBadge: Record<string, string> = {
    high: "badge-wrong", medium: "badge-review", low: "badge-review", info: "badge-review",
  };
</script>

<div class="panel">
  {#if $selectedVerse}
    <div class="panel-header">
      <div class="ref">{$currentChapter}:{$selectedVerse} — verse review</div>
      <div class="sub">
        {$selectedFindings.filter((f) => f.status === "open").length} open finding(s)
      </div>
    </div>

    <div class="panel-scroll">
      {#if editing}
        <div class="section">
          <div class="section-title">Edit verse</div>
          <textarea bind:value={editText} rows="3" />
          {#if editError}<p class="edit-error">{editError}</p>{/if}
          <div class="edit-actions">
            <button class="accept" on:click={saveEdit} disabled={editSaving || editText.trim() === ""}>
              {editSaving ? "Saving…" : "Save & re-check"}
            </button>
            <button class="cancel" on:click={() => (editing = false)} disabled={editSaving}>Cancel</button>
          </div>
        </div>
      {/if}

      <div class="section">
        <div class="section-title">
          Greek Room QA
          {#if greekRoomChecking}
            <span class="live"><span class="spin" /> live check</span>
          {/if}
        </div>
        {#each $selectedFindings.filter((f) => f.engine === "wildebeest") as f}
          <div class="finding">
            <div class="verdict">
              <span class="badge {severityBadge[f.severity]}">{f.severity}</span>
              <span class="check-id">{f.check_type}</span>
              {#if f.status !== "open"}<span class="badge badge-decided">{f.status}</span>{/if}
            </div>
            <p class="explain">{f.explanation}</p>
            {#if f.evidence.length > 0}
              <ul class="evidence">
                {#each f.evidence as e}<li>{e.label}: {e.value}</li>{/each}
              </ul>
            {/if}
            <div class="decision-row">
              <button class="accept" on:click={() => decide(f.id, "accepted")}>✓ Accept</button>
              <button class="reject" on:click={() => decide(f.id, "rejected")}>✗ Reject</button>
              <button class="ignore" on:click={() => decide(f.id, "ignored")}>⊘ Ignore</button>
            </div>
          </div>
        {:else}
          {#if !greekRoomChecking}<p class="none">No Greek Room findings.</p>{/if}
        {/each}
      </div>

      <div class="section">
        <div class="section-title">Already computed in background pass</div>
        {#each $selectedFindings.filter((f) => f.engine !== "wildebeest") as f}
          <div class="finding">
            <div class="verdict">
              <span class="badge {severityBadge[f.severity]}">{f.severity}</span>
              <span class="check-id">{f.category}</span>
              {#if f.status !== "open"}<span class="badge badge-decided">{f.status}</span>{/if}
            </div>
            <p class="explain">{f.explanation}</p>
            <div class="decision-row">
              <button class="accept" on:click={() => decide(f.id, "accepted")}>✓ Accept</button>
              <button class="reject" on:click={() => decide(f.id, "rejected")}>✗ Reject</button>
              <button class="ignore" on:click={() => decide(f.id, "ignored")}>⊘ Ignore</button>
            </div>
          </div>
        {:else}
          <p class="none">No local QA findings.</p>
        {/each}
      </div>

    </div>

    <div class="footer-actions">
      <button class="edit-btn" on:click={startEdit}>✎ Edit verse</button>
    </div>
  {:else}
    <div class="empty-panel">Select a verse to review its findings.</div>
  {/if}
</div>

<style>
  .panel { width: 400px; flex-shrink: 0; background: var(--surface); display: flex; flex-direction: column; overflow: hidden; border-left: 1px solid var(--border); }
  .panel-header { padding: 14px 16px; border-bottom: 1px solid var(--border); }
  .ref { font-size: 13px; font-weight: 700; color: var(--text); }
  .sub { font-size: 11px; color: var(--text-2); margin-top: 2px; }
  .panel-scroll { flex: 1; overflow-y: auto; padding: 14px 16px; }
  .section { border: 1px solid var(--border); border-radius: 12px; padding: 12px 14px; margin-bottom: 12px; }
  .section-title { font-size: 11px; font-weight: 700; color: var(--text); display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
  .live { display: flex; align-items: center; gap: 5px; font-size: 10px; font-weight: 700; color: var(--gr); }
  .spin { width: 10px; height: 10px; border-radius: 50%; border: 2px solid var(--gr-bg); border-top-color: var(--gr); animation: spin 0.8s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .finding { border-top: 1px dashed var(--border); padding-top: 10px; margin-top: 10px; }
  .finding:first-child { border-top: none; padding-top: 0; margin-top: 0; }
  .verdict { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
  .badge { font-size: 10px; font-weight: 700; padding: 3px 8px; border-radius: 5px; }
  .badge-wrong { background: var(--danger-bg); color: var(--danger); }
  .badge-review { background: var(--warning-bg); color: var(--warning); }
  .badge-decided { background: var(--success-bg); color: var(--success); text-transform: capitalize; }
  .check-id { font-size: 11px; color: var(--text-3); }
  .explain { font-size: 12px; color: var(--text-2); line-height: 1.6; margin: 0 0 8px; }
  .evidence { font-size: 11px; color: var(--text-2); padding-left: 16px; margin: 0 0 8px; }
  .decision-row { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 6px; }
  .decision-row button { padding: 7px; font-size: 11px; font-weight: 700; border-radius: 6px; border: none; cursor: pointer; }
  .accept { background: var(--success); color: #fff; }
  .reject { background: var(--danger); color: #fff; }
  .ignore { background: #F5EBFC; color: #9333EA; }
  .none { font-size: 11px; color: var(--text-3); }
  textarea { width: 100%; font-size: 14px; padding: 8px; border: 1px solid var(--accent); border-radius: 6px; font-family: inherit; margin-bottom: 8px; }
  .edit-error { color: var(--danger); font-size: 11px; margin: -4px 0 8px; line-height: 1.4; }
  .edit-actions { display: flex; gap: 6px; }
  .edit-actions button { flex: 1; padding: 7px; font-size: 11px; font-weight: 700; border-radius: 6px; cursor: pointer; }
  .edit-actions .accept { border: none; }
  .cancel { background: var(--surface-2); color: var(--text-2); border: 1px solid var(--border-strong); }
  .decision-row button:disabled, .edit-actions button:disabled { opacity: .55; cursor: not-allowed; }
  .footer-actions { padding: 12px 16px; border-top: 1px solid var(--border); }
  .edit-btn { width: 100%; padding: 8px; font-size: 12px; font-weight: 700; border-radius: 7px; border: none; background: var(--accent-bg); color: var(--accent); cursor: pointer; }
  .empty-panel { padding: 24px 16px; font-size: 12px; color: var(--text-3); }
</style>
