import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";

import FindingContextMenu from "../FindingContextMenu.svelte";

const actions = [
  { id: "apply", label: "Apply proposed fix", disabled: true },
  { id: "accept", label: "Accept finding", separatorBefore: true },
  { id: "defer", label: "Needs discussion" },
];

describe("FindingContextMenu", () => {
  it("keeps unavailable fixes visible but disabled", () => {
    render(FindingContextMenu, { props: { x: 20, y: 30, actions } });
    expect(screen.getByRole("menuitem", { name: "Apply proposed fix" })).toBeDisabled();
  });

  it("dispatches actions and closes with Escape", async () => {
    const { component } = render(FindingContextMenu, { props: { x: 20, y: 30, actions } });
    const action = vi.fn();
    const close = vi.fn();
    component.$on("action", (event) => action(event.detail.id));
    component.$on("close", close);

    await fireEvent.click(screen.getByRole("menuitem", { name: "Accept finding" }));
    expect(action).toHaveBeenCalledWith("accept");
    await fireEvent.keyDown(screen.getByRole("menu"), { key: "Escape" });
    expect(close).toHaveBeenCalledTimes(1);
  });

  it("dismisses on an outside pointer and clamps to the viewport", async () => {
    const { component } = render(FindingContextMenu, {
      props: { x: 99999, y: 99999, actions },
    });
    const close = vi.fn();
    component.$on("close", close);
    const menu = screen.getByRole("menu");
    await waitFor(() => expect(parseFloat(menu.style.left)).toBeLessThan(window.innerWidth));
    await fireEvent.pointerDown(document.body);
    expect(close).toHaveBeenCalledTimes(1);
  });
});
