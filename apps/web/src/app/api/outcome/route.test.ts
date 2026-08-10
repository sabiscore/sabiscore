import { describe, expect, it } from "vitest";
import { POST, PUT } from "./route";

describe("/api/outcome retirement", () => {
  it.each([POST, PUT])("returns a non-operational retired response", async (handler) => {
    const response = await handler();

    expect(response.status).toBe(410);
    expect(response.headers.get("cache-control")).toBe("no-store");
    await expect(response.json()).resolves.toMatchObject({
      error: "outcome_mutation_retired",
      settlementSource: "backend",
    });
  });
});
