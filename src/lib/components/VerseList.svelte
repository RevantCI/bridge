<script lang="ts">
  import { tick } from "svelte";
  import { verseNums, verseTexts, findingsByVerse, checkStatusByVerse, alignmentStatusByVerse, selectedVerse, currentChapter, showSource, verseKey, nativeChecksByVerse, aiCheckReviewsByVerse } from "../stores";
  import { buildSegments } from "../utils/highlight";
  import { parseVerseNotes, withNoteMarkers, type ParsedVerse, type VerseNote, type VerseNoteKind } from "../utils/usfmNotes";
  import VerseNotesPopup from "./VerseNotesPopup.svelte";
  import FindingContextMenu from "./FindingContextMenu.svelte";
  import { decideLocalFinding } from "../findingActions";
  import type { QaFinding } from "../types/finding";
  import {
    applySuggestedFindingFix, editingChapter, editingVerse, editText, editSaving,
    editError, saveVerseEdit, cancelVerseEdit, startVerseEdit,
  } from "../verseEditor";

  export let onSelect: (verse: string) => void;

  let openNotes: { kind: VerseNoteKind; notes: VerseNote[]; reference: string } | null = null;
  let contextMenu: { finding: QaFinding; verse: string; x: number; y: number } | null = null;
  let contextBusy = false;
  // Which underlined finding Left/Right last landed on, scoped to one verse
  // key so switching verses starts at that verse's first finding again.
  let activeFindingVerseKey = "";
  let activeFindingIndex = 0;
  let contextNotice = "";
  let contextNoticeError = false;

  /**
   * The same two actions ReviewPanel offers on an open Greek Room finding
   * ("Accept and edit" / "Ignore"), so the menu and the panel cannot disagree
   * about what a reviewer can do to a finding.
   *
   * Accept folds the correction in rather than offering it separately: a fix
   * a reviewer agrees with and the decision that follows from it are one act,
   * and there is no apply item left stranded and greyed out on the many checks
   * that propose no replacement. Each hint says which of the two things Accept
   * is about to do.
   *
   * These write engine FindingStatus values. The QA review queue's
   * REVIEWER_ACTIONS are a different model over a different data source, and
   * its "Accept translation as correct" means the opposite of "Accept finding"
   * here — see the hints, and USER_MANUAL.md §6.4.
   */
  $: contextActions = contextMenu ? [
    {
      id: "accept",
      label: "Accept finding",
      disabled: contextBusy,
      title: hasProposedFix(contextMenu.finding)
        ? "Replace the highlighted words with the proposed correction, re-check the verse, and file this finding as accepted."
        : "File this finding as accepted. This check proposed no correction, so the verse text is left alone.",
    },
    {
      id: "ignore",
      label: "Ignore",
      disabled: contextBusy,
      title: "Leave the verse as it is and move this finding to Ignored in the review panel.",
    },
  ] : [];

  const hasProposedFix = (finding: QaFinding): boolean =>
    finding.suggested_replacement !== null
      && finding.start_offset !== null && finding.end_offset !== null;

  const markerLabel = (kind: VerseNoteKind): string => (kind === "footnote" ? "f" : "x");
  const markerTitle = (kind: VerseNoteKind): string =>
    kind === "footnote" ? "Footnote" : "Cross reference";

  function openFindingMenu(
    event: MouseEvent,
    findingIds: string[],
    findings: QaFinding[],
    verse: string,
  ): void {
    const finding = findingIds
      .map((id) => findings.find((item) => item.id === id))
      .find((item): item is QaFinding => Boolean(item));
    if (!finding) return;
    event.preventDefault();
    event.stopPropagation();
    onSelect(verse);
    contextMenu = { finding, verse, x: event.clientX, y: event.clientY };
  }

  /**
   * Finding ids that actually carry an underline in this verse, in reading
   * order — same filter and sort buildSegments/findingNumbers use, so the
   * keyboard walks the marks a reviewer can see, in the order their
   * superscript numbers run.
   */
  function markedFindingIds(findings: QaFinding[], textLength: number): string[] {
    return findings
      .filter((f) => f.start_offset !== null && f.end_offset !== null && f.end_offset <= textLength)
      .sort((a, b) => (a.start_offset! - b.start_offset!) || a.id.localeCompare(b.id))
      .map((f) => f.id);
  }

  // Reactive rather than a plain function so the each-block {@const} that calls
  // it re-evaluates when the active finding moves: Svelte invalidates on the
  // reference to activeIndexFor, not on variables read inside a function body.
  $: activeIndexFor = (verseKeyValue: string, count: number): number =>
    verseKeyValue === activeFindingVerseKey && activeFindingIndex < count ? activeFindingIndex : 0;

  /**
   * Keyboard route to the same menu the right-click opens — without it,
   * "Apply proposed fix" would be reachable by pointer only, since the review
   * panel has no apply-fix control.
   *
   * The verse row stays the single tab stop, the way QaFindingList's listbox
   * does it: making every underlined span focusable would add one tab stop per
   * finding inside the verse text, so tabbing through a checked chapter would
   * stop on hundreds of words. Left/Right move the active finding within the
   * row instead, and Shift+F10 (or the Menu key) opens the menu anchored under
   * that finding's underline.
   */
  function onVerseKeydown(
    event: KeyboardEvent,
    verse: string,
    key: string,
    findingIds: string[],
    findings: QaFinding[],
  ): void {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onSelect(verse);
      return;
    }
    if (findingIds.length === 0) return;
    const index = activeIndexFor(key, findingIds.length);
    if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
      event.preventDefault();
      onSelect(verse);
      activeFindingVerseKey = key;
      activeFindingIndex =
        (index + (event.key === "ArrowRight" ? 1 : -1) + findingIds.length) % findingIds.length;
      return;
    }
    if (event.key !== "ContextMenu" && !(event.shiftKey && event.key === "F10")) return;
    event.preventDefault();
    const finding = findings.find((item) => item.id === findingIds[index]);
    if (!finding) return;
    onSelect(verse);
    activeFindingVerseKey = key;
    activeFindingIndex = index;
    const row = event.currentTarget as HTMLElement;
    const anchor = row.querySelector<HTMLElement>(`[data-finding-ids~="${findingIds[index]}"]`) ?? row;
    const rect = anchor.getBoundingClientRect();
    contextMenu = { finding, verse, x: rect.left, y: rect.bottom };
  }

  async function onContextAction(event: CustomEvent<{ id: string }>): Promise<void> {
    if (!contextMenu || contextBusy) return;
    const { finding, verse } = contextMenu;
    contextBusy = true;
    contextNotice = "";
    try {
      if (event.detail.id === "accept" && hasProposedFix(finding)) {
        // applySuggestedFindingFix records the accept itself: it hands the
        // finding id to the save hook ReviewPanel registers, which files it as
        // accepted once the re-check lands. A fix that could not be applied is
        // NOT then quietly accepted — the reviewer sees why and the menu stays
        // open so they can choose again.
        const result = await applySuggestedFindingFix(finding);
        contextNotice = result.message;
        contextNoticeError = !result.ok;
        if (result.ok) contextMenu = null;
      } else if (event.detail.id === "accept" || event.detail.id === "ignore") {
        const accepted = event.detail.id === "accept";
        // $currentChapter and the verse the menu was opened on, not
        // finding.chapter/finding.verse: those are numeric anchors, so a verse
        // bridge ("3-4") would file the decision under "3" and miss the store
        // entry. ReviewPanel keys its own decisions the same way this does.
        await decideLocalFinding(
          $currentChapter, verse, finding.id, accepted ? "accepted" : "ignored",
        );
        contextNotice = accepted ? "Finding accepted." : "Finding ignored.";
        contextNoticeError = false;
        contextMenu = null;
      }
    } catch (error) {
      contextNotice = error instanceof Error ? error.message : String(error);
      contextNoticeError = true;
    } finally {
      contextBusy = false;
    }
  }

  /**
   * QaFinding offsets index the RAW verse string — bridge_service's
   * _first_token_span computes them that way deliberately so they line up with
   * what this component highlights. Now that the rendered text has notes and
   * markers removed, every span has to move with it or each underline slides
   * off its word. A finding that lived entirely inside a lifted footnote
   * collapses to zero length and simply covers no segment; it stays in the
   * list so the 1-based numbering still agrees with ReviewPanel.
   */
  function remapFindings(findings: QaFinding[], parsed: ParsedVerse): QaFinding[] {
    return findings.map((finding) =>
      finding.start_offset !== null && finding.end_offset !== null
        ? {
            ...finding,
            start_offset: parsed.mapOffset(finding.start_offset),
            end_offset: parsed.mapOffset(finding.end_offset),
          }
        : finding,
    );
  }

  let scrollContainer: HTMLDivElement;
  let lastScrolledKey = "";

  async function scrollSelectedToTop(key: string): Promise<void> {
    await tick();
    const target = scrollContainer?.querySelector<HTMLElement>(`[data-verse-key="${key}"]`);
    if (!target) return;
    const containerRect = scrollContainer.getBoundingClientRect();
    const targetRect = target.getBoundingClientRect();
    scrollContainer.scrollTo({
      top: Math.max(0, scrollContainer.scrollTop + targetRect.top - containerRect.top - 8),
      behavior: "smooth",
    });
    lastScrolledKey = key;
  }

  $: {
    const key = $selectedVerse ? verseKey($currentChapter, $selectedVerse) : "";
    if (key && scrollContainer && key !== lastScrolledKey) void scrollSelectedToTop(key);
  }

  /**
   * Selecting by clicking a row must not scroll. The row is already on screen
   * -- the reader just pointed at it -- so pulling it to the top moves the
   * text out from under the cursor. Marking the key as already-scrolled is
   * what suppresses it, rather than dropping the reactive scroll: navigation
   * that does not come from a click (Go to, desktop verse sync, a click
   * through from the report) still has to bring the verse into view, and none
   * of those routes come through here.
   */
  function selectFromList(verse: string): void {
    lastScrolledKey = verseKey($currentChapter, verse);
    onSelect(verse);
  }

  /** Double-click is a second route to Edit verse, for readers who never look
   *  at the review panel's button. startVerseEdit carries its own guards --
   *  it returns false while a check, save or recheck is in flight -- so there
   *  is nothing to re-check here. */
  function beginEditFromList(verse: string): void {
    if ($editingChapter === $currentChapter && $editingVerse === verse) return;
    selectFromList(verse);
    startVerseEdit($currentChapter, verse);
  }

  // Grows the edit textarea to fit its full content (1, 2, or more lines)
  // with no scrollbar, plus one blank line of buffer at the bottom — rather
  // than a fixed rows="2" that scrolls for longer verses and wastes space
  // for short ones.
  function autosize(node: HTMLTextAreaElement) {
    const resize = () => {
      node.style.height = "auto";
      const lineHeight = parseFloat(getComputedStyle(node).lineHeight) || 20;
      const borderHeight = node.offsetHeight - node.clientHeight;
      node.style.height = `${node.scrollHeight + lineHeight + borderHeight}px`;
    };
    resize();
    node.addEventListener("input", resize);
    return { destroy: () => node.removeEventListener("input", resize) };
  }
</script>

<div class="editor-scroll" class:show-source={$showSource} bind:this={scrollContainer}>
  <div class="chapter-label">Chapter {$currentChapter}</div>

  {#each $verseNums as v}
    {@const key = verseKey($currentChapter, v)}
    {@const findings = $findingsByVerse[key] ?? []}
    {@const checkStatus = $checkStatusByVerse[key]}
    {@const alignmentStatus = $alignmentStatusByVerse[key] ?? "untouched"}
    {@const openCount = findings.filter((f) => f.status === "open").length}
    {@const highlightFindings = findings.filter((f) => f.status !== "ignored" && f.status !== "accepted")}
    {@const parsed = parseVerseNotes($verseTexts[key] ?? "")}
    {@const remapped = remapFindings(highlightFindings, parsed)}
    {@const segments = buildSegments(parsed.clean, remapped, $nativeChecksByVerse[key] ?? [], $aiCheckReviewsByVerse[key] ?? [])}
    {@const menuFindingIds = markedFindingIds(remapped, parsed.clean.length)}
    {@const activeFindingId = menuFindingIds[activeIndexFor(key, menuFindingIds.length)]}
    {@const isEditingThis = $editingChapter === $currentChapter && $editingVerse === v}
    <div
      class="verse"
      class:editing-row={isEditingThis}
      data-verse-key={key}
      class:active={$selectedVerse === v}
      class:approved={checkStatus === "succeeded" && openCount === 0}
      class:check-failed={checkStatus === "failed" || checkStatus === "cancelled"}
      role="button"
      tabindex="0"
      aria-haspopup={menuFindingIds.length ? "menu" : undefined}
      aria-keyshortcuts={menuFindingIds.length ? "Shift+F10" : undefined}
      on:click={() => selectFromList(v)}
      on:dblclick={() => beginEditFromList(v)}
      on:keydown={(e) => onVerseKeydown(e, v, key, menuFindingIds, findings)}
    >
      <div class="vnum">
        {v}{#if checkStatus === "succeeded" && openCount === 0}&nbsp;✓{:else if checkStatus === "failed" || checkStatus === "cancelled"}&nbsp;⚠{/if}
      </div>
      {#if isEditingThis}
        <div class="vedit" on:click|stopPropagation on:dblclick|stopPropagation on:keydown|stopPropagation role="presentation">
          <div class="vedit-row">
            <textarea use:autosize bind:value={$editText} disabled={$editSaving} />
            <div class="edit-actions">
              <button
                class="icon-btn save" on:click={() => void saveVerseEdit()}
                disabled={$editSaving || $editText.trim() === ""}
                title={$editSaving ? "Saving…" : "Save & re-check"}
              >{#if $editSaving}<span class="spin-sm" />{:else}✓{/if}</button>
              <button class="icon-btn cancel" on:click={cancelVerseEdit} disabled={$editSaving} title="Cancel">✕</button>
            </div>
          </div>
          {#if $editError}<p class="edit-error">{$editError}</p>{/if}
        </div>
      {:else}
        <div class="vtext">
          {#each withNoteMarkers(segments, parsed.notes) as piece}
            {#if piece.kind === "note"}<button
                class="note-btn {piece.note.kind}"
                on:dblclick|stopPropagation
                on:click|stopPropagation={() =>
                  (openNotes = { kind: piece.note.kind, notes: [piece.note], reference: key })}
                title={`${markerTitle(piece.note.kind)}${piece.note.reference ? ` ${piece.note.reference}` : ""}`}
                aria-label={`Show ${markerTitle(piece.note.kind).toLowerCase()} at this point in verse ${key}`}
              >{markerLabel(piece.note.kind)}</button>{:else if piece.seg.className}<mark
                class={piece.seg.className}
                class:active-finding={$selectedVerse === v && activeFindingId !== undefined
                  && piece.seg.findingIds.includes(activeFindingId)}
                data-finding-ids={piece.seg.findingIds.join(" ")}
                title={piece.seg.title}
                on:contextmenu={(event) => openFindingMenu(event, piece.seg.findingIds, findings, v)}
              >{piece.seg.text}</mark>{#if piece.seg.numbers.length}<sup class="finding-num">{piece.seg.numbers.join(",")}</sup>{/if}{:else}{piece.seg.text}{/if}
          {/each}
        </div>
        <span class="alignment-state {alignmentStatus}" title={`Alignment: ${alignmentStatus}`}>
          {alignmentStatus === "complete" ? "●" : alignmentStatus === "partial" ? "◐" : alignmentStatus === "invalid" ? "!" : "○"}
        </span>
      {/if}
    </div>
  {/each}

  {#if $verseNums.length === 0}
    <p class="empty">No verses loaded for this chapter yet.</p>
  {/if}
</div>

{#if contextNotice}
  <p class="context-notice" class:error={contextNoticeError} role="status">{contextNotice}</p>
{/if}

{#if contextMenu}
  <FindingContextMenu
    x={contextMenu.x}
    y={contextMenu.y}
    findingLabel="Actions for {contextMenu.finding.explanation}"
    actions={contextActions}
    on:action={onContextAction}
    on:close={() => (contextMenu = null)}
  />
{/if}

{#if openNotes}
  <VerseNotesPopup
    kind={openNotes.kind}
    notes={openNotes.notes}
    reference={openNotes.reference}
    onClose={() => (openNotes = null)}
  />
{/if}

<style>
  .editor-scroll { flex: 1; overflow-y: auto; padding: 22px 32px; background: var(--surface); }
  .chapter-label { font-size: var(--fs-xs); font-weight: 700; color: var(--text-3); text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 14px; }
  .verse { display: flex; gap: 10px; padding: 9px 10px; border-radius: 7px; margin-bottom: 2px; cursor: pointer; border: 1px solid transparent; }
  .verse:hover { background: var(--surface-2); }
  .verse.active { background: var(--accent-bg); border-color: #C7D9FB; }
  .vnum { font-size: var(--fs-xs); font-weight: 700; color: var(--text-3); width: 26px; flex-shrink: 0; padding-top: 2px; }
  .verse.approved .vnum { color: var(--success); }
  .verse.check-failed .vnum { color: var(--danger, #ef4444); }
  .vtext { font-size: var(--fs-xl); line-height: 1.85; color: var(--text); }
  .finding-num { font-size: var(--fs-2xs); font-weight: 700; color: var(--accent); margin-left: 1px; }
  /* Where Shift+F10 would open the menu. A visible ring, not colour alone:
     the underline classes already carry the finding's source colour. */
  mark.active-finding { outline: 2px solid var(--accent); outline-offset: 1px; border-radius: 2px; }
  /* Sits inline where the note was, like a printed Bible's callout. A plain
     letter, not an icon font: an offline PyInstaller build can't reach a CDN
     and icon-only controls render as empty boxes there. */
  .note-btn {
    font: inherit; font-size: var(--fs-2xs); font-weight: 800; font-style: italic; line-height: 1;
    vertical-align: super; margin: 0 1px; padding: 1px 3px; cursor: pointer;
    border: 1px solid var(--border-strong); border-radius: 3px;
    background: var(--surface-2); color: var(--text-2);
  }
  .note-btn:hover { background: var(--accent-bg); border-color: var(--accent); color: var(--accent); }
  .note-btn.xref { color: var(--accent); }
  .alignment-state { margin-left: auto; flex-shrink: 0; padding-top: 3px; font-size: var(--fs-xs); color: var(--text-3); }
  .alignment-state.complete { color: var(--success); }
  .alignment-state.partial { color: var(--warning); }
  .alignment-state.invalid { color: var(--danger); font-weight: 800; }
  .empty { color: var(--text-3); font-size: var(--fs-md); }
  .context-notice {
    position: fixed; left: 50%; bottom: 34px; z-index: 9000; transform: translateX(-50%);
    margin: 0; padding: 7px 11px; border-radius: 6px; background: var(--success-bg);
    color: var(--success); font-size: var(--fs-sm); box-shadow: 0 4px 14px rgba(15, 23, 42, .18);
  }
  .context-notice.error { background: var(--danger-bg, #fef2f2); color: var(--danger, #b91c1c); }
  .verse.editing-row { cursor: default; background: var(--surface); }
  .vedit { flex: 1; min-width: 0; cursor: default; }
  .vedit-row { display: flex; align-items: flex-start; gap: 8px; }
  .vedit textarea {
    flex: 1; min-width: 0; box-sizing: border-box; font-size: var(--fs-xl); line-height: 1.7; color: var(--text);
    font-family: inherit; padding: 10px 12px; border: 1px solid var(--border-strong); border-radius: 8px;
    resize: none; overflow-y: hidden;
  }
  /* Neutral, not accent: the blue box read as a validation state. The focus
     ring is replaced rather than simply removed -- a bare `outline: none`
     would leave keyboard users with no indication of where they are. */
  .vedit textarea:focus { outline: none; border-color: var(--text-3); }
  .vedit textarea:disabled { opacity: .6; }
  .edit-error { color: var(--danger); font-size: var(--fs-xs); margin: 6px 0 0; line-height: 1.4; }
  .edit-actions { display: flex; flex-direction: column; gap: 6px; flex-shrink: 0; }
  .icon-btn {
    width: 32px; height: 32px; padding: 0; font-size: var(--fs-xl); font-weight: 800; border-radius: 7px;
    border: none; cursor: pointer; display: flex; align-items: center; justify-content: center;
  }
  .icon-btn.save { background: var(--accent); color: white; }
  .icon-btn.cancel { background: var(--surface-2); color: var(--text-2); border: 1px solid var(--border-strong); }
  .icon-btn:disabled { opacity: .55; cursor: not-allowed; }
  .spin-sm { width: 12px; height: 12px; border-radius: 50%; border: 2px solid rgba(255,255,255,0.4); border-top-color: #fff; animation: spin-sm 0.8s linear infinite; }
  @keyframes spin-sm { to { transform: rotate(360deg); } }
</style>
