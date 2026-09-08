import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";

import QaFindingDetail from "../QaFindingDetail.svelte";
// @ts-expect-error Vite's test-only raw loader is not part of the app tsconfig.
import qaFindingDetailSource from "../QaFindingDetail.svelte?raw";
import {
  LONG_TAMIL,
  detail,
  grammaticallyRequiredAddition,
  quantityContradiction,
  resourceConflict,
  staleConfirmed,
} from "./fixtures";

describe("QaFindingDetail", () => {
  it("offers exactly the four reviewer conclusions", () => {
    render(QaFindingDetail, { props: { detail: detail() } });
    for (const label of [
      "Confirm translation issue",
      "Accept translation as correct",
      "False positive",
      "Needs discussion",
    ]) {
      expect(screen.getByRole("button", { name: label })).toBeInTheDocument();
    }
  });

  it("offers no way to change Scripture", () => {
    render(QaFindingDetail, { props: { detail: quantityContradiction() } });
    expect(screen.queryByRole("button", { name: /apply correction/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /fix|replace|edit verse/i })).toBeNull();
  });

  it("frames the finding as a possibility, not a verdict", () => {
    render(QaFindingDetail, { props: { detail: detail() } });
    expect(screen.getByRole("heading", { name: "Possible omission" })).toBeInTheDocument();
    expect(screen.getByText(/not a confirmed error/i)).toBeInTheDocument();
  });

  it("emits the chosen disposition with the reviewer's note", async () => {
    const { component } = render(QaFindingDetail, { props: { detail: detail() } });
    const decided = vi.fn();
    component.$on("decide", (event) => decided(event.detail));

    await fireEvent.input(screen.getByLabelText(/Note/i), {
      target: { value: "Tamil restructures the clause." },
    });
    await fireEvent.click(screen.getByRole("button", { name: "Accept translation as correct" }));

    expect(decided).toHaveBeenCalledWith({
      disposition: "ACCEPTABLE_TRANSLATION",
      note: "Tamil restructures the clause.",
      promote: false,
    });
  });

  it("only promotes when the reviewer both ticks promote and confirms an issue", async () => {
    const { component } = render(QaFindingDetail, {
      props: { detail: grammaticallyRequiredAddition() },
    });
    const decided = vi.fn();
    component.$on("decide", (event) => decided(event.detail));

    await fireEvent.click(screen.getByRole("checkbox"));
    await fireEvent.click(screen.getByRole("button", { name: "Accept translation as correct" }));
    expect(decided).toHaveBeenLastCalledWith(expect.objectContaining({ promote: false }));

    await fireEvent.click(screen.getByRole("button", { name: "Confirm translation issue" }));
    expect(decided).toHaveBeenLastCalledWith(expect.objectContaining({ promote: true }));
  });

  it("does not offer promotion for a finding that has nothing to promote", () => {
    render(QaFindingDetail, { props: { detail: quantityContradiction() } });
    expect(screen.queryByRole("checkbox")).toBeNull();
  });

  it("clears a typed note when a different finding is opened", async () => {
    const { component } = render(QaFindingDetail, { props: { detail: detail() } });
    const note = screen.getByLabelText(/Note/i) as HTMLTextAreaElement;
    await fireEvent.input(note, { target: { value: "about the first finding" } });
    expect(note.value).toBe("about the first finding");

    await component.$set({ detail: quantityContradiction() });
    expect((screen.getByLabelText(/Note/i) as HTMLTextAreaElement).value).toBe("");
  });

  it("keeps a note-only action separate from deciding", async () => {
    const { component } = render(QaFindingDetail, { props: { detail: detail() } });
    const noted = vi.fn();
    const decided = vi.fn();
    component.$on("note", (event) => noted(event.detail));
    component.$on("decide", () => decided());

    const button = screen.getByRole("button", { name: "Add note only" });
    expect(button).toBeDisabled();

    await fireEvent.input(screen.getByLabelText(/Note/i), { target: { value: "ask the team" } });
    await fireEvent.click(screen.getByRole("button", { name: "Add note only" }));

    expect(noted).toHaveBeenCalledWith({ note: "ask the team" });
    expect(decided).not.toHaveBeenCalled();
  });

  it("shows a stale finding's preserved decision without treating it as current", () => {
    render(QaFindingDetail, { props: { detail: staleConfirmed() } });
    expect(screen.getByText("Confirmed translation issue")).toBeInTheDocument();
    expect(screen.getByText("Stale")).toBeInTheDocument();
    expect(screen.getByText(/This finding was produced against an earlier revision/i))
      .toHaveTextContent(/must be re-evaluated|earlier revision/i);
  });

  it("navigates to the next and previous finding", async () => {
    const { component } = render(QaFindingDetail, { props: { detail: detail() } });
    const next = vi.fn();
    const previous = vi.fn();
    component.$on("next", next);
    component.$on("previous", previous);

    await fireEvent.click(screen.getByRole("button", { name: /Next finding/i }));
    await fireEvent.click(screen.getByRole("button", { name: /Previous finding/i }));
    expect(next).toHaveBeenCalledOnce();
    expect(previous).toHaveBeenCalledOnce();
  });

  it("disables the decision buttons while a write is in flight", () => {
    render(QaFindingDetail, { props: { detail: detail(), busy: true } });
    expect(screen.getByRole("button", { name: "Confirm translation issue" })).toBeDisabled();
  });

  it("prompts for a selection when nothing is open", () => {
    render(QaFindingDetail, { props: { detail: null } });
    expect(screen.getByText(/Select a possible issue/i)).toBeInTheDocument();
  });

  it("surfaces a load error instead of rendering an empty pane", () => {
    render(QaFindingDetail, { props: { detail: null, error: "engine unavailable" } });
    expect(screen.getByRole("alert")).toHaveTextContent("engine unavailable");
  });

  it.each([
    [1920, 760],
    [1366, 768],
    [1366, 500],
    [1550, 350],
    [820, 768],
  ])("keeps evidence, decision, and correction in one normal-flow scroller at %ix%i", (width, height) => {
    Object.defineProperty(window, "innerWidth", { configurable: true, value: width });
    Object.defineProperty(window, "innerHeight", { configurable: true, value: height });
    const evidence = quantityContradiction();
    const resources = resourceConflict();
    const history = staleConfirmed();
    const longDetail = {
      ...evidence,
      source: evidence.source.map((source) => ({ ...source, rawSurface: LONG_TAMIL.repeat(8) })),
      resources: resources.resources.map((resource) => ({
        ...resource,
        content: `${String(resource.content)} ${LONG_TAMIL}`.repeat(12),
      })),
      resourceConflictEvidence: resources.resourceConflictEvidence,
      history: history.history,
    };
    const { container } = render(QaFindingDetail, { props: { detail: longDetail } });

    const scroller = container.querySelector<HTMLElement>("[data-qa-detail-scroll]")!;
    const evidenceFlow = container.querySelector<HTMLElement>("[data-qa-evidence]")!;
    const decision = container.querySelector<HTMLElement>("[data-qa-decision]")!;
    const correction = container.querySelector<HTMLElement>("[data-qa-correction]")!;
    expect(scroller).toBeInTheDocument();
    expect(evidenceFlow.compareDocumentPosition(decision) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(decision.compareDocumentPosition(correction) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

    for (const heading of [
      "Source", "Location Stage 6B", "Meaning Stage 7", "Coverage and support Stage 8",
      "Resources", "What this means", "History", "Your decision",
    ]) {
      expect(screen.getByRole("heading", { name: heading })).toBeInTheDocument();
    }
    expect(screen.getByText(LONG_TAMIL.repeat(8))).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Confirm translation issue" })).toBeInTheDocument();
    expect(correction).toBeInTheDocument();
  });

  it("keeps the complete decision form non-sticky with one vertical scroll owner", () => {
    const detailCss = qaFindingDetailSource.match(/\.detail\s*{([^}]*)}/)?.[1] ?? "";
    const decisionCss = qaFindingDetailSource.match(/\.actions\s*{([^}]*)}/)?.[1] ?? "";
    expect(detailCss).toMatch(/overflow-y:\s*auto/);
    expect(detailCss).toMatch(/overflow-x:\s*hidden/);
    expect(decisionCss).toMatch(/position:\s*static/);
    expect(decisionCss).not.toMatch(/position:\s*(sticky|fixed)/);
  });

  it("keeps keyboard focus moving through normal-flow decision actions", async () => {
    const user = userEvent.setup();
    render(QaFindingDetail, { props: { detail: detail() } });
    const first = screen.getByRole("button", { name: "Confirm translation issue" });
    first.focus();
    expect(first).toHaveFocus();
    await user.tab();
    expect(screen.getByRole("button", { name: "Accept translation as correct" })).toHaveFocus();
  });
});
