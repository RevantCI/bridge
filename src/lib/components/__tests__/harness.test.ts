import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/svelte";

import ReviewStatusBadge from "../ReviewStatusBadge.svelte";

/**
 * Guards the test harness itself: if Svelte component rendering or
 * jest-dom matchers stop working, every other component test fails in a
 * confusing way rather than pointing here.
 */
describe("test harness", () => {
  it("renders a Svelte component into jsdom", () => {
    render(ReviewStatusBadge, { props: { label: "Possible omission", tone: "possible" } });
    expect(screen.getByText("Possible omission")).toBeInTheDocument();
  });
});
