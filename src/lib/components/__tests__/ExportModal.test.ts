import { describe, expect, it, beforeEach, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/svelte";

const { pickSavePath, exportAligned, exportNonAligned } = vi.hoisted(() => ({
  pickSavePath: vi.fn(), exportAligned: vi.fn(), exportNonAligned: vi.fn(),
}));

vi.mock("../../api/bridgeClient", () => ({ bridge: { pickSavePath, exportAligned, exportNonAligned } }));

import ExportModal from "../ExportModal.svelte";

describe("ExportModal publication gate (layered-rules 4.5)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    pickSavePath.mockResolvedValue("/out/rut.usfm");
    exportNonAligned
      .mockResolvedValueOnce({ written: false, blocked: true, path: "/out/rut.usfm", gate: {
        blocking: true, counts: { languageQa: 1 },
        items: [{ source: "languageQa", reference: "1:1", summary: "project/terminology.deprecated-form: தேவன்" }] } })
      .mockResolvedValueOnce({ written: true, path: "/out/rut.usfm", chapters: 4, overridden: true });
  });

  it("shows what blocks, exports only after the override is ticked, and says it was recorded", async () => {
    render(ExportModal, { props: { onClose: vi.fn() } });
    await fireEvent.click(screen.getByText("Non-aligned USFM"));
    expect(await screen.findByText(/Not exported: 1 item\(s\) block publication/)).toBeInTheDocument();
    expect(screen.getByText(/terminology.deprecated-form: தேவன்/)).toBeInTheDocument();
    const anyway = screen.getByRole("button", { name: "Export anyway" });
    expect(anyway).toBeDisabled();
    await fireEvent.click(screen.getByRole("checkbox"));
    await fireEvent.click(anyway);
    expect(exportNonAligned).toHaveBeenLastCalledWith("/out/rut.usfm", true);
    expect(await screen.findByText(/override is recorded/)).toBeInTheDocument();
    expect(pickSavePath).toHaveBeenCalledTimes(1);  // the override reuses the chosen path
  });
});
