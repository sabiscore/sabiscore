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
// those cookies. Each alias used for sign-in must be registered with Google.
export function googleRedirectUri(origin: string): string {
  return `${origin}/api/auth/google/callback`;
}
