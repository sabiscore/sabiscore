import { afterEach, describe, expect, it, vi } from "vitest";
import { getMatchPrediction } from "./predict";
import { analysisFixture } from "@/lib/prediction-truth.fixture";

function mockFetch(impl: () => Promise<Response>) {
  vi.stubGlobal("fetch", vi.fn(impl));
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("getMatchPrediction (fail-closed server boundary)", () => {
  it("returns an OK summary only from a schema-valid canonical analysis", async () => {
    mockFetch(async () => new Response(JSON.stringify(analysisFixture()), { status: 200 }));
    const result = await getMatchPrediction("Arsenal vs Chelsea", { league: "EPL" });
    expect(result.status).toBe("OK");
  });

  it.each([
    ["timeout", () => Promise.reject(Object.assign(new Error("t"), { name: "TimeoutError" })), "BACKEND_TIMEOUT"],
    ["unreachable", () => Promise.reject(new Error("ECONNREFUSED")), "BACKEND_UNREACHABLE"],
    ["http 503", async () => new Response("down", { status: 503 }), "BACKEND_HTTP_503"],
    ["html", async () => new Response("<!doctype html><html></html>", { status: 200 }), "BACKEND_UNAVAILABLE"],
    ["bad json", async () => new Response("not json", { status: 200 }), "SCHEMA_DRIFT"],
    ["schema drift", async () => new Response(JSON.stringify({ match_id: "x" }), { status: 200 }), "SCHEMA_DRIFT"],
  ])("%s => UNAVAILABLE with no fabricated probabilities", async (_name, impl, code) => {
    mockFetch(impl as () => Promise<Response>);
    const result = await getMatchPrediction("Arsenal vs Chelsea", { league: "EPL" });
    expect(result.status).toBe("UNAVAILABLE");
    expect(result).toMatchObject({ reason_code: code, truth_state: "WITHHELD" });
    expect(JSON.stringify(result)).not.toMatch(/probabilit|0\.45|0\.28|0\.27/);
  });

  it("rejects an unsupported league before any network call", async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    const result = await getMatchPrediction("abc", { league: "NOT_A_LEAGUE" });
    expect(result).toMatchObject({ status: "UNAVAILABLE", reason_code: "INVALID_REQUEST" });
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});
