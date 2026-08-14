import { describe, expect, it } from "vitest";
import { edgeQualityLabel } from "@/lib/edge-quality";

// insights-tease-strip.tsx builds its "Edge Quality" tease card's tier text by
// calling edgeQualityLabel() + " quality" — it previously computed its own
// "High Edge"/"Medium Edge"/"Low Edge" tier locally, which dropped "quality"
// and reproduced the exact "% edge" implication @/lib/edge-quality exists to
// prevent (edge_quality_score is a confidence/freshness/completeness
// composite, never a market edge). This pins the tier vocabulary directly at
// its source rather than re-deriving the render logic in a component test.
describe("insights-tease-strip edge-quality tier text", () => {
  it("never produces a bare '{tier} Edge' string", () => {
    for (const score of [0, 0.2, 0.33, 0.5, 0.67, 0.9, 1]) {
      const tier = `${edgeQualityLabel(score)} quality`;
      expect(tier).not.toMatch(/\bedge\b/i);
      expect(tier).toMatch(/quality$/i);
    }
  });
});
