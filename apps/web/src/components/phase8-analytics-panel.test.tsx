import { describe, expect, it } from "vitest";
import { freshnessLabel, groupFreshnessChip } from "./phase8-analytics-panel";

// freshnessLabel/groupFreshnessChip measure feature-data recency, not match
// state. They previously returned the literal string "Live"/"LIVE" for data
// fetched within the last hour, which reads as match-state on the primary
// /match/[id] result page — the same "bare LIVE badge" defect class already
// fixed in upcoming-matches-panel.tsx ("Fresh"/"Recent"/"Stale") and
// full-analysis-dashboard.tsx's FreshnessPill.
describe("phase8-analytics-panel freshness labels", () => {
  it("freshnessLabel never returns 'Live'", () => {
    for (const seconds of [0, 30, 3_599, 3_600, 86_399, 86_400, 200_000]) {
      expect(freshnessLabel(seconds).label.toLowerCase()).not.toBe("live");
    }
    expect(freshnessLabel(0).label).toBe("Fresh");
  });

  it("groupFreshnessChip never returns 'LIVE'", () => {
    for (const seconds of [0, 3_599, 3_600, 86_399, 86_400, 200_000]) {
      expect(groupFreshnessChip(seconds).label).not.toBe("LIVE");
    }
    expect(groupFreshnessChip(0).label).toBe("FRESH");
    expect(groupFreshnessChip(86_400).label).toBe("STALE");
  });
});
