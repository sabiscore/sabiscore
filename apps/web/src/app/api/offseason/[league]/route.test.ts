import type { NextRequest } from "next/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const ORIGINAL_BACKEND_URL = process.env.SABISCORE_BACKEND_URL;

beforeEach(() => {
  process.env.SABISCORE_BACKEND_URL = "https://backend.test";
  vi.resetModules();
});

afterEach(() => {
  vi.unstubAllGlobals();
  process.env.SABISCORE_BACKEND_URL = ORIGINAL_BACKEND_URL;
});

const req = {} as NextRequest;

async function call(league: string) {
  const { GET } = await import("./route");
  return GET(req, { params: Promise.resolve({ league }) });
}

describe("/api/offseason/[league] normalization", () => {
  it("forwards the display form as a canonical id", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ league: "LA_LIGA", season_status: "OFF_SEASON" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    );
    vi.stubGlobal("fetch", fetchMock);

    await call("La Liga");

    const requested = String((fetchMock.mock.calls[0] as unknown[])?.[0] ?? "");
    expect(requested).toContain("/leagues/LA_LIGA/offseason-status");
    expect(requested).not.toContain("La%20Liga");
  });

  it("never claims a season status for an unsupported league", async () => {
    // Zero-fabrication: an out-of-set league must degrade to UNKNOWN with every
    // availability flag false, not invent an in-season or off-season verdict.
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const response = await call("Championship");
    const body = (await response.json()) as Record<string, unknown>;

    expect(fetchMock).not.toHaveBeenCalled();
    expect(body.season_status).toBe("UNKNOWN");
    expect(Object.values(body.data_availability as Record<string, boolean>)).toEqual(
      expect.arrayContaining([false]),
    );
    expect(Object.values(body.data_availability as Record<string, boolean>)).not.toContain(true);
  });
});
