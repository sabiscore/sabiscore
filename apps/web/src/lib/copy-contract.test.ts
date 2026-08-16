import { readdirSync, readFileSync } from "node:fs";
import { extname, join } from "node:path";
import { describe, expect, it } from "vitest";

const SOURCE_ROOT = join(process.cwd(), "src");
const SOURCE_EXTENSIONS = new Set([".ts", ".tsx"]);
const PROHIBITED_COPY =
  /\b(lock|banker|guaranteed|sure bet|free money|execute immediately)\b/i;
const EIGHTH_KELLY = /⅛|\b1\/8\b|one-eighth|eighth[- ]kelly/i;
// edge_quality_score is a confidence/freshness/completeness composite, never a
// market edge (@/lib/edge-quality) — this exact phrase + celebratory framing
// previously shipped on BigMatchesCarousel's top-ranked card (match-selector.tsx).
const TOP_EDGE_TODAY = /top edge today/i;

function sourceFiles(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) return sourceFiles(path);
    if (entry.name.includes(".test.") || entry.name.includes(".spec."))
      return [];
    return SOURCE_EXTENSIONS.has(extname(entry.name)) ? [path] : [];
  });
}

function matchingFiles(pattern: RegExp): string[] {
  return sourceFiles(SOURCE_ROOT)
    .filter((path) => pattern.test(readFileSync(path, "utf8")))
    .map((path) => path.slice(SOURCE_ROOT.length + 1));
}

describe("public copy contract", () => {
  it("contains no prohibited certainty or gambling-promotional terms", () => {
    expect(matchingFiles(PROHIBITED_COPY)).toEqual([]);
  });

  it("contains no one-eighth-Kelly language", () => {
    expect(matchingFiles(EIGHTH_KELLY)).toEqual([]);
  });

  it("never labels the top edge_quality_score fixture as a celebratory market edge", () => {
    expect(matchingFiles(TOP_EDGE_TODAY)).toEqual([]);
  });
});
