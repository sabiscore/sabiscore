import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

const originalRevalidateSecret = process.env.REVALIDATE_SECRET;

beforeEach(() => {
  vi.resetModules();
  delete process.env.REVALIDATE_SECRET;
});

afterEach(() => {
  if (originalRevalidateSecret === undefined) {
    delete process.env.REVALIDATE_SECRET;
  } else {
    process.env.REVALIDATE_SECRET = originalRevalidateSecret;
  }
});

describe("/api/revalidate", () => {
  it("fails closed when its shared secret is not configured", async () => {
    const { POST } = await import("./route");
    const response = await POST(
      new NextRequest("http://localhost/api/revalidate", {
        body: JSON.stringify({ secret: "dev-secret-token", path: "/match/example" }),
        method: "POST",
      }),
    );

    expect(response.status).toBe(503);
    await expect(response.json()).resolves.toEqual({
      error: "Revalidation is not configured",
    });
  });
});