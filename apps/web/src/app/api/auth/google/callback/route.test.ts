import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { GET } from "./route";

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

// Google's token exchange succeeds; the backend answers with `backend`.
function stubFetch(backend: { status: number; body: unknown }) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) =>
      String(url).startsWith("https://oauth2.googleapis.com/token")
        ? new Response(JSON.stringify({ id_token: "google-id-token" }), { status: 200 })
        : new Response(JSON.stringify(backend.body), { status: backend.status }),
    ),
  );
}

function callback() {
  const request = new NextRequest(
    "https://sabiscore.vercel.app/api/auth/google/callback?code=auth-code&state=s1",
  );
  request.cookies.set("sabi_google_oauth_state", "s1");
  request.cookies.set("sabi_google_oauth_nonce", "n1");
  request.cookies.set("sabi_google_oauth_verifier", "v1");
  request.cookies.set("sabi_google_oauth_next", "/dashboard");
  return GET(request);
}

describe("/api/auth/google/callback", () => {
  // Live 2026-09-27: Google redirected back and the code exchange succeeded, then
  // the backend answered 401 twice and the visitor was told to "try again". The
  // likeliest cause, web and backend holding different client IDs, is configuration.
  it("reports a client-ID mismatch as not configured, and logs the backend's reason", async () => {
    vi.stubEnv("AUTH_GOOGLE_ID", "cid");
    vi.stubEnv("AUTH_GOOGLE_SECRET", "secret");
    stubFetch({ status: 401, body: { detail: "Google token audience does not match GOOGLE_OAUTH_CLIENT_ID" } });
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});

    const location = new URL((await callback()).headers.get("location")!);

    expect(location.searchParams.get("auth_error")).toBe("google_not_configured");
    expect(warn).toHaveBeenCalledWith(
      "google_oauth_backend_rejected",
      401,
      "Google token audience does not match GOOGLE_OAUTH_CLIENT_ID",
    );
  });

  it("keeps a genuine verification failure retryable", async () => {
    vi.stubEnv("AUTH_GOOGLE_ID", "cid");
    vi.stubEnv("AUTH_GOOGLE_SECRET", "secret");
    stubFetch({ status: 401, body: { detail: "Google OAuth nonce verification failed" } });
    vi.spyOn(console, "warn").mockImplementation(() => {});

    const location = new URL((await callback()).headers.get("location")!);

    expect(location.searchParams.get("auth_error")).toBe("google_authentication_failed");
  });

  it("sets the session cookie when the backend accepts the token", async () => {
    vi.stubEnv("AUTH_GOOGLE_ID", "cid");
    vi.stubEnv("AUTH_GOOGLE_SECRET", "secret");
    stubFetch({ status: 200, body: { access_token: "jwt", expires_in: 3600 } });

    const response = await callback();

    expect(new URL(response.headers.get("location")!).searchParams.get("auth_error")).toBeNull();
    expect(response.cookies.get("sabi_session")?.value).toBe("jwt");
  });
});
