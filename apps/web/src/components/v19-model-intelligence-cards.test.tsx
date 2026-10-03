import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ModelIntelligenceCards } from "./v19-model-intelligence-cards";
import { analysisFixture } from "@/lib/prediction-truth.fixture";

describe("ModelIntelligenceCards truth states", () => {
  it("labels a missing market snapshot as unavailable, never as a liquidity reading", () => {
    const { container } = render(
      <ModelIntelligenceCards data={analysisFixture({ market: null, odds_edge: null })} />,
    );
    const text = container.textContent ?? "";
    expect(text).toContain("UNAVAILABLE");
    expect(text).not.toContain("ILLIQUID");
  });

  it("keeps internal candidate-research notes off the consumer surface", () => {
    const { container } = render(<ModelIntelligenceCards data={analysisFixture()} />);
    expect(container.textContent ?? "").not.toMatch(/Candidate-M|Candidate evidence/);
  });
});
