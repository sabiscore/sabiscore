import { describe, expect, it } from "vitest";

import { formatLagosTime, formatLagosTimestamp } from "./lagos-time";

describe("Lagos time", () => {
  it("prints WAT (UTC+1) whatever zone the process runs in", () => {
    // PSV-Heerenveen kicks off 18:00 UTC, 19:00 in Lagos.
    expect(formatLagosTime("2026-10-09T18:00:00Z")).toBe("19:00");
    expect(formatLagosTimestamp("2026-10-09T18:00:00Z")).toMatch(/9 Oct 2026, 19:00/);
  });

  it("accepts epoch milliseconds and Date values", () => {
    const at = Date.UTC(2026, 9, 9, 23, 30);
    expect(formatLagosTime(at)).toBe("00:30");
    expect(formatLagosTime(new Date(at))).toBe("00:30");
  });
});
