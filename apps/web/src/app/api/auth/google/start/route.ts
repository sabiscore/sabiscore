import { NextRequest, NextResponse } from "next/server";
import { googleClientId, googleRedirectUri } from "@/lib/google-oauth";

const STATE_COOKIE = "sabi_google_oauth_state";
const NONCE_COOKIE = "sabi_google_oauth_nonce";
const NEXT_COOKIE = "sabi_google_oauth_next";
const VERIFIER_COOKIE = "sabi_google_oauth_verifier";
const OAUTH_TTL_SECONDS = 10 * 60;

function safeNextPath(value: string | null): string {
  if (!value) return "/dashboard";
  if (!value.startsWith("/") || value.startsWith("//") || value.includes("\\")) {
    return "/dashboard";
  }
  return value.slice(0, 512);
}

function randomValue(): string {
  return crypto.randomUUID().replace(/-/g, "");
}

function randomBase64Url(byteLength = 32): string {
  const bytes = new Uint8Array(byteLength);
  crypto.getRandomValues(bytes);
  return Buffer.from(bytes).toString("base64url");
}

async function createCodeChallenge(verifier: string): Promise<string> {
  const digest = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(verifier),
  );
  return Buffer.from(digest).toString("base64url");
}

export async function GET(request: NextRequest) {
  const clientId = googleClientId();
  const appUrl = request.nextUrl.origin;

  if (!clientId) {
    const url = new URL(safeNextPath(request.nextUrl.searchParams.get("next")), appUrl);
    url.searchParams.set("auth_error", "google_not_configured");
    return NextResponse.redirect(url);
  }

  const state = randomValue();
  const nonce = randomValue();
  const codeVerifier = randomBase64Url(48);
  const codeChallenge = await createCodeChallenge(codeVerifier);
  const nextPath = safeNextPath(request.nextUrl.searchParams.get("next"));
  const redirectUri = googleRedirectUri(appUrl);

  const googleUrl = new URL("https://accounts.google.com/o/oauth2/v2/auth");
  googleUrl.searchParams.set("client_id", clientId);
  googleUrl.searchParams.set("redirect_uri", redirectUri);
  googleUrl.searchParams.set("response_type", "code");
  googleUrl.searchParams.set("scope", "openid email profile");
  googleUrl.searchParams.set("state", state);
  googleUrl.searchParams.set("nonce", nonce);
  googleUrl.searchParams.set("code_challenge", codeChallenge);
  googleUrl.searchParams.set("code_challenge_method", "S256");
  googleUrl.searchParams.set("prompt", "select_account");
  googleUrl.searchParams.set("include_granted_scopes", "true");

  const response = NextResponse.redirect(googleUrl);
  const secure = process.env.NODE_ENV === "production";
  const cookieBase = {
    httpOnly: true,
    secure,
    sameSite: "lax" as const,
    path: "/",
    maxAge: OAUTH_TTL_SECONDS,
  };

  response.cookies.set(STATE_COOKIE, state, cookieBase);
  response.cookies.set(NONCE_COOKIE, nonce, cookieBase);
  response.cookies.set(NEXT_COOKIE, nextPath, cookieBase);
  response.cookies.set(VERIFIER_COOKIE, codeVerifier, cookieBase);

  return response;
}
