import { describe, expect, it, vi } from "vitest";
import { get } from "svelte/store";
import { createPointerDrag } from "../../alignmentDrag";
import {
  alignedTargetsFor, bottomIdsAfterDrop, gapCounts, groupForSource, groupForTarget, unalignedTargets,
  unmatchedSources,
} from "../../alignmentGroups";
import type { AlignmentToken } from "../../types/finding";

function pointer(x: number, y: number, button = 0): PointerEvent {
  return { clientX: x, clientY: y, button } as unknown as PointerEvent;
}

/** A stand-in for document.elementFromPoint: jsdom always returns null there. */
function element(attrs: Record<string, string>): Element {
  const el = document.createElement("div");
  for (const [name, value] of Object.entries(attrs)) el.setAttribute(name, value);
  return el;
}

describe("createPointerDrag", () => {
  it("does not deliver a drop for a pointerdown/up without movement (the click handles pick-up)", () => {
    const onDrop = vi.fn();
    const drag = createPointerDrag({ onDrop, hitTest: () => null });
    drag.start(pointer(10, 10), "T001");
    drag.move(pointer(12, 11)); // under the 6px threshold
    drag.up();
    expect(onDrop).not.toHaveBeenCalled();
    expect(drag.consumeSuppressedClick("T001")).toBe(false);
    expect(get(drag.state).tokenId).toBeNull();
  });

  it("ignores non-primary buttons", () => {
    const drag = createPointerDrag({ onDrop: vi.fn(), hitTest: () => null });
    drag.start(pointer(0, 0, 2), "T001");
    expect(get(drag.state).tokenId).toBeNull();
  });

  it("crosses the threshold once, shows a ghost, and reports the column under the pointer", () => {
    const onDragStart = vi.fn();
    const onDrop = vi.fn();
    const drag = createPointerDrag({
      onDragStart, onDrop,
      hitTest: (x) => (x > 100 ? element({ "data-drop-column": "3|H002" }) : null),
    });
    drag.start(pointer(0, 0), "T001");
    drag.move(pointer(20, 0));
    drag.move(pointer(140, 0));
    expect(onDragStart).toHaveBeenCalledTimes(1);
    const state = get(drag.state);
    expect(state).toMatchObject({ tokenId: "T001", moved: true, ghost: { x: 140, y: 0 }, overColumn: "3|H002", overBank: null });
    drag.up();
    expect(onDrop).toHaveBeenCalledWith({ tokenId: "T001", column: "3|H002", bank: null });
    // The state is idle before the drop handler runs, and the trailing click is swallowed once.
    expect(get(drag.state)).toMatchObject({ tokenId: null, moved: false, overColumn: null, overBank: null });
    expect(drag.consumeSuppressedClick("T001")).toBe(true);
    expect(drag.consumeSuppressedClick("T001")).toBe(false);
  });

  it("finds the drop target through closest(): the pointer may be over a child of the marked element", () => {
    const bank = element({ "data-drop-bank": "true" });
    const child = document.createElement("span");
    bank.appendChild(child);
    const onDrop = vi.fn();
    const drag = createPointerDrag({ onDrop, hitTest: () => child });
    drag.start(pointer(0, 0), "T002");
    drag.move(pointer(50, 50));
    expect(get(drag.state).overBank).toBe("true");
    drag.up();
    expect(onDrop).toHaveBeenCalledWith({ tokenId: "T002", column: null, bank: "true" });
  });

  it("reports a drop over nothing with both targets null", () => {
    const onDrop = vi.fn();
    const drag = createPointerDrag({ onDrop, hitTest: () => null });
    drag.start(pointer(0, 0), "T003");
    drag.move(pointer(50, 50));
    drag.up();
    expect(onDrop).toHaveBeenCalledWith({ tokenId: "T003", column: null, bank: null });
  });

  it("attach() wires window pointermove/pointerup and detaches cleanly", () => {
    const listeners = new Map<string, EventListener>();
    const target = {
      addEventListener: vi.fn((type: string, fn: EventListener) => listeners.set(type, fn)),
      removeEventListener: vi.fn((type: string) => listeners.delete(type)),
    } as unknown as Window;
    const onDrop = vi.fn();
    const drag = createPointerDrag({ onDrop, hitTest: () => element({ "data-drop-column": "H001" }) });
    const detach = drag.attach(target);
    drag.start(pointer(0, 0), "T001");
    listeners.get("pointermove")!(pointer(30, 30) as unknown as Event);
    listeners.get("pointerup")!(new Event("pointerup"));
    expect(onDrop).toHaveBeenCalledWith({ tokenId: "T001", column: "H001", bank: null });
    detach();
    expect(listeners.size).toBe(0);
  });
});

function token(id: string, word = id): AlignmentToken {
  return { id, word, occurrence: 1, occurrences: 1 };
}

const context = {
  topTokens: [token("H001"), token("H002"), token("H003")],
  bottomTokens: [token("T001"), token("T002"), token("T003"), token("T004")],
  groups: [
    { id: "G001", topIds: ["H001"], bottomIds: ["T001", "T002"] },
    { id: "G002", topIds: ["H002"], bottomIds: [] }, // tC keeps an empty group for an unaligned source
  ],
};

describe("alignmentGroups", () => {
  it("resolves groups for targets and sources", () => {
    expect(groupForTarget(context, "T002")?.id).toBe("G001");
    expect(groupForTarget(context, "T003")).toBeUndefined();
    expect(groupForSource(context, "H002")?.id).toBe("G002");
    expect(groupForSource(context, "H003")).toBeUndefined();
    expect(alignedTargetsFor(context, "H001").map((t) => t.id)).toEqual(["T001", "T002"]);
    expect(alignedTargetsFor(context, "H003")).toEqual([]);
  });

  it("counts gaps the way the engine does: empty-group sources are unmatched too", () => {
    expect(unalignedTargets(context).map((t) => t.id)).toEqual(["T003", "T004"]);
    expect(unmatchedSources(context).map((t) => t.id)).toEqual(["H002", "H003"]);
    expect(gapCounts(context)).toEqual({ sourceUnmatched: 2, targetUnmatched: 2 });
  });

  it("nets cross-verse links out of the gaps (#117) without touching what is draggable", () => {
    const linked = { ...context, crossVerseAccountedIds: ["T003"], crossVerseRealizedIds: ["H003"] };
    expect(unalignedTargets(linked).map((t) => t.id)).toEqual(["T003", "T004"]);
    expect(gapCounts(linked)).toEqual({ sourceUnmatched: 1, targetUnmatched: 1 });
  });

  it("resends the destination column's existing words on a drop, and refuses a no-op drop", () => {
    expect(bottomIdsAfterDrop(context, "H001", "T003")).toEqual(["T001", "T002", "T003"]);
    expect(bottomIdsAfterDrop(context, "H003", "T003")).toEqual(["T003"]);
    expect(bottomIdsAfterDrop(context, "H001", "T002")).toBeNull();
  });
});
