import { NextResponse } from 'next/server';
import { resolveBackendBaseUrl, proxyHeaders, isHtmlBody } from '@/lib/proxy-utils';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/**
 * "No settled predictions yet" is a 503 the backend answers correctly and on
 * purpose — it is not an outage. Forward its body verbatim so the page can say
 * which of the two happened. Synthesizing a shape here previously did two
 * harmful things: it reported a healthy backend as unavailable, and it filled
 * accuracy/CLV/ROI with literal zeros, which read as measurements rather than
 * as absence (INV-01).
 */
function infrastructureError(message: string, status: number) {
  return NextResponse.json(
    { status: 'METRICS_UNAVAILABLE', reason: 'backend_unreachable', error: message },
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
    return infrastructureError(
      error instanceof DOMException && error.name === 'TimeoutError'
        ? 'Backend performance request timed out'
        : 'Backend performance service unavailable',
      503,
    );
  }
}
