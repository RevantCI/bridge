/**
 * The AI-triage overlay's pure logic (utils/reportStats.ts).
 *
 * The predicate is the safety-critical part of this feature: it decides
 * which findings a reviewer never sees. Hiding a real translation error is
 * a far worse failure than leaving a false positive on screen, so the
 * asymmetry is asserted from several directions here.
 */
import { describe, expect, it } from "vitest";

import {
  TRIAGE_VERDICT_LABELS,
  applyTriage,
  effectiveVerdict,
  exportRows,
  hiddenByTriage,
  isHiddenByTriage,
  triageFor,
  triagedCount,
} from "../../utils/reportStats";
import type { ReportRow, TriageRecord } from "../../types/report";
import { reportRow } from "./reportFixtures";

function record(overrides: Partial<TriageRecord> = {}): TriageRecord {
  return {
    findingId: "f1", chapter: "1", verse: "1", checkType: "wildebeest.script.mixed",
    family: "mechanical", verdict: "false_positive", confidence: 95,
    reason: "Danda punctuation is correct for this language.",
    model: "gpt-5.6", timestamp: "2026-09-07T00:00:00Z", userOverride: null,
    ...overrides,
  };
}

const row = reportRow({ id: "rut:a", triageHash: "h1" });
const entries = (r: TriageRecord): Record<string, TriageRecord> => ({ h1: r });

describe("isHiddenByTriage", () => {
  it("hides a confident false positive at or above the threshold", () => {
    expect(isHiddenByTriage(row, entries(record({ confidence: 95 })), 90)).toBe(true);
    expect(isHiddenByTriage(row, entries(record({ confidence: 90 })), 90)).toBe(true);
  });

  it("keeps a false positive the model was less sure about", () => {
    expect(isHiddenByTriage(row, entries(record({ confidence: 89 })), 90)).toBe(false);
  });

  it.each(["true_positive", "uncertain"] as const)(
    "never hides a %s finding, however confident the model was",
    (verdict) => {
      expect(isHiddenByTriage(row, entries(record({ verdict, confidence: 100 })), 50)).toBe(false);
    },
  );

  it("hides nothing when the slider is off", () => {
    expect(isHiddenByTriage(row, entries(record({ confidence: 100 })), null)).toBe(false);
    expect(isHiddenByTriage(row, entries(record({ confidence: 100 })), 0)).toBe(false);
  });

  it("keeps an untriaged row", () => {
    expect(isHiddenByTriage(row, {}, 50)).toBe(false);
    expect(isHiddenByTriage(reportRow({ triageHash: "" }), entries(record()), 50)).toBe(false);
  });

  it("lets a thumbs-up reveal a finding the model was certain about", () => {
    const overridden = record({
      confidence: 100,
      userOverride: { verdict: "true_positive", timestamp: "t" },
    });
    expect(isHiddenByTriage(row, entries(overridden), 50)).toBe(false);
  });

  it("lets a thumbs-down hide a finding the model was unsure about", () => {
    // A human judgement is definite, not a scored guess, so the model's own
    // low confidence must not keep the row on screen.
    const overridden = record({
      verdict: "uncertain", confidence: 0,
      userOverride: { verdict: "false_positive", timestamp: "t" },
    });
    expect(isHiddenByTriage(row, entries(overridden), 90)).toBe(true);
  });

  it("still respects the off position over a thumbs-down", () => {
    const overridden = record({ userOverride: { verdict: "false_positive", timestamp: "t" } });
    expect(isHiddenByTriage(row, entries(overridden), null)).toBe(false);
  });
});

describe("effectiveVerdict", () => {
  it("prefers the reviewer's override", () => {
    expect(effectiveVerdict(record({
      verdict: "false_positive",
      userOverride: { verdict: "true_positive", timestamp: "t" },
    }))).toBe("true_positive");
  });

  it("falls back to the model verdict", () => {
    expect(effectiveVerdict(record({ verdict: "uncertain" }))).toBe("uncertain");
  });
});

describe("applyTriage and hiddenByTriage", () => {
  const rows: ReportRow[] = [
    reportRow({ id: "a", triageHash: "h-fp" }),
    reportRow({ id: "b", triageHash: "h-tp" }),
    reportRow({ id: "c", triageHash: "h-unsure" }),
    reportRow({ id: "d", triageHash: "" }),
  ];
  const map: Record<string, TriageRecord> = {
    "h-fp": record({ verdict: "false_positive", confidence: 96 }),
    "h-tp": record({ verdict: "true_positive", confidence: 96 }),
    "h-unsure": record({ verdict: "false_positive", confidence: 60 }),
  };

  it("partitions rows into shown and hidden without losing any", () => {
    const shown = applyTriage(rows, map, 90);
    const hidden = hiddenByTriage(rows, map, 90);
    expect(hidden.map((r) => r.id)).toEqual(["a"]);
    expect(shown.map((r) => r.id)).toEqual(["b", "c", "d"]);
    expect(shown.length + hidden.length).toBe(rows.length);
  });

  it("shows everything with the slider off", () => {
    expect(applyTriage(rows, map, null)).toHaveLength(4);
    expect(hiddenByTriage(rows, map, null)).toHaveLength(0);
  });

  it("hides more as the threshold drops", () => {
    expect(hiddenByTriage(rows, map, 50).map((r) => r.id)).toEqual(["a", "c"]);
  });

  it("counts how many rows carry a verdict at all", () => {
    expect(triagedCount(rows, map)).toBe(3);
    expect(triagedCount(rows, {})).toBe(0);
  });
});

describe("triageFor", () => {
  it("looks a record up by the row's hash", () => {
    expect(triageFor(row, entries(record()))?.confidence).toBe(95);
  });

  it("returns null for a row with no hash or no verdict", () => {
    expect(triageFor(reportRow({ triageHash: "" }), entries(record()))).toBeNull();
    expect(triageFor(row, {})).toBeNull();
  });
});

describe("exportRows", () => {
  it("flattens the verdict a reviewer was looking at onto the row", () => {
    const [exported] = exportRows([row], entries(record()));
    expect(exported.triageVerdict).toBe(TRIAGE_VERDICT_LABELS.false_positive);
    expect(exported.triageConfidence).toBe("95");
    expect(exported.triageReason).toBe("Danda punctuation is correct for this language.");
  });

  it("exports the override, not the model verdict, when one exists", () => {
    const overridden = record({ userOverride: { verdict: "true_positive", timestamp: "t" } });
    expect(exportRows([row], entries(overridden))[0].triageVerdict)
      .toBe(TRIAGE_VERDICT_LABELS.true_positive);
  });

  it("leaves triage columns empty for untriaged rows, and works with no triage at all", () => {
    expect(exportRows([row], {})[0].triageVerdict).toBe("");
    expect(exportRows([row])[0].triageConfidence).toBe("");
  });

  it("still converts the category to its display label", () => {
    expect(exportRows([row], {})[0].category).toBe("Greek Room");
  });
});
