import { NextRequest, NextResponse } from "next/server";
import { z } from "zod";

const BACKEND_URL = process.env.SABISCORE_BACKEND_URL;

const BACKEND_TOKEN = process.env.BACKEND_TOKEN;
const BACKEND_DEADLINE_MS = 8_000;

const FixtureIdSchema = z.string().min(1).max(64).regex(/^[a-zA-Z0-9_-]+$/);

export function validateFixtureId(id: string): NextResponse | null {
  const result = FixtureIdSchema.safeParse(id);
  if (!result.success) {
    return NextResponse.json(
      { error: "INVALID_FIXTURE_ID", message: "Fixture ID contains invalid characters." },
      { status: 400, headers: { "Cache-Control": "no-store" } },
    );
  }
  return null;
}

export async function proxyFixtureRequest(
  req: NextRequest,
  backendPath: string,
  init?: { method?: string; body?: string },
): Promise<NextResponse> {
  if (!BACKEND_URL) {
    return NextResponse.json(
      { error: "BACKEND_NOT_CONFIGURED", message: "SABISCORE_BACKEND_URL is not set." },
      { status: 503, headers: { "Cache-Control": "no-store" } },
    );
  }
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (BACKEND_TOKEN) headers.Authorization = `Bearer ${BACKEND_TOKEN}`;

  try {
    const backendRes = await fetch(`${BACKEND_URL}${backendPath}`, {
      method: init?.method ?? req.method,
      headers,
      body: init?.body,
      cache: "no-store",
      signal: AbortSignal.timeout(BACKEND_DEADLINE_MS),
    });
    const data = await backendRes.json().catch(() => null);
    return NextResponse.json(data, {
      status: backendRes.status,
      headers: { "Cache-Control": "no-store" },
    });
  } catch (err: unknown) {
    const name = err instanceof Error ? err.name : "";
    return NextResponse.json(
      {
        status: "UNAVAILABLE",
        data_gap: true,
        reason: name === "TimeoutError" || name === "AbortError"
          ? "backend_deadline_exceeded"
          : "backend_unavailable",
        retryable: true,
        freshness: null,
        provenance: [],
        generated_at: new Date().toISOString(),
        deadline_ms: BACKEND_DEADLINE_MS,
        message: "Could not complete the fixture intelligence request.",
      },
      {
        status: name === "TimeoutError" || name === "AbortError" ? 504 : 503,
        headers: { "Cache-Control": "no-store" },
      },
    );
  }
}
