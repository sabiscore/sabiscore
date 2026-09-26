import { readdirSync, readFileSync } from "node:fs";
import { extname, join, sep } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CANONICAL_SITE_URL, siteUrl } from "./site-url";

afterEach(() => vi.unstubAllEnvs());

function sourceFiles(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) return sourceFiles(path);
    if (entry.name.includes(".test.") || entry.name.includes(".spec.")) return [];
    return [".ts", ".tsx"].includes(extname(entry.name)) ? [path] : [];
  });
}

describe("siteUrl", () => {
  it("defaults to the canonical alias, never a per-deployment host or an unresolved domain", () => {
    vi.stubEnv("NEXT_PUBLIC_SITE_URL", "");
    vi.stubEnv("VERCEL_URL", "web-abc123-oversabis-projects.vercel.app");
    expect(siteUrl()).toBe(CANONICAL_SITE_URL);
    expect(siteUrl()).not.toContain("sabiscore.com");
  });

  it("lets an explicit NEXT_PUBLIC_SITE_URL override it, without a trailing slash", () => {
    vi.stubEnv("NEXT_PUBLIC_SITE_URL", "https://sabiscore.com/");
    expect(siteUrl()).toBe("https://sabiscore.com");
  });

  // Six copies each chose their own fallback (VERCEL_URL, sabiscore.com); fixing one
  // left the others live. The variable is read in one place.
  it("is the only reader of NEXT_PUBLIC_SITE_URL in the web source", () => {
    const root = join(process.cwd(), "src");
    const readers = sourceFiles(root)
      .filter((path) => readFileSync(path, "utf8").includes("process.env.NEXT_PUBLIC_SITE_URL"))
      .map((path) => path.slice(root.length + 1).split(sep).join("/"));
    expect(readers).toEqual(["lib/site-url.ts"]);
  });
});
