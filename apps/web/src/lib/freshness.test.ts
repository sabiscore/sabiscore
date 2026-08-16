import { describe, expect, it } from "vitest";
import { mapEvidenceFreshness } from "./freshness";

describe("mapEvidenceFreshness", () => {
  it.each([undefined, null, Number.NaN, -1])("fails closed for %s", (age) => {
    expect(mapEvidenceFreshness({ stalenessSeconds: age }).tag).toBe("UNKNOWN");
  });

  it("availability=false wins even when a cached payload carries zero", () => {
    expect(mapEvidenceFreshness({ stalenessSeconds: 0, available: false, tag: "LIVE" }).tag).toBe("UNKNOWN");
  });

  it("treats an explicit measured zero as fresh", () => {
    expect(mapEvidenceFreshness({ stalenessSeconds: 0, available: true }).tag).toBe("LIVE");
  });

  it("uses the canonical 24-hour boundary", () => {
    expect(mapEvidenceFreshness({ stalenessSeconds: 86_399 }).tag).toBe("RECENT");
    expect(mapEvidenceFreshness({ stalenessSeconds: 86_400 }).tag).toBe("STALE");
  });

  it("preserves an explicit trustworthy backend tag", () => {
    expect(mapEvidenceFreshness({ stalenessSeconds: 10, available: true, tag: "STALE" }).tag).toBe("STALE");
  });
});
