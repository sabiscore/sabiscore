import { afterEach, describe, expect, it, vi } from "vitest";

import {
  APIError,
  analyzeFixture,
  getUpcomingFixtures,
} from "./betting-intelligence-api";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("betting intelligence API contract validation", () => {
  it("rejects malformed successful analyze payloads", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: vi.fn().mockResolvedValue({ verdict: "ACTIONABLE" }),
      } as unknown as Response),
    );

    await expect(analyzeFixture("fixture-1")).rejects.toBeInstanceOf(APIError);
    await expect(analyzeFixture("fixture-1")).rejects.toMatchObject({
      status: 502,
    });
  });

  it("parses valid upcoming fixtures payload", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: vi.fn().mockResolvedValue({
          fixtures: [
            {
              fixture_id: "fd-1",
              competition: "EPL",
              home_team: "Arsenal",
              away_team: "Chelsea",
              kickoff_utc: "2026-08-21T18:00:00Z",
              status: "scheduled",
              evidence_status: "READY",
              odds_status: "READY",
              venue: null,
            },
          ],
          total: 1,
          source: "database",
        }),
      } as unknown as Response),
    );

    const payload = await getUpcomingFixtures("EPL");
    expect(payload.total).toBe(1);
    expect(payload.fixtures[0]?.fixture_id).toBe("fd-1");
  });
});
