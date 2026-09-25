import { NextRequest, NextResponse } from "next/server";
import { googleClientId, googleClientSecret, googleRedirectUri } from "@/lib/google-oauth";

const STATE_COOKIE = "sabi_google_oauth_state";
const NONCE_COOKIE = "sabi_google_oauth_nonce";
const NEXT_COOKIE = "sabi_google_oauth_next";
const VERIFIER_COOKIE = "sabi_google_oauth_verifier";
const SESSION_COOKIE = "sabi_session";

function safeNextPath(value: string | undefined): string {
  if (!value || !value.startsWith("/") || value.startsWith("//") || value.includes("\\")) {
    return "/dashboard";
  }
  return value.slice(0, 512);
}

function redirectToApp(origin: string, nextPath: string, error?: string) {
  const url = new URL(safeNextPath(nextPath), origin);
  if (error) url.searchParams.set("auth_error", error);
  return NextResponse.redirect(url);
}

async function exchangeCodeForIdToken(code: string, redirectUri: string, codeVerifier: string) {
  const clientId = googleClientId();
  const clientSecret = googleClientSecret();

  if (!clientId || !clientSecret) {
    throw new Error("google_not_configured");
  }

  const body = new URLSearchParams({
    code,
    client_id: clientId,
    client_secret: clientSecret,
    redirect_uri: redirectUri,
    grant_type: "authorization_code",
    code_verifier: codeVerifier,
  });

  const response = await fetch("https://oauth2.googleapis.com/token", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
    cache: "no-store",
    signal: AbortSignal.timeout(10_000),
  });

  if (!response.ok) {
    throw new Error("google_code_exchange_failed");
  }

  const payload = (await response.json()) as { id_token?: string };
  if (!payload.id_token) {
    throw new Error("google_id_token_missing");
  }

  return payload.id_token;
}

export async function GET(request: NextRequest) {
  const stateCookie = request.cookies.get(STATE_COOKIE)?.value;
  const nonceCookie = request.cookies.get(NONCE_COOKIE)?.value;
  const nextPath = safeNextPath(request.cookies.get(NEXT_COOKIE)?.value);
  const codeVerifier = request.cookies.get(VERIFIER_COOKIE)?.value;
  const code = request.nextUrl.searchParams.get("code");
  const returnedState = request.nextUrl.searchParams.get("state");
  const providerError = request.nextUrl.searchParams.get("error");
  const origin = request.nextUrl.origin;

  const clearOAuthCookies = (response: NextResponse) => {
    response.cookies.delete(STATE_COOKIE);
    response.cookies.delete(NONCE_COOKIE);
    response.cookies.delete(NEXT_COOKIE);
    response.cookies.delete(VERIFIER_COOKIE);
    return response;
  };

  if (providerError === "access_denied") {
    return clearOAuthCookies(redirectToApp(origin, nextPath, "google_cancelled"));
  }

  if (!stateCookie || !nonceCookie || !codeVerifier || !returnedState || returnedState !== stateCookie) {
    return clearOAuthCookies(redirectToApp(origin, nextPath, "oauth_state_invalid"));
  }

  if (!code) {
    return clearOAuthCookies(redirectToApp(origin, nextPath, "google_authorization_failed"));
  }

  const redirectUri = googleRedirectUri(origin);

  try {
    const idToken = await exchangeCodeForIdToken(code, redirectUri, codeVerifier);
    const backendUrl = (process.env.SABISCORE_BACKEND_URL || "http://localhost:8000").replace(/\/+$/, "");
    const anonId = request.cookies.get("sabi_anon_id")?.value;

    const backendResponse = await fetch(`${backendUrl}/api/v1/auth/oauth/google`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(anonId ? { "X-Anonymous-Session": anonId } : {}),
      },
      body: JSON.stringify({
        id_token: idToken,
        nonce: nonceCookie,
        remember_me: true,
      }),
      cache: "no-store",
      signal: AbortSignal.timeout(10_000),
    });

    if (!backendResponse.ok) {
      const payload = (await backendResponse.json().catch(() => null)) as { detail?: string } | null;
      const detail = payload?.detail || "google_authentication_failed";
      const error = detail.includes("not configured") ? "google_not_configured" : "google_authentication_failed";
      return clearOAuthCookies(redirectToApp(origin, nextPath, error));
    }

    const payload = (await backendResponse.json()) as {
      access_token?: string;
      expires_in?: number;
    };

    if (!payload.access_token) {
      return clearOAuthCookies(redirectToApp(origin, nextPath, "google_session_failed"));
    }

    const response = redirectToApp(origin, nextPath);
    response.cookies.set(SESSION_COOKIE, payload.access_token, {
      httpOnly: true,
      secure: process.env.NODE_ENV === "production",
      sameSite: "lax",
      path: "/",
      maxAge: Math.max(300, Math.min(payload.expires_in ?? 1_209_600, 1_209_600)),
    });

    return clearOAuthCookies(response);
  } catch (error) {
    const code = error instanceof Error && error.message === "google_not_configured"
      ? "google_not_configured"
      : "google_authentication_failed";
    return clearOAuthCookies(redirectToApp(origin, nextPath, code));
  }
}
