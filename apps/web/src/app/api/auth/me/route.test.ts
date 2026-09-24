import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { GET } from "./route";

afterEach(() => vi.unstubAllGlobals());

describe("/api/auth/me", () => {
  it("answers an anonymous visitor without a backend call or a 401", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const res = await GET(new NextRequest("https://web.test/api/auth/me"));

    expect(res.status).toBe(200);
    expect(await res.json()).toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("forwards a request carrying a session cookie", async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ id: "u1" }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    const req = new NextRequest("https://web.test/api/auth/me", {
      headers: { cookie: "sabi_session=abc" },
    });
    await GET(req);

    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
