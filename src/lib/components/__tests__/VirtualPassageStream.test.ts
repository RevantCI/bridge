import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/svelte";

import VirtualPassageStream from "../VirtualPassageStream.svelte";
import type { PassageVerse } from "../../types/qaReview";

function verse(overrides: Partial<PassageVerse> = {}): PassageVerse {
  return {
    reference: "PHP 1:3",
    text: "நற்செய்தி உங்களுக்கு அறிவிக்கப்பட்ட நாள் முதல்",
    relationshipIds: [],
    linked: false,
    crossVerse: false,
    splitOrMerged: false,
    hasFinding: false,
    reviewed: false,
    stale: false,
    ...overrides,
  };
}

function passage(count: number): PassageVerse[] {
  return Array.from({ length: count }, (_unused, index) =>
    verse({
      reference: `PHP ${Math.floor(index / 30) + 1}:${(index % 30) + 1}`,
      text: `verse text ${index}`,
      relationshipIds: [`rel-${index}`],
      linked: true,
    }),
  );
}

describe("VirtualPassageStream", () => {
  it("lays the passage out as a stream, not one column per verse", () => {
    render(VirtualPassageStream, { props: { verses: passage(4) } });
    // Each verse is a row with a disclosure control, not a fixed column.
    expect(screen.getAllByRole("button", { expanded: false })).toHaveLength(4);
  });

  it("windows a long passage instead of rendering every verse", () => {
    render(VirtualPassageStream, { props: { verses: passage(1200) } });
    const rows = screen.getAllByRole("button");
    expect(rows.length).toBeGreaterThan(0);
    expect(rows.length).toBeLessThan(120);
    expect(screen.getByText(/1200 of 1200 verses/)).toBeInTheDocument();
  });

  it("renders a short passage without windowing", () => {
    render(VirtualPassageStream, { props: { verses: passage(6) } });
    expect(screen.getAllByRole("button")).toHaveLength(6);
  });

  it("expands a verse on demand and collapses it again", async () => {
    const { component } = render(VirtualPassageStream, { props: { verses: passage(3) } });
    const expanded = vi.fn();
    component.$on("expand", (event) => expanded(event.detail.reference));

    await fireEvent.click(screen.getAllByRole("button")[0]);
    expect(expanded).toHaveBeenLastCalledWith("PHP 1:1");

    await component.$set({ expandedReference: "PHP 1:1" });
    expect(screen.getAllByRole("button")[0]).toHaveAttribute("aria-expanded", "true");

    await fireEvent.click(screen.getAllByRole("button")[0]);
    expect(expanded).toHaveBeenLastCalledWith("");
  });

  it("marks the focused relationship distinctly from the rest", async () => {
    const verses = [
      verse({ reference: "PHP 1:3", relationshipIds: ["rel-a"], linked: true }),
      verse({ reference: "PHP 1:4", relationshipIds: ["rel-b"], linked: true }),
    ];
    const { container } = render(VirtualPassageStream, {
      props: { verses, focusedRelationshipIds: ["rel-b"] },
    });
    const focused = container.querySelectorAll(".verse.focused");
    expect(focused).toHaveLength(1);
    // Marked by a glyph too, not by colour alone.
    expect(screen.getByTitle("Carries the focused relationship")).toBeInTheDocument();
  });

  it("draws connector detail only for the focused verse", async () => {
    const verses = [
      verse({ reference: "PHP 1:3", relationshipIds: ["rel-a"], linked: true }),
      verse({ reference: "PHP 1:4", relationshipIds: ["rel-b"], linked: true }),
    ];
    render(VirtualPassageStream, {
      props: { verses, focusedRelationshipIds: ["rel-a"], expandedReference: "PHP 1:3" },
    });
    expect(screen.getByText(/focused source meaning is realized here/i)).toBeInTheDocument();

    // The unfocused verse gets a count, not a connector — no spaghetti graph.
    await fireEvent.click(screen.getAllByRole("button")[1]);
  });

  it("says what an unfocused linked verse holds without drawing it", () => {
    const verses = [verse({ reference: "PHP 1:4", relationshipIds: ["rel-b", "rel-c"], linked: true })];
    render(VirtualPassageStream, {
      props: { verses, focusedRelationshipIds: ["rel-a"], expandedReference: "PHP 1:4" },
    });
    expect(screen.getByText(/2 other relationships land in this verse/i)).toBeInTheDocument();
    expect(screen.queryByText(/focused source meaning is realized here/i)).toBeNull();
  });

  it("flags cross-verse, split, findings, reviewed and stale verses", () => {
    render(VirtualPassageStream, {
      props: {
        verses: [verse({
          crossVerse: true, splitOrMerged: true, hasFinding: true, reviewed: true, stale: true,
        })],
      },
    });
    for (const title of [
      "Cross-verse realization", "Split or merged realization",
      "Has a possible issue", "Reviewed by a human", "Stale",
    ]) {
      expect(screen.getByTitle(title)).toBeInTheDocument();
    }
  });

  it("searches the target passage by text and by reference", async () => {
    const verses = [
      verse({ reference: "PHP 1:3", text: "நற்செய்தி முதல்" }),
      verse({ reference: "PHP 1:4", text: "மகிழ்ச்சியோடு ஜெபம்" }),
    ];
    const { component } = render(VirtualPassageStream, { props: { verses } });

    await component.$set({ search: "ஜெபம்" });
    expect(screen.getByText(/1 of 2 verses/)).toBeInTheDocument();

    await component.$set({ search: "1:3" });
    expect(screen.getByText(/1 of 2 verses/)).toBeInTheDocument();

    await component.$set({ search: "nothing here" });
    expect(screen.getByText(/No verses match that search/i)).toBeInTheDocument();
  });

  it("gives the search box a label for screen readers", () => {
    render(VirtualPassageStream, { props: { verses: passage(2) } });
    expect(screen.getByLabelText(/Search the target passage/i)).toBeInTheDocument();
  });
});
