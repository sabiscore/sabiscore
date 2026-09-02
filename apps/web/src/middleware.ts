import { NextResponse, type NextRequest } from "next/server";

/**
 * Per-request CSP with a script-src nonce.
 *
 * Next.js App Router ships its own inline bootstrap/RSC-payload scripts on
 * every page. A static `script-src 'self'` CSP (the previous approach, set
 * via next.config.js `headers()`) has no way to allowlist those — Next.js
 * can only match its own inline scripts to a nonce it reads off the request,
 * which requires a per-request value, which static config can't produce.
 * Without the nonce, every page silently fails to hydrate in any browser
 * that actually enforces the CSP (confirmed via a clean, extension-free
 * headless Chromium run against the production build: hydration never ran,
 * page stayed blank, console showed "Executing inline script violates ...
 * script-src 'self'" for each Next.js-emitted inline script).
 *
 * See: https://nextjs.org/docs/app/guides/content-security-policy
 */
export function middleware(request: NextRequest) {
  const nonce = Buffer.from(crypto.randomUUID()).toString("base64");
  const backendUrl = process.env.SABISCORE_BACKEND_URL || "http://localhost:8000";

  const csp = [
    "default-src 'self'",
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'`,
    // Explicit, not inherited. `worker-src` falls back to `script-src`, and
    // that value carries 'strict-dynamic', which neutralises 'self' — the
    // WEB_PUSH service worker at /sw.js would be blocked with no nonce to give
    // it. Registration failure is silent from the page's perspective, so this
    // has to be stated rather than relied on.
    "worker-src 'self'",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: https://media.api-sports.io https://flagcdn.com",
    "font-src 'self' data:",
    `connect-src 'self' ${backendUrl}`,
    "object-src 'none'",
    "frame-ancestors 'none'",
    "frame-src 'self' https://vercel.live",
    "base-uri 'self'",
    "form-action 'self'",
  ].join("; ");

  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-nonce", nonce);
  requestHeaders.set("Content-Security-Policy", csp);

  const response = NextResponse.next({ request: { headers: requestHeaders } });
  response.headers.set("Content-Security-Policy", csp);
  return response;
}

export const config = {
  matcher: [
    // Skip static assets and image optimization — they don't render HTML
    // that needs a CSP nonce, and excluding them keeps middleware off the
    // hot path for every chunk/font/icon request.
    "/((?!_next/static|_next/image|favicon.ico|apple-icon|icon|manifest.json).*)",
  ],
};
