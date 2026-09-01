/**
 * Server-side team intelligence fetch.
 *
 * Lives apart from `lib/api.ts` for the same reason as `insights-server.ts`:
 * `lib/api.ts` is also bundled for the browser, and a relative URL cannot be
 * fetched from a server component (undici throws `Failed to parse URL from
 * /api/teams/{slug}/intelligence` — reproduced live via `/team/[slug]`, which
 * is `runtime="nodejs"` + `force-dynamic`). This calls the backend directly via
 * the server-only `SABISCORE_BACKEND_URL`, bypassing the self-proxy hop.
 */

import { APIError, type TeamIntelligenceResponse } from "@/lib/api";
import { isHtmlBody, proxyHeaders, resolveBackendBaseUrl, sanitizeBackendError } from "@/lib/proxy-utils";

export async function getTeamIntelligence(
  slug: string,
  options: { history_matches?: number; upcoming_days?: number } = {},
): Promise<TeamIntelligenceResponse> {
  const qs = new URLSearchParams();
  if (options.history_matches !== undefined) qs.set("history_matches", String(options.history_matches));
  if (options.upcoming_days !== undefined) qs.set("upcoming_days", String(options.upcoming_days));
  const url = `${resolveBackendBaseUrl()}/api/v1/teams/${encodeURIComponent(slug)}/intelligence${qs.size ? `?${qs}` : ""}`;

  let response: Response;
  try {
    response = await fetch(url, {
      headers: proxyHeaders(),
      cache: "no-store",
      signal: AbortSignal.timeout(8_000),
    });
  } catch (error) {
    const timedOut =
      error instanceof Error && (error.name === "AbortError" || error.name === "TimeoutError");
    if (timedOut) {
      throw new APIError("Team intelligence request timed out (8s)", 408, "TEAM_INTELLIGENCE_TIMEOUT");
    }
    throw new APIError(error instanceof Error ? error.message : "Network error", 0, "NETWORK_ERROR");
  }

  const bodyText = await response.text().catch(() => "");

  if (!response.ok || isHtmlBody(bodyText)) {
    throw new APIError(
      sanitizeBackendError(bodyText, response.status),
      response.ok ? 503 : response.status,
      "TEAM_INTELLIGENCE_ERROR",
    );
  }

  try {
    return JSON.parse(bodyText) as TeamIntelligenceResponse;
  } catch {
    throw new APIError("Unexpected response from backend", 502, "TEAM_INTELLIGENCE_ERROR");
  }
}
