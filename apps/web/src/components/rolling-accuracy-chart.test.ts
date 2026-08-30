import { describe, expect, it } from "vitest";
import { withFoldLabels } from "./rolling-accuracy-chart";

describe("withFoldLabels", () => {
  // Walk-forward points are folds, not calendar days. Two chronological splits
  // can end on the same date, which rendered as two identical x-axis ticks and
  // two identical tooltips — the live /performance chart showed "Aug 29" twice.
  it("disambiguates folds that share a calendar date", () => {
    const labels = withFoldLabels([
      { date: "2026-08-22T00:00:00Z" },
      { date: "2026-08-29T00:00:00Z" },
      { date: "2026-08-29T18:00:00Z" },
    ]).map((p) => p.label);

    expect(new Set(labels).size).toBe(labels.length);
    expect(labels[0]).not.toMatch(/^F\d/);
    expect(labels[1]).toMatch(/^F2 · /);
    expect(labels[2]).toMatch(/^F3 · /);
  });

  it("leaves unique dates as bare dates", () => {
    const labels = withFoldLabels([
      { date: "2026-08-22T00:00:00Z" },
      { date: "2026-08-25T00:00:00Z" },
    ]).map((p) => p.label);

    expect(labels.every((l) => !l.startsWith("F"))).toBe(true);
  });

  it("keeps every original field and renders a missing date as an em dash", () => {
    const [point] = withFoldLabels([{ date: null, accuracy: 0.4, n_matches: 3 }]);
    expect(point.label).toBe("—");
    expect(point.accuracy).toBe(0.4);
    expect(point.n_matches).toBe(3);
  });
});
