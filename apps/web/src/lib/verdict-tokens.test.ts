import { describe, expect, it } from "vitest";
import { VERDICT_TOKENS } from "./verdict-tokens";

describe("verdict semantic tokens", () => {
  it("uses repository semantic variables instead of component hex values", () => {
    for (const tokens of Object.values(VERDICT_TOKENS)) {
      const classes = `${tokens.color} ${tokens.bg} ${tokens.border} ${tokens.dot}`;
      expect(classes).toContain("var(--");
      expect(classes).not.toMatch(/#[0-9a-f]{3,8}/i);
    }
  });
});
