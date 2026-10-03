import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { PredictionCard } from "./PredictionCard";
import type { PredictionResponse } from "@/types/prediction";

const mockPrediction: PredictionResponse = {
  match_id: "11662",
  home_team: "Inter",
  away_team: "AC Milan",
  probabilities: {
    home: 0.55,
    draw: 0.25,
    away: 0.20,
  },
  market: {
    home_odds: 2.10,
    draw_odds: 3.40,
    away_odds: 3.80,
    overround: 1.05,
    bookmaker: "consensus_sharp",
    odds_available: true,
  },
  recommendation: {
    action: "ACTIONABLE",
    best_bet: "home",
    edge: 0.055,
    expected_value: 0.155,
    kelly_fraction: 0.035,
    stake_capped: false,
  },
  telemetry: {
    rolling_xg_home: 1.95,
    rolling_xg_away: 1.20,
    delta_rolling_xg: 0.75,
    source: "redis_cache",
  },
};

describe("PredictionCard (Obsidian Nocturne v2 & Metric Translation)", () => {
  it("translates raw probability tensors into clear consumer English", () => {
    render(<PredictionCard prediction={mockPrediction} />);

    // Verifies translated headline
    const probHeadline = screen.getByTestId("translated-probabilities");
    expect(probHeadline).toHaveTextContent("Home: 55% | Draw: 25% | Away: 20%");

    // Verifies progressbar aria-label
    const progressbar = screen.getByRole("progressbar");
    expect(progressbar).toBeInTheDocument();
    expect(progressbar).toHaveAttribute(
      "aria-label",
      "Win probabilities: Inter 55%, Draw 25%, AC Milan 20%"
    );
  });

  it("displays Emerald Green Actionable Edge recommendation when Kelly > 0 and edge >= 4.2%", () => {
    render(<PredictionCard prediction={mockPrediction} />);

    const actionable = screen.getByTestId("recommendation-actionable");
    expect(actionable).toBeInTheDocument();
    expect(actionable).toHaveTextContent("Actionable Edge: Bet 3.5% of your bankroll.");
    expect(actionable).toHaveTextContent("Inter (Home)");
  });

  it("mutes UI and displays 'No Value: Skip this match' when EV <= 0 or edge is insufficient", () => {
    const noValuePrediction: PredictionResponse = {
      ...mockPrediction,
      recommendation: {
        action: "NO_BET",
        best_bet: "none",
        edge: 0.0,
        expected_value: 0.0,
        kelly_fraction: 0.0,
        stake_capped: false,
      },
    };

    render(<PredictionCard prediction={noValuePrediction} />);

    const muted = screen.getByTestId("recommendation-muted");
    expect(muted).toBeInTheDocument();
    expect(muted).toHaveTextContent("No Value: Skip this match.");
    expect(muted).toHaveTextContent("Safe Abstention");
    expect(screen.queryByTestId("recommendation-actionable")).not.toBeInTheDocument();
  });

  it("displays 'Recent Attacking Form (Last 5 Matches)' and Electric Cyan trend momentum indicator", () => {
    render(<PredictionCard prediction={mockPrediction} />);

    expect(screen.getByText("Recent Attacking Form (Last 5 Matches)")).toBeInTheDocument();

    const trend = screen.getByTestId("xg-trend-indicator");
    expect(trend).toBeInTheDocument();
    expect(trend).toHaveTextContent("▲ +0.75 xG momentum");
    expect(trend).toHaveClass("text-[#00F0FF]");
  });

  it("gracefully falls back with warning when live odds are unavailable", () => {
    render(<PredictionCard prediction={mockPrediction} oddsUnavailable={true} />);

    const banner = screen.getByTestId("odds-unavailable-banner");
    expect(banner).toBeInTheDocument();
    expect(banner).toHaveTextContent("Live odds unavailable. Staking recommendations paused.");

    // Core probabilities are still visible
    expect(screen.getByTestId("translated-probabilities")).toHaveTextContent(
      "Home: 55% | Draw: 25% | Away: 20%"
    );
  });
});
