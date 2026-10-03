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
    expect(screen.getByText(/BACKEND_TIMEOUT/)).toBeInTheDocument();
  });

  it("uses no prohibited certainty language", () => {
    const { container } = render(<PredictionCard result={summarizeAnalysis(analysisFixture())} />);
    expect(container.textContent ?? "").not.toMatch(/\b(lock|banker|guaranteed|sure bet|free money)\b/i);
  });
});
