import { describe, it, expect } from "vitest";
import { scrubProperties } from "./analytics";

describe("Adversarial Analytics Scrubbing & PII Redaction", () => {
  it("redacts 15-level deeply nested payload containing passwords, bearer tokens, and API keys", () => {
    const deepPayload = {
      level1: {
        Level2: {
          level3_list: [
            {
              LEVEL4: {
                level5: {
                  level6: [
                    {
                      level7: {
                        level8: {
                          level9: {
                            level10: [
                              {
                                level11: {
                                  level12: {
                                    level13: {
                                      level14: {
                                        user_password: "P@ssw0rdDeepInside!",
                                        api_key: "sbk_live_deep_secret_12345", // gitleaks:allow — fake fixture proving the scrubber redacts this shape
                                        auth_token: "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.token123",
                                        safe_metric: 99.9,
                                        support_email: "admin.team+tier1@corp.sabiscore.co.uk",
                                        raw_jwt: "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c", // gitleaks:allow — fake JWT proving the scrubber redacts this shape
                                      },
                                    },
                                  },
                                },
                              },
                            ],
                          },
                        },
                      },
                    },
                  ],
                },
              },
            },
          ],
        },
      },
      cookie_session: "session_cookie_secret_value",
      nested_arrays: [
        [
          [
            { refresh_token: "rt_secret_token" },
            "plain string message",
          ],
        ],
      ],
    };

    const scrubbed = scrubProperties(deepPayload) as Record<string, unknown>;

    const level1 = scrubbed.level1 as Record<string, unknown>;
    const level2 = level1.Level2 as Record<string, unknown>;
    const level3List = level2.level3_list as Array<Record<string, unknown>>;
    const level4 = level3List[0].LEVEL4 as Record<string, unknown>;
    const level5 = level4.level5 as Record<string, unknown>;
    const level6 = level5.level6 as Array<Record<string, unknown>>;
    const level7 = level6[0].level7 as Record<string, unknown>;
    const level8 = level7.level8 as Record<string, unknown>;
    const level9 = level8.level9 as Record<string, unknown>;
    const level10 = level9.level10 as Array<Record<string, unknown>>;
    const level11 = level10[0].level11 as Record<string, unknown>;
    const level12 = level11.level12 as Record<string, unknown>;
    const level13 = level12.level13 as Record<string, unknown>;
    const leaf = level13.level14 as Record<string, unknown>;

    expect(leaf.safe_metric).toBe(99.9);
    expect(leaf).not.toHaveProperty("user_password");
    expect(leaf).not.toHaveProperty("api_key");
    expect(leaf).not.toHaveProperty("auth_token");
    expect(leaf).not.toHaveProperty("support_email");
    expect(leaf).not.toHaveProperty("raw_jwt");
    expect(scrubbed).not.toHaveProperty("cookie_session");

    const nestedArrays = scrubbed.nested_arrays as Array<Array<Array<Record<string, unknown> | string>>>;
    const innerObj = nestedArrays[0][0][0] as Record<string, unknown>;
    expect(innerObj).not.toHaveProperty("refresh_token");
    expect(nestedArrays[0][0][1]).toBe("plain string message");
  });

  it("safely handles null, undefined, primitives, and empty objects", () => {
    expect(scrubProperties(null)).toBeNull();
    expect(scrubProperties(undefined)).toBeUndefined();
    expect(scrubProperties(42)).toBe(42);
    expect(scrubProperties("safe_text")).toBe("safe_text");
    expect(scrubProperties([])).toEqual([]);
    expect(scrubProperties({})).toEqual({});
  });
});
