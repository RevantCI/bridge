import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/svelte";

import QaFindingList from "../QaFindingList.svelte";
import { manyFindings, summary } from "./fixtures";

describe("QaFindingList", () => {
  it("uses the reviewer-facing wording, not raw enum names", () => {
    render(QaFindingList, { props: { findings: [summary()], total: 1 } });
    expect(screen.getByText("Possible omission")).toBeInTheDocument();
    expect(screen.queryByText("POSSIBLE_OMISSION")).toBeNull();
  });

  it("never labels a machine finding as an error", () => {
    render(QaFindingList, { props: { findings: [summary({ severity: "CRITICAL" })], total: 1 } });
    expect(screen.queryByText(/^Error$/i)).toBeNull();
    expect(screen.queryByText(/wrong translation/i)).toBeNull();
    expect(screen.getByText("Not yet reviewed")).toBeInTheDocument();
  });

  it("presents severity as review priority rather than truth", () => {
    render(QaFindingList, { props: { findings: [summary({ severity: "CRITICAL" })], total: 1 } });
    const severity = screen.getByText(/Critical priority/);
    expect(severity).toHaveAttribute("title", expect.stringContaining("does not mean the issue is confirmed"));
  });

  it("marks a stale finding with text, not colour alone", () => {
    render(QaFindingList, {
      props: { findings: [summary({ lifecycleStatus: "STALE" })], total: 1 },
    });
    expect(screen.getByText("Stale")).toBeInTheDocument();
  });

  it("renders only a window of a large queue", () => {
    render(QaFindingList, { props: { findings: manyFindings(1000), total: 1000 } });
    const rows = screen.getAllByRole("option");
    // Windowed: a fraction of 1000 rows in the DOM, not all of them.
    expect(rows.length).toBeGreaterThan(0);
    expect(rows.length).toBeLessThan(100);
    expect(screen.getByText(/Showing 1000 of 1000/)).toBeInTheDocument();
  });

  it("renders every row when the queue is small enough not to need windowing", () => {
    render(QaFindingList, { props: { findings: manyFindings(12), total: 12 } });
    expect(screen.getAllByRole("option")).toHaveLength(12);
  });

  it("moves the selection with arrow keys from a single tab stop", async () => {
    const findings = manyFindings(5);
    const { component } = render(QaFindingList, {
      props: { findings, selectedId: findings[0].id, total: 5 },
    });
    const selected = vi.fn();
    component.$on("select", (event) => selected(event.detail.id));

    const listbox = screen.getByRole("listbox");
    expect(listbox).toHaveAttribute("tabindex", "0");

    await fireEvent.keyDown(listbox, { key: "ArrowDown" });
    expect(selected).toHaveBeenLastCalledWith(findings[1].id);

    await fireEvent.keyDown(listbox, { key: "End" });
    expect(selected).toHaveBeenLastCalledWith(findings[4].id);

    await fireEvent.keyDown(listbox, { key: "Home" });
    expect(selected).toHaveBeenLastCalledWith(findings[0].id);
  });

  it("does not move above the first row", async () => {
    const findings = manyFindings(3);
    const { component } = render(QaFindingList, {
      props: { findings, selectedId: findings[0].id, total: 3 },
    });
    const selected = vi.fn();
    component.$on("select", (event) => selected(event.detail.id));
    await fireEvent.keyDown(screen.getByRole("listbox"), { key: "ArrowUp" });
    expect(selected).toHaveBeenLastCalledWith(findings[0].id);
  });

  it("exposes the active row to assistive technology", () => {
    const findings = manyFindings(3);
    render(QaFindingList, { props: { findings, selectedId: findings[1].id, total: 3 } });
    expect(screen.getByRole("listbox")).toHaveAttribute(
      "aria-activedescendant", `finding-${findings[1].id}`,
    );
    const rows = screen.getAllByRole("option");
    expect(rows[1]).toHaveAttribute("aria-selected", "true");
    expect(rows[0]).toHaveAttribute("aria-selected", "false");
  });

  it("reports an empty result rather than looking broken", () => {
    render(QaFindingList, { props: { findings: [], total: 0, loading: false } });
    expect(screen.getByText(/No findings match these filters/i)).toBeInTheDocument();
  });

  it("distinguishes the loaded page from the filtered total", () => {
    render(QaFindingList, { props: { findings: manyFindings(50), total: 812 } });
    expect(screen.getByText(/Showing 50 of 812 possible issues/)).toBeInTheDocument();
  });
});
