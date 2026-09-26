import { describe, it, expect, vi } from "vitest";
import { analytics, scrubProperties } from "./analytics";
import { CONSENT_STORAGE_KEY, CONSENT_VERSION } from "./consent";

describe("First-Party Privacy Analytics", () => {
  it("scrubs sensitive credential keys recursively from event payload", () => {
    const rawPayload = {
      match_id: "arsenal-vs-chelsea",
      user_password: "super_secret_password_123",
      auth_token: "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.dummy", // gitleaks:allow — fake JWT proving the scrubber redacts this shape
      user_email: "test@example.com",
      api_key: "sbk_live_abc123", // gitleaks:allow — fake fixture proving the scrubber redacts this shape
      nested: {
        normal_metric: 42,
        secret_token: "secret_value",
      },
    };

    const scrubbed = scrubProperties(rawPayload) as Record<string, unknown> & { nested: Record<string, unknown> };
    expect(scrubbed.match_id).toBe("arsenal-vs-chelsea");
    expect(scrubbed).not.toHaveProperty("user_password");
    expect(scrubbed).not.toHaveProperty("auth_token");
    expect(scrubbed).not.toHaveProperty("user_email");
    expect(scrubbed).not.toHaveProperty("api_key");
    expect(scrubbed.nested.normal_metric).toBe(42);
    expect(scrubbed.nested).not.toHaveProperty("secret_token");
  });

  it("queues and tracks registered event names safely without throwing", () => {
    expect(() => {
      analytics.track("match_viewed", { fixture_id: "101" });
      analytics.track("prediction_inspected", { model_version: "v5" });
      analytics.track("share_card_generated", { match_id: "101" });
    }).not.toThrow();
  });
});

describe("analytics consent (v11 U14)", () => {
  // Until 2026-09-26 the tracker never read the consent record, so a visitor
  // who chose "Essential Only" was still counted.
  it("sends nothing unless the visitor allowed usage counts", () => {
    const beacon = vi.fn(() => true);
    Object.defineProperty(navigator, "sendBeacon", { value: beacon, configurable: true });

    localStorage.clear();
    analytics.track("match_viewed", { fixture_id: "1" });
    analytics.flush();
    expect(beacon).not.toHaveBeenCalled();

    localStorage.setItem(CONSENT_STORAGE_KEY, JSON.stringify({ version: CONSENT_VERSION, analytics: false }));
    analytics.track("match_viewed", { fixture_id: "1" });
    analytics.flush();
    expect(beacon).not.toHaveBeenCalled();

    localStorage.setItem(CONSENT_STORAGE_KEY, JSON.stringify({ version: CONSENT_VERSION, analytics: true }));
    analytics.track("match_viewed", { fixture_id: "1" });
    analytics.flush();
    expect(beacon).toHaveBeenCalledTimes(1);
    localStorage.clear();
  });
});
