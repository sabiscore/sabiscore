import { describe, it, expect } from "vitest";
import { analytics, scrubProperties } from "./analytics";

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
