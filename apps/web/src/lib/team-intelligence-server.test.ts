import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

describe("team intelligence server-fetch contract", () => {
  it("never fetches a relative URL from the server component", () => {
    const source = readFileSync(join(process.cwd(), "src/lib/team-intelligence-server.ts"), "utf8");
    expect(source).toContain("resolveBackendBaseUrl()");
    expect(source).not.toMatch(/fetch\(`\/api\//);
  });

  it("the team page imports the server-only helper, not lib/api's relative fetch", () => {
    const source = readFileSync(join(process.cwd(), "src/app/team/[slug]/page.tsx"), "utf8");
    expect(source).toContain('from "@/lib/team-intelligence-server"');
  });

  it("lib/api.ts no longer exports a browser-bundled relative-URL team fetch", () => {
    const source = readFileSync(join(process.cwd(), "src/lib/api.ts"), "utf8");
    expect(source).not.toContain("export async function getTeamIntelligence");
  });
});
