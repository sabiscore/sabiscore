/**
 * Repo-wide guard: user-facing dates go through formatLagosTimestamp().
 *
 * vΩ.22 standardised match-page timestamps on Africa/Lagos WAT via
 * `formatLagosTimestamp()` + `<time dateTime=…>`, but fixed only the two sites
 * it was looking at. Five more `new Date(x).toLocaleString()` calls survived in
 * full-analysis-dashboard, value-bet-scanner (x2), performance-page-client and
 * team/[slug] — so the same page could print WAT in one place and the viewer's
 * local zone, unlabelled, in another.
 *
 * Two separate defects, which is why this is enforced rather than remembered:
 *   1. Truthfulness — an unlabelled timestamp is ambiguous, and in a server
 *      component it renders the SERVER's timezone to every viewer.
 *   2. Hydration — `toLocaleString()` is locale- and zone-dependent, so a
 *      client component's SSR output can disagree with its hydrated output.
 *
 * Number formatting (`someNumber.toLocaleString()`) is unaffected and allowed;
 * this only matches the `new Date(...).toLocaleString()` shape.
 */
import { describe, expect, it } from "vitest";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

const SRC = join(__dirname, "..");

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) return walk(full);
    return /\.tsx?$/.test(entry) && !/\.(test|spec)\.tsx?$/.test(entry) ? [full] : [];
  });
}

describe("timestamp display contract", () => {
  it("renders no user-facing date through a bare toLocaleString()", () => {
    const offenders: string[] = [];

    for (const file of walk(SRC)) {
      const source = readFileSync(file, "utf8");
      source.split("\n").forEach((line, i) => {
        if (line.trim().startsWith("*") || line.trim().startsWith("//")) return;
        // `new Date(...).toLocaleString()` / `.toLocaleDateString()` / `.toLocaleTimeString()`
        if (/new Date\([^)]*\)\s*\.toLocale(Date|Time)?String\(\s*\)/.test(line)) {
          offenders.push(`${file.replace(SRC, "src")}:${i + 1} — ${line.trim()}`);
        }
      });
    }

    expect(
      offenders,
      `Use formatLagosTimestamp() from @/lib/full-analysis-contract and label the ` +
        `zone (… WAT), rather than the viewer's or the server's local zone:\n` +
        offenders.join("\n"),
    ).toEqual([]);
  });
});
