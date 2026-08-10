import { isHtmlBody, proxyHeaders, resolveBackendBaseUrl } from "@/lib/proxy-utils";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET() {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 8_000);
  try {
    const response = await fetch(`${resolveBackendBaseUrl()}/api/v1/models/status`, {
      signal: controller.signal,
      headers: proxyHeaders(),
      cache: "no-store",
    });
    const text = await response.text();
    if (!response.ok || isHtmlBody(text)) {
      return Response.json(
        { error: "Model status unavailable" },
        { status: response.ok ? 502 : response.status, headers: { "Cache-Control": "no-store" } },
      );
    }
    return new Response(text, {
      status: response.status,
      headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
    });
  } catch (error) {
    const timedOut = error instanceof Error && error.name === "AbortError";
    return Response.json(
      { error: timedOut ? "Model status timed out" : "Model status unreachable" },
      { status: 503, headers: { "Cache-Control": "no-store" } },
    );
  } finally {
    clearTimeout(timeout);
  }
}
