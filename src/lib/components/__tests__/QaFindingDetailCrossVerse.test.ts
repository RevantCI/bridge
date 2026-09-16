import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/svelte";

import QaFindingDetail from "../QaFindingDetail.svelte";
import { detail } from "./fixtures";

// #118: possible omissions and additions get a direct route to the
// Cross-verse alignment page on the finding's own references.
describe("QaFindingDetail cross-verse entry point", () => {
  it("offers Cross-verse alignment for a possible omission and emits the references", async () => {
    const base = detail();
    const fixture = {
      ...base,
      finding: { ...base.finding, kind: "POSSIBLE_OMISSION", displayedReferences: ["PHP 1:3", "PHP 1:6"] },
    };
    const { component } = render(QaFindingDetail, { props: { detail: fixture } });
    const opened = vi.fn();
    component.$on("crossVerse", (event) => opened(event.detail));
    await fireEvent.click(screen.getByRole("button", { name: /Cross-verse alignment/ }));
    expect(opened).toHaveBeenCalledWith({ references: ["PHP 1:3", "PHP 1:6"] });
  });

  it("offers it for a possible addition too", () => {
    const base = detail();
    render(QaFindingDetail, { props: { detail: { ...base, finding: { ...base.finding, kind: "POSSIBLE_ADDITION" } } } });
    expect(screen.getByRole("button", { name: /Cross-verse alignment/ })).toBeInTheDocument();
  });

  it("does not offer it for other finding kinds", () => {
    const base = detail();
    render(QaFindingDetail, { props: { detail: { ...base, finding: { ...base.finding, kind: "QUANTITY_PROBLEM" } } } });
    expect(screen.queryByRole("button", { name: /Cross-verse alignment/ })).toBeNull();
  });

  it("still offers exactly the four reviewer conclusions beside it", () => {
    render(QaFindingDetail, { props: { detail: detail() } });
    expect(screen.getAllByRole("button", { name: /^(Confirm translation issue|Accept translation as correct|False positive|Needs discussion)$/ })).toHaveLength(4);
  });
});
