import { afterEach, describe, expect, it, vi } from "vitest";
import { getSitemapFixtures } from "./sitemap-fixtures-server";

function jsonResponse(body: unknown, ok = true) {
  return {
    ok,
    status: ok ? 200 : 500,
    text: () => Promise.resolve(JSON.stringify(body)),
  } as unknown as Response;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("getSitemapFixtures", () => {
  it("returns fixtures with a valid id and competition", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse({
          fixtures: [
            { fixture_id: "fd-560566", competition: "EPL" },
            { fixture_id: "fd-558217", competition: "EREDIVISIE" },
          ],
        }),
      ),
    );

    const result = await getSitemapFixtures();

    expect(result).toEqual([
      { fixtureId: "fd-560566", competition: "EPL" },
      { fixtureId: "fd-558217", competition: "EREDIVISIE" },
    ]);
  });

  it("drops entries with an id that fails the fixture-id shape check", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse({
          fixtures: [
            { fixture_id: "fd-560566", competition: "EPL" },
            { fixture_id: "not a valid id!", competition: "EPL" },
            { fixture_id: 12345, competition: "EPL" },
          ],
        }),
      ),
    );

    const result = await getSitemapFixtures();

    expect(result).toEqual([{ fixtureId: "fd-560566", competition: "EPL" }]);
  });

  it("fails closed to an empty list on a network error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network down")));

    expect(await getSitemapFixtures()).toEqual([]);
  });

  it("fails closed to an empty list on a non-ok response", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({}, false)));

    expect(await getSitemapFixtures()).toEqual([]);
  });

  it("fails closed to an empty list on an HTML (suspended-service) body", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        text: () => Promise.resolve("<!DOCTYPE html><html>suspended</html>"),
      } as unknown as Response),
    );

    expect(await getSitemapFixtures()).toEqual([]);
  });

  it("fails closed to an empty list when fixtures is missing or malformed", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ total: 0 })));

    expect(await getSitemapFixtures()).toEqual([]);
  });
});
