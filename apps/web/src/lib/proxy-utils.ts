/**
 * Shared utilities for Next.js API proxy routes.
 *
 * Handles the case where the upstream backend (Render free-tier) returns an
 * HTML suspension page instead of JSON — either with status 200 or a 5xx.
 * These helpers prevent raw HTML from leaking into client error messages.
 */

export const BACKEND_TOKEN =
  process.env.BACKEND_TOKEN || "development-token";

/**
 * Resolve the upstream backend base URL from environment variables.
 * Falls back to localhost for local development.
 */
export function resolveBackendBaseUrl(): string {
  const configured = process.env.SABISCORE_BACKEND_URL;
  if (configured && configured.trim().length > 0) {
    return configured.replace(/\/+$/, "");
  }
  return "http://127.0.0.1:8000";
}

/**
 * Return true when the text looks like an HTML page (suspended service,
 * CDN error pages, load-balancer HTML, etc.).
 */
export function isHtmlBody(body: string): boolean {
  const trimmed = body.trimStart().toLowerCase();
  return trimmed.startsWith("<!doctype") || trimmed.startsWith("<html");
}

/**
 * Returns true when the backend URL has not been configured and the proxy
 * is falling back to localhost — useful for surfacing "env var missing" in error reasons.
 */
export function isLocalhostFallback(): boolean {
  const url = resolveBackendBaseUrl();
  return url.startsWith("http://127.0.0.1") || url.startsWith("http://localhost");
}

/**
 * Produce a safe, short error message from a backend response body.
 *
 * - If the body is HTML → returns "Backend service unavailable"
 * - Otherwise strips to ≤ 120 chars
 */
export function sanitizeBackendError(body: string, status: number): string {
  if (isHtmlBody(body)) {
    if (status === 503 || status === 0) return "Backend service unavailable";
    if (status === 200) return "Backend returned an unexpected response (not JSON)";
    return `Backend service unavailable (HTTP ${status})`;
  }
  const trimmed = body.trim();
  return trimmed.length > 120 ? `${trimmed.slice(0, 120)}…` : trimmed || `HTTP ${status}`;
}

/**
 * Cache-Control header for all error responses.
 * Prevents Vercel Edge Network and browsers from caching 4xx/5xx responses.
 */
export const ERROR_CACHE_HEADERS: HeadersInit = {
  "Cache-Control": "no-store",
};

/**
 * Standard headers added to every proxied backend request.
 */
export function proxyHeaders(): HeadersInit {
  return {
    "Content-Type": "application/json",
    Accept: "application/json",
    Authorization: `Bearer ${BACKEND_TOKEN}`,
    "User-Agent": "SabiScore-Proxy/2.0",
  };
}
