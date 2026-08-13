import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * `app/layout.tsx` declares `metadata.title.template = "%s | Sabiscore"`, so
 * Next.js appends the brand to every child page's own title automatically.
 * A page that spells the brand into its own `title:` therefore renders
 * "Match Insights | Sabiscore | Sabiscore" in the browser tab, in the SEO
 * <title>, and in every social share card.
 *
 * This shipped on all 8 titled pages simultaneously, so a single point-fix
 * would not have prevented the next one — the guard is repo-wide, matching
 * the idiom of copy-contract.test.ts and league-contract.test.ts.
 */
const APP_ROOT = join(process.cwd(), "src", "app");
const ROOT_LAYOUT = join(APP_ROOT, "layout.tsx");

/** `title: "..."` / `title: \`...\`` — the metadata field, not arbitrary prose. */
const TITLE_FIELD = /\btitle:\s*(["'`])((?:\\.|(?!\1).)*)\1/g;
const BRAND = /sabiscore/i;

function pageFiles(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) return pageFiles(path);
    if (entry.name.includes(".test.") || entry.name.includes(".spec.")) return [];
    // Only page/layout modules declare route metadata.
    return /^(page|layout)\.tsx?$/.test(entry.name) ? [path] : [];
  });
}

function offenders(): string[] {
  return pageFiles(APP_ROOT)
    .filter((path) => path !== ROOT_LAYOUT) // the root layout is where the brand belongs
    .filter((path) => {
      const source = readFileSync(path, "utf8");
      return [...source.matchAll(TITLE_FIELD)].some(([, , value]) => BRAND.test(value));
    })
    .map((path) => path.slice(APP_ROOT.length + 1).replace(/\\/g, "/"));
}

describe("route metadata title contract", () => {
  it("no page repeats the brand the root layout's title template already appends", () => {
    expect(offenders()).toEqual([]);
  });

  it("the root layout still supplies the brand exactly once", () => {
    const rootLayout = readFileSync(ROOT_LAYOUT, "utf8");
    expect(rootLayout).toMatch(/template:\s*(["'`])%s \| Sabiscore\1/);
  });
});
