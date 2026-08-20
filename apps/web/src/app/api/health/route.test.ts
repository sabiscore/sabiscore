import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * A non-ok /health/ready reply is two different events and used to collapse into
 * one word. Render serves an HTML error page for 502/503/504 when no process is
 * running at all; the backend's own readiness failure is a 503 carrying JSON with
 * `status` and `checks`. Reporting the first as "degraded" understated a total
 * outage on every surface that reads backendStatus (banner, readiness ring,
 * platform pills) — observed live on 2026-08-05 while the Render PostgreSQL host
 * had stopped resolving and the API was crash-looping.
 */

const ORIGINAL_BACKEND_URL = process.env.SABISCORE_BACKEND_URL;
const ORIGINAL_VERCEL_GIT_COMMIT_SHA = process.env.VERCEL_GIT_COMMIT_SHA;

beforeEach(() => {
  process.env.SABISCORE_BACKEND_URL = "https://backend.test";
  delete process.env.VERCEL_GIT_COMMIT_SHA;
  vi.resetModules();
});

afterEach(() => {
  vi.unstubAllGlobals();
  process.env.SABISCORE_BACKEND_URL = ORIGINAL_BACKEND_URL;
  if (ORIGINAL_VERCEL_GIT_COMMIT_SHA === undefined) {
    delete process.env.VERCEL_GIT_COMMIT_SHA;
  } else {
    process.env.VERCEL_GIT_COMMIT_SHA = ORIGINAL_VERCEL_GIT_COMMIT_SHA;
  }
});

/** Stubs readiness; ancillary calls return 404 unless a test overrides them. */
function stubReadiness(response: { ok: boolean; status: number; body: string }) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string | URL) => {
      const href = String(url);
      if (href.includes("/health/ready")) {
        return {
          ok: response.ok,
          status: response.status,
          json: async () => JSON.parse(response.body),
          text: async () => response.body,
        };
      }
      return { ok: false, status: 404, json: async () => ({}), text: async () => "" };
    }),
  );
}

async function getHealth() {
  const { GET } = await import("./route");
  return (await (await GET()).json()) as Record<string, unknown>;
}

describe("/api/health backend status discrimination", () => {
  it("reports a platform HTML error page as unavailable, not degraded", async () => {
    stubReadiness({
      ok: false,
      status: 502,
      body: "<!DOCTYPE html>\n<html lang=\"en\"><head><title>502</title></head></html>",
    });

    const body = await getHealth();

    expect(body.backendStatus).toBe("unavailable");
    expect(body.status).toBe("degraded");
  });

  it("keeps a backend-authored 503 as its own reported status, with its diagnostics", async () => {
    stubReadiness({
      ok: false,
      status: 503,
      body: JSON.stringify({
        status: "degraded",
        checks: { database: { status: "ready" }, cache: { status: "down" } },
        capability: { status: "failed" },
      }),
    });

    const body = await getHealth();

    expect(body.backendStatus).toBe("degraded");
    // Previously discarded on every non-ok reply, blanking the readiness ring
    // precisely when it had something to say.
    expect(body.backendChecks).toMatchObject({ cache: { status: "down" } });
    expect(body.backendCapability).toMatchObject({ status: "failed" });
  });

  it("treats an unparseable non-HTML body as unavailable rather than guessing", async () => {
    stubReadiness({ ok: false, status: 503, body: "upstream connect error" });

    const body = await getHealth();

    expect(body.backendStatus).toBe("unavailable");
  });

  it("still passes a healthy readiness payload straight through", async () => {
    stubReadiness({
      ok: true,
      status: 200,
      body: JSON.stringify({
        status: "ok",
        checks: { database: { status: "ready" } },
        capability: { status: "verified" },
      }),
    });

    const body = await getHealth();

    expect(body.backendStatus).toBe("ok");
    expect(body.status).toBe("healthy");
    expect(body.accuracy).toBeNull();
    expect(body.brierScore).toBeNull();
    expect(body.avgEdgePct).toBeNull();
    expect(body.performanceStatus).toBe("PENDING");
  });

  it("surfaces exact backend/Vercel SHAs and canonical readiness capabilities", async () => {
    const sha = "2beb31e0d4ed8c340fa55ea0063af93daae1d4f7";
    process.env.VERCEL_GIT_COMMIT_SHA = sha;
    stubReadiness({
      ok: true,
      status: 200,
      body: JSON.stringify({
        status: "healthy",
        release_sha: sha,
        checks: { database: { status: "healthy" } },
        capabilities: { prediction: "AVAILABLE", stake: "DISABLED" },
      }),
    });

    const body = await getHealth();

    expect(body.backendSha).toBe(sha);
    expect(body.backendCapability).toEqual({ prediction: "AVAILABLE", stake: "DISABLED" });
    expect(body.vercelSha).toBe(sha);
    expect(body.sha).toBe(sha.slice(0, 7));
  });

  it("does not erase healthy readiness when every ancillary endpoint rejects", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string | URL) => {
        const href = String(url);
        if (href.includes("/health/ready")) {
          return {
            ok: true,
            status: 200,
            json: async () => ({}),
            text: async () => JSON.stringify({
              status: "ok",
              release_sha: "abc123",
              checks: { database: { status: "ready" } },
              capability: { status: "research_only" },
            }),
          };
        }
        throw new Error("ancillary endpoint unavailable");
      }),
    );

    const body = await getHealth();

    expect(body.backendStatus).toBe("ok");
    expect(body.status).toBe("healthy");
    expect(body.backendSha).toBe("abc123");
    expect(body.backendChecks).toMatchObject({ database: { status: "ready" } });
    expect(body.providers).toEqual([]);
    expect(body.performanceStatus).toBe("PENDING");
  });
});
