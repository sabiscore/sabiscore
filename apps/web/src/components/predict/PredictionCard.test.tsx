import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PredictionCard } from "./PredictionCard";
import { summarizeAnalysis, unavailable } from "@/lib/prediction-truth";
import { analysisFixture } from "@/lib/prediction-truth.fixture";

describe("PredictionCard truth states", () => {
  it("renders backend-computed probabilities with a truth-state badge and withheld staking", () => {
    render(<PredictionCard result={summarizeAnalysis(analysisFixture())} />);
    expect(screen.getByTestId("truth-state-badge")).toHaveTextContent("No Verified Edge");
    expect(screen.getByTestId("translated-probabilities")).toHaveTextContent(
      "Home: 52% | Draw: 26% | Away: 22%",
    );
    expect(screen.getByText("Withheld", { selector: "dd" })).toBeInTheDocument();
    expect(screen.getByText("Recent Attacking Form (Last 5 Matches)")).toBeInTheDocument();
  });

  it("renders no numbers when the backend is unavailable", () => {
    render(<PredictionCard result={unavailable("BACKEND_TIMEOUT", "The backend did not respond in time.")} />);
    expect(screen.getByTestId("truth-state-badge")).toHaveTextContent("Withheld");
    expect(screen.queryByTestId("translated-probabilities")).toBeNull();
    expect(screen.getByTestId("withheld-message")).toHaveTextContent("did not respond");
    // Internal reason codes are for logs, not readers.
    expect(screen.queryByText(/BACKEND_TIMEOUT/)).toBeNull();
  });

  it("never shows raw generation ids, certification enums or gap codes", () => {
    const fixture = analysisFixture();
    fixture.ensemble.certification_state = "UNVERIFIED";
    fixture.evidence_quality.advisory_gaps = ["MODEL_UNCERTAINTY_UNAVAILABLE"];
    const { container } = render(<PredictionCard result={summarizeAnalysis(fixture)} />);
    const text = container.textContent ?? "";
    expect(text).not.toMatch(/v5_phase7|UNVERIFIED|MODEL_UNCERTAINTY_UNAVAILABLE/);
    expect(text).toContain("Generation 5");
    expect(text).toContain("Research mode");
  });

  it("rounds each outcome like the orbs and table, and shows readable verdict and freshness", () => {
    // Live Dortmund-Bremen 2026-10-03: 48.9/24.6/26.5 printed Away 26% beside an orb at 27%.
    const fixture = analysisFixture();
    fixture.ensemble.home_win_prob = 0.489;
    fixture.ensemble.draw_prob = 0.246;
    fixture.ensemble.away_win_prob = 0.265;
    fixture.verdict = "PARTIAL";
    fixture.freshness_tag = "UNKNOWN";
    fixture.staleness_available = false;
    const { container } = render(<PredictionCard result={summarizeAnalysis(fixture)} />);
    expect(screen.getByTestId("translated-probabilities")).toHaveTextContent(
      "Home: 49% | Draw: 25% | Away: 27%",
    );
    const text = container.textContent ?? "";
    expect(text).not.toMatch(/PARTIAL|UNKNOWN/);
    expect(text).toContain("Unknown");
  });

  it("uses no prohibited certainty language", () => {
    const { container } = render(<PredictionCard result={summarizeAnalysis(analysisFixture())} />);
    expect(container.textContent ?? "").not.toMatch(/\b(lock|banker|guaranteed|sure bet|free money)\b/i);
  });
});
