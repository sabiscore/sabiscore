import { afterEach, describe, expect, it, vi } from "vitest";

import { GET } from "./route";

vi.mock("@/lib/proxy-utils", () => ({
  resolveBackendBaseUrl: () => "https://backend.test",
  proxyHeaders: () => ({}),
  isHtmlBody: (body: string) => body.trimStart().startsWith("<"),
}));

afterEach(() => {
  vi.restoreAllMocks();
});

/**
 * A request that ran out of time and a host that refused the connection are
 * different facts, and this route is what tells them apart for the page.
 *
 * Live measurement on 2026-09-23: this backend endpoint answers in 2.5-3.0s
 * warm against a 5s budget, and Render's free tier has been measured at ~11s on
 * an idle dyno -- so a cold start times out routinely. Reporting that as
 * "unreachable" asserts an outage nobody observed, which is the same defect
 * class as rendering "0 configured" for a provider list that never arrived
 * (docs/DEBT.md items 136, 138).
 */
describe("GET /api/model-performance/summary", () => {
  it("reports a timeout as backend_timeout, not backend_unreachable", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new DOMException("timed out", "TimeoutError")),
    );

    const response = await GET();
    const body = await response.json();

    expect(response.status).toBe(503);
    expect(body.reason).toBe("backend_timeout");
    expect(body.status).toBe("METRICS_UNAVAILABLE");
  });

  it("still reports a genuine connection failure as backend_unreachable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("fetch failed")));

    const response = await GET();
    const body = await response.json();

    expect(response.status).toBe(503);
    expect(body.reason).toBe("backend_unreachable");
  });

  it("forwards the backend's own body untouched when it answers", async () => {
    // "No settled predictions yet" is a 503 the backend answers on purpose. It
    // must not be rewritten into an infrastructure error, or a healthy backend
    // reads as an outage.
    const payload = { status: "METRICS_UNAVAILABLE", reason: "no_settled_predictions" };
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        status: 503,
        text: async () => JSON.stringify(payload),
      }),
    );

    const response = await GET();
    const body = await response.json();

    expect(body.reason).toBe("no_settled_predictions");
  });
});
