// Pointer-based (not native HTML5) drag-and-drop for alignment tokens, shared
// by AlignmentModal.svelte (one verse) and CrossVerseAlignmentModal.svelte
// (a verse range, #116).
//
// Why pointer events: Tauri's window-level dragDropEnabled -- real,
// load-bearing for the "drop a file to import" feature in ImportScreen.svelte
// and App.svelte -- intercepts the browser's native drag events before the
// page ever sees them, so draggable/dragstart/dragover/drop are silently inert
// inside this webview. Pointer events are not part of that native drag
// protocol, so a from-scratch pointer-tracked drag with a floating ghost
// works instead.
//
// The module owns the state machine only. Markup marks drop targets with two
// data attributes whose *values* are opaque to this file: `data-drop-column`
// (AlignmentModal: the source token id; the cross-verse page: "verse|topId")
// and `data-drop-bank` (AlignmentModal: "true"; the cross-verse page: the
// verse). A drop reports whichever value was under the pointer.
import { writable, type Readable } from "svelte/store";

export interface DragState {
  /** Token whose pointerdown started the track; null when idle. */
  tokenId: string | null;
  /** True once the pointer has travelled past the threshold -- a real drag,
   *  not a click. Only then is a ghost shown and a drop delivered. */
  moved: boolean;
  ghost: { x: number; y: number };
  /** `data-drop-column` value under the pointer, or null. */
  overColumn: string | null;
  /** `data-drop-bank` value under the pointer, or null. */
  overBank: string | null;
}

export interface DropTarget {
  tokenId: string;
  column: string | null;
  bank: string | null;
}

export interface PointerDragOptions {
  /** Pixels of travel before a pointerdown counts as a drag. Default 6. */
  threshold?: number;
  columnAttr?: string;
  bankAttr?: string;
  /** Element under a viewport point. Defaults to document.elementFromPoint;
   *  injectable because jsdom always returns null there. */
  hitTest?: (x: number, y: number) => Element | null;
  /** Fired once when the threshold is crossed (the modal clears its
   *  click-to-pick-up selection here: a real drag supersedes it). */
  onDragStart?: (tokenId: string) => void;
  /** Fired on pointerup after a real drag, with whatever target was under
   *  the pointer. Both `column` and `bank` null means "dropped nowhere". */
  onDrop: (target: DropTarget) => void;
}

export interface PointerDrag {
  state: Readable<DragState>;
  /** pointerdown on a draggable token. Ignores non-primary buttons. */
  start(event: PointerEvent, tokenId: string): void;
  move(event: PointerEvent): void;
  up(): void;
  /** Register window-level pointermove/pointerup listeners; returns the
   *  detach function for onMount's teardown. */
  attach(target: Pick<Window, "addEventListener" | "removeEventListener">): () => void;
  /** After a real drag the browser still fires `click` on the token that was
   *  dragged. The token's click handler asks this once; it answers true for
   *  exactly that token, exactly once, so the click is swallowed instead of
   *  toggling pick-up mode. */
  consumeSuppressedClick(tokenId: string): boolean;
}

const IDLE: DragState = { tokenId: null, moved: false, ghost: { x: 0, y: 0 }, overColumn: null, overBank: null };

function dataValue(el: Element | null | undefined, attr: string): string | null {
  const host = el?.closest?.(`[${attr}]`);
  return host ? host.getAttribute(attr) : null;
}

export function createPointerDrag(options: PointerDragOptions): PointerDrag {
  const threshold = options.threshold ?? 6;
  const columnAttr = options.columnAttr ?? "data-drop-column";
  const bankAttr = options.bankAttr ?? "data-drop-bank";
  const hitTest = options.hitTest ?? ((x: number, y: number) => document.elementFromPoint(x, y));

  const state = writable<DragState>({ ...IDLE });
  let current: DragState = { ...IDLE };
  let origin: { x: number; y: number } | null = null;
  let suppressClickId: string | null = null;

  function set(next: DragState) {
    current = next;
    state.set(next);
  }

  function start(event: PointerEvent, tokenId: string) {
    if (event.button !== 0) return;
    origin = { x: event.clientX, y: event.clientY };
    set({ ...IDLE, tokenId });
  }

  function move(event: PointerEvent) {
    if (!current.tokenId || !origin) return;
    let moved = current.moved;
    if (!moved && Math.hypot(event.clientX - origin.x, event.clientY - origin.y) > threshold) {
      moved = true;
      options.onDragStart?.(current.tokenId);
    }
    if (!moved) return;
    const el = hitTest(event.clientX, event.clientY);
    set({
      tokenId: current.tokenId,
      moved: true,
      ghost: { x: event.clientX, y: event.clientY },
      overColumn: dataValue(el, columnAttr),
      overBank: dataValue(el, bankAttr),
    });
  }

  function up() {
    if (!current.tokenId) return;
    // Snapshot, then reset, then deliver: the drop handler may start an
    // async mutation and re-render, and must see an idle drag state.
    const { tokenId, moved, overColumn, overBank } = current;
    origin = null;
    set({ ...IDLE });
    if (!moved) return; // the browser's own click event fires next and handles pick-up
    suppressClickId = tokenId;
    options.onDrop({ tokenId, column: overColumn, bank: overBank });
  }

  function attach(target: Pick<Window, "addEventListener" | "removeEventListener">) {
    const onMove = (event: Event) => move(event as PointerEvent);
    const onUp = () => up();
    target.addEventListener("pointermove", onMove);
    target.addEventListener("pointerup", onUp);
    return () => {
      target.removeEventListener("pointermove", onMove);
      target.removeEventListener("pointerup", onUp);
    };
  }

  function consumeSuppressedClick(tokenId: string): boolean {
    if (suppressClickId !== tokenId) return false;
    suppressClickId = null;
    return true;
  }

  return { state, start, move, up, attach, consumeSuppressedClick };
}
