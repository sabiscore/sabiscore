import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * APEX §11 — "Internal provenance IDs must never become consumer branding."
 * It names `v5_phase7` / `v6_phase8` / raw artifact filenames explicitly, and
 * permits them only in "developer/admin diagnostics".
 *
 * The violation shipped on FIVE components at once (the homepage Model Pulse
 * rail, the mobile platform summary, two sites in the match dashboard, and two
 * dead components), so a point-fix at any one of them would not have prevented
 * the next — the same shape as the league-vocabulary and `LIVE`-badge classes
 * this repo has already been bitten by. The guard is therefore repo-wide,
 * matching the idiom of copy-contract.test.ts, league-contract.test.ts and
 * metadata-title-contract.test.ts.
 *
 * What it catches: a consumer component interpolating a raw provenance field
 * into JSX. What it deliberately does not catch: passing those fields around
 * in types or fetch layers — only *rendering* them is the violation.
 */
const SRC_ROOT = join(process.cwd(), "src");

/** §11-exempt: developer/admin diagnostics, and the mapping module itself. */
const EXEMPT = [
  join("components", "admin"),
  join("app", "admin"),
  join("lib", "model-identity.ts"),
  join("lib", "model-status.ts"), // the mapping's only sanctioned caller
];

/**
 * Manifest fields that are pure engineering provenance. Mirrors
 * INTERNAL_PROVENANCE_FIELDS in lib/model-identity.ts and
 * backend/models/active_generation.json.
 */
const PROVENANCE_FIELDS = [
  "active_version",
  "generation_hash",
  "feature_schema_version",
  "served_head",
  "model_version",
  "artifact_sha256",
];

/**
 * `{...model_version}` / `{foo.active_version}` inside JSX — a rendered value,
 * not a type declaration or a property read that gets mapped first.
 */
const RENDERED = new RegExp(
  String.raw`\{[^{}]*\b(?:${PROVENANCE_FIELDS.join("|")})\b[^{}]*\}`,
);

/** A line that hands the value to the mapping is compliant, not a violation. */
const MAPPED = /generationLabel|certificationLabel|promotionLabel/;

function sourceFiles(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) return sourceFiles(path);
    if (entry.name.includes(".test.") || entry.name.includes(".spec.")) return [];
    return /\.tsx?$/.test(entry.name) ? [path] : [];
  });
}

function offenders(): string[] {
  return sourceFiles(SRC_ROOT)
    .filter((path) => !EXEMPT.some((exempt) => path.includes(exempt)))
    .filter((path) => {
      const source = readFileSync(path, "utf8");
      return source
        .split("\n")
        .some((line) => RENDERED.test(line) && !MAPPED.test(line));
    })
    .map((path) => path.slice(SRC_ROOT.length + 1).replace(/\\/g, "/"));
}

describe("model identity contract (APEX §11)", () => {
  it("no consumer surface renders a raw internal provenance identifier", () => {
    expect(offenders()).toEqual([]);
  });

  it("the raw identifiers are still reachable in admin diagnostics", () => {
    const adminClient = readFileSync(
      join(SRC_ROOT, "components", "admin", "model-health-client.tsx"),
      "utf8",
    );
    for (const field of ["active_version", "generation_hash", "served_head"]) {
      expect(adminClient).toContain(field);
    }
  });
});
