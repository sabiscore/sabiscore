import { NextResponse } from 'next/server';
import { resolveBackendBaseUrl, proxyHeaders, isHtmlBody } from '@/lib/proxy-utils';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/**
 * "No settled predictions yet" is a 200 with `status: METRICS_UNAVAILABLE` in
 * the body (directive v9 L2) — a correct answer, not an outage. Forward the
 * backend's status and body verbatim so the page can say which happened.
 * Synthesizing a shape here previously did two harmful things: it reported a healthy backend as unavailable, and it filled
 * accuracy/CLV/ROI with literal zeros, which read as measurements rather than
 * as absence (INV-01).
 */
function infrastructureError(
  message: string,
  status: number,
  // A request that ran out of time and a host that refused the connection are
  // different facts. This endpoint measures 2.5-3.0s warm against a 5s budget,
  // and Render's free tier has been measured at ~11s on an idle dyno, so a cold
  // start times out routinely -- reporting that as "unreachable" asserts an
  // outage we did not observe. Same principle the keep-alive job already
  // encodes: inability to confirm is not an outage (docs/DEBT.md item 138).
  reason: 'backend_unreachable' | 'backend_timeout' = 'backend_unreachable',
) {
  return NextResponse.json(
    { status: 'METRICS_UNAVAILABLE', reason, error: message },
    { status },
  );
}

export async function GET() {
  try {
    const url = `${resolveBackendBaseUrl()}/api/v1/model-performance/summary`;
    const response = await fetch(url, {
      headers: proxyHeaders(),
      cache: 'no-store',
      signal: AbortSignal.timeout(5000),
    });
    const body = await response.text().catch(() => '');

    if (isHtmlBody(body)) {
      return infrastructureError('Backend service unavailable', 503);
    }

    try {
      return NextResponse.json(JSON.parse(body), { status: response.status });
    } catch {
      return infrastructureError('Unexpected response from backend', 502);
    }
  } catch (error: unknown) {
    const timedOut = error instanceof DOMException && error.name === 'TimeoutError';
    return infrastructureError(
      timedOut
        ? 'Backend performance request timed out'
        : 'Backend performance service unavailable',
      503,
      timedOut ? 'backend_timeout' : 'backend_unreachable',
    );
  }
}
