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

function request(url: string): NextRequest {
  return { nextUrl: new URL(url) } as NextRequest;
}

describe("/api/upcoming route", () => {
  it("uses discovery defaults when include flags are omitted", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(
        JSON.stringify({
          upcoming_matches: [],
          total: 0,
          matches_with_value: 0,
          avg_edge_pct: 0,
          cache_hit: false,
          ttl_seconds: 0,
          source: "cache",
          offseason: false,
          next_season_start: null,
          data_gap: false,
          unavailable_reasons: [],
          generated_at: "2026-08-11T00:00:00.000Z",
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      )
    );
    vi.stubGlobal("fetch", fetchMock);

    const { GET } = await import("./route");
    const response = await GET(request("https://web.test/api/upcoming?limit=8&days_ahead=7"));

    expect(response.status).toBe(200);
    expect(fetchMock).toHaveBeenCalledTimes(1);

    const firstCall = fetchMock.mock.calls[0] as unknown[] | undefined;
    const requestedUrl = String(firstCall?.[0] ?? "");
    const search = new URL(requestedUrl).searchParams;
    expect(search.get("include_predictions")).toBe("false");
    expect(search.get("include_value_bets")).toBe("false");
  });

  it("returns structured 503 when upstream responds non-ok", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify({ detail: "unavailable" }), { status: 503 }))
    );

    const { GET } = await import("./route");
    const response = await GET(request("https://web.test/api/upcoming?limit=8&days_ahead=7"));

    expect(response.status).toBe(503);
    expect(response.headers.get("Cache-Control")).toBe("no-store");

    const body = (await response.json()) as Record<string, unknown>;
    expect(body.data_gap).toBe(true);
    expect(body.retryable).toBe(true);
    expect(body.reason).toBe("backend_service_unavailable");
  });

  it("returns structured 503 when upstream returns HTML body", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response("<!DOCTYPE html><html><body>Service unavailable</body></html>", {
          status: 200,
          headers: { "Content-Type": "text/html" },
        })
      )
    );

    const { GET } = await import("./route");
    const response = await GET(request("https://web.test/api/upcoming?limit=8&days_ahead=7"));

    expect(response.status).toBe(503);
    const body = (await response.json()) as Record<string, unknown>;
    expect(body.reason).toBe("backend_service_unavailable");
    expect(body.retryable).toBe(true);
  });

  it("returns structured 502 with no-store headers on invalid backend JSON", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("not-json", { status: 200, headers: { "Content-Type": "application/json" } })));

    const { GET } = await import("./route");
    const response = await GET(request("https://web.test/api/upcoming?limit=8&days_ahead=7"));

    expect(response.status).toBe(502);
    expect(response.headers.get("Cache-Control")).toBe("no-store");

    const body = (await response.json()) as Record<string, unknown>;
    expect(body.data_gap).toBe(true);
    expect(body.retryable).toBe(true);
    expect(body.reason).toBe("backend_invalid_response");
  });

  it("returns structured 503 on backend timeout/network failure", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new Error("network down");
      })
    );

    const { GET } = await import("./route");
    const response = await GET(request("https://web.test/api/upcoming?limit=8&days_ahead=7"));

    expect(response.status).toBe(503);
    expect(response.headers.get("Cache-Control")).toBe("no-store");

    const body = (await response.json()) as Record<string, unknown>;
    expect(body.reason).toBe("backend_deadline_or_network_failure");
    expect(body.retryable).toBe(true);
  });
});
