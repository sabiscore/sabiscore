import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { GET } from "./route";

afterEach(() => vi.unstubAllEnvs());

const start = () => GET(new NextRequest("https://sabiscore.vercel.app/api/auth/google/start?next=/match"));

describe("/api/auth/google/start", () => {
  it("accepts the Auth.js variable name the Vercel project actually carries", async () => {
    vi.stubEnv("GOOGLE_OAUTH_CLIENT_ID", "");
    vi.stubEnv("AUTH_GOOGLE_ID", "client-from-authjs-name");

    const location = new URL((await start()).headers.get("location")!);

    expect(location.host).toBe("accounts.google.com");
    expect(location.searchParams.get("client_id")).toBe("client-from-authjs-name");
  });

  it("returns to the host the visitor is on, not the per-deployment VERCEL_URL", async () => {
    vi.stubEnv("AUTH_GOOGLE_ID", "cid");
    vi.stubEnv("VERCEL_URL", "web-abc123-oversabis-projects.vercel.app");

    const location = new URL((await start()).headers.get("location")!);

    expect(location.searchParams.get("redirect_uri")).toBe(
      "https://sabiscore.vercel.app/api/auth/google/callback",
    );
  });

  it("reports not-configured on the same host when no client id exists", async () => {
    vi.stubEnv("GOOGLE_OAUTH_CLIENT_ID", "");
    vi.stubEnv("AUTH_GOOGLE_ID", "");

    const location = new URL((await start()).headers.get("location")!);

    expect(location.origin).toBe("https://sabiscore.vercel.app");
    expect(location.searchParams.get("auth_error")).toBe("google_not_configured");
  });
});
