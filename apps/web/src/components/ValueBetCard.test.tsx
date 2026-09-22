import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ValueBetCard } from "./ValueBetCard";
import { FeatureFlagProvider } from "@/lib/feature-flags";
import type { ValueBet } from "@/types/value-bet";
import type { MatchActionability } from "@/lib/api";

function renderWithFlags(ui: React.ReactElement) {
  return render(<FeatureFlagProvider>{ui}</FeatureFlagProvider>);
}

describe("ValueBetCard betting safety & default-deny posture (P9)", () => {
  const sampleBet: ValueBet = {
    bet_type: "home_win",
    market_odds: 2.25,
    model_prob: 0.52,
    market_prob: 0.44,
    expected_value: 0.17,
    value_pct: 18.2,
    edge: 0.08,
    kelly_stake: 0.025,
    quality: {
      tier: "VALUE",
      recommendation: "Positive edge with model support",
      quality_score: 0.72,
      ev_contribution: 0.35,
      confidence_contribution: 0.25,
      liquidity_contribution: 0.12,
    },
  };

  const context = {
    matchId: "match-123",
    homeTeam: "Arsenal",
    awayTeam: "Chelsea",
    bookmaker: "Betfair",
  };

  const actionableBlock: MatchActionability = {
    edge_quality_score: 0.65,
    clv_pct: 2.1,
    closing_line_convergence_delta: 0.02,
    suggested_stake_pct: 2.5,
    abstain: false,
    abstain_reason: null,
    top_evidence: ["model_edge"],
    caveats: [],
  };

  const abstainBlock: MatchActionability = {
    edge_quality_score: 0.35,
    clv_pct: null,
    closing_line_convergence_delta: null,
    suggested_stake_pct: 0,
    abstain: true,
    abstain_reason: "High market uncertainty and missing injury reports.",
    top_evidence: [],
    caveats: ["Injuries pending"],
  };

  it("suppresses 'Place Bet' button and staking in default research mode", () => {
    const { container } = renderWithFlags(
      <ValueBetCard bet={sampleBet} context={context} actionability={actionableBlock} />,
    );

    // No wager text/number input fields
    expect(container.querySelectorAll("input")).toHaveLength(0);

    // No Place Bet or Execute Bet buttons
    expect(screen.queryByRole("button", { name: /place bet/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /execute bet/i })).not.toBeInTheDocument();

    // Fallback indicator
    expect(screen.getByText("Staking Disabled")).toBeInTheDocument();
    expect(screen.getAllByText("Disabled").length).toBeGreaterThanOrEqual(1);
  });

  it("suppresses 'Place Bet' button when stakePermitted is explicitly false", () => {
    const { container } = renderWithFlags(
      <ValueBetCard
        bet={sampleBet}
        context={context}
        actionability={actionableBlock}
        stakePermitted={false}
        researchMode={false}
      />,
    );

    expect(container.querySelectorAll("input")).toHaveLength(0);
    expect(screen.queryByRole("button", { name: /place bet/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /execute bet/i })).not.toBeInTheDocument();
    expect(screen.getByText("Staking Disabled")).toBeInTheDocument();
  });

  it("enforces research mode override when researchMode is true", () => {
    const { container } = renderWithFlags(
      <ValueBetCard
        bet={sampleBet}
        context={context}
        actionability={actionableBlock}
        stakePermitted={true}
        researchMode={true}
      />,
    );

    expect(container.querySelectorAll("input")).toHaveLength(0);
    expect(screen.queryByRole("button", { name: /place bet/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /execute bet/i })).not.toBeInTheDocument();
    expect(screen.getByText("Staking Disabled")).toBeInTheDocument();
  });

  it("falls back to 'No bet advised' and 'ABSTAIN' when actionability enforces abstention", () => {
    const { container } = renderWithFlags(
      <ValueBetCard bet={sampleBet} context={context} actionability={abstainBlock} />,
    );

    expect(container.querySelectorAll("input")).toHaveLength(0);
    expect(screen.queryByRole("button", { name: /place bet/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /execute bet/i })).not.toBeInTheDocument();

    expect(screen.getByText("No bet advised")).toBeInTheDocument();
    expect(screen.getByText("ABSTAIN")).toBeInTheDocument();
    expect(screen.getByText(/High market uncertainty and missing injury reports/i)).toBeInTheDocument();
  });

  it("permits bookmaker navigation link only when stakePermitted is true and not in research mode", () => {
    const { container } = renderWithFlags(
      <ValueBetCard
        bet={sampleBet}
        context={context}
        actionability={actionableBlock}
        stakePermitted={true}
        researchMode={false}
      />,
    );

    // Bookmaker link button is present
    expect(screen.getByRole("button", { name: /open betfair to place bet/i })).toBeInTheDocument();

    // Still no text inputs for wager amounts or automated execute buttons
    expect(container.querySelectorAll("input")).toHaveLength(0);
    expect(screen.queryByRole("button", { name: /execute bet/i })).not.toBeInTheDocument();
  });
});
