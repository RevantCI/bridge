import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/svelte";

const pickSavePath = vi.fn();
const reportExport = vi.fn();

vi.mock("../../api/bridgeClient", () => ({
  bridge: {
    pickSavePath: (...args: unknown[]) => pickSavePath(...args),
    reportExport: (...args: unknown[]) => reportExport(...args),
  },
}));

import ProjectReportScreen from "../ProjectReportScreen.svelte";
import { EXPORT_COLUMNS } from "../../utils/reportStats";
import type { ReportJobSnapshot, TriageJobSnapshot, TriageRecord } from "../../types/report";
import { reportRow, sampleReport } from "./reportFixtures";

function mount(props: Partial<{
  report: ReturnType<typeof sampleReport> | null;
  job: ReportJobSnapshot | null;
  error: string;
  onGenerate: () => void;
  onCancel: () => void;
  onNavigate: (book: string, chapter: string, verse: string) => void;
  triage: Record<string, TriageRecord>;
  triageJob: TriageJobSnapshot | null;
  triageAvailable: boolean;
  triageUnavailableReason: string;
  triageError: string;
  triageThreshold: number | null;
  onRunTriage: () => void;
  onCancelTriage: () => void;
  onTriageThreshold: (value: number | null) => void;
  onTriageOverride: (book: string, hash: string, verdict: string) => void;
}> = {}) {
  return render(ProjectReportScreen, {
    props: {
      projectName: "IRV Tamil",
      report: sampleReport(),
      job: null,
      error: "",
      onGenerate: () => {},
      ...props,
    },
  });
}

function tableRows(): HTMLElement[] {
  const table = screen.getByRole("table", { name: "Issue table" });
  return within(table).getAllByRole("row").slice(1);
}

/** jsdom does not toggle <details> on a summary click; open the menu directly. */
function openExportMenu(): void {
  const details = screen.getByText("Export ▾").closest("details") as HTMLDetailsElement;
  details.open = true;
}

beforeEach(() => {
  pickSavePath.mockReset();
  reportExport.mockReset();
});

describe("ProjectReportScreen", () => {
  it("lists every book with its per-check progress and scopes the table to a clicked book", async () => {
    mount();
    const books = screen.getByLabelText("Books in this report");
    expect(within(books).getByText("Ruth")).toBeInTheDocument();
    expect(within(books).getByText("Genesis")).toBeInTheDocument();
    expect(within(books).getAllByText("2/4 chapters")).toHaveLength(2);
    expect(within(books).getAllByText("83/120 checks")).toHaveLength(2);
    expect(within(books).getAllByText("no resource index")).toHaveLength(2);
    expect(within(books).getAllByText("1 open")).toHaveLength(2);
    expect(screen.getByText("Showing 4 of 4 issues")).toBeInTheDocument();

    await fireEvent.click(within(books).getByRole("button", { name: /Genesis/ }));

    expect(screen.getByText("Showing 2 of 2 issues (filtered from 4)")).toBeInTheDocument();
    expect(screen.queryByText("Mixed script")).not.toBeInTheDocument();
    expect(screen.getByText("Word Alignment recheck required")).toBeInTheDocument();
    // Check-level tiles follow the selected book too.
    const tiles = within(screen.getByLabelText("Summary"));
    expect(tiles.getByText("Checks run").nextElementSibling?.textContent).toBe("177");
  });

  it("filters by category chip and clears back to everything", async () => {
    mount();
    await fireEvent.click(screen.getByRole("button", { name: "tN" }));
    expect(screen.getByText("Showing 1 of 1 issue (filtered from 4)")).toBeInTheDocument();
    expect(screen.getByText("figs-metaphor: θεός")).toBeInTheDocument();

    await fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(screen.getByText("Showing 4 of 4 issues")).toBeInTheDocument();
  });

  it("shows the summary tiles, the table columns the reviewer asked for, and who fixed what", () => {
    mount();
    const tiles = within(screen.getByLabelText("Summary"));
    expect(tiles.getByText("Checks run").nextElementSibling?.textContent).toBe("354");
    expect(tiles.getByText("Passed").nextElementSibling?.textContent).toBe("260");
    expect(tiles.getByText("Failed").nextElementSibling?.textContent).toBe("94");
    expect(tiles.getByText("Resolved").nextElementSibling?.textContent).toBe("2");
    expect(tiles.getByText("Unresolved").nextElementSibling?.textContent).toBe("2");

    const headers = screen.getAllByRole("columnheader").map((h) => h.textContent);
    expect(headers).toEqual([
      "Error category", "Book", "Chapter", "Verse", "Issue and explanation", "AI proposal", "Fixed by", "Pass / fail",
    ]);
    expect(screen.getByText("Machine (Bridge AI)")).toBeInTheDocument();
    expect(screen.getByText("Select: தேவன்")).toBeInTheDocument();
    expect(screen.getAllByText("✓ Pass")).toHaveLength(2);
    expect(screen.getAllByText("✗ Fail")).toHaveLength(2);
    // Charts carry their identities in text, never colour alone.
    expect(screen.getByRole("figure", { name: "Issues by category" })).toHaveTextContent("Alignment");
    expect(screen.getByRole("figure", { name: "Fixed by" })).toHaveTextContent("Machine");
  });

  it("exports the filtered rows as CSV to the path the user picks", async () => {
    pickSavePath.mockResolvedValue("C:/exports/report.csv");
    reportExport.mockResolvedValue({ written: true, path: "C:/exports/report.csv", rows: 1, format: "csv" });
    mount();
    await fireEvent.click(screen.getByRole("button", { name: "tN" }));
    openExportMenu();
    await fireEvent.click(screen.getByRole("button", { name: "CSV" }));

    await waitFor(() => expect(reportExport).toHaveBeenCalledTimes(1));
    const [path, format, rows, columns] = reportExport.mock.calls[0];
    expect(path).toBe("C:/exports/report.csv");
    expect(format).toBe("csv");
    expect(rows).toHaveLength(1);
    expect(rows[0].id).toBe("rut:b");
    expect(rows[0].category).toBe("tN");
    expect(columns).toBe(EXPORT_COLUMNS);
    expect(pickSavePath.mock.calls[0][0]).toMatch(/^irv-tamil-qa-report-\d{4}-\d{2}-\d{2}\.csv$/);
    expect(await screen.findByText("Wrote 1 row to C:/exports/report.csv")).toBeInTheDocument();
  });

  it("writes nothing when the save dialog is cancelled", async () => {
    pickSavePath.mockResolvedValue(null);
    mount();
    openExportMenu();
    await fireEvent.click(screen.getByRole("button", { name: "TSV" }));
    await waitFor(() => expect(pickSavePath).toHaveBeenCalledTimes(1));
    expect(reportExport).not.toHaveBeenCalled();
  });

  it("prints the report for PDF through the webview's print dialog", async () => {
    const print = vi.fn();
    const original = window.print;
    window.print = print;
    try {
      mount();
      openExportMenu();
      await fireEvent.click(screen.getByRole("button", { name: "PDF (print)" }));
      await waitFor(() => expect(print).toHaveBeenCalledTimes(1));
    } finally {
      window.print = original;
    }
  });

  it("shows generation progress with a cancel action, and the previous report underneath", async () => {
    const onCancel = vi.fn();
    const job: ReportJobSnapshot = {
      jobId: "j1", state: "running", totalBooks: 66, completedBooks: 12, percent: 18, currentBook: "exo",
      failedBooks: [], bookDurationsMs: {}, totalDurationMs: 0,
      error: null, createdAt: "", finishedAt: null, ready: false,
    };
    mount({ job, onCancel });
    expect(screen.getByRole("status")).toHaveTextContent("Generating report… 12/66 books · EXO");
    await fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(screen.getByText("Showing 4 of 4 issues")).toBeInTheDocument();
  });

  it("offers to generate when there is no report yet, and to retry after a failure", async () => {
    const onGenerate = vi.fn();
    const { unmount } = mount({ report: null, onGenerate });
    await fireEvent.click(screen.getByRole("button", { name: "Generate report" }));
    expect(onGenerate).toHaveBeenCalledTimes(1);
    unmount();

    mount({ report: null, error: "sidecar went away", onGenerate });
    expect(screen.getByText(/Could not generate the report: sidecar went away/)).toBeInTheDocument();
    await fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(onGenerate).toHaveBeenCalledTimes(2);
  });

  it("navigates to a verse from its row", async () => {
    const onNavigate = vi.fn();
    mount({ onNavigate });
    await fireEvent.click(screen.getByTitle("Open GEN 3:1"));
    expect(onNavigate).toHaveBeenCalledWith("gen", "3", "1");
  });

  it("pages long tables a hundred rows at a time", async () => {
    const many = Array.from({ length: 250 }, (_, i) => reportRow({ id: `rut:${i}`, verse: String(i + 1) }));
    mount({ report: sampleReport({ rows: many }) });
    expect(tableRows()).toHaveLength(100);
    await fireEvent.click(screen.getByRole("button", { name: "Show 100 more" }));
    expect(tableRows()).toHaveLength(200);
    await fireEvent.click(screen.getByRole("button", { name: "Show all 250" }));
    expect(tableRows()).toHaveLength(250);
  });
});

describe("ProjectReportScreen — AI triage overlay", () => {
  function triageRecord(overrides: Partial<TriageRecord> = {}): TriageRecord {
    return {
      findingId: "f1", chapter: "1", verse: "1", checkType: "wildebeest.script.mixed",
      family: "mechanical", verdict: "false_positive", confidence: 96,
      reason: "Tamil uses this punctuation normally.",
      model: "gpt-5.6", timestamp: "2026-09-07T00:00:00Z", userOverride: null,
      ...overrides,
    };
  }

  /** sampleRows[0] is the Greek Room row; give it the only verdict. */
  const oneVerdict = (overrides: Partial<TriageRecord> = {}) => ({
    "hash-rut:a": triageRecord(overrides),
  });

  it("renders exactly as before when no triage has ever run", () => {
    mount();
    expect(screen.queryByLabelText(/Hide findings rated/)).not.toBeInTheDocument();
    expect(screen.queryByText(/hidden by AI triage/)).not.toBeInTheDocument();
    expect(tableRows()).toHaveLength(4);
  });

  it("disables the run button and explains why when there is no API key", () => {
    mount({ triageAvailable: false, triageUnavailableReason: "No OpenAI-compatible API key is configured." });
    const button = screen.getByRole("button", { name: "Run AI triage" });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("title", "No OpenAI-compatible API key is configured.");
  });

  it("runs triage when the button is enabled", async () => {
    const onRunTriage = vi.fn();
    mount({ triageAvailable: true, onRunTriage });
    await fireEvent.click(screen.getByRole("button", { name: "Run AI triage" }));
    expect(onRunTriage).toHaveBeenCalledTimes(1);
  });

  it("shows progress with a cancel action while triage runs", async () => {
    const onCancelTriage = vi.fn();
    const triageJob: TriageJobSnapshot = {
      jobId: "t1", state: "running", force: false, totalBooks: 66, completedBooks: 3, percent: 5,
      currentBook: "exo", currentChapter: "4", currentBookTriaged: 12, currentBookSkipped: 2,
      triaged: 40, skipped: 5, pruned: 0, batches: 4, failedBatches: 0, failedBooks: [], books: [],
      error: null, createdAt: "", finishedAt: null,
    };
    mount({ triageJob, onCancelTriage });
    expect(screen.getByText(/Triaging… 3\/66 books · EXO · 12 findings/)).toBeInTheDocument();
    await fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onCancelTriage).toHaveBeenCalledTimes(1);
  });

  it("hides a confident false positive and says how many it hid", () => {
    mount({ triage: oneVerdict(), triageThreshold: 90 });
    expect(tableRows()).toHaveLength(3);
    const bar = within(screen.getByLabelText("AI triage"));
    expect(bar.getByText(/hidden by AI triage/)).toHaveTextContent("1 finding hidden by AI triage.");
    // The hidden row is the Greek Room one that carried the verdict.
    expect(screen.queryByText("Mixed script")).not.toBeInTheDocument();
  });

  it("keeps everything visible with the slider off", () => {
    mount({ triage: oneVerdict(), triageThreshold: null });
    expect(tableRows()).toHaveLength(4);
    expect(screen.getByText(/Showing every finding/)).toBeInTheDocument();
  });

  it.each(["uncertain", "true_positive"] as const)(
    "never hides a %s finding, however confident the model was",
    (verdict) => {
      mount({ triage: oneVerdict({ verdict, confidence: 100 }), triageThreshold: 50 });
      expect(tableRows()).toHaveLength(4);
    },
  );

  it("reveals hidden rows on request without moving the slider", async () => {
    mount({ triage: oneVerdict(), triageThreshold: 90 });
    expect(tableRows()).toHaveLength(3);
    await fireEvent.click(screen.getByRole("button", { name: "Show them" }));
    expect(tableRows()).toHaveLength(4);
    // The count stays truthful while they are on screen.
    expect(screen.getByText(/shown despite AI triage/)).toBeInTheDocument();
    await fireEvent.click(screen.getByRole("button", { name: "Hide them again" }));
    expect(tableRows()).toHaveLength(3);
  });

  it("moves the threshold through the slider, and treats its floor as off", async () => {
    const onTriageThreshold = vi.fn();
    mount({ triage: oneVerdict(), triageThreshold: 90, onTriageThreshold });
    const slider = screen.getByLabelText(/Hide findings rated at least/);
    await fireEvent.input(slider, { target: { value: "75" } });
    expect(onTriageThreshold).toHaveBeenLastCalledWith(75);
    await fireEvent.input(slider, { target: { value: "49" } });
    expect(onTriageThreshold).toHaveBeenLastCalledWith(null);
  });

  it("shows the verdict and the model's reason on a triaged row", () => {
    mount({ triage: oneVerdict({ confidence: 72 }), triageThreshold: 90 });
    expect(screen.getByText("Likely false positive · 72%")).toBeInTheDocument();
    expect(screen.getByText("Tamil uses this punctuation normally.")).toBeInTheDocument();
  });

  it("sends a thumbs up, and toggles it off when clicked again", async () => {
    const onTriageOverride = vi.fn();
    mount({ triage: oneVerdict({ confidence: 60 }), triageThreshold: 90, onTriageOverride });
    await fireEvent.click(screen.getByRole("button", { name: /Mark RUT 1:1 as a real problem/ }));
    expect(onTriageOverride).toHaveBeenCalledWith("rut", "hash-rut:a", "true_positive");

  });

  it("clears an override by clicking the thumb it already carries", async () => {
    const onTriageOverride = vi.fn();
    mount({
      triage: oneVerdict({ confidence: 60, userOverride: { verdict: "true_positive", timestamp: "t" } }),
      triageThreshold: 90,
      onTriageOverride,
    });
    await fireEvent.click(screen.getByRole("button", { name: /Mark RUT 1:1 as a real problem/ }));
    expect(onTriageOverride).toHaveBeenCalledWith("rut", "hash-rut:a", "");
  });

  it("labels an overridden verdict as the reviewer's own call", () => {
    mount({
      triage: oneVerdict({ userOverride: { verdict: "true_positive", timestamp: "t" } }),
      triageThreshold: 90,
    });
    expect(screen.getByText("Likely real · your call")).toBeInTheDocument();
    // And the override wins: the row is no longer hidden.
    expect(tableRows()).toHaveLength(4);
  });

  it("carries the verdict into an export", async () => {
    pickSavePath.mockResolvedValue("C:/out.csv");
    reportExport.mockResolvedValue({ written: true, path: "C:/out.csv", rows: 3, format: "csv" });
    mount({ triage: oneVerdict(), triageThreshold: null });
    openExportMenu();
    await fireEvent.click(screen.getByRole("button", { name: "CSV" }));
    await waitFor(() => expect(reportExport).toHaveBeenCalled());
    const rows = reportExport.mock.calls[0][2];
    const triaged = rows.find((r: Record<string, string>) => r.triageVerdict);
    expect(triaged.triageVerdict).toBe("Likely false positive");
    expect(triaged.triageConfidence).toBe("96");
  });

  it("surfaces a triage failure without breaking the report", () => {
    mount({ triageError: "Network error contacting OpenAI" });
    expect(screen.getByText(/AI triage: Network error contacting OpenAI/)).toBeInTheDocument();
    expect(tableRows()).toHaveLength(4);
  });
});
