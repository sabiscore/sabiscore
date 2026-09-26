// Server-only Google OAuth settings shared by /api/auth/google/{start,callback}.
//
// The Vercel project carries the Auth.js names (AUTH_GOOGLE_ID/_SECRET); the
// setup doc names GOOGLE_OAUTH_CLIENT_ID/_SECRET. Reading only the second set
// made a configured deployment report "not configured". The documented name
// wins when both are present.
export function googleClientId(): string | undefined {
  return (process.env.GOOGLE_OAUTH_CLIENT_ID || process.env.AUTH_GOOGLE_ID)?.trim() || undefined;
}

export function googleClientSecret(): string | undefined {
  return (process.env.GOOGLE_OAUTH_CLIENT_SECRET || process.env.AUTH_GOOGLE_SECRET)?.trim() || undefined;
}

// The flow must start and finish on the host the visitor is on: the state,
// nonce and PKCE cookies are host-only. VERCEL_URL is the per-deployment host,
// so a visitor on a production alias was sent back to a host that had none of
// those cookies. In production only the canonical host needs registering with
// Google (canonicalSignInOrigin); a preview's own host must be registered to sign in there.
export function googleRedirectUri(origin: string): string {
  return `${origin}/api/auth/google/callback`;
}

// Per-deployment URLs (web-<hash>-…vercel.app) can never be registered, so on a
// production deployment the flow starts on the canonical host (NEXT_PUBLIC_SITE_URL)
// before any cookie is set. Previews and local dev keep their own origin.
export function canonicalSignInOrigin(requestOrigin: string): string | null {
  if (process.env.VERCEL_ENV !== "production") return null;
  try {
    // Compare hosts, not origins: a proxy reporting http:// for the canonical
    // host must not redirect to itself forever.
    const canonical = new URL(process.env.NEXT_PUBLIC_SITE_URL ?? "");
    return canonical.host === new URL(requestOrigin).host ? null : canonical.origin;
  } catch {
    return null;
  }
}
