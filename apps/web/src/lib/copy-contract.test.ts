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
// "Closing line value" is a term of art requiring a taken price and subsequent
// market movement. The platform's aggregate diagnostic stat (model_probs[argmax]
// − closing_probs[argmax]) has neither, so labelling it "Closing line value"
// is a mislabelling — the same defect family as DEBT 63. The stat tile is now
// labelled "Market belief differential". This guard catches regressions.
// Note: the abbreviation "CLV" is permitted; only the spelled-out term of art
// is banned in JSX label props on the aggregate stat tile.
const CLV_MISLABEL = /label=["']Closing[- ]line[- ]value["']/i;
const UNSUPPORTED_OUTCOME_CLAIMS =
  /\b(maximi[sz]e (?:your )?betting edge|beat(?:s|ing)? (?:the market|the odds)|win more|winning picks?|highly accurate predictions?|profitable predictions?|guaranteed returns?)\b/i;

// Method names for models that do not ship. No reinforcement-learning policy is
// installed (no stable-baselines3, no artifact) and no Bayesian network exists
// (DEBT 42), yet cards read "RL Bet Recommendation" and "BNN Uncertainty"
// (DEBT 159, 160). A hard-coded settled count ("live with 59 settled
// predictions") went false when the served generation changed.
const UNSHIPPED_METHOD_CLAIMS =
  /\b(RL (bet|betting|abstention)|BNN uncertainty|Bayesian Neural Network)\b/i;
const HARDCODED_SETTLED_COUNT = /live with \d+ settled/i;
// Times in the viewer's own zone, unlabelled: /intelligence printed "12:30 PM"
// beside pages that say "12:30 WAT" (DEBT 160). Use @/lib/lagos-time.
const BROWSER_ZONE_TIME = /toLocaleTimeString\(\s*\[\]|DateTimeFormat\(\s*undefined/;

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

  it("contains no unsupported outcome-oriented promotional claims", () => {
    expect(matchingFiles(UNSUPPORTED_OUTCOME_CLAIMS)).toEqual([]);
  });

  it("does not mislabel the model–market belief differential as closing-line value", () => {
    expect(matchingFiles(CLV_MISLABEL)).toEqual([]);
  });

  it("names no model method that does not ship, and hard-codes no settled count", () => {
    expect(matchingFiles(UNSHIPPED_METHOD_CLAIMS)).toEqual([]);
    expect(matchingFiles(HARDCODED_SETTLED_COUNT)).toEqual([]);
  });

  it("prints no time in the viewer's own zone without a label", () => {
    expect(matchingFiles(BROWSER_ZONE_TIME)).toEqual([]);
  });
});
