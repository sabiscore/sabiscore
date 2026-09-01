import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

describe("match Open Graph route contract", () => {
  it("does not manufacture probabilities, verdicts, or evidence state", () => {
    const source = readFileSync(join(process.cwd(), "src/app/api/og/match/[id]/route.tsx"), "utf8");

    expect(source).not.toMatch(/home_win|away_win|searchParams/);
    expect(source).not.toMatch(/ACTIONABLE|HIGH_CONVICTION|Verified Evidence/);
    expect(source).toContain("Missing or conflicting evidence remains unavailable.");
  });
});