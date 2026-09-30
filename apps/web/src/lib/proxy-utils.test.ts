import { describe, expect, it } from "vitest";
import {
  isHtmlBody,
  proxyHeaders,
  resolveBackendBaseUrl,
  sanitizeBackendError,
} from "./proxy-utils";

describe("proxy-utils", () => {
  describe("proxyHeaders", () => {
    it("returns standard headers when called without arguments", () => {
      const headers = proxyHeaders() as Record<string, string>;
      expect(headers["Content-Type"]).toBe("application/json");
      expect(headers.Accept).toBe("application/json");
      expect(headers.Authorization).toBeDefined();
      expect(headers["User-Agent"]).toBe("SabiScore-Proxy/2.0");
      expect(headers["X-Request-ID"]).toBeUndefined();
      expect(headers.traceparent).toBeUndefined();
    });

    it("propagates X-Request-ID and traceparent from Headers instance", () => {
      const incoming = new Headers({
        "x-request-id": "req-12345",
        traceparent: "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
        tracestate: "rojo=1",
      });

      const headers = proxyHeaders(incoming) as Record<string, string>;
      expect(headers["X-Request-ID"]).toBe("req-12345");
      expect(headers.traceparent).toBe(
        "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
      );
      expect(headers.tracestate).toBe("rojo=1");
    });

    it("propagates headers from a Request object", () => {
      const req = new Request("http://localhost:3000/api/predict", {
        headers: {
          "x-request-id": "client-correlation-id",
          traceparent: "00-traceid-spanid-01",
        },
      });

      const headers = proxyHeaders(req) as Record<string, string>;
      expect(headers["X-Request-ID"]).toBe("client-correlation-id");
      expect(headers.traceparent).toBe("00-traceid-spanid-01");
    });

    it("handles partial mock objects without headers safely", () => {
      const mockReq = { nextUrl: new URL("http://localhost:3000/api/upcoming") };
      const headers = proxyHeaders(mockReq as unknown as Request) as Record<string, string>;
      expect(headers["Content-Type"]).toBe("application/json");
      expect(headers["X-Request-ID"]).toBeUndefined();
    });
  });

  describe("isHtmlBody", () => {
    it("identifies html responses", () => {
      expect(isHtmlBody("<!DOCTYPE html><html><body>Error</body></html>")).toBe(true);
      expect(isHtmlBody("<html><body>Suspended</body></html>")).toBe(true);
      expect(isHtmlBody("   <HTML>")).toBe(true);
      expect(isHtmlBody('{"error": "not_found"}')).toBe(false);
    });
  });

  describe("sanitizeBackendError", () => {
    it("returns safe messages for HTML bodies", () => {
      expect(sanitizeBackendError("<html>Suspended</html>", 503)).toBe(
        "Backend service unavailable"
      );
      expect(sanitizeBackendError("<!doctype html>Error", 200)).toBe(
        "Backend returned an unexpected response (not JSON)"
      );
    });

    it("truncates long non-html error messages", () => {
      const longMessage = "a".repeat(200);
      const sanitized = sanitizeBackendError(longMessage, 500);
      expect(sanitized.length).toBeLessThanOrEqual(122);
      expect(sanitized.endsWith("…")).toBe(true);
    });
  });

  describe("resolveBackendBaseUrl", () => {
    it("strips trailing slashes from configured backend url", () => {
      const prev = process.env.SABISCORE_BACKEND_URL;
      process.env.SABISCORE_BACKEND_URL = "https://api.sabiscore.com///";
      expect(resolveBackendBaseUrl()).toBe("https://api.sabiscore.com");
      process.env.SABISCORE_BACKEND_URL = prev;
    });
  });
});
