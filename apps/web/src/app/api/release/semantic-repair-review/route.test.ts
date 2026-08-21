import { afterEach, describe, expect, it, vi } from "vitest";

import { GET } from "./route";

describe("semantic repair review proxy", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("forwards successful JSON without caching it", async () => {
    const payload = {
      read_only: true,
      repair_manifest_sha256: "a".repeat(64),
      production_mutation_authorized: false,
    };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(payload), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const response = await GET();

    expect(response.status).toBe(200);
    expect(response.headers.get("cache-control")).toBe("no-store");
    await expect(response.json()).resolves.toEqual(payload);
    expect(fetchMock).toHaveBeenCalledOnce();
    expect(String(fetchMock.mock.calls[0]?.[0])).toContain(
      "/api/v1/release/semantic-repair-review",
    );
    expect(fetchMock.mock.calls[0]?.[1]).toMatchObject({ cache: "no-store" });
  });

  it("fails closed when the backend returns HTML", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response("<!doctype html><html>upstream error</html>", { status: 200 }),
      ),
    );

    const response = await GET();

    expect(response.status).toBe(502);
    expect(response.headers.get("cache-control")).toBe("no-store");
    await expect(response.json()).resolves.toEqual({
      status: "UNAVAILABLE",
      detail: "Backend returned an unexpected response (not JSON)",
    });
  });

  it("fails closed when the backend cannot be reached", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network")));

    const response = await GET();

    expect(response.status).toBe(503);
    await expect(response.json()).resolves.toEqual({
      status: "UNAVAILABLE",
      detail: "Backend service unavailable",
    });
  });
});
