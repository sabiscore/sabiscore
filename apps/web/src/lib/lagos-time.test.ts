import { describe, expect, it } from "vitest";

import {
  formatLagosTime,
  formatLagosTimestamp,
  fromLagosInputValue,
  toLagosInputValue,
} from "./lagos-time";

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

  it("round-trips a datetime-local value as Lagos wall time, not browser time", () => {
    // Live 2026-10-03: the form showed 21:23 at 22:23 WAT and submitted an hour early.
    expect(toLagosInputValue("2026-10-03T21:23:00Z")).toBe("2026-10-03T22:23");
    expect(fromLagosInputValue("2026-10-03T22:23")).toBe("2026-10-03T21:23:00.000Z");
  });
});
