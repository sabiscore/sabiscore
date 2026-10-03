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

  it("uses no prohibited certainty language", () => {
    const { container } = render(<PredictionCard result={summarizeAnalysis(analysisFixture())} />);
    expect(container.textContent ?? "").not.toMatch(/\b(lock|banker|guaranteed|sure bet|free money)\b/i);
  });
});
