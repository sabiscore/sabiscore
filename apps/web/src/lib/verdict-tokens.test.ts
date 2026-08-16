import { describe, expect, it } from "vitest";
import { VERDICT_TOKENS } from "./verdict-tokens";

describe("verdict semantic tokens", () => {
  it("uses first-class semantic Tailwind utilities instead of arbitrary component colors", () => {
    for (const tokens of Object.values(VERDICT_TOKENS)) {
      const classes = `${tokens.color} ${tokens.bg} ${tokens.border} ${tokens.dot}`;
      expect(classes).toMatch(/(?:conviction|signal)-/);
      expect(classes).not.toContain("[hsl(var(--");
      expect(classes).not.toMatch(/#[0-9a-f]{3,8}/i);
    }
  });
});
