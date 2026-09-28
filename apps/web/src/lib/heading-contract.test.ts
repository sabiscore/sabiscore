import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * One <h1> per page (directive v12 U15). The root layout's workspace header was
 * an <h1>, so once pages rendered on the server every page carried two, and the
 * home page three (live 2026-09-27). The layout renders no <h1>; each top-level
 * component in a page module (a page, or one of its variants) renders at most one.
 */
const APP_ROOT = join(process.cwd(), "src", "app");
const H1 = /<h1[\s>]/g;

function pageFiles(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) return pageFiles(path);
    // Error and 404 screens render inside the layout too.
    return /^(page|not-found|error|global-error)\.tsx$/.test(entry.name) ? [path] : [];
  });
}

/** Source split at each top-level function, so page variants count separately. */
function topLevelComponents(source: string): string[] {
  // ponytail: column-0 `function`/`export default function` split; a component
  // declared as a const arrow is not split out, so it counts with its neighbour.
  return source.split(/\n(?=(?:export default )?(?:async )?function )/);
}

describe("heading contract", () => {
  it("the root layout renders no <h1>", () => {
    const layout = readFileSync(join(APP_ROOT, "layout.tsx"), "utf8");
    expect(layout.match(H1)).toBeNull();
  });

  it("no page component renders more than one <h1>", () => {
    const offenders = pageFiles(APP_ROOT).flatMap((path) =>
      topLevelComponents(readFileSync(path, "utf8"))
        .filter((chunk) => (chunk.match(H1) ?? []).length > 1)
        .map(() => path.slice(APP_ROOT.length + 1).replace(/\\/g, "/")),
    );
    expect(offenders).toEqual([]);
  });
});
