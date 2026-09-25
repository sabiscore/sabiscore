import { readdirSync, readFileSync } from "node:fs";
import { extname, join } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * Directive v8 §3.6: `apps/web` never computes expected value, implied
 * probability or a stake from odds. The backend owns EV, edge and Kelly
 * (CLAUDE.md); a second browser computation once produced a second,
 * contradictory edge (see EdgeDeltaBar). Comments are skipped so explaining
 * the rule does not trip it.
 */
const SOURCE_ROOT = join(process.cwd(), "src");
const ODDS_ARITHMETIC = [
  /\b1(?:\.0)?\s*\/\s*\(?[\w.?]*odds\w*/i, // 1 / odds  -> implied probability
  /[\w.?)\]]*odds\w*\s*-\s*1(?![\d.])/i, // odds - 1  -> Kelly denominator / EV
  /\*\s*\(?[\w.?]*odds\w*/i, // p * odds  -> EV
];

function sourceFiles(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) return sourceFiles(path);
    if (entry.name.includes(".test.") || entry.name.includes(".spec.")) return [];
    return [".ts", ".tsx"].includes(extname(entry.name)) ? [path] : [];
  });
}

export function oddsArithmeticHits(source: string): string[] {
  return source
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => !/^(\/\/|\*|\/\*)/.test(line))
    .filter((line) => ODDS_ARITHMETIC.some((pattern) => pattern.test(line)));
}

describe("no client-side betting math", () => {
  it("computes no EV, implied probability or stake from odds in web source", () => {
    const offenders = sourceFiles(SOURCE_ROOT).flatMap((path) =>
      oddsArithmeticHits(readFileSync(path, "utf8")).map(
        (line) => `${path.slice(SOURCE_ROOT.length + 1)}: ${line}`,
      ),
    );
    expect(offenders).toEqual([]);
  });

  it.each([
    "const implied = 1 / marketOdds;",
    "const ev = prob * odds.home - 1;",
    "const kelly = (p * b - 1) / (odds - 1);",
  ])("catches %s", (line) => {
    expect(oddsArithmeticHits(line)).toHaveLength(1);
  });

  it("ignores comments that explain the rule", () => {
    expect(oddsArithmeticHits("// recomputing 1 / market_odds here was the bug")).toEqual([]);
  });
});
