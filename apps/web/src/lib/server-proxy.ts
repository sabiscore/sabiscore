import { NextRequest, NextResponse } from "next/server";

const BACKEND_URL = process.env.SABISCORE_BACKEND_URL || "http://localhost:8000";
const BACKEND_DEADLINE_MS = 10_000;

export interface ProxyOptions {
  customHeaders?: Record<string, string>;
  timeoutMs?: number;
}

/**
 * Clean, robust server-side proxy utility forwarding requests from Next.js Route Handlers
 * to the authoritative FastAPI backend at SABISCORE_BACKEND_URL.
 *
 * Preserves HttpOnly cookies (sabi_session, sabi_anon_id), passes forward bearer/api-key auth,
 * and always sets Cache-Control: no-store on proxy responses.
 */
export async function proxyToBackend(
  req: NextRequest,
  backendPath: string,
  options?: ProxyOptions
): Promise<NextResponse> {
  const url = `${BACKEND_URL.replace(/\/+$/, "")}${backendPath.startsWith("/") ? backendPath : `/${backendPath}`}`;

  const headers: Record<string, string> = {};

  // Forward existing content-type if provided
  const contentType = req.headers.get("content-type");
  if (contentType) {
    headers["content-type"] = contentType;
  } else if (req.method !== "GET" && req.method !== "HEAD") {
    headers["content-type"] = "application/json";
  }

  // Forward authorization header if present
  const authHeader = req.headers.get("authorization");
  if (authHeader) {
    headers["authorization"] = authHeader;
  }

  // Forward developer API key header if present
  const apiKeyHeader = req.headers.get("x-api-key");
  if (apiKeyHeader) {
    headers["x-api-key"] = apiKeyHeader;
  }

  // Forward anonymous device id if present in headers or cookies
  const anonHeader = req.headers.get("x-anonymous-id");
  const anonCookie = req.cookies.get("sabi_anon_id")?.value;
  if (anonHeader) {
    headers["x-anonymous-id"] = anonHeader;
  } else if (anonCookie) {
    headers["x-anonymous-id"] = anonCookie;
  }

  // Forward session cookie in cookie header
  const cookieHeader = req.headers.get("cookie");
  if (cookieHeader) {
    headers["cookie"] = cookieHeader;
  } else {
    const sessionCookie = req.cookies.get("sabi_session")?.value;
    const cookiesToForward: string[] = [];
    if (sessionCookie) cookiesToForward.push(`sabi_session=${sessionCookie}`);
    if (anonCookie) cookiesToForward.push(`sabi_anon_id=${anonCookie}`);
    if (cookiesToForward.length > 0) {
      headers["cookie"] = cookiesToForward.join("; ");
    }
  }

  // Apply custom headers override
  if (options?.customHeaders) {
    Object.assign(headers, options.customHeaders);
  }

  // Extract body for non-GET/HEAD methods
  let body: string | undefined = undefined;
  if (req.method !== "GET" && req.method !== "HEAD") {
    try {
      body = await req.text();
    } catch {
      body = undefined;
    }
  }

  const timeoutMs = options?.timeoutMs ?? BACKEND_DEADLINE_MS;

  try {
    const backendRes = await fetch(url, {
      method: req.method,
      headers,
      body: body && body.length > 0 ? body : undefined,
      cache: "no-store",
      signal: AbortSignal.timeout(timeoutMs),
    });

    const responseHeaders = new Headers();
    responseHeaders.set("Cache-Control", "no-store");

    // Forward Set-Cookie headers from backend if present
    const setCookieHeaders = backendRes.headers.getSetCookie?.() || [];
    if (setCookieHeaders.length > 0) {
      for (const cookie of setCookieHeaders) {
        responseHeaders.append("Set-Cookie", cookie);
      }
    } else {
      const singleSetCookie = backendRes.headers.get("set-cookie");
      if (singleSetCookie) {
        responseHeaders.set("Set-Cookie", singleSetCookie);
      }
    }

    // Try to parse JSON response, fallback to text
    const textData = await backendRes.text();
    let jsonData: unknown = null;
    try {
      jsonData = JSON.parse(textData);
    } catch {
      jsonData = null;
    }

    if (jsonData !== null) {
      return NextResponse.json(jsonData, {
        status: backendRes.status,
        headers: responseHeaders,
      });
    }

    return new NextResponse(textData, {
      status: backendRes.status,
      headers: responseHeaders,
    });
  } catch (err: unknown) {
    const name = err instanceof Error ? err.name : "";
    const isTimeout = name === "TimeoutError" || name === "AbortError";
    return NextResponse.json(
      {
        error: isTimeout ? "BACKEND_TIMEOUT" : "BACKEND_UNAVAILABLE",
        message: isTimeout
          ? `Backend deadline of ${timeoutMs}ms exceeded.`
          : "Could not connect to SabiScore backend authority.",
        timestamp: new Date().toISOString(),
      },
      {
        status: isTimeout ? 504 : 503,
        headers: { "Cache-Control": "no-store" },
      }
    );
  }
}
