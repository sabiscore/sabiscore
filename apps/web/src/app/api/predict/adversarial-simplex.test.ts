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

describe("Adversarial Stress Testing of /api/predict Probability Simplex Validation", () => {
  it("rejects non-json request body with HTTP 400", async () => {
    const { POST } = await import("./route");
    const badReq = new Request("https://web.test/api/predict", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "not json at all",
    }) as NextRequest;

    const res = await POST(badReq);
    expect(res.status).toBe(400);
    await expect(res.json()).resolves.toMatchObject({ error: "invalid_request" });
  });

  it("rejects invalid/malformed fixture_id with HTTP 422", async () => {
    const { POST } = await import("./route");
    const invalidIds = ["", "   ", "../escape", "<script>", "id with spaces", "a".repeat(150)];
    for (const matchId of invalidIds) {
      const res = await POST(request({ match_id: matchId }));
      expect(res.status).toBe(422);
      await expect(res.json()).resolves.toMatchObject({ error: "verified_fixture_required" });
    }
  });

  const ADVERSARIAL_NON_SIMPLEX_PAYLOADS = [
    { name: "negative probability", probs: { home: -0.1, draw: 0.6, away: 0.5 } },
    { name: "probability > 1.0", probs: { home: 1.2, draw: -0.1, away: -0.1 } },
    { name: "sum > 1.0 (1.5)", probs: { home: 0.5, draw: 0.5, away: 0.5 } },
    { name: "sum < 1.0 (0.6)", probs: { home: 0.2, draw: 0.2, away: 0.2 } },
    { name: "sum zero", probs: { home: 0.0, draw: 0.0, away: 0.0 } },
    { name: "missing away outcome", probs: { home: 0.5, draw: 0.5 } },
    { name: "null probabilities object", probs: null },
    { name: "string type confusion", probs: { home: "0.5", draw: "0.3", away: "0.2" } },
    { name: "array type confusion", probs: [0.5, 0.3, 0.2] },
    { name: "boolean type confusion", probs: { home: true, draw: false, away: false } },
    { name: "NaN value", probs: { home: NaN, draw: 0.5, away: 0.5 } },
    { name: "Infinity value", probs: { home: Infinity, draw: 0.0, away: 0.0 } },
  ];

  for (const { name, probs } of ADVERSARIAL_NON_SIMPLEX_PAYLOADS) {
    it(`fails closed with HTTP 502 on ${name}`, async () => {
      vi.stubGlobal(
        "fetch",
        vi.fn(async () =>
          new Response(
            JSON.stringify({
              fixture_id: "match-valid-123",
              probabilities: probs,
              verdict: "ACTIONABLE",
            }),
            { status: 200, headers: { "Content-Type": "application/json" } }
          )
        )
      );

      const { POST } = await import("./route");
      const response = await POST(request({ match_id: "match-valid-123" }));

      expect(response.status).toBe(502);
      const json = await response.json();
      expect(json).toMatchObject({
        error: "invalid_probability_simplex",
      });
    });
  }

  it("handles HTML error bodies from backend cold start / cloud proxy with HTTP 503", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response("<html><body>502 Bad Gateway from Nginx</body></html>", {
          status: 502,
          headers: { "Content-Type": "text/html" },
        })
      )
    );

    const { POST } = await import("./route");
    const response = await POST(request({ match_id: "match-valid-123" }));

    expect(response.status).toBe(503);
    await expect(response.json()).resolves.toMatchObject({
      error: "backend_unavailable",
    });
  });

  it("handles backend timeout with HTTP 504", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        const err = new DOMException("The operation was aborted due to timeout", "TimeoutError");
        throw err;
      })
    );

    const { POST } = await import("./route");
    const response = await POST(request({ match_id: "match-valid-123" }));

    expect(response.status).toBe(504);
    await expect(response.json()).resolves.toMatchObject({
      error: "backend_timeout",
    });
  });

  it("preserves authoritative valid probability simplex and metadata", async () => {
    const validPayload = {
      fixture_id: "match-valid-123",
      probabilities: { home: 0.50, draw: 0.30, away: 0.20 },
      verdict: "PARTIAL",
      stake: 0,
      metadata: {
        certification_state: "UNVERIFIED",
      },
    };

    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(JSON.stringify(validPayload), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        })
      )
    );

    const { POST } = await import("./route");
    const response = await POST(request({ match_id: "match-valid-123" }));

    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toEqual(validPayload);
  });
});
