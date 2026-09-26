/**
 * Backend Keepalive Cron Job
 *
 * Pings /health/ready on the Render.com backend to prevent cold starts and
 * validate strict per-league model readiness.
 *
 * URL sourced from BACKEND_URL (server-side secret) — never from a public
 * NEXT_PUBLIC_ variable so it cannot be leaked to clients.
 *
 * Impact: Eliminates cold-start delays (5-30s) and provides latency trend data.
 */

import { NextResponse } from 'next/server';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

const TIMEOUT_MS = 30_000;
const PING_PATH = '/health/ready';

function resolveBackendUrl(): string | null {
  // Server-side secret only — never fall back to a public env var.
  const url = (process.env.BACKEND_URL ?? '').trim();
  return url || null;
}

export async function GET() {
  const backendUrl = resolveBackendUrl();

  if (!backendUrl) {
    console.error('[keepalive] BACKEND_URL is not set — cannot ping backend');
    return NextResponse.json(
      {
        status: 'misconfigured',
        error: 'BACKEND_URL env var is required but not set',
        timestamp: new Date().toISOString(),
      },
      { status: 500 },
    );
  }

  const target = backendUrl.replace(/\/$/, '') + PING_PATH;
  const startedAt = Date.now();

  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), TIMEOUT_MS);

    const response = await fetch(target, {
      method: 'GET',
      headers: {
        'User-Agent': 'SabiScore-Keepalive/1.0',
        'X-Keepalive-Ping': 'true',
      },
      signal: controller.signal,
    });

    clearTimeout(timeoutId);
    const latencyMs = Date.now() - startedAt;

    let readinessData: Record<string, unknown> | null = null;
    try {
      readinessData = await response.json();
    } catch {
      // Non-JSON response is acceptable — log the status only.
    }

    const modelsLoaded = Boolean(readinessData?.models_loaded);
    const leaguesLoaded = Array.isArray(readinessData?.leagues_loaded)
      ? (readinessData!.leagues_loaded as string[])
      : [];

    console.log(
      `[keepalive] status=${response.status} latency=${latencyMs}ms models_loaded=${modelsLoaded} leagues=${leaguesLoaded.join(',') || 'unknown'}`,
    );

    return NextResponse.json({
      status: response.ok ? 'ok' : 'degraded',
      latency_ms: latencyMs,
      backend: {
        status_code: response.status,
        models_loaded: modelsLoaded,
        leagues_loaded: leaguesLoaded,
        readiness_status: readinessData?.status ?? null,
        model_error: readinessData?.model_error ?? null,
      },
      timestamp: new Date().toISOString(),
    });
  } catch (error) {
    const latencyMs = Date.now() - startedAt;
    const message = error instanceof Error ? error.message : String(error);
    const timedOut = error instanceof Error && error.name === 'AbortError';

    console.error(
      `[keepalive] error latency=${latencyMs}ms timed_out=${timedOut} message=${message}`,
    );

    return NextResponse.json(
      {
        status: 'error',
        latency_ms: latencyMs,
        timed_out: timedOut,
        error: message,
        timestamp: new Date().toISOString(),
      },
      { status: 500 },
    );
  }
}
