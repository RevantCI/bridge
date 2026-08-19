<script lang="ts">
  import { bridge } from "../api/bridgeClient";
  import {
    selectedVerse, selectedFindings, findingsByVerse, currentChapter,
    verseTexts, verseNums,
  } from "../stores";
  import type { FindingStatus } from "../types/finding";

  let greekRoomChecking = false;

  // Re-run Greek Room live whenever the selected verse changes — per the
  // approved design, Greek Room is the one engine that re-checks live on
  // focus; tN/tW/Alignment are already-computed background-pass results.
  $: if ($selectedVerse) {
    runLiveGreekRoomCheck($selectedVerse);
  }

  async function runLiveGreekRoomCheck(verse: string) {
    greekRoomChecking = true;
    try {
      const findings = await bridge.runVerseChecks($currentChapter, verse, ["greekroom"]);
      findingsByVerse.update((map) => {
        const existing = (map[verse] ?? []).filter((f) => f.engine !== "wildebeest");
        return { ...map, [verse]: [...existing, ...findings] };
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
    findingsByVerse.update((map) => {
      const list = (map[$selectedVerse!] ?? []).map((f) =>
        f.id === findingId ? { ...f, status } : f
      );
      return { ...map, [$selectedVerse!]: list };
    });
  }

  let editing = false;
  let editText = "";

  function startEdit() {
    if (!$selectedVerse) return;
    editText = $verseTexts[$selectedVerse] ?? "";
    editing = true;
  }

  async function saveEdit() {
    if (!$selectedVerse) return;
    await bridge.editVerse($currentChapter, $selectedVerse, editText);
    verseTexts.update((t) => ({ ...t, [$selectedVerse!]: editText }));
    editing = false;
    // re-run all checks on the edited verse since text changed
    const findings = await bridge.runVerseChecks($currentChapter, $selectedVerse, ["local", "greekroom"]);
    findingsByVerse.update((map) => ({ ...map, [$selectedVerse!]: findings }));
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

      {#if editing}
        <div class="section">
          <div class="section-title">Edit verse</div>
          <textarea bind:value={editText} rows="3" />
          <div class="decision-row full">
            <button class="accept" on:click={saveEdit}>Save & re-check</button>
          </div>
        </div>
      {/if}
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
  .check-id { font-size: 11px; color: var(--text-3); }
  .explain { font-size: 12px; color: var(--text-2); line-height: 1.6; margin: 0 0 8px; }
  .evidence { font-size: 11px; color: var(--text-2); padding-left: 16px; margin: 0 0 8px; }
  .decision-row { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 6px; }
  .decision-row.full { grid-template-columns: 1fr; }
  .decision-row button { padding: 7px; font-size: 11px; font-weight: 700; border-radius: 6px; border: none; cursor: pointer; }
  .accept { background: var(--success); color: #fff; }
  .reject { background: var(--danger); color: #fff; }
  .ignore { background: #F5EBFC; color: #9333EA; }
  .none { font-size: 11px; color: var(--text-3); }
  textarea { width: 100%; font-size: 14px; padding: 8px; border: 1px solid var(--accent); border-radius: 6px; font-family: inherit; margin-bottom: 8px; }
  .footer-actions { padding: 12px 16px; border-top: 1px solid var(--border); }
  .edit-btn { width: 100%; padding: 8px; font-size: 12px; font-weight: 700; border-radius: 7px; border: none; background: var(--accent-bg); color: var(--accent); cursor: pointer; }
  .empty-panel { padding: 24px 16px; font-size: 12px; color: var(--text-3); }
</style>
