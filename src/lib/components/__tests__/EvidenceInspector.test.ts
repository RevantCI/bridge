import { describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/svelte";

import EvidenceInspector from "../EvidenceInspector.svelte";
import {
  LONG_TAMIL,
  ambiguousLocation,
  detail,
  grammaticallyRequiredAddition,
  quantityContradiction,
  resourceConflict,
  searchIncomplete,
  staleConfirmed,
} from "./fixtures";

describe("EvidenceInspector", () => {
  it("presents evidence in named layers rather than one explanation", () => {
    render(EvidenceInspector, { props: { detail: detail() } });
    // Exact names: "Resources" also contains "source", and the stage suffix
    // means "Location" appears as "Location Stage 6B".
    for (const heading of [/^Source$/, /^Location/, /^Meaning/, /^Coverage and support/, /^Resources$/, /^History$/]) {
      expect(screen.getByRole("heading", { name: heading })).toBeInTheDocument();
    }
  });

  it("keeps location and meaning as separate verdicts", () => {
    render(EvidenceInspector, { props: { detail: quantityContradiction() } });
    const location = screen.getByRole("heading", { name: /^Location/ }).closest("section");
    const meaning = screen.getByRole("heading", { name: /^Meaning/ }).closest("section");
    expect(within(location as HTMLElement).getByText("Located")).toBeInTheDocument();
    // "Contradicted" is both the overall status and one dimension row, so
    // assert on the count rather than a single match.
    expect(within(meaning as HTMLElement).getAllByText("Contradicted").length).toBeGreaterThan(0);
    // The strong location must not be reported inside the meaning verdict.
    expect(within(meaning as HTMLElement).queryByText("Located")).toBeNull();
  });

  it("shows each meaning dimension separately instead of one score", () => {
    render(EvidenceInspector, { props: { detail: quantityContradiction() } });
    const row = screen.getByRole("rowheader", { name: "QUANTITY" }).closest("tr");
    expect(within(row as HTMLElement).getByText("Contradicted")).toBeInTheDocument();
    expect(within(row as HTMLElement).queryByText("Preserved")).toBeNull();
    const preserved = screen.getByRole("rowheader", { name: "LEXICAL_CONTENT" }).closest("tr");
    expect(within(preserved as HTMLElement).getByText("Preserved")).toBeInTheDocument();
  });

  it("does not present cross-verse realization as a fault", () => {
    render(EvidenceInspector, { props: { detail: quantityContradiction() } });
    expect(screen.getByText("Realized in another verse")).toBeInTheDocument();
    expect(
      screen.getByText(/normal features of\s+translation, not problems in themselves/i),
    ).toBeInTheDocument();
  });

  it("lists every retained alternative candidate", () => {
    render(EvidenceInspector, { props: { detail: ambiguousLocation() } });
    expect(screen.getByText("Ambiguous")).toBeInTheDocument();
    expect(screen.getByText("நாள்")).toBeInTheDocument();
    expect(screen.getByText("நாளில்")).toBeInTheDocument();
    expect(screen.queryByText(/retained no competing candidate/i)).toBeNull();
  });

  it("distinguishes an incomplete search from a genuine absence", () => {
    render(EvidenceInspector, { props: { detail: searchIncomplete() } });
    expect(screen.getByText("Search incomplete")).toBeInTheDocument();
    expect(screen.getByText(/absence here proves nothing/i)).toBeInTheDocument();
  });

  it("explains why a grammatically required addition is not a fault", () => {
    render(EvidenceInspector, { props: { detail: grammaticallyRequiredAddition() } });
    expect(screen.getByText("Required by target grammar")).toBeInTheDocument();
    expect(screen.getByText(/has no separate source counterpart and needs none/i)).toBeInTheDocument();
  });

  it("shows resource disagreement rather than a single reconciled summary", () => {
    render(EvidenceInspector, { props: { detail: resourceConflict() } });
    expect(screen.getByText(/should be rendered as a blessing/i)).toBeInTheDocument();
    expect(screen.getByText(/treats this term as a greeting/i)).toBeInTheDocument();
    expect(screen.getByText("Conflicting")).toBeInTheDocument();
  });

  it("never hides stale, and says what stale means", () => {
    render(EvidenceInspector, { props: { detail: staleConfirmed() } });
    const notice = screen.getByRole("status");
    expect(notice).toHaveTextContent(/earlier revision/i);
    expect(notice).toHaveTextContent(/re-evaluated against the current text/i);
  });

  it("preserves a human decision in history even when the finding is stale", () => {
    render(EvidenceInspector, { props: { detail: staleConfirmed() } });
    expect(screen.getByText("Confirmed with the translation team.")).toBeInTheDocument();
    expect(screen.getByText(/UNRESOLVED → CONFIRMED_TRANSLATION_ERROR/)).toBeInTheDocument();
  });

  it("names a mapping problem and a translation problem differently", () => {
    const { unmount } = render(EvidenceInspector, { props: { detail: quantityContradiction() } });
    expect(screen.getByText(/found the right place/i)).toBeInTheDocument();
    unmount();

    render(EvidenceInspector, { props: { detail: ambiguousLocation() } });
    expect(screen.getByText(/Mapping is uncertain/i)).toBeInTheDocument();
  });

  it("keeps advanced source internals behind progressive disclosure", async () => {
    const { component } = render(EvidenceInspector, { props: { detail: detail() } });
    expect(screen.queryByText("Audit eligibility")).toBeNull();
    const toggle = screen.getByRole("button", { name: /advanced source detail/i });
    toggle.click();
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(screen.getByText("Audit eligibility")).toBeInTheDocument();
    component.$destroy();
  });

  it("renders long Tamil target text without truncating it", () => {
    render(EvidenceInspector, {
      props: {
        detail: detail({
          source: [{
            id: "source-unit-long",
            rawSurface: LONG_TAMIL,
            displayedReferences: ["PHP 1:3-5"],
            kind: "CLAUSE",
            semanticObligation: "REQUIRED",
          }],
        }),
      },
    });
    expect(screen.getByText(LONG_TAMIL)).toBeInTheDocument();
  });
});
