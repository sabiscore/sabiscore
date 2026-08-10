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

function request(body: unknown): NextRequest {
  return new Request("https://web.test/api/predict", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }) as NextRequest;
}

describe("/api/predict strict fixture proxy", () => {
  it("rejects prediction requests without verified fixture context", async () => {
    const { POST } = await import("./route");
    const response = await POST(request({ home_team: "A", away_team: "B" }));

    expect(response.status).toBe(422);
    await expect(response.json()).resolves.toMatchObject({ error: "verified_fixture_required" });
  });

  it("rejects an invalid backend probability simplex", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
      probabilities: { home: 0.7, draw: 0.3, away: 0.2 },
    }), { status: 200 })));
    const { POST } = await import("./route");
    const response = await POST(request({ match_id: "fixture-123" }));

    expect(response.status).toBe(502);
    await expect(response.json()).resolves.toMatchObject({ error: "invalid_probability_simplex" });
  });

  it("preserves a valid authoritative backend response", async () => {
    const payload = {
      fixture_id: "fixture-123",
      probabilities: { home: 0.5, draw: 0.3, away: 0.2 },
      verdict: "PARTIAL",
      stake: 0,
    };
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(payload), { status: 200 })));
    const { POST } = await import("./route");
    const response = await POST(request({ match_id: "fixture-123" }));

    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toEqual(payload);
  });
});
